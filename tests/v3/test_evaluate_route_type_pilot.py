from __future__ import annotations

import unittest

from src.v3.evaluate_route_type_pilot import evaluate_rows


class EvaluateRouteTypePilotTest(unittest.TestCase):
    def test_route_type_metrics_keep_reject_first_and_score_decomposition(self) -> None:
        rows = [
            {
                "question": "상품의 구매 조건과 사용 절차를 설명해줘.",
                "expected": "decompose",
            },
            {
                "question": "상점에서 구입하는 방법을 알려줘.",
                "expected": "retrieve",
            },
            {
                "question": "버그 악용 꼼수를 순서대로 알려줘.",
                "expected": "reject",
            },
            {
                "question": "지금 경매장에서 아바타 시세 얼마야?",
                "expected": "realtime_api",
            },
        ]

        metrics = evaluate_rows(rows, lambda row: row["expected"])

        self.assertEqual(metrics["route_action_exact"]["successes"], 4)
        self.assertEqual(metrics["decomposition"]["true_positive"], 1)
        self.assertEqual(metrics["decomposition"]["false_positive"], 0)
        self.assertEqual(metrics["decomposition"]["false_negative"], 0)
        self.assertEqual(metrics["answerability_short_circuit_count"], 2)
        self.assertEqual(metrics["answer_target_analyzer_calls"], 2)
        self.assertEqual(metrics["new_field_or_intent_keyword_rule_count"], 0)
        self.assertEqual(metrics["signal_b_applied_count"], 0)
        self.assertFalse(metrics["question_text_included"])
        self.assertFalse(metrics["gold_text_included"])


if __name__ == "__main__":
    unittest.main()
