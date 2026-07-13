from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from make_partial_dev_review import EXTRA_TRUE_IDS, select_source_rows  # noqa: E402


class PartialDevReviewTests(unittest.TestCase):
    def test_selects_partial_rows_and_fixed_true_anchors(self) -> None:
        domain = [
            {"eval_id": "partial", "answerability": "partial"},
            *({"eval_id": eval_id, "answerability": "true"} for eval_id in EXTRA_TRUE_IDS),
        ]
        fresh = [{"eval_id": "fresh", "answerability": "partial"}]
        selected = select_source_rows(domain, fresh)
        self.assertEqual(len(selected), 2 + len(EXTRA_TRUE_IDS))
        self.assertEqual(selected[0][1]["eval_id"], "partial")
        self.assertEqual(selected[1][1]["eval_id"], "fresh")


if __name__ == "__main__":
    unittest.main()
