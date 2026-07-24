from __future__ import annotations

from src.v3.evaluate_subject_anchored_retrieval_ab import summarize


def _row(
    slot: int,
    *,
    baseline: bool,
    arm: bool,
    blocked: bool = False,
    strict: bool = False,
    false_full: bool = False,
) -> dict:
    return {
        "candidate_id": f"case-{slot}",
        "slot_ordinal": slot,
        "plan": {"subject": "길드"},
        "baseline_candidate_covered": baseline,
        "arm_candidate_covered": arm,
        "arm_candidate_ids": ["a", "b"],
        "blocked_citations": [{"chunk_id": "x"}] if blocked else [],
        "baseline_all_evidence_spans_hit": strict,
        "baseline_false_full": false_full,
    }


def test_summary_reports_new_coverage_and_safe_blocking() -> None:
    result = summarize(
        [
            _row(1, baseline=True, arm=True, strict=True),
            _row(2, baseline=False, arm=True, blocked=True, false_full=True),
            _row(3, baseline=False, arm=False),
        ]
    )

    assert result["baseline_candidate_covered"] == 1
    assert result["arm_candidate_covered"] == 2
    assert result["newly_covered_slots"] == [2]
    assert result["candidate_regression_slots"] == []
    assert result["false_full_blocked_slots"] == [2]
    assert result["strict_success_blocked_slots"] == []
