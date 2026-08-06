from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl


ADJUDICATOR_VERSION = "product-free-rag-a6-human-adjudicator-v1"
TRUE_VALUES = {"1", "true", "y", "yes", "맞음", "예"}
FALSE_VALUES = {"0", "false", "n", "no", "아님", "아니오"}
REVIEW_FIELDS = (
    "human_semantic_correct",
    "human_false_full",
    "human_unsupported_overclaim",
    "adjudication_complete",
    "reviewer_id",
    "reviewed_at",
    "review_rationale",
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expected_mode(row: dict[str, Any]) -> str:
    return {
        "full_answer": "answer",
        "partial_answer": "partial",
        "clarification": "clarification",
        "abstain": "unsupported",
    }[row["expected_response_mode"]]


def _load_run(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = list(read_jsonl(path))
    summaries = [row for row in rows if row.get("type") == "summary"]
    records = [row for row in rows if row.get("type") in {"case", "error"}]
    if len(summaries) != 1 or len(records) != 32:
        raise RuntimeError("one-shot output must contain 32 records and one summary")
    candidate_ids = [str(row.get("candidate_id") or "") for row in records]
    if not all(candidate_ids) or len(set(candidate_ids)) != 32:
        raise RuntimeError("one-shot output candidate IDs are missing or duplicated")
    summary = summaries[0]
    if not (
        summary.get("status") == "provisional_awaiting_human_semantic_review"
        and summary.get("human_semantic_review_required") is True
        and summary.get("go") is None
    ):
        raise RuntimeError("one-shot summary is not awaiting human adjudication")
    return records, summary


def _load_frozen(path: Path) -> list[dict[str, Any]]:
    rows = list(read_jsonl(path))
    if len(rows) != 32:
        raise RuntimeError("frozen A6 set must contain 32 rows")
    if len({row["candidate_id"] for row in rows}) != 32:
        raise RuntimeError("frozen A6 candidate IDs are not unique")
    return sorted(rows, key=lambda row: row["slot_ordinal"])


def _citations(record: dict[str, Any]) -> list[dict[str, Any]]:
    result = record.get("result") or {}
    return [
        citation
        for claim in result.get("claims") or []
        for citation in claim.get("citations") or []
    ]


def render_review_template(
    *,
    one_shot_output: Path,
    frozen_set: Path,
    output: Path,
) -> dict[str, Any]:
    run_sha256 = sha256_path(one_shot_output)
    frozen_sha256 = sha256_path(frozen_set)
    records, _ = _load_run(one_shot_output)
    frozen_rows = _load_frozen(frozen_set)
    records_by_id = {row["candidate_id"]: row for row in records}
    if set(records_by_id) != {row["candidate_id"] for row in frozen_rows}:
        raise RuntimeError("one-shot output and frozen set candidate IDs differ")

    rows = []
    for frozen in frozen_rows:
        record = records_by_id[frozen["candidate_id"]]
        result = record.get("result") or {}
        rows.append(
            {
                "one_shot_sha256": run_sha256,
                "frozen_set_sha256": frozen_sha256,
                "slot_ordinal": frozen["slot_ordinal"],
                "candidate_id": frozen["candidate_id"],
                "question_text": frozen["question_text"],
                "expected_mode": _expected_mode(frozen),
                "actual_mode": record.get("actual_mode", ""),
                "rendered_answer": result.get("rendered_answer", ""),
                "automatic_meaning_complete": record.get("meaning_complete", False),
                "automatic_false_full": record.get("false_full_candidate", False),
                "automatic_unsupported_overclaim": record.get(
                    "unsupported_overclaim_candidate", False
                ),
                "automatic_citation_policy_restored": record.get(
                    "citation_policy_restored", False
                ),
                "requirement_scores_json": json.dumps(
                    record.get("requirement_scores") or [], ensure_ascii=False
                ),
                "citations_json": json.dumps(_citations(record), ensure_ascii=False),
                "error": record.get("error", ""),
                **{field: "" for field in REVIEW_FIELDS},
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError(f"review template already exists: {output}")
    with output.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "status": "human_semantic_adjudication_pending",
        "row_count": 32,
        "one_shot_sha256": run_sha256,
        "frozen_set_sha256": frozen_sha256,
        "review_csv": output.as_posix(),
        "review_csv_sha256": sha256_path(output),
    }


def _required_bool(value: Any, *, field: str, slot: int) -> bool:
    normalized = str(value or "").strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise RuntimeError(f"slot {slot}: {field} must be an explicit yes or no")


def _reviewed_at(value: Any, *, slot: int) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RuntimeError(f"slot {slot}: reviewed_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"slot {slot}: reviewed_at must include a timezone")
    return text


def _write_immutable(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == value:
            return
        raise RuntimeError(f"final adjudication output already differs: {path}")
    with path.open("xb") as handle:
        handle.write(value)


def finalize_review(
    *,
    one_shot_output: Path,
    frozen_set: Path,
    review_csv: Path,
    output: Path,
) -> dict[str, Any]:
    run_sha256 = sha256_path(one_shot_output)
    frozen_sha256 = sha256_path(frozen_set)
    records, automatic_summary = _load_run(one_shot_output)
    frozen_rows = _load_frozen(frozen_set)
    records_by_id = {row["candidate_id"]: row for row in records}
    with review_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    if len(review_rows) != 32:
        raise RuntimeError("human adjudication CSV must contain 32 rows")
    reviews_by_slot: dict[int, dict[str, Any]] = {}
    reviewer_ids = set()
    for raw in review_rows:
        try:
            slot = int(raw.get("slot_ordinal") or 0)
        except ValueError as exc:
            raise RuntimeError("invalid adjudication slot") from exc
        if slot in reviews_by_slot or not 1 <= slot <= 32:
            raise RuntimeError(f"invalid or duplicate adjudication slot: {slot}")
        frozen = frozen_rows[slot - 1]
        record = records_by_id.get(frozen["candidate_id"])
        if record is None:
            raise RuntimeError(f"slot {slot}: missing one-shot record")
        fixed_values = {
            "one_shot_sha256": run_sha256,
            "frozen_set_sha256": frozen_sha256,
            "candidate_id": frozen["candidate_id"],
            "question_text": frozen["question_text"],
            "expected_mode": _expected_mode(frozen),
            "actual_mode": str(record.get("actual_mode") or ""),
        }
        for field, expected in fixed_values.items():
            if str(raw.get(field) or "") != expected:
                raise RuntimeError(f"slot {slot}: protected field changed: {field}")
        if not _required_bool(
            raw.get("adjudication_complete"), field="adjudication_complete", slot=slot
        ):
            raise RuntimeError(f"slot {slot}: adjudication is not complete")
        reviewer_id = str(raw.get("reviewer_id") or "").strip()
        rationale = str(raw.get("review_rationale") or "").strip()
        if not reviewer_id or not rationale:
            raise RuntimeError(f"slot {slot}: reviewer_id and rationale are required")
        reviewer_ids.add(reviewer_id)
        reviews_by_slot[slot] = {
            "semantic_correct": _required_bool(
                raw.get("human_semantic_correct"),
                field="human_semantic_correct",
                slot=slot,
            ),
            "false_full": _required_bool(
                raw.get("human_false_full"), field="human_false_full", slot=slot
            ),
            "unsupported_overclaim": _required_bool(
                raw.get("human_unsupported_overclaim"),
                field="human_unsupported_overclaim",
                slot=slot,
            ),
            "reviewer_id": reviewer_id,
            "reviewed_at": _reviewed_at(raw.get("reviewed_at"), slot=slot),
            "rationale": rationale,
        }
    if set(reviews_by_slot) != set(range(1, 33)):
        raise RuntimeError("human adjudication must cover slots 1 through 32 exactly")

    clear_slots = [
        row["slot_ordinal"]
        for row in frozen_rows
        if row["expected_response_mode"] != "clarification"
    ]
    semantic_correct = sum(reviews_by_slot[slot]["semantic_correct"] for slot in clear_slots)
    human_semantic_accuracy = semantic_correct / len(clear_slots)
    human_false_full_slots = [
        slot for slot, review in reviews_by_slot.items() if review["false_full"]
    ]
    human_unsupported_overclaim_slots = [
        slot
        for slot, review in reviews_by_slot.items()
        if review["unsupported_overclaim"]
    ]
    automatic_gates = dict(automatic_summary.get("gates") or {})
    automatic_gates.pop("clear_semantic_accuracy_at_least_80pct", None)
    final_gates = {
        **automatic_gates,
        "human_clear_semantic_accuracy_at_least_80pct": human_semantic_accuracy >= 0.8,
        "human_false_full_zero": not human_false_full_slots,
        "human_unsupported_overclaim_zero": not human_unsupported_overclaim_slots,
    }
    final = {
        "report_schema_version": "product-free-rag-a6-final-adjudication-v1",
        "adjudicator_version": ADJUDICATOR_VERSION,
        "status": "final_go" if all(final_gates.values()) else "final_no_go",
        "go": all(final_gates.values()),
        "one_shot_output": {
            "path": one_shot_output.as_posix(),
            "sha256": run_sha256,
        },
        "frozen_set": {
            "path": frozen_set.as_posix(),
            "sha256": frozen_sha256,
        },
        "human_review": {
            "path": review_csv.as_posix(),
            "sha256": sha256_path(review_csv),
            "reviewed_rows": 32,
            "reviewer_ids": sorted(reviewer_ids),
            "clear_case_count": len(clear_slots),
            "semantic_correct": semantic_correct,
            "semantic_accuracy": human_semantic_accuracy,
            "false_full_slots": human_false_full_slots,
            "unsupported_overclaim_slots": human_unsupported_overclaim_slots,
        },
        "automatic_summary": automatic_summary,
        "final_gates": final_gates,
    }
    value = (json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _write_immutable(output, value)
    if sha256_path(one_shot_output) != run_sha256:
        raise RuntimeError("one-shot output changed during adjudication")
    return {
        "status": final["status"],
        "go": final["go"],
        "output": output.as_posix(),
        "sha256": sha256_path(output),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Human-adjudicate Product Free RAG A6")
    parser.add_argument("mode", choices=("template", "finalize"))
    parser.add_argument("--one-shot-output", type=Path, required=True)
    parser.add_argument("--frozen-set", type=Path, required=True)
    parser.add_argument("--review-csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.mode == "template":
        result = render_review_template(
            one_shot_output=args.one_shot_output,
            frozen_set=args.frozen_set,
            output=args.output,
        )
    else:
        if args.review_csv is None:
            raise RuntimeError("--review-csv is required for finalize")
        result = finalize_review(
            one_shot_output=args.one_shot_output,
            frozen_set=args.frozen_set,
            review_csv=args.review_csv,
            output=args.output,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

