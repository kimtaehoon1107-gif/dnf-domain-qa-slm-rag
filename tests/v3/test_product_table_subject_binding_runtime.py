from src.v3.product_evidence_pack import (
    _atomic_reranker_text,
    _query_score,
    _ranking_context_text,
    _requirement_score,
)
from src.v3.simple_evidence_refs import _chunk_atomic_units


def _table_units(text: str) -> list[dict[str, object]]:
    return _chunk_atomic_units(
        candidate_index=1,
        chunk_id="chunk-1",
        chunk={
            "parent_document_id": "doc-1",
            "display_text": text,
            "heading_path": ["업데이트", "개선 및 변경 사항"],
        },
        document={
            "source_id": "dnf_update",
            "title": "업데이트 안내",
        },
        temporal={},
    )


def test_table_rows_keep_introducer_and_existing_subject() -> None:
    units = _table_units(
        "- 스킬 개화 옵션이 변경됩니다.\n"
        "[TABLE]\n"
        "| 구분 | 값 |\n"
        "| 아이템명 | 타이드 바운드 |\n"
        "| 기본 쿨타임 | 12초 → 9초 |\n"
        "[/TABLE]"
    )
    row = next(unit for unit in units if "기본 쿨타임" in str(unit["text"]))
    assert "표 도입: - 스킬 개화 옵션이 변경됩니다." in str(
        row["context_text"]
    )
    assert "표 대상: | 아이템명 | 타이드 바운드 |" in str(
        row["context_text"]
    )


def test_table_introducer_does_not_cross_note_heading_or_length_cap() -> None:
    cases = (
        "실제 대상입니다.\n※ 주의사항입니다.\n[TABLE]\n| 구분 | 값 |\n| A | 1 |\n[/TABLE]",
        "실제 대상입니다.\n## 새 절\n[TABLE]\n| 구분 | 값 |\n| A | 1 |\n[/TABLE]",
        f"{'가' * 161}\n[TABLE]\n| 구분 | 값 |\n| A | 1 |\n[/TABLE]",
    )
    for text in cases:
        rows = [
            unit
            for unit in _table_units(text)
            if unit["unit_kind"] == "table_row"
        ]
        assert rows
        assert all(
            "표 도입:" not in str(row["context_text"])
            for row in rows
        )


def test_ranking_context_includes_introducer_and_subject() -> None:
    with_intro = {
        "candidate_ref": "1",
        "start_char": 10,
        "title": "업데이트 안내",
        "context_text": (
            "업데이트 > 표 헤더: | 전 | 후 | > "
            "표 도입: - 스킬 개화 옵션 > 표 대상: | 아이템명 | 타이드 |"
        ),
        "text": "| 기본 쿨타임 12초 | 기본 쿨타임 9초 |",
    }
    without_intro = {
        **with_intro,
        "context_text": (
            "업데이트 > 표 헤더: | 전 | 후 | > "
            "표 대상: | 아이템명 | 타이드 |"
        ),
    }
    assert _ranking_context_text(with_intro) == with_intro["context_text"]
    assert "표 도입: - 스킬 개화 옵션" in _atomic_reranker_text(
        with_intro
    )
    assert _query_score(with_intro, "스킬 개화 옵션 쿨타임") > _query_score(
        without_intro,
        "스킬 개화 옵션 쿨타임",
    )
    assert _requirement_score(
        with_intro,
        query="스킬 개화 옵션 쿨타임",
        subject="스킬 개화 옵션",
    ) > _requirement_score(
        without_intro,
        query="스킬 개화 옵션 쿨타임",
        subject="스킬 개화 옵션",
    )
    assert _atomic_reranker_text(with_intro) != _atomic_reranker_text(
        without_intro
    )
