from __future__ import annotations

from src.v3.diagnose_sufficiency_shadow_generalization_64 import (
    acceptable_evidence_visibility,
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
    assert summary["selector_group_count"] == 0
    assert summary["selector_visible_text_chars"] == 0


def test_acceptable_evidence_visibility_requires_full_coordinate_coverage() -> None:
    requirement = {
        "acceptable_evidence_units": [
            {
                "chunk_id": "c1",
                "start_char": 10,
                "end_char": 30,
            }
        ]
    }
    complete = {
        "E1": {
            "chunk_id": "c1",
            "start_char": 0,
            "end_char": 20,
        },
        "E2": {
            "chunk_id": "c1",
            "start_char": 20,
            "end_char": 40,
        },
    }
    partial = {
        "E1": {
            "chunk_id": "c1",
            "start_char": 10,
            "end_char": 20,
        }
    }

    visible = acceptable_evidence_visibility(requirement, complete)
    missing = acceptable_evidence_visibility(requirement, partial)

    assert visible["reviewed_acceptable_evidence_visible"] is True
    assert visible["visible_acceptable_evidence_refs"] == ["E1", "E2"]
    assert missing["reviewed_acceptable_evidence_visible"] is False


def test_acceptable_evidence_visibility_allows_one_source_separator() -> None:
    requirement = {
        "acceptable_evidence_units": [
            {
                "chunk_id": "c1",
                "start_char": 10,
                "end_char": 30,
            }
        ]
    }
    units = {
        "E1": {
            "chunk_id": "c1",
            "start_char": 10,
            "end_char": 20,
        },
        "E2": {
            "chunk_id": "c1",
            "start_char": 21,
            "end_char": 30,
        },
    }

    visible = acceptable_evidence_visibility(requirement, units)

    assert visible["reviewed_acceptable_evidence_visible"] is True
    assert visible["visible_acceptable_evidence_refs"] == ["E1", "E2"]
