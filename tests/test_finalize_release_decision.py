from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finalize_release_decision import failed_pre_gates, selection_tuple  # noqa: E402


class FinalizeReleaseDecisionTests(unittest.TestCase):
    def test_selection_tuple_uses_frozen_order(self):
        metrics = {
            "human_strict_requirement_joint": 3,
            "human_exact_citation": 12,
            "fresh_partial_joint": 3,
            "fresh_exact_citation": 14,
            "unsupported_explicit_abstention": 8,
        }
        self.assertEqual(selection_tuple(metrics), (3, 12, 3, 14, 8))

    def test_pre_gates_report_false_and_abstention_failures(self):
        metrics = {
            "fresh_exact_citation": 14,
            "fresh_partial_joint": 3,
            "fresh_false_joint": 5,
            "human_exact_citation": 12,
            "human_partial_joint": 8,
            "human_strict_requirement_joint": 3,
            "grounded_answered_and_cited": 11,
            "unsupported_explicit_abstention": 8,
            "unsupported_over_answer": 0,
            "unsafe_answer_rows": 0,
        }
        failures = {item["gate"] for item in failed_pre_gates(metrics)}
        self.assertEqual(
            failures,
            {"fresh_false_joint", "unsupported_explicit_abstention"},
        )


if __name__ == "__main__":
    unittest.main()
