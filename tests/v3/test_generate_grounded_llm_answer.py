from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.v3.generate_grounded_llm_answer import (
    GroundedAnswerOutput,
    NonTableRequirementSelectionOutput,
    build_batched_requirement_prompt,
    build_grounded_prompt,
    build_requirement_prompt,
    select_table_rows_for_requirement,
    verify_and_sanitize_output,
    verify_non_table_requirement_selection,
    verify_requirement_selection,
)


def _fixtures() -> tuple[dict, dict, dict]:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": "상품 A의 가격은 100 세라이며 거래 타입은 계정귀속입니다.",
            "default_exposure": True,
            "status": "current",
        },
        "c2": {
            "chunk_id": "c2",
            "parent_document_id": "d2",
            "display_text": "종료된 상품의 가격은 200 세라입니다.",
            "default_exposure": False,
            "status": "expired",
        },
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_shop",
            "title": "상품 A",
            "published_at": "2026-07-01",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
            "valid_from": None,
            "valid_to": None,
        },
        "d2": {
            "document_id": "d2",
            "source_id": "dnf_shop",
            "title": "종료 상품",
            "published_at": "2025-01-01",
            "revision_id": "r2",
            "status": "expired",
            "default_exposure": False,
            "valid_from": None,
            "valid_to": "2025-02-01",
        },
    }
    temporal = {
        "d1": {
            "document_id": "d1",
            "revision_id": "r1",
            "validity_state": "current_unverified",
            "retrieval_action_current": "allow_with_warning",
        },
        "d2": {
            "document_id": "d2",
            "revision_id": "r2",
            "validity_state": "expired",
            "retrieval_action_current": "deny",
        },
    }
    return chunks, documents, temporal


