from pathlib import Path

from src.v3.audit_product_minimal_verifier_step2 import (
    DEFAULT_INPUTS,
    HISTORICAL_PROCESSING_INPUT,
    audit_step2,
)


def test_step2_saved_output_audit_preserves_safety_guards():
    rows = audit_step2(
        DEFAULT_INPUTS,
        historical_processing_input=HISTORICAL_PROCESSING_INPUT,
    )
    summary = rows[-1]

    assert summary["saved_case_count"] == 160
    assert summary["qwen_calls"] == 0
    assert summary["retrieval_calls"] == 0
    assert summary["reason_counts"] == {
        "ambiguous_cross_parent_context": 4,
        "cross_parent_structured_value_conflict": 3,
        "evidence_relevance_below_threshold": 4,
        "negative_absence_not_in_evidence": 1,
        "question_relation_role_mismatch": 0,
    }
    assert summary["processing_duration"] == {
        "selected_160_triggered_claims": 3,
        "selected_160_blocked_claims": 0,
        "historical_actual_errors_blocked": 1,
        "regression_test_present": True,
        "decision": "keep_blocking_not_dead_code",
        "deletion_applied": False,
    }
    assert summary["token_overlap_0_1"] == {
        "logged_claims": 4,
        "non_blocking_reason_configured": True,
        "decision": "keep_existing_shadow",
    }
    assert summary["cross_parent_structured_value_conflict"] == {
        "blocked_claims": 3,
        "actual_errors_blocked": 2,
        "correct_claims_blocked": 1,
        "precision": 2 / 3,
        "decision": "keep_blocking_until_semantic_replacement",
    }
    assert summary["ambiguous_cross_parent_context"] == {
        "rejection_records": 4,
        "claim_text_unavailable": 4,
        "precision": None,
        "decision": "not_measurable_from_saved_output_do_not_shadow",
    }
    assert summary["negative_absence_not_in_evidence"] == {
        "blocked_claims": 1,
        "actual_errors_blocked": 1,
        "correct_claims_blocked": 0,
        "precision": 1.0,
        "known_positive_wording_bypass": True,
        "decision": "keep_blocking_and_cover_bypass_in_step3",
    }
    assert summary["blocking_guard_code_changes"] == 0
    assert summary["step2_decision"] == (
        "no_guard_ready_for_deletion_or_shadow"
    )


def test_step2_audit_records_processing_duration_counterexample():
    rows = audit_step2(
        DEFAULT_INPUTS,
        historical_processing_input=HISTORICAL_PROCESSING_INPUT,
    )

    counterexamples = [
        row for row in rows if row["type"] == "historical_counterexample"
    ]
    assert len(counterexamples) == 1
    assert counterexamples[0]["slot_ordinal"] == 24
    assert counterexamples[0]["adjudication"] == "actual_error_blocked"
    assert "12개월 이상 미접속" in counterexamples[0]["text"]


def test_step2_audit_identifies_a5_slot_15_and_22_guards():
    rows = audit_step2(
        DEFAULT_INPUTS,
        historical_processing_input=HISTORICAL_PROCESSING_INPUT,
    )

    assert rows[-1]["a5_failure_assignment"] == {
        "slot_15": "cross_parent_structured_value_conflict",
        "slot_22": "factual_values_not_in_evidence",
    }


def test_step2_default_reports_exist():
    assert all(Path(path).is_file() for path in DEFAULT_INPUTS)
    assert HISTORICAL_PROCESSING_INPUT.is_file()
