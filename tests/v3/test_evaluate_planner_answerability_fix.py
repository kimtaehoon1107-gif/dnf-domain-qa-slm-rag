from __future__ import annotations

import unittest

from src.v3.evaluate_planner_answerability_fix import (
    ANSWERABILITY_SYSTEM_PROMPT,
    AnswerabilityBatchOutput,
    OFFICIAL_FACT_FALSE_LABEL_IDS,
    PARTIAL_REQUIREMENT_TRUTH,
    build_answerability_ground_truth,
    compare_requirement_regression,
    run_answerability_classifier,
    score_answerability,
)
from src.v3.evaluate_semantic_requirement_planner import (
    PLANNER_SYSTEM_PROMPT,
    _fixed_prompt_hash,
)


def _requirement(name: str, answerable: bool) -> dict:
    return {
        "requirement_id": name,
        "subject": name,
        "relation": "관계",
        "value_type": "text",
        "subject_group": name,
        "answerable_from_docs": answerable,
        "qualifiers": [],
        "time_scope": None,
        "coordination_scope": None,
    }


class PlannerAnswerabilityFixTest(unittest.TestCase):
    def test_prompt_contains_false_true_examples_without_changing_enumeration_rule(self) -> None:
        self.assertIn("내 계정의 현재 제재 상태", ANSWERABILITY_SYSTEM_PROMPT)
        self.assertIn("공개된 이용제한 단계", ANSWERABILITY_SYSTEM_PROMPT)
        self.assertIn(
            "추가·삭제·병합", ANSWERABILITY_SYSTEM_PROMPT
        )
        self.assertEqual(
            _fixed_prompt_hash(PLANNER_SYSTEM_PROMPT),
            "01ddcf34498276b4896f5c628f53fa874047e8a989b3a5df3e405bd43c87d948",
        )

    def test_official_fact_can_be_docs_true_even_when_eval_label_is_false(self) -> None:
        case_id = next(iter(OFFICIAL_FACT_FALSE_LABEL_IDS))
        population = [
            {
                "case_id": case_id,
                "dataset": "fixture",
                "question": "공식 사실 질문",
                "source_ids": ["dnf_notice"],
                "answerability_label": "false",
            }
        ]
        original_partial = dict(PARTIAL_REQUIREMENT_TRUTH)
        original_official = set(OFFICIAL_FACT_FALSE_LABEL_IDS)
        try:
            PARTIAL_REQUIREMENT_TRUTH.clear()
            OFFICIAL_FACT_FALSE_LABEL_IDS.clear()
            OFFICIAL_FACT_FALSE_LABEL_IDS.add(case_id)
            rows = build_answerability_ground_truth(population)
        finally:
            PARTIAL_REQUIREMENT_TRUTH.clear()
            PARTIAL_REQUIREMENT_TRUTH.update(original_partial)
            OFFICIAL_FACT_FALSE_LABEL_IDS.clear()
            OFFICIAL_FACT_FALSE_LABEL_IDS.update(original_official)
        self.assertTrue(rows[0]["default_requirement_answerable_from_docs"])

    def test_boolean_classifier_preserves_frozen_requirement_fields(self) -> None:
        population = [{"case_id": "case-1", "question": "내 상태는?"}]
        baseline = [
            {
                "case_id": "case-1",
                "requirements": [_requirement("private", True)],
            }
        ]

        def fake_caller(**_: object):
            return AnswerabilityBatchOutput.model_validate(
                {
                    "cases": [
                        {
                            "case_id": "case_1",
                            "decisions": [
                                {
                                    "requirement_index": 1,
                                    "answerable_from_docs": False,
                                }
                            ],
                        }
                    ]
                }
            ), {"latency_ms": 1.0}

        rows, _ = run_answerability_classifier(
            population,
            baseline,
            model="fixture",
            batch_size=1,
            timeout=1,
            caller=fake_caller,
        )
        self.assertEqual(rows[0]["requirements"][0]["subject"], "private")
        self.assertFalse(rows[0]["requirements"][0]["answerable_from_docs"])

    def test_ground_truth_uses_existing_label_and_frozen_partial_overlay(self) -> None:
        partial_id = next(iter(PARTIAL_REQUIREMENT_TRUTH))
        population = [
            {
                "case_id": partial_id,
                "dataset": "fixture",
                "question": "fixture partial",
                "source_ids": ["dnf_notice"],
                "answerability_label": "partial",
            }
        ]
        original = dict(PARTIAL_REQUIREMENT_TRUTH)
        try:
            keep = PARTIAL_REQUIREMENT_TRUTH[partial_id]
            PARTIAL_REQUIREMENT_TRUTH.clear()
            PARTIAL_REQUIREMENT_TRUTH[partial_id] = keep
            rows = build_answerability_ground_truth(population)
        finally:
            PARTIAL_REQUIREMENT_TRUTH.clear()
            PARTIAL_REQUIREMENT_TRUTH.update(original)
        self.assertEqual(rows[0]["answerability_profile"], "mixed")
        self.assertFalse(
            rows[0]["new_planner_output_visible_during_ground_truth_authoring"]
        )

    def test_docs_false_positive_and_false_negative_are_separate(self) -> None:
        planner = [
            {
                "case_id": "case-1",
                "requirements": [
                    _requirement("private", True),
                    _requirement("official", False),
                ],
            }
        ]
        truth = [
            {
                "case_id": "case-1",
                "dataset": "fixture",
                "source_ids": [],
                "answerability_profile": "mixed",
                "default_requirement_answerable_from_docs": None,
                "partial_requirements_in_question_order": [
                    {"answerable_from_docs": False},
                    {"answerable_from_docs": True},
                ],
                "claim_ceiling_stress_slice": False,
            }
        ]
        diagnostics, metrics = score_answerability(planner, truth)
        self.assertEqual(metrics["overall"]["docs_false_positive_count"], 1)
        self.assertEqual(metrics["overall"]["docs_false_negative_count"], 1)
        self.assertEqual(diagnostics[0]["docs_false_positive_indices"], [1])
        self.assertEqual(diagnostics[0]["docs_false_negative_indices"], [2])

    def test_requirement_diff_ignores_only_answerability_and_generated_id(self) -> None:
        baseline = [
            {
                "case_id": "case-1",
                "requirements": [_requirement("before-id", True)],
            }
        ]
        new = [
            {
                "case_id": "case-1",
                "requirements": [
                    {
                        **_requirement("before-id", False),
                        "requirement_id": "after-id",
                    }
                ],
            }
        ]
        _, metrics = compare_requirement_regression(baseline, new)
        self.assertEqual(metrics["requirement_regression_count"], 0)

    def test_requirement_content_change_is_a_regression(self) -> None:
        baseline = [
            {"case_id": "case-1", "requirements": [_requirement("item", True)]}
        ]
        changed = _requirement("item", False)
        changed["relation"] = "다른 관계"
        new = [{"case_id": "case-1", "requirements": [changed]}]
        _, metrics = compare_requirement_regression(baseline, new)
        self.assertEqual(metrics["content_changed_question_count"], 1)


if __name__ == "__main__":
    unittest.main()
