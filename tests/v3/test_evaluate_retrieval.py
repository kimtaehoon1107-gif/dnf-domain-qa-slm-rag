from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from src.io_utils import read_jsonl
from src.v3.build_bm25 import _allowed, build_bm25_index
from src.v3.evaluate_retrieval import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DEV_SET,
    evaluate_rows,
    freeze_evaluation,
    load_retrieval_artifacts,
    policy_from_dev,
    score_ranked_hits,
)
from src.v3.build_corpus import file_sha256


DEV_MANIFEST = Path(
    "data/v3/evaluation/"
    "retrieval_dev_manifest_bb5a858702d8b8c0c267f35309db75221f8e9d5515e30f34b4e6b9dfb17dcec3.json"
)
FROZEN_QUERY_EMBEDDINGS = Path(
    "data/v3/retrieval/"
    "retrieval_dev_query_embeddings_323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32"
)
FROZEN_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_ab_results_c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/retrieval/"
    "retrieval_ab_manifest_5d96c252d65aed8632f2a72581641150fe04f04903f283c97cfae29686abc0ca.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "retrieval_ab_5c8ebeb3606d785e7c898f32eef036b2fa2f8c8c1dbfbe49957602f23e907550.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "retrieval_ab_d8debe965e499ca6a1a20a18a27ecd6e631068a205a81571f09de2e7a7d25fcb.md"
)


class RetrievalMetricTest(unittest.TestCase):
    def test_single_and_multi_evidence_metrics_use_acceptable_chunk_groups(self) -> None:
        groups = [
            {"acceptable_chunk_ids": ["overlap_a", "overlap_b"]},
            {"acceptable_chunk_ids": ["second_fact"]},
        ]
        hits = [
            {"rank": 1, "chunk_id": "noise"},
            {"rank": 2, "chunk_id": "overlap_b"},
            {"rank": 7, "chunk_id": "second_fact"},
        ]

        metrics = score_ranked_hits(groups, hits)

        self.assertEqual(metrics["group_first_ranks"], [2, 7])
        self.assertEqual(metrics["reciprocal_rank"], 0.5)
        self.assertTrue(metrics["at_k"]["3"]["any_hit"])
        self.assertFalse(metrics["at_k"]["3"]["all_groups_hit"])
        self.assertEqual(metrics["at_k"]["3"]["evidence_group_recall"], 0.5)
        self.assertTrue(metrics["at_k"]["10"]["all_groups_hit"])

    def test_unanswerable_rows_are_not_scored_as_retrieval_failures(self) -> None:
        metrics = score_ranked_hits([], [{"rank": 1, "chunk_id": "anything"}])

        self.assertFalse(metrics["evaluated"])
        self.assertIsNone(metrics["reciprocal_rank"])
        self.assertEqual(metrics["at_k"], {})

    def test_fixture_bm25_and_dense_apply_the_same_policy_and_metrics(self) -> None:
        chunks = [
            {
                "chunk_id": "chunk_current",
                "parent_document_id": "doc_current",
                "retrieval_text": "정기점검 시간 안내",
                "source_id": "dnf_notice",
                "source_kind": "maintenance",
                "status": "current",
                "default_exposure": True,
                "review_required": False,
                "offset_source": "text",
                "valid_from": None,
                "valid_to": None,
            },
            {
                "chunk_id": "chunk_expired",
                "parent_document_id": "doc_expired",
                "retrieval_text": "종료 이벤트 보상",
                "source_id": "dnf_event",
                "source_kind": "event",
                "status": "expired",
                "default_exposure": False,
                "review_required": False,
                "offset_source": "text",
                "valid_from": None,
                "valid_to": "2025-01-01",
            },
        ]
        documents = [
            {"document_id": "doc_current", "canonical_url": "https://x/current", "title": "점검"},
            {"document_id": "doc_expired", "canonical_url": "https://x/expired", "title": "이벤트"},
        ]
        bm25 = build_bm25_index(chunks, documents)
        metadata = [
            {
                **{key: value for key, value in entry.items() if key != "document_length"},
                "metadata_schema_version": "fixture",
            }
            for entry in bm25["entries"]
        ]
        embeddings = np.eye(2, dtype=np.float32)
        dev = [
            {
                "dev_id": "dev_current",
                "question": "정기점검 시간",
                "answerability": "true",
                "query_kind": "single_fact",
                "source_ids": ["dnf_notice"],
                "target_statuses": ["current"],
                "query_policy": {
                    "default_exposure_only": True,
                    "allowed_statuses": ["current", "upcoming"],
                    "include_review_required": False,
                    "as_of": None,
                },
                "gold_chunk_ids": ["chunk_current"],
                "evidence_groups": [
                    {"acceptable_chunk_ids": ["chunk_current"]}
                ],
                "required_evidence_group_count": 1,
            }
        ]

        results, audit = evaluate_rows(
            dev, bm25, metadata, embeddings, np.array([[1.0, 0.0]], dtype=np.float32)
        )

        self.assertEqual(audit["filter_candidate_set_mismatches"], 0)
        self.assertEqual(audit["gold_chunks_excluded_by_policy"], 0)
        self.assertEqual(results[0]["candidate_count"], 1)
        self.assertTrue(results[0]["systems"]["bm25"]["metrics"]["at_k"]["1"]["any_hit"])
        self.assertTrue(results[0]["systems"]["dense"]["metrics"]["at_k"]["1"]["any_hit"])


class ActualRetrievalInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path.cwd()
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.bm25, cls.metadata, cls.embeddings, _, _ = load_retrieval_artifacts(
            cls.root, DEFAULT_BM25_MANIFEST, DEFAULT_DENSE_MANIFEST
        )

    def test_actual_dev_policies_have_dense_bm25_parity_and_keep_all_gold(self) -> None:
        mismatches = 0
        excluded_gold = []
        candidate_counts = []
        for row in self.dev:
            policy = policy_from_dev(row)
            bm25_ids = {
                entry["chunk_id"]
                for entry in self.bm25["entries"]
                if _allowed(entry, policy)
            }
            dense_ids = {
                entry["chunk_id"]
                for entry in self.metadata
                if _allowed(entry, policy)
            }
            mismatches += len(bm25_ids ^ dense_ids)
            excluded_gold.extend(
                chunk_id for chunk_id in row["gold_chunk_ids"] if chunk_id not in bm25_ids
            )
            candidate_counts.append(len(bm25_ids))

        self.assertEqual(mismatches, 0)
        self.assertEqual(excluded_gold, [])
        self.assertEqual(len(self.dev), 63)
        self.assertEqual(min(candidate_counts), 17)
        self.assertEqual(max(candidate_counts), 2881)
        self.assertEqual(self.embeddings.shape, (3599, 1024))

    def test_policy_conversion_never_uses_gold_source_as_a_filter(self) -> None:
        for row in self.dev:
            self.assertIsNone(policy_from_dev(row).source_ids)


class FrozenRetrievalEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        cls.report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

    def test_frozen_hashes_integrity_gates_and_measured_metrics(self) -> None:
        for path in (
            FROZEN_QUERY_EMBEDDINGS,
            FROZEN_RESULTS,
            FROZEN_MANIFEST,
            FROZEN_REPORT,
            FROZEN_REPORT_MD,
        ):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])
        self.assertTrue(self.report["audit"]["gate_pass"])
        self.assertEqual(self.report["audit"]["filter_candidate_set_mismatches"], 0)
        self.assertEqual(self.report["audit"]["gold_chunks_excluded_by_policy"], 0)
        self.assertEqual(self.report["decision"]["evaluation_integrity"], "GO")
        self.assertEqual(self.report["decision"]["hybrid_experiment_entry"], "GO")
        self.assertEqual(self.report["decision"]["hybrid_promotion"], "NOT_RUN")
        self.assertEqual(self.report["aggregate"]["evaluated_count"], 55)
        self.assertEqual(self.report["aggregate"]["unanswerable_count"], 8)
        self.assertEqual(self.report["aggregate"]["systems"]["bm25"]["mrr"], 0.614934)
        self.assertEqual(self.report["aggregate"]["systems"]["dense"]["mrr"], 0.644567)
        self.assertEqual(
            self.report["aggregate"]["complementarity"]["10"],
            {"both": 46, "bm25_only": 2, "dense_only": 6, "neither": 1},
        )

def test_retrieval_generator_is_reproducible(tmp_path: Path) -> None:
    embeddings = np.fromfile(FROZEN_QUERY_EMBEDDINGS, dtype="<f4").reshape(63, 1024)
    query_model = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))[
        "query_model"
    ]
    kwargs = {
        "root": Path.cwd(),
        "dev_path": DEFAULT_DEV_SET,
        "dev_manifest_path": DEV_MANIFEST,
        "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
        "dense_manifest_path": DEFAULT_DENSE_MANIFEST,
        "query_embeddings": embeddings,
        "query_model": query_model,
        "artifact_root": tmp_path,
    }

    first = freeze_evaluation(**kwargs)
    second = freeze_evaluation(**kwargs)

    assert first == second


if __name__ == "__main__":
    unittest.main()
