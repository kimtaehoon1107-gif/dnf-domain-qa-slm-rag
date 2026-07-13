from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from io_utils import read_jsonl


LABEL_QUOTAS = {"true": 15, "partial": 5, "false": 10}


def max_recall(row: dict[str, Any]) -> float:
    return max(
        (float(item.get("evidence_token_recall") or 0.0) for item in row.get("hard_negatives") or []),
        default=0.0,
    )


def select_rows(
    rows: list[dict[str, Any]],
    qa_by_id: dict[str, dict[str, Any]],
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    for label, quota in LABEL_QUOTAS.items():
        bucket = [row for row in rows if str(row.get("answerability")) == label]
        if label != "false":
            high_risk_count = max(1, (quota * 2) // 3)
            ranked = sorted(bucket, key=lambda row: (-max_recall(row), str(row.get("source_qa_id"))))
            chosen = ranked[:high_risk_count]
            remainder = ranked[high_risk_count:]
            chosen.extend(rng.sample(remainder, min(quota - len(chosen), len(remainder))))
        else:
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in bucket:
                qa = qa_by_id.get(str(row.get("source_qa_id")), {})
                groups[str(qa.get("intent") or qa.get("source_eval_type") or "unknown")].append(row)
            for group in groups.values():
                group.sort(key=lambda row: str(row.get("source_qa_id")))
            chosen = []
            names = sorted(groups)
            while len(chosen) < quota and any(groups.values()):
                for name in names:
                    if groups[name] and len(chosen) < quota:
                        chosen.append(groups[name].pop(0))
        if len(chosen) != quota:
            raise RuntimeError(f"Unable to sample {quota} {label} rows; got {len(chosen)}")
        selected.extend(chosen)
    return selected


def select_requested_rows(
    rows: list[dict[str, Any]], source_qa_ids: list[str]
) -> list[dict[str, Any]]:
    rows_by_id = {str(row.get("source_qa_id") or ""): row for row in rows}
    missing = [source_qa_id for source_qa_id in source_qa_ids if source_qa_id not in rows_by_id]
    if missing:
        raise ValueError(f"Unknown source_qa_id values: {missing}")
    return [rows_by_id[source_qa_id] for source_qa_id in source_qa_ids]


def record(
    row: dict[str, Any],
    qa_by_id: dict[str, dict[str, Any]],
    docs_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    qa = qa_by_id.get(str(row.get("source_qa_id")), {})
    negatives = list(row.get("hard_negatives") or [])
    result: dict[str, Any] = {
        "source_qa_id": row.get("source_qa_id", ""),
        "answerability": row.get("answerability", ""),
        "intent": qa.get("intent", ""),
        "source_eval_type": qa.get("source_eval_type", ""),
        "question": row.get("question", ""),
        "gold_answer": qa.get("gold_answer") or qa.get("expected_answer") or "",
        "evidence_span": qa.get("evidence_span", ""),
        "max_evidence_token_recall": max_recall(row),
        "risk_reason": (
            "near_answer_overlap"
            if max_recall(row) >= 0.3
            else "false_label_context_check"
            if row.get("answerability") == "false"
            else "stratified_control"
        ),
    }
    for index in range(3):
        item = negatives[index] if index < len(negatives) else {}
        doc = docs_by_id.get(str(item.get("doc_id", "")), {})
        suffix = index + 1
        result[f"negative_{suffix}_doc_id"] = item.get("doc_id", "")
        result[f"negative_{suffix}_title"] = item.get("title") or doc.get("title", "")
        result[f"negative_{suffix}_text"] = doc.get("text", "")
        result[f"negative_{suffix}_selection_tier"] = item.get("selection_tier", "")
        result[f"negative_{suffix}_rerank_score"] = item.get("rerank_score", "")
        result[f"negative_{suffix}_evidence_recall"] = item.get("evidence_token_recall", "")
        result[f"negative_{suffix}_valid_non_answer"] = ""
    result["human_decision"] = ""
    result["review_notes"] = ""
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a stratified hard-negative human review sheet.")
    parser.add_argument("--hard-negatives", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--docs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--source-qa-ids",
        nargs="*",
        help="Optional explicit QA IDs for a targeted follow-up review instead of stratified sampling.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.hard_negatives)
    qa_rows = read_jsonl(args.qa)
    docs = read_jsonl(args.docs)
    qa_by_id = {str(row.get("qa_id") or row.get("eval_id")): row for row in qa_rows}
    docs_by_id = {str(row["doc_id"]): row for row in docs}
    selected = (
        select_requested_rows(rows, args.source_qa_ids)
        if args.source_qa_ids
        else select_rows(rows, qa_by_id, seed=args.seed)
    )
    records = [record(row, qa_by_id, docs_by_id) for row in selected]
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
                "answerability_counts": dict(Counter(row["answerability"] for row in records)),
                "risk_reason_counts": dict(Counter(row["risk_reason"] for row in records)),
                "max_evidence_token_recall": max(row["max_evidence_token_recall"] for row in records),
                "seed": args.seed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
