from __future__ import annotations

import unittest

from src.v3.evaluate_grounded_llm_replay import run_fixed_requirement_replay
from src.v3.typed_evidence_ref import (
    build_evidence_units,
    build_typed_evidence_prompt,
    verify_typed_requirement_selection,
)


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
