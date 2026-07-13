from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from io_utils import read_jsonl


EXTRA_TRUE_IDS = ("domain_eval_0001", "domain_eval_0003", "domain_eval_0004", "domain_eval_0005")


def row_id(row: dict[str, Any]) -> str:
    return str(row.get("eval_id") or row.get("id") or "")


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    values = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        values = [str(row["expected_chunk_id"])]
    return values


def select_source_rows(
    domain_rows: list[dict[str, Any]], fresh_rows: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    selected = [("domain", row) for row in domain_rows if row.get("answerability") == "partial"]
    selected.extend(("fresh_dev", row) for row in fresh_rows if row.get("answerability") == "partial")
    domain_by_id = {row_id(row): row for row in domain_rows}
    missing = [eval_id for eval_id in EXTRA_TRUE_IDS if eval_id not in domain_by_id]
    if missing:
        raise ValueError(f"Missing extra source rows: {missing}")
    selected.extend(("domain_true_anchor", domain_by_id[eval_id]) for eval_id in EXTRA_TRUE_IDS)
    return selected


def make_records(
    selected: list[tuple[str, dict[str, Any]]], chunks_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, (source_set, row) in enumerate(selected, start=1):
        chunk_ids = expected_chunk_ids(row)
        if not chunk_ids or chunk_ids[0] not in chunks_by_id:
            raise ValueError(f"Missing source chunk for {row_id(row)}")
        chunk = chunks_by_id[chunk_ids[0]]
        records.append(
            {
                "candidate_id": f"partial_dev_human_{index:04d}",
                "source_set": source_set,
                "source_row_id": row_id(row),
                "expected_doc_id": row.get("expected_doc_id", ""),
                "expected_chunk_ids": "|".join(chunk_ids),
                "title": chunk.get("title", ""),
                "evidence_span": row.get("evidence_span", ""),
                "seed_question": row.get("question", ""),
                "seed_gold_answer": row.get("gold_answer") or row.get("expected_answer") or "",
                "writing_requirement": (
                    "근거로 답할 수 있는 사실과 사용자 상황 없이는 확정할 수 없는 개인 판단을 "
                    "자연스러운 구어체 한 문장에 함께 물어볼 것"
                ),
                "human_question": "",
                "human_gold_answer": "",
                "human_decision": "",
                "review_notes": "",
            }
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a human-authored partial-development review sheet.")
    parser.add_argument("--domain-eval", type=Path, default=Path("data/processed/domain_eval_set_expanded.jsonl"))
    parser.add_argument("--fresh-dev", type=Path, default=Path("data/processed/fresh_paraphrase_eval_set.jsonl"))
    parser.add_argument("--docs", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/partial_dev_human_review_20.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    domain_rows = read_jsonl(args.domain_eval)
    fresh_rows = read_jsonl(args.fresh_dev)
    chunks = read_jsonl(args.docs)
    chunks_by_id = {str(row["doc_id"]): row for row in chunks}
    selected = select_source_rows(domain_rows, fresh_rows)
    records = make_records(selected, chunks_by_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(records),
                "source_counts": {
                    source: sum(1 for value, _ in selected if value == source)
                    for source in sorted({value for value, _ in selected})
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
