from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_retrieval_signals import (
    CANDIDATE_CONFIG,
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_HYBRID_RESULTS,
    DEFAULT_RETRIEVAL_RESULTS,
    aggregate_signal,
    apply_structured_parent_lead_guard,
    build_and_freeze,
    build_lead_chunk_index,
    evaluate_signal,
    is_structured_field_query,
)


RETRIEVAL_REPORT = Path(
    "reports/v3/"
    "retrieval_ab_5c8ebeb3606d785e7c898f32eef036b2fa2f8c8c1dbfbe49957602f23e907550.json"
)
HYBRID_REPORT = Path(
    "reports/v3/"
    "hybrid_grid_35ac0dbb861207a55bc380bb94dcc92a71defcc7b34e205911c8ee5f5131c093.json"
)
FROZEN_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_signal_results_c8f5c902f237ef70b4add45ee63815bd1cdafeb84741c86c1bd634b1df02127e.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/retrieval/"
    "retrieval_signal_manifest_65e0a1e210aae40c2a610e69a1cf79f90ef79e8b39bd9e971c2e9029fc9358ca.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "retrieval_signal_e476a6f9f0c310bb952aadf1d128f16a711fcab4019512493f575c174e20555d.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "retrieval_signal_a4bace8ed2c24eeb6fb57335a0d4e2e0d7816722ef7b52035c26a21ea2ccdbf8.md"
)


def chunk(chunk_id: str, parent_id: str, index: int = 1) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": parent_id,
        "chunk_index": index,
        "source_id": "dnf_seria_shop",
        "status": "current",
        "default_exposure": True,
        "review_required": False,
        "offset_source": "dom_text",
        "valid_from": None,
        "valid_to": None,
    }


def hit(chunk_id: str, parent_id: str, rank: int) -> dict:
    return {
        "rank": rank,
        "score": round(1.0 / rank, 6),
        "chunk_id": chunk_id,
        "parent_document_id": parent_id,
        "source_id": "dnf_seria_shop",
        "status": "current",
        "default_exposure": True,
        "review_required": False,
    }


POLICY = {
    "default_exposure_only": True,
    "allowed_statuses": ["current", "upcoming"],
    "include_review_required": False,
    "as_of": None,
}


class StructuredParentLeadUnitTest(unittest.TestCase):
    def test_structured_field_detection_is_narrow_and_deterministic(self) -> None:
        self.assertTrue(is_structured_field_query("상품 가격과 거래 타입은?"))
        self.assertTrue(is_structured_field_query("판매 종료 시점은?"))
        self.assertFalse(is_structured_field_query("비인가 프로그램 주의사항은?"))

    def test_guard_preserves_top_eight_and_injects_two_lexical_parent_leads(self) -> None:
        chunks = [chunk("lead_a", "parent_a"), chunk("lead_b", "parent_b")]
        chunks.extend(
            chunk(f"base_{index}", f"base_parent_{index}") for index in range(1, 21)
        )
        lead_index = build_lead_chunk_index(chunks)
        base = [hit(f"base_{index}", f"base_parent_{index}", index) for index in range(1, 21)]
        bm25 = [hit("other_a", "parent_a", 1), hit("other_b", "parent_b", 2)]

        output, audit = apply_structured_parent_lead_guard(
            "판매 종료 시점은?", POLICY, base, bm25, lead_index
        )

        self.assertEqual([row["chunk_id"] for row in output[:8]], [f"base_{i}" for i in range(1, 9)])
        self.assertEqual([row["chunk_id"] for row in output[8:10]], ["lead_a", "lead_b"])
        self.assertEqual(audit["injected_chunk_ids"], ["lead_a", "lead_b"])
        self.assertTrue(all(row["guardrail_injected"] for row in output[8:10]))

    def test_nonstructured_query_keeps_base_ranking_unchanged(self) -> None:
        lead_index = build_lead_chunk_index([chunk("lead_a", "parent_a")])
        base = [hit("base", "base_parent", 1)]

        output, audit = apply_structured_parent_lead_guard(
            "주의사항은?", POLICY, base, [hit("other", "parent_a", 1)], lead_index
        )

        self.assertEqual([row["chunk_id"] for row in output], ["base"])
        self.assertFalse(audit["structured_field_query"])
        self.assertEqual(audit["injected_chunk_ids"], [])


class ActualStructuredParentLeadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.retrieval = read_jsonl(DEFAULT_RETRIEVAL_RESULTS)
        cls.hybrid = read_jsonl(DEFAULT_HYBRID_RESULTS)
        cls.chunks = read_jsonl(DEFAULT_CHUNKS)
        cls.results = evaluate_signal(cls.dev, cls.retrieval, cls.hybrid, cls.chunks)
        cls.aggregate = aggregate_signal(cls.results)

    def test_actual_signal_is_deterministic_and_uses_no_gold_for_ranking(self) -> None:
        second = evaluate_signal(
            self.dev,
            list(reversed(self.retrieval)),
            list(reversed(self.hybrid)),
            list(reversed(self.chunks)),
        )

        self.assertEqual(self.results, second)
        self.assertEqual(len(self.results), 63)
        self.assertEqual(sum(row["signal"]["structured_field_query"] for row in self.results), 7)
        self.assertTrue(
            all(set(row["signal"]) == {"structured_field_query", "guard_chunk_ids", "injected_chunk_ids"} for row in self.results)
        )

    def test_actual_candidate_improves_best_hybrid_without_source_regression(self) -> None:
        metrics = self.aggregate["overall"]

        self.assertEqual(metrics["evaluated_count"], 55)
        self.assertEqual(metrics["mrr"], 0.709336)
        self.assertEqual(metrics["at_k"]["10"]["hit_rate"], 0.981818)
        self.assertEqual(metrics["at_k"]["10"]["all_groups_hit_rate"], 0.981818)
        self.assertEqual(metrics["at_k"]["10"]["evidence_group_recall_micro"], 0.983051)
        self.assertEqual(
            self.aggregate["by_source"]["dnf_seria_shop"]["at_k"]["10"][
                "all_groups_hit_rate"
            ],
            1.0,
        )
        self.assertIn(CANDIDATE_CONFIG, self.results[0]["configurations"])


class FrozenStructuredParentLeadArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

    def test_frozen_hashes_promotion_and_review_block_are_preserved(self) -> None:
        for path in (FROZEN_RESULTS, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        self.assertEqual(self.report["decision"]["experiment_integrity"], "GO")
        self.assertEqual(self.report["decision"]["retrieval_candidate_promotion"], "GO")
        self.assertEqual(self.report["decision"]["final_benchmark"], "NO-GO")
        self.assertTrue(self.report["promotion_audit"]["promotion_pass"])
        self.assertTrue(all(self.report["promotion_audit"]["gates"].values()))
        self.assertEqual(self.report["audit"]["structured_query_count"], 7)
        self.assertEqual(self.report["audit"]["guard_injection_count"], 7)
        self.assertEqual(len(self.report["remaining_failures_at_10"]), 1)
        self.assertEqual(
            self.report["remaining_failures_at_10"][0]["review_status"],
            "human_review_required",
        )

    def test_actual_inputs_refreeze_to_identical_artifacts(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_RETRIEVAL_RESULTS,
            RETRIEVAL_REPORT,
            DEFAULT_HYBRID_RESULTS,
            HYBRID_REPORT,
            DEFAULT_CHUNKS,
        )

        self.assertEqual(result["results_sha256"], file_sha256(FROZEN_RESULTS))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD))


if __name__ == "__main__":
    unittest.main()
