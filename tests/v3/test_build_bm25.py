from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_bm25 import (
    SearchPolicy,
    audit_bm25_index,
    build_bm25_artifacts,
    build_bm25_index,
    search_bm25,
    tokenize_lexical,
)
from src.v3.build_corpus import file_sha256


def _document(document_id: str, title: str) -> dict:
    return {
        "document_id": document_id,
        "canonical_url": f"https://example.test/{document_id}",
        "title": title,
    }


def _chunk(
    chunk_id: str,
    parent_document_id: str,
    text: str,
    *,
    status: str = "current",
    default_exposure: bool = True,
    review_required: bool = False,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": parent_document_id,
        "retrieval_text": text,
        "source_id": "dnf_notice",
        "source_kind": "general_notice",
        "status": status,
        "default_exposure": default_exposure,
        "review_required": review_required,
        "offset_source": "visual_ocr" if review_required else "dom_text",
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


BUILT_AT = "2026-07-18T01:35:07+09:00"
CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
CHUNK_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json"
)
DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
FROZEN_INDEX = Path(
    "data/v3/indexes/"
    "bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
FROZEN_MANIFEST = Path(
    "data/v3/indexes/"
    "bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
FROZEN_SMOKE = Path(
    "data/v3/retrieval/"
    "bm25_smoke_9a6ea43369174ef761f95e7a371bf9fdcf8e0c5824732e28bea06e4b2fc487c0.jsonl"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "bm25_baseline_905fed042802020d2b0aeefc50136df166cac70fc4d4f71706f156c9741a3acc.json"
)


class BuildBm25Test(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = [
            _document("doc_current", "정기점검 안내"),
            _document("doc_expired", "종료 이벤트"),
            _document("doc_visual", "이미지 가격표"),
            _document("doc_future", "예정 이벤트"),
        ]
        self.chunks = [
            _chunk("chunk_current", "doc_current", "정기점검 서버 점검 안내"),
            _chunk(
                "chunk_expired",
                "doc_expired",
                "종료 이벤트 특별 보상",
                status="expired",
                default_exposure=False,
            ),
            _chunk(
                "chunk_visual",
                "doc_visual",
                "이미지 가격 1,000 세라",
                default_exposure=False,
                review_required=True,
            ),
            _chunk(
                "chunk_future",
                "doc_future",
                "예정 이벤트 미래 보상",
                valid_from="2027-01-01",
            ),
        ]

    def test_tokenizer_normalizes_nfkc_case_and_date_variants(self) -> None:
        tokens = tokenize_lexical("ＡＢＣ 7월 18일 07/18")

        self.assertIn("abc", tokens)
        self.assertIn("7/18", tokens)
        self.assertIn("07-18", tokens)
        self.assertIn("7월", tokens)
        self.assertIn("18일", tokens)

    def test_default_filter_excludes_historical_visual_and_future_rows(self) -> None:
        index = build_bm25_index(self.chunks, self.documents)

        current = search_bm25(index, "정기점검", policy=SearchPolicy(as_of="2026-07-18"))
        expired_default = search_bm25(index, "특별 보상", policy=SearchPolicy())
        expired_control = search_bm25(
            index,
            "특별 보상",
            policy=SearchPolicy(default_exposure_only=False, allowed_statuses=("expired",)),
        )
        visual_default = search_bm25(index, "1,000 세라", policy=SearchPolicy())
        visual_control = search_bm25(
            index,
            "1,000 세라",
            policy=SearchPolicy(
                default_exposure_only=False,
                allowed_statuses=("current",),
                include_review_required=True,
            ),
        )
        future = search_bm25(index, "미래 보상", policy=SearchPolicy(as_of="2026-07-18"))

        self.assertEqual(current[0]["chunk_id"], "chunk_current")
        self.assertNotIn("chunk_expired", {row["chunk_id"] for row in expired_default})
        self.assertEqual(expired_control[0]["chunk_id"], "chunk_expired")
        self.assertNotIn("chunk_visual", {row["chunk_id"] for row in visual_default})
        self.assertEqual(visual_control[0]["chunk_id"], "chunk_visual")
        self.assertNotIn("chunk_future", {row["chunk_id"] for row in future})

    def test_index_is_order_independent_and_audit_rebuilds_exactly(self) -> None:
        first = build_bm25_index(self.chunks, self.documents)
        second = build_bm25_index(list(reversed(self.chunks)), list(reversed(self.documents)))

        self.assertEqual(first, second)
        gates = audit_bm25_index(self.chunks, first, expected_chunk_count=4)
        self.assertTrue(all(value is True or value == 0 for value in gates.values()))


class FrozenBm25ArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = read_jsonl(CHUNKS)
        cls.documents = read_jsonl(DOCUMENTS)
        cls.index = json.loads(FROZEN_INDEX.read_text(encoding="utf-8"))
        cls.manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        cls.smoke = read_jsonl(FROZEN_SMOKE)
        cls.report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

    def test_actual_bm25_artifacts_pass_hash_index_filter_and_dense_length_gates(self) -> None:
        self.assertEqual(file_sha256(FROZEN_INDEX), FROZEN_INDEX.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_SMOKE), FROZEN_SMOKE.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[1])
        self.assertEqual(self.index["document_count"], 3599)
        self.assertEqual(len(self.index["entries"]), 3599)
        self.assertEqual(len(self.index["postings"]), 29980)
        self.assertEqual(len(self.smoke), 12)
        self.assertTrue(
            all(value is True or value == 0 for value in self.report["gates"].values())
        )
        self.assertEqual(self.report["lexical_baseline_decision"], "GO")
        self.assertEqual(self.report["dense_tokenizer_readiness"], "GO")
        dense = self.report["dense_token_measurement"]
        self.assertEqual(dense["row_count"], 3599)
        self.assertEqual(dense["model_max_length"], 8192)
        self.assertEqual(dense["over_threshold"]["512"], 1182)
        self.assertEqual(dense["over_threshold"]["1024"], 80)
        self.assertEqual(dense["over_threshold"]["2048"], 0)
        self.assertEqual(dense["over_threshold"]["8192"], 0)
        gates = audit_bm25_index(self.chunks, self.index, expected_chunk_count=3599)
        self.assertTrue(all(value is True or value == 0 for value in gates.values()))
        hits = search_bm25(
            self.index,
            "정기점검 업데이트",
            top_k=3,
            policy=SearchPolicy(as_of="2026-07-18"),
        )
        self.assertTrue(hits)
        self.assertTrue(
            all(
                row["default_exposure"]
                and row["status"] in {"current", "upcoming"}
                and not row["review_required"]
                for row in hits
            )
        )

    def test_actual_bm25_refreeze_is_reproducible_without_reloading_tokenizer(self) -> None:
        kwargs = {
            "built_at": BUILT_AT,
            "chunks_path": CHUNKS,
            "chunk_manifest_path": CHUNK_MANIFEST,
            "documents_path": DOCUMENTS,
            "index_dir": Path("data/v3/indexes"),
            "retrieval_dir": Path("data/v3/retrieval"),
            "report_dir": Path("reports/v3"),
            "dense_measurement_override": self.report["dense_token_measurement"],
        }

        first = build_bm25_artifacts(**kwargs)
        second = build_bm25_artifacts(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["index_sha256"], file_sha256(FROZEN_INDEX))
        self.assertEqual(first["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(first["smoke_sha256"], file_sha256(FROZEN_SMOKE))
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_REPORT))


if __name__ == "__main__":
    unittest.main()
