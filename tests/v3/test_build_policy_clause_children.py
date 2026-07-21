from __future__ import annotations

from src.v3.build_policy_clause_children import (
    extract_policy_children,
    reconstruct_document_text,
)


def _document() -> dict:
    return {
        "document_id": "document_policy",
        "source_id": "dnf_account_policy",
        "source_kind": "account_policy",
        "status": "current",
        "default_exposure": True,
        "valid_from": "2026-03-15",
        "valid_to": None,
        "title": "운영정책",
    }


def test_reconstruct_document_uses_exact_overlap() -> None:
    chunks = [
        {"chunk_id": "a", "start_offset": 0, "end_offset": 6, "display_text": "abcdef"},
        {"chunk_id": "b", "start_offset": 4, "end_offset": 10, "display_text": "efghij"},
    ]

    text, conflicts, gaps = reconstruct_document_text(chunks)

    assert text == "abcdefghij"
    assert conflicts == 0
    assert gaps == 0


def test_numbered_clause_and_table_row_keep_exact_offsets() -> None:
    text = "[2-1-1] 첫 조항의 답입니다.\n[TABLE]\n| 구분 | 1차 |\n| 사칭 | 100일 |\n[2-1-2] 다음 답입니다."
    children = extract_policy_children(_document(), text)

    assert {row["child_kind"] for row in children} == {"numbered_clause", "table_row"}
    assert all(text[row["start_offset"]:row["end_offset"]] == row["display_text"] for row in children)
    assert {row["clause_or_row_id"] for row in children if row["child_kind"] == "numbered_clause"} == {"2-1-1", "2-1-2"}


def test_legacy_paragraph_excludes_revision_list_and_toc() -> None:
    text = "시행일자\n2026년 03월 15일\n1. 기본 운영 방침\n이 문장은 실제 운영정책 본문으로 충분히 깁니다."
    children = extract_policy_children(_document(), text)

    assert [row["display_text"] for row in children] == ["이 문장은 실제 운영정책 본문으로 충분히 깁니다."]
