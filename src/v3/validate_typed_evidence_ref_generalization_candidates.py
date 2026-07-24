from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl


VALIDATOR_VERSION = "typed-evidence-ref-generalization-candidate-validator-v1"


def normalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_prior_fields(value: Any, questions: set[str], parent_ids: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"question", "question_text"} and isinstance(child, str) and child.strip():
                questions.add(normalize_question(child))
            if key == "gold_document_ids" and isinstance(child, list):
                parent_ids.update(
                    item for item in child if isinstance(item, str) and item.startswith("document_")
                )
            collect_prior_fields(child, questions, parent_ids)
    elif isinstance(value, list):
        for child in value:
            collect_prior_fields(child, questions, parent_ids)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--prior-evaluation-dir", type=Path, required=True)
    parser.add_argument("--adaptive-32", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--md-output", type=Path, required=True)
    args = parser.parse_args()

    candidates = list(read_jsonl(args.candidates))
    chunks = {row["chunk_id"]: row for row in read_jsonl(args.chunks)}
    failures: list[dict[str, Any]] = []

    def fail(check: str, slot: int | None, detail: str) -> None:
        failures.append({"check": check, "slot_ordinal": slot, "detail": detail})

    if len(candidates) != 64:
        fail("row_count", None, f"expected 64, got {len(candidates)}")

    source_counts = Counter(row["source_id"] for row in candidates)
    dimension_counts = Counter(row["primary_dimension"] for row in candidates)
    if any(count != 8 for count in source_counts.values()) or len(source_counts) != 8:
        fail("source_matrix", None, json.dumps(source_counts, ensure_ascii=False))
    if any(count != 8 for count in dimension_counts.values()) or len(dimension_counts) != 8:
        fail("dimension_matrix", None, json.dumps(dimension_counts, ensure_ascii=False))

    normalized_questions = [normalize_question(row["question_text"]) for row in candidates]
    duplicate_questions = sorted(
        question for question, count in Counter(normalized_questions).items() if count > 1
    )
    for duplicate in duplicate_questions:
        fail("duplicate_question", None, duplicate)

    evidence_unit_count = 0
    unsupported_requirement_count = 0
    for row in candidates:
        slot = row["slot_ordinal"]
        if row["review"]["status"] != "pending":
            fail("review_lock", slot, f"review status is {row['review']['status']}")
        if row["execution_allowed"] or row["training_allowed"]:
            fail("execution_lock", slot, "execution_allowed or training_allowed is true")

        statuses = []
        requirement_ids = set()
        for requirement in row["requirements"]:
            requirement_id = requirement["requirement_id"]
            if requirement_id in requirement_ids:
                fail("duplicate_requirement_id", slot, requirement_id)
            requirement_ids.add(requirement_id)
            status = requirement["expected_status"]
            statuses.append(status)
            values = requirement["required_values"]
            units = requirement["acceptable_evidence_units"]
            if status == "supported" and (not values or not units):
                fail("supported_requirement_incomplete", slot, requirement_id)
            if status == "unsupported":
                unsupported_requirement_count += 1
                if values or units:
                    fail("unsupported_requirement_has_gold", slot, requirement_id)
            for unit in units:
                evidence_unit_count += 1
                chunk = chunks.get(unit["chunk_id"])
                if chunk is None:
                    fail("missing_chunk", slot, unit["chunk_id"])
                    continue
                start = unit["start_char"]
                end = unit["end_char"]
                actual = chunk["display_text"][start:end]
                if actual != unit["text"]:
                    fail(
                        "evidence_slice_mismatch",
                        slot,
                        f"{unit['chunk_id']}:{start}:{end} expected={unit['text']!r} actual={actual!r}",
                    )
                if chunk["parent_document_id"] != unit["document_id"]:
                    fail("evidence_parent_mismatch", slot, unit["chunk_id"])

        expected_mode = (
            "full_answer"
            if statuses and all(status == "supported" for status in statuses)
            else "partial_answer"
            if "supported" in statuses
            else "abstain"
        )
        if row["expected_response_mode"] != expected_mode:
            fail(
                "response_mode_mismatch",
                slot,
                f"{row['expected_response_mode']} != {expected_mode}",
            )

    prior_questions: set[str] = set()
    prior_parent_ids: set[str] = set()
    prior_paths = sorted(args.prior_evaluation_dir.glob("*.jsonl")) + [args.adaptive_32]
    for path in prior_paths:
        if not path.exists():
            continue
        for row in read_jsonl(path):
            collect_prior_fields(row, prior_questions, prior_parent_ids)

    prior_exact_question_overlaps = [
        row["slot_ordinal"]
        for row in candidates
        if normalize_question(row["question_text"]) in prior_questions
    ]
    for slot in prior_exact_question_overlaps:
        fail("prior_exact_question_overlap", slot, "exact normalized question overlap")

    parent_overlaps = [
        {
            "slot_ordinal": row["slot_ordinal"],
            "document_id": row["primary_document_id"],
            "registered_exception": bool(row["parent_overlap_exception_reason"]),
        }
        for row in candidates
        if row["primary_document_id"] in prior_parent_ids
    ]
    unregistered_parent_overlaps = [
        overlap for overlap in parent_overlaps if not overlap["registered_exception"]
    ]
    for overlap in unregistered_parent_overlaps:
        fail(
            "unregistered_parent_overlap",
            overlap["slot_ordinal"],
            overlap["document_id"],
        )

    report = {
        "validator_version": VALIDATOR_VERSION,
        "status": "pass" if not failures else "fail",
        "candidate_path": args.candidates.as_posix(),
        "candidate_sha256": sha256_path(args.candidates),
        "row_count": len(candidates),
        "source_counts": dict(sorted(source_counts.items())),
        "dimension_counts": dict(sorted(dimension_counts.items())),
        "evidence_unit_count": evidence_unit_count,
        "unsupported_requirement_count": unsupported_requirement_count,
        "pending_review_count": sum(
            row["review"]["status"] == "pending" for row in candidates
        ),
        "execution_allowed_rows": sum(bool(row["execution_allowed"]) for row in candidates),
        "training_allowed_rows": sum(bool(row["training_allowed"]) for row in candidates),
        "duplicate_question_count": len(duplicate_questions),
        "prior_question_count_scanned": len(prior_questions),
        "prior_parent_count_scanned": len(prior_parent_ids),
        "prior_exact_question_overlap_slots": prior_exact_question_overlaps,
        "parent_overlap_count": len(parent_overlaps),
        "parent_overlaps": parent_overlaps,
        "unregistered_parent_overlap_count": len(unregistered_parent_overlaps),
        "failure_count": len(failures),
        "failures": failures,
        "model_or_retrieval_execution_performed": False,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_lines = [
        "# Typed evidence-ref 64문항 후보 자동 검증",
        "",
        f"- 상태: **{report['status'].upper()}**",
        f"- 문항: {len(candidates)}",
        f"- 정확 근거 단위: {evidence_unit_count}",
        f"- pending human review: {report['pending_review_count']}",
        f"- 실행/학습 허용 행: {report['execution_allowed_rows']} / {report['training_allowed_rows']}",
        f"- 내부 중복 질문: {report['duplicate_question_count']}",
        f"- 과거 질문 exact overlap: {len(prior_exact_question_overlaps)}",
        f"- 과거 gold parent overlap: {len(parent_overlaps)}",
        f"- 미등록 parent overlap: {len(unregistered_parent_overlaps)}",
        f"- 실패: {len(failures)}",
        "",
        "모델·검색·reranker·verifier 평가는 실행하지 않았습니다.",
    ]
    if failures:
        md_lines.extend(["", "## 실패", ""])
        md_lines.extend(
            f"- slot {failure['slot_ordinal']}: {failure['check']} — {failure['detail']}"
            for failure in failures
        )
    args.md_output.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError(f"validation failed with {len(failures)} failure(s)")


if __name__ == "__main__":
    main()
