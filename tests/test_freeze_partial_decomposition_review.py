from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from freeze_partial_decomposition_review import freeze_reviewed_rows  # noqa: E402


def candidate(candidate_id: str, question: str = "사실 알려줘? 개인 선택도 정해줘.") -> dict:
    return {
        "qa_id": candidate_id,
        "question": question,
        "gold_answer": "사실은 A입니다. 개인 선택은 판단할 수 없습니다.",
        "expected_answer": "사실은 A입니다. 개인 선택은 판단할 수 없습니다.",
        "source_qa_id": "source_1",
        "expected_doc_id": "parent_train",
        "expected_chunk_id": "chunk_train",
        "expected_evidence_doc_ids": ["parent_train"],
        "expected_chunk_ids": ["chunk_train"],
        "source_question": "사실 알려줘?",
        "grounded_answer": "사실은 A입니다.",
        "evidence_span": "사실은 A",
        "unsupported_request": "개인 선택도 정해줘.",
        "targeted_abstention": "개인 선택은 판단할 수 없습니다.",
    }


def review_for(row: dict, decision: str = "approve") -> dict[str, str]:
    return {
        "candidate_id": row["qa_id"],
        "source_qa_id": row["source_qa_id"],
        "expected_doc_id": row["expected_doc_id"],
        "expected_chunk_ids": "|".join(row["expected_chunk_ids"]),
        "source_question": row["source_question"],
        "grounded_answer": row["grounded_answer"],
        "evidence_span": row["evidence_span"],
        "unsupported_request": row["unsupported_request"],
        "targeted_abstention": row["targeted_abstention"],
        "proposed_question": row["question"],
        "proposed_answer": row["gold_answer"],
        "grounded_fact_correct": "yes",
        "unsupported_request_natural": "yes",
        "targeted_abstention_correct": "yes",
        "human_decision": decision,
        "human_question": "",
        "human_answer": "",
        "review_notes": "checked",
    }


class FreezePartialDecompositionReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = {"chunk_train": {"text": "문서에서 사실은 A라고 안내합니다."}}

    def test_applies_approve_rewrite_and_reject(self) -> None:
        rows = [candidate("p1"), candidate("p2", "두 번째 사실? 개인 선택도?"), candidate("p3", "세 번째 사실?")]
        reviews = [review_for(row) for row in rows]
        reviews[1]["human_decision"] = "rewrite"
        reviews[1]["human_question"] = "두 번째 사실과 개인 판단을 나눠서 알려줘."
        reviews[1]["human_answer"] = "사실은 A입니다. 개인 판단은 정보가 없어 할 수 없습니다."
        reviews[2]["human_decision"] = "reject"

        frozen, summary = freeze_reviewed_rows(rows, reviews, self.chunks, [], [])

        self.assertEqual([row["qa_id"] for row in frozen], ["p1", "p2"])
        self.assertEqual(frozen[1]["question"], reviews[1]["human_question"])
        self.assertEqual(frozen[1]["pre_review_question"], rows[1]["question"])
        self.assertEqual(summary["decision_counts"], {"approve": 1, "rewrite": 1, "reject": 1})

    def test_requires_review_for_every_candidate(self) -> None:
        row = candidate("p1")
        with self.assertRaisesRegex(ValueError, "Review coverage mismatch"):
            freeze_reviewed_rows([row], [], self.chunks, [], [])

    def test_rejects_changed_immutable_evidence(self) -> None:
        row = candidate("p1")
        review = review_for(row)
        review["evidence_span"] = "다른 근거"
        with self.assertRaisesRegex(ValueError, "immutable field evidence_span"):
            freeze_reviewed_rows([row], [review], self.chunks, [], [])

    def test_accepted_row_requires_three_yes_votes(self) -> None:
        row = candidate("p1")
        review = review_for(row)
        review["targeted_abstention_correct"] = "no"
        with self.assertRaisesRegex(ValueError, "requires yes"):
            freeze_reviewed_rows([row], [review], self.chunks, [], [])

    def test_rejects_heldout_parent_or_question(self) -> None:
        row = candidate("p1")
        review = review_for(row)
        heldout = [{"question": "다른 질문", "expected_doc_id": "parent_train"}]
        with self.assertRaisesRegex(ValueError, "held-out parent/chunk"):
            freeze_reviewed_rows([row], [review], self.chunks, heldout, [])

    def test_rejects_existing_train_question(self) -> None:
        row = candidate("p1")
        review = review_for(row)
        with self.assertRaisesRegex(ValueError, "already exists in train QA"):
            freeze_reviewed_rows([row], [review], self.chunks, [], [{"question": row["question"]}])


if __name__ == "__main__":
    unittest.main()
