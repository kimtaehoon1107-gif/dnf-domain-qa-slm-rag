from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import retrieve  # noqa: E402
from finetune_lora import dev_group_key, split_grouped_rows  # noqa: E402
from prompt_format import evidence_span_visible, select_query_window  # noqa: E402


def raft_row(source_qa_id: str, label: str) -> dict:
    return {
        "source_qa_id": source_qa_id,
        "question": f"question {source_qa_id}",
        "answer": f"answer {source_qa_id}",
        "answerability": label,
        "expected_doc_id": "" if label == "false" else f"doc_{source_qa_id}",
        "expected_chunk_ids": [] if label == "false" else [f"doc_{source_qa_id}__chunk_001"],
    }


class GroupedSplitTests(unittest.TestCase):
    def test_oversampled_copies_never_cross_train_dev(self) -> None:
        rows = []
        for label in ("true", "partial", "false"):
            for group_index in range(4):
                row = raft_row(f"{label}_{group_index}", label)
                copies = 3 if label != "true" else 1
                rows.extend(dict(row) for _ in range(copies))

        train_rows, dev_rows, report = split_grouped_rows(
            rows,
            dev_ratio=0.25,
            seed=42,
            group_by="source_qa_id",
        )

        train_groups = {dev_group_key(row, "source_qa_id") for row in train_rows}
        dev_groups = {dev_group_key(row, "source_qa_id") for row in dev_rows}
        self.assertFalse(train_groups & dev_groups)
        self.assertEqual(len(dev_rows), len(dev_groups))
        self.assertEqual(report["group_overlap"], 0)
        self.assertGreater(report["dev_duplicate_rows_removed"], 0)


class EvidenceWindowTests(unittest.TestCase):
    def test_query_specific_terms_select_late_window(self) -> None:
        text = (
            "보급 작전 보급품 안내 "
            + ("일반 미션 설명 " * 45)
            + "모든 보급품은 우편으로 지급되며 보관 기간은 15일입니다."
        )
        question = "보급 작전 보급품은 우편에 며칠 보관돼?"
        title = "파도치는 폭권으로 보급 작전"

        window = select_query_window(text, question, max_chars=240, title=title)

        self.assertIn("우편으로 지급", window)
        self.assertTrue(
            evidence_span_visible(
                question,
                [{"title": title, "text": text}],
                "우편으로 지급되며 보관 기간은 15일",
                max_doc_chars=240,
            )
        )


class RetrievalPlumbingTests(unittest.TestCase):
    def test_reranker_pool_must_cover_top_k(self) -> None:
        with self.assertRaisesRegex(ValueError, "rerank_candidates"):
            retrieve.retrieve(
                "question",
                top_k=5,
                candidate_k=100,
                reranker_model="reranker",
                rerank_candidates=3,
            )

    @patch("retrieve.retrieve")
    @patch("retrieve.parse_args")
    def test_cli_forwards_reranker_arguments(self, parse_args, mocked_retrieve) -> None:
        parse_args.return_value = argparse.Namespace(
            question="question",
            persist_dir=Path("index"),
            top_k=3,
            candidate_k=100,
            model_name="embedding",
            rank_mode="hybrid",
            reranker_model="reranker",
            rerank_candidates=20,
            reranker_max_length=1024,
            reranker_batch_size=4,
        )
        mocked_retrieve.return_value = []

        retrieve.main()

        mocked_retrieve.assert_called_once_with(
            "question",
            persist_dir=Path("index"),
            top_k=3,
            model_name="embedding",
            candidate_k=100,
            rank_mode="hybrid",
            reranker_model="reranker",
            rerank_candidates=20,
            reranker_max_length=1024,
            reranker_batch_size=4,
        )


if __name__ == "__main__":
    unittest.main()
