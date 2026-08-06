from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3 import product_minimal_verifier as verifier


DEFAULT_INPUTS = (
    Path(
        "reports/v3/"
        "product_free_rag_a5_current_product_adaptive_replay_20260804.jsonl"
    ),
    Path(
        "reports/v3/"
        "product_free_rag_existing32_qcoverage_lexical_shadow_adaptive_"
        "20260804.jsonl"
    ),
    Path(
        "reports/v3/"
        "product_free_rag_existing32_step1_clause_numeric_20260804.jsonl"
    ),
    Path(
        "reports/v3/"
        "product_free_rag_new_claim32_final_guards_adaptive_20260803.jsonl"
    ),
    Path(
        "reports/v3/"
        "product_free_rag_new_claim32_step1_clause_numeric_20260804.jsonl"
    ),
)
HISTORICAL_PROCESSING_INPUT = Path(
    "reports/v3/"
    "product_free_rag_existing32_final_adaptive_replay_20260803.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/"
    "product_minimal_verifier_step2_heuristic_audit_20260804.jsonl"
)

_PROCESSING_DURATION_CLAIM = re.compile(
    r"(?:처리|소요)\s*(?:기간|시간)"
)
_TARGET_REASONS = {
    "ambiguous_cross_parent_context",
    "cross_parent_structured_value_conflict",
    "evidence_relevance_below_threshold",
    "negative_absence_not_in_evidence",
    "question_relation_role_mismatch",
}


def _key(
    path: Path,
    slot: int,
    reason: str,
    occurrence: int,
) -> tuple[str, int, str, int]:
    return path.name, slot, reason, occurrence


_ADJUDICATIONS = {
    _key(
        DEFAULT_INPUTS[0],
        15,
        "cross_parent_structured_value_conflict",
        1,
    ): (
        "correct_claim_blocked",
        "공식 마법부여 원문이 1회 거래 뒤 계정귀속 변경을 그대로 명시한다.",
    ),
    _key(
        DEFAULT_INPUTS[3],
        3,
        "ambiguous_cross_parent_context",
        1,
    ): (
        "claim_text_unavailable_case_level_mixed_signal",
        "서버가 원시 claim text를 지웠다. sealed 기대는 구 문서의 5만원이지만 "
        "검색에는 수정 문서의 4만원도 있어 문서 충돌 자체는 실제다.",
    ),
    _key(
        DEFAULT_INPUTS[3],
        3,
        "ambiguous_cross_parent_context",
        2,
    ): (
        "claim_text_unavailable_case_level_mixed_signal",
        "서버가 원시 claim text를 지웠으므로 claim 단위 정오 판정이 불가능하다.",
    ),
    _key(
        DEFAULT_INPUTS[4],
        3,
        "ambiguous_cross_parent_context",
        1,
    ): (
        "claim_text_unavailable_case_level_mixed_signal",
        "서버가 원시 claim text를 지웠다. 같은 질문에 서로 다른 공식 문서가 "
        "동시에 노출된 것은 확인된다.",
    ),
    _key(
        DEFAULT_INPUTS[4],
        3,
        "ambiguous_cross_parent_context",
        2,
    ): (
        "claim_text_unavailable_case_level_mixed_signal",
        "서버가 원시 claim text를 지웠으므로 claim 단위 정오 판정이 불가능하다.",
    ),
    _key(
        DEFAULT_INPUTS[3],
        12,
        "cross_parent_structured_value_conflict",
        1,
    ): (
        "actual_error_blocked",
        "공식 문서는 일일 최대 50M만 제공하며 사용자의 현재 남은 양 0M은 "
        "서버 상태 없이는 증명할 수 없다.",
    ),
    _key(
        DEFAULT_INPUTS[4],
        12,
        "cross_parent_structured_value_conflict",
        1,
    ): (
        "actual_error_blocked",
        "공식 문서는 일일 최대 50M만 제공하며 사용자의 현재 남은 양 0M은 "
        "서버 상태 없이는 증명할 수 없다.",
    ),
    _key(
        DEFAULT_INPUTS[3],
        32,
        "negative_absence_not_in_evidence",
        1,
    ): (
        "actual_error_blocked",
        "인용 근거에 구매 제한 부재가 없으므로 '제한이 없습니다'는 미지원 claim이다.",
    ),
}

