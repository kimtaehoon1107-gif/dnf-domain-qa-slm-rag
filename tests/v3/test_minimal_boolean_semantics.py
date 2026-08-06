from __future__ import annotations

import unittest

from src.v3.minimal_boolean_semantics import boolean_relation_evidence


class MinimalBooleanSemanticsTests(unittest.TestCase):
    def test_narrative_negative_phrases_mean_false(self) -> None:
        requirement = {"relation": "ranked", "value_type": "boolean"}
        self.assertEqual(
            boolean_relation_evidence(
                requirement,
                "일반모드는 랭킹 집계와 무관합니다.",
            ),
            {False},
        )
        self.assertEqual(
            boolean_relation_evidence(
                {"relation": "duel_arena_available"},
                "성장 가속 모드 상태에서는 결투장 이용이 어렵습니다.",
            ),
            {False},
        )

    def test_unlimited_only_negates_deadline_relation(self) -> None:
        text = "시브의 보조장비 보주는 기간 무제한 아이템입니다."
        self.assertEqual(
            boolean_relation_evidence(
                {"relation": "has_deletion_deadline"},
                text,
            ),
            {False},
        )
        self.assertEqual(
            boolean_relation_evidence({"relation": "usable"}, text),
            set(),
        )

    def test_existing_boolean_markers_are_preserved(self) -> None:
        self.assertEqual(
            boolean_relation_evidence(
                {"relation": "available"},
                "OTP 이용이 가능합니다.",
            ),
            {True},
        )


if __name__ == "__main__":
    unittest.main()
