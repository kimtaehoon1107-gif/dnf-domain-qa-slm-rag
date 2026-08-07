from __future__ import annotations

import unittest

from src.v3.typed_evidence_ref import (
    build_evidence_units,
    build_typed_evidence_prompt,
    verify_typed_requirement_selection,
)


def _artifacts(
    text: str,
    *,
    source_id: str,
    title: str,
    published_at: str = "2026-07-01",
    valid_from: str | None = None,
    source_kind: str | None = None,
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    chunk = {
        "chunk_id": "chunk_1",
        "parent_document_id": "document_1",
        "display_text": text,
        "default_exposure": True,
        "status": "current",
    }
    document = {
        "document_id": "document_1",
        "source_id": source_id,
        "title": title,
        "published_at": published_at,
        "valid_from": valid_from,
        "revision_id": "revision_1",
        "status": "current",
        "default_exposure": True,
    }
    if source_kind is not None:
        document["source_kind"] = source_kind
    temporal = {
        "document_id": "document_1",
        "revision_id": "revision_1",
        "valid_from": valid_from,
        "validity_state": "current",
        "retrieval_action_current": "allow",
    }
    if source_kind is not None:
        temporal["source_kind"] = source_kind
    return (
        {"chunk_1": chunk},
        {"document_1": document},
        {"document_1": temporal},
    )


def _units(
    text: str,
    *,
    source_id: str,
    title: str,
    published_at: str = "2026-07-01",
    valid_from: str | None = None,
    source_kind: str | None = None,
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    chunks, documents, temporal = _artifacts(
        text,
        source_id=source_id,
        title=title,
        published_at=published_at,
        valid_from=valid_from,
        source_kind=source_kind,
    )
    unit_rows = build_evidence_units(
        ["chunk_1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    return chunks, {
        unit["evidence_ref"]: unit
        for unit in unit_rows
    }


def _ref_containing(
    units: dict[str, dict[str, object]],
    needle: str,
) -> str:
    return next(
        evidence_ref
        for evidence_ref, unit in units.items()
        if needle in str(unit["text"])
    )


class TypedEvidenceRefMonthPolicyRegressionTest(unittest.TestCase):
    def test_inline_next_month_item_does_not_rebind_monthly_record(
        self,
    ) -> None:
        text = (
            "# [6월 이달의 아이템]\n"
            "사용 시 [7월]클론 레어 아바타 상자를 획득합니다.\n"
            "거래타입: 교환가능"
        )
        chunks, units = _units(
            text,
            source_id="dnf_monthly_item",
            title="이달의 아이템",
        )
        evidence_ref = _ref_containing(units, "거래타입: 교환가능")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "trade_type",
                "status": "supported",
                "value_type": "enum",
                "value": "교환가능",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "trade_type",
                "subject": "7월 이달의 아이템",
                "relation": "trade_type",
                "value_type": "enum",
            },
            question_time_scope="current",
            question_text="7월 이달의 아이템 거래타입은?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported", audit)
        self.assertIn(
            "monthly_record_binding_failed",
            audit["failure_reasons"],
        )

    def test_non_temporal_preamble_is_excluded_from_monthly_record(
        self,
    ) -> None:
        text = (
            "상점판매가\n"
            "2,000만 골드\n"
            "# [7월 이달의 아이템]\n"
            "상점판매가\n"
            "4,000만 골드"
        )
        chunks, documents, temporal = _artifacts(
            text,
            source_id="dnf_monthly_item",
            title="이달의 아이템",
        )

        prompt, visible_units = build_typed_evidence_prompt(
            question="7월 이달의 아이템 상점 판매가는?",
            requirements=[
                {
                    "requirement_id": "shop_price",
                    "subject": "7월 이달의 아이템",
                    "relation": "shop_price",
                    "value_type": "currency",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["chunk_1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )
        visible_text = "\n".join(
            str(unit["text"]) for unit in visible_units.values()
        )

        self.assertIn("4,000만 골드", prompt)
        self.assertNotIn("2,000만 골드", prompt)
        self.assertNotIn("2,000만 골드", visible_text)

    def test_policy_question_year_binds_returned_effective_date(
        self,
    ) -> None:
        text = (
            "세라 이용약관은 2025년 12월 2일 시행하며, "
            "별도 이벤트는 2026년 1월 1일 종료됩니다."
        )
        chunks, units = _units(
            text,
            source_id="dnf_account_policy",
            source_kind="account_policy",
            title="세라 이용약관",
            published_at="2025-11-20",
            valid_from="2025-12-02",
        )
        evidence_ref = _ref_containing(units, "2025년 12월 2일")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2025-12-02",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "effective_date",
                "subject": "세라 이용약관",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="historical",
            question_text="2026년 세라 이용약관은 언제 시행돼?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported", audit)
        self.assertIn(
            "policy_question_year_mismatch",
            audit["failure_reasons"],
        )

    def test_temporal_marker_is_local_to_its_date_occurrence(self) -> None:
        text = (
            "Act 업데이트는 2025년 12월 2일 적용되며, "
            "관련 이벤트는 2026년 1월 1일 종료됩니다."
        )
        chunks, units = _units(
            text,
            source_id="dnf_update",
            title="Act 업데이트",
        )
        evidence_ref = _ref_containing(units, "2025년 12월 2일")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2026-01-01",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "effective_date",
                "subject": "Act 업데이트",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="current",
            question_text="Act 업데이트는 언제 적용됐어?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported", audit)
        self.assertIn(
            "temporal_role_mismatch",
            audit["failure_reasons"],
        )

    def test_policy_question_recognizes_iso_year_identity(self) -> None:
        text = "세라 이용약관은 2026년 3월 15일부터 시행됩니다."
        chunks, units = _units(
            text,
            source_id="dnf_account_policy",
            source_kind="account_policy",
            title="세라 이용약관",
            published_at="2026-03-01",
            valid_from="2026-03-15",
        )
        evidence_ref = _ref_containing(units, "2026년 3월 15일")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2026-03-15",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "effective_date",
                "subject": "세라 이용약관",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="historical",
            question_text=(
                "2025-11-01에 공지된 세라 이용약관은 언제 시행돼?"
            ),
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported", audit)
        self.assertIn(
            "policy_question_year_mismatch",
            audit["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
