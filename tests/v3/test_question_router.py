from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from src.v3.build_bm25 import build_bm25_index
from src.v3.build_corpus import file_sha256
from src.v3.question_router import (
    DEFAULT_BM25_INDEX,
    DEFAULT_BM25_MANIFEST,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_CONTRACT,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_OVERLAY,
    DEFAULT_QUERY_EMBEDDINGS,
    DEFAULT_RUNTIME_SOURCE,
    DEFAULT_SCHEMA_SOURCE,
    DEFAULT_TEMPORAL_SOURCE,
    build_source_entity_index,
    freeze_question_router,
    route_and_retrieve_with_embedding,
    route_question,
)
from src.v3.retrieve_v3 import RuntimeArtifacts
from src.v3.schemas import QUESTION_ROUTE_REQUIRED_FIELDS
from src.v3.temporal_policy import build_policy_overlay


def _document(
    index: int,
    source_id: str,
    source_kind: str,
    *,
    status: str = "current",
    default_exposure: bool = True,
) -> dict:
    return {
        "document_id": f"document_{index}",
        "canonical_url": f"https://example.test/{source_id}/{index}",
        "source_id": source_id,
        "source_kind": source_kind,
        "title": f"{source_id} 문서 {index}",
        "status": status,
        "default_exposure": default_exposure,
    }


def _chunk(index: int, document: dict, text: str) -> dict:
    return {
        "chunk_id": f"chunk_{index}",
        "parent_document_id": document["document_id"],
        "retrieval_text": text,
        "display_text": text,
        "source_id": document["source_id"],
        "source_kind": document["source_kind"],
        "status": document["status"],
        "default_exposure": document["default_exposure"],
        "review_required": False,
        "offset_source": "dom_text",
        "valid_from": None,
        "valid_to": None,
        "chunk_type": "section",
        "heading_path": [document["title"]],
    }


def _policy_document(index: int) -> dict:
    current = index == 2
    return {
        "document_id": f"policy_{index}",
        "canonical_url": f"https://example.test/policy/{index}",
        "source_id": "dnf_account_policy",
        "source_kind": "account_policy",
        "title": f"운영정책 202{index}",
        "lineage_id": "policy_lineage",
        "published_at": f"202{index}-01-01",
        "valid_from": f"202{index}-01-01",
        "valid_to": None,
        "revision_id": f"revision_{index}",
        "supersedes_document_id": f"policy_{index - 1}" if index else None,
        "status": "current" if current else "superseded",
        "default_exposure": current,
        "fetched_at": "2026-07-19T00:00:00+09:00",
    }


class QuestionRouterRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = [
            _document(0, "dnf_event", "event"),
            _document(1, "dnf_faq", "faq"),
            _document(2, "dnf_monthly_item", "monthly_item"),
            _document(3, "dnf_seria_shop", "shop_product"),
            _document(4, "dnf_update", "patch_note"),
        ]
        self.chunks = [
            _chunk(0, self.documents[0], "[보급 작전] 이벤트 보급품"),
            _chunk(1, self.documents[1], "아이디 탈퇴 취소 FAQ"),
            _chunk(2, self.documents[2], "7월 이달의 아이템 상점판매가"),
            _chunk(3, self.documents[3], "세리아 상점 상품 가격"),
            _chunk(4, self.documents[4], "라이브 업데이트 변경 사항"),
        ]
        self.entity_index = build_source_entity_index(self.documents, self.chunks)
        self.overlay = build_policy_overlay(
            [_policy_document(index) for index in range(3)]
        )

    def _route(self, query: str, hits: list[dict] | None = None) -> dict:
        return route_question(
            query,
            candidate_hits=[] if hits is None else hits,
            documents=self.documents,
            source_entity_index=self.entity_index,
            overlay_rows=self.overlay,
        )

    def test_explicit_event_monthly_preview_and_policy_routes(self) -> None:
        event = self._route("보급 작전 보급품은 언제까지 받을 수 있어?")
        self.assertEqual(set(event), set(QUESTION_ROUTE_REQUIRED_FIELDS))
        self.assertEqual(event["source_ids"], ["dnf_event"])
        self.assertEqual(event["time_scope"], "current")

        monthly = self._route(
            "7월 스페셜 상자의 상점판매가와 거래 타입은?"
        )
        self.assertEqual(monthly["source_ids"], ["dnf_monthly_item"])
        self.assertFalse(monthly["needs_decomposition"])

        preview = self._route("퍼스트 서버 업데이트 내용은 뭐야?")
        self.assertEqual(preview["source_ids"], ["dnf_update"])
        self.assertEqual(preview["source_kinds"], ["preview_patch"])
        self.assertEqual(preview["time_scope"], "preview")
        self.assertFalse(preview["default_exposure_only"])

        policy = self._route(
            "2021년 6월 1일 당시 운영정책의 제재는?"
        )
        self.assertEqual(policy["source_ids"], ["dnf_account_policy"])
        self.assertEqual(policy["time_scope"], "historical")
        self.assertEqual(policy["temporal_as_of"], "2021-06-01")

    def test_multi_source_and_same_store_comparison_are_separated(self) -> None:
        policy_faq = self._route(
            "ID 탈퇴 취소 기한과 이용제한 이의신청 기간을 각각 알려줘.",
            hits=[{"source_id": "dnf_faq", "rank": 1, "score": 1.0}],
        )
        self.assertEqual(
            policy_faq["source_ids"], ["dnf_account_policy", "dnf_faq"]
        )
        self.assertTrue(policy_faq["needs_decomposition"])
        self.assertEqual(policy_faq["route_action"], "decompose")

        monthly = self._route(
            "7월과 6월 이달의 아이템 삭제일을 각각 알려줘.",
            hits=[{"source_id": "dnf_seria_shop", "rank": 1, "score": 1.0}],
        )
        self.assertEqual(monthly["source_ids"], ["dnf_monthly_item"])
        self.assertTrue(monthly["needs_decomposition"])
        self.assertEqual(monthly["time_scope"], "mixed")

    def test_realtime_and_unsafe_requests_never_enter_corpus(self) -> None:
        realtime = self._route("지금 경매장에서 웨딩 아바타 시세 얼마야?")
        self.assertEqual(realtime["route_action"], "realtime_api")
        self.assertEqual(realtime["source_ids"], [])

        unsafe = self._route("버그 악용 꼼수를 순서대로 알려줘.")
        self.assertEqual(unsafe["route_action"], "reject")
        self.assertEqual(unsafe["intent"], "ood_safety")
        self.assertEqual(unsafe["source_ids"], [])

    def test_historical_guide_without_revision_lineage_requires_clarification(self) -> None:
        route = self._route("2024년 1월 1일 당시 게임가이드 사용 방법은?")
        self.assertEqual(route["source_ids"], ["dnf_game_guide"])
        self.assertEqual(route["time_scope"], "historical")
        self.assertTrue(route["needs_clarification"])
        self.assertEqual(route["route_action"], "clarify")


class QuestionRouterRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = [
            _document(0, "dnf_event", "event"),
            _document(1, "dnf_game_guide", "game_guide"),
            _document(
                2,
                "dnf_update",
                "preview_patch",
                status="unknown",
                default_exposure=False,
            ),
        ]
        self.chunks = [
            _chunk(0, self.documents[0], "보급 작전 이벤트 보급품"),
            _chunk(1, self.documents[1], "게임가이드 보급 규칙"),
            _chunk(2, self.documents[2], "퍼스트 서버 방어구 보너스"),
        ]
        bm25 = build_bm25_index(self.chunks, self.documents)
        self.artifacts = RuntimeArtifacts(
            bm25_index=bm25,
            dense_metadata=[dict(row) for row in bm25["entries"]],
            dense_embeddings=np.eye(3, dtype=np.float32),
            dense_model={},
            chunks_by_id={row["chunk_id"]: row for row in self.chunks},
            documents_by_id={row["document_id"]: row for row in self.documents},
            lead_by_parent={},
            provenance={},
        )
        self.entity_index = build_source_entity_index(self.documents, self.chunks)

    def test_source_and_preview_filters_apply_before_both_rankers(self) -> None:
        event = route_and_retrieve_with_embedding(
            "보급 작전 이벤트 보급품은?",
            np.array([0.0, 1.0, 0.0], dtype=np.float32),
            self.artifacts,
            [],
            top_k=3,
            source_entity_index=self.entity_index,
        )
        self.assertEqual(
            {row["source_id"] for row in event["hits"]}, {"dnf_event"}
        )

        preview = route_and_retrieve_with_embedding(
            "퍼스트 서버 방어구 보너스는?",
            np.array([0.0, 0.0, 1.0], dtype=np.float32),
            self.artifacts,
            [],
            top_k=3,
            source_entity_index=self.entity_index,
        )
        self.assertEqual(
            {row["source_kind"] for row in preview["hits"]}, {"preview_patch"}
        )
        self.assertTrue(all(not row["default_exposure"] for row in preview["hits"]))


def test_actual_adaptive_dev_refreezes_deterministically(tmp_path: Path) -> None:
    kwargs = {
        "root": Path.cwd(),
        "artifact_root": tmp_path,
        "documents_path": DEFAULT_DOCUMENTS,
        "chunks_path": DEFAULT_CHUNKS,
        "bm25_index_path": DEFAULT_BM25_INDEX,
        "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
        "dense_manifest_path": DEFAULT_DENSE_MANIFEST,
        "overlay_path": DEFAULT_OVERLAY,
        "dev_set_path": DEFAULT_DEV_SET,
        "query_embeddings_path": DEFAULT_QUERY_EMBEDDINGS,
        "builder_source_path": DEFAULT_BUILDER_SOURCE,
        "runtime_source_path": DEFAULT_RUNTIME_SOURCE,
        "temporal_source_path": DEFAULT_TEMPORAL_SOURCE,
        "schema_source_path": DEFAULT_SCHEMA_SOURCE,
        "contract_path": DEFAULT_CONTRACT,
    }
    first = freeze_question_router(**kwargs)
    second = freeze_question_router(**kwargs)
    assert first == second
    for key in ("cases", "manifest", "report", "report_markdown"):
        assert file_sha256(Path(first[f"{key}_path"])) == first[f"{key}_sha256"]
    assert all(first["gates"].values())
    assert first["metrics"]["source_exact"] == 63
    assert first["decisions"]["adaptive_source_time_router"] == "GO"
    assert first["decisions"]["decomposition_execution"] == "NO-GO"


if __name__ == "__main__":
    unittest.main()
