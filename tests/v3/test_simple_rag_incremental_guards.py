from __future__ import annotations

from src.v3.simple_rag_incremental_guards import (
    apply_relation_value_colocation_guard,
    apply_subject_period_identity_guard,
    apply_temporal_role_guard,
)


def _result(
    *,
    answer: str,
    citation_texts: list[str],
    question_part: str = "요구",
    chunk_ids: list[str] | None = None,
) -> dict:
    chunk_ids = chunk_ids or [
        f"chunk-{index}" for index in range(1, len(citation_texts) + 1)
    ]
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
                        "chunk_id": chunk_id,
                        "parent_document_id": f"doc-{index}",
                        "text": text,
                    }
                    for index, (chunk_id, text) in enumerate(
                        zip(chunk_ids, citation_texts, strict=True),
                        1,
                    )
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


def _artifacts(display_text: str, *, title: str = "문서") -> tuple[dict, dict]:
    return (
        {
            "chunk-1": {
                "parent_document_id": "doc-1",
                "display_text": display_text,
            }
        },
        {"doc-1": {"title": title}},
    )


def test_subject_period_guard_rejects_sibling_month_record() -> None:
    chunks, documents = _artifacts(
        "# [7월 이달의 아이템]\n| 삭제일자 | 2026년 8월 13일 |",
        title="7월 이달의 아이템",
    )
    guarded = apply_subject_period_identity_guard(
        _result(
            answer="2026년 8월 13일 06시",
            citation_texts=["2026년 8월 13일 06시 일괄 삭제됩니다."],
        ),
        question="[2월]스페셜 상자는 언제 삭제됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["requirements"][0]["answer"] == ""
    assert guarded["verification"]["requirements"][0][
        "failure_reasons"
    ] == ["explicit_subject_period_identity_mismatch"]


def test_subject_period_guard_allows_later_deletion_month_for_target_record() -> None:
    chunks, documents = _artifacts(
        "# [2월 이달의 아이템]\n| 삭제일자 | 2026년 3월 12일 |",
        title="2월 이달의 아이템",
    )
    guarded = apply_subject_period_identity_guard(
        _result(
            answer="2026년 3월 12일 06시",
            citation_texts=["2026년 3월 12일 06시 일괄 삭제됩니다."],
        ),
        question="[2월]스페셜 상자는 언제 삭제됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded["response_mode"] == "full_answer"
    assert guarded["requirements"][0]["answer"] == "2026년 3월 12일 06시"


def test_subject_period_guard_does_not_infer_unstated_month() -> None:
    chunks, documents = _artifacts("# [7월 이달의 아이템]")
    baseline = _result(
        answer="2026년 8월 13일 06시",
        citation_texts=["2026년 8월 13일 06시 일괄 삭제됩니다."],
    )
    guarded = apply_subject_period_identity_guard(
        baseline,
        question="스페셜 상자는 언제 삭제됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded == baseline


def test_subject_period_guard_accepts_explicit_year_month_metadata() -> None:
    chunks, documents = _artifacts(
        "# 해방의 열쇠 100개 상자\n| 삭제일자 | 2026년 1월 22일 |",
        title="해방의 열쇠 100개 상자",
    )
    documents["doc-1"]["published_at"] = "2026-01-01"
    guarded = apply_subject_period_identity_guard(
        _result(
            answer="2026년 1월 22일 06시",
            citation_texts=["삭제일자 | 2026년 1월 22일 06시 일괄삭제"],
        ),
        question="2026년 1월에 판매한 해방의 열쇠 상자는 언제 삭제됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded["response_mode"] == "full_answer"


def test_temporal_guard_rejects_explicit_published_effective_conflict() -> None:
    chunks, documents = _artifacts(
        "게시 시각은 2026년 5월 20일 15시입니다.",
        title="업데이트 공지",
    )
    guarded = apply_temporal_role_guard(
        _result(
            answer="2026년 5월 20일 15시",
            citation_texts=["게시 시각은 2026년 5월 20일 15시입니다."],
            question_part="실제 적용일",
        ),
        question="업데이트는 언제 적용됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["verification"]["requirements"][0][
        "failure_reasons"
    ] == ["temporal_role_conflict"]


def test_temporal_guard_keeps_matching_deletion_role() -> None:
    chunks, documents = _artifacts(
        "삭제일자는 2026년 3월 12일입니다.",
        title="2월 이달의 아이템",
    )
    guarded = apply_temporal_role_guard(
        _result(
            answer="2026년 3월 12일",
            citation_texts=["삭제일자는 2026년 3월 12일입니다."],
            question_part="삭제일",
        ),
        question="이 상자는 언제 삭제됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded["response_mode"] == "full_answer"


def test_temporal_guard_uses_requirement_role_in_multi_role_question() -> None:
    chunks, documents = _artifacts(
        "게시 시각은 5월 20일이고 실제 적용일은 5월 21일입니다.",
        title="5월 21일 업데이트",
    )
    guarded = apply_temporal_role_guard(
        _result(
            answer="5월 20일",
            citation_texts=["게시 시각은 5월 20일입니다."],
            question_part="실제 적용일",
        ),
        question="공지는 언제 게시됐고 실제 업데이트는 언제 적용됐어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["verification"]["requirements"][0][
        "failure_reasons"
    ] == ["temporal_role_conflict"]


def test_relation_value_guard_rejects_value_and_maximum_in_separate_quotes() -> None:
    guarded = apply_relation_value_colocation_guard(
        _result(
            answer="100일",
            citation_texts=[
                "4차 제재는 100일 게임 이용제한입니다.",
                "제재 누적일은 최대 30일까지 가능합니다.",
            ],
        ),
        question="채팅 제재의 누적일은 최대 며칠까지 가능해?",
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["verification"]["requirements"][0][
        "failure_reasons"
    ] == ["relation_value_not_colocated"]


def test_relation_value_guard_keeps_colocated_maximum_value() -> None:
    guarded = apply_relation_value_colocation_guard(
        _result(
            answer="30일",
            citation_texts=["제재 누적일은 최대 30일까지 가능합니다."],
        ),
        question="채팅 제재의 누적일은 최대 며칠까지 가능해?",
    )

    assert guarded["response_mode"] == "full_answer"


def test_relation_value_guard_keeps_daily_maximum_value() -> None:
    guarded = apply_relation_value_colocation_guard(
        _result(
            answer="50M",
            citation_texts=["플레이 마일리지는 일일 최대 50M입니다."],
        ),
        question="플레이로 얻는 일일 최대 마일리지는 얼마야?",
    )

    assert guarded["response_mode"] == "full_answer"
