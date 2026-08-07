from __future__ import annotations

from copy import deepcopy

from src.v3.clean_retrieval_corpus import audit_integrity, clean_retrieval_text, clean_rows


def _chunk(chunk_id: str, text: str, source_id: str = "dnf_notice") -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": f"document_{chunk_id}",
        "display_text": "본문 값 4,000만 골드",
        "retrieval_text": text,
        "start_offset": 0,
        "end_offset": 14,
        "normalized_text_hash": "n",
        "parent_content_hash": "p",
        "source_id": source_id,
        "source_kind": "notice",
        "status": "current",
        "default_exposure": True,
    }


def test_shop_footer_and_pager_are_removed_without_touching_body() -> None:
    text = "\n".join(
        [
            "상품 제목",
            "가격 4,000만 골드",
            "텍스트복사",
            "목록",
            "제목",
            "삭제",
            "판매중",
            "종료",
            "FIRST",
            "PREV",
            "1",
            "NEXT",
            "END",
        ]
    )
    cleaned, types, warnings, _ = clean_retrieval_text(
        text, source_id="dnf_seria_shop"
    )
    assert cleaned == "상품 제목\n가격 4,000만 골드"
    assert "shop_or_monthly_listing_tail" in types
    assert "pagination_tail" in types
    assert warnings == []


def test_policy_selector_and_toc_are_removed_but_body_heading_is_kept() -> None:
    text = "\n".join(
        [
            "던전앤파이터 운영정책 (2026-03-15 시행)",
            "### 운영정책",
            "시행일자",
            "2026년 03월 15일",
            "2025년 11월 01일",
            "인쇄",
            "1. 기본 운영 정책",
            "2. 고객의 의무",
            "1. 기본 운영 정책",
            "실제 정책 본문",
        ]
    )
    cleaned, types, warnings, _ = clean_retrieval_text(
        text, source_id="dnf_account_policy"
    )
    assert cleaned.endswith("1. 기본 운영 정책\n실제 정책 본문")
    assert "2025년 11월 01일" not in cleaned
    assert cleaned.count("1. 기본 운영 정책") == 1
    assert types == ["policy_revision_selector", "policy_table_of_contents"]
    assert warnings == []


def test_content_image_alt_is_preserved_but_known_footer_banner_is_removed() -> None:
    body_image = "[IMAGE_ALT] 상품 구성 이미지"
    text = "\n".join(
        [
            "본문",
            body_image,
            "[IMAGE_ALT] 피싱방지4차_공식 배너",
            "텍스트복사",
            "목록",
        ]
    )
    cleaned, types, _, _ = clean_retrieval_text(text, source_id="dnf_notice")
    assert body_image in cleaned
    assert "피싱방지" not in cleaned
    assert "known_phishing_banner_alt" in types


def test_clean_rows_changes_only_retrieval_text_and_preserves_exact_gold() -> None:
    dirty = [_chunk("chunk_1", "제목\n본문 값 4,000만 골드\n텍스트복사\n목록")]
    original = deepcopy(dirty)
    clean, audit, metrics = clean_rows(dirty)
    evaluation = [
        {
            "dev_id": "case_1",
            "evidence_groups": [
                {
                    "group_id": "group_1",
                    "evidence_span": "본문 값 4,000만 골드",
                    "acceptable_chunk_ids": ["chunk_1"],
                }
            ],
        }
    ]
    integrity = audit_integrity(original, clean, {"fixture": evaluation})
    assert integrity["pass"] is True
    assert clean[0]["display_text"] == original[0]["display_text"]
    assert clean[0]["chunk_id"] == original[0]["chunk_id"]
    assert clean[0]["start_offset"] == original[0]["start_offset"]
    assert len(audit) == metrics["modified_unique_chunks"] == 1


def test_noncontaminated_retrieval_text_is_byte_stable() -> None:
    text = "제목\n일반 본문\n[IMAGE_ALT] 실제 내용 이미지"
    cleaned, types, warnings, counters = clean_retrieval_text(
        text, source_id="dnf_guide"
    )
    assert cleaned == text
    assert types == []
    assert warnings == []
    assert counters == {}
