from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


DECISIONS = {"approve", "rewrite", "reject"}
CORRECTION_FIELDS = {"expected_answer", "gold_answer", "evidence_span"}
REVIEW_CSV_FIELDS = (
    "eval_id",
    "answerability",
    "intent",
    "question",
    "expected_answer",
    "evidence_span",
    "source_title",
    "auto_review_flags",
    "human_decision",
    "rewritten_question",
    "question_natural",
    "evidence_alignment",
    "answerability_correct",
    "expected_answer_correct",
    "review_notes",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def index_unique(rows: list[dict[str, Any]], key: str, source: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key, "")).strip()
        if not value:
            raise ValueError(f"{source} row is missing {key}")
        if value in indexed:
            raise ValueError(f"duplicate {key} in {source}: {value}")
        indexed[value] = row
    return indexed


def apply_reviews(
    candidate_rows: list[dict[str, Any]],
    review_rows: list[dict[str, str]],
    correction_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = index_unique(candidate_rows, "eval_id", "candidate")
    reviews = index_unique(review_rows, "eval_id", "review CSV")
    corrections = index_unique(correction_rows or [], "eval_id", "corrections")

    unknown_reviews = sorted(set(reviews) - set(candidates))
    unknown_corrections = sorted(set(corrections) - set(reviews))
    if unknown_reviews:
        raise ValueError(f"review IDs not found in candidate: {unknown_reviews}")
    if unknown_corrections:
        raise ValueError(f"correction IDs not found in reviewed rows: {unknown_corrections}")

    decision_counts: Counter[str] = Counter()
    output: list[dict[str, Any]] = []
    for source_row in candidate_rows:
        row = dict(source_row)
        eval_id = str(row["eval_id"])
        review = reviews.get(eval_id)
        if review is None:
            output.append(row)
            continue

        decision = str(review.get("human_decision", "")).strip().lower()
        if decision not in DECISIONS:
            raise ValueError(f"invalid human_decision for {eval_id}: {decision!r}")

        rewritten_question = str(review.get("rewritten_question", "")).strip()
        if decision == "rewrite" and not rewritten_question:
            raise ValueError(f"rewrite requires rewritten_question: {eval_id}")
        if decision != "rewrite" and rewritten_question:
            raise ValueError(f"only rewrite may set rewritten_question: {eval_id}")

        if decision == "rewrite":
            row["pre_review_question"] = row.get("question", "")
            row["question"] = rewritten_question

        correction = corrections.get(eval_id, {})
        unexpected_fields = set(correction) - CORRECTION_FIELDS - {"eval_id"}
        if unexpected_fields:
            raise ValueError(f"unsupported correction fields for {eval_id}: {sorted(unexpected_fields)}")
        if decision == "reject" and correction:
            raise ValueError(f"rejected row must not have corrections: {eval_id}")
        for field in CORRECTION_FIELDS:
            if field in correction:
                row[field] = correction[field]

        row["review_status"] = "rejected" if decision == "reject" else "approved"
        row["review_notes"] = str(review.get("review_notes", "")).strip()
        decision_counts[decision] += 1
        output.append(row)

    status_counts = Counter(str(row.get("review_status", "pending")) for row in output)
    label_counts = Counter(
        str(row.get("answerability", ""))
        for row in output
        if row.get("review_status") == "approved"
    )
    return output, {
        "candidate_rows": len(candidate_rows),
        "reviewed_rows": len(review_rows),
        "decision_counts": dict(decision_counts),
        "status_counts": dict(status_counts),
        "approved_answerability_counts": dict(label_counts),
        "correction_rows": len(corrections),
    }


def review_csv_record(row: dict[str, Any]) -> dict[str, str]:
    return {
        "eval_id": str(row.get("eval_id", "")),
        "answerability": str(row.get("answerability", "")),
        "intent": str(row.get("intent", "")),
        "question": str(row.get("question", "")),
        "expected_answer": str(row.get("expected_answer", "")),
        "evidence_span": str(row.get("evidence_span", "")),
        "source_title": str(row.get("source_title", "")),
        "auto_review_flags": "|".join(row.get("auto_review_flags") or []),
        "human_decision": "",
        "rewritten_question": "",
        "question_natural": "",
        "evidence_alignment": "",
        "answerability_correct": "",
        "expected_answer_correct": "",
        "review_notes": "",
    }


def write_pending_review_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    pending = [row for row in rows if row.get("review_status", "pending") == "pending"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(review_csv_record(row) for row in pending)
    return len(pending)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply human blind-test review decisions safely.")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--corrections", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pending-review-csv", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidate_rows = read_jsonl(args.candidate)
    review_rows = read_csv(args.review_csv)
    correction_rows = read_jsonl(args.corrections) if args.corrections else []
    output_rows, summary = apply_reviews(candidate_rows, review_rows, correction_rows)
    write_jsonl(args.output, output_rows)
    summary["output"] = str(args.output)
    if args.pending_review_csv:
        summary["pending_review_rows"] = write_pending_review_csv(
            args.pending_review_csv, output_rows
        )
        summary["pending_review_csv"] = str(args.pending_review_csv)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
