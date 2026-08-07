from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_evidence_reranker import (
    ADAPTIVE_ARM,
    BASELINE_ARM,
    DEFAULT_BASELINE_MANIFEST,
    DEFAULT_BASELINE_RESULTS,
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_EVALUATOR_SOURCE,
    DEFAULT_LATENCY_REPORT,
    DEFAULT_RERANKER_MANIFEST,
    DEFAULT_RERANKER_SCORES,
    DEFAULT_SELECTOR_SOURCE,
    TOP_3_ARM,
    TOP_8_ARM,
    aggregate,
    audit,
    build_and_freeze,
    evaluate_rows,
)


FROZEN_RESULTS = Path(
    "data/v3/evidence/"
    "evidence_reranker_ab_results_49d4e5b75339582c0aad9f6b35bc9d9cb5aa63a671c55ec46de5c023bb04a56f.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/evidence/"
    "evidence_reranker_ab_manifest_d0f1a2e89fd98da965af1b8a48687a20b777b60ec24082f003ea73ca6039a1f2.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "evidence_reranker_ab_763ca7b93bec87e475a4406f24b7780ebaeadffb7a36b494c473452244d8c90f.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "evidence_reranker_ab_95124cc1e37b7bd6b8e61550e1bde700d3a848cb8f07bf8205aa04d3ec4c2f87.md"
)


class ActualEvidenceRerankerABTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.baseline = read_jsonl(DEFAULT_BASELINE_RESULTS)
        cls.scores = read_jsonl(DEFAULT_RERANKER_SCORES)
        cls.chunks = read_jsonl(DEFAULT_CHUNKS)
        cls.rows = evaluate_rows(cls.dev, cls.baseline, cls.scores, cls.chunks)
        cls.metrics = aggregate(cls.rows)
        cls.gates = audit(cls.rows, cls.metrics)

    def test_actual_ab_is_deterministic(self) -> None:
        second = evaluate_rows(
            self.dev,
            list(reversed(self.baseline)),
            list(reversed(self.scores)),
            list(reversed(self.chunks)),
        )

        self.assertEqual(self.rows, second)
        self.assertEqual(len(self.rows), 63)
        self.assertTrue(self.gates["integrity_pass"])
        self.assertTrue(self.gates["promotion_pass"])
        self.assertFalse(self.gates["production_pass"])

    def test_adaptive_arm_preserves_recall_and_improves_precision(self) -> None:
        arms = self.metrics["arms"]
        delta = self.metrics["adaptive_vs_baseline"]

        self.assertEqual(arms[BASELINE_ARM]["all_groups_hit_rate"], 0.981818)
        self.assertEqual(arms[TOP_3_ARM]["all_groups_hit_rate"], 0.945455)
        self.assertEqual(arms[TOP_8_ARM]["annotated_evidence_precision"], 0.131818)
        self.assertEqual(arms[ADAPTIVE_ARM]["all_groups_hit_rate"], 0.981818)
        self.assertEqual(arms[ADAPTIVE_ARM]["evidence_group_recall_micro"], 0.983051)
        self.assertEqual(arms[ADAPTIVE_ARM]["annotated_evidence_precision"], 0.29)
        self.assertEqual(arms[ADAPTIVE_ARM]["average_selected_count"], 3.636364)
        self.assertEqual(delta["annotated_precision_delta"], 0.160246)
        self.assertEqual(delta["average_selected_reduction"], 0.552573)


class FrozenEvidenceRerankerABArtifactTest(unittest.TestCase):
    def test_frozen_hashes_and_decisions_are_preserved(self) -> None:
        for path in (FROZEN_RESULTS, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["decision"]["ab_integrity"], "GO")
        self.assertEqual(report["decision"]["adaptive_reranker_development"], "GO")
        self.assertEqual(report["decision"]["production_evidence_selector"], "NO-GO")
        self.assertEqual(report["decision"]["generator_entry"], "NO-GO")
        self.assertEqual(report["decision"]["final_benchmark"], "NO-GO")

    def test_actual_inputs_refreeze_to_identical_artifacts(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_BASELINE_RESULTS,
            DEFAULT_BASELINE_MANIFEST,
            DEFAULT_RERANKER_SCORES,
            DEFAULT_RERANKER_MANIFEST,
            DEFAULT_LATENCY_REPORT,
            DEFAULT_CHUNKS,
            DEFAULT_SELECTOR_SOURCE,
            DEFAULT_EVALUATOR_SOURCE,
        )

        self.assertEqual(result["results_sha256"], file_sha256(FROZEN_RESULTS))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD))


if __name__ == "__main__":
    unittest.main()
