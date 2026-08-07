from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.audit_retrieval_annotation import (
    ALTERNATIVE_CHUNK_IDS,
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_RETRIEVAL_RESULTS,
    TARGET_DEV_ID,
    build_and_freeze,
    build_review_packet,
)
from src.v3.build_corpus import file_sha256


FROZEN_PACKET = Path(
    "data/v3/evaluation/"
    "retrieval_annotation_review_packet_6224137078afbea7067c10f40b31009adb74fd5fda30cdd5334fcbe74b1e3037.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/evaluation/"
    "retrieval_annotation_review_manifest_a73c22708fa24fd4311cde62675d59137358d185cdca1eb223d284d2e7e0d258.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "retrieval_annotation_audit_701be217544ab3686a3fae279d6c2885fe93483f391078829da1d8e98cdbd12c.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "retrieval_annotation_audit_4e1a4e10f7a668dc690ebc98466cd82236cc2708237e787c7644409d0f0a65e3.md"
)


class RetrievalAnnotationAuditTest(unittest.TestCase):
    def test_review_packet_is_deterministic_and_does_not_mutate_dev(self) -> None:
        args = (
            read_jsonl(DEFAULT_DEV_SET),
            read_jsonl(DEFAULT_RETRIEVAL_RESULTS),
            read_jsonl(DEFAULT_CHUNKS),
            read_jsonl(DEFAULT_DOCUMENTS),
        )
        packet = build_review_packet(*args)
        second = build_review_packet(
            list(reversed(args[0])),
            list(reversed(args[1])),
            list(reversed(args[2])),
            list(reversed(args[3])),
        )

        self.assertEqual(packet, second)
        self.assertEqual(packet[0]["dev_id"], TARGET_DEV_ID)
        self.assertEqual(
            [row["chunk_id"] for row in packet[0]["alternative_official_evidence"]],
            list(ALTERNATIVE_CHUNK_IDS),
        )
        self.assertEqual(packet[0]["human_review_status"], "pending")
        self.assertFalse(packet[0]["dev_set_mutated"])
        self.assertFalse(packet[0]["training_allowed"])
        self.assertFalse(packet[0]["final_benchmark_eligible"])

    def test_frozen_hashes_and_review_gate_are_preserved(self) -> None:
        for path in (FROZEN_PACKET, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(
            report["decision"]["annotation_ambiguity"],
            "CONFIRMED_BY_AGENT_AUDIT",
        )
        self.assertEqual(report["decision"]["human_review"], "PENDING")
        self.assertEqual(report["decision"]["dev_set_refreeze"], "NO-GO")
        self.assertEqual(report["decision"]["final_benchmark"], "NO-GO")
        self.assertTrue(report["audit"]["gate_pass"])

    def test_actual_inputs_refreeze_to_identical_artifacts(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_RETRIEVAL_RESULTS,
            DEFAULT_CHUNKS,
            DEFAULT_DOCUMENTS,
        )

        self.assertEqual(result["packet_sha256"], file_sha256(FROZEN_PACKET))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD))


if __name__ == "__main__":
    unittest.main()
