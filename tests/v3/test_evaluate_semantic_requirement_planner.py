from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.v3.collect_details import _serialize_jsonl, write_immutable
from src.v3.evaluate_semantic_requirement_planner import (
    GoldBatchOutput,
    MATCHER_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    author_gold,
    build_population,
    gold_prompt,
    maximum_match_edges,
    needs_human_review,
    planner_prompt,
    score_cases,
    _normalize_pair_matrix,
)


def _input_row(index: int) -> dict:
    return {
        "dev_id": f"case-{index:03d}",
        "question": f"질문 {index}의 가격은?",
        "answerability": "true",
        "source_ids": ["dnf_faq"],
        "time_scope": "current",
        "query_kind": "single",
        "evidence_groups": [
            {"group_id": "g1", "evidence_span": "가격은 100 세라"}
        ],
    }


def _requirement(answerable: bool = True) -> dict:
    return {
        "requirement_id": "requirement_1",
        "subject": "상품",
        "relation": "가격",
        "value_type": "금액",
        "subject_group": "상품",
        "answerable_from_docs": answerable,
        "qualifiers": [],
        "time_scope": None,
        "coordination_scope": None,
    }


class SemanticRequirementPlannerTest(unittest.TestCase):
    def test_population_deduplicates_non_additive_ceiling_slice(self) -> None:
        canary = [_input_row(index) for index in range(32)]
        dev = [_input_row(index) for index in range(32, 95)]
        ceiling = [
            {"case_id": f"case-{index:03d}", "question": canary[index]["question"]}
            for index in range(15)
        ]
        population = build_population(canary, dev, ceiling)
        self.assertEqual(len(population), 95)
        self.assertEqual(sum(row["claim_ceiling_stress_slice"] for row in population), 15)

    def test_planner_prompt_contains_no_gold_or_evidence(self) -> None:
        row = {
            "case_id": "case-1",
            "question": "가격과 삭제일은?",
            "evidence_group_hints": [{"group_id": "secret-gold", "evidence_span": "secret-span"}],
        }
        prompt = planner_prompt([row])
        self.assertIn("가격과 삭제일은?", prompt)
        self.assertNotIn("secret-gold", prompt)
        self.assertNotIn("secret-span", prompt)
        self.assertIn("read only each question", PLANNER_SYSTEM_PROMPT.lower())

    def test_gold_prompt_never_contains_planner_output(self) -> None:
        row = {
            "case_id": "case-1",
            "question": "가격은?",
            "evidence_group_hints": [{"group_id": "g1", "evidence_span": "100 세라"}],
            "planner_requirements": ["must-not-leak"],
        }
        prompt = gold_prompt([row])
        self.assertIn("g1", prompt)
        self.assertNotIn("must-not-leak", prompt)

    def test_gold_author_rejects_invented_evidence_group(self) -> None:
        population = [
            {
                "case_id": "case-1",
                "dataset": "fixture",
                "question": "가격은?",
                "source_ids": ["dnf_shop"],
                "time_scope": "current",
                "query_kind": "single",
                "claim_ceiling_stress_slice": False,
                "evidence_group_hints": [{"group_id": "g1", "evidence_span": "100 세라"}],
            }
        ]

        def fake_caller(**_: object):
            return GoldBatchOutput.model_validate(
                {
                    "cases": [
                        {
                            "case_id": "case_1",
                            "requirements": [
                                {
                                    "subject": "상품",
                                    "relation": "가격",
                                    "value_type": "금액",
                                    "subject_group": "상품",
                                    "answerable_from_docs": True,
                                    "acceptable_evidence_group_ids": ["invented"],
                                    "qualifiers": [],
                                    "time_scope": None,
                                    "coordination_scope": None,
                                }
                            ],
                        }
                    ]
                }
            ), {"latency_ms": 1.0}

        with self.assertRaisesRegex(RuntimeError, "invented evidence group"):
            author_gold(population, model="gold", batch_size=1, timeout=1, caller=fake_caller)

    def test_bipartite_matching_never_double_counts_one_prediction(self) -> None:
        pairs = [
            {"prediction_index": 1, "gold_index": 1, "verdict": "MATCH"},
            {"prediction_index": 1, "gold_index": 2, "verdict": "MATCH"},
        ]
        self.assertEqual(len(maximum_match_edges(pairs)), 1)

    def test_out_of_range_matcher_pair_is_conservatively_defaulted(self) -> None:
        normalized = _normalize_pair_matrix(
            "case-1",
            [
                {
                    "prediction_index": 9,
                    "gold_index": 1,
                    "verdict": "MATCH",
                    "rationale": "invalid",
                }
            ],
            prediction_count=1,
            gold_count=1,
        )
        self.assertEqual(normalized[0]["verdict"], "NO_MATCH")
        self.assertEqual(normalized[0]["judgment_origin"], "conservative_default")

    def test_metrics_use_atomic_one_to_one_matches(self) -> None:
        gold = [
            {
                "case_id": "case-1",
                "dataset": "fixture",
                "source_ids": ["dnf_shop"],
                "time_scope": "current",
                "query_kind": "multi",
                "claim_ceiling_stress_slice": False,
                "requirements": [
                    {**_requirement(), "requirement_id": "requirement_1"},
                    {**_requirement(), "requirement_id": "requirement_2", "relation": "삭제일"},
                ],
            }
        ]
        planner = [{"case_id": "case-1", "requirements": [_requirement()]}]
        matches = [
            {
                "case_id": "case-1",
                "pair_judgments": [
                    {"prediction_index": 1, "gold_index": 1, "verdict": "MATCH", "rationale": "same"},
                    {"prediction_index": 1, "gold_index": 2, "verdict": "MATCH", "rationale": "bundled"},
                ],
            }
        ]
        _, metrics = score_cases(gold, planner, matches)
        primary = metrics["primary_unique_95"]
        self.assertEqual(primary["micro_recall"]["successes"], 1)
        self.assertEqual(primary["micro_recall"]["total"], 2)
        self.assertEqual(primary["all_requirements_recalled_questions"]["successes"], 0)

    def test_human_review_selects_all_multi_and_is_deterministic(self) -> None:
        case = {
            "case_id": "case-1",
            "gold_count": 2,
            "prediction_count": 2,
            "matched_count": 2,
            "source_ids": ["dnf_shop"],
            "query_kind": "multi",
            "time_scope": "current",
            "docs_false_positive": 0,
            "ambiguous_pair_count": 0,
            "partial_pair_count": 0,
        }
        selected, reasons = needs_human_review(case)
        self.assertTrue(selected)
        self.assertIn("multi_requirement_100pct", reasons)

    def test_content_addressed_serialization_is_reproducible_and_immutable(self) -> None:
        rows = [{"case_id": "b", "value": 2}, {"case_id": "a", "value": 1}]
        first = _serialize_jsonl(rows, lambda row: row["case_id"])
        second = _serialize_jsonl(list(reversed(rows)), lambda row: row["case_id"])
        self.assertEqual(first, second)
        digest = hashlib.sha256(first).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"artifact_{digest}.jsonl"
            write_immutable(path, first)
            write_immutable(path, second)
            with self.assertRaises(RuntimeError):
                write_immutable(path, json.dumps({"different": True}).encode())

    def test_models_and_prompts_are_independent_contracts(self) -> None:
        self.assertNotEqual(PLANNER_SYSTEM_PROMPT, MATCHER_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
