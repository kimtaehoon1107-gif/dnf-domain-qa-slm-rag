from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from io_utils import read_jsonl
from prompt_format import format_prompt_and_completion, format_training_text


DEFAULT_TARGET_MODULES = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"


def validate_raft_rows(rows: list[dict[str, Any]]) -> None:
    required = {"instruction", "question", "documents", "answer"}
    for index, row in enumerate(rows, start=1):
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"Row {index} missing required fields: {missing}")
        if not isinstance(row["documents"], list) or not row["documents"]:
            raise ValueError(f"Row {index} must include non-empty documents list.")


def dry_run(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    texts = [format_training_text(row, args.max_doc_chars) for row in rows]
    answerability_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("answerability", "unknown"))
        answerability_counts[key] = answerability_counts.get(key, 0) + 1

    report = {
        "rows": len(rows),
        "answerability_counts": answerability_counts,
        "avg_training_text_chars": round(mean(len(text) for text in texts), 2),
        "max_training_text_chars": max(len(text) for text in texts),
        "loss_masking": "completion_only_after_### Answer",
        "sample": texts[0] if texts else "",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def train(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Training dependencies are missing. Install them with: pip install -r requirements-train.txt"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization_config = None
    model_kwargs: dict[str, Any] = {"trust_remote_code": True}
    if args.qlora:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16 if args.bf16 else torch.float16,
        )
        model_kwargs.update({"quantization_config": quantization_config, "device_map": "auto"})

    model = AutoModelForCausalLM.from_pretrained(args.model_name, **model_kwargs)
    if args.qlora:
        model = prepare_model_for_kbit_training(model)

    target_modules = [item.strip() for item in args.target_modules.split(",") if item.strip()]
    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    )
    model = get_peft_model(model, lora_config)

    def tokenize_row(row: dict[str, Any]) -> dict[str, list[int]]:
        prompt, completion = format_prompt_and_completion(row, args.max_doc_chars)
        completion = completion + (tokenizer.eos_token or "")
        prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        full = tokenizer(
            prompt + completion,
            add_special_tokens=False,
            truncation=True,
            max_length=args.max_seq_length,
            padding=False,
        )
        labels = list(full["input_ids"])
        prompt_len = min(len(prompt_ids), len(labels))
        labels[:prompt_len] = [-100] * prompt_len
        return {
            "input_ids": full["input_ids"],
            "attention_mask": full["attention_mask"],
            "labels": labels,
        }

    tokenized_rows = [tokenize_row(row) for row in rows]
    tokenized_rows = [row for row in tokenized_rows if any(label != -100 for label in row["labels"])]
    if not tokenized_rows:
        raise ValueError("All rows were truncated before the answer completion. Increase --max-seq-length.")
    skipped_rows = len(rows) - len(tokenized_rows)

    # Hold out a dev slice so train-vs-dev loss divergence (overfitting) is
    # visible during training instead of only after evaluation. v2 trained
    # blind and reached train loss 0.004 on 456 rows with no dev signal.
    dev_rows: list[dict[str, list[int]]] = []
    if args.dev_ratio > 0:
        shuffled = list(tokenized_rows)
        random.Random(args.seed).shuffle(shuffled)
        dev_count = max(1, int(len(shuffled) * args.dev_ratio))
        dev_rows = shuffled[:dev_count]
        tokenized_rows = shuffled[dev_count:]
    tokenized = Dataset.from_list(tokenized_rows)
    dev_dataset = Dataset.from_list(dev_rows) if dev_rows else None

    def collator(features: list[dict[str, list[int]]]) -> dict[str, Any]:
        max_len = max(len(feature["input_ids"]) for feature in features)
        batch = {"input_ids": [], "attention_mask": [], "labels": []}
        for feature in features:
            pad_len = max_len - len(feature["input_ids"])
            batch["input_ids"].append(feature["input_ids"] + [tokenizer.pad_token_id] * pad_len)
            batch["attention_mask"].append(feature["attention_mask"] + [0] * pad_len)
            batch["labels"].append(feature["labels"] + [-100] * pad_len)
        return {key: torch.tensor(value, dtype=torch.long) for key, value in batch.items()}

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        num_train_epochs=args.num_train_epochs,
        learning_rate=args.learning_rate,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=2,
        bf16=args.bf16,
        fp16=args.fp16,
        report_to=[],
        seed=args.seed,
        eval_strategy="steps" if dev_dataset is not None else "no",
        eval_steps=args.eval_steps if dev_dataset is not None else None,
        per_device_eval_batch_size=args.per_device_train_batch_size,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        eval_dataset=dev_dataset,
        data_collator=collator,
    )
    trainer.train()
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    final_dev_loss = None
    if dev_dataset is not None:
        final_dev_loss = trainer.evaluate().get("eval_loss")
    print(
        json.dumps(
            {
                "input_rows": len(rows),
                "trained_rows": len(tokenized_rows),
                "dev_rows": len(dev_rows),
                "final_dev_loss": final_dev_loss,
                "skipped_truncated_rows": skipped_rows,
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune a small model with LoRA/QLoRA on RAFT-style data.")
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--train-file", type=Path, default=Path("data/processed/official_raft_sample.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/slm_lora"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-doc-chars", type=int, default=1200)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--qlora", action="store_true")
    parser.add_argument("--target-modules", default=DEFAULT_TARGET_MODULES)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--num-train-epochs", type=float, default=1.0)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--save-steps", type=int, default=50)
    parser.add_argument("--dev-ratio", type=float, default=0.0)
    parser.add_argument("--eval-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.train_file)
    if args.limit is not None:
        rows = rows[: args.limit]
    validate_raft_rows(rows)

    if args.dry_run:
        dry_run(rows, args)
    else:
        train(rows, args)


if __name__ == "__main__":
    main()
