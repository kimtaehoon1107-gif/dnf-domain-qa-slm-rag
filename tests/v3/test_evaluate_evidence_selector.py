from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_evidence_selector import (
    DEFAULT_ANNOTATION_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_RETRIEVAL_RESULTS,
    DEFAULT_RUNTIME_MANIFEST,
    DEFAULT_SELECTOR_SOURCE,
    aggregate,
    audit,
    build_and_freeze,
    evaluate_rows,
)


FROZEN_RESULTS = Path(
    "data/v3/evidence/"
    "evidence_selector_pilot_results_c5f0f49ae0e519a8533d7672ba72208a73169c14263a3d77e70768ff6bef31e2.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/evidence/"
    "evidence_selector_pilot_manifest_268a6e48243f6a21a5f36706692186af1a3081799d5b6f72de98948fe3fda16b.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "evidence_selector_pilot_e902434a0de3eac720b5e3699d1fab5476f81b58b959234de355c5e47332c8e1.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "evidence_selector_pilot_286df5b8019f644ad5ae3b9daa6c410e1897c85df38b4d708b2187a4578e9946.md"
)


class ActualEvidenceSelectorPilotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.retrieval = read_jsonl(DEFAULT_RETRIEVAL_RESULTS)
        cls.chunks = read_jsonl(DEFAULT_CHUNKS)
        cls.rows = evaluate_rows(cls.dev, cls.retrieval, cls.chunks)
        cls.metrics = aggregate(cls.rows)
        cls.gates = audit(cls.rows, cls.metrics)

    def test_actual_evaluation_is_deterministic(self) -> None:
        second = evaluate_rows(
            self.dev,
            list(reversed(self.retrieval)),
            list(reversed(self.chunks)),
        )

        self.assertEqual(self.rows, second)
        self.assertEqual(len(self.rows), 63)
        self.assertTrue(all(row["answerability_exact"] for row in self.rows))
        self.assertTrue(
            all(
                not row["selected_evidence"]
                for row in self.rows
                if row["gold_answerability"] == "false"
            )
        )

    def test_selector_preserves_recall_but_fails_production_precision_gate(self) -> None:
        selector = self.metrics["selector"]

        self.assertEqual(selector["candidate_top_10_all_groups_hit_rate"], 0.981818)
        self.assertEqual(selector["selected_all_groups_hit_rate"], 0.981818)
        self.assertEqual(selector["candidate_top_10_group_recall_micro"], 0.983051)
        self.assertEqual(selector["selected_group_recall_micro"], 0.983051)
        self.assertEqual(selector["average_selected_count"], 8.127273)
        self.assertEqual(selector["candidate_reduction_from_top_10"], 0.187273)
        self.assertEqual(selector["annotated_evidence_precision"], 0.129754)
        self.assertTrue(self.gates["integrity_pass"])
        self.assertTrue(self.gates["compression_pass"])
        self.assertFalse(self.gates["production_pass"])


class FrozenEvidenceSelectorArtifactTest(unittest.TestCase):
    def test_frozen_hashes_and_decisions_are_preserved(self) -> None:
        for path in (FROZEN_RESULTS, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["decision"]["answerability_dev_baseline"], "GO")
        self.assertEqual(report["decision"]["selector_compression_candidate"], "GO")
        self.assertEqual(report["decision"]["production_evidence_selector"], "NO-GO")
        self.assertEqual(report["decision"]["generator_entry"], "NO-GO")
        self.assertEqual(report["decision"]["final_benchmark"], "NO-GO")

    def test_actual_inputs_refreeze_to_identical_artifacts(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_RETRIEVAL_RESULTS,
            DEFAULT_RUNTIME_MANIFEST,
            DEFAULT_ANNOTATION_MANIFEST,
            DEFAULT_CHUNKS,
            DEFAULT_SELECTOR_SOURCE,
        )

        self.assertEqual(result["results_sha256"], file_sha256(FROZEN_RESULTS))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD))


if __name__ == "__main__":
    unittest.main()
