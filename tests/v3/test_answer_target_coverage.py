from __future__ import annotations

import unittest

from src.v3.answer_target_coverage import evaluate_top_chunk_coverage


class AnswerTargetCoverageTest(unittest.TestCase):
    def test_top_chunk_must_cover_every_structural_target(self) -> None:
        result = evaluate_top_chunk_coverage(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            "상품 구매 조건과 상품 사용 절차를 안내합니다.",
        )

        self.assertEqual(result["target_group_count"], 2)
        self.assertEqual(result["covered_target_group_count"], 2)
        self.assertTrue(result["all_targets_in_top_chunk"])

    def test_partial_top_chunk_does_not_downgrade_decomposition(self) -> None:
        result = evaluate_top_chunk_coverage(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            "상품 구매 조건만 안내합니다.",
        )

        self.assertEqual(result["covered_target_group_count"], 1)
        self.assertFalse(result["all_targets_in_top_chunk"])

    def test_single_target_is_not_signal_b_eligible(self) -> None:
        result = evaluate_top_chunk_coverage(
            "상점에서 구입하는 방법을 알려줘.",
            "상점에서 구입하는 방법입니다.",
        )

        self.assertEqual(result["target_group_count"], 0)
        self.assertFalse(result["all_targets_in_top_chunk"])

    def test_coverage_has_no_keyword_or_store_expansion_rule(self) -> None:
        result = evaluate_top_chunk_coverage(
            "보상 수령 조건과 지급 시점은?",
            "보상 수령 조건과 지급 시점을 안내합니다.",
        )

        self.assertEqual(result["domain_keyword_rule_count"], 0)
        self.assertFalse(result["store_expansion_applied"])
        self.assertTrue(all(len(value) == 64 for value in result["target_group_hashes"]))


if __name__ == "__main__":
    unittest.main()
