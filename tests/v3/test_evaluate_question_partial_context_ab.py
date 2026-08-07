from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_question_partial_context_ab import (
    DEFAULT_FEDERATED_CANDIDATES,
    DEFAULT_FEDERATED_CASES,
    DEFAULT_Q2_CASES,
    build_context_rows,
    build_failure_audit,
    evaluate_and_freeze,
    summarize_context,
)
from src.v3.evaluate_question_partial_fallback_ab import (
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_CHUNKS,
)
from src.v3.evaluate_question_partial_hybrid_ab import DEFAULT_CLAIM_RERANKER
from src.v3.evaluate_router_backbone_mixed_metrics import DEFAULT_CANARY, DEFAULT_DEV

ROOT = Path(__file__).resolve().parents[2]


def _actual():
    q2 = read_jsonl(ROOT / DEFAULT_Q2_CASES)
    evaluation = read_jsonl(ROOT / DEFAULT_DEV) + read_jsonl(ROOT / DEFAULT_CANARY)
    chunks = read_jsonl(ROOT / DEFAULT_CHUNKS)
    q3 = build_context_rows(q2_rows=q2, evaluation_rows=evaluation, chunks=chunks)
    audit = build_failure_audit(
        q2_rows=q2,
        q3_rows=q3,
        evaluation_rows=evaluation,
        chunks=chunks,
        claim_reranker_rows=read_jsonl(ROOT / DEFAULT_CLAIM_RERANKER),
        canary_rows=read_jsonl(ROOT / DEFAULT_CANARY_RUNTIME),
        federated_cases=read_jsonl(ROOT / DEFAULT_FEDERATED_CASES),
        federated_candidates=read_jsonl(ROOT / DEFAULT_FEDERATED_CANDIDATES),
    )
    return q3, audit


def test_same_chunk_context_improves_span_strict_without_regression():
    rows, _ = _actual()
    result = summarize_context(rows)

    assert result["arm_q2_mixed"]["correct_mixed_partial"]["successes"] == 12
    assert result["arm_q2_mixed"]["correct_mixed_partial_span_strict"]["successes"] == 9
    assert result["arm_q3_mixed"]["correct_mixed_partial"]["successes"] == 12
    assert result["arm_q3_mixed"]["correct_mixed_partial_span_strict"]["successes"] == 12
    assert result["arm_q3_mixed"]["mixed_overclaim"]["successes"] == 0
    assert result["arm_q3_mixed"]["mixed_missing_evidence"]["successes"] == 1
    assert result["context_applied_count"] == 12
    assert result["existing_correct_regression_case_ids"] == []
    assert result["remaining_error_count"] == 1
    assert result["strict_gate_passed"] is True


def test_direct_audit_attributes_three_context_and_one_route_signal_failure():
    _, audit = _actual()

    assert len(audit) == 4
    counts = {}
    for row in audit:
        counts[row["first_failure_type"]] = counts.get(row["first_failure_type"], 0) + 1
        assert row["question"]
        assert row["gold_evidence_groups"]
    assert counts == {
        "SAME_CHUNK_CONTEXT_TRUNCATION": 3,
        "SOURCE_SCOPE_PLUS_PARTIAL_SIGNAL_MISS": 1,
    }
    fixed = [row for row in audit if row["q3_span_strict_fixed"]]
    assert len(fixed) == 3
    remaining = [row for row in audit if not row["q3_span_strict_fixed"]]
    assert len(remaining) == 1
    item = remaining[0]
    assert item["route_audit"]["chosen_source_ids"] == ["dnf_seria_shop"]
    assert "dnf_event" in item["route_audit"]["candidate_sources"]
    assert item["route_audit"]["answerability"] == "true"
    assert item["federated_existing_ab"]["federated_global"]["all_groups_cited"]
    assert item["federated_existing_ab"]["federated_quota"]["all_groups_cited"]
    # The expiry requirement retrieves the shared event chunk at rank 2; that
    # same chunk contains both official facts, so the union arm covers 2/2 even
    # though the limit-only query does not independently retrieve it.
    assert any(
        any(rank is not None for rank in row["variant_gold_ranks"].values())
        for row in item["federated_gold_rank_audit"]
    )


def test_context_claims_are_exact_full_chunk_slices():
    rows, _ = _actual()
    chunks = {row["chunk_id"]: row for row in read_jsonl(ROOT / DEFAULT_CHUNKS)}
    for row in rows:
        if not row["q3_context_applied"]:
            continue
        observation = row["arm_q3_observation"]
        assert observation["exact_extractive"] is True
        expected_chars = sum(
            len(chunks[chunk_id]["display_text"])
            for chunk_id in observation["cited_chunk_ids"]
        )
        assert observation["context_character_count"] == expected_chars


def test_freeze_is_content_addressed_and_reproducible():
    first = evaluate_and_freeze(ROOT)
    second = evaluate_and_freeze(ROOT)

    assert first["cases_sha256"] == second["cases_sha256"]
    assert first["audit_sha256"] == second["audit_sha256"]
    assert first["report_json_sha256"] == second["report_json_sha256"]
    assert first["report_md_sha256"] == second["report_md_sha256"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
