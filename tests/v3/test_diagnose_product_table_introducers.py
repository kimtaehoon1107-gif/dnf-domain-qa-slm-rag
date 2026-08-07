from src.v3.diagnose_product_table_introducers import (
    _line_kind,
    select_table_introducer,
)


def _select(text: str, *, note_policy: str = "skip", max_chars: int = 200):
    lines = text.splitlines()
    return select_table_introducer(
        lines,
        lines.index("[TABLE]"),
        note_policy=note_policy,
        max_chars=max_chars,
    )


def test_selects_previous_sentence() -> None:
    selected = _select("질풍 스킬 개화 옵션이 변경됩니다.\n[TABLE]")
    assert selected["introducer"] == "질풍 스킬 개화 옵션이 변경됩니다."
    assert selected["classification"] == "sentence"


def test_stop_policy_does_not_cross_note() -> None:
    selected = _select(
        "실제 표 대상입니다.\n* 사용 시 주의사항입니다.\n[TABLE]",
        note_policy="stop",
    )
    assert selected["introducer"] == ""
    assert selected["reason"] == "stop_note"


def test_skip_policy_can_recover_introducer_above_note() -> None:
    selected = _select(
        "실제 표 대상입니다.\n※ 사용 시 주의사항입니다.\n[TABLE]",
        note_policy="skip",
    )
    assert selected["introducer"] == "실제 표 대상입니다."
    assert selected["skipped_notes"] == ["※ 사용 시 주의사항입니다."]


def test_does_not_cross_heading_or_previous_table() -> None:
    assert _select("이전 문단\n## 새 절\n[TABLE]")["reason"] == "stop_heading"
    assert _select("이전 문단\n[/TABLE]\n[TABLE]")["reason"] == "stop_table_boundary"
    assert _select("이전 문단\n| 값 | 값 |\n[TABLE]")["reason"] == "stop_table_row"


def test_item_number_is_classified_separately() -> None:
    selected = _select("10. 아바타(남)\n[TABLE]")
    assert selected["classification"] == "item_number"


def test_long_line_and_chunk_start_return_none() -> None:
    assert _select("긴 문장입니다.\n[TABLE]", max_chars=3)["reason"] == "too_long"
    assert _select("[TABLE]")["reason"] == "chunk_start"


def test_note_classifier_is_structural() -> None:
    assert _line_kind("※ 주의") == "note"
    assert _line_kind("* 주의") == "note"
