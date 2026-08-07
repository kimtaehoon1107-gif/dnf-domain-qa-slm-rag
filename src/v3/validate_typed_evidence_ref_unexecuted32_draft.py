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


VALIDATOR_VERSION = "typed-evidence-ref-unexecuted32-draft-validator-v1"


def normalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_prior_fields(
    value: Any, questions: set[str], parent_ids: set[str]
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"question", "question_text"} and isinstance(child, str) and child.strip():
                questions.add(normalize_question(child))
            if key in {"document_id", "primary_document_id", "parent_document_id"}:
                if isinstance(child, str) and child.startswith("document_"):
                    parent_ids.add(child)
            if key in {"document_ids", "gold_document_ids"} and isinstance(child, list):
                parent_ids.update(
                    item
                    for item in child
                    if isinstance(item, str) and item.startswith("document_")
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
    parser.add_argument("--prior-output-dir", type=Path)
    parser.add_argument("--prior-evaluation", type=Path, action="append", default=[])
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--md-output", type=Path, required=True)
    args = parser.parse_args()

    rows = list(read_jsonl(args.candidates))
    chunks = {row["chunk_id"]: row for row in read_jsonl(args.chunks)}
    failures: list[dict[str, Any]] = []

    def fail(check: str, slot: int | None, detail: str) -> None:
        failures.append({"check": check, "slot_ordinal": slot, "detail": detail})

    if len(rows) != 32:
        fail("row_count", None, f"expected 32, got {len(rows)}")

    source_counts = Counter(row["source_id"] for row in rows)
    dimension_counts = Counter(row["primary_dimension"] for row in rows)
    if len(source_counts) != 8 or any(count != 4 for count in source_counts.values()):
        fail("source_matrix", None, json.dumps(source_counts, ensure_ascii=False))
    if len(dimension_counts) != 8 or any(count != 4 for count in dimension_counts.values()):
        fail("dimension_matrix", None, json.dumps(dimension_counts, ensure_ascii=False))

    normalized_questions = [normalize_question(row["question_text"]) for row in rows]
    for question, count in Counter(normalized_questions).items():
        if count > 1:
            fail("duplicate_question", None, question)

    evidence_unit_count = 0
    unsupported_requirement_count = 0
    for row in rows:
        slot = row["slot_ordinal"]
        if row["review"]["status"] != "pending":
            fail("review_lock", slot, f"review status is {row['review']['status']}")
        if row["execution_allowed"] or row["training_allowed"]:
            fail("execution_lock", slot, "execution_allowed or training_allowed is true")
        if row["evaluation_role"] != "codex_authored_unexecuted_candidate_pending_human_review":
            fail("evaluation_role", slot, row["evaluation_role"])

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
                        f"{unit['chunk_id']}:{start}:{end}",
                    )
                if chunk["parent_document_id"] != unit["document_id"]:
                    fail("evidence_parent_mismatch", slot, unit["chunk_id"])
                if unit["document_id"] != row["primary_document_id"]:
                    fail("primary_document_mismatch", slot, unit["document_id"])

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
    prior_paths = sorted(args.prior_evaluation_dir.glob("*.jsonl"))
    if args.prior_output_dir:
        prior_paths.extend(sorted(args.prior_output_dir.rglob("*.jsonl")))
    prior_paths.extend(args.prior_evaluation)
    for path in prior_paths:
        if not path.exists() or path.resolve() == args.candidates.resolve():
            continue
        for row in read_jsonl(path):
            collect_prior_fields(row, prior_questions, prior_parent_ids)

    exact_question_overlap_slots = [
        row["slot_ordinal"]
        for row in rows
        if normalize_question(row["question_text"]) in prior_questions
    ]
    for slot in exact_question_overlap_slots:
        fail("prior_exact_question_overlap", slot, "exact normalized question overlap")

    parent_overlaps = [
        {
            "slot_ordinal": row["slot_ordinal"],
            "document_id": row["primary_document_id"],
            "registered_exception": bool(row["parent_overlap_exception_reason"]),
        }
        for row in rows
        if row["primary_document_id"] in prior_parent_ids
    ]
    for overlap in parent_overlaps:
        if not overlap["registered_exception"]:
            fail("unregistered_parent_overlap", overlap["slot_ordinal"], overlap["document_id"])

    report = {
        "validator_version": VALIDATOR_VERSION,
        "status": "pass" if not failures else "fail",
        "candidate_path": args.candidates.as_posix(),
        "candidate_sha256": sha256_path(args.candidates),
        "row_count": len(rows),
        "requirement_count": sum(len(row["requirements"]) for row in rows),
        "evidence_unit_count": evidence_unit_count,
        "unsupported_requirement_count": unsupported_requirement_count,
        "source_counts": dict(sorted(source_counts.items())),
        "dimension_counts": dict(sorted(dimension_counts.items())),
        "pending_review_count": sum(row["review"]["status"] == "pending" for row in rows),
        "execution_allowed_rows": sum(row["execution_allowed"] for row in rows),
        "training_allowed_rows": sum(row["training_allowed"] for row in rows),
        "prior_question_count_scanned": len(prior_questions),
        "prior_exact_question_overlap_slots": exact_question_overlap_slots,
        "prior_parent_overlap_count": len(parent_overlaps),
        "prior_parent_overlaps": parent_overlaps,
        "failures": failures,
        "retrieval_run_performed": False,
        "generation_run_performed": False,
        "evaluation_run_performed": False,
        "freeze_allowed": False,
        "next_action": "human_review",
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Typed evidence-ref 신규 32문항 초안 검증",
        "",
        f"- 상태: **{report['status'].upper()}**",
        f"- 문항: `{report['row_count']}`",
        f"- 요구사항: `{report['requirement_count']}`",
        f"- 원문 evidence unit: `{report['evidence_unit_count']}`",
        f"- prior exact question overlap: `{len(exact_question_overlap_slots)}`",
        f"- prior parent overlap: `{len(parent_overlaps)}` (등록된 claim-disjoint 예외)",
        f"- 실행 허용 문항: `{report['execution_allowed_rows']}`",
        f"- 학습 허용 문항: `{report['training_allowed_rows']}`",
        "",
        "## 분포",
        "",
        f"- 출처: `{json.dumps(report['source_counts'], ensure_ascii=False)}`",
        f"- 차원: `{json.dumps(report['dimension_counts'], ensure_ascii=False)}`",
        "",
        "## 판정",
        "",
        "- 이 파일은 아직 평가 세트가 아니라 사람 검수 대기 초안입니다.",
        "- 검색·reranker·Qwen·verifier·scorer 실행은 수행하지 않았습니다.",
        "- 사람 검수 승인 후 별도 freeze/SHA 단계가 필요합니다.",
    ]
    if failures:
        lines.extend(["", "## 실패", ""])
        lines.extend(
            f"- `{item['check']}` slot={item['slot_ordinal']}: {item['detail']}"
            for item in failures
        )
    args.md_output.parent.mkdir(parents=True, exist_ok=True)
    args.md_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if failures:
        raise RuntimeError(f"draft validation failed with {len(failures)} issue(s)")


if __name__ == "__main__":
    main()
