from __future__ import annotations

import unittest
from collections import Counter

from src.v3.build_authored_validation_v3_2 import SLOTS


class AuthoredValidationV32BuilderTest(unittest.TestCase):
    def test_slots_are_balanced_and_unique(self) -> None:
        self.assertEqual(len(SLOTS), 24)
        self.assertEqual(set(Counter(slot["source_id"] for slot in SLOTS).values()), {3})
        self.assertEqual(len({slot["question"] for slot in SLOTS}), 24)

    def test_every_slot_has_explicit_evidence(self) -> None:
        for slot in SLOTS:
            self.assertTrue(slot["question"].strip())
            self.assertTrue(slot["spans"])
            self.assertTrue(all(span.strip() for span in slot["spans"]))


if __name__ == "__main__":
    unittest.main()
