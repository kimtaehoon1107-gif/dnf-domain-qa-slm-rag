from __future__ import annotations

import unittest

from src.v3.audit_false_full_cases import (
    CLASSIFICATIONS,
    summarize,
    validate_classifications,
)


class FalseFullAuditTest(unittest.TestCase):
    def test_frozen_classifications_are_exactly_one_valid_type(self) -> None:
        validate_classifications(CLASSIFICATIONS)
        self.assertEqual(len(CLASSIFICATIONS), 9)

    def test_summary_reports_hardcore_and_measurement_counts(self) -> None:
        cases = [
            {
                "classification": item["type"],
                "severity": item["severity"],
                "form": item["form"],
            }
            for item in CLASSIFICATIONS.values()
        ]
        result = summarize(cases)
        self.assertEqual(result["type_counts"]["A_WRONG_ATTRIBUTE"], 2)
        self.assertEqual(result["type_counts"]["B_RETRIEVAL_MISS"], 6)
        self.assertEqual(result["type_counts"]["C_MEASUREMENT_ARTIFACT"], 0)
        self.assertEqual(result["type_counts"]["D_CROSS_PARENT_MISS"], 1)
        self.assertEqual(result["true_hardcore_wrong_attribute_count"], 2)
        self.assertEqual(result["actual_error_count_excluding_measurement_artifact"], 9)
        self.assertEqual(result["severity_counts"], {"catchable": 6, "subtle": 3})


if __name__ == "__main__":
    unittest.main()

