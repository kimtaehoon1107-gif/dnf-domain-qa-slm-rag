from __future__ import annotations

import unittest

from src.v3.typed_evidence_ref import (
    build_evidence_units,
    build_typed_evidence_prompt,
    build_typed_evidence_prompt_with_candidate_units,
    verify_typed_requirement_selection,
)


def _artifacts(
    text: str,
    *,
    title: str,
) -> tuple[dict, dict, dict]:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": text,
            "default_exposure": True,
            "status": "current",
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_test",
            "title": title,
            "published_at": "2026-07-01",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }
    temporal = {
        "d1": {
            "document_id": "d1",
            "revision_id": "r1",
            "validity_state": "current",
            "retrieval_action_current": "allow",
        }
    }
    return chunks, documents, temporal


def _units(
    text: str,
    *,
    title: str,
) -> tuple[dict, dict[str, dict], dict, dict]:
    chunks, documents, temporal = _artifacts(text, title=title)
    units = build_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    return (
        chunks,
        {unit["evidence_ref"]: unit for unit in units},
        documents,
        temporal,
    )


def _ref_containing(
    units_by_ref: dict[str, dict],
    needle: str,
) -> str:
    return next(
        evidence_ref
        for evidence_ref, unit in units_by_ref.items()
        if unit["text"] == needle
    )


