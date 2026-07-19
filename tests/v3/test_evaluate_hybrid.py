from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_hybrid import (
    DEFAULT_DEV_SET,
    DEFAULT_RETRIEVAL_RESULTS,
    DENSE_WEIGHTS,
    aggregate_grid,
    build_and_freeze,
    choose_best_config,
    config_name,
    evaluate_grid,
    fuse_hits,
    normalize_minmax,
)
from src.v3.build_corpus import file_sha256


RETRIEVAL_MANIFEST = Path(
    "data/v3/retrieval/"
    "retrieval_ab_manifest_5d96c252d65aed8632f2a72581641150fe04f04903f283c97cfae29686abc0ca.json"
)
RETRIEVAL_REPORT = Path(
    "reports/v3/"
    "retrieval_ab_5c8ebeb3606d785e7c898f32eef036b2fa2f8c8c1dbfbe49957602f23e907550.json"
)
FROZEN_RESULTS = Path(
    "data/v3/retrieval/"
    "hybrid_grid_results_a570e39e37dc6311c5e82fb32d8c403908d3251ba4d6b06babd2857e6b50d9e1.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/retrieval/"
    "hybrid_grid_manifest_1e8d64ae1c4deb121333bbf009178668111ad52925438a45b17cda1da1dfadf6.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "hybrid_grid_35ac0dbb861207a55bc380bb94dcc92a71defcc7b34e205911c8ee5f5131c093.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "hybrid_grid_2d827819e42e154c294c8920a51ecd78eb9a53f5c30c6a724480e51372bca364.md"
)


def hit(chunk_id: str, rank: int, score: float, source_id: str = "dnf_notice") -> dict:
    return {
        "rank": rank,
        "score": score,
        "chunk_id": chunk_id,
        "parent_document_id": f"doc_{chunk_id}",
        "source_id": source_id,
        "status": "current",
        "default_exposure": True,
        "review_required": False,
    }


class HybridFusionUnitTest(unittest.TestCase):
    def test_minmax_normalization_and_missing_scores_are_deterministic(self) -> None:
        bm25 = [hit("a", 1, 10.0), hit("b", 2, 5.0), hit("c", 3, 0.0)]
        dense = [hit("b", 1, 0.9), hit("d", 2, 0.7), hit("a", 3, 0.5)]

        normalized = normalize_minmax(bm25)
        fused = fuse_hits(bm25, dense, dense_weight=0.5, top_k=4)

        self.assertEqual(normalized, {"a": 1.0, "b": 0.5, "c": 0.0})
        self.assertEqual([row["chunk_id"] for row in fused], ["b", "a", "d", "c"])
        self.assertEqual(fused[0]["score"], 0.75)
        self.assertEqual(fused[2]["bm25_normalized_score"], 0.0)
        self.assertEqual(fused[3]["dense_normalized_score"], 0.0)

    def test_fusion_rejects_endpoint_weights_and_metadata_disagreement(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "strictly between"):
            fuse_hits([hit("a", 1, 1.0)], [hit("a", 1, 1.0)], dense_weight=1.0)
        dense = hit("a", 1, 1.0)
        dense["status"] = "expired"
        with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
            fuse_hits([hit("a", 1, 1.0)], [dense], dense_weight=0.5)


class ActualHybridGridInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.retrieval = read_jsonl(DEFAULT_RETRIEVAL_RESULTS)
        cls.rows = evaluate_grid(cls.dev, cls.retrieval)
        cls.aggregate = aggregate_grid(cls.rows)

    def test_actual_grid_is_complete_and_deterministic(self) -> None:
        second = evaluate_grid(self.dev, list(reversed(self.retrieval)))

        self.assertEqual(self.rows, second)
        self.assertEqual(len(self.rows), 63)
        self.assertEqual(
            set(self.rows[0]["configurations"]),
            {config_name(weight) for weight in DENSE_WEIGHTS},
        )
        self.assertTrue(
            all(
                len(config["hits"]) <= 20
                for row in self.rows
                for config in row["configurations"].values()
            )
        )

    def test_actual_best_fixed_config_is_dense_75(self) -> None:
        best = choose_best_config(self.aggregate)

        self.assertEqual(best, "dense_75_bm25_25")
        metrics = self.aggregate["overall"][best]
        self.assertEqual(metrics["evaluated_count"], 55)
        self.assertEqual(metrics["at_k"]["10"]["hit_rate"], 0.963636)
        self.assertEqual(metrics["at_k"]["10"]["all_groups_hit_rate"], 0.945455)
        self.assertEqual(metrics["at_k"]["10"]["evidence_group_recall_micro"], 0.949153)
        self.assertEqual(metrics["mrr"], 0.708528)


class FrozenHybridGridArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

    def test_frozen_hashes_metrics_and_strict_no_go_are_preserved(self) -> None:
        for path in (FROZEN_RESULTS, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        promotion = self.report["promotion_audit"]
        self.assertEqual(self.report["decision"]["experiment_integrity"], "GO")
        self.assertEqual(self.report["decision"]["hybrid_promotion"], "NO-GO")
        self.assertEqual(promotion["best_config"], "dense_75_bm25_25")
        self.assertTrue(promotion["gates"]["hit_rate_at_10_strictly_improved"])
        self.assertTrue(promotion["gates"]["all_groups_at_10_strictly_improved"])
        self.assertTrue(promotion["gates"]["group_recall_at_10_strictly_improved"])
        self.assertTrue(promotion["gates"]["mrr_not_regressed"])
        self.assertTrue(promotion["gates"]["source_regression_0"])
        self.assertFalse(promotion["gates"]["worst_source_at_10_strictly_improved"])
        self.assertEqual(promotion["candidate_worst_source_all_groups_at_10"], 0.666667)
        self.assertEqual(promotion["dense_worst_source_all_groups_at_10"], 0.666667)

    def test_actual_inputs_refreeze_to_identical_artifacts(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_RETRIEVAL_RESULTS,
            RETRIEVAL_MANIFEST,
            RETRIEVAL_REPORT,
        )

        self.assertEqual(result["results_sha256"], file_sha256(FROZEN_RESULTS))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD))


if __name__ == "__main__":
    unittest.main()
