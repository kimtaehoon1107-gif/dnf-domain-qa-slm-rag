from __future__ import annotations

from src.v3.subject_anchored_retrieval import (
    build_planner_relation_queries,
    candidate_supports_subject,
    enforce_subject_citation_support,
    extract_subject_anchored_queries,
    merge_subject_anchored_candidates,
    reciprocal_rank_fuse,
)


def _entity_index() -> dict:
    return {"길드": {"phrase": "길드"}}


def _chunk(chunk_id: str, text: str, *, heading: str = "") -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": f"doc-{chunk_id}",
        "heading_path": [heading] if heading else [],
        "retrieval_text": text,
    }


def test_extracts_subject_and_propagates_it_to_two_requirements() -> None:
    result = extract_subject_anchored_queries(
        "길드 해제의 명예훼손 사유와 사칭·사기 사유는 어떻게 규정돼?",
        _entity_index(),
    )

    assert result is not None
    assert result["subject"] == "길드 해제"
    assert result["queries"] == [
        "길드 해제 명예훼손 사유",
        "길드 해제 사칭·사기 사유",
    ]


def test_extracts_three_comma_separated_requirements() -> None:
    result = extract_subject_anchored_queries(
        "길드의 명예훼손 사유, 사칭·사기 사유, 영리 홍보 사유를 모두 알려줘.",
        _entity_index(),
    )

    assert result is not None
    assert result["queries"] == [
        "길드 명예훼손 사유",
        "길드 사칭·사기 사유",
        "길드 영리 홍보 사유",
    ]


def test_planner_relation_query_preserves_implicit_relation_detail() -> None:
    assert build_planner_relation_queries(
        "길드",
        [
            {
                "relation": "길드 해제 명예훼손 사유",
            },
            {
                "relation": "영리_홍보_사유",
            },
        ],
    ) == [
        "길드 해제 명예훼손 사유",
        "길드 영리 홍보 사유",
    ]


def test_rejects_question_without_verified_official_anchor() -> None:
    assert (
        extract_subject_anchored_queries(
            "알 수 없는 대상의 가격과 거래 타입은?",
            _entity_index(),
        )
        is None
    )


def test_subject_support_rejects_account_withdrawal_for_guild_question() -> None:
    chunk = _chunk("account", "던파ID 탈퇴 후 14일 뒤 재가입 가능합니다.")
    document = {"title": "탈퇴 후 재가입", "document_id": "doc-account"}

    assert not candidate_supports_subject(
        "길드",
        chunk=chunk,
        document=document,
    )


def test_subject_support_accepts_title_or_dense_body_evidence() -> None:
    titled = _chunk("title", "탈퇴 후 다음 날 가입할 수 있습니다.")
    dense = _chunk("dense", "길드 탈퇴 후 길드 재가입은 06시부터 가능합니다.")

    assert candidate_supports_subject(
        "길드",
        chunk=titled,
        document={"title": "길드", "document_id": "doc-title"},
    )
    assert candidate_supports_subject(
        "길드",
        chunk=dense,
        document={"title": "운영정책", "document_id": "doc-dense"},
    )


def test_merge_preserves_baseline_and_adds_one_candidate_per_query() -> None:
    chunks = {
        "good": _chunk("good", "길드 탈퇴 후 길드 재가입"),
        "wrong": _chunk("wrong", "던파ID 탈퇴 후 재가입"),
        "new-a": _chunk("new-a", "길드 명예훼손 길드 해제"),
        "new-b": _chunk("new-b", "길드 사칭 길드 해제"),
    }
    documents = {
        row["parent_document_id"]: {
            "document_id": row["parent_document_id"],
            "title": "운영정책",
        }
        for row in chunks.values()
    }

    merged = merge_subject_anchored_candidates(
        [{"chunk_id": "good"}, {"chunk_id": "wrong"}],
        [
            [{"chunk_id": "new-a"}],
            [{"chunk_id": "new-b"}],
        ],
        subject="길드",
        chunks_by_id=chunks,
        documents_by_id=documents,
        maximum=4,
    )

    assert [row["chunk_id"] for row in merged] == [
        "good",
        "new-a",
        "new-b",
        "wrong",
    ]


def test_subject_gate_rejects_requirement_with_wrong_subject_citation() -> None:
    chunks = {
        "wrong": _chunk("wrong", "던파ID 탈퇴 후 재가입은 14일입니다."),
    }
    result = {
        "response_mode": "full_answer",
        "requirements": [
            {
                "requirement_index": 0,
                "question_part": "길드 탈퇴 후 재가입 시점",
                "status": "supported_exact",
                "answer": "14일",
                "citations": [{"chunk_id": "wrong", "text": "14일"}],
            }
        ],
        "verification": {"requirements": []},
    }

    checked = enforce_subject_citation_support(
        result,
        subject="길드",
        chunks_by_id=chunks,
        documents_by_id={
            "doc-wrong": {
                "document_id": "doc-wrong",
                "title": "던파ID 탈퇴 후 재가입",
            }
        },
    )

    assert checked["response_mode"] == "abstain"
    assert checked["requirements"][0]["status"] == "unsupported"
    assert checked["requirements"][0]["citations"] == []
    assert checked["verification"]["requirements"][0][
        "failure_reasons"
    ] == ["citation_subject_mismatch"]


def test_query_fusion_rewards_candidate_seen_by_both_queries() -> None:
    fused = reciprocal_rank_fuse(
        [
            [{"chunk_id": "surface-only"}, {"chunk_id": "shared"}],
            [{"chunk_id": "planner-only"}, {"chunk_id": "shared"}],
        ]
    )

    assert [row["chunk_id"] for row in fused] == [
        "shared",
        "planner-only",
        "surface-only",
    ]