class GroundedLlmAnswerTest(unittest.TestCase):
    def test_fixed_requirement_prompt_excludes_gold_and_filters_table_rows(self) -> None:
        chunks, documents, temporal = _fixtures()
        rows = {
            "c1": [
                {
                    "row_id": "target",
                    "row_text": "상품 A의 가격은 100 세라",
                    "facts": [
                        {"subject": "상품 A", "attribute": "가격", "value": "100 세라"}
                    ],
                },
                {
                    "row_id": "sibling",
                    "row_text": "상품 B의 가격은 200 세라",
                    "facts": [
                        {"subject": "상품 B", "attribute": "가격", "value": "200 세라"}
                    ],
                },
            ]
        }
        requirement = {
            "requirement_id": "r1",
            "subject": "상품 A",
            "relation": "상품 A 가격",
            "surface": "가격",
            "value_type": "price",
        }

        selected = select_table_rows_for_requirement(rows, requirement)
        prompt = build_requirement_prompt(
            question="상품 A의 가격은?",
            requirement={**requirement, "acceptable_evidence_group_ids": ["gold"]},
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
            table_rows_by_chunk=rows,
        )

        self.assertEqual([row["row_id"] for row in selected["c1"]], ["target"])
        self.assertIn('"table_row_ref": "1"', prompt)
        self.assertIn("상품 A의 가격은 100 세라", prompt)
        self.assertNotIn("상품 B의 가격은 200 세라", prompt)
        self.assertNotIn('"row_id": "target"', prompt)
        self.assertNotIn("acceptable_evidence_group_ids", prompt)
        self.assertNotIn("gold", prompt)

    def test_table_row_key_value_can_bind_the_requirement_subject(self) -> None:
        rows = {
            "c1": [
                {
                    "row_id": "target",
                    "row_text": (
                        "| [프리미엄 코인샵]트로피컬 바캉스 무기 아바타 상자 "
                        "| 2개 | 계정당 5회 | 2026년 8월 27일 06시 |"
                    ),
                    "facts": [
                        {
                            "subject": "삭제일자가 존재하는 판매 물품",
                            "attribute": "판매 목록",
                            "value": (
                                "[프리미엄 코인샵]"
                                "트로피컬 바캉스 무기 아바타 상자"
                            ),
                        },
                        {
                            "subject": "삭제일자가 존재하는 판매 물품",
                            "attribute": "삭제일자",
                            "value": "2026년 8월 27일 06시",
                        },
                    ],
                },
                {
                    "row_id": "sibling",
                    "row_text": (
                        "| [프리미엄 코인샵]트로피컬 바캉스 스페셜 모자 "
                        "아바타 상자 | 2개 | 계정당 5회 "
                        "| 2026년 8월 27일 06시 |"
                    ),
                    "facts": [
                        {
                            "subject": "삭제일자가 존재하는 판매 물품",
                            "attribute": "판매 목록",
                            "value": (
                                "[프리미엄 코인샵]"
                                "트로피컬 바캉스 스페셜 모자 아바타 상자"
                            ),
                        },
                        {
                            "subject": "삭제일자가 존재하는 판매 물품",
                            "attribute": "삭제일자",
                            "value": "2026년 8월 27일 06시",
                        },
                    ],
                },
            ]
        }
        requirement = {
            "requirement_id": "deletion_at",
            "subject": (
                "[프리미엄 코인샵]트로피컬 바캉스 무기 아바타 상자"
            ),
            "relation": "deletion_at",
            "value_type": "datetime",
        }

        selected = select_table_rows_for_requirement(rows, requirement)

        self.assertEqual(
            [row["row_id"] for row in selected["c1"]],
            ["target"],
        )

    def test_batched_table_prompt_keeps_requirement_local_row_refs(self) -> None:
        chunks, documents, temporal = _fixtures()
        rows = {
            "c1": [
                {
                    "row_id": "price",
                    "row_text": "상품 A의 가격은 100 세라",
                    "facts": [
                        {"subject": "상품 A", "attribute": "가격", "value": "100 세라"}
                    ],
                },
                {
                    "row_id": "trade",
                    "row_text": "상품 A의 거래 타입은 계정귀속",
                    "facts": [
                        {
                            "subject": "상품 A",
                            "attribute": "거래 타입",
                            "value": "계정귀속",
                        }
                    ],
                },
            ]
        }
        prompt = build_batched_requirement_prompt(
            question="상품 A의 가격과 거래 타입은?",
            requirements=[
                {
                    "requirement_id": "price",
                    "subject": "상품 A",
                    "relation": "가격",
                    "surface": "가격",
                    "value_type": "price",
                },
                {
                    "requirement_id": "trade",
                    "subject": "상품 A",
                    "relation": "거래 타입",
                    "surface": "거래 타입",
                    "value_type": "trade_type",
                },
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
            table_rows_by_chunk=rows,
            include_table_rows=True,
        )

        self.assertEqual(prompt.count('"table_row_ref": "1"'), 2)
        self.assertNotIn('"table_row_ref": "2"', prompt)
        self.assertIn("상품 A의 가격은 100 세라", prompt)
        self.assertIn("상품 A의 거래 타입은 계정귀속", prompt)
        self.assertNotIn(
            "상품 A의 가격은 100 세라이며 거래 타입은 계정귀속입니다.",
            prompt,
        )
        self.assertNotIn('"row_id":', prompt)

    def test_boolean_prompt_requires_an_exact_evidence_phrase_not_false(self) -> None:
        chunks, documents, temporal = _fixtures()
        prompt = build_requirement_prompt(
            question="상품 A에 가격이 반영돼?",
            requirement={
                "requirement_id": "r1",
                "subject": "상품 A",
                "relation": "가격 반영 여부",
                "surface": "가격 반영 여부",
                "value_type": "boolean",
            },
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("answer에 true 또는 false를 쓰지 마세요", prompt)
        self.assertIn("접속어미에서 끊지 마세요", prompt)
        self.assertIn("evidence quote 안에서", prompt)

    def test_prompt_contains_candidates_but_not_gold_fields(self) -> None:
        chunks, documents, temporal = _fixtures()
        prompt = build_grounded_prompt(
            question="상품 A의 가격은?",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn("상품 A의 가격은 100 세라", prompt)
        self.assertNotIn("acceptable_chunk_ids", prompt)
        self.assertNotIn("evidence_span", prompt)
        self.assertNotIn("gold_answer", prompt)

    def test_exact_current_quote_is_exposed(self) -> None:
        chunks, documents, temporal = _fixtures()
        raw = GroundedAnswerOutput.model_validate(
            {
                "question_time_scope": "current",
                "response_mode": "full_answer",
                "requirements": [
                    {
                        "question_part": "가격",
                        "status": "supported",
                        "answer": "100 세라",
                        "evidence": [
                            {"candidate_ref": "1", "quote": "상품 A의 가격은 100 세라"}
                        ],
                    }
                ],
            }
        )

        verified = verify_and_sanitize_output(
            raw,
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(verified["response_mode"], "full_answer")
        citation = verified["requirements"][0]["citations"][0]
        self.assertEqual(chunks["c1"]["display_text"][citation["start_char"] : citation["end_char"]], citation["text"])

    def test_non_candidate_or_hallucinated_quote_fails_closed(self) -> None:
        chunks, documents, temporal = _fixtures()
        raw = {
            "question_time_scope": "current",
            "response_mode": "full_answer",
            "requirements": [
                {
                    "question_part": "가격",
                    "status": "supported",
                    "answer": "200 세라",
                    "evidence": [{"candidate_ref": "2", "quote": "가격은 999 세라"}],
                }
            ],
        }

        verified = verify_and_sanitize_output(
            raw,
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(verified["response_mode"], "abstain")
        self.assertEqual(verified["requirements"][0]["citations"], [])
        self.assertIn(
            "candidate_ref_not_in_candidates",
            verified["verification"]["requirements"][0]["failure_reasons"],
        )

    def test_expired_current_document_fails_closed(self) -> None:
        chunks, documents, temporal = _fixtures()
        raw = {
            "question_time_scope": "current",
            "response_mode": "full_answer",
            "requirements": [
                {
                    "question_part": "가격",
                    "status": "supported",
                    "answer": "200 세라",
                    "evidence": [
                        {"candidate_ref": "1", "quote": "종료된 상품의 가격은 200 세라"}
                    ],
                }
            ],
        }

        verified = verify_and_sanitize_output(
            raw,
            candidate_chunk_ids=["c2"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(verified["response_mode"], "abstain")
        self.assertIn(
            "current_temporal_or_revision_policy_failed",
            verified["verification"]["requirements"][0]["failure_reasons"],
        )

    def test_supported_and_unsupported_becomes_partial(self) -> None:
        chunks, documents, temporal = _fixtures()
        raw = {
            "question_time_scope": "current",
            "response_mode": "full_answer",
            "requirements": [
                {
                    "question_part": "가격",
                    "status": "supported",
                    "answer": "100 세라",
                    "evidence": [{"candidate_ref": "1", "quote": "가격은 100 세라"}],
                },
                {
                    "question_part": "판매 종료일",
                    "status": "unsupported",
                    "answer": "",
                    "evidence": [],
                },
            ],
        }

        verified = verify_and_sanitize_output(
            raw,
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(verified["response_mode"], "partial_answer")
        self.assertEqual(verified["model_response_mode"], "full_answer")

    def test_requirement_verifier_rejects_answer_not_contained_in_quote(self) -> None:
        chunks, documents, temporal = _fixtures()
        decision, audit = verify_requirement_selection(
            {
                "status": "supported",
                "answer": "200 세라",
                "evidence": [
                    {"candidate_ref": "1", "quote": "상품 A의 가격은 100 세라"}
                ],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "상품 A",
                "relation": "가격",
                "surface": "가격",
                "value_type": "price",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn("answer_tokens_not_contained_in_evidence", audit["failure_reasons"])

    def test_requirement_verifier_resolves_short_table_row_ref(self) -> None:
        chunks, documents, temporal = _fixtures()
        rows = {
            "c1": [
                {
                    "row_id": "target",
                    "row_text": "상품 A의 가격은 100 세라",
                    "facts": [
                        {"subject": "상품 A", "attribute": "가격", "value": "100 세라"}
                    ],
                }
            ]
        }

        decision, audit = verify_requirement_selection(
            {
                "status": "supported",
                "answer": "100 세라",
                "evidence": [
                    {"candidate_ref": "1", "quote": "", "table_row_ref": "1"}
                ],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "상품 A",
                "relation": "가격",
                "surface": "가격",
                "value_type": "price",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
            table_rows_by_chunk=rows,
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["citations"][0]["text"], "상품 A의 가격은 100 세라")
        self.assertEqual(audit["matching_table_row_ids"], ["target"])

    def test_table_verifier_normalizes_datetime_to_exact_row_value(self) -> None:
        chunks, documents, temporal = _fixtures()
        row_text = (
            "| [프리미엄 코인샵]트로피컬 바캉스 무기 아바타 상자 "
            "| 2개 | 계정당 5회 | 2026년 8월 27일 06시 |"
        )
        chunks["c1"]["display_text"] = row_text
        rows = {
            "c1": [
                {
                    "row_id": "target",
                    "row_text": row_text,
                    "facts": [
                        {
                            "subject": "삭제일자가 존재하는 판매 물품",
                            "attribute": "판매 목록",
                            "value": (
                                "[프리미엄 코인샵]"
                                "트로피컬 바캉스 무기 아바타 상자"
                            ),
                        },
                        {
                            "subject": "삭제일자가 존재하는 판매 물품",
                            "attribute": "삭제일자",
                            "value": "2026년 8월 27일 06시",
                        },
                    ],
                }
            ]
        }

        decision, audit = verify_requirement_selection(
            {
                "status": "supported",
                "answer": "2026-08-27T06:00:00",
                "evidence": [
                    {"candidate_ref": "1", "quote": "", "table_row_ref": "1"}
                ],
            },
            requirement={
                "requirement_id": "deletion_at",
                "subject": (
                    "[프리미엄 코인샵]"
                    "트로피컬 바캉스 무기 아바타 상자"
                ),
                "relation": "deletion_at",
                "value_type": "datetime",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
            table_rows_by_chunk=rows,
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["answer"], "2026년 8월 27일 06시")
        self.assertEqual(audit["failure_reasons"], [])
        self.assertEqual(
            audit["answer_value_source"],
            "selected_table_fact",
        )

    def test_non_table_schema_forbids_table_row_ref(self) -> None:
        with self.assertRaises(ValidationError):
            NonTableRequirementSelectionOutput.model_validate(
                {
                    "status": "supported",
                    "answer": "100 세라",
                    "evidence": [
                        {
                            "candidate_ref": "1",
                            "quote": "상품 A의 가격은 100 세라",
                            "table_row_ref": "1",
                        }
                    ],
                }
            )

    def test_non_table_verifier_accepts_exact_quote_without_table_fields(self) -> None:
        chunks, documents, temporal = _fixtures()

        decision, audit = verify_non_table_requirement_selection(
            {
                "status": "supported",
                "answer": "100 세라",
                "evidence": [
                    {
                        "candidate_ref": "1",
                        "quote": "상품 A의 가격은 100 세라",
                    }
                ],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "상품 A",
                "relation": "가격",
                "surface": "가격",
                "value_type": "price",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(audit["failure_reasons"], [])
        self.assertEqual(audit["matching_table_row_ids"], [])

    def test_requirement_verifier_recovers_whitespace_only_quote_difference(self) -> None:
        chunks, documents, temporal = _fixtures()
        chunks["c1"]["display_text"] = "상품 A의 가격은\n100 세라입니다."

        decision, _ = verify_requirement_selection(
            {
                "status": "supported",
                "answer": "100 세라",
                "evidence": [
                    {"candidate_ref": "1", "quote": "가격은 100 세라입니다."}
                ],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "상품 A",
                "relation": "가격",
                "surface": "가격",
                "value_type": "price",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(decision["status"], "supported_exact")
        self.assertEqual(decision["citations"][0]["text"], "가격은\n100 세라입니다.")

    def test_unsupported_payload_is_discarded_without_generation_error(self) -> None:
        chunks, documents, temporal = _fixtures()

        decision, audit = verify_requirement_selection(
            {
                "status": "unsupported",
                "answer": "추측 답변",
                "evidence": [{"candidate_ref": "1", "quote": "가격은 100 세라"}],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "상품 A",
                "relation": "가격",
                "surface": "가격",
                "value_type": "price",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertEqual(decision["answer"], "")
        self.assertIn("unsupported_payload_discarded", audit["failure_reasons"])

    def test_answer_support_allows_korean_particle_and_ending_suffixes(self) -> None:
        chunks, documents, temporal = _fixtures()
        chunks["c1"]["display_text"] = "몬스터의 Y축 피격 판정이 조정됩니다."

        decision, _ = verify_requirement_selection(
            {
                "status": "supported",
                "answer": "Y축 피격 판정 조정",
                "evidence": [
                    {
                        "candidate_ref": "1",
                        "quote": "몬스터의 Y축 피격 판정이 조정됩니다.",
                    }
                ],
            },
            requirement={
                "requirement_id": "r1",
                "subject": "몬스터",
                "relation": "Y축 피격 판정 조정",
                "surface": "Y축 피격 판정 조정",
                "value_type": "change",
            },
            question_time_scope="current",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertEqual(decision["status"], "supported_exact")
