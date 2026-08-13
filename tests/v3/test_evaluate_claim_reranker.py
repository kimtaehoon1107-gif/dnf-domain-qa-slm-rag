from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import src.v3.evaluate_claim_reranker as claim_reranker_evaluator
from src.v3.collect_details import write_immutable
from src.v3.evaluate_claim_reranker import (
    verify_reranked_claim,
)


class RerankedClaimVerifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.route = {
            "source_ids": ["dnf_account_policy"],
            "source_kinds": ["account_policy"],
            "time_scope": "current",
        }
        self.chunk = {
            "chunk_id": "chunk_current",
            "parent_document_id": "doc_current",
            "source_id": "dnf_account_policy",
            "source_kind": "account_policy",
            "status": "current",
            "default_exposure": True,
            "display_text": "근거 데이터는 90일간 보유합니다.",
        }
        self.document = {
            "document_id": "doc_current",
            "revision_id": "rev_current",
            "source_id": "dnf_account_policy",
            "source_kind": "account_policy",
            "status": "current",
            "default_exposure": True,
        }
        self.claim = {
            "claim_text": "근거 데이터는 90일간 보유합니다.",
            "citation_chunk_id": "chunk_current",
            "citation_parent_document_id": "doc_current",
            "revision_id": "rev_current",
        }

    def test_exact_current_claim_passes_all_gates(self) -> None:
        result = verify_reranked_claim(
            self.claim,
            self.route,
            self.chunk,
            self.document,
            current_policy_document_id="doc_current",
        )
        self.assertTrue(result["verified"])
        self.assertTrue(all(result["gates"].values()))

    def test_non_exact_quote_fails_closed(self) -> None:
        claim = {**self.claim, "claim_text": "보유 기간은 30일입니다."}
        result = verify_reranked_claim(
            claim,
            self.route,
            self.chunk,
            self.document,
            current_policy_document_id="doc_current",
        )
        self.assertFalse(result["verified"])
        self.assertFalse(result["gates"]["exact_canonical_quote"])

    def test_current_policy_must_use_latest_revision(self) -> None:
        result = verify_reranked_claim(
            self.claim,
            self.route,
            self.chunk,
            self.document,
            current_policy_document_id="doc_newer",
        )
        self.assertFalse(result["verified"])
        self.assertFalse(result["gates"]["current_policy_revision"])


class ClaimRerankerArtifactTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    CASES_SHA = "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a"
    MANIFEST_SHA = "32d236a75d30ead63c33530e92ea1349bb8000e6f03615e3783c82f76ce6bd6c"

    def test_frozen_artifacts_match_recorded_sha(self) -> None:
        cases_path = self.ROOT / (
            f"data/v3/evidence/claim_reranker_cases_{self.CASES_SHA}.jsonl"
        )
        manifest_path = self.ROOT / (
            f"data/v3/evidence/claim_reranker_manifest_{self.MANIFEST_SHA}.json"
        )
        self.assertEqual(
            hashlib.sha256(cases_path.read_bytes()).hexdigest(), self.CASES_SHA
        )
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(), self.MANIFEST_SHA
        )
        rows = [
            json.loads(line)
            for line in cases_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(rows), 63)
        self.assertEqual(
            [row["query_ordinal"] for row in rows], list(range(63))
        )


def test_claim_reranker_generator_is_reproducible(
    tmp_path: Path, monkeypatch
) -> None:
    root = Path(__file__).resolve().parents[2]

    def write_to_tmp(path: Path, content: bytes) -> None:
        write_immutable(tmp_path / path.resolve().relative_to(root), content)

    monkeypatch.setattr(claim_reranker_evaluator, "write_immutable", write_to_tmp)
    first = claim_reranker_evaluator.freeze_claim_reranker(root=root)
    second = claim_reranker_evaluator.freeze_claim_reranker(root=root)

    assert first == second
    assert first["metrics"]["reranked_cited_group_hits"] == 56
    assert first["metrics"]["strict_regressions"] == 0
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 4


if __name__ == "__main__":
    unittest.main()
