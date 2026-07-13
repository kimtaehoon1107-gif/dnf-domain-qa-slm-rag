from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mine_hard_negatives import (  # noqa: E402
    filter_hard_negatives,
    load_human_blocklist,
    reusable_negative_row,
)


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

    def test_rejects_semantically_duplicate_answer_evidence(self) -> None:
        evidence = "입장 레벨 115 이상이며 모험가 명성 90000 이상이 필요합니다"
        hits = [
            {
                "doc_id": "duplicate_answer",
                "rank": 1,
                "text": "이 콘텐츠는 입장 레벨 115 이상이며 모험가 명성 90000 이상이 필요합니다.",
                "metadata": {"parent_doc_id": "p1"},
            },
            {
                "doc_id": "safe",
                "rank": 2,
                "text": "이벤트 보상은 우편으로 지급됩니다.",
                "metadata": {"parent_doc_id": "p2"},
            },
        ]
        selected = filter_hard_negatives(
            hits,
            set(),
            set(),
            set(),
            set(),
            limit=1,
            evidence_span=evidence,
            max_evidence_token_recall=0.5,
        )
        self.assertEqual([row["doc_id"] for row in selected], ["safe"])

    def test_excludes_human_rejected_pair(self) -> None:
        hits = [
            {"doc_id": "human_rejected", "rank": 1, "metadata": {"parent_doc_id": "p1"}},
            {"doc_id": "safe", "rank": 2, "metadata": {"parent_doc_id": "p2"}},
        ]
        selected = filter_hard_negatives(
            hits, set(), set(), set(), set(), limit=1, blocked_doc_ids={"human_rejected"}
        )
        self.assertEqual([row["doc_id"] for row in selected], ["safe"])

    def test_loads_no_votes_from_review_csv(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            path.write_text(
                "source_qa_id,negative_1_doc_id,negative_1_valid_non_answer,"
                "negative_2_doc_id,negative_2_valid_non_answer,negative_3_doc_id,negative_3_valid_non_answer\n"
                "qa_1,bad,no,good,yes,,\n",
                encoding="utf-8",
            )
            self.assertEqual(load_human_blocklist(path), {"qa_1": {"bad"}})

    def test_reuse_requires_unchanged_question_and_unblocked_negatives(self) -> None:
        existing = {
            "question": "same",
            "answerability": "true",
            "gold_chunk_ids": ["gold"],
            "gold_parent_ids": ["parent"],
            "hard_negatives": [{"doc_id": "negative", "parent_doc_id": "negative_parent"}],
        }
        common = dict(
            existing=existing,
            gold_chunks={"gold"},
            gold_parents={"parent"},
            heldout_chunks=set(),
            heldout_parents=set(),
            negatives_per_row=1,
        )
        self.assertTrue(
            reusable_negative_row(
                qa_row={"question": "same", "answerability": "true"},
                blocked_doc_ids=set(),
                **common,
            )
        )
        self.assertFalse(
            reusable_negative_row(
                qa_row={"question": "changed", "answerability": "true"},
                blocked_doc_ids=set(),
                **common,
            )
        )
        self.assertFalse(
            reusable_negative_row(
                qa_row={"question": "same", "answerability": "true"},
                blocked_doc_ids={"negative"},
                **common,
            )
        )


if __name__ == "__main__":
    unittest.main()