_HISTORICAL_PROCESSING_ADJUDICATION = (
    "actual_error_blocked",
    "12개월 이상 미접속은 길드장 위임 조건이지 처리 기간이 아니다.",
)


def _case_rows(path: Path) -> list[dict[str, Any]]:
    return [row for row in read_jsonl(path) if row.get("type") == "case"]


def _claim_texts(case: dict[str, Any]) -> list[str]:
    result = case.get("result") or {}
    return [
        str(claim.get("text") or "")
        for claim in [
            *(result.get("claims") or []),
            *(result.get("rejected_claims") or []),
        ]
        if str(claim.get("text") or "").strip()
    ]


def audit_step2(
    inputs: tuple[Path, ...],
    *,
    historical_processing_input: Path,
) -> list[dict[str, Any]]:
    cases_by_path = {path: _case_rows(path) for path in inputs}
    case_count = sum(len(cases) for cases in cases_by_path.values())
    if case_count != 160:
        raise RuntimeError(f"expected 160 saved cases, got {case_count}")

    processing_surface_claims = [
        {
            "source_report": path.as_posix(),
            "slot_ordinal": int(case["slot_ordinal"]),
            "text": text,
        }
        for path, cases in cases_by_path.items()
        for case in cases
        for text in _claim_texts(case)
        if _PROCESSING_DURATION_CLAIM.search(text)
    ]

    reason_rows = []
    reason_counts: dict[str, int] = {}
    for path, cases in cases_by_path.items():
        for case in cases:
            occurrences: dict[str, int] = {}
            for rejection in (case.get("result") or {}).get(
                "rejected_claims"
            ) or []:
                for reason in rejection.get("reasons") or []:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                    if reason not in _TARGET_REASONS:
                        continue
                    occurrences[reason] = occurrences.get(reason, 0) + 1
                    key = _key(
                        path,
                        int(case["slot_ordinal"]),
                        reason,
                        occurrences[reason],
                    )
                    adjudication = _ADJUDICATIONS.get(key)
                    reason_rows.append(
                        {
                            "type": "heuristic_occurrence",
                            "source_report": path.as_posix(),
                            "slot_ordinal": int(case["slot_ordinal"]),
                            "question": str(case.get("question") or ""),
                            "reason": reason,
                            "occurrence": occurrences[reason],
                            "text": str(rejection.get("text") or ""),
                            "evidence_refs": list(
                                rejection.get("evidence_refs") or []
                            ),
                            "adjudication": (
                                adjudication[0] if adjudication else None
                            ),
                            "rationale": (
                                adjudication[1] if adjudication else ""
                            ),
                        }
                    )

    expected_target_counts = {
        "ambiguous_cross_parent_context": 4,
        "cross_parent_structured_value_conflict": 3,
        "evidence_relevance_below_threshold": 4,
        "negative_absence_not_in_evidence": 1,
        "question_relation_role_mismatch": 0,
    }
    actual_target_counts = {
        reason: reason_counts.get(reason, 0)
        for reason in expected_target_counts
    }
    if actual_target_counts != expected_target_counts:
        raise RuntimeError(
            "unexpected STEP 2 reason counts: "
            f"{actual_target_counts}"
        )

    adjudicated_target_rows = [
        row
        for row in reason_rows
        if row["reason"]
        in {
            "ambiguous_cross_parent_context",
            "cross_parent_structured_value_conflict",
            "negative_absence_not_in_evidence",
        }
    ]
    if any(row["adjudication"] is None for row in adjudicated_target_rows):
        raise RuntimeError("missing STEP 2 adjudication")

    historical_rows = _case_rows(historical_processing_input)
    historical_processing = []
    for case in historical_rows:
        for rejection in (case.get("result") or {}).get(
            "rejected_claims"
        ) or []:
            if "question_relation_role_mismatch" not in (
                rejection.get("reasons") or []
            ):
                continue
            historical_processing.append(
                {
                    "type": "historical_counterexample",
                    "source_report": historical_processing_input.as_posix(),
                    "slot_ordinal": int(case["slot_ordinal"]),
                    "question": str(case.get("question") or ""),
                    "reason": "question_relation_role_mismatch",
                    "text": str(rejection.get("text") or ""),
                    "evidence_refs": list(
                        rejection.get("evidence_refs") or []
                    ),
                    "adjudication": (
                        _HISTORICAL_PROCESSING_ADJUDICATION[0]
                    ),
                    "rationale": (
                        _HISTORICAL_PROCESSING_ADJUDICATION[1]
                    ),
                }
            )
    if len(historical_processing) != 1:
        raise RuntimeError(
            "expected one historical processing-duration counterexample"
        )

    conflict_rows = [
        row
        for row in adjudicated_target_rows
        if row["reason"] == "cross_parent_structured_value_conflict"
    ]
    absence_rows = [
        row
        for row in adjudicated_target_rows
        if row["reason"] == "negative_absence_not_in_evidence"
    ]
    ambiguity_rows = [
        row
        for row in adjudicated_target_rows
        if row["reason"] == "ambiguous_cross_parent_context"
    ]
    summary = {
        "type": "summary",
        "measurement": "saved_160_step2_heuristic_precision_audit",
        "qwen_calls": 0,
        "retrieval_calls": 0,
        "saved_case_count": case_count,
        "input_reports": [path.as_posix() for path in inputs],
        "reason_counts": actual_target_counts,
        "processing_duration": {
            "selected_160_triggered_claims": len(
                processing_surface_claims
            ),
            "selected_160_blocked_claims": 0,
            "historical_actual_errors_blocked": 1,
            "regression_test_present": True,
            "decision": "keep_blocking_not_dead_code",
            "deletion_applied": False,
        },
        "token_overlap_0_1": {
            "logged_claims": actual_target_counts[
                "evidence_relevance_below_threshold"
            ],
            "non_blocking_reason_configured": (
                "evidence_relevance_below_threshold"
                in verifier._NON_BLOCKING_REJECTION_REASONS
            ),
            "decision": "keep_existing_shadow",
        },
        "cross_parent_structured_value_conflict": {
            "blocked_claims": len(conflict_rows),
            "actual_errors_blocked": sum(
                row["adjudication"] == "actual_error_blocked"
                for row in conflict_rows
            ),
            "correct_claims_blocked": sum(
                row["adjudication"] == "correct_claim_blocked"
                for row in conflict_rows
            ),
            "precision": 2 / 3,
            "decision": "keep_blocking_until_semantic_replacement",
        },
        "ambiguous_cross_parent_context": {
            "rejection_records": len(ambiguity_rows),
            "claim_text_unavailable": sum(
                not row["text"] for row in ambiguity_rows
            ),
            "precision": None,
            "decision": "not_measurable_from_saved_output_do_not_shadow",
        },
        "negative_absence_not_in_evidence": {
            "blocked_claims": len(absence_rows),
            "actual_errors_blocked": sum(
                row["adjudication"] == "actual_error_blocked"
                for row in absence_rows
            ),
            "correct_claims_blocked": 0,
            "precision": 1.0,
            "known_positive_wording_bypass": True,
            "decision": "keep_blocking_and_cover_bypass_in_step3",
        },
        "a5_failure_assignment": {
            "slot_15": "cross_parent_structured_value_conflict",
            "slot_22": "factual_values_not_in_evidence",
        },
        "blocking_guard_code_changes": 0,
        "step2_decision": "no_guard_ready_for_deletion_or_shadow",
    }
    return [
        *reason_rows,
        *historical_processing,
        {
            "type": "processing_duration_selected_surface_claims",
            "claims": processing_surface_claims,
        },
        summary,
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit STEP 2 verifier heuristics on saved outputs."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = audit_step2(
        DEFAULT_INPUTS,
        historical_processing_input=HISTORICAL_PROCESSING_INPUT,
    )
    write_jsonl(args.output, rows)
    print(json.dumps(rows[-1], ensure_ascii=False))


if __name__ == "__main__":
    main()
