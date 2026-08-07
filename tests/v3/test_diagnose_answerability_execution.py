from __future__ import annotations

import unittest

from src.v3.diagnose_answerability_execution import (
    _best_rule,
    build_case_rows,
    evaluate_numeric_rule,
    extract_mechanical_features,
    score_parent_coverable,
    selected_parent_coverable,
    summarize_value_type_structure,
    sweep_numeric_rules,
)


class AnswerabilityExecutionDiagnosticTest(unittest.TestCase):
    def test_feature_extraction_is_numeric_and_text_free(self) -> None:
        features = extract_mechanical_features(
            {
                "case_id": "case-1",
                "requirements": [
                    {
                        "candidates": [
                            {"chunk_id": "a", "reranker_score": 0.8},
                            {"chunk_id": "b", "reranker_score": 0.3},
                        ]
                    },
                    {
                        "candidates": [
                            {"chunk_id": "a", "reranker_score": 0.6},
                            {"chunk_id": "c", "reranker_score": 0.1},
                        ]
                    },
                ],
            }
        )
        self.assertEqual(features["candidate_count"], 3)
        self.assertEqual(features["requirement_count"], 2)
        self.assertEqual(features["distinct_top_chunk_count"], 1)
        self.assertEqual(features["min_top_score"], 0.6)
        self.assertEqual(features["mean_margin"], 0.5)
        self.assertNotIn("question", features)

    def test_aggregate_rule_selection_prefers_zero_fp_reject_signal(self) -> None:
        rows = [
            {"answerability_target": "reject", "features": self._features(0)},
            {"answerability_target": "reject", "features": self._features(1)},
            {"answerability_target": "reject", "features": self._features(8)},
            {"answerability_target": "answerable_docs", "features": self._features(8)},
            {"answerability_target": "answerable_docs", "features": self._features(10)},
            {"answerability_target": "realtime_api", "features": self._features(8)},
        ]
        fixed = evaluate_numeric_rule(
            rows,
            target="reject",
            feature="candidate_count",
            operator="le",
            threshold=1,
        )
        self.assertEqual(fixed["target_recall"]["successes"], 2)
        self.assertEqual(fixed["answerable_false_positive"]["successes"], 0)
        best = _best_rule(
            sweep_numeric_rules(rows, "reject"), maximum_answerable_fp=0
        )
        self.assertGreaterEqual(best["target_recall"]["successes"], 2)
        self.assertEqual(best["answerable_false_positive"]["successes"], 0)

    def test_parent_coverage_requires_one_parent_for_every_requirement(self) -> None:
        parents = {"a": "p1", "b": "p1", "c": "p2", "d": "p3"}
        same_result = {
            "requirement_aware": {
                "requirement_selections": [
                    {"selected_chunk_ids": ["a", "c"]},
                    {"selected_chunk_ids": ["b", "d"]},
                ]
            }
        }
        cross_result = {
            "requirement_aware": {
                "requirement_selections": [
                    {"selected_chunk_ids": ["a"]},
                    {"selected_chunk_ids": ["c"]},
                ]
            }
        }
        self.assertTrue(selected_parent_coverable(same_result, parents))
        self.assertFalse(selected_parent_coverable(cross_result, parents))

        score_row = {
            "requirements": [
                {
                    "candidates": [
                        {"chunk_id": "a", "reranker_score": 0.9},
                        {"chunk_id": "c", "reranker_score": 0.01},
                    ]
                },
                {
                    "candidates": [
                        {"chunk_id": "b", "reranker_score": 0.004},
                        {"chunk_id": "d", "reranker_score": 0.8},
                    ]
                },
            ]
        }
        self.assertTrue(score_parent_coverable(score_row, parents, threshold=0.0))
        self.assertFalse(score_parent_coverable(score_row, parents, threshold=0.005))

    def test_case_rows_never_copy_question_or_gold_text(self) -> None:
        ground_truth = [
            {
                "case_id": "case-1",
                "dataset": "adaptive_dev_63",
                "question": "official fact",
                "answerability_label": "true",
                "answerability_profile": "docs_only",
            }
        ]
        scores = [
            {
                "case_id": "case-1",
                "requirements": [
                    {
                        "candidates": [
                            {"chunk_id": "a", "reranker_score": 0.9}
                        ]
                    }
                ],
            }
        ]
        results = [
            {
                "case_id": "case-1",
                "requirement_aware": {
                    "requirement_selections": [
                        {"selected_chunk_ids": ["a"]}
                    ]
                },
            }
        ]
        chunks = [{"chunk_id": "a", "parent_document_id": "p1"}]
        enumeration = [
            {
                "case_id": "case-1",
                "requirements": [{"value_type": "text"}],
            }
        ]
        rows = build_case_rows(
            ground_truth, enumeration, scores, results, [], chunks
        )
        self.assertNotIn("question", rows[0])
        self.assertNotIn("gold_answer", rows[0])
        self.assertFalse(rows[0]["question_text_included"])
        self.assertFalse(rows[0]["gold_text_included"])

    def test_value_type_structure_does_not_claim_safe_realtime_signal(self) -> None:
        rows = [
            {
                "answerability_target": "realtime_api",
                "value_type_signature": ["amount", "amount"],
            },
            {
                "answerability_target": "realtime_api",
                "value_type_signature": ["text"],
            },
            {
                "answerability_target": "answerable_docs",
                "value_type_signature": ["amount", "amount"],
            },
            {
                "answerability_target": "answerable_docs",
                "value_type_signature": ["text"],
            },
            {
                "answerability_target": "reject",
                "value_type_signature": ["boolean"],
            },
        ]
        summary = summarize_value_type_structure(rows)
        self.assertEqual(
            summary["best_zero_answerable_fp_signature"]["realtime_recall"][
                "successes"
            ],
            0,
        )
        self.assertEqual(
            summary["observed_realtime_signature_union_upper_bound"][
                "answerable_false_positive"
            ]["successes"],
            2,
        )
        self.assertFalse(summary["planner_schema_has_typed_answer_source"])

    @staticmethod
    def _features(candidate_count: int) -> dict:
        return {
            "candidate_count": candidate_count,
            "requirement_count": 1,
            "distinct_top_chunk_count": int(candidate_count > 0),
            "min_top_score": float(candidate_count),
            "max_top_score": float(candidate_count),
            "mean_top_score": float(candidate_count),
            "min_margin": float(candidate_count),
            "mean_margin": float(candidate_count),
        }


if __name__ == "__main__":
    unittest.main()
