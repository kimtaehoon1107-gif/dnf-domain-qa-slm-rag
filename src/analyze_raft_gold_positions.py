from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl


def document_roles(row: dict[str, Any]) -> list[str]:
    return [str(doc.get("role", "")) for doc in row.get("documents", []) or []]


def first_gold_position(row: dict[str, Any]) -> int | None:
    for index, role in enumerate(document_roles(row), start=1):
        if role == "gold":
            return index
    return None


def analyze_gold_positions(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    citation_rows = [row for row in rows if row.get("citations")]
    answerable_rows = [row for row in rows if str(row.get("answerability", "")).lower() != "false"]
    false_rows = [row for row in rows if str(row.get("answerability", "")).lower() == "false"]

    first_gold_counter: Counter[str] = Counter()
    gold_role_count_counter: Counter[str] = Counter()
    citation_first_gold_counter: Counter[str] = Counter()
    false_gold_rows = []
    answerable_without_gold = []

    for row in rows:
        gold_count = sum(1 for role in document_roles(row) if role == "gold")
        gold_role_count_counter[str(gold_count)] += 1
        position = first_gold_position(row)
        bucket = f"position_{position}" if position is not None else "missing"
        first_gold_counter[bucket] += 1
        if row.get("citations"):
            citation_first_gold_counter[bucket] += 1
        if str(row.get("answerability", "")).lower() == "false" and gold_count:
            false_gold_rows.append(str(row.get("raft_id")))
        if str(row.get("answerability", "")).lower() != "false" and not gold_count:
            answerable_without_gold.append(str(row.get("raft_id")))

    return {
        "raft_file": str(path),
        "rows": len(rows),
        "answerability_counts": dict(Counter(str(row.get("answerability", "")) for row in rows)),
        "citation_rows": len(citation_rows),
        "answerable_or_partial_rows": len(answerable_rows),
        "false_rows": len(false_rows),
        "first_gold_position_distribution_all_rows": dict(sorted(first_gold_counter.items())),
        "first_gold_position_distribution_citation_rows": dict(sorted(citation_first_gold_counter.items())),
        "gold_role_count_distribution": dict(sorted(gold_role_count_counter.items())),
        "citation_rows_with_gold_position_1": citation_first_gold_counter.get("position_1", 0),
        "citation_rows_with_gold_position_1_rate": (
            citation_first_gold_counter.get("position_1", 0) / len(citation_rows)
            if citation_rows
            else None
        ),
        "false_rows_with_gold_role": false_gold_rows[:20],
        "answerable_rows_without_gold_role": answerable_without_gold[:20],
        "false_rows_with_gold_role_count": len(false_gold_rows),
        "answerable_rows_without_gold_role_count": len(answerable_without_gold),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze RAFT gold document position distribution.")
    parser.add_argument("--raft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = analyze_gold_positions(args.raft)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
