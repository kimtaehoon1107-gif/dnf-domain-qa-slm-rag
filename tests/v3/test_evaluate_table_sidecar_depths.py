from __future__ import annotations

from src.v3.evaluate_table_sidecar_depths import coverage_metrics


def test_coverage_metrics_requires_every_group_for_question_hit() -> None:
    evaluations = [
        {
            "dev_id": "case",
            "evidence_groups": [
                {"acceptable_chunk_ids": ["a"]},
                {"acceptable_chunk_ids": ["b", "b_sibling"]},
            ],
        }
    ]

    partial = coverage_metrics(evaluations, {"case": {"a"}})
    complete = coverage_metrics(evaluations, {"case": {"a", "b_sibling"}})

    assert partial["evidence_groups_hit"] == 1
    assert partial["all_groups_questions"] == 0
    assert complete["evidence_groups_hit"] == 2
    assert complete["all_groups_questions"] == 1
