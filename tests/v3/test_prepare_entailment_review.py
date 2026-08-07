from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.prepare_entailment_review import (
    DEFAULT_BM25_INDEX,
    DEFAULT_BM25_MANIFEST,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_RERANKER_MANIFEST,
    DEFAULT_RERANKER_SCORES,
    HISTORICAL_QUOTAS,
    audit_completed_reviews,
    audit_packet,
    build_and_freeze,
    build_packet_and_ledger,
)


FROZEN_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_packet_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl"
)
FROZEN_LEDGER = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_manifest_0a318f692c2c7c3e761b06dd4a10959b4fcf25f4b59adbf9597b3fc1180eb49e.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "entailment_natural_review_a55d8b984b26a63c6847503e24c7d622758fc75a0792d26b73c5f8c7cf2a7cc4.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "entailment_natural_review_64c40b0be207a15cdff5b90a5d56c2519fa268d96380c3fb08ba79f9c0b11525.md"
)


def _load_index() -> dict:
    return json.loads(DEFAULT_BM25_INDEX.read_text(encoding="utf-8"))


def _complete_reviews(packet: list[dict]) -> list[dict]:
    completed = copy.deepcopy(packet)
    labels = ("support", "contradiction", "insufficient")
    for ordinal, row in enumerate(completed):
        label = labels[ordinal % len(labels)]
        row["review_label"] = label
        row["reviewer_type"] = "human"
        row["reviewer_id"] = "reviewer-kim"
        row["reviewed_at"] = "2026-07-18T18:00:00+09:00"
        row["review_rationale"] = "The official evidence was checked against every material claim."
        row["needs_adjudication"] = False
        row["decisive_excerpt"] = (
            row["evidence_text"][:40]
            if label in {"support", "contradiction"}
            else None
        )
    return completed


class EntailmentNaturalReviewSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = (
            read_jsonl(DEFAULT_DEV_SET),
            read_jsonl(DEFAULT_RERANKER_SCORES),
            read_jsonl(DEFAULT_CHUNKS),
            read_jsonl(DEFAULT_DOCUMENTS),
            _load_index(),
        )
        cls.packet, cls.ledger = build_packet_and_ledger(*cls.inputs)

    def test_selection_is_deterministic_balanced_and_blinded(self) -> None:
        second_packet, second_ledger = build_packet_and_ledger(
            list(reversed(self.inputs[0])),
            list(reversed(self.inputs[1])),
            list(reversed(self.inputs[2])),
            list(reversed(self.inputs[3])),
            self.inputs[4],
        )
        self.assertEqual(self.packet, second_packet)
        self.assertEqual(self.ledger, second_ledger)
        audit = audit_packet(self.packet, self.ledger)
        self.assertTrue(audit["gate_pass"])
        self.assertEqual(audit["stratum_counts"]["annotated_anchor"], 16)
        self.assertEqual(audit["stratum_counts"]["default_hard_candidate"], 16)
        self.assertEqual(
            audit["stratum_counts"]["historical_revision_candidate"], 8
        )
        self.assertFalse(any("stratum" in row for row in self.packet))
        self.assertFalse(
            any("prediction" in key for row in self.packet for key in row)
        )

    def test_historical_rows_match_fixed_quotas_and_statuses(self) -> None:
        historical = [
            row
            for row in self.ledger
            if row["stratum"] == "historical_revision_candidate"
        ]
        self.assertEqual(len(historical), sum(HISTORICAL_QUOTAS.values()))
        self.assertEqual(
            {row["evidence_status"] for row in historical},
            {"superseded", "expired", "unknown"},
        )
        self.assertFalse(any(row["annotated_acceptable_chunk"] for row in historical))


class EntailmentNaturalReviewValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packet = read_jsonl(FROZEN_PACKET)

    def test_complete_human_labels_pass_all_validation_gates(self) -> None:
        audit = audit_completed_reviews(
            self.packet, _complete_reviews(self.packet)
        )
        self.assertTrue(audit["primary_review_complete"])
        self.assertTrue(audit["ready_for_scoring"])
        self.assertEqual(audit["adjudication_pending_count"], 0)
        self.assertEqual(set(audit["label_counts"]), {"support", "contradiction", "insufficient"})

    def test_immutable_change_placeholder_reviewer_and_bad_excerpt_fail(self) -> None:
        completed = _complete_reviews(self.packet)
        completed[0]["claim_text"] += " changed"
        completed[1]["reviewer_id"] = "codex"
        completed[2]["review_label"] = "support"
        completed[2]["decisive_excerpt"] = "not present in evidence"
        completed[3]["needs_adjudication"] = True
        audit = audit_completed_reviews(self.packet, completed)
        self.assertFalse(audit["primary_review_complete"])
        self.assertFalse(audit["ready_for_scoring"])
        self.assertGreaterEqual(len(audit["errors"]), 3)
        self.assertEqual(audit["adjudication_pending_count"], 1)


class FrozenEntailmentNaturalReviewArtifactTest(unittest.TestCase):
    def test_frozen_hashes_and_pending_decisions(self) -> None:
        for path in (
            FROZEN_PACKET,
            FROZEN_LEDGER,
            FROZEN_MANIFEST,
            FROZEN_REPORT,
            FROZEN_REPORT_MD,
        ):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["decision"]["packet_integrity"], "GO")
        self.assertEqual(report["decision"]["human_review"], "PENDING")
        self.assertEqual(report["decision"]["natural_verifier_evaluation"], "NO-GO")
        self.assertEqual(report["decision"]["generator_entry"], "NO-GO")

    def test_actual_inputs_refreeze_packet_and_ledger_identically(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_RERANKER_SCORES,
            DEFAULT_RERANKER_MANIFEST,
            DEFAULT_CHUNKS,
            DEFAULT_DOCUMENTS,
            DEFAULT_BM25_INDEX,
            DEFAULT_BM25_MANIFEST,
            DEFAULT_BUILDER_SOURCE,
        )
        self.assertEqual(result["packet_sha256"], file_sha256(FROZEN_PACKET))
        self.assertEqual(result["ledger_sha256"], file_sha256(FROZEN_LEDGER))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(
            result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD)
        )


if __name__ == "__main__":
    unittest.main()
