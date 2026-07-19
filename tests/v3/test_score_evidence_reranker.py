from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.score_evidence_reranker import (
    MODEL_NAME,
    MODEL_REVISION,
    attach_scores,
    prepare_pairs,
)


FROZEN_SCORES = Path(
    "data/v3/evidence/"
    "evidence_reranker_scores_ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/evidence/"
    "evidence_reranker_manifest_ad6b3f074d8f6edf848c0129d0ea3d8de1c9438aa3de98dde0bfac0fb7a2f26c.json"
)
FROZEN_LATENCY = Path(
    "reports/v3/"
    "evidence_reranker_latency_823dcb4d60ad4af02343389ad1610a6d27ad9a9a8c80eb644121df839e7a8547.json"
)


def retrieval_row(dev_id: str, chunk_id: str) -> dict:
    return {
        "dev_id": dev_id,
        "configurations": {
            "dense_75_bm25_25_structured_parent_lead_guard": {
                "hits": [
                    {
                        "rank": 1,
                        "chunk_id": chunk_id,
                        "parent_document_id": "document_1",
                        "source_id": "dnf_game_guide",
                        "status": "current",
                        "default_exposure": True,
                        "review_required": False,
                        "base_score": 1.0,
                        "guardrail_injected": False,
                    }
                ]
            }
        },
    }


class RerankerScorePreparationTest(unittest.TestCase):
    def test_prepare_pairs_skips_predicted_false_without_gold_labels(self) -> None:
        dev = [
            {"dev_id": "answerable", "question": "공식 판매 기간은?"},
            {"dev_id": "blocked", "question": "다음 로또 번호를 예측해줘"},
        ]
        retrieval = [
            retrieval_row("answerable", "chunk_1"),
            retrieval_row("blocked", "chunk_1"),
        ]
        chunks = [{"chunk_id": "chunk_1", "retrieval_text": "공식 판매 기간"}]

        rows, pairs = prepare_pairs(dev, retrieval, chunks)

        self.assertEqual(pairs, [("공식 판매 기간은?", "공식 판매 기간")])
        self.assertEqual(rows[0]["scoring_status"], "pending")
        self.assertEqual(rows[1]["scoring_status"], "skipped_predicted_false")
        self.assertEqual(rows[1]["candidates"], [])
        self.assertNotIn("gold_answerability", rows[0])

    def test_attach_scores_rounds_and_validates_alignment(self) -> None:
        rows = [
            {
                "scoring_status": "pending",
                "candidates": [{"pair_ordinal": 0, "chunk_id": "chunk_1"}],
            }
        ]

        scored = attach_scores(rows, [0.123456789])

        self.assertEqual(scored[0]["candidates"][0]["reranker_score"], 0.12345679)
        self.assertEqual(scored[0]["scoring_status"], "success")
        with self.assertRaises(RuntimeError):
            attach_scores(rows, [])
        with self.assertRaises(RuntimeError):
            attach_scores(rows, [math.nan])


class FrozenRerankerScoreArtifactTest(unittest.TestCase):
    def test_frozen_scores_manifest_and_latency_are_valid(self) -> None:
        for path in (FROZEN_SCORES, FROZEN_MANIFEST, FROZEN_LATENCY):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        rows = read_jsonl(FROZEN_SCORES)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        latency = json.loads(FROZEN_LATENCY.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 63)
        self.assertEqual(sum(len(row["candidates"]) for row in rows), 550)
        self.assertEqual(
            sum(row["scoring_status"] == "skipped_predicted_false" for row in rows),
            8,
        )
        self.assertTrue(
            all(
                math.isfinite(candidate["reranker_score"])
                for row in rows
                for candidate in row["candidates"]
            )
        )
        self.assertEqual(manifest["model"]["name"], MODEL_NAME)
        self.assertEqual(manifest["model"]["revision"], MODEL_REVISION)
        self.assertFalse(manifest["gold_ids_available_to_scorer"])
        self.assertEqual(latency["pair_count"], 550)
        self.assertEqual(latency["device"], "cuda")


if __name__ == "__main__":
    unittest.main()
