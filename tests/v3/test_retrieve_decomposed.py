from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from src.v3.build_corpus import file_sha256
from src.v3.retrieve_decomposed import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_CONTRACT,
    DEFAULT_DECOMPOSER_SOURCE,
    DEFAULT_DECOMPOSITION_CASES,
    DEFAULT_DECOMPOSITION_MANIFEST,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_OVERLAY,
    DEFAULT_QUERY_EMBEDDINGS,
    DEFAULT_ROUTER_SOURCE,
    DEFAULT_RUNTIME_SOURCE,
    DEFAULT_SELECTOR_SOURCE,
    document_overlaps_window,
    freeze_decomposed_hybrid,
    infer_historical_month_window,
    merge_decomposed_evidence,
)


FROZEN_CASES = Path(
    "data/v3/decomposition/"
    "decomposed_hybrid_cases_"
    "3ee97cdf7a0ad0f7c124269ea9459a8ba2633d20d4572b11a333e86b5fd35c67.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/decomposition/"
    "decomposed_hybrid_manifest_"
    "d352cf2bcc21f89acfb7647e48ce91b1b1b0fd819ddb901e64b54713aed9e980.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "decomposed_hybrid_"
    "d561fdf0746f5c61d5f7655f47d22516c0f482ca538ff1130b14835e238f3375.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "decomposed_hybrid_"
    "6bbebfbd57ade8b991dc7766a4c9ba28dd4e953ea461c63fe7fd87261e928951.md"
)


