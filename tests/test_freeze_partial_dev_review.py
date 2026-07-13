from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freeze_partial_dev_review import freeze_rows  # noqa: E402


class FreezePartialDevReviewTests(unittest.TestCase):
    def test_freezes_approved_grounded_row(self) -> None:
        review = [
            {
                "candidate_id": "p1",
                "human_decision": "approve",
                "human_question": "사실과 내 선택을 알려줘?",
                "human_gold_answer": "사실은 A입니다. 개인 선택은 확정할 수 없습니다.",
                "evidence_span": "사실은 A",
                "expected_doc_id": "parent",
                "expected_chunk_ids": "chunk",
                "source_set": "domain",
                "source_row_id": "source",
                "review_notes": "ok",
            }
        ]
        frozen = freeze_rows(review, {"chunk": {"text": "문서의 사실은 A 입니다."}}, set())
        self.assertEqual(frozen[0]["answerability"], "partial")
        self.assertEqual(frozen[0]["expected_chunk_ids"], ["chunk"])

    def test_rejects_train_question_overlap(self) -> None:
        review = [
            {
                "candidate_id": "p1",
                "human_decision": "approve",
                "human_question": "same",
                "human_gold_answer": "answer",
                "evidence_span": "evidence",
                "expected_doc_id": "parent",
                "expected_chunk_ids": "chunk",
            }
        ]
        with self.assertRaises(ValueError):
            freeze_rows(review, {"chunk": {"text": "evidence"}}, {"same"})


if __name__ == "__main__":
    unittest.main()
