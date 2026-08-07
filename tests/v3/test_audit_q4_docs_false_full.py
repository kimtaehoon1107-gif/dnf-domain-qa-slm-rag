from __future__ import annotations

import unittest

from src.v3.audit_q4_docs_false_full import CLASSIFICATIONS, summarize, validate_classifications


class Q4DocsFalseFullAuditTest(unittest.TestCase):
    def test_frozen_classifications_cover_six_valid_cases(self) -> None:
        validate_classifications()
        self.assertEqual(len(CLASSIFICATIONS), 6)

    def test_summary_counts_each_earliest_stage_once(self) -> None:
        cases = [
            {
                "earliest_failure_stage": item["stage"],
                "semantic_type": item["semantic_type"],
                "gold_evidence": [{"candidate_present": item["stage"] == "SELECTION_SUPPORT"}],
            }
            for item in CLASSIFICATIONS.values()
        ]
        result = summarize(cases)
        self.assertEqual(result["stage_counts"]["ROUTING_SOURCE_SCOPE"], 4)
        self.assertEqual(result["stage_counts"]["RETRIEVAL"], 1)
        self.assertEqual(result["stage_counts"]["SELECTION_SUPPORT"], 1)
        self.assertEqual(result["stage_counts"]["MEASUREMENT"], 0)


if __name__ == "__main__":
    unittest.main()
