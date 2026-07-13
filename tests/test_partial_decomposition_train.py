from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from make_partial_decomposition_train import build_candidates, validate_candidate_evidence  # noqa: E402


def true_row(index: int, parent: str = "train_parent") -> dict:
    return {
        "qa_id": f"train_{index}",
        "question": f"입장 조건 {index}은 뭐야?",
        "intent": "guide_fact",
        "answerability": "true",
        "source_eval_type": "casual_paraphrase_train",
        "gold_answer": f"입장 조건은 명성 {index}입니다",
        "evidence_span": f"입장 조건은 명성 {index}입니다",
        "expected_doc_id": parent,
        "expected_evidence_doc_ids": [parent],
        "expected_chunk_id": f"{parent}__chunk_{index:03d}",
        "expected_chunk_ids": [f"{parent}__chunk_{index:03d}"],
    }


class PartialDecompositionTrainTests(unittest.TestCase):
    def test_builds_grounded_then_targeted_abstention(self) -> None:
        candidate = build_candidates([true_row(1)], [], limit=1)[0]

        self.assertEqual(candidate["answerability"], "partial")
        self.assertTrue(candidate["gold_answer"].startswith("입장 조건은 명성 1입니다."))
        self.assertIn(candidate["targeted_abstention"], candidate["gold_answer"])
        self.assertNotIn("수집된 공식 문서만으로는 해당 질문", candidate["gold_answer"])
        self.assertEqual([item["type"] for item in candidate["requirements"]], ["grounded", "unsupported"])

    def test_excludes_any_heldout_parent_or_chunk(self) -> None:
        blocked = {
            "eval_id": "eval_1",
            "question": "다른 질문",
            "expected_doc_id": "blocked_parent",
            "expected_chunk_ids": ["blocked_parent__chunk_001"],
        }
        rows = [true_row(1, "blocked_parent"), true_row(2, "safe_parent")]

        candidates = build_candidates(rows, [blocked], limit=1)

        self.assertEqual(candidates[0]["expected_doc_id"], "safe_parent")

    def test_limits_examples_per_parent(self) -> None:
        rows = [true_row(index, "same_parent") for index in range(1, 5)]
        rows.append(true_row(5, "other_parent"))

        candidates = build_candidates(rows, [], limit=3, max_per_parent=2)

        self.assertEqual(sum(row["expected_doc_id"] == "same_parent" for row in candidates), 2)

    def test_event_item_uses_item_specific_unsupported_request(self) -> None:
        row = true_row(1)
        row["intent"] = "event_fact"
        row["question"] = "아바타 상자는 언제 삭제돼?"

        candidate = build_candidates([row], [], limit=1)[0]

        self.assertNotIn("지금 참여", candidate["unsupported_request"])
        self.assertTrue(
            any(term in candidate["unsupported_request"] for term in ("아이템", "보상", "구성"))
        )

    def test_validates_evidence_against_expected_chunk(self) -> None:
        candidate = build_candidates([true_row(1)], [], limit=1)[0]
        chunks = [
            {
                "doc_id": candidate["expected_chunk_id"],
                "text": f"앞 문장 {candidate['evidence_span']} 뒤 문장",
            }
        ]

        result = validate_candidate_evidence([candidate], chunks)

        self.assertEqual(result, {"missing_chunks": 0, "span_mismatches": 0})

    def test_rejects_evidence_span_mismatch(self) -> None:
        candidate = build_candidates([true_row(1)], [], limit=1)[0]
        chunks = [{"doc_id": candidate["expected_chunk_id"], "text": "다른 내용"}]
        with self.assertRaisesRegex(ValueError, "span_mismatches=1"):
            validate_candidate_evidence([candidate], chunks)


if __name__ == "__main__":
    unittest.main()
