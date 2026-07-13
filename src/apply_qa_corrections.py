from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


def apply_corrections(
    rows: list[dict[str, Any]], corrections: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    corrections_by_id: dict[str, dict[str, Any]] = {}
    for correction in corrections:
        qa_id = str(correction.get("qa_id") or "").strip()
        updates = correction.get("updates")
        if not qa_id or not isinstance(updates, dict):
            raise ValueError("Each correction needs qa_id and an updates object.")
        if qa_id in corrections_by_id:
            raise ValueError(f"Duplicate correction: {qa_id}")
        if "qa_id" in updates:
            raise ValueError(f"Correction cannot change qa_id: {qa_id}")
        corrections_by_id[qa_id] = updates

    row_ids = {str(row.get("qa_id") or "") for row in rows}
    missing = sorted(set(corrections_by_id) - row_ids)
    if missing:
        raise ValueError(f"Corrections reference unknown qa_id values: {missing}")

    result = []
    for row in rows:
        qa_id = str(row.get("qa_id") or "")
        result.append({**row, **corrections_by_id.get(qa_id, {})})
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply audited QA corrections without overwriting the source.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--corrections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_jsonl(args.input)
    corrections = read_jsonl(args.corrections)
    result = apply_corrections(rows, corrections)
    write_jsonl(args.output, result)
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "rows": len(result),
                "corrected_rows": len(corrections),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
