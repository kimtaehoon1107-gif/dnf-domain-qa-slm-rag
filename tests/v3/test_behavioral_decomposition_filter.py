from __future__ import annotations

import inspect
import unittest

from src.v3.behavioral_decomposition_filter import evaluate_behavioral_coverage


def _hit(text: str) -> dict:
    return {"display_text": text}


class BehavioralDecompositionFilterTest(unittest.TestCase):
    def test_decomposition_commits_only_for_strict_coverage_gain(self) -> None:
        result = evaluate_behavioral_coverage(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            [_hit("상품 구매 조건을 안내합니다.")],
            [
                _hit("상품 구매 조건을 안내합니다."),
                _hit("상품 사용 절차를 안내합니다."),
            ],
            threshold=1.0,
        )

        self.assertEqual(result["coverage_single"], 1)
        self.assertEqual(result["coverage_decomposed"], 2)
        self.assertTrue(result["commit_decomposition"])

    def test_equal_full_coverage_downgrades_to_single(self) -> None:
        result = evaluate_behavioral_coverage(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            [_hit("상품 구매 조건과 사용 절차를 안내합니다.")],
            [
                _hit("상품 구매 조건을 안내합니다."),
                _hit("상품 사용 절차를 안내합니다."),
            ],
            threshold=1.0,
        )

        self.assertEqual(result["coverage_single"], 2)
        self.assertEqual(result["coverage_decomposed"], 2)
        self.assertFalse(result["commit_decomposition"])

    def test_unmeasurable_targets_stay_single(self) -> None:
        result = evaluate_behavioral_coverage(
            "상점에서 구입하는 방법을 알려줘.",
            [_hit("상점 구입 방법을 안내합니다.")],
            [_hit("상점 구입 방법을 안내합니다.")],
            threshold=0.5,
        )

        self.assertFalse(result["coverage_measurable"])
        self.assertFalse(result["commit_decomposition"])

    def test_runtime_signature_cannot_accept_gold_or_expected_source(self) -> None:
        parameters = set(inspect.signature(evaluate_behavioral_coverage).parameters)

        self.assertNotIn("gold_chunk_ids", parameters)
        self.assertNotIn("gold_document_ids", parameters)
        self.assertNotIn("expected_source_ids", parameters)

    def test_filter_has_no_keyword_or_store_expansion_rule(self) -> None:
        result = evaluate_behavioral_coverage(
            "보상 수령 조건과 지급 시점은?",
            [_hit("보상 수령 조건만 안내합니다.")],
            [_hit("보상 수령 조건과 지급 시점을 안내합니다.")],
            threshold=0.5,
        )

        self.assertEqual(result["new_field_or_intent_keyword_rule_count"], 0)
        self.assertFalse(result["gold_identifiers_used"])
        self.assertFalse(result["expected_source_used"])
        self.assertFalse(result["store_expansion_applied"])


if __name__ == "__main__":
    unittest.main()
