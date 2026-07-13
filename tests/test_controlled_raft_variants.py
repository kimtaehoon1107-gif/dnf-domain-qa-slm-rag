from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from make_raft_dataset import make_raft_rows  # noqa: E402


class ControlledRaftVariantTests(unittest.TestCase):
    def test_gold_position_is_independent_of_distractor_strategy(self) -> None:
        docs = [
            {
                "doc_id": doc_id,
                "parent_doc_id": parent_id,
                "title": doc_id,
                "text": f"text for {doc_id}",
            }
            for doc_id, parent_id in (
                ("gold", "gold_parent"),
                ("random_1", "p1"),
                ("random_2", "p2"),
                ("hard_1", "p3"),
                ("hard_2", "p4"),
            )
        ]
        qa = [
            {
                "qa_id": "qa_1",
                "split": "train",
                "question": "question",
                "answerability": "true",
                "gold_answer": "answer",
                "evidence_span": "answer",
                "expected_doc_id": "gold_parent",
                "expected_chunk_ids": ["gold"],
            }
        ]
        common = dict(
            docs=docs,
            qa_rows=qa,
            max_rows=1,
            distractors=2,
            seed=42,
            train_splits={"train"},
            allow_unsplit=False,
            excluded_chunk_ids=set(),
            excluded_parent_ids=set(),
            gold_text="chunk",
        )
        random_row = make_raft_rows(**common)[0]
        hard_row = make_raft_rows(
            **common,
            hard_negatives_by_source={"qa_1": ["hard_1", "hard_2"]},
            require_hard_negatives=True,
        )[0]

        def gold_position(row: dict) -> int:
            return next(
                index
                for index, document in enumerate(row["documents"], start=1)
                if document["doc_id"] == "gold"
            )

        self.assertEqual(gold_position(random_row), gold_position(hard_row))
        self.assertEqual(random_row["distractor_strategy"], "random")
        self.assertEqual(hard_row["distractor_strategy"], "hard_negative")

    def test_random_distractors_exclude_answer_like_and_human_blocked_docs(self) -> None:
        evidence = "입장 레벨 115 이상이며 모험가 명성 90000 이상이 필요합니다"
        docs = [
            {"doc_id": "gold", "parent_doc_id": "gold_parent", "text": evidence},
            {
                "doc_id": "duplicate_answer",
                "parent_doc_id": "duplicate_parent",
                "text": f"이 콘텐츠는 {evidence}.",
            },
            {"doc_id": "human_blocked", "parent_doc_id": "blocked_parent", "text": "other"},
            {"doc_id": "safe_1", "parent_doc_id": "safe_parent_1", "text": "이벤트 보상 안내"},
            {"doc_id": "safe_2", "parent_doc_id": "safe_parent_2", "text": "정기점검 안내"},
        ]
        qa = [
            {
                "qa_id": "qa_1",
                "split": "train",
                "question": "입장 조건은?",
                "answerability": "true",
                "gold_answer": "입장 레벨과 명성 조건이 있습니다.",
                "evidence_span": evidence,
                "expected_doc_id": "gold_parent",
                "expected_chunk_ids": ["gold"],
            }
        ]
        row = make_raft_rows(
            docs=docs,
            qa_rows=qa,
            max_rows=1,
            distractors=2,
            seed=42,
            train_splits={"train"},
            allow_unsplit=False,
            excluded_chunk_ids=set(),
            excluded_parent_ids=set(),
            gold_text="chunk",
            human_blocklist_by_source={"qa_1": {"human_blocked"}},
        )[0]
        distractor_ids = {
            document["doc_id"] for document in row["documents"] if document["role"] == "distractor"
        }
        self.assertEqual(distractor_ids, {"safe_1", "safe_2"})


if __name__ == "__main__":
    unittest.main()
