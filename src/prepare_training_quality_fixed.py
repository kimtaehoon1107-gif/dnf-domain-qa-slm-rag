from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from prompt_format import evidence_span_visible


UI_NOISE_HINTS = (
    "휴대전화 번호 확인",
    "취소 계속 사전예약",
    "게임 및 서비스의 유용한 소식",
)


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    values = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        values = [str(row["expected_chunk_id"])]
    return values


def prepare_rows(
    rows: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    max_answer_chars: int,
    max_doc_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    kept = []
    excluded = []
    for row in rows:
        row_id = str(row.get("qa_id") or "<missing-id>")
        answerability = str(row.get("answerability") or "")
        answer = str(row.get("gold_answer") or row.get("expected_answer") or "")
        reasons = []
        if len(answer) > max_answer_chars:
            reasons.append(f"answer_chars={len(answer)}>{max_answer_chars}")
        if any(hint in answer or hint in str(row.get("evidence_span") or "") for hint in UI_NOISE_HINTS):
            reasons.append("ui_noise")

        chunk_ids = expected_chunk_ids(row)
        if answerability != "false" and chunk_ids:
            documents = [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]
            if not evidence_span_visible(
                question=str(row.get("question") or ""),
                documents=documents,
                evidence_span=row.get("evidence_span", ""),
                max_doc_chars=max_doc_chars,
            ):
                reasons.append(f"evidence_not_visible_at_{max_doc_chars}_chars")

        if reasons:
            excluded.append({"qa_id": row_id, "reasons": ",".join(reasons)})
            continue

        copied = dict(row)
        if str(copied.get("source_eval_type") or "") == "partial_diverse_train":
            copied["failure_focus"] = "partial_personal_decision"
        kept.append(copied)
    return kept, excluded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a quality-gated train QA variant without mutating historical data.")
    parser.add_argument("--input", type=Path, default=Path("data/processed/domain_train_qa_expanded.jsonl"))
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/domain_train_qa_measurement_fixed.jsonl"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/domain_train_qa_measurement_fixed.json"),
    )
    parser.add_argument("--max-answer-chars", type=int, default=200)
    parser.add_argument("--max-doc-chars", type=int, default=900)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.input)
    chunks = read_jsonl(args.chunks)
    chunks_by_id = {str(chunk["doc_id"]): chunk for chunk in chunks}
    kept, excluded = prepare_rows(
        rows,
        chunks_by_id=chunks_by_id,
        max_answer_chars=args.max_answer_chars,
        max_doc_chars=args.max_doc_chars,
    )
    write_jsonl(args.output, kept)
    report = {
        "input": str(args.input),
        "output": str(args.output),
        "input_rows": len(rows),
        "output_rows": len(kept),
        "excluded_rows": len(excluded),
        "excluded": excluded,
        "answerability_counts": dict(Counter(str(row.get("answerability")) for row in kept)),
        "max_answer_chars": args.max_answer_chars,
        "max_doc_chars": args.max_doc_chars,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
