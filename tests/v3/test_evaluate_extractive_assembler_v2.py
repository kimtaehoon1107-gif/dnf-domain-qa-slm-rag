from __future__ import annotations

import unittest

from src.v3.evaluate_extractive_assembler_v2 import (
    SegmentChoice,
    aggregate_v2,
    assemble_segment_selections,
    classify_non_substring,
    gate_v2,
    run_segment_selector,
    score_cases_v2,
    segment_chunk,
    selector_prompt,
)


def _case(text: str = "Price is 10. Deletion is January 1.") -> dict:
    return {
        "case_id": "case-1",
        "dataset": "adaptive_dev_63",
        "question": "What are the price and deletion date?",
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
        "selected_chunks": {"c1": text, "c2": "Irrelevant text."},
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


class ExtractiveAssemblerV2Test(unittest.TestCase):
    def test_segments_are_exact_stable_slices_and_include_table_rows(self) -> None:
        text = "First sentence. Second sentence.\n\n| Item | Value |\n| A | 10 |"
        first = segment_chunk("c1", text)
        second = segment_chunk("c1", text)
        self.assertEqual(first, second)
        self.assertTrue(any("table_row" in row["kinds"] for row in first))
        for row in first:
            self.assertEqual(text[row["start_char"] : row["end_char"]], row["text"])

    def test_prompt_exposes_segments_but_not_gold(self) -> None:
        case = _case()
        segments = segment_chunk("c1", case["selected_chunks"]["c1"])
        prompt = selector_prompt(case, case["requirements"][0], 1, segments)
        self.assertIn("span_", prompt)
        self.assertNotIn("acceptable_chunk_ids", prompt)
        self.assertNotIn("evidence_span", prompt)

    def test_multiple_selected_ids_are_sliced_without_generation(self) -> None:
        case = _case(
            "\uac00\uaca9\uc740 10\uc785\ub2c8\ub2e4. "
            "\uc0ad\uc81c\uc77c\uc740 1\uc6d4 1\uc77c\uc785\ub2c8\ub2e4."
        )
        segments = segment_chunk("c1", case["selected_chunks"]["c1"])
        segment_row = {"case_id": "case-1", "segments": segments}
        chosen = [row["span_id"] for row in segments[:2]]

        def fake_caller(**_: object):
            return SegmentChoice(
                status="supported", selected_span_ids=chosen
            ), {"latency_ms": 1.0}

        selections, _ = run_segment_selector(
            [case], [segment_row], model="fixture", timeout=1, caller=fake_caller
        )
        assembled = assemble_segment_selections([case], [segment_row], selections)
        decision = assembled[0]["decisions"][0]
        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(len(decision["spans"]), 2)
        for span in decision["spans"]:
            self.assertIn(span["text"], case["selected_chunks"][span["chunk_id"]])

    def test_duplicate_segment_id_is_malformed(self) -> None:
        case = _case()
        segments = segment_chunk("c1", case["selected_chunks"]["c1"])
        segment_row = {"case_id": "case-1", "segments": segments}
        duplicate = segments[0]["span_id"]

        def fake_caller(**_: object):
            return SegmentChoice(
                status="supported", selected_span_ids=[duplicate, duplicate]
            ), {"latency_ms": 1.0}

        selections, _ = run_segment_selector(
            [case], [segment_row], model="fixture", timeout=1, caller=fake_caller
        )
        assembled = assemble_segment_selections([case], [segment_row], selections)
        self.assertEqual(
            assembled[0]["decisions"][0]["status"], "invalid_model_output"
        )

    def test_model_call_failure_is_preserved_as_malformed(self) -> None:
        case = _case()
        segments = segment_chunk("c1", case["selected_chunks"]["c1"])
        segment_row = {"case_id": "case-1", "segments": segments}

        def failing_caller(**_: object):
            raise RuntimeError("fixture failure")

        selections, _ = run_segment_selector(
            [case], [segment_row], model="fixture", timeout=1, caller=failing_caller
        )
        assembled = assemble_segment_selections([case], [segment_row], selections)
        self.assertEqual(
            assembled[0]["decisions"][0]["status"], "invalid_model_output"
        )

    def test_v1_failure_classification_is_structural(self) -> None:
        case = _case("Alpha   beta. OMIT THIS. Second piece.")
        self.assertEqual(
            classify_non_substring(
                case,
                {"cited_chunk_id": "c1", "proposed_span": "Alpha beta."},
            ),
            "whitespace_only",
        )
        self.assertEqual(
            classify_non_substring(
                case,
                {"cited_chunk_id": "c1", "proposed_span": "Irrelevant text."},
            ),
            "wrong_chunk",
        )
        self.assertEqual(
            classify_non_substring(
                case,
                {
                    "cited_chunk_id": "c1",
                    "proposed_span": "Alpha   beta. Second piece.",
                },
            ),
            "multi_segment",
        )
        self.assertEqual(
            classify_non_substring(
                case,
                {"cited_chunk_id": "c1", "proposed_span": "Completely new answer."},
            ),
            "paraphrase",
        )

    def test_mechanical_scoring_and_gate(self) -> None:
        case = _case()
        segments = segment_chunk("c1", case["selected_chunks"]["c1"])
        assembled = [
            {
                "case_id": "case-1",
                "dataset": "adaptive_dev_63",
                "decisions": [
                    {
                        "requirement_id": "requirement_1",
                        "status": "supported_exact",
                        "spans": [
                            {
                                "span_id": segments[0]["span_id"],
                                "chunk_id": "c1",
                                "start_char": segments[0]["start_char"],
                                "end_char": segments[0]["end_char"],
                                "text": segments[0]["text"],
                            }
                        ],
                        "model_output_errors": [],
                        "unsupported_message": None,
                    }
                ],
            }
        ]
        metrics = aggregate_v2(score_cases_v2([case], assembled))
        self.assertEqual(
            metrics["all_human_gold_evidence_group_citation"][
                "assembler_successes"
            ],
            1,
        )
        self.assertEqual(metrics["span_validity"]["rate"], 1.0)

        gate_metrics = {
            "combined": {
                "comparison": {
                    "evidence_group_regression_count": 0,
                    "all_groups_question_regression_count": 0,
                },
                "all_groups_cited_questions": {
                    "assembler_successes": 2,
                    "baseline_successes": 1,
                },
                "span_validity": {"invalid": 0},
                "malformed_requirement_count": 0,
            },
            "adaptive_dev_63": {
                "all_human_gold_evidence_group_citation": {
                    "assembler_successes": 48
                }
            },
        }
        self.assertTrue(gate_v2(gate_metrics)["pass"])


if __name__ == "__main__":
    unittest.main()
