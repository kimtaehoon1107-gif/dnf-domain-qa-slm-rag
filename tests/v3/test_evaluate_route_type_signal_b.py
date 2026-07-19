from __future__ import annotations

import unittest

from src.v3.evaluate_route_type_signal_b import _predict


class EvaluateRouteTypeSignalBTest(unittest.TestCase):
    def test_full_top_chunk_coverage_downgrades_to_retrieve(self) -> None:
        action, measured, downgraded = _predict(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            {"display_text": "상품 구매 조건과 상품 사용 절차를 안내합니다."},
            True,
        )

        self.assertEqual(action, "retrieve")
        self.assertTrue(measured)
        self.assertTrue(downgraded)

    def test_partial_coverage_keeps_decomposition(self) -> None:
        action, measured, downgraded = _predict(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            {"display_text": "상품 구매 조건만 안내합니다."},
            True,
        )

        self.assertEqual(action, "decompose")
        self.assertTrue(measured)
        self.assertFalse(downgraded)

    def test_wrong_store_does_not_apply_signal_b(self) -> None:
        action, measured, downgraded = _predict(
            "상품의 구매 조건과 사용 절차를 설명해줘.",
            {"display_text": "상품 구매 조건과 상품 사용 절차를 안내합니다."},
            False,
        )

        self.assertEqual(action, "decompose")
        self.assertFalse(measured)
        self.assertFalse(downgraded)

    def test_reject_short_circuits_before_both_signals(self) -> None:
        action, measured, downgraded = _predict(
            "버그 악용 꼼수를 순서대로 알려줘.", None, False
        )

        self.assertEqual(action, "reject")
        self.assertFalse(measured)
        self.assertFalse(downgraded)


if __name__ == "__main__":
    unittest.main()
