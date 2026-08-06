from src.v3.run_free_simple_rag_top3_visibility import (
    _value_variants,
)


def test_date_value_variants_cover_korean_document_dates() -> None:
    assert _value_variants("2026-06-04") == (
        "2026-06-04",
        "2026.06.04",
        "2026년 6월 4일",
        "6월 4일",
        "6/4",
    )


def test_non_date_value_is_preserved() -> None:
    assert _value_variants("63,257") == ("63,257",)
