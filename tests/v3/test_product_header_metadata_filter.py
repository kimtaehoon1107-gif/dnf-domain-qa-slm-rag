from src.v3.product_evidence_pack import (
    _product_header_metadata_spans,
    _without_product_header_metadata_units,
)


def _unit(start: int, end: int, text: str) -> dict[str, object]:
    return {"start_char": start, "end_char": end, "text": text}


def test_header_metadata_filter_removes_timestamp_and_view_only() -> None:
    text = "\n".join(
        (
            "### 공지사항",
            "일반",
            "제목은 유지",
            "2025.08.12 14:00",
            "37,477",
            "안녕하세요.",
            "본문 시각은 2025.08.12 15:00입니다.",
        )
    )
    chunk = {"display_text": text}
    timestamp_start = text.index("2025.08.12 14:00")
    view_start = text.index("37,477")
    body_start = text.index("본문 시각")
    units = [
        _unit(9, 11, "일반"),
        _unit(timestamp_start, timestamp_start + 16, "2025.08.12 14:00"),
        _unit(view_start, view_start + 6, "37,477"),
        _unit(body_start, len(text), text[body_start:]),
    ]
    assert _without_product_header_metadata_units(units, chunk=chunk) == [
        units[0],
        units[3],
    ]


def test_headerless_chunk_is_completely_unchanged() -> None:
    chunk = {
        "display_text": "이용 안내\n2025.08.12 14:00\n본문의 실제 시각입니다."
    }
    units = [_unit(0, len(chunk["display_text"]), chunk["display_text"])]
    assert _product_header_metadata_spans(chunk) == []
    assert _without_product_header_metadata_units(units, chunk=chunk) is units


def test_body_timestamp_after_leading_six_lines_is_preserved() -> None:
    text = "\n".join(
        (
            "### 안내",
            "분류",
            "제목",
            "머리말",
            "안녕하세요.",
            "본문이 시작됩니다.",
            "2025.08.12 14:00",
        )
    )
    chunk = {"display_text": text}
    assert _product_header_metadata_spans(chunk) == []


def test_published_timestamp_is_kept_when_question_asks_for_it() -> None:
    text = "\n".join(
        (
            "### 공지사항",
            "일반",
            "정기점검 안내",
            "2026.05.20 15:00",
            "37,477",
            "점검은 5월 21일에 적용됩니다.",
        )
    )
    chunk = {"display_text": text}
    timestamp_start = text.index("2026.05.20 15:00")
    view_start = text.index("37,477")
    units = [
        _unit(timestamp_start, timestamp_start + 16, "2026.05.20 15:00"),
        _unit(view_start, view_start + 6, "37,477"),
    ]
    assert _without_product_header_metadata_units(
        units,
        chunk=chunk,
        question="정기점검 업데이트 공지는 언제 게시됐어?",
    ) == [units[0]]


def test_notice_as_of_question_keeps_published_timestamp() -> None:
    text = "\n".join(
        (
            "### 공지사항",
            "일반",
            "지원 안내",
            "2026.07.02 10:00",
            "1,234",
            "지원 상태를 안내합니다.",
        )
    )
    chunk = {"display_text": text}
    timestamp_start = text.index("2026.07.02 10:00")
    unit = _unit(
        timestamp_start,
        timestamp_start + 16,
        "2026.07.02 10:00",
    )
    assert _without_product_header_metadata_units(
        [unit],
        chunk=chunk,
        question="2026년 7월 2일 공지 시점에 이미 종료된 상태였어?",
    ) == [unit]
