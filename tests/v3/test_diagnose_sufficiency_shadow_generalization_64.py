from __future__ import annotations

from src.v3.diagnose_sufficiency_shadow_generalization_64 import (
    summarize_shadow,
)


def test_shadow_summary_separates_triggers_from_excluded_requirements() -> None:
    rows = [
        {
            "slot_ordinal": 1,
            "requirements": [
                {
                    "assessable": True,
                    "would_trigger": True,
                    "reason": "same_group_support_missing",
                },
                {
                    "assessable": False,
                    "would_trigger": False,
                    "reason": "unregistered_relation_excluded",
                },
            ],
        },
        {
            "slot_ordinal": 2,
            "requirements": [
                {
                    "assessable": False,
                    "would_trigger": False,
                    "reason": "table_branch_excluded",
                }
            ],
        },
    ]

    summary = summarize_shadow(rows)

    assert summary["question_count"] == 2
    assert summary["requirement_count"] == 3
    assert summary["assessable_requirement_count"] == 1
    assert summary["would_trigger_requirement_count"] == 1
    assert summary["would_trigger_slots"] == [1]
    assert summary["excluded_table_requirement_count"] == 1
    assert summary["excluded_unregistered_requirement_count"] == 1
