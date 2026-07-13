from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from apply_qa_corrections import apply_corrections  # noqa: E402


class ApplyQaCorrectionsTests(unittest.TestCase):
    def test_applies_updates_and_preserves_other_rows(self) -> None:
        rows = [{"qa_id": "a", "question": "old"}, {"qa_id": "b", "question": "same"}]
        corrections = [{"qa_id": "a", "updates": {"question": "new", "answerability": "true"}}]
        result = apply_corrections(rows, corrections)
        self.assertEqual(result[0]["question"], "new")
        self.assertEqual(result[0]["answerability"], "true")
        self.assertEqual(result[1], rows[1])

    def test_rejects_unknown_id(self) -> None:
        with self.assertRaises(ValueError):
            apply_corrections([{"qa_id": "a"}], [{"qa_id": "missing", "updates": {"question": "x"}}])


if __name__ == "__main__":
    unittest.main()
