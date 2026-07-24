from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_question_partial_hybrid_ab import (
    DEFAULT_ARM_Q_CASES,
    DEFAULT_CLAIM_RERANKER,
    build_error_audit_rows,
    build_hybrid_rows,
    evaluate_and_freeze,
    summarize_hybrid,
)
from src.v3.evaluate_question_partial_fallback_ab import (
    DEFAULT_ARM0_CASES,
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_CHUNKS,
    DEFAULT_GROUND_TRUTH,
)
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_ASSEMBLER,
    DEFAULT_CANARY,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
)

ROOT = Path(__file__).resolve().parents[2]


def _actual_rows():
    ground_truth = read_jsonl(ROOT / DEFAULT_GROUND_TRUTH)
    arm0 = read_jsonl(ROOT / DEFAULT_ARM0_CASES)
    arm_q = read_jsonl(ROOT / DEFAULT_ARM_Q_CASES)
    enumeration = read_jsonl(ROOT / DEFAULT_ENUMERATION)
    assembler = read_jsonl(ROOT / DEFAULT_ASSEMBLER)
    evaluation = read_jsonl(ROOT / DEFAULT_DEV) + read_jsonl(ROOT / DEFAULT_CANARY)
    hybrid = build_hybrid_rows(
        ground_truth_rows=ground_truth,
        arm0_rows=arm0,
        arm_q_rows=arm_q,
        assembler_rows=assembler,
        evaluation_rows=evaluation,
        claim_reranker_rows=read_jsonl(ROOT / DEFAULT_CLAIM_RERANKER),
        canary_rows=read_jsonl(ROOT / DEFAULT_CANARY_RUNTIME),
        chunks=read_jsonl(ROOT / DEFAULT_CHUNKS),
    )
    audit = build_error_audit_rows(
        hybrid_rows=hybrid,
        ground_truth_rows=ground_truth,
        enumeration_rows=enumeration,
        assembler_rows=assembler,
        arm0_rows=arm0,
        arm_q_rows=arm_q,
        evaluation_rows=evaluation,
    )
    return hybrid, audit


def test_hybrid_ab_passes_preregistered_development_gate():
    hybrid, _ = _actual_rows()
    result = summarize_hybrid(hybrid)

    assert result["arm0_mixed"]["correct_mixed_partial"]["successes"] == 2
    assert result["arm_q_mixed"]["correct_mixed_partial"]["successes"] == 10
    assert result["arm_q2_mixed"]["correct_mixed_partial"]["successes"] == 12
    assert result["arm_q2_mixed"]["correct_mixed_partial_span_strict"]["successes"] == 9
    assert result["arm_q2_mixed"]["mixed_overclaim"]["successes"] == 0
    assert result["arm_q2_mixed"]["mixed_missing_evidence"]["successes"] == 1
    assert result["existing_correct_mixed_regression_count"] == 0
    assert result["arm_q2_contract"]["exact_extractive"]["successes"] == 12
    assert result["arm_q2_contract"]["partial_safety_contract"]["successes"] == 12
    assert result["strict_gate_passed"] is True
    assert result["decision"] == "DEVELOPMENT_GO_CANDIDATE"


def test_error_audit_contains_every_observed_error_with_direct_data():
    _, audit = _actual_rows()

    assert len(audit) == 12
    assert sum(
        row["analysis"]["first_failure_stage"] == "SEMANTIC_SUPPORT_BOUNDARY"
        for row in audit
    ) == 10
    assert sum(
        row["analysis"]["first_failure_stage"] == "FALLBACK_EVIDENCE_SELECTION"
        for row in audit
    ) == 1
    assert sum(
        row["analysis"]["first_failure_stage"] == "QUESTION_PARTIAL_SIGNAL"
        for row in audit
    ) == 1
    for row in audit:
        assert row["question"]
        assert row["requirements"]
        assert row["gold_evidence_groups"]
        assert all(group["evidence_span"] for group in row["gold_evidence_groups"])

    overclaims = [row for row in audit if row["arm0"]["label"] == "mixed_overclaim"]
    assert len(overclaims) == 10
    for row in overclaims:
        assert any(
            not requirement["answerable_from_docs"]
            and requirement["arm0_status"] == "supported_exact"
            and requirement["arm0_exact_spans"]
            for requirement in row["requirements"]
        )


def test_freeze_is_content_addressed_and_reproducible():
    first = evaluate_and_freeze(ROOT)
    second = evaluate_and_freeze(ROOT)

    assert first["cases_sha256"] == second["cases_sha256"]
    assert first["audit_sha256"] == second["audit_sha256"]
    assert first["report_json_sha256"] == second["report_json_sha256"]
    assert first["report_md_sha256"] == second["report_md_sha256"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