def _document(
    document_id: str,
    *,
    lineage_id: str,
    revision_id: str,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "lineage_id": lineage_id,
        "revision_id": revision_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def _child(
    ordinal: int,
    *,
    time_scope: str,
    selected: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "subquestion": {
            "subquestion_id": f"sub_{ordinal}",
            "ordinal": ordinal,
            "question": f"question {ordinal}",
        },
        "route": {
            "source_ids": ["dnf_monthly_item"],
            "source_kinds": ["monthly_item"],
            "time_scope": time_scope,
        },
        "selected_evidence": selected,
    }


def _selected(
    chunk_id: str,
    document_id: str,
    *,
    status: str,
    default_exposure: bool,
    rank: int = 1,
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": document_id,
        "source_id": "dnf_monthly_item",
        "source_kind": "monthly_item",
        "status": status,
        "default_exposure": default_exposure,
        "review_required": False,
        "selected_rank": rank,
        "retrieval_rank": rank,
        "display_text": f"evidence {chunk_id}",
    }


class DecomposedTemporalWindowTest(unittest.TestCase):
    def test_historical_month_is_restored_to_closed_calendar_window(self) -> None:
        self.assertEqual(
            infer_historical_month_window(
                "이달의 아이템 기준으로 2026년 6월 당시 삭제일은?",
                "historical",
            ),
            ("2026-06-01", "2026-06-30"),
        )
        self.assertIsNone(
            infer_historical_month_window("7월 이달의 아이템은?", "current")
        )

    def test_historical_window_requires_explicit_document_validity(self) -> None:
        self.assertTrue(
            document_overlaps_window(
                {"valid_from": "2026-06-04", "valid_to": "2026-07-09"},
                ("2026-06-01", "2026-06-30"),
            )
        )
        self.assertFalse(
            document_overlaps_window(
                {"valid_from": "2026-07-02", "valid_to": "2026-08-13"},
                ("2026-06-01", "2026-06-30"),
            )
        )
        self.assertFalse(
            document_overlaps_window(
                {"valid_from": None, "valid_to": None},
                ("2026-06-01", "2026-06-30"),
            )
        )


class DecomposedEvidenceMergeTest(unittest.TestCase):
    def test_exact_chunk_dedup_preserves_all_child_slots(self) -> None:
        documents = {
            "doc_current": _document(
                "doc_current", lineage_id="lineage", revision_id="rev_current"
            )
        }
        selected = _selected(
            "chunk_shared",
            "doc_current",
            status="current",
            default_exposure=True,
        )
        result = merge_decomposed_evidence(
            "parent",
            [
                _child(1, time_scope="current", selected=[selected]),
                _child(2, time_scope="current", selected=[selected]),
            ],
            documents,
        )

        self.assertEqual(result["merge_status"], "resolved_no_conflict")
        self.assertEqual(len(result["merged_candidates"]), 1)
        self.assertEqual(
            result["merged_candidates"][0]["subquestion_ids"], ["sub_1", "sub_2"]
        )
        self.assertEqual(result["policy_violations"], [])

    def test_current_revision_conflict_blocks_merged_packet(self) -> None:
        documents = {
            "doc_old": _document(
                "doc_old", lineage_id="lineage", revision_id="rev_old"
            ),
            "doc_new": _document(
                "doc_new", lineage_id="lineage", revision_id="rev_new"
            ),
        }
        result = merge_decomposed_evidence(
            "parent",
            [
                _child(
                    1,
                    time_scope="current",
                    selected=[
                        _selected(
                            "chunk_old",
                            "doc_old",
                            status="current",
                            default_exposure=True,
                        )
                    ],
                ),
                _child(
                    2,
                    time_scope="current",
                    selected=[
                        _selected(
                            "chunk_new",
                            "doc_new",
                            status="current",
                            default_exposure=True,
                        )
                    ],
                ),
            ],
            documents,
        )

        self.assertEqual(result["merge_status"], "blocked_revision_conflict")
        self.assertEqual(result["merged_candidates"], [])
        self.assertEqual(len(result["revision_conflicts"]), 1)

    def test_explicit_current_historical_slots_preserve_revision_pair(self) -> None:
        documents = {
            "doc_old": _document(
                "doc_old", lineage_id="lineage", revision_id="rev_old"
            ),
            "doc_new": _document(
                "doc_new", lineage_id="lineage", revision_id="rev_new"
            ),
        }
        result = merge_decomposed_evidence(
            "parent",
            [
                _child(
                    1,
                    time_scope="current",
                    selected=[
                        _selected(
                            "chunk_new",
                            "doc_new",
                            status="current",
                            default_exposure=True,
                        )
                    ],
                ),
                _child(
                    2,
                    time_scope="historical",
                    selected=[
                        _selected(
                            "chunk_old",
                            "doc_old",
                            status="superseded",
                            default_exposure=False,
                        )
                    ],
                ),
            ],
            documents,
        )

        self.assertEqual(result["merge_status"], "explicit_temporal_separation")
        self.assertEqual(len(result["merged_candidates"]), 2)
        self.assertEqual(result["revision_conflicts"], [])

    def test_current_slot_rejects_expired_or_non_default_evidence(self) -> None:
        documents = {
            "doc_old": _document(
                "doc_old", lineage_id="lineage", revision_id="rev_old"
            )
        }
        result = merge_decomposed_evidence(
            "parent",
            [
                _child(
                    1,
                    time_scope="current",
                    selected=[
                        _selected(
                            "chunk_old",
                            "doc_old",
                            status="expired",
                            default_exposure=False,
                        )
                    ],
                )
            ],
            documents,
        )

        self.assertEqual(result["merge_status"], "blocked_policy_violation")
        self.assertEqual(result["merged_candidates"], [])
        self.assertEqual(len(result["policy_violations"]), 2)


def test_frozen_decomposed_artifacts_match_recorded_sha() -> None:
    for path in (FROZEN_CASES, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
        assert file_sha256(path) == path.stem.rsplit("_", 1)[-1]


def test_decomposed_generator_is_reproducible(tmp_path: Path) -> None:
    embeddings = np.fromfile(DEFAULT_QUERY_EMBEDDINGS, dtype="<f4").reshape(8, 1024)
    kwargs = {
        "root": Path.cwd(),
        "artifact_root": tmp_path,
        "documents_path": DEFAULT_DOCUMENTS,
        "chunks_path": DEFAULT_CHUNKS,
        "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
        "dense_manifest_path": DEFAULT_DENSE_MANIFEST,
        "overlay_path": DEFAULT_OVERLAY,
        "dev_set_path": DEFAULT_DEV_SET,
        "decomposition_cases_path": DEFAULT_DECOMPOSITION_CASES,
        "decomposition_manifest_path": DEFAULT_DECOMPOSITION_MANIFEST,
        "builder_source_path": DEFAULT_BUILDER_SOURCE,
        "runtime_source_path": DEFAULT_RUNTIME_SOURCE,
        "router_source_path": DEFAULT_ROUTER_SOURCE,
        "decomposer_source_path": DEFAULT_DECOMPOSER_SOURCE,
        "selector_source_path": DEFAULT_SELECTOR_SOURCE,
        "contract_path": DEFAULT_CONTRACT,
        "query_embeddings": embeddings,
    }
    first = freeze_decomposed_hybrid(**kwargs)
    second = freeze_decomposed_hybrid(**kwargs)

    assert first == second
    assert all(first["gates"].values())
    assert first["metrics"]["merged_evidence_group_hits"] == 8
    assert first["decisions"]["child_hybrid_retrieval"] == "GO"
    assert first["decisions"]["evidence_merge_and_conflict_policy"] == "GO"


if __name__ == "__main__":
    unittest.main()
