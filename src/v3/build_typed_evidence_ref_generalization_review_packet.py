from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import write_jsonl


BUILDER_VERSION = "typed-evidence-ref-generalization-review-packet-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_rows(plan: dict[str, Any], plan_sha256: str) -> list[dict[str, Any]]:
    matrix = plan["slot_matrix"]
    rows = []
    ordinal = 0
    for source_id in matrix["source_ids"]:
        for dimension in matrix["primary_dimensions"]:
            ordinal += 1
            key = f"{plan_sha256}\n{source_id}\n{dimension}"
            slot_id = f"typed_generalization_slot_sha256_{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
            rows.append(
                {
                    "packet_schema_version": BUILDER_VERSION,
                    "plan_sha256": plan_sha256,
                    "slot_id": slot_id,
                    "slot_ordinal": ordinal,
                    "source_id": source_id,
                    "primary_dimension": dimension,
                    "candidate_id": None,
                    "question_text": None,
                    "as_of": None,
                    "time_scope": None,
                    "expected_response_mode": None,
                    "requirements": [],
                    "parent_overlap_exception_reason": None,
                    "author_status": "pending",
                    "author_id": None,
                    "review": {
                        "status": "pending",
                        "reviewer_id": None,
                        "reviewed_at": None,
                        "rationale": None,
                    },
                    "execution_allowed": False,
                    "training_allowed": False,
                    "evaluation_role": "authoring_slot_not_an_evaluation_case",
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "slot_ordinal",
        "slot_id",
        "source_id",
        "primary_dimension",
        "question_text",
        "as_of",
        "time_scope",
        "expected_response_mode",
        "requirements_json",
        "parent_overlap_exception_reason",
        "author_status",
        "author_id",
        "review_status",
        "reviewer_id",
        "reviewed_at",
        "review_rationale",
        "execution_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "slot_ordinal": row["slot_ordinal"],
                    "slot_id": row["slot_id"],
                    "source_id": row["source_id"],
                    "primary_dimension": row["primary_dimension"],
                    "question_text": "",
                    "as_of": "",
                    "time_scope": "",
                    "expected_response_mode": "",
                    "requirements_json": "[]",
                    "parent_overlap_exception_reason": "",
                    "author_status": row["author_status"],
                    "author_id": "",
                    "review_status": row["review"]["status"],
                    "reviewer_id": "",
                    "reviewed_at": "",
                    "review_rationale": "",
                    "execution_allowed": "false",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--jsonl-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    args = parser.parse_args()

    for output in (args.jsonl_output, args.csv_output):
        if output.exists():
            raise RuntimeError(f"output already exists: {output}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    plan_sha256 = _sha256(args.plan)
    rows = build_rows(plan, plan_sha256)
    if len(rows) != plan["target_approved_count"]:
        raise RuntimeError("slot count does not match target_approved_count")

    write_jsonl(args.jsonl_output, rows)
    write_csv(args.csv_output, rows)
    print(
        json.dumps(
            {
                "builder_version": BUILDER_VERSION,
                "row_count": len(rows),
                "plan_sha256": plan_sha256,
                "jsonl_output": args.jsonl_output.as_posix(),
                "jsonl_sha256": _sha256(args.jsonl_output),
                "csv_output": args.csv_output.as_posix(),
                "csv_sha256": _sha256(args.csv_output),
                "execution_allowed_rows": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
