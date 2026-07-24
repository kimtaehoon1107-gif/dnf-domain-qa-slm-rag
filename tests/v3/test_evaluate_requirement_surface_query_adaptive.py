import json

import pytest

from src.v3.evaluate_requirement_surface_query_adaptive import (
    close_aborted_run,
    compare_summaries,
)


def _summary(*, literal: int, applied: int, false_full: int) -> dict:
    ratio = lambda value: {"successes": value, "total": 32, "rate": value / 32}
    return {
        "metrics": {
            "arm1_candidate_all_required_coverage": ratio(22),
            "arm1_all_required_evidence": ratio(22),
            "arm1_all_literal_spans": ratio(literal),
            "positive_application": {
                "successes": applied,
                "total": 16,
                "rate": applied / 16,
            },
            "control_bypass": {"successes": 16, "total": 16, "rate": 1.0},
            "arm1_false_full_case_ids": [f"case-{i}" for i in range(false_full)],
            "runtime_requirement_count_mismatch_case_ids": ["case-a", "case-b"],
        }
    }


def test_comparison_keeps_adaptive_delta_separate_from_original_sealed_result():
    comparison = compare_summaries(
        _summary(literal=12, applied=0, false_full=20),
        _summary(literal=16, applied=14, false_full=16),
    )

    assert comparison["positive_application"] == {
        "before": 0,
        "after": 14,
        "delta": 14,
    }
    assert comparison["arm1_all_literal_spans"]["delta"] == 4
    assert comparison["false_full"]["delta"] == -4


def test_aborted_run_can_be_closed_but_completed_run_cannot(tmp_path):
    evaluation = tmp_path / "data/v3/evaluation"
    evaluation.mkdir(parents=True)
    started = evaluation / "requirement_surface_query_adaptive_execution_started.json"
    started.write_text(
        json.dumps({"status": "STARTED_ADAPTIVE_RUN_CONSUMED", "run_key": "old"}),
        encoding="utf-8",
    )

    closure = close_aborted_run(tmp_path, "old")

    assert closure["path"].startswith("data/v3/evaluation/")
    completed = evaluation / "requirement_surface_query_adaptive_execution_done.json"
    completed.write_text(
        json.dumps({"status": "COMPLETED_ADAPTIVE", "run_key": "old"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="cannot be superseded"):
        close_aborted_run(tmp_path, "old")
