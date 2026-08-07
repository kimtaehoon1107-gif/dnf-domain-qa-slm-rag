from __future__ import annotations

from src.v3.simple_evidence_refs import (
    _sentence_spans,
    _should_bind_trailing_parenthetical,
)


def test_runtime_binds_reviewed_numeric_parenthetical_with_exact_coordinates() -> None:
    text = "- 타이드 바운드 - 쿨타임이 감소합니다. (20초 → 18초)"
    assert _sentence_spans(text, line_start=189) == [
        (189, 189 + len(text), text)
    ]


def test_runtime_keeps_incomplete_boundary_parenthetical_separate() -> None:
    text = "적용됩니다. (2012년은 6월 7일"
    assert [span[2] for span in _sentence_spans(text, line_start=0)] == [
        "적용됩니다.",
        "(2012년은 6월 7일",
    ]


def test_runtime_requires_all_six_registered_conditions() -> None:
    previous_text = "완료됨."
    valid_text = "(20초 → 18초)"
    previous = (0, len(previous_text), previous_text)
    valid = (
        len(previous_text) + 1,
        len(previous_text) + 1 + len(valid_text),
        valid_text,
    )
    assert _should_bind_trailing_parenthetical(
        previous,
        valid,
        line="완료됨. (20초 → 18초)",
        line_start=0,
    )
    for invalid_text in (
        "(20초 → 18초",
        "(변경 예정)",
        "(" + "1" * 31 + ")",
        "(20초입니다)",
    ):
        fragment = (
            len(previous_text) + 1,
            len(previous_text) + 1 + len(invalid_text),
            invalid_text,
        )
        assert not _should_bind_trailing_parenthetical(
            previous,
            fragment,
            line="완료됨. " + fragment[2],
            line_start=0,
        )


def test_runtime_requires_sentence_boundary_and_whitespace_gap() -> None:
    fragment_text = "(20초 → 18초)"
    assert not _should_bind_trailing_parenthetical(
        (0, len("완료됨"), "완료됨"),
        (
            len("완료됨") + 2,
            len("완료됨") + 2 + len(fragment_text),
            fragment_text,
        ),
        line="완료됨  (20초 → 18초)",
        line_start=0,
    )
    assert not _should_bind_trailing_parenthetical(
        (0, len("완료됨."), "완료됨."),
        (
            len("완료됨.") + 1,
            len("완료됨.") + 1 + len(fragment_text),
            fragment_text,
        ),
        line="완료됨.x(20초 → 18초)",
        line_start=0,
    )
