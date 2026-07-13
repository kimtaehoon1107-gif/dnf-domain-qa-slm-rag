from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from apply_blind_review import apply_reviews  # noqa: E402


def candidate(eval_id: str) -> dict:
    return {
        "eval_id": eval_id,
        "question": f"question {eval_id}",
        "answerability": "true",
        "review_status": "pending",
        "expected_answer": "old answer",
        "gold_answer": "old answer",
        "evidence_span": "old evidence",
    }


class ApplyBlindReviewTests(unittest.TestCase):
    def test_applies_approve_rewrite_reject_and_correction(self) -> None:
        rows = [candidate("a"), candidate("b"), candidate("c")]
        reviews = [
            {"eval_id": "a", "human_decision": "approve", "rewritten_question": ""},
            {
                "eval_id": "b",
                "human_decision": "rewrite",
                "rewritten_question": "better question",
                "review_notes": "aligned",
            },
            {"eval_id": "c", "human_decision": "reject", "rewritten_question": ""},
        ]
        corrections = [
            {
                "eval_id": "b",
                "expected_answer": "better answer",
                "gold_answer": "better answer",
                "evidence_span": "better evidence",
            }
        ]

        output, summary = apply_reviews(rows, reviews, corrections)

        self.assertEqual(output[0]["review_status"], "approved")
        self.assertEqual(output[1]["question"], "better question")
        self.assertEqual(output[1]["pre_review_question"], "question b")
        self.assertEqual(output[1]["expected_answer"], "better answer")
        self.assertEqual(output[1]["review_notes"], "aligned")
        self.assertEqual(output[2]["review_status"], "rejected")
        self.assertEqual(summary["status_counts"], {"approved": 2, "rejected": 1})

    def test_rewrite_requires_question(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires rewritten_question"):
            apply_reviews(
                [candidate("a")],
                [{"eval_id": "a", "human_decision": "rewrite", "rewritten_question": ""}],
            )

    def test_correction_must_belong_to_reviewed_row(self) -> None:
        with self.assertRaisesRegex(ValueError, "correction IDs not found"):
            apply_reviews(
                [candidate("a"), candidate("b")],
                [{"eval_id": "a", "human_decision": "approve", "rewritten_question": ""}],
                [{"eval_id": "b", "expected_answer": "answer"}],
            )


if __name__ == "__main__":
    unittest.main()
