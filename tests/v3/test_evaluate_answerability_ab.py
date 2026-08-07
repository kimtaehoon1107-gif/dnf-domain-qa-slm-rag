from __future__ import annotations

import unittest

from src.v3.evaluate_answerability_ab import (
    ANSWERABILITY_MODEL_PROMPT,
    AnswerSourceBatch,
    build_enumeration_rows,
    choose_approach,
    classify_structural,
    run_model_classifier,
    score_predictions,
)


def _planner_row(answerable: bool = True) -> dict:
    return {
        "case_id": "case-1",
        "requirements": [
            {
                "requirement_id": "requirement_1",
                "subject": "이용제한",
                "relation": "단계",
                "value_type": "text",
                "subject_group": "정책",
                "answerable_from_docs": answerable,
                "qualifiers": ["ignored"],
                "time_scope": None,
                "coordination_scope": None,
            }
        ],
    }


def _truth(expected: bool) -> dict:
    return {
        "case_id": "case-1",
        "dataset": "adaptive_dev_63",
        "source_ids": ["dnf_account_policy"],
        "answerability_profile": "docs_only" if expected else "non_docs_only",
        "default_requirement_answerable_from_docs": expected,
        "partial_requirements_in_question_order": [],
        "question": "이용제한 단계는 무엇인가?",
    }


class AnswerabilitySeparationTest(unittest.TestCase):
    def test_enumeration_projection_removes_answerability_and_optional_fields(self) -> None:
        rows = build_enumeration_rows([_planner_row(False)])
        requirement = rows[0]["requirements"][0]
        self.assertEqual(
            set(requirement),
            {"requirement_id", "subject", "relation", "value_type", "subject_group"},
        )
        self.assertNotIn("answerable_from_docs", requirement)

    def test_model_contract_is_multiclass_and_does_not_edit_requirements(self) -> None:
        self.assertIn("personal_account", ANSWERABILITY_MODEL_PROMPT)
        self.assertIn("ambiguous", ANSWERABILITY_MODEL_PROMPT)
        enumeration = build_enumeration_rows([_planner_row()])

        def fake_caller(**_: object):
            return AnswerSourceBatch.model_validate(
                {
                    "cases": [
                        {
                            "case_id": "case_1",
                            "decisions": [
                                {
                                    "requirement_index": 1,
                                    "answer_source": "official_docs",
                                }
                            ],
                        }
                    ]
                }
            ), {"latency_ms": 1.0}

        predictions, _ = run_model_classifier(
            [_truth(True)],
            enumeration,
            model="fixture",
            batch_size=1,
            timeout=1,
            caller=fake_caller,
        )
        self.assertEqual(
            predictions[0]["decisions"][0]["answer_source"], "official_docs"
        )
        self.assertNotIn("requirements", predictions[0])

    def test_structural_gate_distinguishes_examples(self) -> None:
        official = _planner_row()["requirements"][0]
        personal = {
            **official,
            "subject": "내 계정",
            "subject_group": "사용자 계정",
            "relation": "제재 상태",
        }
        realtime = {
            **official,
            "subject": "웨딩 아바타",
            "relation": "current_auction_price",
        }
        subjective = {
            **official,
            "subject": "내 세팅",
            "relation": "추천 여부",
        }
        self.assertEqual(
            classify_structural(
                "이용제한 단계는?", official, requirement_count=1
            )[0],
            "official_docs",
        )
        self.assertEqual(
            classify_structural(
                "내 계정 제재 상태는?", personal, requirement_count=1
            )[0],
            "personal_account",
        )
        self.assertEqual(
            classify_structural(
                "지금 경매장 시세는?", realtime, requirement_count=1
            )[0],
            "realtime",
        )
        self.assertEqual(
            classify_structural(
                "내 세팅을 추천해줘", subjective, requirement_count=1
            )[0],
            "subjective",
        )
        self.assertEqual(
            classify_structural(
                "로또 번호를 골라줘", official, requirement_count=1
            )[0],
            "out_of_scope",
        )

    def test_mixed_scope_without_requirement_binding_is_ambiguous(self) -> None:
        requirement = _planner_row()["requirements"][0]
        answer_source, _ = classify_structural(
            "공식 조건과 내 상황을 함께 알려줘",
            requirement,
            requirement_count=2,
        )
        self.assertEqual(answer_source, "ambiguous")

    def test_scoring_separates_clear_errors_from_ambiguous(self) -> None:
        predictions = [
            {
                "case_id": "case-1",
                "decisions": [
                    {"requirement_index": 1, "answer_source": "ambiguous"}
                ],
            }
        ]
        _, metrics = score_predictions(predictions, [_truth(False)])
        self.assertEqual(metrics["overall"]["docs_false_positive_count"], 0)
        self.assertEqual(metrics["overall"]["ambiguous_count"], 1)
        self.assertEqual(metrics["overall"]["clear_coverage"], 0.0)

    def test_selection_rejects_trivial_all_ambiguous_arm(self) -> None:
        metrics = {
            "overall": {
                "docs_false_positive_count": 0,
                "docs_false_negative_count": 0,
                "ambiguous_count": 10,
                "clear_coverage": 0.0,
            }
        }
        selected = choose_approach({"all_ambiguous": metrics})
        self.assertEqual(selected["decision"], "NO_GO_ANSWERABILITY_AB")


if __name__ == "__main__":
    unittest.main()
