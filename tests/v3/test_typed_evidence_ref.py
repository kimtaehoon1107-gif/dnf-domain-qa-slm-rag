from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.v3.evaluate_grounded_llm_replay import run_fixed_requirement_replay
from src.v3.typed_evidence_ref import (
    _local_ollama_request_chars,
    _value_supported,
    assess_parent_relation_semantic_shadow,
    assess_requirement_evidence_sufficiency_shadow,
    build_evidence_units,
    build_typed_evidence_prompt,
    generate_typed_evidence_output,
    parse_typed_requirement_batch,
    resolve_requirement_claim_contract,
    resolve_requirement_claim_contracts,
    select_prompt_evidence_units,
    verify_typed_requirement_selection,
)
from src.v3.value_normalization import (
    boolean_evidence,
    currency_values,
    number_values,
    time_sequence,
    time_values,
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


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class TypedEvidenceRefTest(unittest.TestCase):
    def test_invalid_requirement_is_downgraded_without_losing_valid_sibling(
        self,
    ) -> None:
        parsed, errors = parse_typed_requirement_batch(
            json.dumps(
                {
                    "requirements": [
                        {
                            "requirement_id": "r1",
                            "status": "supported",
                            "value_type": "number",
                            "value": 10,
                            "evidence_refs": ["E1"],
                        },
                        {
                            "requirement_id": "r2",
                            "status": "supported",
                            "value_type": "number",
                            "value": None,
                            "evidence_refs": [],
                        },
                    ]
                }
            )
        )

        self.assertEqual(parsed.requirements[0].status, "supported")
        self.assertEqual(parsed.requirements[1].status, "unsupported")
        self.assertIsNone(parsed.requirements[1].value)
        self.assertEqual(parsed.requirements[1].evidence_refs, [])
        self.assertEqual(errors[0]["requirement_index"], 1)

    def test_local_ollama_uses_think_false_and_bounded_output(self) -> None:
        response = {
            "model": "qwen3-8b:ctx8192",
            "done_reason": "stop",
            "prompt_eval_count": 100,
            "eval_count": 20,
            "message": {
                "content": json.dumps(
                    {
                        "requirements": [
                            {
                                "requirement_id": "r1",
                                "status": "unsupported",
                                "value_type": "number",
                                "value": None,
                                "evidence_refs": [],
                            }
                        ]
                    }
                ),
                "thinking": "",
            },
        }
        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHttpResponse(response)

        with (
            patch.dict(
                "os.environ",
                {
                    "OPENAI_BASE_URL": "http://localhost:11434/v1",
                    "OPENAI_API_KEY": "ollama",
                },
                clear=False,
            ),
            patch("src.v3.typed_evidence_ref.urlopen", fake_urlopen),
        ):
            result = generate_typed_evidence_output(
                prompt="짧은 프롬프트",
                model="qwen3-8b:ctx8192",
                timeout_seconds=3,
            )

        self.assertIs(captured["payload"]["think"], False)
        self.assertEqual(captured["payload"]["options"]["num_predict"], 512)
        self.assertEqual(captured["payload"]["options"]["num_ctx"], 8192)
        self.assertEqual(result["provider"], "ollama_native")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"]["output_tokens"], 20)
        self.assertEqual(result["raw_content"], response["message"]["content"])

    def test_local_ollama_rejects_oversized_prompt_before_request(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_BASE_URL": "http://localhost:11434/v1",
                "OPENAI_API_KEY": "ollama",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "prompt_budget_exceeded",
            ):
                generate_typed_evidence_output(
                    prompt="가" * 20_000,
                    model="qwen3-8b:ctx8192",
                )

    def test_month_identity_conflict_is_rejected(self) -> None:
        text = "특별 아이템은 트로피컬 바캉스 패키지입니다."
        chunks_by_id, units, _, _ = _units(
            text,
            title="7월 이달의 아이템",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "august_item",
                "status": "supported",
                "value_type": "entity",
                "value": "트로피컬 바캉스 패키지",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "august_item",
                "subject": "8월 이달의 아이템",
                "relation": "item_name",
                "value_type": "entity",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "subject_identity_conflict",
            audit["failure_reasons"],
        )

    def test_matching_month_identity_is_allowed(self) -> None:
        text = (
            "8월 이달의 아이템\n"
            "특별 아이템은 트로피컬 바캉스 패키지입니다."
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="8월 이달의 아이템",
        )
        evidence_ref = _ref_containing(
            units,
            "특별 아이템은 트로피컬 바캉스 패키지입니다.",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "august_item",
                "status": "supported",
                "value_type": "entity",
                "value": "트로피컬 바캉스 패키지",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "august_item",
                "subject": "8월 이달의 아이템",
                "relation": "item_name",
                "value_type": "entity",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)

    def test_monthly_value_before_the_month_record_is_rejected(self) -> None:
        text = (
            "# 특별 아이템\n"
            "| 아이템명 | 무기 강화권 상자 |\n"
            "| 상점판매가격 | 2,000만 골드 |\n"
            "* 이 표는 별도의 특별 아이템 정보입니다. "
            "이달의 아이템 목록과는 다른 레코드입니다. "
            "관련 주의사항과 이용 방법을 확인해 주세요.\n"
            "7월 이달의 아이템"
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="7월 이달의 아이템",
        )
        evidence_ref = _ref_containing(
            units,
            "| 상점판매가격 | 2,000만 골드 |",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "shop_price",
                "status": "supported",
                "value_type": "currency",
                "value": "2,000만 골드",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "shop_price",
                "subject": "7월 이달의 아이템",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            question_text="7월 이달의 아이템 상점 판매가는 얼마야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "monthly_record_binding_failed",
            audit["failure_reasons"],
        )

    def test_monthly_value_after_the_month_record_is_allowed(self) -> None:
        text = (
            "### 이달의 아이템\n"
            "[7월]스페셜 클론 레어 아바타 풀세트 상자\n"
            "상점판매가\n"
            "4,000만 골드"
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="이달의 아이템",
        )
        evidence_ref = _ref_containing(units, "4,000만 골드")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "shop_price",
                "status": "supported",
                "value_type": "currency",
                "value": "4,000만 골드",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "shop_price",
                "subject": "7월 이달의 아이템",
                "relation": "shop_price",
                "value_type": "currency",
            },
            question_time_scope="current",
            question_text="7월 이달의 아이템 상점 판매가는 얼마야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)

    def test_monthly_sale_period_can_precede_the_month_item_label(self) -> None:
        text = (
            "### 이달의 아이템\n"
            "판매기간: 06.25 ~ 07.30\n"
            "[7월]스페셜 클론 레어 아바타 풀세트 상자"
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="이달의 아이템",
        )
        evidence_ref = _ref_containing(
            units,
            "판매기간: 06.25 ~ 07.30",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "sale_period",
                "status": "supported",
                "value_type": "date_range",
                "value": "2026-06-25/2026-07-30",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "sale_period",
                "subject": "7월 이달의 아이템",
                "relation": "sale_period",
                "value_type": "date_range",
            },
            question_time_scope="current",
            question_text="7월 이달의 아이템 판매 기간은 언제야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)

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

    def test_typed_prompt_exposes_only_minimum_claim_spec_fields(self) -> None:
        chunks, documents, temporal = _artifacts(
            "업데이트는 2026년 6월 4일 적용됩니다.",
            title="업데이트 안내",
        )

        prompt, _ = build_typed_evidence_prompt(
            question="업데이트는 언제 적용됐어?",
            requirements=[
                {
                    "requirement_id": "effective_at",
                    "subject": "업데이트",
                    "subject_group": "업데이트 일정",
                    "relation": "effective_at",
                    "surface": "적용 시점",
                    "relation_surface": "적용일",
                    "value_type": "date",
                    "temporal_role": "effective_at",
                    "cardinality": "single",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        public_requirements = prompt.split(
            "고정 요구사항 목록:\n", 1
        )[1].split("\n\n후보 evidence units", 1)[0]
        self.assertEqual(
            json.loads(public_requirements),
            [
                {
                    "requirement_id": "effective_at",
                    "subject": "업데이트",
                    "relation": "effective_at",
                    "value_type": "date",
                }
            ],
        )

    def test_typed_prompt_keeps_only_non_default_claim_constraints(self) -> None:
        chunks, documents, temporal = _artifacts(
            "5주차 보상 장소는 상점과 우편함입니다.",
            title="5주차 보상 안내",
        )

        prompt, _ = build_typed_evidence_prompt(
            question="5주차 보상 장소 두 곳을 모두 알려줘.",
            requirements=[
                {
                    "requirement_id": "reward_locations",
                    "subject": "5주차 보상",
                    "relation": "usable_locations",
                    "value_type": "entity_list",
                    "qualifiers": {"week_index": 5},
                    "cardinality": "all",
                    "expected_count": 2,
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        public_requirements = prompt.split(
            "고정 요구사항 목록:\n", 1
        )[1].split("\n\n후보 evidence units", 1)[0]
        self.assertEqual(
            json.loads(public_requirements),
            [
                {
                    "requirement_id": "reward_locations",
                    "subject": "5주차 보상",
                    "relation": "usable_locations",
                    "value_type": "entity_list",
                    "qualifiers": {"week_index": 5},
                    "cardinality": "all",
                    "expected_count": 2,
                }
            ],
        )

    def test_policy_prompt_binds_the_requested_policy_identity_before_generation(
        self,
    ) -> None:
        chunks = {
            "sera": {
                "chunk_id": "sera",
                "parent_document_id": "sera_doc",
                "display_text": (
                    "### 공지사항\n"
                    "세라 이용약관 개정 안내\n"
                    "▒ 적용 일자\n"
                    "- 2026년 5월 28일(목)"
                ),
                "default_exposure": True,
                "status": "current",
            },
            "mobile": {
                "chunk_id": "mobile",
                "parent_document_id": "mobile_doc",
                "display_text": (
                    "### 공지사항\n"
                    "운영정책, 모바일 이용약관 개정 안내\n"
                    "▒ 적용 일자\n"
                    "- 2026년 3월 15일\n"
                    "던전앤파이터 세라이용약관을 참고할 수 있습니다."
                ),
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            "sera_doc": {
                "document_id": "sera_doc",
                "source_id": "dnf_notice",
                "title": "세라 이용약관 개정 안내",
                "published_at": "2026-04-23",
                "revision_id": "sera_revision",
                "status": "current",
                "default_exposure": True,
            },
            "mobile_doc": {
                "document_id": "mobile_doc",
                "source_id": "dnf_notice",
                "title": "운영정책, 모바일 이용약관 개정 안내",
                "published_at": "2026-02-13",
                "revision_id": "mobile_revision",
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

        prompt, visible_units = build_typed_evidence_prompt(
            question="2026년 세라 이용약관 개정안은 언제부터 적용돼?",
            requirements=[
                {
                    "requirement_id": "effective_date",
                    "subject": "세라 이용약관 개정안",
                    "relation": "effective_at",
                    "value_type": "date",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["sera", "mobile"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("2026년 5월 28일", prompt)
        self.assertNotIn("2026년 3월 15일", prompt)
        self.assertEqual(
            {unit["chunk_id"] for unit in visible_units.values()},
            {"sera"},
        )

    def test_policy_prompt_binds_the_explicit_historical_year_before_generation(
        self,
    ) -> None:
        chunks = {
            "historical": {
                "chunk_id": "historical",
                "parent_document_id": "historical_doc",
                "display_text": (
                    "### 공지사항\n"
                    "던전앤파이터 운영정책 변경 안내\n"
                    "2025년 11월 1일 자로 변경이 예정되어 안내 드립니다."
                ),
                "default_exposure": True,
                "status": "current",
            },
            "current": {
                "chunk_id": "current",
                "parent_document_id": "current_doc",
                "display_text": (
                    "### 운영정책\n"
                    "시행일자\n"
                    "2026년 03월 15일\n"
                    "2025년 11월 01일"
                ),
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            "historical_doc": {
                "document_id": "historical_doc",
                "source_id": "dnf_notice",
                "title": "던전앤파이터 운영정책 변경 안내",
                "published_at": "2025-10-02",
                "revision_id": "historical_revision",
                "status": "current",
                "default_exposure": True,
            },
            "current_doc": {
                "document_id": "current_doc",
                "source_id": "dnf_account_policy",
                "source_kind": "account_policy",
                "title": "던전앤파이터 운영정책 (2026-03-15 시행)",
                "published_at": "2026-03-15",
                "valid_from": "2026-03-15",
                "revision_id": "current_revision",
                "status": "current",
                "default_exposure": True,
            },
        }
        temporal = {
            "historical_doc": {
                "document_id": "historical_doc",
                "revision_id": "historical_revision",
                "validity_state": "current",
                "retrieval_action_current": "allow",
            },
            "current_doc": {
                "document_id": "current_doc",
                "revision_id": "current_revision",
                "source_kind": "account_policy",
                "valid_from": "2026-03-15",
                "validity_state": "current",
                "retrieval_action_current": "allow",
            },
        }

        prompt, visible_units = build_typed_evidence_prompt(
            question=(
                "2025년에 공지된 던전앤파이터 운영정책 변경은 "
                "언제 시행될 예정이었어?"
            ),
            requirements=[
                {
                    "requirement_id": "policy_effective_date",
                    "subject": "던전앤파이터 운영정책 변경",
                    "relation": "effective_at",
                    "value_type": "date",
                }
            ],
            question_time_scope="historical",
            as_of="2026-07-22",
            candidate_chunk_ids=["historical", "current"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("2025년 11월 1일 자로 변경", prompt)
        self.assertNotIn("2026년 03월 15일", prompt)
        self.assertEqual(
            {unit["chunk_id"] for unit in visible_units.values()},
            {"historical"},
        )

    def test_policy_prompt_accepts_effective_year_from_body(
        self,
    ) -> None:
        chunks = {
            "correct": {
                "chunk_id": "correct",
                "parent_document_id": "correct_doc",
                "display_text": (
                    "세라 이용약관 변경 안내\n"
                    "개정 약관은 2026년 1월 2일부터 시행됩니다."
                ),
                "default_exposure": True,
                "status": "current",
            },
            "sibling": {
                "chunk_id": "sibling",
                "parent_document_id": "sibling_doc",
                "display_text": (
                    "세라 이용약관 변경 안내\n"
                    "개정 약관은 2025년 12월 2일부터 시행됩니다."
                ),
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            "correct_doc": {
                "document_id": "correct_doc",
                "source_id": "dnf_notice",
                "title": "세라 이용약관 변경 안내",
                "published_at": "2025-12-20",
                "revision_id": "correct_revision",
                "status": "current",
                "default_exposure": True,
            },
            "sibling_doc": {
                "document_id": "sibling_doc",
                "source_id": "dnf_notice",
                "title": "세라 이용약관 변경 안내",
                "published_at": "2025-11-20",
                "revision_id": "sibling_revision",
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

        prompt, visible_units = build_typed_evidence_prompt(
            question="2026년 세라 이용약관은 언제부터 시행돼?",
            requirements=[
                {
                    "requirement_id": "effective_date",
                    "subject": "세라 이용약관",
                    "relation": "effective_at",
                    "value_type": "date",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["correct", "sibling"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("2026년 1월 2일부터 시행", prompt)
        self.assertNotIn("2025년 12월 2일부터 시행", prompt)
        self.assertEqual(
            {unit["chunk_id"] for unit in visible_units.values()},
            {"correct"},
        )

    def test_monthly_prompt_does_not_leak_previous_month_record(
        self,
    ) -> None:
        text = (
            "# [6월 이달의 아이템]\n"
            "상점판매가\n"
            "3,000만 골드\n"
            "# [7월 이달의 아이템]\n"
            "상점판매가\n"
            "4,000만 골드"
        )
        chunks, documents, temporal = _artifacts(
            text,
            title="이달의 아이템",
        )
        documents["d1"]["source_id"] = "dnf_monthly_item"

        prompt, visible_units = build_typed_evidence_prompt(
            question="7월 이달의 아이템 상점 판매가는 얼마야?",
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
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("4,000만 골드", prompt)
        self.assertNotIn("3,000만 골드", prompt)
        self.assertNotIn(
            "3,000만 골드",
            "\n".join(unit["text"] for unit in visible_units.values()),
        )

    def test_monthly_prompt_keeps_shared_preamble_for_first_record(
        self,
    ) -> None:
        text = (
            "### 이달의 아이템\n"
            "판매기간: 06.25 ~ 07.30\n"
            "# [7월 이달의 아이템]\n"
            "상점판매가\n"
            "4,000만 골드"
        )
        chunks, documents, temporal = _artifacts(
            text,
            title="이달의 아이템",
        )
        documents["d1"]["source_id"] = "dnf_monthly_item"

        prompt, visible_units = build_typed_evidence_prompt(
            question="7월 이달의 아이템 판매 기간은 언제야?",
            requirements=[
                {
                    "requirement_id": "sale_period",
                    "subject": "7월 이달의 아이템",
                    "relation": "sale_period",
                    "temporal_role": "sale_period",
                    "value_type": "date_range",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        visible_text = "\n".join(
            unit["text"] for unit in visible_units.values()
        )
        self.assertIn("판매기간: 06.25 ~ 07.30", prompt)
        self.assertIn("판매기간: 06.25 ~ 07.30", visible_text)

    def test_monthly_prompt_keeps_only_the_requested_month_record(
        self,
    ) -> None:
        chunks = {
            "monthly": {
                "chunk_id": "monthly",
                "parent_document_id": "monthly_doc",
                "display_text": (
                    "### 이달의 아이템\n"
                    "판매기간: 06.25 ~ 07.30\n"
                    "# [7월 이달의 아이템] : "
                    "[7월]스페셜 클론 레어 아바타 풀세트 상자\n"
                    "사용 시 [7월]클론 레어 아바타 상자를 획득합니다.\n"
                    "상점판매가\n"
                    "4,000만 골드\n"
                    "거래타입\n"
                    "교환가능\n"
                    "삭제기일\n"
                    "2026년 08월 13일 06시 일괄삭제"
                ),
                "default_exposure": True,
                "status": "current",
            },
            "sibling": {
                "chunk_id": "sibling",
                "parent_document_id": "sibling_doc",
                "display_text": (
                    "# 특별 아이템\n"
                    "| 아이템명 | 무기 강화권 상자 |\n"
                    "| 상점판매가격 | 2,000만 골드 |\n"
                    "| 거래타입 | 교환가능 |\n"
                    "7월 이달의 아이템"
                ),
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            "monthly_doc": {
                "document_id": "monthly_doc",
                "source_id": "dnf_monthly_item",
                "title": "이달의 아이템",
                "published_at": "2026-06-25",
                "revision_id": "monthly_revision",
                "status": "current",
                "default_exposure": True,
            },
            "sibling_doc": {
                "document_id": "sibling_doc",
                "source_id": "dnf_seria_shop",
                "title": "7월 이달의 아이템",
                "published_at": "2026-06-25",
                "revision_id": "sibling_revision",
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

        prompt, visible_units = build_typed_evidence_prompt(
            question=(
                "7월 이달의 아이템의 상점 판매가, 거래 타입, 삭제 시각은 "
                "각각 얼마, 무엇, 언제야?"
            ),
            requirements=[
                {
                    "requirement_id": "shop_price",
                    "subject": "7월 이달의 아이템",
                    "relation": "shop_price",
                    "value_type": "currency",
                },
                {
                    "requirement_id": "trade_type",
                    "subject": "7월 이달의 아이템",
                    "relation": "trade_type",
                    "value_type": "enum",
                },
                {
                    "requirement_id": "deletion_at",
                    "subject": "7월 이달의 아이템",
                    "relation": "deletion_at",
                    "value_type": "datetime",
                },
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["monthly", "sibling"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("4,000만 골드", prompt)
        self.assertIn("2026년 08월 13일 06시", prompt)
        self.assertIn("[7월]스페셜 클론 레어 아바타", prompt)
        self.assertIn(
            "거래타입\n교환가능",
            [unit["text"] for unit in visible_units.values()],
        )
        self.assertNotIn("2,000만 골드", prompt)
        self.assertEqual(
            {unit["source_id"] for unit in visible_units.values()},
            {"dnf_monthly_item"},
        )
        trade_ref = next(
            evidence_ref
            for evidence_ref, unit in visible_units.items()
            if unit["text"] == "거래타입\n교환가능"
        )
        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "trade_type",
                "status": "supported",
                "value_type": "enum",
                "value": "교환가능",
                "evidence_refs": [trade_ref],
            },
            requirement={
                "requirement_id": "trade_type",
                "subject": "7월 이달의 아이템",
                "relation": "trade_type",
                "value_type": "enum",
            },
            question_time_scope="current",
            question_text="7월 이달의 아이템 거래 타입은 뭐야?",
            evidence_units_by_ref=visible_units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )
        self.assertEqual(decision["status"], "supported_exact", audit)
        self.assertEqual(decision["answer"], "교환가능")

    def test_large_policy_prompt_keeps_relevant_late_units_within_budget(
        self,
    ) -> None:
        irrelevant = "\n".join(
            f"관계없는 정책 조항 {index}" for index in range(100)
        )
        text = (
            "### 운영정책\n"
            f"{irrelevant}\n"
            "시행일자\n"
            "2026년 03월 15일"
        )
        chunks, documents, temporal = _artifacts(
            text,
            title="던전앤파이터 운영정책 (2026-03-15 시행)",
        )
        documents["d1"]["source_id"] = "dnf_account_policy"
        temporal["d1"].update(
            {
                "source_kind": "account_policy",
                "valid_from": "2026-03-15",
            }
        )
        requirement = {
            "requirement_id": "effective_date",
            "subject": "던전앤파이터 운영정책",
            "relation": "effective_at",
            "value_type": "date",
        }
        all_units = build_evidence_units(
            ["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        prompt, visible_units = build_typed_evidence_prompt(
            question="현재 던전앤파이터 운영정책은 언제부터 시행됐어?",
            requirements=[requirement],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertLess(len(visible_units), len(all_units))
        self.assertLessEqual(len(visible_units), 8)
        self.assertIn("시행일자", prompt)
        self.assertIn("2026년 03월 15일", prompt)
        self.assertIn("normalized_dates=2026-03-15", prompt)
        self.assertLessEqual(_local_ollama_request_chars(prompt), 12_000)
        for unit in visible_units.values():
            self.assertEqual(
                text[unit["start_char"] : unit["end_char"]],
                unit["text"],
            )

    def test_prompt_selection_drops_weaker_duplicate_period_candidate(
        self,
    ) -> None:
        common = {
            "parent_document_id": "d1",
            "source_id": "dnf_test",
            "source_kind": None,
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "context_text": "",
            "context_refs": [],
        }
        units = [
            {
                **common,
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "title": "이달의 아이템",
                "start_char": 0,
                "end_char": 23,
                "text": "판매기간: 06.25 ~ 07.30",
            },
            {
                **common,
                "evidence_ref": "E2",
                "candidate_ref": "2",
                "chunk_id": "c2",
                "title": "트로피컬 바캉스 패키지",
                "start_char": 0,
                "end_char": 10,
                "text": "7월 이달의 아이템",
            },
            {
                **common,
                "evidence_ref": "E3",
                "candidate_ref": "2",
                "chunk_id": "c2",
                "title": "트로피컬 바캉스 패키지",
                "start_char": 11,
                "end_char": 34,
                "text": "2026.06.25 ~ 2026.07.30",
            },
        ]

        selected = select_prompt_evidence_units(
            units,
            requirements=[
                {
                    "requirement_id": "sale_period",
                    "subject": "7월 이달의 아이템",
                    "relation": "sale_period",
                    "value_type": "date_range",
                }
            ],
            question="7월 이달의 아이템 판매 기간은 언제야?",
            as_of="2026-07-22",
            maximum_units=2,
        )

        self.assertEqual(
            [unit["evidence_ref"] for unit in selected],
            ["E1"],
        )

    def test_prompt_selection_reserves_evidence_for_each_requirement(
        self,
    ) -> None:
        common = {
            "parent_document_id": "d1",
            "source_id": "dnf_notice",
            "source_kind": "notice",
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "context_text": "",
            "context_refs": [],
            "title": "브라우저 결제 권한 안내",
        }
        units = [
            {
                **common,
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "start_char": 0,
                "end_char": 10,
                "text": "안내 문서 제목",
            },
            {
                **common,
                "evidence_ref": "E2",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "start_char": 11,
                "end_char": 35,
                "text": "로컬 네트워크 변경으로 ISP 결제가 불가능합니다.",
            },
            {
                **common,
                "evidence_ref": "E3",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "start_char": 36,
                "end_char": 62,
                "text": "권한 알림이 표시되면 로컬 네트워크 접근을 허용합니다.",
            },
            {
                **common,
                "evidence_ref": "E4",
                "candidate_ref": "2",
                "chunk_id": "c2",
                "start_char": 0,
                "end_char": 15,
                "text": "관련 없는 브라우저 설정",
            },
        ]

        selected = select_prompt_evidence_units(
            units,
            requirements=[
                {
                    "requirement_id": "payment_impact",
                    "subject": "ISP 결제 영향",
                    "relation": "payment_impact",
                    "value_type": "text",
                },
                {
                    "requirement_id": "permission_action",
                    "subject": "로컬 네트워크 권한 알림",
                    "relation": "recommended_action",
                    "value_type": "enum",
                },
            ],
            question=(
                "ISP 결제에 어떤 영향이 있고 권한 알림이 뜨면 "
                "어떻게 해야 해?"
            ),
            as_of="2026-07-22",
            maximum_units=3,
        )

        selected_refs = {unit["evidence_ref"] for unit in selected}
        self.assertIn("E2", selected_refs)
        self.assertIn("E3", selected_refs)

    def test_prompt_selection_prefers_notice_method_over_change_schedule(
        self,
    ) -> None:
        common = {
            "parent_document_id": "d1",
            "source_id": "dnf_account_policy",
            "source_kind": "account_policy",
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "context_text": "",
            "context_refs": [],
            "title": "던전앤파이터 운영정책",
        }
        units = [
            {
                **common,
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "start_char": 0,
                "end_char": 24,
                "text": "운영정책이 11월 1일 자로 변경될 예정입니다.",
            },
            {
                **common,
                "evidence_ref": "E2",
                "candidate_ref": "2",
                "chunk_id": "c2",
                "start_char": 0,
                "end_char": 36,
                "text": "운영정책 변경 시 홈페이지 공지를 통해 알려드립니다.",
            },
        ]

        selected = select_prompt_evidence_units(
            units,
            requirements=[
                {
                    "requirement_id": "change_notice_method",
                    "subject": "던전앤파이터 운영정책",
                    "relation": "change_notice_method",
                    "value_type": "text",
                }
            ],
            question="운영정책이 변경될 때 어떤 방식으로 알려줘?",
            as_of="2026-07-22",
            maximum_units=1,
        )

        self.assertEqual(
            [unit["evidence_ref"] for unit in selected],
            ["E2"],
        )

    def test_relation_semantic_selector_prefers_relation_and_value_unit(
        self,
    ) -> None:
        common = {
            "parent_document_id": "d1",
            "source_id": "dnf_notice",
            "source_kind": "notice",
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "context_text": "",
            "context_refs": [],
        }
        units = [
            {
                **common,
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "title": "4/2(목) 정기점검 안내",
                "start_char": 0,
                "end_char": 17,
                "text": "| 시간 | 04:30 ~ 10:00 |",
            },
            {
                **common,
                "evidence_ref": "E2",
                "candidate_ref": "2",
                "chunk_id": "c2",
                "title": "일반 안내",
                "start_char": 0,
                "end_char": 32,
                "text": (
                    "2026년 4월 2일 정기점검은 몇 시부터 "
                    "몇 시까지였는지 안내합니다."
                ),
            },
        ]
        requirement = {
            "requirement_id": "maintenance_time",
            "subject": "2026년 4월 2일 정기점검",
            "relation": "maintenance_time",
            "value_type": "time_range",
        }

        baseline = select_prompt_evidence_units(
            units,
            requirements=[requirement],
            question="2026년 4월 2일 정기점검은 몇 시부터 몇 시까지였어?",
            as_of="2026-07-22",
            maximum_units=1,
        )
        semantic = select_prompt_evidence_units(
            units,
            requirements=[requirement],
            question="2026년 4월 2일 정기점검은 몇 시부터 몇 시까지였어?",
            as_of="2026-07-22",
            maximum_units=1,
            selector_mode="relation_semantic",
        )

        self.assertEqual(
            [unit["evidence_ref"] for unit in baseline],
            ["E2"],
        )
        self.assertEqual(
            [unit["evidence_ref"] for unit in semantic],
            ["E1"],
        )

    def test_prompt_selector_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "unknown evidence selector mode",
        ):
            select_prompt_evidence_units(
                [],
                requirements=[],
                question="질문",
                as_of="2026-07-22",
                selector_mode="unknown",
            )

    def test_relation_semantic_duration_ignores_clause_numbers(self) -> None:
        common = {
            "parent_document_id": "d1",
            "source_id": "dnf_faq",
            "source_kind": "faq",
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "context_text": "",
            "context_refs": [],
            "title": "[게임이용제한] 이용 제한 해제",
        }
        units = [
            {
                **common,
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "c1",
                "start_char": 0,
                "end_char": 28,
                "text": "[1-3] 일반적인 통념에 기초해 처리됩니다.",
            },
            {
                **common,
                "evidence_ref": "E2",
                "candidate_ref": "2",
                "chunk_id": "c2",
                "start_char": 0,
                "end_char": 35,
                "text": "유형에 따라 3~5일 정도 소요될 수 있습니다.",
            },
        ]

        selected = select_prompt_evidence_units(
            units,
            requirements=[
                {
                    "requirement_id": "processing_days",
                    "subject": "게임 이용제한 이의신청",
                    "relation": "processing_days",
                    "value_type": "number",
                }
            ],
            question="게임 이용제한 이의신청 처리 기한은 며칠이야?",
            as_of="2026-07-22",
            maximum_units=1,
            selector_mode="relation_semantic",
        )

        self.assertEqual(
            [unit["evidence_ref"] for unit in selected],
            ["E2"],
        )

    def test_sufficiency_shadow_requires_one_complete_evidence_group(
        self,
    ) -> None:
        text = (
            "### 이달의 아이템\n"
            "[7월]스페셜 클론 레어 아바타 풀세트 상자\n"
            "상점판매가\n"
            "4,000만 골드"
        )
        _, units, _, _ = _units(text, title="이달의 아이템")

        result = assess_requirement_evidence_sufficiency_shadow(
            {
                "requirement_id": "shop_price",
                "subject": "7월 이달의 아이템",
                "relation": "shop_price",
                "value_type": "currency",
            },
            evidence_units_by_ref=units,
            as_of="2026-07-22",
        )

        self.assertTrue(result["assessable"])
        self.assertFalse(result["would_trigger"])
        self.assertTrue(result["supporting_group_refs"])

    def test_sufficiency_shadow_excludes_unregistered_relations(self) -> None:
        _, units, _, _ = _units(
            "세리아방의 NPC 세리아",
            title="세리아의 특별 상점",
        )

        result = assess_requirement_evidence_sufficiency_shadow(
            {
                "requirement_id": "location",
                "subject": "세리아의 특별 상점",
                "relation": "location",
                "value_type": "text",
            },
            evidence_units_by_ref=units,
            as_of="2026-07-22",
        )

        self.assertFalse(result["assessable"])
        self.assertFalse(result["would_trigger"])
        self.assertEqual(result["reason"], "unregistered_relation_excluded")

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

    def test_policy_subject_identity_mismatch_is_rejected(self) -> None:
        text = "▒ 적용 일자\n- 2026년 3월 15일"
        chunks, units, _, _ = _units(
            text,
            title="운영정책, 모바일 이용약관 개정 안내",
        )
        evidence_ref = _ref_containing(units, "- 2026년 3월 15일")

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
                "subject": "세라 이용약관 개정안",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="current",
            question_text="2026년 세라 이용약관 개정안은 언제 적용돼?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "policy_subject_identity_mismatch",
            audit["failure_reasons"],
        )

    def test_policy_question_year_mismatch_is_rejected(self) -> None:
        text = "### 운영정책\n시행일자\n2026년 03월 15일"
        chunks, documents, temporal = _artifacts(
            text,
            title="던전앤파이터 운영정책 (2026-03-15 시행)",
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
                "subject": "던전앤파이터 운영정책 변경",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="historical",
            question_text=(
                "2025년에 공지된 던전앤파이터 운영정책 변경은 "
                "언제 시행될 예정이었어?"
            ),
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "policy_question_year_mismatch",
            audit["failure_reasons"],
        )

    def test_current_policy_rejects_a_non_active_revision_date(self) -> None:
        text = (
            "### 운영정책\n"
            "시행일자\n"
            "2026년 03월 15일\n"
            "2025년 11월 01일"
        )
        chunks, documents, temporal = _artifacts(
            text,
            title="던전앤파이터 운영정책 (2026-03-15 시행)",
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
        evidence_ref = _ref_containing(units, "2025년 11월 01일")

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "effective_date",
                "status": "supported",
                "value_type": "date",
                "value": "2025-11-01",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "effective_date",
                "subject": "던전앤파이터 운영정책",
                "relation": "effective_at",
                "value_type": "date",
            },
            question_time_scope="current",
            question_text="현재 운영정책은 언제부터 시행됐어?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "policy_revision_effective_date_mismatch",
            audit["failure_reasons"],
        )

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

    def test_free_text_rejects_value_not_supported_by_selected_evidence(
        self,
    ) -> None:
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

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "typed_value_not_supported_by_evidence",
            audit["failure_reasons"],
        )

    def test_free_text_preserves_grounded_typed_value(self) -> None:
        text = (
            "이용제한 이의 제기의 접수 채널은 고객센터입니다."
        )
        chunks, units, _, _ = _units(text, title="이용제한 안내")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "appeal_channel",
                "status": "supported",
                "value_type": "text",
                "value": "고객센터",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "appeal_channel",
                "subject": "이용제한 이의 제기",
                "relation": "접수 채널",
                "surface": "접수 채널",
                "value_type": "text",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "고객센터")
        self.assertEqual(audit["answer_value_source"], "model_typed_value")

    def test_shared_time_and_number_normalization(self) -> None:
        self.assertEqual(time_values("매일 오전 6시"), {"06:00"})
        self.assertEqual(
            time_sequence("04:30 ~ 10:00"),
            ["04:30", "10:00"],
        )
        self.assertEqual(number_values("4,000"), {4000.0})
        self.assertEqual(
            number_values("2026년 4월 2일 04:30"),
            set(),
        )
        self.assertEqual(number_values("4/2 정기점검"), set())
        self.assertEqual(number_values("4.2 정기점검"), set())
        self.assertEqual(
            number_values("판매기간 6.25 ~ 7.30"),
            set(),
        )
        self.assertEqual(number_values("계정당 4회"), {4.0})
        self.assertEqual(number_values("가격은 4,000만 골드"), set())
        self.assertTrue(
            _value_supported(
                "enum",
                "06:00",
                "매일 06시에 초기화됩니다.",
                as_of="2026-07-22",
            )
        )
        self.assertFalse(
            _value_supported(
                "number",
                4,
                "구매 횟수 기준은 2026년 4월 2일 공지입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertFalse(
            _value_supported(
                "entity",
                "매일 06:00 갱신",
                "삭제 시각은 06시입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertTrue(
            _value_supported(
                "time_range",
                "04:30/10:00",
                "점검 시간은 04:30 ~ 10:00입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertFalse(
            _value_supported(
                "time_range",
                "10:00/04:30",
                "점검 시간은 04:30 ~ 10:00입니다.",
                as_of="2026-07-22",
            )
        )
        self.assertTrue(
            _value_supported(
                "number",
                4000,
                "필요 수량은 4,000개입니다.",
                as_of="2026-07-22",
            )
        )

    def test_entity_list_requires_a_nonempty_string_array(self) -> None:
        text = "무한 올빼미는 마을, 던전에서 사용할 수 있습니다."
        chunks_by_id, units, _, _ = _units(
            text,
            title="무한 올빼미",
        )
        evidence_ref = next(iter(units))

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "usable_locations",
                "status": "supported",
                "value_type": "entity_list",
                "value": "마을, 던전",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "usable_locations",
                "subject": "무한 올빼미",
                "relation": "usable_locations",
                "value_type": "entity_list",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "entity_list_value_shape_mismatch",
            audit["failure_reasons"],
        )

    def test_entity_list_repairs_only_a_json_array_string(self) -> None:
        text = "무한 올빼미는 마을, 던전에서 사용할 수 있습니다."
        chunks_by_id, units, _, _ = _units(
            text,
            title="무한 올빼미",
        )
        evidence_ref = next(iter(units))

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "usable_locations",
                "status": "supported",
                "value_type": "entity_list",
                "value": '["마을","던전"]',
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "usable_locations",
                "subject": "무한 올빼미",
                "relation": "usable_locations",
                "value_type": "entity_list",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "마을, 던전")
        self.assertEqual(
            audit["value_shape_repair"],
            "json_array_string",
        )

    def test_entity_list_expected_count_is_enforced(self) -> None:
        text = "무한 올빼미는 마을, 던전에서 사용할 수 있습니다."
        chunks_by_id, units, _, _ = _units(
            text,
            title="무한 올빼미",
        )
        evidence_ref = next(iter(units))

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "usable_locations",
                "status": "supported",
                "value_type": "entity_list",
                "value": ["던전"],
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "usable_locations",
                "subject": "무한 올빼미",
                "relation": "usable_locations",
                "value_type": "entity_list",
                "cardinality": "all",
                "expected_count": 2,
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "cardinality_count_mismatch",
            audit["failure_reasons"],
        )
        self.assertEqual(
            audit["cardinality_validation_state"],
            "count_mismatch",
        )

    def test_cardinality_all_without_closure_fails_closed(
        self,
    ) -> None:
        text = "무한 올빼미는 마을, 던전에서 사용할 수 있습니다."
        chunks_by_id, units, _, _ = _units(
            text,
            title="무한 올빼미",
        )
        evidence_ref = next(iter(units))
        output = {
            "requirement_id": "usable_locations",
            "status": "supported",
            "value_type": "entity_list",
            "value": ["마을", "던전"],
            "evidence_refs": [evidence_ref],
        }
        requirement = {
            "requirement_id": "usable_locations",
            "subject": "무한 올빼미",
            "relation": "usable_locations",
            "value_type": "entity_list",
            "cardinality": "all",
        }

        decision, audit = (
            verify_typed_requirement_selection(
                output,
                requirement=requirement,
                question_time_scope="current",
                evidence_units_by_ref=units,
                chunks_by_id=chunks_by_id,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(
            decision["status"],
            "unsupported",
        )
        self.assertEqual(
            audit["cardinality_validation_state"],
            "all_unproven",
        )
        self.assertIn(
            "cardinality_all_unproven",
            audit["failure_reasons"],
        )
        self.assertTrue(
            audit[
                "would_reject_if_cardinality_fail_closed"
            ]
        )

    def test_relation_contract_states_and_shadow_mode(self) -> None:
        text = (
            "게임 이용제한 이의신청의 접수 채널은 "
            "고객센터입니다."
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="게임 이용제한 이의신청",
        )
        evidence_ref = next(iter(units))
        output = {
            "requirement_id": "appeal_channel",
            "status": "supported",
            "value_type": "text",
            "value": "고객센터",
            "evidence_refs": [evidence_ref],
        }
        base_requirement = {
            "requirement_id": "appeal_channel",
            "subject": "게임 이용제한 이의신청",
            "relation": "unknown_appeal_destination",
            "value_type": "text",
        }

        shadow_decision, shadow_audit = (
            verify_typed_requirement_selection(
                output,
                requirement=base_requirement,
                question_time_scope="current",
                evidence_units_by_ref=units,
                chunks_by_id=chunks_by_id,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(
            shadow_decision["status"],
            "supported_exact",
        )
        self.assertEqual(
            shadow_audit["relation_validation_state"],
            "unvalidated",
        )
        self.assertTrue(
            shadow_audit["would_reject_if_relation_fail_closed"]
        )

        strict_decision, strict_audit = (
            verify_typed_requirement_selection(
                output,
                requirement={
                    **base_requirement,
                    "relation_validation_mode": "strict",
                },
                question_time_scope="current",
                evidence_units_by_ref=units,
                chunks_by_id=chunks_by_id,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(strict_decision["status"], "unsupported")
        self.assertIn(
            "relation_unvalidated",
            strict_audit["failure_reasons"],
        )

        surface_decision, surface_audit = (
            verify_typed_requirement_selection(
                output,
                requirement={
                    **base_requirement,
                    "relation_surface": "접수 채널",
                },
                question_time_scope="current",
                evidence_units_by_ref=units,
                chunks_by_id=chunks_by_id,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(
            surface_decision["status"],
            "supported_exact",
        )
        self.assertEqual(
            surface_audit["relation_validation_state"],
            "surface_fallback",
        )

    def test_known_relation_uses_explicit_alias_contract(self) -> None:
        text = "아이템의 거래타입은 교환가능입니다."
        chunks_by_id, units, _, _ = _units(
            text,
            title="아이템",
        )
        evidence_ref = next(iter(units))

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
                "subject": "아이템",
                "relation": "trade_type",
                "value_type": "enum",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(
            audit["relation_validation_state"],
            "explicit_alias",
        )

    def test_colocation_does_not_cross_chunks_in_same_parent(self) -> None:
        chunks = {
            "c1": {
                "chunk_id": "c1",
                "parent_document_id": "d1",
                "display_text": "상품 A 상점 판매가 안내",
                "default_exposure": True,
                "status": "current",
            },
            "c2": {
                "chunk_id": "c2",
                "parent_document_id": "d1",
                "display_text": "다른 상품의 가격은 2,600 세라입니다.",
                "default_exposure": True,
                "status": "current",
            },
        }
        documents = {
            "d1": {
                "document_id": "d1",
                "source_id": "dnf_seria_shop",
                "title": "상품 A 판매 안내",
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
        units = build_evidence_units(
            ["c1", "c2"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )
        units_by_ref = {unit["evidence_ref"]: unit for unit in units}

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "2,600 세라",
                "evidence_refs": [
                    _ref_containing(units_by_ref, "상품 A 상점 판매가 안내"),
                    _ref_containing(
                        units_by_ref,
                        "다른 상품의 가격은 2,600 세라입니다.",
                    ),
                ],
            },
            requirement={
                "requirement_id": "price",
                "subject": "상품 A",
                "relation": "상점 판매가",
                "surface": "상점 판매가",
                "value_type": "currency",
            },
            question_time_scope="current",
            evidence_units_by_ref=units_by_ref,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "subject_relation_value_not_colocated",
            audit["failure_reasons"],
        )

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

    def test_currency_sibling_values_require_a_question_qualifier(
        self,
    ) -> None:
        text = (
            "상의 클론 아바타 가격은 2,600 세라입니다.\n"
            "상의 클론 아바타 가격은 15 골드 코인입니다."
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="상의 클론 아바타",
        )
        gold_coin_ref = _ref_containing(
            units,
            "상의 클론 아바타 가격은 15 골드 코인입니다.",
        )
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
            "relation": "price",
            "value_type": "currency",
        }

        ambiguous_decision, ambiguous_audit = (
            verify_typed_requirement_selection(
                output,
                requirement=requirement,
                question_time_scope="current",
                question_text="상의 클론 아바타 가격은 얼마야?",
                evidence_units_by_ref=units,
                chunks_by_id=chunks_by_id,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(
            ambiguous_decision["status"],
            "unsupported",
        )
        self.assertIn(
            "currency_qualifier_ambiguity_unresolved",
            ambiguous_audit["failure_reasons"],
        )
        self.assertEqual(
            ambiguous_audit["unresolved_currency_values"],
            [{"amount": 2600, "unit": "세라"}],
        )

        qualified_decision, qualified_audit = (
            verify_typed_requirement_selection(
                output,
                requirement=requirement,
                question_time_scope="current",
                question_text=(
                    "상의 클론 아바타의 골드 코인 가격은 얼마야?"
                ),
                evidence_units_by_ref=units,
                chunks_by_id=chunks_by_id,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(
            qualified_decision["status"],
            "supported_exact",
            qualified_audit,
        )

    def test_currency_ambiguity_uses_exact_table_subject_cells(
        self,
    ) -> None:
        text = (
            "| 은 금고 | 40 칸 | 400 세라 |\n"
            "| 세련된 은 금고 | 56 칸 | 800 세라 |"
        )
        chunks_by_id, units, _, _ = _units(
            text,
            title="금고 업그레이드",
        )
        silver_ref = _ref_containing(
            units,
            "| 은 금고 | 40 칸 | 400 세라 |",
        )

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "currency",
                "value": "400 세라",
                "evidence_refs": [silver_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "은 금고",
                "relation": "price",
                "value_type": "currency",
            },
            question_time_scope="current",
            question_text="은 금고의 가격은 얼마야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks_by_id,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)
        self.assertEqual(audit["unresolved_currency_values"], [])

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

    def test_boolean_evidence_supports_plain_and_past_tense_answers(
        self,
    ) -> None:
        cases = {
            "성장 가속 모드 상태에서는 결투장을 이용할 수 없다.": {False},
            "비정상 재화는 고의 여부와 무관하게 회수할 수 있었다.": {True},
            "삭제 기한이 정해져 있지 않았다.": {False},
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
                            "requirement_id": "r1",
                            "status": "supported",
                            "value_type": "price",
                            "value": "100 세라",
                            "evidence_refs": [evidence_ref],
                        },
                        {
                            "requirement_id": "r2",
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
            typed_evidence_selector_mode="relation_semantic",
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(rows[0]["model_call"]["call_count"], 1)
        self.assertEqual(
            rows[0]["typed_evidence_selector_mode"],
            "relation_semantic",
        )
        self.assertNotIn(
            "requirement_id_normalization",
            rows[0]["model_call"]["calls"][0],
        )
        shadow = rows[0]["model_call"]["calls"][0]["sufficiency_shadow"]
        self.assertEqual(
            [row["requirement_id"] for row in shadow],
            ["r1", "r2"],
        )
        self.assertFalse(shadow[0]["assessable"])
        self.assertFalse(shadow[1]["would_trigger"])
        self.assertTrue(
            rows[0]["llm_score"]["all_evidence_spans_hit"], rows[0]
        )
        self.assertEqual(rows[0]["verified_output"]["response_mode"], "full_answer")

    def test_single_explicit_ordinal_is_inferred_without_guessing_ambiguous_ones(
        self,
    ) -> None:
        requirement = {
            "requirement_id": "quantity",
            "subject": "추첨 상품",
            "relation": "수량",
            "value_type": "number",
        }

        resolved, source, consistent = resolve_requirement_claim_contract(
            requirement,
            question_text="5주차 추첨 상품은 몇 개야?",
        )
        self.assertEqual(resolved["qualifiers"], {"week_index": 5})
        self.assertEqual(source, "question_inferred")
        self.assertTrue(consistent)

        for question in (
            "5주 동안 추첨 상품은 몇 개야?",
            "1회차와 7회차 추첨 상품은 각각 몇 개야?",
            "5주차와 5단계 보상은 각각 몇 개야?",
        ):
            with self.subTest(question=question):
                unresolved, unresolved_source, unresolved_consistent = (
                    resolve_requirement_claim_contract(
                        requirement,
                        question_text=question,
                    )
                )
                self.assertNotIn("qualifiers", unresolved)
                self.assertEqual(unresolved_source, "none")
                self.assertTrue(unresolved_consistent)

    def test_question_ordinal_is_visible_in_typed_prompt(self) -> None:
        chunks, documents, temporal = _artifacts(
            "그래픽카드는 4개입니다.",
            title="[5주차] 추첨 당첨자 발표",
        )
        prompt, _ = build_typed_evidence_prompt(
            question="5주차 그래픽카드는 몇 개야?",
            requirements=[
                {
                    "requirement_id": "quantity",
                    "subject": "그래픽카드",
                    "relation": "수량",
                    "value_type": "number",
                }
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn('"qualifiers":{"week_index":5}', prompt)

    def test_same_relation_requirements_share_question_ordinal(self) -> None:
        resolved = resolve_requirement_claim_contracts(
            [
                {
                    "requirement_id": "reward_quantity",
                    "relation": "보상 수량",
                    "value_type": "number",
                },
                {
                    "requirement_id": "bonus_quantity",
                    "relation": "보상 수량",
                    "value_type": "number",
                },
            ],
            question_text="5주차 기본 보상과 추가 보상 수량은 각각 몇 개야?",
        )

        self.assertEqual(
            [requirement["qualifiers"] for requirement in resolved],
            [{"week_index": 5}, {"week_index": 5}],
        )
        for requirement in resolved:
            rerun, source, consistent = resolve_requirement_claim_contract(
                requirement,
                question_text="5주차 기본 보상과 추가 보상 수량은 각각 몇 개야?",
            )
            self.assertEqual(rerun["qualifiers"], {"week_index": 5})
            self.assertEqual(source, "question_inferred")
            self.assertTrue(consistent)

    def test_question_ordinal_does_not_leak_across_mixed_relations(self) -> None:
        resolved = resolve_requirement_claim_contracts(
            [
                {
                    "requirement_id": "reward_quantity",
                    "relation": "보상 수량",
                    "value_type": "number",
                },
                {
                    "requirement_id": "shop_price",
                    "relation": "상점 가격",
                    "value_type": "currency",
                },
            ],
            question_text="5주차 보상 수량과 상점 가격은 얼마야?",
        )

        self.assertNotIn("qualifiers", resolved[0])
        self.assertNotIn("qualifiers", resolved[1])
        rerun, source, consistent = resolve_requirement_claim_contract(
            resolved[1],
            question_text="5주차 보상 수량과 상점 가격은 얼마야?",
        )
        self.assertNotIn("qualifiers", rerun)
        self.assertEqual(source, "none")
        self.assertTrue(consistent)

    def test_explicit_planner_ordinal_remains_in_mixed_relations(self) -> None:
        resolved = resolve_requirement_claim_contracts(
            [
                {
                    "requirement_id": "reward_quantity",
                    "relation": "보상 수량",
                    "value_type": "number",
                    "qualifiers": {"week_index": 5},
                },
                {
                    "requirement_id": "shop_price",
                    "relation": "상점 가격",
                    "value_type": "currency",
                },
            ],
            question_text="5주차 보상 수량과 상점 가격은 얼마야?",
        )

        self.assertEqual(
            resolved[0]["qualifiers"],
            {"week_index": 5},
        )
        self.assertNotIn("qualifiers", resolved[1])
        rerun, source, consistent = resolve_requirement_claim_contract(
            resolved[0],
            question_text="5주차 보상 수량과 상점 가격은 얼마야?",
        )
        self.assertEqual(rerun["qualifiers"], {"week_index": 5})
        self.assertEqual(source, "explicit")
        self.assertTrue(consistent)

    def test_wrong_week_is_rejected_even_when_numeric_value_matches(self) -> None:
        text = "그래픽카드는 4개입니다."
        chunks, units, _, _ = _units(
            text,
            title="[1주차] 추첨 당첨자 발표",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "quantity",
                "status": "supported",
                "value_type": "number",
                "value": 4,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "quantity",
                "subject": "그래픽카드",
                "relation": "수량",
                "value_type": "number",
            },
            question_time_scope="current",
            question_text="5주차 그래픽카드는 몇 개야?",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "qualifier_identity_mismatch",
            audit["failure_reasons"],
        )
        self.assertEqual(audit["resolved_qualifiers"], {"week_index": 5})
        self.assertEqual(
            audit["qualifier_contract_source"],
            "question_inferred",
        )

    def test_matching_week_passes_and_missing_week_is_unproven(self) -> None:
        text = "그래픽카드는 4개입니다."
        requirement = {
            "requirement_id": "quantity",
            "subject": "그래픽카드",
            "relation": "수량",
            "value_type": "number",
        }
        output = {
            "requirement_id": "quantity",
            "status": "supported",
            "value_type": "number",
            "value": 4,
            "evidence_refs": ["E1"],
        }

        matching_chunks, matching_units, _, _ = _units(
            text,
            title="[5주차] 추첨 당첨자 발표",
        )
        matching_output = dict(output)
        matching_output["evidence_refs"] = [
            _ref_containing(matching_units, text)
        ]
        matching_decision, matching_audit = (
            verify_typed_requirement_selection(
                matching_output,
                requirement=requirement,
                question_time_scope="current",
                question_text="5주차 그래픽카드는 몇 개야?",
                evidence_units_by_ref=matching_units,
                chunks_by_id=matching_chunks,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(
            matching_decision["status"],
            "supported_exact",
            matching_audit,
        )
        self.assertEqual(
            matching_audit["qualifier_validation_state"],
            "matched",
        )

        unproven_chunks, unproven_units, _, _ = _units(
            text,
            title="추첨 당첨자 발표",
        )
        unproven_output = dict(output)
        unproven_output["evidence_refs"] = [
            _ref_containing(unproven_units, text)
        ]
        unproven_decision, unproven_audit = (
            verify_typed_requirement_selection(
                unproven_output,
                requirement=requirement,
                question_time_scope="current",
                question_text="5주차 그래픽카드는 몇 개야?",
                evidence_units_by_ref=unproven_units,
                chunks_by_id=unproven_chunks,
                as_of="2026-07-22",
            )
        )
        self.assertEqual(unproven_decision["status"], "unsupported")
        self.assertIn(
            "qualifier_identity_unproven",
            unproven_audit["failure_reasons"],
        )

    def test_relation_family_contract_is_recorded_and_type_checked(
        self,
    ) -> None:
        text = "해당 상품의 가격은 100 세라입니다."
        chunks, units, _, _ = _units(text, title="상품 가격")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "price",
                "status": "supported",
                "value_type": "boolean",
                "value": True,
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "price",
                "subject": "해당 상품",
                "relation": "price",
                "value_type": "boolean",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn(
            "relation_family_value_type_mismatch",
            audit["failure_reasons"],
        )
        self.assertEqual(audit["relation_family"], "price_currency")
        self.assertEqual(audit["parent_relation"], "price")
        self.assertEqual(
            audit["relation_family_validation_state"],
            "type_mismatch",
        )

    def test_parent_relation_shadow_distinguishes_slot_30_relations(
        self,
    ) -> None:
        correct = (
            "115레벨 이상 장비, 융합석을 검색 및 착용이 가능합니다."
        )
        wrong_relation = (
            "110레벨 또는 115레벨 장비를 모두 장착하면 "
            "예상 공격력을 확인할 수 있습니다."
        )
        requirement = {
            "requirement_id": "supported_levels",
            "subject": "장비 시뮬레이터",
            "relation": "searchable_and_equippable_equipment_level",
            "value_type": "entity_list",
        }

        _, correct_units, _, _ = _units(
            correct,
            title="장비 시뮬레이터",
        )
        supported = assess_parent_relation_semantic_shadow(
            requirement,
            evidence_units_by_ref=correct_units,
            as_of="2026-07-22",
        )
        self.assertTrue(supported["assessable"])
        self.assertFalse(supported["would_trigger"])
        self.assertEqual(
            supported["reason"],
            "child_relation_support_found",
        )

        _, wrong_units, _, _ = _units(
            wrong_relation,
            title="장비 시뮬레이터",
        )
        rejected = assess_parent_relation_semantic_shadow(
            requirement,
            evidence_units_by_ref=wrong_units,
            as_of="2026-07-22",
        )
        self.assertTrue(rejected["assessable"])
        self.assertTrue(rejected["would_trigger"])
        self.assertEqual(
            rejected["reason"],
            "child_relation_support_missing",
        )

    def test_parent_relation_shadow_excludes_audit_only_parent(
        self,
    ) -> None:
        _, units, _, _ = _units(
            "회사는 고객센터 공지로 안내합니다.",
            title="운영정책",
        )

        assessment = assess_parent_relation_semantic_shadow(
            {
                "requirement_id": "notice",
                "subject": "운영정책",
                "relation": "notice_method",
                "value_type": "text",
            },
            evidence_units_by_ref=units,
            as_of="2026-07-22",
        )

        self.assertFalse(assessment["assessable"])
        self.assertEqual(
            assessment["reason"],
            "parent_relation_excluded",
        )


if __name__ == "__main__":
    unittest.main()
