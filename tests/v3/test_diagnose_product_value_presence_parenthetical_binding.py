from __future__ import annotations

from src.v3.diagnose_product_value_presence_parenthetical_binding import (
    build_p32_review_rows,
    classify_orphan_fragment,
    extract_numeric_orphan_fragments,
    score_requirement_value_presence,
    sentence_spans_with_parenthetical_binding,
    value_present,
)


def test_value_present_normalizes_date_order_spacing_and_currency() -> None:
    date_ok, _ = value_present(
        "2025-09-11 점검 후",
        "25.09.11 점검 후부터 적용됩니다.",
        value_type="date_range",
        as_of="2026-08-05",
    )
    order_ok, _ = value_present(
        "숫자 6자리",
        "6자리 숫자를 입력합니다.",
        value_type="number",
        as_of="2026-08-05",
    )
    spacing_ok, _ = value_present(
        "264칸",
        "264 칸으로 확장됩니다.",
        value_type="number",
        as_of="2026-08-05",
    )
    currency_ok, _ = value_present(
        "무기 강화권[리노] 상자 2,000만 골드",
        "무기 강화권[리노] 상자는 2000만 골드입니다.",
        value_type="structured_values",
        as_of="2026-08-05",
    )
    assert date_ok and order_ok and spacing_ok and currency_ok


def test_value_present_requires_descriptive_binding() -> None:
    present, detail = value_present(
        "무기 강화권[리노] 상자 2,000만 골드",
        "| 상점판매가격 | 2,000만 골드 | 1,000만 골드 |",
        value_type="structured_values",
        as_of="2026-08-05",
    )
    assert not present
    assert detail["token_coverage"] < 0.8


def test_requirement_assignment_exposes_partial_overlap() -> None:
    requirement = {
        "requirement_id": "limits",
        "expected_status": "supported",
        "value_type": "structured_values",
        "required_values": ["1일 200만원", "1월 500만원"],
        "acceptable_evidence_units": [
            {"chunk_id": "chunk-1", "start_char": 10, "end_char": 30}
        ],
    }
    result = score_requirement_value_presence(
        requirement,
        evidence_pack=[
            {
                "evidence_ref": "E1",
                "chunk_id": "chunk-1",
                "start_char": 10,
                "end_char": 20,
                "text": "| 1일(만원) | 200 |",
            }
        ],
        as_of="2026-08-05",
    )
    assert result["overlap_visible"]
    assert result["value_presence"] == "value_present_partial"


def test_runtime_binding_removes_same_line_numeric_orphan() -> None:
    chunks = [
        {
            "source_id": "dnf_update",
            "source_kind": "update",
            "chunk_id": "chunk-1",
            "parent_document_id": "doc-1",
            "chunk_index": 1,
            "display_text": (
                "- 쿨타임이 감소합니다. (20초 → 18초)\n"
                "독립 문장입니다. 다음 문장도 끝납니다.\n"
                "[TABLE]\n| 값 | 10 |\n[/TABLE]"
                "\n설명입니다. | 가격 | 100 |"
            ),
        }
    ]
    rows = extract_numeric_orphan_fragments(chunks)
    assert rows == []
    assert classify_orphan_fragment("20초 → 18초") == "arrow"


def test_p32_review_requires_the_fully_reviewed_corpus() -> None:
    try:
        build_p32_review_rows(
            [
                {
                    "fragment_type": "parenthetical",
                    "fragment_text": "(20초 → 18초)",
                }
            ]
        )
    except RuntimeError as error:
        assert "104-row corpus" in str(error)
    else:
        raise AssertionError("partial review input must not be accepted")


def test_shadow_binding_merges_only_complete_same_line_parenthetical() -> None:
    text = "- 쿨타임이 감소합니다. (20초 → 18초)"
    spans = sentence_spans_with_parenthetical_binding(text, line_start=100)
    assert spans[0] == (
        100,
        100 + len("- 쿨타임이 감소합니다. (20초 → 18초)"),
        "- 쿨타임이 감소합니다. (20초 → 18초)",
    )
    assert len(spans) == 1


def test_shadow_binding_leaves_incomplete_date_parenthesis_unmerged() -> None:
    text = "적용됩니다. (2012년은 6월 7일"
    spans = sentence_spans_with_parenthetical_binding(text, line_start=0)
    assert spans[0][2] == "적용됩니다."
    assert spans[1][2] == "(2012년은 6월 7일"
