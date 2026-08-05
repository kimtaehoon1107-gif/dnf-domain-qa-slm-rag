from src.v3.diagnose_product_table_subject_binding_s2 import (
    _coordinate,
    _without_table_introducer_context,
)


def test_without_table_introducer_preserves_heading_header_and_subject() -> None:
    context = (
        "업데이트 > 표 헤더: | 전 | 후 | > "
        "표 도입: - 질풍 개화 옵션 > 표 대상: | 아이템명 | 타이드 |"
    )
    assert _without_table_introducer_context(context) == (
        "업데이트 > 표 헤더: | 전 | 후 | > 표 대상: | 아이템명 | 타이드 |"
    )


def test_without_table_introducer_handles_no_subject_and_no_marker() -> None:
    assert _without_table_introducer_context(
        "업데이트 > 표 헤더: | 전 | 후 | > 표 도입: 질풍"
    ) == "업데이트 > 표 헤더: | 전 | 후 |"
    unchanged = "업데이트 > 표 헤더: | 전 | 후 |"
    assert _without_table_introducer_context(unchanged) == unchanged


def test_coordinate_excludes_context_and_score() -> None:
    unit = {
        "chunk_id": "c1",
        "start_char": 10,
        "end_char": 20,
        "unit_kind": "table_row",
        "context_text": "변경됨",
        "question_relevance_score": 0.9,
    }
    assert _coordinate(unit) == ("c1", 10, 20, "table_row")
