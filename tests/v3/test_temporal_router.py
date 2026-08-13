from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from src.v3.build_bm25 import build_bm25_index
from src.v3.build_corpus import file_sha256
from src.v3.retrieve_v3 import RuntimeArtifacts
from src.v3.schemas import TEMPORAL_ROUTE_REQUIRED_FIELDS
from src.v3.temporal_policy import build_policy_overlay
from src.v3.temporal_router import (
    DEFAULT_BM25_INDEX,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_CONFLICT_PACKET,
    DEFAULT_CONTRACT,
    DEFAULT_DOCUMENTS,
    DEFAULT_OVERLAY,
    DEFAULT_RETRIEVER_SOURCE,
    DEFAULT_SCHEMA_SOURCE,
    DEFAULT_SELECTOR_SOURCE,
    build_temporal_generator_entry,
    classify_temporal_query,
    freeze_temporal_router,
    route_and_retrieve_with_embedding,
    route_temporal_query,
    select_temporal_evidence,
)


def _document(index: int) -> dict:
    current = index == 2
    return {
        "document_id": f"document_{index}",
        "canonical_url": f"https://example.test/policy?revision=202{index}-01-01",
        "source_id": "dnf_account_policy",
        "source_kind": "account_policy",
        "title": f"운영정책 202{index}",
        "lineage_id": "lineage_policy",
        "published_at": f"202{index}-01-01",
        "valid_from": f"202{index}-01-01",
        "valid_to": None,
        "revision_id": f"revision_{index}",
        "supersedes_document_id": f"document_{index - 1}" if index else None,
        "status": "current" if current else "superseded",
        "default_exposure": current,
        "fetched_at": "2026-07-19T00:00:00+09:00",
    }


def _chunk(index: int) -> dict:
    current = index == 2
    return {
        "chunk_id": f"chunk_{index}",
        "parent_document_id": f"document_{index}",
        "retrieval_text": f"운영정책 사기 복구 규정 {index}",
        "display_text": f"운영정책 사기 복구 규정 {index}",
        "source_id": "dnf_account_policy",
        "source_kind": "account_policy",
        "status": "current" if current else "superseded",
        "default_exposure": current,
        "review_required": False,
        "offset_source": "dom_text",
        "valid_from": f"202{index}-01-01",
        "valid_to": None,
        "chunk_type": "section",
        "heading_path": ["운영정책"],
    }


class TemporalIntentClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = build_policy_overlay([_document(index) for index in range(3)])

    def test_current_duration_is_not_mistaken_for_historical_date(self) -> None:
        route = classify_temporal_query("복구 신청은 발생 후 15일 이내여야 해?")
        self.assertEqual(set(route), set(TEMPORAL_ROUTE_REQUIRED_FIELDS))
        self.assertEqual(route["mode"], "current")
        self.assertFalse(route["needs_clarification"])
        self.assertIsNone(route["as_of"])

    def test_exact_historical_date_and_ambiguous_year_are_separated(self) -> None:
        exact = route_temporal_query(
            "2021년 6월 1일 당시 운영정책의 복구 기준은?", self.overlay
        )
        self.assertEqual(exact["mode"], "historical")
        self.assertEqual(exact["as_of"], "2021-06-01")
        self.assertFalse(exact["needs_clarification"])

        ambiguous = route_temporal_query("2021년 운영정책은 어땠어?", self.overlay)
        self.assertEqual(ambiguous["mode"], "historical")
        self.assertTrue(ambiguous["needs_clarification"])
        self.assertEqual(
            ambiguous["clarification_reason"],
            "historical_mode_requires_exact_date",
        )

    def test_latest_previous_comparison_uses_current_boundary(self) -> None:
        route = route_temporal_query(
            "최신 정책과 직전 정책의 차이를 비교해줘.", self.overlay
        )
        self.assertEqual(route["mode"], "comparison")
        self.assertEqual(route["as_of"], "2022-01-01")
        self.assertEqual(route["as_of_source"], "latest_current_revision")
        self.assertFalse(route["needs_clarification"])

    def test_generic_past_comparison_and_multiple_dates_stop(self) -> None:
        generic = route_temporal_query(
            "현재와 과거 운영정책을 비교해줘.", self.overlay
        )
        self.assertEqual(generic["mode"], "comparison")
        self.assertTrue(generic["needs_clarification"])

        multiple = route_temporal_query(
            "2020년 1월 1일과 2021년 1월 1일 정책을 비교해줘.",
            self.overlay,
        )
        self.assertEqual(multiple["mode"], "comparison")
        self.assertTrue(multiple["needs_clarification"])
        self.assertEqual(
            multiple["clarification_reason"],
            "multiple_explicit_dates_require_target_pair",
        )

    def test_invalid_date_and_empty_query_fail(self) -> None:
        with self.assertRaises(RuntimeError):
            classify_temporal_query("")
        with self.assertRaises(RuntimeError):
            classify_temporal_query("2024년 2월 31일 당시 정책")


class TemporalRoutedPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        documents = [_document(index) for index in range(3)]
        chunks = [_chunk(index) for index in range(3)]
        bm25 = build_bm25_index(chunks, documents)
        self.chunks_by_id = {row["chunk_id"]: row for row in chunks}
        self.artifacts = RuntimeArtifacts(
            bm25_index=bm25,
            dense_metadata=[dict(row) for row in bm25["entries"]],
            dense_embeddings=np.eye(3, dtype=np.float32),
            dense_model={},
            chunks_by_id=self.chunks_by_id,
            documents_by_id={row["document_id"]: row for row in documents},
            lead_by_parent={},
            provenance={},
        )
        self.overlay = build_policy_overlay(documents)

    def _run(self, query: str, embedding: list[float], top_k: int = 3) -> dict:
        return route_and_retrieve_with_embedding(
            query,
            np.array(embedding, dtype=np.float32),
            self.artifacts,
            self.overlay,
            top_k=top_k,
        )

    def test_current_and_historical_modes_reach_generator_with_one_revision(self) -> None:
        current = self._run("현재 운영정책의 복구 규정은?", [0.0, 0.0, 1.0])
        self.assertEqual(
            {row["parent_document_id"] for row in current["hits"]},
            {"document_2"},
        )
        current_evidence = select_temporal_evidence(
            current["route"]["query"], current, self.chunks_by_id
        )
        current_entry = build_temporal_generator_entry(
            current["route"]["query"], current, current_evidence
        )
        self.assertTrue(current_entry["generation_allowed"])
        self.assertEqual(current_entry["blocked_reasons"], [])

        historical = self._run(
            "2021년 6월 1일 당시 운영정책의 복구 규정은?",
            [0.0, 1.0, 0.0],
        )
        self.assertEqual(
            {row["parent_document_id"] for row in historical["hits"]},
            {"document_1"},
        )
        historical_evidence = select_temporal_evidence(
            historical["route"]["query"], historical, self.chunks_by_id
        )
        historical_entry = build_temporal_generator_entry(
            historical["route"]["query"], historical, historical_evidence
        )
        self.assertTrue(historical_entry["generation_allowed"])
        self.assertIn("답변 기준일: 2021-06-01", historical_entry["required_answer_disclosures"])

    def test_comparison_requires_evidence_from_both_revisions(self) -> None:
        result = self._run(
            "최신 정책과 직전 정책의 복구 규정을 비교해줘.",
            [0.0, 0.0, 1.0],
            top_k=4,
        )
        evidence = select_temporal_evidence(
            result["route"]["query"], result, self.chunks_by_id
        )
        entry = build_temporal_generator_entry(
            result["route"]["query"], result, evidence
        )
        self.assertTrue(entry["generation_allowed"])
        self.assertEqual(
            {row["temporal_role"] for row in entry["evidence"]},
            {"selected_revision", "previous_revision"},
        )

        incomplete = [
            row for row in evidence if row["temporal_role"] == "selected_revision"
        ]
        blocked = build_temporal_generator_entry(
            result["route"]["query"], result, incomplete
        )
        self.assertFalse(blocked["generation_allowed"])
        self.assertIn(
            "comparison_revision_pair_incomplete", blocked["blocked_reasons"]
        )

    def test_clarification_stops_retrieval_and_generation(self) -> None:
        result = self._run("예전 운영정책의 복구 규정은?", [0.0, 1.0, 0.0])
        self.assertTrue(result["route"]["needs_clarification"])
        self.assertIsNone(result["resolution"])
        self.assertEqual(result["hits"], [])
        entry = build_temporal_generator_entry(result["route"]["query"], result, [])
        self.assertFalse(entry["generation_allowed"])
        self.assertIn("temporal_clarification_required", entry["blocked_reasons"])

    def test_current_generator_guard_rejects_superseded_injection(self) -> None:
        result = self._run("현재 운영정책의 복구 규정은?", [0.0, 0.0, 1.0])
        evidence = select_temporal_evidence(
            result["route"]["query"], result, self.chunks_by_id
        )
        injected = {
            **evidence[0],
            "chunk_id": "chunk_1",
            "parent_document_id": "document_1",
            "status": "superseded",
            "default_exposure": False,
        }
        entry = build_temporal_generator_entry(
            result["route"]["query"], result, evidence + [injected]
        )
        self.assertFalse(entry["generation_allowed"])
        self.assertIn("evidence_document_not_allowed", entry["blocked_reasons"])
        self.assertIn(
            "non_current_evidence_in_current_mode", entry["blocked_reasons"]
        )


def test_actual_inputs_refreeze_deterministically(tmp_path: Path) -> None:
    kwargs = {
        "root": Path.cwd(),
        "artifact_root": tmp_path,
        "documents_path": DEFAULT_DOCUMENTS,
        "chunks_path": DEFAULT_CHUNKS,
        "bm25_index_path": DEFAULT_BM25_INDEX,
        "overlay_path": DEFAULT_OVERLAY,
        "conflict_packet_path": DEFAULT_CONFLICT_PACKET,
        "builder_source_path": DEFAULT_BUILDER_SOURCE,
        "retriever_source_path": DEFAULT_RETRIEVER_SOURCE,
        "selector_source_path": DEFAULT_SELECTOR_SOURCE,
        "schema_source_path": DEFAULT_SCHEMA_SOURCE,
        "contract_path": DEFAULT_CONTRACT,
    }
    first = freeze_temporal_router(**kwargs)
    second = freeze_temporal_router(**kwargs)
    assert first == second
    for key in ("cases", "manifest", "report", "report_markdown"):
        assert file_sha256(Path(first[f"{key}_path"])) == first[f"{key}_sha256"]
    assert all(first["gates"].values())
    assert first["decisions"]["account_policy_temporal_intent_router"] == "GO"
    assert first["decisions"]["free_form_generator_generation"] == "NO-GO"


if __name__ == "__main__":
    unittest.main()
