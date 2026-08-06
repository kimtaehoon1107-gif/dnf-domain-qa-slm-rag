from src.v3.diagnose_product_header_metadata_filter import (
    diagnostic_header_metadata_spans,
)


def test_diagnostic_header_spans_find_only_structured_metadata_lines() -> None:
    text = "\n".join(
        (
            "### 공지사항",
            "일반",
            "제목은 유지",
            "2025.08.12 14:00",
            "37,477",
            "안녕하세요.",
            "본문 시각은 8월 12일 15시입니다.",
        )
    )
    spans = diagnostic_header_metadata_spans(text)
    assert [kind for _, _, kind in spans] == [
        "published_timestamp",
        "view_count",
    ]
    assert [text[start:end] for start, end, _ in spans] == [
        "2025.08.12 14:00",
        "37,477",
    ]


def test_diagnostic_header_spans_leave_headerless_body_unchanged() -> None:
    text = "본문 안내\n2025.08.12 14:00\n본문의 실제 시각입니다."
    assert diagnostic_header_metadata_spans(text) == []
