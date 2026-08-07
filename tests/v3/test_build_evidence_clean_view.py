from __future__ import annotations

from src.v3.build_evidence_clean_view import build_evidence_view, span_is_eligible


def _chunk(text: str, source_id: str = "dnf_seria_shop") -> dict:
    return {
        "chunk_id": "chunk_1",
        "parent_document_id": "document_1",
        "source_id": source_id,
        "display_text": text,
    }


def test_footer_is_excluded_but_original_offsets_remain_valid() -> None:
    text = "판매기간: 7월 1일~7월 31일\n텍스트복사\n목록\n제목\nFIRST\nEND"
    view = build_evidence_view(_chunk(text))

    assert view is not None
    assert view["evidence_text_clean"] == "판매기간: 7월 1일~7월 31일\n"
    assert view["excluded_ranges"][0]["start_offset"] == text.index("텍스트복사")
    assert span_is_eligible(view, start_offset=0, end_offset=4)
    nav_start = text.index("제목")
    assert not span_is_eligible(view, start_offset=nav_start, end_offset=nav_start + 2)


def test_policy_selector_is_removed_without_removing_repeated_body() -> None:
    text = (
        "운영정책\n시행일자\n2026년 3월 15일\n인쇄\n"
        "1. 기본 운영 정책\n2. 이용 제한\n"
        "1. 기본 운영 정책\n실제 본문\n"
    )
    view = build_evidence_view(_chunk(text, "dnf_account_policy"))

    assert view is not None
    assert "2026년 3월 15일" not in view["evidence_text_clean"]
    assert view["evidence_text_clean"].endswith("1. 기본 운영 정책\n실제 본문\n")
    body_start = text.rindex("1. 기본 운영 정책")
    assert span_is_eligible(view, start_offset=body_start, end_offset=body_start + 2)


def test_unmodified_chunk_has_no_view_and_all_spans_are_eligible() -> None:
    view = build_evidence_view(_chunk("정상 본문"))
    assert view is None
    assert span_is_eligible(view, start_offset=0, end_offset=5)


def test_pure_navigation_chunk_is_preserved_but_has_no_eligible_span() -> None:
    text = "텍스트복사\n목록\n제목\nFIRST\nEND"
    view = build_evidence_view(_chunk(text))

    assert view is not None
    assert view["evidence_text_clean"] == ""
    assert view["fully_excluded_from_evidence"]
    assert not span_is_eligible(view, start_offset=0, end_offset=4)