class TypedEvidenceRefValueContractRegressionTest(unittest.TestCase):
    def test_requested_currency_unit_must_match_model_value_unit(
        self,
    ) -> None:
        text = (
            "상의 클론 아바타 판매가는 2,600 세라입니다.\n"
            "상의 클론 아바타 판매가는 15 골드 코인입니다."
        )
        chunks, units, _, _ = _units(
            text,
            title="상의 클론 아바타",
        )
        gold_coin_ref = _ref_containing(
            units,
            "상의 클론 아바타 판매가는 15 골드 코인입니다.",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "15 골드 코인",
                "evidence_refs": [gold_coin_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "상의 클론 아바타",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            question_text="상의 클론 아바타의 세라 판매가는 얼마야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn("currency_unit_mismatch", audit["failure_reasons"])
        self.assertEqual(audit["requested_currency_units"], ["세라"])
        self.assertEqual(audit["model_currency_units"], ["골드 코인"])

    def test_unreduced_candidate_units_expose_hidden_currency_sibling(
        self,
    ) -> None:
        text = (
            "상의 클론 아바타 판매가는 2,600 세라입니다.\n"
            "상의 클론 아바타 판매가는 15 골드 코인입니다."
        )
        chunks, candidate_units, _, _ = _units(
            text,
            title="상의 클론 아바타",
        )
        gold_coin_ref = _ref_containing(
            candidate_units,
            "상의 클론 아바타 판매가는 15 골드 코인입니다.",
        )
        visible_units = {
            gold_coin_ref: candidate_units[gold_coin_ref],
        }
        output = {
            "requirement_id": "price",
            "status": "supported",
            "value_type": "currency",
            "value": "15 골드 코인",
            "evidence_refs": [gold_coin_ref],
        }
        requirement = {
            "requirement_id": "price",
            "subject": "상의 클론 아바타",
            "relation": "shop_price",
            "value_type": "currency",
        }

        legacy_decision, legacy_audit = (
            verify_typed_requirement_selection(
                output,
                requirement=requirement,
                question_time_scope="current",
                question_text="상의 클론 아바타 판매가는 얼마야?",
                evidence_units_by_ref=visible_units,
                chunks_by_id=chunks,
                as_of="2026-07-22",
            )
        )
        candidate_decision, candidate_audit = (
            verify_typed_requirement_selection(
                output,
                requirement=requirement,
                question_time_scope="current",
                question_text="상의 클론 아바타 판매가는 얼마야?",
                evidence_units_by_ref=visible_units,
                candidate_evidence_units_by_ref=candidate_units,
                chunks_by_id=chunks,
                as_of="2026-07-22",
            )
        )

        self.assertEqual(
            legacy_decision["status"],
            "supported_exact",
            legacy_audit,
        )
        self.assertEqual(candidate_decision["status"], "unsupported")
        self.assertIn(
            "currency_qualifier_ambiguity_unresolved",
            candidate_audit["failure_reasons"],
        )
        self.assertEqual(
            candidate_audit["unresolved_currency_values"],
            [{"amount": 2600, "unit": "세라"}],
        )

    def test_entity_list_rejects_duplicate_values(self) -> None:
        text = "장비 지원 레벨: 110레벨과 115레벨"
        chunks, units, _, _ = _units(text, title="장비 지원 정보")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "levels",
                "status": "supported",
                "value_type": "entity_list",
                "value": ["110", "110"],
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "levels",
                "subject": "장비",
                "relation": "supported_levels",
                "relation_surface": "지원 레벨",
                "value_type": "entity_list",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "entity_list_duplicate_values",
            audit["failure_reasons"],
        )
        self.assertEqual(
            audit["cardinality_validation_state"],
            "duplicate_values",
        )

    def test_numeric_entity_list_accepts_delimited_exact_values(
        self,
    ) -> None:
        text = "장비 지원 레벨: 110, 115"
        chunks, units, _, _ = _units(text, title="장비 지원 정보")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "levels",
                "status": "supported",
                "value_type": "entity_list",
                "value": ["110", "115"],
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "levels",
                "subject": "장비",
                "relation": "supported_levels",
                "relation_surface": "지원 레벨",
                "value_type": "entity_list",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)

    def test_numeric_entity_does_not_match_longer_numeric_entity(
        self,
    ) -> None:
        text = "장비 지원 레벨: 1100레벨"
        chunks, units, _, _ = _units(text, title="장비 지원 정보")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "levels",
                "status": "supported",
                "value_type": "entity_list",
                "value": ["110"],
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "levels",
                "subject": "장비",
                "relation": "supported_levels",
                "relation_surface": "지원 레벨",
                "value_type": "entity_list",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "typed_value_not_supported_by_evidence",
            audit["failure_reasons"],
        )

    def test_shop_price_relation_is_not_satisfied_by_currency_value(
        self,
    ) -> None:
        text = "상의 클론 아바타는 15 골드 코인으로 교환됩니다."
        chunks, units, _, _ = _units(
            text,
            title="상의 클론 아바타",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "15 골드 코인",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "상의 클론 아바타",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "relation_not_supported_by_evidence",
            audit["failure_reasons"],
        )

    def test_shop_price_relation_accepts_relation_label(self) -> None:
        text = "상의 클론 아바타 상점판매가는 15 골드 코인입니다."
        chunks, units, _, _ = _units(
            text,
            title="상의 클론 아바타",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "15 골드 코인",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "상의 클론 아바타",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)

    def test_currency_name_in_subject_is_not_a_requested_unit(
        self,
    ) -> None:
        text = "골드 코인 상자 상점판매가는 2,600 세라입니다."
        chunks, units, _, _ = _units(text, title="골드 코인 상자")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "2,600 세라",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "골드 코인 상자",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            question_text="골드 코인 상자의 상점 판매가는 얼마야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)
        self.assertEqual(audit["requested_currency_units"], [])

    def test_currency_amount_in_subject_is_not_a_sibling_price(
        self,
    ) -> None:
        text = "골드 코인 10개 상점판매가는 1,500 세라입니다."
        chunks, units, _, _ = _units(text, title="골드 코인 10개")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "1,500 세라",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "골드 코인 10개",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            question_text="골드 코인 10개 상점 판매가는 얼마야?",
            evidence_units_by_ref=units,
            candidate_evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)
        self.assertEqual(audit["requested_currency_units"], [])
        self.assertEqual(audit["unresolved_currency_values"], [])

    def test_hidden_currency_sibling_respects_ordinal_qualifier(
        self,
    ) -> None:
        text = (
            "## 1주차\n"
            "상의 클론 아바타 상점판매가는 15 골드 코인입니다.\n"
            "## 2주차\n"
            "상의 클론 아바타 상점판매가는 2,600 세라입니다."
        )
        chunks, candidate_units, _, _ = _units(
            text,
            title="상의 클론 아바타 주차별 판매가",
        )
        selected_ref = _ref_containing(
            candidate_units,
            "상의 클론 아바타 상점판매가는 15 골드 코인입니다.",
        )
        visible_refs = {
            selected_ref,
            *candidate_units[selected_ref].get("context_refs", []),
        }
        visible_units = {
            evidence_ref: candidate_units[evidence_ref]
            for evidence_ref in visible_refs
        }

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "15 골드 코인",
                "evidence_refs": [selected_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "상의 클론 아바타",
                "relation": "shop_price",
                "value_type": "currency",
                "qualifiers": {"week_index": 1},
            },
            question_time_scope="current",
            question_text="1주차 상의 클론 아바타 판매가는 얼마야?",
            evidence_units_by_ref=visible_units,
            candidate_evidence_units_by_ref=candidate_units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)
        self.assertEqual(audit["unresolved_currency_values"], [])

    def test_prompt_api_keeps_legacy_pair_and_exposes_candidate_map(
        self,
    ) -> None:
        text = "\n".join(
            f"장비 안내 문장 {index}입니다."
            for index in range(60)
        )
        chunks, documents, temporal = _artifacts(
            text,
            title="장비 안내",
        )
        kwargs = {
            "question": "장비 안내가 뭐야?",
            "requirements": [
                {
                    "requirement_id": "guide",
                    "subject": "장비",
                    "relation": "guide",
                    "value_type": "text",
                }
            ],
            "question_time_scope": "current",
            "as_of": "2026-07-22",
            "candidate_chunk_ids": ["c1"],
            "chunks_by_id": chunks,
            "documents_by_id": documents,
            "temporal_by_document": temporal,
        }

        legacy_prompt, legacy_visible = build_typed_evidence_prompt(
            **kwargs
        )
        prompt, visible, candidates = (
            build_typed_evidence_prompt_with_candidate_units(**kwargs)
        )

        self.assertEqual(prompt, legacy_prompt)
        self.assertEqual(visible, legacy_visible)
        self.assertGreater(len(candidates), len(visible))


if __name__ == "__main__":
    unittest.main()
