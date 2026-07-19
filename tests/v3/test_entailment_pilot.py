from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.build_entailment_pilot import (
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_DEV_SET,
    LABELS,
    SOURCE_IDS,
    build_and_freeze as build_cases_and_freeze,
    build_cases,
)
from src.v3.evaluate_entailment_pilot import (
    DEFAULT_CASE_MANIFEST,
    DEFAULT_CASES,
    DEFAULT_EVALUATOR_SOURCE,
    DEFAULT_LATENCY,
    DEFAULT_SCORE_MANIFEST,
    DEFAULT_SCORES,
    aggregate,
    audit,
    build_and_freeze as evaluate_and_freeze,
)
from src.v3.score_entailment_pilot import (
    attach_predictions,
    predictions_from_probabilities,
    prepare_pairs,
)


FROZEN_REPORT = Path(
    "reports/v3/"
    "entailment_verifier_pilot_98a2639e135c222364b82ad53bc17c1aa3af5090730d877aaa26e9475df8174c.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "entailment_verifier_pilot_6cf13a4b73abd2adff8695df84563bef746f26f45cc00c97dc8110b800c99e75.md"
)


class EntailmentControlBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.cases = build_cases(cls.dev)

    def test_selection_and_case_ids_are_deterministic(self) -> None:
        self.assertEqual(self.cases, build_cases(list(reversed(self.dev))))
        self.assertEqual(len(self.cases), 24)
        self.assertEqual(
            [row["case_ordinal"] for row in self.cases], list(range(24))
        )
        self.assertEqual(len({row["case_id"] for row in self.cases}), 24)
        self.assertEqual({row["source_id"] for row in self.cases}, set(SOURCE_IDS))
        for label in LABELS:
            self.assertEqual(sum(row["label"] == label for row in self.cases), 8)

    def test_counterfactuals_and_rotations_are_explicit(self) -> None:
        by_source_label = {
            (row["source_id"], row["label"]): row for row in self.cases
        }
        for source_id in SOURCE_IDS:
            support = by_source_label[(source_id, "support")]
            contradiction = by_source_label[(source_id, "contradiction")]
            insufficient = by_source_label[(source_id, "insufficient")]
            mutation = contradiction["mutation"]
            self.assertIn(mutation["from"], support["claim_text"])
            self.assertNotIn(mutation["from"], contradiction["claim_text"])
            self.assertIn(mutation["to"], contradiction["claim_text"])
            self.assertNotEqual(insufficient["rotated_claim_source_id"], source_id)
            self.assertFalse(support["training_allowed"])
            self.assertFalse(support["final_benchmark_eligible"])

    def test_actual_cases_refreeze_identically(self) -> None:
        result = build_cases_and_freeze(
            Path.cwd(), DEFAULT_DEV_SET, DEFAULT_BUILDER_SOURCE
        )
        self.assertEqual(result["cases_sha256"], file_sha256(DEFAULT_CASES))
        self.assertEqual(
            result["manifest_sha256"], file_sha256(DEFAULT_CASE_MANIFEST)
        )


class EntailmentScorerContractTest(unittest.TestCase):
    def test_nli_labels_map_to_verifier_labels(self) -> None:
        predictions = predictions_from_probabilities(
            [[0.9, 0.09, 0.01], [0.01, 0.04, 0.95], [0.02, 0.96, 0.02]],
            {0: "ENTAILMENT", 1: "NEUTRAL", 2: "CONTRADICTION"},
        )
        self.assertEqual(
            [row["predicted_label"] for row in predictions],
            ["support", "contradiction", "insufficient"],
        )

    def test_pair_preparation_and_prediction_attachment_are_aligned(self) -> None:
        cases = read_jsonl(DEFAULT_CASES)
        pairs = prepare_pairs(cases)
        fake = [
            {
                "predicted_label": row["label"],
                "predicted_nli_label": "entailment",
                "probabilities": {
                    "support": 1.0,
                    "contradiction": 0.0,
                    "insufficient": 0.0,
                },
            }
            for row in cases
        ]
        rows = attach_predictions(cases, {"fake": fake})
        self.assertEqual(len(pairs), len(rows))
        self.assertEqual(rows[0]["case_id"], cases[0]["case_id"])
        self.assertFalse(any(row["training_allowed"] for row in rows))


class FrozenEntailmentPilotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_jsonl(DEFAULT_CASES)
        cls.rows = read_jsonl(DEFAULT_SCORES)
        cls.metrics = aggregate(cls.rows)
        cls.gates = audit(cls.cases, cls.rows, cls.metrics)

    def test_actual_metrics_and_decisions(self) -> None:
        klue = self.metrics["models"]["klue_roberta_base_nli"]
        multilingual = self.metrics["models"]["mdeberta_v3_mnli_xnli"]
        self.assertEqual(klue["accuracy"], 1.0)
        self.assertEqual(multilingual["accuracy"], 0.875)
        self.assertEqual(multilingual["per_label"]["insufficient"]["recall"], 0.75)
        self.assertTrue(self.gates["integrity_pass"])
        self.assertTrue(self.gates["controlled_candidate_pass"])
        self.assertEqual(
            self.gates["selected_controlled_candidate"], "klue_roberta_base_nli"
        )
        self.assertFalse(self.gates["production_pass"])

    def test_frozen_hashes_and_report_restrictions(self) -> None:
        for path in (
            DEFAULT_CASES,
            DEFAULT_CASE_MANIFEST,
            DEFAULT_SCORES,
            DEFAULT_SCORE_MANIFEST,
            DEFAULT_LATENCY,
            FROZEN_REPORT,
            FROZEN_REPORT_MD,
        ):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["decision"]["controlled_verifier_development"], "GO")
        self.assertEqual(report["decision"]["production_verifier"], "NO-GO")
        self.assertEqual(report["decision"]["generator_entry"], "NO-GO")
        self.assertEqual(report["decision"]["final_benchmark"], "NO-GO")

    def test_actual_evaluation_refreezes_identically(self) -> None:
        result = evaluate_and_freeze(
            Path.cwd(),
            DEFAULT_CASES,
            DEFAULT_CASE_MANIFEST,
            DEFAULT_SCORES,
            DEFAULT_SCORE_MANIFEST,
            DEFAULT_LATENCY,
            DEFAULT_EVALUATOR_SOURCE,
        )
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(
            result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD)
        )


if __name__ == "__main__":
    unittest.main()
