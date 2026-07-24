from __future__ import annotations

import unittest

from src.v3.evaluate_grounded_llm_replay import run_fixed_requirement_replay
from src.v3.typed_evidence_ref import (
    _value_supported,
    build_evidence_units,
    build_typed_evidence_prompt,
    verify_typed_requirement_selection,
)
from src.v3.value_normalization import boolean_evidence, currency_values


def _artifacts(
    text: str,
    *,
    title: str,
    published_at: str = "2026-07-01",
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
            "published_at": published_at,
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
    published_at: str = "2026-07-01",
) -> tuple[dict, dict[str, dict], dict, dict]:
    chunks, documents, temporal = _artifacts(
        text, title=title, published_at=published_at
    )
    units = build_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    return chunks, {unit["evidence_ref"]: unit for unit in units}, documents, temporal


def _ref_containing(units: dict[str, dict], needle: str) -> str:
    return next(
        evidence_ref
        for evidence_ref, unit in units.items()
        if unit["text"] == needle
    )


class TypedEvidenceRefTest(unittest.TestCase):
    def test_evidence_units_restore_exact_source_coordinates(self) -> None:
        text = "제목\n첫 문장입니다. 둘째 문장입니다.\n마지막 줄"
        chunks, documents, temporal = _artifacts(text, title="테스트")

        prompt, units = build_typed_evidence_prompt(
            question="질문",
            requirements=[
                {
                    "requirement_id": "r1",
                    "subject": "테스트",
                    "relation": "첫 문장",
                    "surface": "첫 문장",
                    "value_type": "text",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("E1\t", prompt)
        self.assertNotIn("evidence=E1", prompt)
        self.assertIn("선택 가능한 ID는 E숫자뿐", prompt)
        for unit in units.values():
            self.assertEqual(
                text[unit["start_char"] : unit["end_char"]],
                unit["text"],
            )

    def test_datetime_normalization_accepts_korean_source_and_iso_value(self) -> None:
        text = "삭제일자: 2026년 8월 13일 06시 일괄삭제"
        chunks, units, _, _ = _units(text, title="이달의 아이템")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "datetime",
                "value": "2026-08-13T06:00",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "이달의 아이템",
                "relation": "삭제 시각",
                "surface": "삭제 시각",
                "value_type": "datetime",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "2026년 8월 13일 6시")
        self.assertEqual(audit["failure_reasons"], [])

    def test_effective_date_rejects_published_timestamp(self) -> None:
        text = (
            "2026.06.24 15:00\n"
            "6/25(목) 적용되는 던파ON 2.0.19 버전 업데이트 안내"
        )
        chunks, units, _, _ = _units(
            text, title="던파ON 2.0.19", published_at="2026-06-24"
        )
        published_ref = _ref_containing(units, "2026.06.24 15:00")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "date",
                "value": "2026-06-24",
                "evidence_refs": [published_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "던파ON",
                "relation": "2.0.19 버전 적용일",
                "surface": "적용 시점",
                "value_type": "date",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn("relation_not_supported_by_evidence", audit["failure_reasons"])
        self.assertIn("temporal_role_mismatch", audit["failure_reasons"])

    def test_effective_date_accepts_explicit_apply_context(self) -> None:
        text = "6/25(목) 적용되는 던파ON 2.0.19 버전 업데이트 안내"
        chunks, units, _, _ = _units(text, title="던파ON 2.0.19")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "date",
                "value": "2026-06-25",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "던파ON",
                "relation": "2.0.19 버전 적용일",
                "surface": "적용 시점",
                "value_type": "date",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(audit["failure_reasons"], [])

    def test_canonical_effective_at_uses_role_labeled_evidence(self) -> None:
        text = (
            "### 업데이트\n"
            "시즌 11 Act 2. 제국의 파도 ＆ 폭권\n"
            "2026.06.02 15:00\n"
            "6/4(목) 점검 중 업데이트 되는 내용 안내 드립니다."
        )
        chunks, units, documents, temporal = _units(
            text,
            title="시즌 11 Act 2. 제국의 파도 ＆ 폭권",
            published_at="2026-06-02",
        )
        published_ref = _ref_containing(units, "2026.06.02 15:00")
        effective_ref = _ref_containing(
            units,
            "6/4(목) 점검 중 업데이트 되는 내용 안내 드립니다.",
        )
        requirement = {
            "requirement_id": "effective_date",
            "subject": "시즌 11 Act 2. 제국의 파도 ＆ 폭권",
            "relation": "effective_at",
            "value_type": "date",
        }

        wrong, wrong_audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2026-06-02",
                "evidence_refs": [published_ref],
            },
            requirement=requirement,
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )
        right, right_audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2026-06-04",
                "evidence_refs": [effective_ref],
            },
            requirement=requirement,
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )
        prompt, _ = build_typed_evidence_prompt(
            question="업데이트는 언제 적용됐어?",
            requirements=[requirement],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(wrong["status"], "unsupported")
        self.assertIn(
            "temporal_role_mismatch",
            wrong_audit["failure_reasons"],
        )
        self.assertEqual(right["status"], "supported_exact")
        self.assertEqual(right["answer"], "2026년 6월 4일")
        self.assertEqual(right_audit["failure_reasons"], [])
        self.assertIn(
            f"{published_ref}\ttemporal_roles=published_at\t",
            prompt,
        )
        self.assertIn(
            f"{effective_ref}\ttemporal_roles="
            "effective_at,maintenance_time\t",
            prompt,
        )

    def test_event_end_rejects_start_date_from_same_period(self) -> None:
        text = (
            "이벤트 기간: 2026년 7월 2일(목) 점검 후 "
            "~ 2026년 7월 23일(목) 점검 전"
        )
        chunks, units, _, _ = _units(text, title="보급 작전 이벤트")
        evidence_ref = _ref_containing(units, text)
        requirement = {
            "requirement_id": "event_end",
            "subject": "보급 작전 이벤트",
            "relation": "event_end",
            "value_type": "date",
        }

        wrong, wrong_audit = verify_typed_requirement_selection(
            {
                "requirement_id": "event_end",
                "status": "supported",
                "value_type": "date",
                "value": "2026-07-02",
                "evidence_refs": [evidence_ref],
            },
            requirement=requirement,
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )
        right, right_audit = verify_typed_requirement_selection(
            {
                "requirement_id": "event_end",
                "status": "supported",
                "value_type": "date",
                "value": "2026-07-23",
                "evidence_refs": [evidence_ref],
            },
            requirement=requirement,
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(wrong["status"], "unsupported")
        self.assertIn(
            "temporal_role_mismatch",
            wrong_audit["failure_reasons"],
        )
        self.assertEqual(right["status"], "supported_exact")
        self.assertEqual(right["answer"], "2026년 7월 23일")
        self.assertEqual(right_audit["failure_reasons"], [])

    def test_effective_at_uses_adjacent_apply_heading_context(self) -> None:
        text = "▒ 적용 일자\n- 2026년 5월 28일(목)"
        chunks, units, _, _ = _units(
            text,
            title="세라 이용약관 개정 안내",
            published_at="2026-05-20",
        )
        evidence_ref = _ref_containing(units, "- 2026년 5월 28일(목)")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2026-05-28",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "effective_date",
                "subject": "세라 이용약관 개정",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(audit["failure_reasons"], [])

    def test_policy_valid_from_supports_canonical_effective_at(self) -> None:
        text = "### 운영정책\n2026년 03월 15일"
        chunks, documents, temporal = _artifacts(
            text,
            title="던전앤파이터 운영정책",
            published_at="2026-03-15",
        )
        documents["d1"]["source_id"] = "dnf_account_policy"
        temporal["d1"].update(
            {
                "source_kind": "account_policy",
                "valid_from": "2026-03-15",
            }
        )
        unit_rows = build_evidence_units(
            ["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )
        units = {unit["evidence_ref"]: unit for unit in unit_rows}
        evidence_ref = _ref_containing(units, "2026년 03월 15일")

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
                "subject": "던전앤파이터 운영정책",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(audit["failure_reasons"], [])

    def test_revision_cutoff_accepts_labeled_update_baseline(self) -> None:
        text = (
            "- 2026년 5월 28일 기준 라이브 서버 업데이트가 "
            "완료된 직업의 아바타만 포함되어 있습니다."
        )
        chunks, units, _, _ = _units(
            text,
            title="2026 나비 무도회 패키지",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "class_cutoff",
                "status": "supported",
                "value_type": "date",
                "value": "2026-05-28",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "class_cutoff",
                "subject": "2026 나비 무도회 패키지",
                "relation": "revision_cutoff",
                "value_type": "date",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(audit["failure_reasons"], [])

    def test_first_purchase_relation_must_be_in_selected_evidence(self) -> None:
        text = (
            "[EVENT]열대야의 추억 오라 확정 변경권\n"
            "EVENT 첫 구매 혜택! 열대야의 추억 오라 확정 변경권 지급!"
        )
        chunks, units, _, _ = _units(text, title="트로피컬 바캉스 패키지")
        wrong_ref = _ref_containing(
            units, "[EVENT]열대야의 추억 오라 확정 변경권"
        )
        right_ref = _ref_containing(
            units,
            "EVENT 첫 구매 혜택! 열대야의 추억 오라 확정 변경권 지급!",
        )
        requirement = {
            "requirement_id": "r1",
            "subject": "트로피컬 바캉스 패키지",
            "relation": "첫 구매 혜택",
            "surface": "첫 구매 혜택",
            "value_type": "item",
        }
        common = {
            "requirement_id": "r1",
            "status": "supported",
            "value_type": "item",
            "value": "열대야의 추억 오라 확정 변경권",
        }

        wrong, wrong_audit = verify_typed_requirement_selection(
            {**common, "evidence_refs": [wrong_ref]},
            requirement=requirement,
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )
        right, right_audit = verify_typed_requirement_selection(
            {**common, "evidence_refs": [right_ref]},
            requirement=requirement,
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(wrong["status"], "unsupported")
        self.assertIn(
            "relation_not_supported_by_evidence",
            wrong_audit["failure_reasons"],
        )
        self.assertEqual(right["status"], "supported_exact")
        self.assertEqual(right_audit["failure_reasons"], [])

    def test_guild_policy_without_dissolution_relation_is_rejected(self) -> None:
        text = "길드, 지인을 사칭하여 아이템 등을 요구하는 행위"
        chunks, units, _, _ = _units(text, title="던전앤파이터 운영정책")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "violation",
                "value": text,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "길드",
                "relation": "길드 해제 사칭 또는 사기 사유",
                "surface": "사칭·사기 사유",
                "value_type": "violation",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn("relation_not_supported_by_evidence", audit["failure_reasons"])

    def test_safe_evidence_and_text_type_aliases_are_normalized(self) -> None:
        text = "① 특정 개인이나 단체에 대한 비난이나 명예 훼손을 하는 경우"
        chunks, units, _, _ = _units(
            text,
            title="길드는 회사 판단에 따라 해제될 수 있습니다",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "string",
                "value": "특정 개인이나 단체에 대한 비난이나 명예 훼손을 하는 경우",
                "evidence_refs": ["evidence_1"],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "길드",
                "relation": "길드 해제 명예훼손 사유",
                "surface": "명예훼손 사유",
                "value_type": "violation",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(audit["value_type"], "violation")
        self.assertEqual(audit["evidence_refs"], ["E1"])

    def test_list_intro_context_binds_subject_relation_and_percentage(self) -> None:
        text = (
            "해방된 흉몽(챌린지)에 다음 버프가 적용됩니다.\n"
            "- 공격속도 20% 증가"
        )
        chunks, units, _, _ = _units(text, title="개선 및 변경 사항")
        evidence_ref = _ref_containing(units, "- 공격속도 20% 증가")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "percent",
                "value": 20,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "해방된 흉몽(챌린지)",
                "relation": "공격속도 증가",
                "surface": "공격속도 증가치",
                "value_type": "percentage",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "20%")
        self.assertEqual(audit["failure_reasons"], [])
        self.assertEqual(audit["expanded_context_refs"], ["E1"])
        self.assertEqual(
            [citation["text"] for citation in decision["citations"]],
            [
                "해방된 흉몽(챌린지)에 다음 버프가 적용됩니다.",
                "- 공격속도 20% 증가",
            ],
        )

    def test_free_text_answer_is_rendered_from_selected_exact_evidence(self) -> None:
        text = (
            "길드 콘텐츠를 이용한 경우 해당 길드는 해제될 수 있습니다.\n"
            "① 특정 개인이나 단체에 대한 비난이나 명예 훼손을 하는 경우"
        )
        chunks, units, _, _ = _units(text, title="길드 운영정책")
        evidence_ref = _ref_containing(
            units,
            "① 특정 개인이나 단체에 대한 비난이나 명예 훼손을 하는 경우",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "string",
                "value": "an unrelated English paraphrase",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "길드",
                "relation": "길드 해제 명예훼손 사유",
                "surface": "명예훼손 사유",
                "value_type": "violation",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(
            decision["answer"],
            "① 특정 개인이나 단체에 대한 비난이나 명예 훼손을 하는 경우",
        )
        self.assertEqual(audit["answer_value_source"], "selected_exact_evidence")

    def test_boolean_model_value_cannot_override_negative_evidence(self) -> None:
        text = (
            "장비 점수에는 캐릭터 별 스킬 정보가 적용되지 않습니다."
        )
        chunks, units, _, _ = _units(text, title="장비 점수")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "boolean",
                "value": True,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "장비 점수",
                "relation": "캐릭터별 스킬 정보 반영",
                "surface": "캐릭터 스킬 반영 여부",
                "value_type": "boolean",
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

    def test_currency_amount_only_and_extended_units_are_supported(self) -> None:
        self.assertEqual(currency_values("10 골드 코인"), {(10, "골드 코인")})
        self.assertEqual(currency_values("1500 마일리지"), {(1500, "마일리지")})
        self.assertEqual(currency_values("12,900 세라"), {(12900, "세라")})
        self.assertEqual(
            currency_values("광휘의 잔영 120개"),
            {(120, "광휘의 잔영")},
        )
        self.assertTrue(
            _value_supported(
                "currency",
                "12900",
                "가격은 12,900 세라입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertTrue(
            _value_supported(
                "currency",
                22600,
                "가격은 22,600 세라입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertTrue(
            _value_supported(
                "currency",
                "10",
                "가격은 10 골드 코인입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertFalse(
            _value_supported(
                "currency",
                "12900",
                "가격은 99,999 골드입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertFalse(
            _value_supported(
                "currency",
                "10",
                "가격은 10 세라 또는 10 골드입니다.",
                as_of="2026-07-22",
            )
        )

    def test_currency_amount_only_passes_public_verifier(self) -> None:
        text = "트로피컬 바캉스 패키지의 가격은 12,900 세라입니다."
        chunks, units, _, _ = _units(
            text,
            title="트로피컬 바캉스 패키지",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "currency",
                "value": 12900,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "트로피컬 바캉스 패키지",
                "relation": "가격",
                "surface": "가격",
                "value_type": "currency",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "12,900 세라")
        self.assertEqual(audit["failure_reasons"], [])

    def test_boolean_state_noun_passes_public_verifier(self) -> None:
        text = (
            "다른 계정으로 이동하면 해당 아이템은 교환불가 타입으로 변경됩니다."
        )
        chunks, units, _, _ = _units(text, title="아이템 거래 타입")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "boolean",
                "value": True,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "해당 아이템",
                "relation": "교환불가 타입으로 변경",
                "surface": "교환불가 타입으로 변경",
                "value_type": "boolean",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "예")
        self.assertEqual(audit["failure_reasons"], [])

    def test_boolean_opposite_direction_is_blocked_by_public_verifier(self) -> None:
        text = (
            "다른 계정으로 이동해도 해당 아이템은 "
            "교환불가 상태로 변경되지 않습니다."
        )
        chunks, units, _, _ = _units(text, title="아이템 거래 타입")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "boolean",
                "value": True,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "해당 아이템",
                "relation": "교환불가 상태로 변경",
                "surface": "교환불가 상태로 변경",
                "value_type": "boolean",
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

    def test_boolean_evidence_is_directional_and_protects_state_nouns(self) -> None:
        cases = {
            "해당 현상이 수정됩니다.": {True},
            "거래타입 교환가능": {True},
            "다른 계정으로 이동하면 교환불가 타입으로 변경": {True},
            "교환불가 상태로 변경되지 않습니다": {False},
            "연출이 출력되지 않는 현상": {False},
            "결투장에서는 적용되지 않습니다": {False},
            "정지된 이후에도 OTP 이용이 가능합니다": {True},
        }
        for evidence, expected in cases.items():
            with self.subTest(evidence=evidence):
                self.assertEqual(boolean_evidence(evidence), expected)

    def test_boolean_ignores_negative_evidence_for_another_subject_relation(
        self,
    ) -> None:
        positive = "기존 이용 중이신 경우 비밀번호 변경, 재발급이 가능합니다."
        negative = "폐기 시 추가 발급이 가능하지 않은 점 참고 부탁드립니다."
        chunks = {
            "c1": {
                "chunk_id": "c1",
                "parent_document_id": "d1",
                "display_text": positive,
                "default_exposure": True,
                "status": "current",
            },
            "c2": {
                "chunk_id": "c2",
                "parent_document_id": "d2",
                "display_text": negative,
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            "d1": {
                "document_id": "d1",
                "source_id": "dnf_test",
                "title": "[고블린패드] 신규 가입",
                "published_at": "2026-07-01",
                "revision_id": "r1",
                "status": "current",
                "default_exposure": True,
            },
            "d2": {
                "document_id": "d2",
                "source_id": "dnf_test",
                "title": "[고블린패드] 폐기",
                "published_at": "2026-07-01",
                "revision_id": "r2",
                "status": "current",
                "default_exposure": True,
            },
        }
        temporal = {
            document_id: {
                "document_id": document_id,
                "revision_id": document["revision_id"],
                "validity_state": "current",
                "retrieval_action_current": "allow",
            }
            for document_id, document in documents.items()
        }
        unit_rows = build_evidence_units(
            ["c1", "c2"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )
        units = {unit["evidence_ref"]: unit for unit in unit_rows}
        positive_ref = _ref_containing(units, positive)
        negative_ref = _ref_containing(units, negative)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "boolean",
                "value": True,
                "evidence_refs": [positive_ref, negative_ref],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "고블린패드 기존 이용자",
                "relation": "can_reissue",
                "value_type": "boolean",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "예")
        self.assertEqual(
            [citation["evidence_ref"] for citation in decision["citations"]],
            [positive_ref],
        )
        self.assertEqual(audit["failure_reasons"], [])

    def test_boolean_blocks_relation_compatible_conflicting_evidence(self) -> None:
        positive = "기존 이용자는 재발급이 가능합니다."
        negative = "기존 이용자는 재발급이 가능하지 않습니다."
        chunks = {
            "c1": {
                "chunk_id": "c1",
                "parent_document_id": "d1",
                "display_text": positive,
                "default_exposure": True,
                "status": "current",
            },
            "c2": {
                "chunk_id": "c2",
                "parent_document_id": "d2",
                "display_text": negative,
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            document_id: {
                "document_id": document_id,
                "source_id": "dnf_test",
                "title": "[고블린패드] 기존 이용자",
                "published_at": "2026-07-01",
                "revision_id": f"r{index}",
                "status": "current",
                "default_exposure": True,
            }
            for index, document_id in enumerate(("d1", "d2"), 1)
        }
        temporal = {
            document_id: {
                "document_id": document_id,
                "revision_id": document["revision_id"],
                "validity_state": "current",
                "retrieval_action_current": "allow",
            }
            for document_id, document in documents.items()
        }
        unit_rows = build_evidence_units(
            ["c1", "c2"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )
        units = {unit["evidence_ref"]: unit for unit in unit_rows}

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "r1",
                "status": "supported",
                "value_type": "boolean",
                "value": True,
                "evidence_refs": list(units),
            },
            requirement={
                "requirement_id": "r1",
                "subject": "고블린패드 기존 이용자",
                "relation": "can_reissue",
                "value_type": "boolean",
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

    def test_typed_batch_replay_uses_one_call_and_existing_scoring(self) -> None:
        text = "상품 A의 가격은 100 세라이며 거래 타입은 계정귀속입니다."
        chunks_by_id, units, documents_by_id, temporal_by_id = _units(
            text, title="상품 A"
        )
        evidence_ref = _ref_containing(units, text)
        reviewed = {
            "candidate_id": "case1",
            "question_text": "상품 A의 가격과 거래 타입은?",
            "time_scope": "current",
            "requirements": [
                {
                    "requirement_id": "r1",
                    "subject": "상품 A",
                    "relation": "가격",
                    "surface": "가격",
                    "value_type": "price",
                },
                {
                    "requirement_id": "r2",
                    "subject": "상품 A",
                    "relation": "거래 타입",
                    "surface": "거래 타입",
                    "value_type": "trade_type",
                },
            ],
            "evidence_groups": [
                {
                    "group_id": "g1",
                    "acceptable_chunk_ids": ["c1"],
                    "evidence_span": "가격은 100 세라",
                },
                {
                    "group_id": "g2",
                    "acceptable_chunk_ids": ["c1"],
                    "evidence_span": "거래 타입은 계정귀속",
                },
            ],
        }
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }
        calls = []

        def typed_generator(**kwargs):
            calls.append(kwargs["prompt"])
            return {
                "output": {
                    "requirements": [
                        {
                            "requirement_id": "price_value",
                            "status": "supported",
                            "value_type": "price",
                            "value": "100 세라",
                            "evidence_refs": [evidence_ref],
                        },
                        {
                            "requirement_id": "trade_value",
                            "status": "supported",
                            "value_type": "trade_type",
                            "value": "계정귀속",
                            "evidence_refs": [evidence_ref],
                        },
                    ]
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[reviewed],
            baseline_rows=[baseline],
            chunks=list(chunks_by_id.values()),
            documents=list(documents_by_id.values()),
            temporal_rows=list(temporal_by_id.values()),
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            typed_batch_generator=typed_generator,
            split_evidence_schema=True,
            batch_requirements=True,
            typed_evidence_refs=True,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(rows[0]["model_call"]["call_count"], 1)
        self.assertEqual(
            rows[0]["model_call"]["calls"][0]["requirement_id_normalization"],
            "positional_to_fixed",
        )
        self.assertTrue(
            rows[0]["llm_score"]["all_evidence_spans_hit"], rows[0]
        )
        self.assertEqual(rows[0]["verified_output"]["response_mode"], "full_answer")


if __name__ == "__main__":
    unittest.main()
