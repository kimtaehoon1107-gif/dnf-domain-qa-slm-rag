from __future__ import annotations

from src.v3.table_relation_shadow import (
    build_relation_rows,
    rank_relation_rows,
    render_relation_value,
    select_explicit_qualifier_values,
    split_markdown_row,
)


def _fact(
    *,
    row_id: str,
    row_text: str,
    attribute: str,
    value: str,
    value_start_offset: int,
) -> dict[str, object]:
    return {
        "fact_id": f"{row_id}-{attribute}-{value}",
        "table_id": "table-1",
        "row_id": row_id,
        "parent_document_id": "document-1",
        "source_chunk_id": "chunk-1",
        "title": "아포칼립스 : 안티엔바이",
        "heading_path": ["콘텐츠 진행", "난이도별 정보"],
        "table_caption": "난이도별 정보",
        "attribute": attribute,
        "value": value,
        "row_text": row_text,
        "start_offset": 10,
        "end_offset": 70,
        "value_start_offset": value_start_offset,
        "status": "current",
    }


def test_split_markdown_row_preserves_escaped_pipe() -> None:
    assert split_markdown_row(r"| 이름 | A \| B |") == [
        "이름",
        r"A \| B",
    ]


def test_build_relation_rows_uses_atomic_column_labels() -> None:
    row_text = "| 추천 명성 | 73,993 | 98,171 | 105,881 | 112,621 |"
    facts = [
        _fact(
            row_id="fame",
            row_text=row_text,
            attribute="",
            value="추천 명성",
            value_start_offset=2,
        ),
        *[
            _fact(
                row_id="fame",
                row_text=row_text,
                attribute=attribute,
                value=value,
                value_start_offset=offset,
            )
            for attribute, value, offset in (
                ("매칭 난이도", "73,993", 10),
                ("1단계", "98,171", 20),
                ("2단계", "105,881", 30),
                ("3단계", "112,621", 40),
            )
        ],
    ]

    rows = build_relation_rows(facts)

    assert len(rows) == 1
    assert rows[0]["relation_label"] == "추천 명성"
    assert rows[0]["qualifiers"] == [
        "매칭 난이도",
        "1단계",
        "2단계",
        "3단계",
    ]
    assert render_relation_value(rows[0]) == (
        "매칭 난이도 73,993, 1단계 98,171, "
        "2단계 105,881, 3단계 112,621"
    )


def test_build_relation_rows_recovers_unique_structural_header() -> None:
    fame_text = "| 권장 명성 | 47,684 | 47,684 | 61,757 | 69,300 |"
    difficulty_text = "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |"
    facts = [
        _fact(
            row_id="fame",
            row_text=fame_text,
            attribute="내용",
            value="47,684",
            value_start_offset=10,
        ),
        _fact(
            row_id="difficulty",
            row_text=difficulty_text,
            attribute="내용",
            value="싱글",
            value_start_offset=10,
        ),
    ]

    rows = build_relation_rows(facts)
    fame = next(row for row in rows if row["relation_label"] == "권장 명성")

    assert fame["qualifiers"] == ["싱글", "매칭", "일반", "하드"]
    assert fame["qualifier_source_row_id"] == "difficulty"


def test_build_relation_rows_does_not_guess_ambiguous_header() -> None:
    fame_text = "| 권장 명성 | 1 | 2 |"
    facts = [
        _fact(
            row_id="fame",
            row_text=fame_text,
            attribute="내용",
            value="1",
            value_start_offset=10,
        ),
        _fact(
            row_id="header-a",
            row_text="| 난이도 | 일반 | 하드 |",
            attribute="내용",
            value="일반",
            value_start_offset=10,
        ),
        _fact(
            row_id="header-b",
            row_text="| 유형 | A | B |",
            attribute="내용",
            value="A",
            value_start_offset=10,
        ),
    ]

    rows = build_relation_rows(facts)
    fame = next(row for row in rows if row["relation_label"] == "권장 명성")

    assert fame["qualifiers"] == []


def test_rank_relation_rows_sorts_by_model_score() -> None:
    rows = [
        {"table_id": "t", "row_id": "entry", "relation_label": "입장 명성"},
        {"table_id": "t", "row_id": "recommended", "relation_label": "권장 명성"},
    ]

    ranked = rank_relation_rows(rows, [0.8, 0.2])

    assert ranked[0]["relation_label"] == "입장 명성"


def test_select_explicit_qualifier_values_slices_one_named_column() -> None:
    row = {
        "values": ["47,684", "47,684", "61,757", "69,300"],
        "qualifiers": ["싱글", "매칭", "일반", "하드"],
    }

    values, qualifiers, audit = select_explicit_qualifier_values(
        "나벨 하드 권장 명성은?",
        row,
    )

    assert values == ["69,300"]
    assert qualifiers == ["하드"]
    assert audit == {
        "applied": True,
        "matched_qualifiers": ["하드"],
        "reason": "one_explicit_qualifier",
    }


def test_select_explicit_qualifier_values_keeps_all_without_one_match() -> None:
    row = {
        "values": ["73,993", "98,171"],
        "qualifiers": ["매칭 난이도", "1단계"],
    }

    values, qualifiers, audit = select_explicit_qualifier_values(
        "아포칼립스 권장 명성은?",
        row,
    )

    assert values == ["73,993", "98,171"]
    assert qualifiers == ["매칭 난이도", "1단계"]
    assert audit["applied"] is False
    assert audit["reason"] == "no_explicit_qualifier"


def test_select_explicit_qualifier_values_keeps_all_for_ambiguous_matches() -> None:
    row = {
        "values": ["47,684", "69,300"],
        "qualifiers": ["일반", "하드"],
    }

    values, qualifiers, audit = select_explicit_qualifier_values(
        "일반과 하드 권장 명성은?",
        row,
    )

    assert values == ["47,684", "69,300"]
    assert qualifiers == ["일반", "하드"]
    assert audit["applied"] is False
    assert audit["reason"] == "multiple_explicit_qualifiers"
