from __future__ import annotations

import unittest

from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    K_VALUES,
    assemble_chunk_diverse_configuration,
    evaluate_chunk_diverse_grid,
)
from src.v3.evaluate_extractive_assembler_v3 import THRESHOLDS


def _case() -> dict:
    return {
        "case_id": "case-1",
        "dataset": "adaptive_dev_63",
        "question": "가격은 얼마인가요?",
        "source_ids": ["dnf_shop"],
        "gold_answerability": "true",
        "requirements": [
            {
                "requirement_id": "requirement_1",
                "subject": "상품",
                "relation": "가격",
                "value_type": "amount",
                "subject_group": "상품",
            }
        ],
        "evidence_groups": [
            {
                "group_id": "evidence_1",
                "acceptable_chunk_ids": ["chunk_2"],
                "evidence_span": "가격은 10원입니다.",
            }
        ],
        "selected_chunk_ids": ["chunk_1", "chunk_2"],
        "selected_chunks": {
            "chunk_1": "첫 문장. 둘째 문장.",
            "chunk_2": "가격은 10원입니다.",
        },
        "requirement_attribution": [],
        "baseline_cited_group_ids": ["evidence_1"],
        "retrieval_bound_group_ids": [],
    }


def _scores() -> list[dict]:
    return [
        {
            "case_id": "case-1",
            "dataset": "adaptive_dev_63",
            "requirements": [
                {
                    "requirement_index": 1,
                    "requirement_id": "requirement_1",
                    "query": "상품 가격",
                    "candidates": [
                        {
                            "span_id": "s1",
                            "chunk_id": "chunk_1",
                            "start_char": 0,
                            "end_char": 5,
                            "text": "첫 문장.",
                            "kind": "sentence",
                            "reranker_score": 0.9,
                        },
                        {
                            "span_id": "s2",
                            "chunk_id": "chunk_1",
                            "start_char": 6,
                            "end_char": 12,
                            "text": "둘째 문장.",
                            "kind": "sentence",
                            "reranker_score": 0.8,
                        },
                        {
                            "span_id": "s3",
                            "chunk_id": "chunk_2",
                            "start_char": 0,
                            "end_char": 12,
                            "text": "가격은 10원입니다.",
                            "kind": "sentence",
                            "reranker_score": 0.7,
                        },
                    ],
                }
            ],
            "not_evaluated_no_gold_evidence_groups": False,
        }
    ]


class ChunkDiverseAssemblerTest(unittest.TestCase):
    def test_selects_at_most_one_segment_per_chunk(self) -> None:
        assembled = assemble_chunk_diverse_configuration(
            [_case()], _scores(), threshold=0.001, k=2
        )
        spans = assembled[0]["decisions"][0]["spans"]
        self.assertEqual([row["span_id"] for row in spans], ["s1", "s3"])
        self.assertEqual(len({row["chunk_id"] for row in spans}), len(spans))

    def test_output_is_exact_source_slice(self) -> None:
        case = _case()
        assembled = assemble_chunk_diverse_configuration(
            [case], _scores(), threshold=0.001, k=2
        )
        for span in assembled[0]["decisions"][0]["spans"]:
            source = case["selected_chunks"][span["chunk_id"]]
            self.assertEqual(source[span["start_char"] : span["end_char"]], span["text"])

    def test_grid_is_complete_and_deterministic(self) -> None:
        first = evaluate_chunk_diverse_grid([_case()], _scores())
        second = evaluate_chunk_diverse_grid([_case()], _scores())
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), len(THRESHOLDS) * len(K_VALUES))

    def test_value_first_prefers_the_span_carrying_the_required_shape(self) -> None:
        # s1 outranks s3 on reranker score but carries no price; the 가격 requirement
        # expects cost_value, so value-first must reach past the higher-scoring header.
        default = assemble_chunk_diverse_configuration(
            [_case()], _scores(), threshold=0.001, k=1
        )
        value_first = assemble_chunk_diverse_configuration(
            [_case()], _scores(), threshold=0.001, k=1, value_first=True
        )
        self.assertEqual(
            [row["span_id"] for row in default[0]["decisions"][0]["spans"]], ["s1"]
        )
        self.assertEqual(
            [row["span_id"] for row in value_first[0]["decisions"][0]["spans"]], ["s3"]
        )

    def test_value_first_off_leaves_selection_untouched(self) -> None:
        explicit_off = assemble_chunk_diverse_configuration(
            [_case()], _scores(), threshold=0.001, k=2, value_first=False
        )
        default = assemble_chunk_diverse_configuration(
            [_case()], _scores(), threshold=0.001, k=2
        )
        self.assertEqual(explicit_off, default)

    def test_value_first_never_selects_below_threshold_candidates(self) -> None:
        scores = _scores()
        scores[0]["requirements"][0]["candidates"][2]["reranker_score"] = 0.0
        assembled = assemble_chunk_diverse_configuration(
            [_case()], scores, threshold=0.001, k=1, value_first=True
        )
        # s3 carries the price but no longer clears the threshold, so it stays out.
        self.assertEqual(
            [row["span_id"] for row in assembled[0]["decisions"][0]["spans"]], ["s1"]
        )

    def test_gold_fields_do_not_influence_selection(self) -> None:
        original = _case()
        changed = _case()
        changed["evidence_groups"] = []
        changed["baseline_cited_group_ids"] = []
        first = assemble_chunk_diverse_configuration(
            [original], _scores(), threshold=0.001, k=2
        )
        second = assemble_chunk_diverse_configuration(
            [changed], _scores(), threshold=0.001, k=2
        )
        self.assertEqual(first[0]["decisions"], second[0]["decisions"])


if __name__ == "__main__":
    unittest.main()
