from __future__ import annotations

from src.v3.assemble_table_group_answers import (
    assemble_table_group_answers,
    build_complete_table_view,
)


def _fact(
    *,
    table_id: str,
    row_id: str,
    subject: str,
    attribute: str,
    value: str,
    row_text: str,
    row_start: int,
    value_start: int,
    caption: str,
) -> dict:
    return {
        "fact_id": f"{table_id}:{row_id}:{attribute}",
        "table_id": table_id,
        "row_id": row_id,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "source_chunk_id": "chunk_1",
        "start_offset": row_start,
        "end_offset": row_start + len(row_text),
        "value_start_offset": row_start + value_start,
        "value_end_offset": row_start + value_start + len(value),
        "parent_document_id": "document_1",
        "parent_start_offset": row_start,
        "parent_end_offset": row_start + len(row_text),
        "row_text": row_text,
        "table_caption": caption,
        "title": "초월",
        "canonical_url": "https://example.test/guide",
    }


def _fixture() -> tuple[list[dict], dict[str, dict]]:
    rows = [
        ("유니크", "25개", "125,000골드"),
        ("레전더리", "60개", "1,250,000골드"),
        ("에픽", "200개", "3,750,000골드"),
        ("태초", "500개", "15,000,000골드"),
    ]
    text_parts = []
    facts = []
    cursor = 0
    for ordinal, (rarity, soul, gold) in enumerate(rows, 1):
        row_text = f"| {rarity} | {soul} | {gold} |"
        text_parts.append(row_text)
        for attribute, value in (("광휘의 소울", soul), ("골드", gold)):
            facts.append(
                _fact(
                    table_id="table_oath",
                    row_id=f"row_{ordinal}",
                    subject=f"서약 결정 초월 {rarity}",
                    attribute=attribute,
                    value=value,
                    row_text=row_text,
                    row_start=cursor,
                    value_start=row_text.index(value),
                    caption="서약 결정 초월 비용은 아래와 같습니다.",
                )
            )
        cursor += len(row_text) + 1
    text = "\n".join(text_parts)
    return facts, {"chunk_1": {"display_text": text}}


def test_complete_view_keeps_all_rarities_and_attributes() -> None:
    facts, chunks = _fixture()
    view = build_complete_table_view(facts, chunks_by_id=chunks)

    assert [row["label"] for row in view["rows"]] == [
        "유니크",
        "레전더리",
        "에픽",
        "태초",
    ]
    assert view["attributes"] == ["광휘의 소울", "골드"]
    assert view["all_rows_have_all_attributes"]
    assert view["exact_offset_mismatch_count"] == 0
    assert "| 유니크 | 25개 | 125,000골드 |" in view["rendered_markdown"]
    assert "| 태초 | 500개 | 15,000,000골드 |" in view["rendered_markdown"]


def test_query_selects_best_matching_table_without_dropping_rows() -> None:
    facts, chunks = _fixture()
    other = {
        **facts[0],
        "fact_id": "other",
        "table_id": "table_equipment",
        "row_id": "other_row",
        "subject": "115Lv 장비 초월 유니크",
        "table_caption": "115Lv 장비 초월 비용은 아래와 같습니다.",
    }
    all_facts = [*facts, other]

    views = assemble_table_group_answers(
        query="서약 결정 초월 가격",
        ranked_seed_facts=[facts[0]],
        all_facts=all_facts,
        chunks_by_id=chunks,
    )

    assert len(views) == 1
    assert views[0]["table_id"] == "table_oath"
    assert views[0]["row_count"] == 4


def test_generic_query_keeps_equally_relevant_tables_in_same_parent() -> None:
    facts, chunks = _fixture()
    other_rows = []
    for index, rarity in enumerate(("유니크", "레전더리", "에픽", "태초"), 1):
        row_text = facts[(index - 1) * 2]["row_text"]
        other_rows.append(
            {
                **facts[(index - 1) * 2],
                "fact_id": f"other_{index}",
                "table_id": "table_equipment",
                "row_id": f"other_row_{index}",
                "subject": f"115Lv 장비 초월 {rarity}",
                "table_caption": "115Lv 장비 초월 비용은 아래와 같습니다.",
                "row_text": row_text,
            }
        )

    views = assemble_table_group_answers(
        query="초월 가격",
        ranked_seed_facts=[facts[0], other_rows[0]],
        all_facts=[*facts, *other_rows],
        chunks_by_id=chunks,
    )

    assert {view["table_id"] for view in views} == {"table_oath", "table_equipment"}
    assert all(view["row_count"] == 4 for view in views)
