import unittest

from src.v3.evaluate_requirement_surface_query_ab import (
    TARGET_LITERAL_SPANS,
    _carry_arm0,
    literal_provisional_sibling_hit,
)


class RequirementSurfaceQueryAbTests(unittest.TestCase):
    def test_provisional_sibling_requires_literal_spans_not_chunk_membership(self) -> None:
        heading_only = [
            {
                "citations": [
                    {
                        "chunk_id": "guide_chunk",
                        "text": "## 광휘의 행로",
                    }
                ]
            }
        ]
        self.assertFalse(literal_provisional_sibling_hit(heading_only))
        exact = [
            {
                "citations": [
                    {"chunk_id": "guide_chunk", "text": TARGET_LITERAL_SPANS[0]},
                    {"chunk_id": "guide_chunk", "text": TARGET_LITERAL_SPANS[1]},
                ]
            }
        ]
        self.assertTrue(literal_provisional_sibling_hit(exact))

    def test_noop_row_uses_entity_arm_as_both_sides(self) -> None:
        score = {"all_groups_hit": True}
        decisions = [{"requirement_id": "r1", "citations": []}]
        carried = _carry_arm0(
            {
                "case_id": "case",
                "dataset": "dev",
                "evaluation_block": "frozen_docs_69",
                "question": "질문",
                "source_id": None,
                "arm1_decisions": decisions,
                "arm1_score": score,
                "entity_anchor_audit": [],
                "sibling_proposal": None,
                "exact_slices": True,
                "temporal_violation_chunk_ids": [],
            }
        )
        self.assertEqual(carried["arm0_decisions"], carried["arm1_decisions"])
        self.assertEqual(carried["arm0_score"], carried["arm1_score"])
        self.assertFalse(carried["surface_query_applied"])


if __name__ == "__main__":
    unittest.main()
