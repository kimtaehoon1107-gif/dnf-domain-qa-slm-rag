from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from make_hard_negative_review_sample import select_requested_rows  # noqa: E402


class HardNegativeReviewSampleTests(unittest.TestCase):
    def test_selects_requested_rows_in_requested_order(self) -> None:
        rows = [{"source_qa_id": "a"}, {"source_qa_id": "b"}]
        self.assertEqual(select_requested_rows(rows, ["b", "a"]), [rows[1], rows[0]])

    def test_rejects_unknown_requested_id(self) -> None:
        with self.assertRaises(ValueError):
            select_requested_rows([{"source_qa_id": "a"}], ["missing"])


if __name__ == "__main__":
    unittest.main()
