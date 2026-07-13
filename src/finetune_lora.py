from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean
from typing import Any

from io_utils import read_jsonl
from prompt_format import format_prompt_and_completion, format_training_text


DEFAULT_TARGET_MODULES = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
MANIFEST_PACKAGES = ("torch", "transformers", "datasets", "peft", "accelerate")


def validate_raft_rows(rows: list[dict[str, Any]]) -> None:
    required = {"instruction", "question", "documents", "answer"}
    for index, row in enumerate(rows, start=1):
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"Row {index} missing required fields: {missing}")
        if not isinstance(row["documents"], list) or not row["documents"]:
            raise ValueError(f"Row {index} must include non-empty documents list.")


def stable_row_fingerprint(row: dict[str, Any]) -> str:
    source_qa_id = str(row.get("source_qa_id") or "").strip()
    if source_qa_id:
        return source_qa_id
    payload = {
        "question": row.get("question", ""),
        "answer": row.get("answer", ""),
        "answerability": row.get("answerability", ""),
        "expected_doc_id": row.get("expected_doc_id", ""),
        "expected_chunk_ids": row.get("expected_chunk_ids", []),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def dev_group_key(row: dict[str, Any], group_by: str) -> str:
    source_key = stable_row_fingerprint(row)
    if group_by == "parent_doc_id":
        parent_id = str(row.get("expected_doc_id") or "").strip()
        if parent_id:
            return f"parent:{parent_id}"
    return f"source:{source_key}"


def split_grouped_rows(
    rows: list[dict[str, Any]],
    dev_ratio: float,
    seed: int,
    group_by: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if dev_ratio <= 0:
        return list(rows), [], {
            "group_by": group_by,
            "input_groups": len({dev_group_key(row, group_by) for row in rows}),
            "train_groups": len({dev_group_key(row, group_by) for row in rows}),
            "dev_groups": 0,
            "group_overlap": 0,
            "dev_duplicate_rows_removed": 0,
        }
    if not 0 < dev_ratio < 1:
        raise ValueError("--dev-ratio must be between 0 and 1.")

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(dev_group_key(row, group_by), []).append(row)

    groups_by_label: dict[str, list[str]] = {}
    for key, members in groups.items():
        label_signature = "+".join(
            sorted({str(member.get("answerability", "unknown")) for member in members})
        )
        groups_by_label.setdefault(label_signature, []).append(key)

    dev_keys: set[str] = set()
    rng = random.Random(seed)
    for label in sorted(groups_by_label):
        keys = sorted(groups_by_label[label])
        rng.shuffle(keys)
        count = max(1, int(len(keys) * dev_ratio)) if len(keys) > 1 else 0
        dev_keys.update(keys[:count])

    train_rows = [row for row in rows if dev_group_key(row, group_by) not in dev_keys]
    # Dev measures every unique source QA in a held-out group. For source-level
    # grouping this keeps one representative of oversampled copies; for parent
    # grouping it preserves distinct QA from the same held-out document.
    dev_rows = []
    dev_source_keys: set[str] = set()
    for key in sorted(dev_keys):
        for row in groups[key]:
            source_key = stable_row_fingerprint(row)
            if source_key in dev_source_keys:
                continue
            dev_source_keys.add(source_key)
            dev_rows.append(row)
    train_keys = {dev_group_key(row, group_by) for row in train_rows}
    dev_group_keys = {dev_group_key(row, group_by) for row in dev_rows}
    overlap = train_keys & dev_group_keys
    if overlap:
        raise RuntimeError(f"Grouped train/dev split leaked {len(overlap)} groups.")

    train_parents = {str(row.get("expected_doc_id")) for row in train_rows if row.get("expected_doc_id")}
    dev_parents = {str(row.get("expected_doc_id")) for row in dev_rows if row.get("expected_doc_id")}
    return train_rows, dev_rows, {
        "group_by": group_by,
        "input_groups": len(groups),
        "train_groups": len(train_keys),
        "dev_groups": len(dev_group_keys),
        "group_overlap": len(overlap),
        "dev_duplicate_rows_removed": sum(len(groups[key]) for key in dev_keys) - len(dev_rows),
        "train_parent_docs": len(train_parents),
        "dev_parent_docs": len(dev_parents),
        "parent_doc_overlap": len(train_parents & dev_parents),
        "dev_group_keys": sorted(dev_group_keys),
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def package_versions() -> dict[str, str]:
    versions = {}
    for package in MANIFEST_PACKAGES:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def serializable_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }


def answerability_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get("answerability", "unknown"))
        counts[label] = counts.get(label, 0) + 1
    return counts


def dry_run(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    train_rows, dev_rows, split_report = split_grouped_rows(
        rows,
        dev_ratio=args.dev_ratio,
        seed=args.seed,
        group_by=args.dev_group_by,
    )
    texts = [format_training_text(row, args.max_doc_chars) for row in train_rows]

    report = {
        "rows": len(rows),
        "train_rows": len(train_rows),
        "dev_rows": len(dev_rows),
        "train_answerability_counts": answerability_counts(train_rows),
        "dev_answerability_counts": answerability_counts(dev_rows),
        "split": split_report,
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

    train_source_rows, dev_source_rows, split_report = split_grouped_rows(
        rows,
        dev_ratio=args.dev_ratio,
        seed=args.seed,
        group_by=args.dev_group_by,
    )

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
    if args.gradient_checkpointing:
        # 8GB laptop GPU: full-chunk gold docs + mid-epoch dev evals OOM
        # without checkpointing (v3 run died at step 35/120).
        model.config.use_cache = False
        model.enable_input_require_grads()

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

    tokenized_train_rows = [tokenize_row(row) for row in train_source_rows]
    tokenized_train_rows = [row for row in tokenized_train_rows if any(label != -100 for label in row["labels"])]
    tokenized_dev_rows = [tokenize_row(row) for row in dev_source_rows]
    tokenized_dev_rows = [row for row in tokenized_dev_rows if any(label != -100 for label in row["labels"])]
    if not tokenized_train_rows:
        raise ValueError("All rows were truncated before the answer completion. Increase --max-seq-length.")
    skipped_train_rows = len(train_source_rows) - len(tokenized_train_rows)
    skipped_dev_rows = len(dev_source_rows) - len(tokenized_dev_rows)

    tokenized = Dataset.from_list(tokenized_train_rows)
    dev_dataset = Dataset.from_list(tokenized_dev_rows) if tokenized_dev_rows else None

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
        gradient_checkpointing=args.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False} if args.gradient_checkpointing else None,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        eval_dataset=dev_dataset,
        data_collator=collator,
    )
    trainer.train(
        resume_from_checkpoint=str(args.resume_from_checkpoint)
        if args.resume_from_checkpoint
        else None
    )
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    final_dev_loss = None
    if dev_dataset is not None:
        final_dev_loss = trainer.evaluate().get("eval_loss")
    manifest = {
        "status": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "train_file": str(args.train_file),
        "train_file_sha256": file_sha256(args.train_file),
        "prompt_instruction_sha256": hashlib.sha256(
            "\n".join(sorted({str(row.get("instruction") or "") for row in rows})).encode("utf-8")
        ).hexdigest(),
        "arguments": serializable_args(args),
        "package_versions": package_versions(),
        "input_rows": len(rows),
        "train_rows": len(tokenized_train_rows),
        "dev_rows": len(tokenized_dev_rows),
        "train_answerability_counts": answerability_counts(train_source_rows),
        "dev_answerability_counts": answerability_counts(dev_source_rows),
        "split": split_report,
        "skipped_train_rows": skipped_train_rows,
        "skipped_dev_rows": skipped_dev_rows,
        "final_dev_loss": final_dev_loss,
        "global_step": trainer.state.global_step,
        "log_history": trainer.state.log_history,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "training_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "input_rows": len(rows),
                "trained_rows": len(tokenized_train_rows),
                "dev_rows": len(tokenized_dev_rows),
                "final_dev_loss": final_dev_loss,
                "skipped_train_rows": skipped_train_rows,
                "skipped_dev_rows": skipped_dev_rows,
                "split_group_overlap": split_report["group_overlap"],
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
    parser.add_argument(
        "--resume-from-checkpoint",
        type=Path,
        help="Resume an interrupted Trainer run from a checkpoint directory.",
    )
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
    parser.add_argument(
        "--dev-group-by",
        choices=("source_qa_id", "parent_doc_id"),
        default="source_qa_id",
        help="Keep oversampled copies together; parent_doc_id also holds out all QA from the same source document.",
    )
    parser.add_argument("--eval-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gradient-checkpointing", action="store_true")
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
