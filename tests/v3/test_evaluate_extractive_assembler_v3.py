from __future__ import annotations

import unittest

from src.v3.evaluate_extractive_assembler_v2 import aggregate_v2, score_cases_v2
from src.v3.evaluate_extractive_assembler_v3 import (
    K_VALUES,
    THRESHOLDS,
    assemble_configuration,
    evaluate_grid,
    gate_v3,
    prepare_score_requests,
    segment_chunk_nonoverlap,
)


def _case() -> dict:
    return {
        "case_id": "case-1",
        "dataset": "adaptive_dev_63",
        "question": "What is the price?",
        "source_ids": ["dnf_shop"],
        "gold_answerability": "true",
        "requirements": [
            {
                "requirement_id": "requirement_1",
                "subject": "item",
                "relation": "price",
                "value_type": "amount",
                "subject_group": "item",
            }
        ],
        "evidence_groups": [
            {
                "group_id": "g1",
                "acceptable_chunk_ids": ["c1"],
                "evidence_span": "Price is 10.",
            }
        ],
        "selected_chunk_ids": ["c1", "c2"],
        "selected_chunks": {
            "c1": "Price is 10.\n| Item | Value |\n| A | 10 |",
            "c2": "Irrelevant sentence.",
        },
        "requirement_attribution": [
            {
                "requirement_index": 1,
                "requirement_id": "requirement_1",
                "ordered_chunk_ids": ["c1", "c2"],
            }
        ],
        "baseline_cited_group_ids": [],
        "retrieval_bound_group_ids": [],
    }


def _segments(case: dict) -> list[dict]:
    output = []
    for chunk_id in case["selected_chunk_ids"]:
        output.extend(
            segment_chunk_nonoverlap(chunk_id, case["selected_chunks"][chunk_id])
        )
    return output


def _scores(case: dict) -> list[dict]:
    segments = _segments(case)
    candidates = []
    for index, segment in enumerate(segments):
        candidates.append(
            {
                **segment,
                "reranker_score": 0.9 if segment["chunk_id"] == "c1" else 0.1,
            }
        )
    return [
        {
            "case_id": case["case_id"],
            "dataset": case["dataset"],
            "requirements": [
                {
                    "requirement_index": 1,
                    "requirement_id": "requirement_1",
                    "query": "item price",
                    "candidates": candidates,
                }
            ],
            "not_evaluated_no_gold_evidence_groups": False,
        }
    ]


class ExtractiveAssemblerV3Test(unittest.TestCase):
    def test_segments_are_nonoverlapping_exact_and_have_no_paragraph(self) -> None:
        case = _case()
        for chunk_id, text in case["selected_chunks"].items():
            segments = segment_chunk_nonoverlap(chunk_id, text)
            previous_end = -1
            for segment in segments:
                self.assertNotEqual(segment["kind"], "paragraph")
                self.assertGreaterEqual(segment["start_char"], previous_end)
                self.assertEqual(
                    text[segment["start_char"] : segment["end_char"]],
                    segment["text"],
                )
                previous_end = segment["end_char"]
        self.assertTrue(
            any(
                row["kind"] == "table_row"
                for row in segment_chunk_nonoverlap(
                    "c1", case["selected_chunks"]["c1"]
                )
            )
        )

    def test_score_requests_use_subject_relation_and_hide_gold(self) -> None:
        case = _case()
        segment_rows = [{"case_id": case["case_id"], "segments": _segments(case)}]
        requests = prepare_score_requests([case], segment_rows)
        self.assertEqual(requests[0]["query"], "item price")
        serialized = repr(requests)
        self.assertNotIn("acceptable_chunk_ids", serialized)
        self.assertNotIn("evidence_span", serialized)

    def test_threshold_and_k_select_exact_slices(self) -> None:
        case = _case()
        assembled = assemble_configuration(
            [case], _scores(case), threshold=0.5, k=2
        )
        decision = assembled[0]["decisions"][0]
        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(len(decision["spans"]), 2)
        for span in decision["spans"]:
            self.assertEqual(span["chunk_id"], "c1")
            self.assertEqual(
                case["selected_chunks"]["c1"][
                    span["start_char"] : span["end_char"]
                ],
                span["text"],
            )

    def test_no_segment_above_threshold_is_unsupported(self) -> None:
        case = _case()
        assembled = assemble_configuration(
            [case], _scores(case), threshold=0.95, k=3
        )
        self.assertEqual(assembled[0]["decisions"][0]["status"], "unsupported")

    def test_grid_is_complete_and_deterministic(self) -> None:
        case = _case()
        first = evaluate_grid([case], _scores(case))
        second = evaluate_grid([case], _scores(case))
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), len(THRESHOLDS) * len(K_VALUES))

    def test_mechanical_output_has_no_malformed_and_exact_validity(self) -> None:
        case = _case()
        assembled = assemble_configuration(
            [case], _scores(case), threshold=0.5, k=1
        )
        metrics = aggregate_v2(score_cases_v2([case], assembled))
        self.assertEqual(metrics["malformed_requirement_count"], 0)
        self.assertEqual(metrics["span_validity"]["rate"], 1.0)

    def test_gate_requires_all_prefrozen_checks(self) -> None:
        metrics = {
            "combined": {
                "comparison": {
                    "evidence_group_regression_count": 0,
                    "all_groups_question_regression_count": 0,
                },
                "all_groups_cited_questions": {
                    "assembler_successes": 2,
                    "baseline_successes": 1,
                },
                "mean_spans_per_supported_requirement": 2.0,
                "span_validity": {"rate": 1.0},
                "malformed_requirement_count": 0,
            },
            "adaptive_dev_63": {
                "all_human_gold_evidence_group_citation": {
                    "assembler_successes": 48
                }
            },
        }
        self.assertTrue(gate_v3(metrics)["pass"])
        metrics["combined"]["comparison"]["evidence_group_regression_count"] = 1
        self.assertFalse(gate_v3(metrics)["pass"])


if __name__ == "__main__":
    unittest.main()
