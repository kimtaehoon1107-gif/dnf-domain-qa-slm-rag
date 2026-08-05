from __future__ import annotations

import unittest

from src.v3.answer_target_router import (
    _clause_boundaries,
    _kiwi,
    analyze_answer_targets,
)


class AnswerTargetRouterTest(unittest.TestCase):
    def test_coordinated_answer_targets_require_decomposition(self) -> None:
        result = analyze_answer_targets(
            "상품의 구매 조건과 사용 절차를 설명해줘."
        )

        self.assertTrue(result["needs_decomposition"])
        self.assertEqual(result["answer_target_count"], 2)
        self.assertEqual(result["coordinated_nominal_target_count"], 2)

    def test_independent_clauses_require_decomposition(self) -> None:
        result = analyze_answer_targets(
            "재료를 어디서 얻고 어떻게 사용해?"
        )

        self.assertTrue(result["needs_decomposition"])
        self.assertEqual(result["independent_clause_target_count"], 2)

    def test_single_target_stays_retrieve(self) -> None:
        result = analyze_answer_targets("상점에서 구입하는 방법을 알려줘.")

        self.assertFalse(result["needs_decomposition"])
        self.assertEqual(result["answer_target_count"], 1)

    def test_repeated_nominal_is_not_counted_as_distinct_target(self) -> None:
        result = analyze_answer_targets("가격과 가격 정보를 다시 확인해줘.")

        self.assertFalse(result["needs_decomposition"])
        self.assertEqual(result["coordinated_nominal_target_count"], 0)

    def test_signal_is_deterministic_and_has_no_keyword_rules(self) -> None:
        question = "보상 수령 조건과 지급 시점은?"

        first = analyze_answer_targets(question)
        second = analyze_answer_targets(question)

        self.assertEqual(first, second)
        self.assertEqual(first["domain_keyword_rule_count"], 0)
        self.assertEqual(first["surface_marker_rule_count"], 0)
        self.assertFalse(first["signal_b_applied"])

    def test_empty_question_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must not be empty"):
            analyze_answer_targets("  ")

    def test_allowed_forms_does_not_change_default_clause_boundaries(self) -> None:
        question = (
            "게임에서 버그를 발견하면 어디에 제보해야 하고, "
            "제보 뒤 답변까지 걸리는 기한은 정확히 며칠이야?"
        )
        tokens = list(_kiwi().tokenize(question))

        self.assertEqual(
            [str(tokens[index].form) for index in _clause_boundaries(tokens)],
            ["면", "어야"],
        )
        self.assertEqual(
            [
                str(tokens[index].form)
                for index in _clause_boundaries(
                    tokens,
                    allowed_forms={"고"},
                )
            ],
            ["고"],
        )


if __name__ == "__main__":
    unittest.main()
