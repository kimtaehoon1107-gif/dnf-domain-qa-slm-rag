from __future__ import annotations

from src.v3.build_faq_title_dedup_view import deduplicate_faq_titles


def test_only_duplicate_faq_title_is_removed() -> None:
    documents = [{"document_id": "faq_doc", "title": "[게임 이용] 질문"}]
    chunks = [
        {
            "chunk_id": "faq_chunk",
            "parent_document_id": "faq_doc",
            "source_id": "dnf_faq",
            "retrieval_text": "[게임 이용] 질문\n[게임 이용] 질문\n답변 본문",
            "display_text": "[게임 이용] 질문\n답변 본문",
            "start_offset": 0,
        }
    ]

    cleaned, audit = deduplicate_faq_titles(chunks, documents)

    assert cleaned[0]["retrieval_text"] == "[게임 이용] 질문\n답변 본문"
    assert cleaned[0]["display_text"] == chunks[0]["display_text"]
    assert audit["changed_chunk_count"] == 1


def test_non_faq_and_nonduplicate_faq_are_unchanged() -> None:
    documents = [
        {"document_id": "notice_doc", "title": "공지"},
        {"document_id": "faq_doc", "title": "FAQ"},
    ]
    chunks = [
        {"parent_document_id": "notice_doc", "source_id": "dnf_notice", "retrieval_text": "공지\n공지\n본문"},
        {"parent_document_id": "faq_doc", "source_id": "dnf_faq", "retrieval_text": "FAQ\n본문"},
    ]

    cleaned, audit = deduplicate_faq_titles(chunks, documents)

    assert cleaned == chunks
    assert audit["changed_chunk_count"] == 0
