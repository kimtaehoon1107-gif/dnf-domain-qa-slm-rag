from __future__ import annotations

import unittest

from src.v3.minimal_list_contract import verify_entity_list_contract


class MinimalListContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requirement = {
            "relation": "required_inquiry_fields",
            "value_type": "entity_list",
        }
        self.evidence = (
            "[기재사항]\n"
            "1. 서버/캐릭터명 :\n"
            "2. 장착중인 칭호 :"
        )

    def test_required_fields_must_all_be_present(self) -> None:
        result = verify_entity_list_contract(
            self.requirement,
            ["서버", "캐릭터명", "장착중인 칭호"],
            self.evidence,
        )
        self.assertEqual(result["state"], "matched")
        self.assertEqual(
            result["required_items"],
            ["서버", "캐릭터명", "장착중인 칭호"],
        )

    def test_missing_required_field_is_blocked(self) -> None:
        result = verify_entity_list_contract(
            self.requirement,
            ["서버", "캐릭터명"],
            self.evidence,
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn(
            "entity_list_required_items_missing",
            result["failures"],
        )


if __name__ == "__main__":
    unittest.main()
