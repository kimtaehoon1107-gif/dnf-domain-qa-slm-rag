from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from build_partial_decomposition_arm import build_arm  # noqa: E402


def base_row() -> dict:
    return {"qa_id": "base_1", "question": "기존 질문", "answerability": "true"}


def reviewed_row() -> dict:
    return {
        "qa_id": "partial_1",
        "question": "근거와 개인 판단을 나눠서 알려줘",
        "answerability": "partial",
        "review_status": "approved",
        "source_split": "train",
        "gold_answer": "근거는 A입니다. 개인 판단은 할 수 없습니다.",
        "expected_doc_id": "parent_train",
        "expected_chunk_ids": ["chunk_train"],
        "requirements": [{"type": "grounded"}, {"type": "unsupported"}],
    }


class BuildPartialDecompositionArmTests(unittest.TestCase):
    def test_appends_only_reviewed_train_rows(self) -> None:
        combined, summary = build_arm([base_row()], [reviewed_row()], [])
        self.assertEqual([row["qa_id"] for row in combined], ["base_1", "partial_1"])
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["reviewed_decomposition_rows"], 1)

    def test_rejects_unapproved_row(self) -> None:
        row = reviewed_row()
        row["review_status"] = "pending"
        with self.assertRaisesRegex(ValueError, "not approved"):
            build_arm([base_row()], [row], [])

    def test_rejects_duplicate_base_question(self) -> None:
        row = reviewed_row()
        row["question"] = "기존 질문"
        with self.assertRaisesRegex(ValueError, "duplicate train question"):
            build_arm([base_row()], [row], [])

    def test_rejects_heldout_parent(self) -> None:
        heldout = [{"question": "평가 질문", "expected_doc_id": "parent_train"}]
        with self.assertRaisesRegex(ValueError, "held-out parent"):
            build_arm([base_row()], [reviewed_row()], heldout)

    def test_requires_both_requirement_types(self) -> None:
        row = reviewed_row()
        row["requirements"] = [{"type": "grounded"}]
        with self.assertRaisesRegex(ValueError, "grounded/unsupported"):
            build_arm([base_row()], [row], [])


if __name__ == "__main__":
    unittest.main()
