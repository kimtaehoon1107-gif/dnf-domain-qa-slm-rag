from __future__ import annotations

import unittest

from src.v3.evaluate_requirement_slot_coverage import (
    _safe_threshold,
    _single_parent_coverable,
    select_threshold,
)


def _metrics(
    threshold: float,
    *,
    complete: int,
    cited: int,
    recall: float,
    precision: float,
    false_partial: int = 0,
) -> dict:
    return {
        "threshold": threshold,
        "same_parent_multi_field": {
            "after_claim_completeness": {"successes": complete},
            "after_cited_group_hit": {"successes": cited},
        },
        "signal_a_slot_enumeration": {
            "recall": {"rate": recall},
            "precision": {"rate": precision},
        },
        "safety": {
            "single_field_group_regressions": 0,
            "runtime_false_citations": 0,
            "strict_unsupported_slot_citations": 0,
            "false_partial_candidate_complete": false_partial,
        },
    }


class EvaluateRequirementSlotCoverageTest(unittest.TestCase):
    def test_threshold_selection_applies_safety_before_quality(self) -> None:
        unsafe_best = _metrics(
            0.5,
            complete=9,
            cited=18,
            recall=1.0,
            precision=1.0,
            false_partial=1,
        )
        safe = _metrics(
            0.8,
            complete=8,
            cited=17,
            recall=0.8,
            precision=0.7,
        )

        selected = select_threshold([unsafe_best, safe])

        self.assertEqual(selected["threshold"], 0.8)
        self.assertTrue(selected["safety_gate_satisfied"])
        self.assertFalse(selected["selection_used_development_63"])

    def test_threshold_selection_uses_higher_threshold_for_complete_tie(self) -> None:
        first = _metrics(0.7, complete=8, cited=17, recall=0.8, precision=0.7)
        second = _metrics(0.8, complete=8, cited=17, recall=0.8, precision=0.7)

        self.assertEqual(select_threshold([first, second])["threshold"], 0.8)

    def test_no_safe_threshold_is_explicit(self) -> None:
        row = _metrics(
            0.8,
            complete=8,
            cited=17,
            recall=0.8,
            precision=0.7,
            false_partial=1,
        )

        selected = select_threshold([row])

        self.assertFalse(_safe_threshold(row))
        self.assertFalse(selected["safety_gate_satisfied"])

    def test_same_parent_requires_one_parent_covering_every_group(self) -> None:
        chunks = {
            "a": {"parent_document_id": "doc-1"},
            "b": {"parent_document_id": "doc-1"},
            "c": {"parent_document_id": "doc-2"},
        }
        same = {
            "dev_id": "same",
            "evidence_groups": [
                {"acceptable_chunk_ids": ["a"]},
                {"acceptable_chunk_ids": ["b"]},
            ],
        }
        cross = {
            "dev_id": "cross",
            "evidence_groups": [
                {"acceptable_chunk_ids": ["a"]},
                {"acceptable_chunk_ids": ["c"]},
            ],
        }

        self.assertTrue(_single_parent_coverable(same, chunks))
        self.assertFalse(_single_parent_coverable(cross, chunks))


if __name__ == "__main__":
    unittest.main()
