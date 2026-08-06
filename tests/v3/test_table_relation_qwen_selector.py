from __future__ import annotations

import pytest

from src.v3.table_relation_qwen_selector import (
    RelationSelection,
    build_relation_options,
    selected_relation_values,
    validate_relation_selection,
)


def _row() -> dict[str, object]:
    return {
        "title": "만들어진 신 나벨",
        "heading_path": ["콘텐츠 정보"],
        "table_caption": "콘텐츠 정보",
        "relation_label": "권장 명성",
        "values": ["47,684", "47,684", "61,757", "69,300"],
        "qualifiers": ["싱글", "매칭", "일반", "하드"],
    }


def test_select_requires_supplied_id_and_exact_qualifier() -> None:
    _, by_id = build_relation_options([_row()])
    selection = RelationSelection(
        mode="select",
        selection_id="R1",
        qualifier="하드",
    )

    selected = validate_relation_selection(selection, by_id)
    values, qualifiers = selected_relation_values(
        selected or {},
        selection.qualifier,
    )

    assert selected is by_id["R1"]
    assert values == ["69,300"]
    assert qualifiers == ["하드"]


def test_select_without_qualifier_returns_complete_row() -> None:
    _, by_id = build_relation_options([_row()])
    selection = RelationSelection(mode="select", selection_id="R1")

    selected = validate_relation_selection(selection, by_id)
    values, qualifiers = selected_relation_values(selected or {}, "")

    assert values == ["47,684", "47,684", "61,757", "69,300"]
    assert qualifiers == ["싱글", "매칭", "일반", "하드"]


@pytest.mark.parametrize(
    ("selection", "reason"),
    [
        (
            RelationSelection(mode="select", selection_id="R9"),
            "unknown_relation_selection_id",
        ),
        (
            RelationSelection(
                mode="select",
                selection_id="R1",
                qualifier="악연",
            ),
            "unknown_relation_qualifier",
        ),
        (
            RelationSelection(mode="clarification"),
            "clarification_text_required",
        ),
        (
            RelationSelection(
                mode="clarification",
                selection_id="R1",
                clarification="어떤 보상인가요?",
            ),
            "non_select_must_not_choose_evidence",
        ),
    ],
)
def test_invalid_selection_fails_closed(
    selection: RelationSelection,
    reason: str,
) -> None:
    _, by_id = build_relation_options([_row()])

    with pytest.raises(RuntimeError, match=reason):
        validate_relation_selection(selection, by_id)


def test_clarification_selects_no_evidence() -> None:
    _, by_id = build_relation_options([_row()])
    selection = RelationSelection(
        mode="clarification",
        clarification="보상 아이템과 보상 횟수 중 무엇을 찾으시나요?",
    )

    assert validate_relation_selection(selection, by_id) is None
