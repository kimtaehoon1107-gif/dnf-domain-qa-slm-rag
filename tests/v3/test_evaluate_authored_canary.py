from __future__ import annotations

import unittest

from src.v3.evaluate_authored_canary import (
    _single_baseline_response,
    aggregate_canary,
    wilson_interval,
)


def _passing_rows() -> list[dict]:
    sources = [
        "dnf_notice",
        "dnf_update",
        "dnf_event",
        "dnf_game_guide",
        "dnf_faq",
        "dnf_account_policy",
        "dnf_seria_shop",
        "dnf_monthly_item",
    ]
    rows = []
    for ordinal in range(32):
        rows.append(
            {
                "case_id": f"case_{ordinal}",
                "source_ids": [sources[ordinal // 4]],
                "answerability": "partial" if ordinal < 5 else "true",
                "route_action_exact": True,
                "group_results": [
                    {
                        "group_id": "evidence_1",
                        "retrieval_hit": True,
                        "selected_hit": True,
                        "baseline_cited_hit": ordinal != 0,
                        "canonical_cited_hit": True,
                        "canonical_claim_token_recall": 1.0,
                        "claim_complete": True,
                    }
                ],
                "temporal_revision_violations": [],
                "false_realtime_evidence_exposure": False,
                "partial_disclaimer": ordinal < 5,
            }
        )
    return rows


class EvaluateAuthoredCanaryTest(unittest.TestCase):
    def test_preregistered_gates_pass_for_complete_rows(self) -> None:
        aggregate = aggregate_canary(_passing_rows())

        self.assertTrue(aggregate["go"])
        self.assertTrue(all(aggregate["gates"].values()))
        self.assertEqual(aggregate["metrics"]["strict_improvement_count"], 1)
        self.assertEqual(aggregate["metrics"]["strict_regression_count"], 0)
        self.assertEqual(
            aggregate["metrics"]["partial_disclaimer"]["successes"], 5
        )

    def test_any_strict_regression_is_no_go(self) -> None:
        rows = _passing_rows()
        rows[1]["group_results"][0].update(
            {"baseline_cited_hit": True, "canonical_cited_hit": False}
        )

        aggregate = aggregate_canary(rows)

        self.assertFalse(aggregate["go"])
        self.assertFalse(aggregate["gates"]["strict_regression_zero"])

    def test_temporal_and_false_exposure_are_hard_gates(self) -> None:
        rows = _passing_rows()
        rows[2]["temporal_revision_violations"] = ["wrong_revision"]
        rows[3]["false_realtime_evidence_exposure"] = True

        aggregate = aggregate_canary(rows)

        self.assertFalse(aggregate["gates"]["temporal_revision_violation_zero"])
        self.assertFalse(
            aggregate["gates"]["false_realtime_evidence_exposure_zero"]
        )

    def test_wilson_interval_is_bounded_and_deterministic(self) -> None:
        self.assertEqual(wilson_interval(0, 0), [0.0, 0.0])
        self.assertEqual(wilson_interval(9, 10), [0.59584997, 0.98212379])
        lower, upper = wilson_interval(4, 4)
        self.assertGreaterEqual(lower, 0.0)
        self.assertLessEqual(upper, 1.0)

    def test_historical_full_date_does_not_require_month_window_metadata(self) -> None:
        response = _single_baseline_response(
            {
                "dev_id": "case_historical",
                "question": "2025년 4월 26일 정책은 무엇이었어?",
            },
            {
                "route": {
                    "answerability": "true",
                    "time_scope": "historical",
                    "source_ids": ["dnf_account_policy"],
                    "source_kinds": ["account_policy"],
                },
                "hits": [],
                "temporal_resolution": None,
            },
            [],
            {},
        )

        self.assertEqual(response["runtime_status"], "blocked_no_verified_evidence")


if __name__ == "__main__":
    unittest.main()
