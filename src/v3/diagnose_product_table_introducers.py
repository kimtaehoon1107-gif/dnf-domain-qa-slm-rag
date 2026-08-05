from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import write_jsonl
from src.v3.retrieve_v3 import load_runtime_artifacts


DEFAULT_OUTPUT = Path(
    "reports/v3/product_table_introducer_s1_20260805.jsonl"
)
RUNNER_VERSION = "product-table-introducer-s1-v1"
_ITEM_NUMBER = re.compile(r"\d{1,2}[.)]\s*\S.*")


def _line_kind(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "blank"
    if stripped == "[/TABLE]":
        return "table_boundary"
    if stripped.startswith("|") and stripped.endswith("|"):
        return "table_row"
    if stripped.startswith("#"):
        return "heading"
    if stripped.startswith(("※", "*")):
        return "note"
    if _ITEM_NUMBER.fullmatch(stripped):
        return "item_number"
    return "sentence"


def select_table_introducer(
    lines: list[str],
    table_index: int,
    *,
    note_policy: str,
    max_chars: int,
) -> dict[str, Any]:
    if note_policy not in {"stop", "skip"}:
        raise ValueError(f"unsupported note policy: {note_policy}")
    skipped_notes = []
    for index in range(table_index - 1, -1, -1):
        stripped = lines[index].strip()
        kind = _line_kind(stripped)
        if kind == "blank":
            continue
        if kind in {"table_boundary", "table_row", "heading"}:
            return {
                "introducer": "",
                "classification": "none",
                "reason": f"stop_{kind}",
                "source_line_index": None,
                "skipped_notes": skipped_notes,
            }
        if kind == "note":
            if note_policy == "stop":
                return {
                    "introducer": "",
                    "classification": "none",
                    "reason": "stop_note",
                    "source_line_index": None,
                    "skipped_notes": [stripped],
                }
            skipped_notes.append(stripped)
            continue
        if len(stripped) > max_chars:
            return {
                "introducer": "",
                "classification": "none",
                "reason": "too_long",
                "source_line_index": None,
                "skipped_notes": skipped_notes,
                "candidate_length": len(stripped),
            }
        return {
            "introducer": stripped,
            "classification": kind,
            "reason": "selected_previous_nonempty",
            "source_line_index": index,
            "skipped_notes": skipped_notes,
            "candidate_length": len(stripped),
        }
    return {
        "introducer": "",
        "classification": "none",
        "reason": "chunk_start",
        "source_line_index": None,
        "skipped_notes": skipped_notes,
    }


def _review_sample_refs(rows: list[dict[str, Any]]) -> list[str]:
    chosen: list[str] = []

    def take(predicate, count: int) -> None:
        for row in rows:
            if len([ref for ref in chosen if ref]) >= 30:
                return
            if row["table_ref"] in chosen or not predicate(row):
                continue
            chosen.append(row["table_ref"])
            if sum(predicate(item) and item["table_ref"] in chosen for item in rows) >= count:
                return

    take(lambda row: "질풍" in row["source_excerpt"], 1)
    take(lambda row: row["immediate_kind"] == "note", 10)
    take(lambda row: row["skip_policy"]["classification"] == "item_number", 5)
    take(lambda row: row["skip_policy"]["classification"] == "sentence", 10)
    take(lambda row: row["skip_policy"]["classification"] == "none", 4)
    for row in rows:
        if len(chosen) >= 30:
            break
        if row["table_ref"] not in chosen:
            chosen.append(row["table_ref"])
    return chosen[:30]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure table introducer selection without changing runtime"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-chars", type=int, default=200)
    args = parser.parse_args()
    if args.max_chars < 1:
        raise RuntimeError("max-chars must be positive")
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")

    artifacts = load_runtime_artifacts(root)
    rows: list[dict[str, Any]] = []
    table_ordinal = 0
    for chunk_id, chunk in artifacts.chunks_by_id.items():
        source_text = str(chunk.get("display_text") or "")
        lines = source_text.splitlines()
        parent_id = str(chunk.get("parent_document_id") or "")
        document = artifacts.documents_by_id[parent_id]
        for table_index, line in enumerate(lines):
            if line.strip() != "[TABLE]":
                continue
            table_ordinal += 1
            previous_nonempty = next(
                (
                    lines[index].strip()
                    for index in range(table_index - 1, -1, -1)
                    if lines[index].strip()
                ),
                "",
            )
            excerpt_start = max(0, table_index - 6)
            excerpt_end = min(len(lines), table_index + 5)
            rows.append(
                {
                    "type": "table",
                    "table_ref": f"TBL-{table_ordinal}",
                    "source_id": document.get("source_id") or "",
                    "title": document.get("title") or "",
                    "chunk_id": chunk_id,
                    "parent_document_id": parent_id,
                    "heading_path": chunk.get("heading_path") or [],
                    "table_line_index": table_index,
                    "immediate_previous_nonempty": previous_nonempty,
                    "immediate_kind": _line_kind(previous_nonempty),
                    "stop_policy": select_table_introducer(
                        lines,
                        table_index,
                        note_policy="stop",
                        max_chars=args.max_chars,
                    ),
                    "skip_policy": select_table_introducer(
                        lines,
                        table_index,
                        note_policy="skip",
                        max_chars=args.max_chars,
                    ),
                    "source_excerpt": "\n".join(
                        f"{index + 1}: {lines[index]}"
                        for index in range(excerpt_start, excerpt_end)
                    ),
                }
            )

    review_refs = _review_sample_refs(rows)
    review_set = set(review_refs)
    for row in rows:
        row["review_sample"] = row["table_ref"] in review_set
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "qwen_calls": 0,
        "table_count": len(rows),
        "max_chars": args.max_chars,
        "immediate_kind_counts": dict(
            Counter(row["immediate_kind"] for row in rows)
        ),
        "stop_policy_classification_counts": dict(
            Counter(row["stop_policy"]["classification"] for row in rows)
        ),
        "stop_policy_reason_counts": dict(
            Counter(row["stop_policy"]["reason"] for row in rows)
        ),
        "skip_policy_classification_counts": dict(
            Counter(row["skip_policy"]["classification"] for row in rows)
        ),
        "skip_policy_reason_counts": dict(
            Counter(row["skip_policy"]["reason"] for row in rows)
        ),
        "skip_policy_selected_note_count": sum(
            row["skip_policy"]["classification"] == "note" for row in rows
        ),
        "skip_policy_no_introducer_rate": round(
            sum(row["skip_policy"]["classification"] == "none" for row in rows)
            / max(1, len(rows)),
            6,
        ),
        "policy_difference_count": sum(
            row["stop_policy"] != row["skip_policy"] for row in rows
        ),
        "review_sample_refs": review_refs,
    }
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
