from __future__ import annotations

import unittest

from src.v3.evaluate_source_aware_retrieval_32 import (
    score_requirement_pools,
    select_ranked_candidates,
    summarize,
)


class SourceAwareRetrieval32Test(unittest.TestCase):
    def test_ranked_selection_enforces_parent_cap(self) -> None:
        hits = [
            {"chunk_id": "c1", "parent_document_id": "p1", "source_id": "s1"},
            {"chunk_id": "c2", "parent_document_id": "p1", "source_id": "s1"},
            {"chunk_id": "c3", "parent_document_id": "p2", "source_id": "s2"},
        ]

        selected = select_ranked_candidates(hits, [3.0, 2.0, 1.0], top_k=3, parent_cap=1)

        self.assertEqual([row["chunk_id"] for row in selected], ["c1", "c3"])

    def test_pool_scoring_is_requirement_aligned(self) -> None:
        reviewed = {
            "evidence_groups": [
                {"group_id": "g1", "acceptable_chunk_ids": ["c1"]},
                {"group_id": "g2", "acceptable_chunk_ids": ["c2"]},
            ]
        }
        pools = [
            {
                "requirement_id": "r1",
                "arm": {"candidate_chunk_ids": ["c1"]},
            },
            {
                "requirement_id": "r2",
                "arm": {"candidate_chunk_ids": ["wrong"]},
            },
        ]

        score = score_requirement_pools(reviewed, pools, arm="arm")

        self.assertFalse(score["all_required_candidates_present"])
        self.assertEqual(
            [row["candidate_present"] for row in score["groups"]], [True, False]
        )

    def test_summary_selects_smallest_non_regressing_improvement(self) -> None:
        rows = [
            {
                "candidate_id": "a",
                "baseline": {"candidate_all_required_coverage": True},
                "source_aware_top_3": {"all_required_candidates_present": True},
                "source_aware_top_5": {"all_required_candidates_present": True},
                "source_aware_top_8": {"all_required_candidates_present": True},
                "source_balanced_top_1_per_source": {
                    "all_required_candidates_present": True
                },
                "baseline_union_source_aware_top_5": {
                    "all_required_candidates_present": True
                },
                "latency_ms": 1,
            },
            {
                "candidate_id": "b",
                "baseline": {"candidate_all_required_coverage": False},
                "source_aware_top_3": {"all_required_candidates_present": False},
                "source_aware_top_5": {"all_required_candidates_present": True},
                "source_aware_top_8": {"all_required_candidates_present": True},
                "source_balanced_top_1_per_source": {
                    "all_required_candidates_present": False
                },
                "baseline_union_source_aware_top_5": {
                    "all_required_candidates_present": True
                },
                "latency_ms": 1,
            },
        ]

        summary = summarize(rows)

        self.assertEqual(summary["selected_arm_for_stage3"], "source_aware_top_5")
        self.assertEqual(summary["decision"], "GO_TO_STAGE3")


if __name__ == "__main__":
    unittest.main()
