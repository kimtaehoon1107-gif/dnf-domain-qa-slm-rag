from __future__ import annotations

import unittest

from src.v3.evaluate_extractive_assembler import (
    SpanProposalOutput,
    aggregate,
    cut_exact_spans,
    gate,
    model_prompt,
    run_span_model,
    score_cases,
)


def _case() -> dict:
    return {
        "case_id": "case-1",
        "dataset": "adaptive_dev_63",
        "question": "상품 가격은?",
        "source_ids": ["dnf_monthly_item"],
        "gold_answerability": "true",
        "requirements": [
            {
                "requirement_id": "r1",
                "subject": "상품",
                "relation": "가격",
                "value_type": "amount",
                "subject_group": "상품",
            }
        ],
        "evidence_groups": [
            {
                "group_id": "g1",
                "acceptable_chunk_ids": ["c1"],
                "evidence_span": "가격 1,000 세라",
            }
        ],
        "selected_chunk_ids": ["c1", "c2"],
        "selected_chunks": {"c1": "상품\n가격 1,000 세라", "c2": "다른 문서"},
        "requirement_attribution": [
            {
                "requirement_index": 1,
                "requirement_id": "r1",
                "ordered_chunk_ids": ["c1", "c2"],
            }
        ],
        "baseline_cited_group_ids": [],
        "retrieval_bound_group_ids": [],
    }


class ExtractiveAssemblerTest(unittest.TestCase):
    def test_model_prompt_does_not_contain_gold(self) -> None:
        prompt = model_prompt(_case())
        self.assertNotIn("acceptable_chunk_ids", prompt)
        self.assertNotIn("evidence_span", prompt)
        self.assertNotIn("baseline_cited", prompt)

    def test_span_model_requires_one_decision_per_requirement(self) -> None:
        def fake_caller(**_: object):
            return SpanProposalOutput.model_validate(
                {
                    "decisions": [
                        {
                            "requirement_index": 1,
                            "status": "supported",
                            "cited_chunk_id": "c1",
                            "proposed_span": "가격 1,000 세라",
                        }
                    ]
                }
            ), {"latency_ms": 1.0}

        rows, _ = run_span_model(
            [_case()], model="fixture", timeout=1, caller=fake_caller
        )
        self.assertEqual(rows[0]["decisions"][0]["requirement_index"], 1)

    def test_missing_model_decision_is_preserved_as_invalid_outcome(self) -> None:
        def fake_caller(**_: object):
            return SpanProposalOutput.model_validate({"decisions": []}), {
                "latency_ms": 1.0
            }

        rows, _ = run_span_model(
            [_case()], model="fixture", timeout=1, caller=fake_caller
        )
        assembled = cut_exact_spans([_case()], rows)
        self.assertEqual(
            assembled[0]["decisions"][0]["status"], "invalid_model_output"
        )

    def test_exact_cutter_accepts_only_literal_substring(self) -> None:
        valid = [
            {
                "case_id": "case-1",
                "decisions": [
                    {
                        "requirement_index": 1,
                        "status": "supported",
                        "cited_chunk_id": "c1",
                        "proposed_span": "가격 1,000 세라",
                    }
                ],
            }
        ]
        result = cut_exact_spans([_case()], valid)[0]["decisions"][0]
        self.assertEqual(result["status"], "supported_exact")
        self.assertEqual(result["extracted_span"], "가격 1,000 세라")

        invalid = [
            {
                "case_id": "case-1",
                "decisions": [
                    {
                        "requirement_index": 1,
                        "status": "supported",
                        "cited_chunk_id": "c1",
                        "proposed_span": "가격은 천 세라입니다",
                    }
                ],
            }
        ]
        result = cut_exact_spans([_case()], invalid)[0]["decisions"][0]
        self.assertEqual(result["status"], "invalid_non_substring")
        self.assertIsNone(result["extracted_span"])

    def test_scoring_is_chunk_membership_and_exact_status(self) -> None:
        proposals = [
            {
                "case_id": "case-1",
                "decisions": [
                    {
                        "requirement_index": 1,
                        "status": "supported",
                        "cited_chunk_id": "c1",
                        "proposed_span": "가격 1,000 세라",
                    }
                ],
            }
        ]
        assembled = cut_exact_spans([_case()], proposals)
        scored = score_cases([_case()], assembled)
        metrics = aggregate(scored)
        self.assertEqual(
            metrics["assembler_evidence_group_citation"]["successes"], 1
        )
        self.assertEqual(metrics["span_validity"]["rate"], 1.0)

    def test_gate_requires_improvement_and_zero_regression(self) -> None:
        fixture = {
            "combined": {
                "assembler_all_groups_cited_questions": {"successes": 2},
                "baseline_all_groups_cited_questions": {"successes": 1},
                "comparison": {
                    "evidence_group_regression_count": 0,
                    "all_groups_question_regression_count": 0,
                },
                "span_validity": {"invalid": 0},
                "model_output_error_question_count": 0,
            },
            "adaptive_dev_63": {
                "assembler_evidence_group_citation": {"successes": 48}
            },
        }
        self.assertTrue(gate(fixture)["pass"])
        fixture["combined"]["comparison"]["evidence_group_regression_count"] = 1
        self.assertFalse(gate(fixture)["pass"])


if __name__ == "__main__":
    unittest.main()
