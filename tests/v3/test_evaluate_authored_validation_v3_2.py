from __future__ import annotations

import unittest

from src.v3.evaluate_authored_validation_v3_2 import classify_earliest_failure, summarize


class AuthoredValidationV32EvaluatorTest(unittest.TestCase):
    def test_failure_attribution_is_upstream_first(self) -> None:
        evaluation = {
            "source_ids": ["dnf_faq"],
            "gold_chunk_ids": ["gold"],
        }
        route_miss = {
            "route": {"source_ids": ["dnf_game_guide"]},
            "retrieval": {"selected_chunk_ids": []},
        }
        retrieval_miss = {
            "route": {"source_ids": ["dnf_faq"]},
            "retrieval": {"selected_chunk_ids": ["other"]},
        }
        selection_miss = {
            "route": {"source_ids": ["dnf_faq"]},
            "retrieval": {"selected_chunk_ids": ["gold"]},
        }
        self.assertEqual(
            classify_earliest_failure(evaluation, route_miss, False),
            "ROUTING_SOURCE_SCOPE",
        )
        self.assertEqual(
            classify_earliest_failure(evaluation, retrieval_miss, False),
            "RETRIEVAL",
        )
        self.assertEqual(
            classify_earliest_failure(evaluation, selection_miss, False),
            "SELECTION_SUPPORT",
        )

    def test_summary_applies_preregistered_gate(self) -> None:
        rows = []
        for source_index in range(8):
            for item_index in range(3):
                passed = item_index < 2
                rows.append(
                    {
                        "source_id": f"source_{source_index}",
                        "score": {
                            "all_groups_hit": passed,
                            "false_full": not passed and source_index < 3,
                            "honest_partial_or_abstain": not passed and source_index >= 3,
                            "exact_citations": True,
                            "temporal_violation_chunk_ids": [],
                            "earliest_failure_stage": None if passed else "RETRIEVAL",
                        },
                        "runtime": {"latency_ms": 10 + source_index},
                    }
                )
        result = summarize(rows)
        self.assertEqual(result["all_groups_covered"]["successes"], 16)
        self.assertFalse(result["gate_passed"])
        self.assertEqual(result["false_full"]["successes"], 3)


if __name__ == "__main__":
    unittest.main()
