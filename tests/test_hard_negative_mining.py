from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mine_hard_negatives import filter_hard_negatives  # noqa: E402


class HardNegativeFilterTests(unittest.TestCase):
    def test_excludes_gold_same_parent_and_heldout(self) -> None:
        hits = [
            {"doc_id": "gold", "rank": 1, "metadata": {"parent_doc_id": "gold_parent"}},
            {"doc_id": "gold_sibling", "rank": 2, "metadata": {"parent_doc_id": "gold_parent"}},
            {"doc_id": "heldout", "rank": 3, "metadata": {"parent_doc_id": "heldout_parent"}},
            {"doc_id": "safe_1", "rank": 4, "metadata": {"parent_doc_id": "safe_parent_1"}},
            {"doc_id": "safe_2", "rank": 5, "metadata": {"parent_doc_id": "safe_parent_2"}},
        ]
        selected = filter_hard_negatives(
            hits,
            gold_chunk_ids={"gold"},
            gold_parent_ids={"gold_parent"},
            heldout_chunk_ids={"heldout"},
            heldout_parent_ids={"heldout_parent"},
            limit=2,
        )
        self.assertEqual([row["doc_id"] for row in selected], ["safe_1", "safe_2"])
        self.assertEqual([row["retrieval_rank"] for row in selected], [4, 5])

    def test_deduplicates_candidates_without_reordering(self) -> None:
        hits = [
            {"doc_id": "safe", "rank": 1, "metadata": {"parent_doc_id": "p1"}},
            {"doc_id": "safe", "rank": 2, "metadata": {"parent_doc_id": "p1"}},
            {"doc_id": "other", "rank": 3, "metadata": {"parent_doc_id": "p2"}},
        ]
        selected = filter_hard_negatives(hits, set(), set(), set(), set(), limit=3)
        self.assertEqual([row["doc_id"] for row in selected], ["safe", "other"])


if __name__ == "__main__":
    unittest.main()
