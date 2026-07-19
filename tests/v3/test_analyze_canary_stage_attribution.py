from __future__ import annotations

import unittest

from src.v3.analyze_canary_stage_attribution import (
    _dominance,
    _histogram,
    attribute_case,
)


def _dev(*, answerability: str = "true") -> dict:
    return {
        "dev_id": "case_1",
        "query_ordinal": 1,
        "question": "표면 키워드 없이 여러 조건을 묻는 문장",
        "source_ids": ["dnf_notice"],
        "query_kind": "multi",
        "time_scope": "current",
        "answerability": answerability,
        "query_policy": {"expected_route_action": "decompose"},
    }


def _group(**updates: object) -> dict:
    row = {
        "group_id": "evidence_1",
        "retrieval_hit": True,
        "selected_hit": True,
        "canonical_cited_hit": True,
        "claim_complete": True,
    }
    row.update(updates)
    return row


def _case(**updates: object) -> dict:
    row = {
        "case_id": "case_1",
        "query_ordinal": 1,
        "route_action_exact": True,
        "actual_route": {"route_action": "decompose"},
        "group_results": [_group()],
        "temporal_revision_violations": [],
        "false_realtime_evidence_exposure": False,
        "partial_disclaimer": False,
    }
    row.update(updates)
    return row


class AnalyzeCanaryStageAttributionTest(unittest.TestCase):
    def test_each_case_is_attributed_to_its_first_failed_stage(self) -> None:
        scenarios = [
            (_case(route_action_exact=False), "ROUTING"),
            (_case(group_results=[_group(retrieval_hit=False)]), "RETRIEVAL"),
            (_case(group_results=[_group(selected_hit=False)]), "SELECTION"),
            (
                _case(group_results=[_group(canonical_cited_hit=False)]),
                "CLAIM_COVERAGE",
            ),
            (_case(temporal_revision_violations=["wrong_revision"]), "VERIFY"),
            (_case(), "PASS"),
        ]

        for case, expected in scenarios:
            with self.subTest(expected=expected):
                self.assertEqual(
                    attribute_case(_dev(), case)["first_failure_stage"], expected
                )

    def test_upstream_routing_failure_prevents_downstream_double_counting(self) -> None:
        row = attribute_case(
            _dev(),
            _case(
                route_action_exact=False,
                group_results=[
                    _group(
                        retrieval_hit=False,
                        selected_hit=False,
                        canonical_cited_hit=False,
                        claim_complete=False,
                    )
                ],
                temporal_revision_violations=["wrong_revision"],
                false_realtime_evidence_exposure=True,
            ),
        )

        self.assertEqual(row["first_failure_stage"], "ROUTING")
        self.assertEqual(
            row["group_attribution"][0]["first_failure_stage"], "ROUTING"
        )

    def test_missing_partial_disclaimer_is_claim_coverage_failure(self) -> None:
        row = attribute_case(
            _dev(answerability="partial"), _case(partial_disclaimer=False)
        )

        self.assertEqual(row["first_failure_stage"], "CLAIM_COVERAGE")
        self.assertEqual(row["group_attribution"][0]["first_failure_stage"], "PASS")

    def test_output_excludes_question_and_gold_text(self) -> None:
        row = attribute_case(_dev(), _case())

        self.assertNotIn("question", row)
        self.assertNotIn("gold_answer", row)
        self.assertFalse(row["question_text_included"])
        self.assertFalse(row["gold_text_included"])
        self.assertIn("multi_without_surface_keywords", row["type_tags"])

    def test_buckets_below_five_are_hints_and_routing_dominates(self) -> None:
        histogram = _histogram(
            ["ROUTING"] * 6 + ["RETRIEVAL"] * 4 + ["PASS"] * 2, 12
        )

        result = _dominance(histogram)

        self.assertEqual(result["dominant_buckets"], ["ROUTING"])
        self.assertEqual(result["buckets_with_at_least_five_failures"], ["ROUTING"])
        self.assertEqual(result["secondary_supported_buckets"], [])
        self.assertEqual(
            result["buckets_below_five_are_hints_only"], ["RETRIEVAL"]
        )
        self.assertEqual(result["required_first_approach"], "ROBUST_ROUTING")
        self.assertEqual(
            result["downstream_change_before_routing_gate"], "PROHIBITED"
        )


if __name__ == "__main__":
    unittest.main()
