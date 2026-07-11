from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from prompt_format import RAG_INSTRUCTIONS, evidence_span_visible, format_prompt, instruction_for_mode
from run_tuned_slm_smoke import generate_answer, load_tuned_model, parse_generated_fields, setup_determinism


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    values = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        values = [str(row["expected_chunk_id"])]
    return values


def oracle_documents(
    row: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
    oracle_mode: str,
) -> list[dict[str, str]]:
    documents = []
    for chunk_id in expected_chunk_ids(row):
        chunk = chunks_by_id.get(chunk_id)
        if not chunk:
            continue
        if oracle_mode == "span":
            text = str(row.get("evidence_span") or chunk.get("text", ""))
        elif oracle_mode == "chunk":
            text = str(chunk.get("text", ""))
        else:
            raise ValueError(f"Unknown oracle_mode: {oracle_mode}")
        documents.append(
            {
                "doc_id": str(chunk["doc_id"]),
                "role": "retrieved",
                "title": str(chunk.get("title", "")),
                "text": text,
            }
        )
    return documents


def citation_sets(row: dict[str, Any]) -> tuple[set[str], set[str]]:
    expected = {str(item) for item in row.get("expected_chunk_ids", []) if item}
    predicted = {str(item) for item in row.get("parsed_citations", []) or [] if item}
    return expected, predicted


def citation_precision(row: dict[str, Any]) -> float:
    expected, predicted = citation_sets(row)
    if not predicted:
        return 0.0
    return len(expected & predicted) / len(predicted)


def citation_recall(row: dict[str, Any]) -> float:
    expected, predicted = citation_sets(row)
    if not expected:
        return 0.0
    return len(expected & predicted) / len(expected)


def run_oracle(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.eval_set)[: args.limit]
    chunks = read_jsonl(args.chunks)
    chunks_by_id = {str(chunk["doc_id"]): chunk for chunk in chunks}

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for tuned-SLM oracle evaluation.") from exc

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    setup_determinism(torch, seed=args.seed, deterministic=args.deterministic)
    torch_module, tokenizer, model = load_tuned_model(args.model_name, args.adapter_dir, device, args.fp16)

    details = []
    start = time.perf_counter()
    for row in rows:
        documents = oracle_documents(row, chunks_by_id, oracle_mode=args.oracle_mode)
        prompt = format_prompt(
            question=row["question"],
            documents=documents,
            max_doc_chars=args.max_doc_chars,
            instruction=instruction_for_mode(args.instruction_mode),
        )
        row_start = time.perf_counter()
        answer = generate_answer(
            torch_module=torch_module,
            tokenizer=tokenizer,
            model=model,
            prompt=prompt,
            max_new_tokens=args.max_new_tokens,
        )
        parsed = parse_generated_fields(answer)
        expected_chunks = expected_chunk_ids(row)
        parsed_citations = set(parsed["parsed_citations"])
        expected_chunk_set = set(expected_chunks)
        oracle_visible = (
            evidence_span_visible(
                question=row["question"],
                documents=documents,
                evidence_span=row.get("evidence_span", ""),
                max_doc_chars=args.max_doc_chars,
            )
            if expected_chunks
            else True
        )
        detail = {
            "eval_id": row.get("eval_id"),
            "question": row["question"],
            "expected_answerability": row.get("answerability"),
            "expected_chunk_ids": expected_chunks,
            "oracle_chunk_ids": [doc["doc_id"] for doc in documents],
            "oracle_has_gold": bool(documents) if expected_chunks else True,
            "oracle_has_visible_gold": oracle_visible,
            "generated_answer": answer,
            "latency_sec": round(time.perf_counter() - row_start, 3),
        }
        detail.update(parsed)
        detail["parsed_citation_hit"] = bool(expected_chunk_set & parsed_citations)
        details.append(detail)

    answerability_correct = [
        row.get("parsed_answerability") == str(row.get("expected_answerability") or "").lower()
        for row in details
    ]
    answerability_by_label: dict[str, dict[str, int | float]] = {}
    for row, is_correct in zip(details, answerability_correct, strict=True):
        label = str(row.get("expected_answerability") or "")
        stats = answerability_by_label.setdefault(label, {"correct": 0, "total": 0, "accuracy": 0.0})
        stats["total"] = int(stats["total"]) + 1
        if is_correct:
            stats["correct"] = int(stats["correct"]) + 1
    for stats in answerability_by_label.values():
        total = int(stats["total"])
        stats["accuracy"] = int(stats["correct"]) / total if total else 0.0

    answerable = [row for row in details if row["expected_chunk_ids"]]
    exact_citation = [row for row in answerable if row["parsed_citation_hit"]]
    label_and_citation = [
        row
        for row in answerable
        if row.get("parsed_answerability") == str(row.get("expected_answerability") or "").lower()
        and row["parsed_citation_hit"]
    ]
    exact_set_match = [row for row in answerable if citation_sets(row)[0] == citation_sets(row)[1]]
    precision_sum = sum(citation_precision(row) for row in answerable)
    recall_sum = sum(citation_recall(row) for row in answerable)
    answer_chars = [row["parsed_answer_chars"] for row in details if row["has_answer_field"]]

    return {
        "report_schema_version": 2,
        "model_name": args.model_name,
        "adapter_dir": str(args.adapter_dir),
        "eval_set": str(args.eval_set),
        "chunks": str(args.chunks),
        "oracle_mode": args.oracle_mode,
        "max_doc_chars": args.max_doc_chars,
        "max_new_tokens": args.max_new_tokens,
        "instruction_mode": args.instruction_mode,
        "seed": args.seed,
        "deterministic": args.deterministic,
        "device": device,
        "rows": len(details),
        "total_runtime_sec": round(time.perf_counter() - start, 3),
        "summary": {
            "answerability_accuracy": sum(answerability_correct) / len(answerability_correct) if answerability_correct else 0.0,
            "answerability_by_label": answerability_by_label,
            "answerable_rows": len(answerable),
            "oracle_gold_context_rate": (
                sum(1 for row in answerable if row["oracle_has_gold"]) / len(answerable)
                if answerable
                else None
            ),
            "oracle_visible_gold_rate": (
                sum(1 for row in answerable if row["oracle_has_visible_gold"]) / len(answerable)
                if answerable
                else None
            ),
            "exact_citation_on_answerable": len(exact_citation) / len(answerable) if answerable else None,
            "answerability_and_exact_citation_on_answerable": (
                len(label_and_citation) / len(answerable) if answerable else None
            ),
            "citation_precision_macro": precision_sum / len(answerable) if answerable else None,
            "citation_recall_macro": recall_sum / len(answerable) if answerable else None,
            "citation_exact_set_match": len(exact_set_match) / len(answerable) if answerable else None,
            "avg_answer_chars": round(sum(answer_chars) / len(answer_chars), 1) if answer_chars else 0.0,
        },
        "details": details,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run tuned-SLM with gold-only oracle context.")
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oracle-mode", choices=("span", "chunk"), default="span")
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--max-doc-chars", type=int, default=500)
    parser.add_argument("--max-new-tokens", type=int, default=160)
    parser.add_argument("--instruction-mode", choices=tuple(RAG_INSTRUCTIONS), default="legacy")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deterministic", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = run_oracle(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in report.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
