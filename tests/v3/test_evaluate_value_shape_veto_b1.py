from __future__ import annotations

from src.v3.evaluate_value_shape_veto_b1 import evaluate_gate


def _case(case_id: str, *, grounded0: bool, grounded1: bool, false0: bool, false1: bool, vetoed: bool = False) -> dict:
    def arm(grounded: bool, false_full: bool) -> dict:
        return {
            "score": {
                "grounded_answer": grounded,
                "false_full_answer": false_full,
                "honest_partial": False,
                "false_partial": False,
                "answerable_overreject": False,
                "reject_correct": False,
                "realtime_safe_abstain": False,
                "realtime_static_exposure": False,
            }
        }

    return {
        "case_id": case_id,
        "answerability_target": "answerable_docs",
        "arm0": arm(grounded0, false0),
        "arm_b1": arm(grounded1, false1),
        "requirement_audits": [{"vetoed": vetoed}],
    }


def test_gate_rejects_any_grounded_regression() -> None:
    rows = [
        _case("regressed", grounded0=True, grounded1=False, false0=False, false1=False, vetoed=True)
    ]
    result = evaluate_gate(rows)
    assert not result["pass"]
    assert result["grounded_regression_case_ids"] == ["regressed"]
