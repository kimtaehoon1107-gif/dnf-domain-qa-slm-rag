from __future__ import annotations

from src.v3.simple_rag_minimal_verifier import (
    apply_server_scope_agreement_guard,
    apply_table_attribute_identity_guard,
    build_table_rows_by_chunk,
    factual_values_supported,
    recover_unique_whitespace_quotes,
    select_exact_query_window,
    select_query_table_rows,
)


def _result(answer: str, question_part: str = "계정당 구매 제한") -> dict:
    return {
        "response_mode": "full_answer",
        "requirements": [
            {
                "requirement_index": 1,
                "question_part": question_part,
                "status": "supported_exact",
                "answer": answer,
                "citations": [
                    {
                        "chunk_id": "c1",
                        "start_char": 0,
                        "end_char": 30,
                        "text": "| 상품 A | 100 세라 | 무제한 |",
                    }
                ],
            }
        ],
        "verification": {
            "requirements": [
                {
                    "requirement_index": 1,
                    "model_status": "supported",
                    "exposed_status": "supported_exact",
                    "failure_reasons": [],
                }
            ],
            "raw_output_passed_without_sanitization": True,
        },
    }


def _rows() -> dict:
    chunk = {"display_text": "| 상품 A | 100 세라 | 무제한 |"}
    facts = [
        {
            "source_chunk_id": "c1",
            "row_id": "r1",
            "start_offset": 0,
            "end_offset": len(chunk["display_text"]),
            "row_text": chunk["display_text"],
            "subject": "상품 A",
            "attribute": "아이템 명칭",
            "value": "상품 A",
        },
        {
            "source_chunk_id": "c1",
            "row_id": "r1",
            "start_offset": 0,
            "end_offset": len(chunk["display_text"]),
            "row_text": chunk["display_text"],
            "subject": "상품 A",
            "attribute": "아이템 가격",
            "value": "100 세라",
        },
        {
            "source_chunk_id": "c1",
            "row_id": "r1",
            "start_offset": 0,
            "end_offset": len(chunk["display_text"]),
            "row_text": chunk["display_text"],
            "subject": "상품 A",
            "attribute": "기간제한",
            "value": "무제한",
        },
    ]
    return build_table_rows_by_chunk(facts, chunks_by_id={"c1": chunk})


def test_table_guard_rejects_sibling_attribute_value() -> None:
    guarded = apply_table_attribute_identity_guard(
        _result("무제한"),
        question="상품 A의 계정당 구매 제한은?",
        table_rows_by_chunk=_rows(),
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["verification"]["requirements"][0]["failure_reasons"] == [
        "table_attribute_identity_mismatch"
    ]


def test_table_guard_preserves_matching_price_attribute() -> None:
    guarded = apply_table_attribute_identity_guard(
        _result("100 세라", question_part="가격"),
        question="상품 A의 가격은?",
        table_rows_by_chunk=_rows(),
    )

    assert guarded["response_mode"] == "full_answer"
    assert guarded["requirements"][0]["answer"] == "100 세라"


def test_table_guard_uses_requirement_part_before_multi_attribute_question() -> None:
    guarded = apply_table_attribute_identity_guard(
        _result("100 세라", question_part="가격"),
        question="상품 A의 가격과 구매 제한은?",
        table_rows_by_chunk=_rows(),
    )

    assert guarded["response_mode"] == "full_answer"


def test_table_guard_rejects_purchase_limit_in_multi_attribute_question() -> None:
    guarded = apply_table_attribute_identity_guard(
        _result("무제한", question_part="계정당 구매 제한"),
        question="상품 A의 가격과 계정당 구매 제한은?",
        table_rows_by_chunk=_rows(),
    )

    assert guarded["response_mode"] == "abstain"


def test_scope_guard_fails_closed_on_model_server_disagreement() -> None:
    guarded = apply_server_scope_agreement_guard(
        _result("100 세라", question_part="가격"),
        model_scope="current",
        route_scope="historical",
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["verification"]["requirements"][0]["failure_reasons"] == [
        "model_server_time_scope_disagreement"
    ]


def test_unique_whitespace_quote_recovery_restores_exact_slice() -> None:
    raw = {
        "requirements": [
            {
                "evidence": [
                    {
                        "candidate_ref": "1",
                        "quote": "문장 A 문장 B",
                    }
                ]
            }
        ]
    }
    recovered, audit = recover_unique_whitespace_quotes(
        raw,
        candidate_chunk_ids=["c1"],
        chunks_by_id={"c1": {"display_text": "문장 A\n문장 B"}},
    )

    assert recovered["requirements"][0]["evidence"][0]["quote"] == (
        "문장 A\n문장 B"
    )
    assert len(audit) == 1


def test_unique_whitespace_quote_recovery_rejects_ambiguous_match() -> None:
    raw = {
        "requirements": [
            {
                "evidence": [
                    {
                        "candidate_ref": "1",
                        "quote": "문장 A",
                    }
                ]
            }
        ]
    }
    recovered, audit = recover_unique_whitespace_quotes(
        raw,
        candidate_chunk_ids=["c1"],
        chunks_by_id={"c1": {"display_text": "문장 A\n문장 A"}},
    )

    assert recovered == raw
    assert audit == []


def test_normalized_factual_support_accepts_equivalent_date_and_time() -> None:
    assert factual_values_supported(
        "2026-06-04 20:30에 적용됐습니다.",
        "2026년 6월 4일 오후 8시 30분 적용",
    )


def test_normalized_factual_support_rejects_different_currency_value() -> None:
    assert not factual_values_supported(
        "5,800 세라",
        "5,800 골드",
    )


def test_normalized_factual_support_treats_count_words_as_equivalent() -> None:
    assert factual_values_supported(
        "지정 던전을 하루 10번 클리어해야 합니다.",
        "지정 던전 클리어 10회 완료 시 참여할 수 있습니다.",
    )
    assert not factual_values_supported(
        "지정 던전을 하루 9번 클리어해야 합니다.",
        "지정 던전 클리어 10회 완료 시 참여할 수 있습니다.",
    )


def test_normalized_factual_support_uses_context_for_year_only() -> None:
    assert factual_values_supported(
        "2026-06-04",
        "6/4 점검 중 적용",
        context_years={2026},
    )
    assert not factual_values_supported(
        "2026년 4월 2일 20:30",
        "수정됩니다.",
        context_years={2026},
    )


def test_exact_query_window_is_an_unmodified_source_slice() -> None:
    source = "앞부분 " * 100 + "상의 클론 가격 2,600 세라" + " 뒷부분" * 100
    selected = select_exact_query_window(
        source,
        question="상의 클론 가격은?",
        max_chars=120,
    )

    assert selected in source
    assert "상의 클론 가격 2,600 세라" in selected


def test_query_table_rows_require_subject_and_requested_attribute() -> None:
    selected = select_query_table_rows(
        _rows(),
        question="상품 A의 가격은?",
    )

    assert [row["row_id"] for row in selected["c1"]] == ["r1"]
    assert select_query_table_rows(
        _rows(),
        question="상품 B의 가격은?",
    ) == {}
