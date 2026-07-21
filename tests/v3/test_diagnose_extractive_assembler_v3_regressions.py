from __future__ import annotations

import unittest

from src.v3.diagnose_extractive_assembler_v3_regressions import (
    K_VALUES,
    adjusted_gate,
    attribute_regressions,
    build_merged_segment_rows,
    evaluate_extended_grid,
)
from src.v3.evaluate_extractive_assembler_v3 import (
    THRESHOLDS,
    build_segment_rows,
)


def _case(case_id: str, text: str, evidence_span: str) -> dict:
    return {
        "case_id": case_id,
        "dataset": "adaptive_dev_63",
        "question": "두 항목을 확인해 주세요.",
        "source_ids": ["dnf_notice"],
        "gold_answerability": "true",
        "requirements": [
            {
                "requirement_id": "requirement_1",
                "subject": "항목",
                "relation": "내용",
                "value_type": "text",
                "subject_group": "항목",
            }
        ],
        "evidence_groups": [
            {
                "group_id": "evidence_1",
                "acceptable_chunk_ids": ["chunk_1"],
                "evidence_span": evidence_span,
            }
        ],
        "selected_chunk_ids": ["chunk_1"],
        "selected_chunks": {"chunk_1": text},
        "requirement_attribution": [
            {
                "requirement_index": 1,
                "requirement_id": "requirement_1",
                "ordered_chunk_ids": ["chunk_1"],
            }
        ],
        "baseline_cited_group_ids": ["evidence_1"],
        "retrieval_bound_group_ids": [],
    }


def _score_row(case: dict, scores: list[float]) -> dict:
    segments = build_segment_rows([case])[0]["segments"]
    if len(scores) != len(segments):
        raise AssertionError("score fixture must cover every segment")
    candidates = [
        {**segment, "reranker_score": score}
        for segment, score in zip(segments, scores)
    ]
    return {
        "case_id": case["case_id"],
        "dataset": case["dataset"],
        "requirements": [
            {
                "requirement_index": 1,
                "requirement_id": "requirement_1",
                "query": "항목 내용",
                "candidates": candidates,
            }
        ],
        "not_evaluated_no_gold_evidence_groups": False,
    }


def _diagnostic(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "groups": [
            {
                "group_id": "evidence_1",
                "selected_bound": True,
                "baseline_cited": True,
                "assembler_cited": False,
            }
        ],
    }


class ExtractiveAssemblerV3RegressionDiagnosticTest(unittest.TestCase):
    def test_uniform_merges_are_exact_two_and_three_segment_slices(self) -> None:
        text = "첫 문장입니다.\n둘째 문장입니다.\n셋째 문장입니다."
        case = _case("boundary", text, "첫 문장입니다. 둘째 문장입니다.")
        segments = build_merged_segment_rows([case])[0]["segments"]
        merged = [row for row in segments if row["kind"].startswith("adjacent_merge")]

        self.assertEqual(
            {row["kind"] for row in merged},
            {"adjacent_merge_2", "adjacent_merge_3"},
        )
        for row in merged:
            self.assertEqual(text[row["start_char"] : row["end_char"]], row["text"])

    def test_attribution_distinguishes_boundary_from_k_boundary(self) -> None:
        boundary = _case(
            "boundary",
            "첫 문장입니다.\n둘째 문장입니다.\n셋째 문장입니다.",
            "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.",
        )
        k_case = _case(
            "k-boundary",
            "하나.\n둘.\n셋.\n넷.\n정답은 다섯.",
            "정답은 다섯.",
        )
        segment_rows = build_segment_rows([boundary, k_case])
        score_rows = [
            _score_row(boundary, [0.9, 0.8, 0.7]),
            _score_row(k_case, [0.9, 0.8, 0.7, 0.6, 0.5]),
        ]

        rows = attribute_regressions(
            [boundary, k_case],
            segment_rows,
            score_rows,
            [_diagnostic("boundary"), _diagnostic("k-boundary")],
            threshold=0.001,
            k=3,
        )
        by_id = {row["case_id"]: row for row in rows}
        self.assertEqual(by_id["boundary"]["primary_stage"], "SEGMENTATION_BOUNDARY")
        self.assertEqual(
            by_id["boundary"]["minimum_adjacent_covering_window"]["width"], 3
        )
        self.assertEqual(by_id["k-boundary"]["primary_stage"], "K_BOUNDARY")
        self.assertEqual(
            by_id["k-boundary"]["requirement_rank_diagnostics"][0][
                "best_answer_bearing_segment_rank"
            ],
            5,
        )

    def test_extended_grid_is_complete_and_deterministic(self) -> None:
        case = _case("grid", "정답 문장입니다.", "정답 문장입니다.")
        scores = [_score_row(case, [0.9])]
        first = evaluate_extended_grid([case], scores)
        second = evaluate_extended_grid([case], scores)
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), len(THRESHOLDS) * len(K_VALUES))

    def test_adjusted_gate_enforces_regression_and_selection_limits(self) -> None:
        metrics = {
            "combined": {
                "comparison": {
                    "evidence_group_regression_count": 0,
                    "all_groups_question_regression_count": 0,
                },
                "all_groups_cited_questions": {"assembler_successes": 69},
                "mean_spans_per_supported_requirement": 3.0,
                "span_validity": {"rate": 1.0},
                "malformed_requirement_count": 0,
            },
            "adaptive_dev_63": {
                "all_human_gold_evidence_group_citation": {
                    "assembler_successes": 54
                }
            },
        }
        self.assertTrue(adjusted_gate(metrics)["pass"])
        metrics["combined"]["mean_spans_per_supported_requirement"] = 3.01
        self.assertFalse(adjusted_gate(metrics)["pass"])


if __name__ == "__main__":
    unittest.main()
