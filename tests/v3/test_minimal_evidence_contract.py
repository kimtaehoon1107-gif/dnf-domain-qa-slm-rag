from __future__ import annotations

import unittest

from src.v3.minimal_evidence_contract import (
    NARRATIVE,
    PRODUCT_RECORD,
    STRUCTURED_TABLE,
    annotate_prompt_with_evidence_contracts,
    evidence_contract_for_unit,
    selected_evidence_contract,
)


class MinimalEvidenceContractTests(unittest.TestCase):
    def test_routes_narrative_product_and_structured_units(self) -> None:
        narrative = {
            "chunk_id": "narrative",
            "start_char": 0,
            "end_char": 10,
            "source_id": "dnf_faq",
            "source_kind": "faq",
        }
        product = {
            "chunk_id": "product",
            "start_char": 0,
            "end_char": 10,
            "source_id": "dnf_monthly_item",
            "source_kind": "monthly_item",
        }
        structured = {
            "chunk_id": "policy",
            "start_char": 20,
            "end_char": 30,
            "source_id": "dnf_account_policy",
            "source_kind": "policy",
        }
        rows = {("policy", 20, 30): {"row_subject": "운영자 사칭"}}
        self.assertEqual(
            evidence_contract_for_unit(
                narrative,
                structured_rows_by_coordinate=rows,
            ),
            NARRATIVE,
        )
        self.assertEqual(
            evidence_contract_for_unit(
                product,
                structured_rows_by_coordinate=rows,
            ),
            PRODUCT_RECORD,
        )
        self.assertEqual(
            evidence_contract_for_unit(
                structured,
                structured_rows_by_coordinate=rows,
            ),
            STRUCTURED_TABLE,
        )

    def test_selected_contract_prefers_stricter_product_branch(self) -> None:
        result = selected_evidence_contract(
            [
                {
                    "chunk_id": "a",
                    "start_char": 0,
                    "end_char": 1,
                    "source_id": "dnf_faq",
                },
                {
                    "chunk_id": "b",
                    "start_char": 0,
                    "end_char": 1,
                    "source_id": "dnf_seria_shop",
                },
            ],
            structured_rows_by_coordinate={},
        )
        self.assertEqual(result["branch"], PRODUCT_RECORD)
        self.assertTrue(result["mixed"])

    def test_prompt_annotation_keeps_evidence_ref(self) -> None:
        unit = {
            "chunk_id": "a",
            "start_char": 0,
            "end_char": 1,
            "source_id": "dnf_faq",
        }
        prompt = annotate_prompt_with_evidence_contracts(
            "E7\ttemporal_roles=none\t근거",
            evidence_units_by_ref={"E7": unit},
            structured_rows_by_coordinate={},
        )
        self.assertIn("E7\tevidence_contract=narrative\t", prompt)
        self.assertIn("근거 계약 규칙", prompt)


if __name__ == "__main__":
    unittest.main()
