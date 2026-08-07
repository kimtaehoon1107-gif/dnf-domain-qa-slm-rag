from __future__ import annotations

import inspect
import unittest

from src.v3.evaluate_behavioral_decomposition import (
    _prepare_parent_executions,
    build_runtime_rows,
    select_threshold,
)


def _sweep_row(
    threshold: float, exact: int, precision: float, recall: float
) -> dict:
    return {
        "threshold": threshold,
        "route_action_exact": {"successes": exact},
        "decomposition": {
            "precision": {"rate": precision},
            "recall": {"rate": recall},
        },
    }


class EvaluateBehavioralDecompositionTest(unittest.TestCase):
    def test_threshold_selection_uses_recall_floor_then_fixed_tiebreaks(self) -> None:
        sweep = [
            _sweep_row(0.5, 20, 0.50, 1.00),
            _sweep_row(0.8, 22, 0.70, 0.89),
            _sweep_row(1.0, 24, 0.90, 0.78),
        ]

        selected = select_threshold(sweep)

        self.assertEqual(selected["threshold"], 0.8)
        self.assertTrue(selected["recall_floor_satisfied"])
        self.assertFalse(selected["selection_used_development_63"])

    def test_higher_threshold_wins_a_complete_tie(self) -> None:
        sweep = [
            _sweep_row(0.7, 22, 0.70, 0.89),
            _sweep_row(0.8, 22, 0.70, 0.89),
        ]

        self.assertEqual(select_threshold(sweep)["threshold"], 0.8)

    def test_runtime_rows_strip_gold_and_expected_source_fields(self) -> None:
        rows = build_runtime_rows(
            [
                {
                    "dev_id": "case_1",
                    "question": "질문",
                    "as_of": "2026-07-19",
                    "source_ids": ["gold_source"],
                    "gold_chunk_ids": ["gold_chunk"],
                    "gold_document_ids": ["gold_document"],
                    "query_policy": {"expected_route_action": "decompose"},
                }
            ]
        )

        self.assertEqual(
            rows,
            [
                {
                    "case_id": "case_1",
                    "question": "질문",
                    "as_of": "2026-07-19",
                }
            ],
        )

    def test_runtime_execution_signature_has_no_gold_or_expected_source(self) -> None:
        parameters = set(inspect.signature(_prepare_parent_executions).parameters)

        self.assertNotIn("gold_chunk_ids", parameters)
        self.assertNotIn("gold_document_ids", parameters)
        self.assertNotIn("expected_source_ids", parameters)

    def test_runtime_rows_use_router_default_for_null_as_of(self) -> None:
        rows = build_runtime_rows(
            [{"dev_id": "case_1", "question": "질문", "as_of": None}]
        )

        self.assertEqual(rows[0]["as_of"], "2026-07-18")


if __name__ == "__main__":
    unittest.main()
