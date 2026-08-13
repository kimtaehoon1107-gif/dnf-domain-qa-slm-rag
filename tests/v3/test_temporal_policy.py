from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_bm25 import search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.schemas import TEMPORAL_POLICY_REVISION_REQUIRED_FIELDS
from src.v3.temporal_policy import (
    DEFAULT_BM25_INDEX,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_CONFLICT_PACKET,
    DEFAULT_CONFLICT_DRAFT,
    DEFAULT_CONTRACT,
    DEFAULT_DOCUMENTS,
    DEFAULT_SCHEMA_SOURCE,
    DEFAULT_SEARCH_SOURCE,
    audit_policy_overlay,
    build_policy_overlay,
    freeze_temporal_policy,
    restrict_bm25_index,
    resolve_policy_revisions,
    search_policy_for_resolution,
)


class AccountPolicyTemporalOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = read_jsonl(DEFAULT_DOCUMENTS)
        cls.overlay = build_policy_overlay(cls.documents)

    def test_actual_overlay_has_complete_revision_lineage(self) -> None:
        audit = audit_policy_overlay(self.overlay)
        self.assertTrue(audit["gate_pass"])
        self.assertEqual(len(self.overlay), 51)
        self.assertEqual(
            set(TEMPORAL_POLICY_REVISION_REQUIRED_FIELDS), set(self.overlay[0])
        )
        current = [row for row in self.overlay if row["is_current_revision"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["valid_from"], "2026-03-15")
        self.assertIsNone(current[0]["valid_to"])
        self.assertTrue(current[0]["default_exposure"])

    def test_every_effective_date_resolves_exact_revision_and_pair(self) -> None:
        for ordinal, row in enumerate(self.overlay):
            historical = resolve_policy_revisions(
                self.overlay, mode="historical", as_of=row["valid_from"]
            )
            self.assertEqual(historical["selected_document_id"], row["document_id"])
            if ordinal:
                comparison = resolve_policy_revisions(
                    self.overlay, mode="comparison", as_of=row["valid_from"]
                )
                self.assertEqual(
                    comparison["allowed_document_ids"],
                    [row["document_id"], self.overlay[ordinal - 1]["document_id"]],
                )

    def test_current_policy_filters_six_cancelled_questions_before_bm25(self) -> None:
        index = json.loads(DEFAULT_BM25_INDEX.read_text(encoding="utf-8"))
        packet = read_jsonl(DEFAULT_CONFLICT_PACKET)
        current = resolve_policy_revisions(self.overlay, mode="current")
        policy = search_policy_for_resolution(current)
        current_index = restrict_bm25_index(
            index, current["allowed_document_ids"]
        )
        old_origin_ids = {
            row["revision_comparison"]["origin_document_id"] for row in packet
        }
        for row in packet:
            hits = search_bm25(
                current_index, row["question"], top_k=10, policy=policy
            )
            self.assertTrue(hits)
            self.assertEqual(
                {hit["parent_document_id"] for hit in hits},
                {current["selected_document_id"]},
            )
            self.assertFalse(any(hit["status"] == "superseded" for hit in hits))
            self.assertFalse(
                old_origin_ids & {hit["parent_document_id"] for hit in hits}
            )

    def test_modes_require_valid_dates(self) -> None:
        with self.assertRaises(RuntimeError):
            resolve_policy_revisions(self.overlay, mode="historical")
        with self.assertRaises(RuntimeError):
            resolve_policy_revisions(
                self.overlay, mode="comparison", as_of="2010-01-01"
            )


def test_actual_inputs_refreeze_deterministically(tmp_path: Path) -> None:
    kwargs = {
        "root": Path.cwd(),
        "artifact_root": tmp_path,
        "documents_path": DEFAULT_DOCUMENTS,
        "chunks_path": DEFAULT_CHUNKS,
        "bm25_index_path": DEFAULT_BM25_INDEX,
        "conflict_packet_path": DEFAULT_CONFLICT_PACKET,
        "conflict_draft_path": DEFAULT_CONFLICT_DRAFT,
        "builder_source_path": DEFAULT_BUILDER_SOURCE,
        "search_source_path": DEFAULT_SEARCH_SOURCE,
        "schema_source_path": DEFAULT_SCHEMA_SOURCE,
        "contract_path": DEFAULT_CONTRACT,
    }
    first = freeze_temporal_policy(**kwargs)
    second = freeze_temporal_policy(**kwargs)
    assert first == second
    for key in ("overlay", "manifest", "report", "report_markdown"):
        path = Path(first[f"{key}_path"])
        assert file_sha256(path) == first[f"{key}_sha256"]
    assert first["decisions"]["current_policy_retrieval_filter"] == "GO"
    assert first["decisions"]["revision_conflict_human_review"] == "CANCELLED"


if __name__ == "__main__":
    unittest.main()
