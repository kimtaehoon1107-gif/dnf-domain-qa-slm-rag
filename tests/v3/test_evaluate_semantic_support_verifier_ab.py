from __future__ import annotations

import unittest

from src.v3.evaluate_semantic_support_verifier_ab import (
    diagnostic_points,
    filter_decisions,
    operating_point_pass,
    select_operating_point,
    simulate_filtered_arm,
)


class SemanticSupportVerifierABTest(unittest.TestCase):
    def test_filter_decisions_uses_pair_score_and_baseline_support(self) -> None:
        pairs = [
            {
                "pair_id": "p1",
                "requirement_index": 1,
                "span": {"span_id": "s1"},
            },
            {
                "pair_id": "p2",
                "requirement_index": 2,
                "span": {"span_id": "s2"},
            },
        ]
        decisions = [
            {"requirement_id": "r1", "spans": [{"span_id": "s1", "chunk_id": "c1"}]},
            {"requirement_id": "r2", "spans": [{"span_id": "s2", "chunk_id": "c2"}]},
        ]
        result = filter_decisions(
            pairs,
            decisions,
            {1},
            {"p1": 0.9, "p2": 0.9},
            bar=0.5,
        )
        self.assertEqual(result[0]["status"], "supported_exact")
        self.assertEqual(result[1]["status"], "unsupported")

    def test_filtering_common_parent_can_surface_cross_parent(self) -> None:
        baseline = {"safety_reason": None}
        decisions = [
            {
                "status": "supported_exact",
                "spans": [{"chunk_id": "c1"}, {"chunk_id": "common"}],
            },
            {
                "status": "supported_exact",
                "spans": [{"chunk_id": "c2"}],
            },
        ]
        arm = simulate_filtered_arm(
            baseline,
            decisions,
            {"c1": "p1", "common": "p1", "c2": "p2"},
        )
        self.assertTrue(arm["cross_parent_candidate"])
        self.assertEqual(arm["route_action"], "decompose_candidate")

    def test_operating_point_never_trades_grounded_guard(self) -> None:
        good = self._metric(grounded=73, false_full=7, bar=0.2)
        lower_false_but_regressed = self._metric(grounded=72, false_full=0, bar=0.3)
        self.assertTrue(operating_point_pass(good))
        self.assertFalse(operating_point_pass(lower_false_but_regressed))
        self.assertEqual(select_operating_point([lower_false_but_regressed, good]), good)

    def test_diagnostic_point_surfaces_the_closest_unsafe_tradeoff(self) -> None:
        baseline = self._metric(grounded=73, false_full=9, bar=0.0)
        closer = self._metric(grounded=70, false_full=7, bar=0.1)
        worse = self._metric(grounded=60, false_full=2, bar=0.9)
        points = diagnostic_points([baseline, closer, worse])
        self.assertEqual(points["best_guard_preserving"], baseline)
        self.assertEqual(points["closest_minimum_reduction"], closer)

    @staticmethod
    def _metric(*, grounded: int, false_full: int, bar: float) -> dict:
        return {
            "bar": bar,
            "answerable": {
                "grounded_answer": {"successes": grounded},
                "false_full_answer": {"successes": false_full},
                "overreject": {"successes": 0},
            },
            "reject_correct": {"successes": 11},
            "realtime_safe_abstain": {"successes": 2},
            "realtime_static_exposure": {"successes": 0},
            "cross_parent_trigger": {"successes": 0},
            "pair_proxy": {"recall": 0.5},
        }


if __name__ == "__main__":
    unittest.main()
