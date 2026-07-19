from __future__ import annotations

import unittest

import numpy as np

from src.v3.build_bm25 import build_bm25_index
from src.v3.retrieve_temporal import retrieve_policy_with_embedding
from src.v3.retrieve_v3 import RuntimeArtifacts
from src.v3.temporal_policy import build_policy_overlay


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
        "retrieval_text": f"운영정책 규정 {index}",
        "display_text": f"운영정책 규정 {index}",
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


class TemporalRetrieverTest(unittest.TestCase):
    def setUp(self) -> None:
        documents = [_document(index) for index in range(3)]
        chunks = [_chunk(index) for index in range(3)]
        bm25 = build_bm25_index(chunks, documents)
        metadata = [dict(row) for row in bm25["entries"]]
        embeddings = np.eye(3, dtype=np.float32)
        chunks_by_id = {row["chunk_id"]: row for row in chunks}
        documents_by_id = {row["document_id"]: row for row in documents}
        self.artifacts = RuntimeArtifacts(
            bm25_index=bm25,
            dense_metadata=metadata,
            dense_embeddings=embeddings,
            dense_model={},
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            lead_by_parent={},
            provenance={},
        )
        self.overlay = build_policy_overlay(documents)

    def test_current_and_historical_modes_filter_before_both_rankers(self) -> None:
        current = retrieve_policy_with_embedding(
            "운영정책 규정",
            np.array([0.0, 0.0, 1.0], dtype=np.float32),
            self.artifacts,
            self.overlay,
            mode="current",
            top_k=3,
        )
        self.assertEqual(
            {row["parent_document_id"] for row in current["hits"]}, {"document_2"}
        )
        self.assertTrue(
            all(row["temporal_role"] == "selected_revision" for row in current["hits"])
        )

        historical = retrieve_policy_with_embedding(
            "운영정책 규정",
            np.array([0.0, 1.0, 0.0], dtype=np.float32),
            self.artifacts,
            self.overlay,
            mode="historical",
            as_of="2021-06-01",
            top_k=3,
        )
        self.assertEqual(
            {row["parent_document_id"] for row in historical["hits"]},
            {"document_1"},
        )

    def test_comparison_mode_returns_selected_and_previous_revision(self) -> None:
        result = retrieve_policy_with_embedding(
            "운영정책 규정",
            np.array([0.0, 0.0, 1.0], dtype=np.float32),
            self.artifacts,
            self.overlay,
            mode="comparison",
            as_of="2022-06-01",
            top_k=4,
        )
        self.assertEqual(
            result["resolution"]["allowed_document_ids"],
            ["document_2", "document_1"],
        )
        self.assertEqual(
            {row["temporal_role"] for row in result["hits"]},
            {"selected_revision", "previous_revision"},
        )
        self.assertEqual([row["rank"] for row in result["hits"]], [1, 2])

    def test_comparison_requires_space_for_both_revisions(self) -> None:
        with self.assertRaises(RuntimeError):
            retrieve_policy_with_embedding(
                "운영정책",
                np.array([0.0, 0.0, 1.0], dtype=np.float32),
                self.artifacts,
                self.overlay,
                mode="comparison",
                as_of="2022-06-01",
                top_k=1,
            )


if __name__ == "__main__":
    unittest.main()
