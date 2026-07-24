from __future__ import annotations

import unittest
from collections import Counter

from src.v3.audit_authored_validation_v3_2_failures import CLASSIFICATIONS, validate_classifications


class AuthoredValidationFailureAuditTest(unittest.TestCase):
    def test_classifications_capture_repeated_stage_pattern(self) -> None:
        validate_classifications()
        counts = Counter(item["stage"] for item in CLASSIFICATIONS.values())
        self.assertEqual(len(CLASSIFICATIONS), 8)
        self.assertEqual(counts["ROUTING_SOURCE_SCOPE"], 5)
        self.assertEqual(counts["RETRIEVAL"], 1)
        self.assertEqual(counts["SELECTION_SUPPORT"], 1)
        self.assertEqual(counts["MEASUREMENT"], 1)


if __name__ == "__main__":
    unittest.main()
