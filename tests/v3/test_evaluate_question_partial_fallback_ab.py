from __future__ import annotations

from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_question_partial_fallback_ab import (
    DEFAULT_ARM0_CASES,
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_CHUNKS,
    DEFAULT_GROUND_TRUTH,
    DEFAULT_UNIFIED_RUNTIME,
    _fallback_metrics,
    build_ab_rows,
    summarize_ab,
)

ROOT = Path(__file__).resolve().parents[2]


def test_fallback_metrics_require_disclaimer_and_official_evidence() -> None:
    observation = {
        "global_partial_disclaimer": True,
        "all_official_groups_cited": True,
        "all_official_spans_complete": True,
    }
    result = _fallback_metrics(observation)
    assert result["correct_mixed_partial"] is True
    assert result["correct_mixed_partial_span_strict"] is True
    assert result["mixed_overclaim"] is False


def test_fallback_without_disclaimer_is_overclaim() -> None:
    observation = {
        "global_partial_disclaimer": False,
        "all_official_groups_cited": True,
        "all_official_spans_complete": True,
    }
    result = _fallback_metrics(observation)
    assert result["correct_mixed_partial"] is False
    assert result["mixed_overclaim"] is True


def test_integration_question_partial_fallback_is_honest_no_go() -> None:
    rows = build_ab_rows(
        ground_truth_rows=read_jsonl(ROOT / DEFAULT_GROUND_TRUTH),
        arm0_rows=read_jsonl(ROOT / DEFAULT_ARM0_CASES),
        unified_rows=read_jsonl(ROOT / DEFAULT_UNIFIED_RUNTIME),
        canary_rows=read_jsonl(ROOT / DEFAULT_CANARY_RUNTIME),
        chunks=read_jsonl(ROOT / DEFAULT_CHUNKS),
    )
    result = summarize_ab(rows)

    assert result["question_signal_counts_by_profile"]["docs_only"] == {"true": 69}
    assert result["question_signal_counts_by_profile"]["mixed"] == {
        "partial": 12,
        "true": 1,
    }
    assert result["docs_only_unchanged"]["chunk_grounded"]["successes"] == 61
    assert result["docs_only_unchanged"]["span_value_grounded"]["successes"] == 45

    assert result["arm0_mixed"]["correct_mixed_partial"]["successes"] == 2
    assert result["arm0_mixed"]["mixed_overclaim"]["successes"] == 10
    assert result["arm_q_mixed"]["correct_mixed_partial"]["successes"] == 10
    assert result["arm_q_mixed"]["correct_mixed_partial_span_strict"]["successes"] == 7
    assert result["arm_q_mixed"]["mixed_overclaim"]["successes"] == 0
    assert result["arm_q_mixed"]["mixed_missing_evidence"]["successes"] == 3

    conversion = result["overclaim_conversion"]
    assert conversion["converted_to_correct_partial"] == 9
    assert conversion["converted_to_missing_evidence"] == 1
    assert conversion["unresolved_overclaim"] == 0
    assert result["existing_correct_mixed_regression_count"] == 1
    assert result["fallback_contract"]["exact_extractive"]["successes"] == 12
    assert result["fallback_contract"]["partial_disclaimer"]["successes"] == 12
    assert result["strict_gate_passed"] is False
    assert result["decision"] == "DEVELOPMENT_NO_GO"

