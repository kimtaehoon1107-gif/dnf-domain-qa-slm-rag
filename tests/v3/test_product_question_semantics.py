import pytest

from src.v3.product_evidence_pack import content_kind_table_row_present
from src.v3.product_free_rag import (
    _release_date_candidate_reservation,
    product_retrieval_query_variants,
)
from src.v3.product_minimal_verifier import verify_product_claim_output
from src.v3.product_reward_kind import _is_reward_kind_question


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("미카엘라 레이드 보상 내역 알려줘", True),
        ("미카엘라 레이드 보상 구성을 알려줘", True),
        ("미카엘라 레이드에서 어떤 아이템을 얻어?", True),
        ("미카엘라 레이드의 빛의 전도 획득 여부 알려줘", False),
    ],
)
def test_reward_kind_intent_generalizes_without_capturing_single_item(
    question,
    expected,
):
    assert _is_reward_kind_question(question) is expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("미카엘라 레이드 난이도 알려줘", True),
        ("미카엘라는 어떤 모드로 나뉘어?", True),
        ("미카엘라 레이드 보상 종류 알려줘", False),
    ],
)
def test_content_kind_intent_generalizes_without_capturing_reward_kinds(
    question,
    expected,
):
    row = "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |"
    assert content_kind_table_row_present(question, row) is expected


@pytest.mark.parametrize(
    ("question", "expected_variant"),
    [
        (
            "미카엘라 레이드 도입일이 언제야?",
            "미카엘라 레이드 업데이트 되는 내용 언제야?",
        ),
        (
            "미카엘라 레이드 서비스 시작일 알려줘",
            "미카엘라 레이드 업데이트 되는 내용 알려줘",
        ),
        (
            "미카엘라 레이드가 업데이트된 날 알려줘",
            "미카엘라 레이드가 업데이트 되는 내용 알려줘",
        ),
    ],
)
def test_release_date_query_variants_cover_common_paraphrases(
    question,
    expected_variant,
):
    variants = product_retrieval_query_variants(question)

    assert variants == [expected_variant]


def test_release_date_relation_alias_survives_question_surface_verification():
    evidence_text = "미카엘라 레이드가 2026년 8월 6일(목) 업데이트 됩니다."
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "미카엘라 레이드 도입일은 "
                        "2026년 8월 6일(목) 점검 후입니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드 도입일이 언제야?",
        evidence_units=[
            {
                "evidence_ref": "E1",
                "chunk_id": "release",
                "parent_document_id": "release-doc",
                "title": "미카엘라 레이드 업데이트",
                "context_text": "미카엘라 레이드 업데이트 날짜",
                "start_char": 0,
                "end_char": len(evidence_text),
                "text": evidence_text,
            }
        ],
        chunks_by_id={"release": {"display_text": evidence_text}},
        requested_subjects=["미카엘라 레이드 도입일"],
    )

    assert verified["mode"] == "answer"
    assert len(verified["claims"]) == 1


def test_release_date_candidate_reservation_excludes_event_period_only():
    ranked = [
        {"chunk_id": "event", "parent_document_id": "event-doc"},
        {"chunk_id": "patch", "parent_document_id": "patch-doc"},
    ]
    chunks = {
        "event": {
            "display_text": (
                "이벤트 기간: 2026년 8월 6일 ~ 8월 20일\n"
                "미카엘라 레이드 클리어 이벤트입니다."
            )
        },
        "patch": {
            "display_text": (
                "8/6(목) 점검 중 미카엘라 레이드가 업데이트 됩니다."
            )
        },
    }

    reserved = _release_date_candidate_reservation(
        "미카엘라 레이드 도입일이 언제야?",
        ranked,
        chunks_by_id=chunks,
    )

    assert [row["chunk_id"] for row in reserved] == ["patch"]


def test_release_date_claim_rebinds_from_event_period_to_direct_patch():
    patch_text = "8/6(목) 점검 중 미카엘라 레이드가 업데이트 됩니다."
    event_text = "이벤트 기간은 8/6(목) 점검 후부터입니다."
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "patch",
            "parent_document_id": "patch-doc",
            "title": "미카엘라 레이드 업데이트",
            "context_text": "업데이트",
            "published_at": "2026-08-05",
            "start_char": 0,
            "end_char": len(patch_text),
            "text": patch_text,
        },
        {
            "evidence_ref": "E2",
            "chunk_id": "event",
            "parent_document_id": "event-doc",
            "title": "미카엘라 레이드 이벤트",
            "context_text": "이벤트 기간",
            "published_at": "2026-08-06",
            "start_char": 0,
            "end_char": len(event_text),
            "text": event_text,
        },
    ]
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "미카엘라 레이드 도입일은 2026년 8월 6일입니다.",
                    "evidence_refs": ["E2"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드 도입일이 언제야?",
        evidence_units=units,
        chunks_by_id={
            "patch": {"display_text": patch_text},
            "event": {"display_text": event_text},
        },
        requested_subjects=["미카엘라 레이드 도입일"],
    )

    assert verified["mode"] == "answer"
    assert verified["claims"][0]["evidence_refs"] == ["E1"]
    assert verified["verification"]["rebound_evidence_refs"] == [
        {"claim_index": 1, "from": ["E2"], "to": ["E1"]}
    ]


def test_partial_release_date_rebinds_low_relevance_ref_and_becomes_answer():
    patch_text = "8/6(목) 점검 중 미카엘라 레이드가 업데이트 됩니다."
    event_text = "이벤트 기간은 8/6(목) 점검 후부터입니다."
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "patch",
            "parent_document_id": "patch-doc",
            "title": "미카엘라 레이드 업데이트",
            "context_text": "업데이트",
            "published_at": "2026-08-05",
            "question_relevance_score": 0.9,
            "start_char": 0,
            "end_char": len(patch_text),
            "text": patch_text,
        },
        {
            "evidence_ref": "E2",
            "chunk_id": "event",
            "parent_document_id": "event-doc",
            "title": "미카엘라 레이드 이벤트",
            "context_text": "이벤트 기간",
            "published_at": "2026-08-06",
            "question_relevance_score": 0.01,
            "start_char": 0,
            "end_char": len(event_text),
            "text": event_text,
        },
    ]
    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": (
                        "미카엘라 레이드 서비스 시작일은 "
                        "2026년 8월 6일입니다."
                    ),
                    "evidence_refs": ["E2"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드 서비스 시작일 알려줘",
        evidence_units=units,
        chunks_by_id={
            "patch": {"display_text": patch_text},
            "event": {"display_text": event_text},
        },
    )

    assert verified["mode"] == "answer"
    assert verified["claims"][0]["evidence_refs"] == ["E1"]
