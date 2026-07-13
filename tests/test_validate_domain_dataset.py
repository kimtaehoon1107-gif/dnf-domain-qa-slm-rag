from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from validate_domain_dataset import gold_position_balance  # noqa: E402


def raft_row(row_id: str, gold_position: int) -> dict:
    documents = [
        {"doc_id": "d1"},
        {"doc_id": "d2"},
        {"doc_id": "d3"},
    ]
    return {
        "raft_id": row_id,
        "answerability": "partial",
        "documents": documents,
        "citations": [documents[gold_position - 1]["doc_id"]],
    }


class ValidateDomainDatasetTests(unittest.TestCase):
    def test_reports_balanced_gold_positions(self) -> None:
        stats = gold_position_balance(
            [raft_row("r1", 1), raft_row("r2", 2), raft_row("r3", 3)]
        )
        self.assertEqual(stats["position_counts"], {"1": 1, "2": 1, "3": 1})
        self.assertAlmostEqual(stats["max_position_share"], 1 / 3)

    def test_reports_missing_gold_position(self) -> None:
        row = raft_row("r1", 1)
        row["citations"] = ["not_in_context"]
        stats = gold_position_balance([row])
        self.assertEqual(stats["rows_without_gold_position"], 1)
        self.assertIsNone(stats["max_position_share"])


if __name__ == "__main__":
    unittest.main()
