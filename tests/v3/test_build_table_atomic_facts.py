from __future__ import annotations

import json
from pathlib import Path

from src.v3.build_corpus import file_sha256
from src.v3.build_table_atomic_facts import (
    build_table_atomic_facts,
    freeze_table_atomic_facts,
)


def _chunk(
    text: str,
    *,
    chunk_id: str = "chunk_1",
    start_offset: int = 0,
    source_id: str = "dnf_game_guide",
    heading_path: list[str] | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": "document_1",
        "parent_content_hash": "a" * 64,
        "display_text": text,
        "retrieval_text": text,
        "start_offset": start_offset,
        "end_offset": start_offset + len(text),
        "offset_source": "dom_text",
        "heading_path": (
            ["NPC 장비 초월", "비용"]
            if heading_path is None
            else heading_path
        ),
        "source_id": source_id,
        "source_kind": "game_guide",
        "status": "current",
        "default_exposure": True,
        "review_required": False,
        "valid_from": None,
        "valid_to": None,
    }


def _document() -> dict:
    return {
        "document_id": "document_1",
        "title": "초월",
        "canonical_url": "https://example.test/guide?no=1",
    }


def test_row_facts_preserve_merged_identity_and_exact_offsets() -> None:
    text = """### 비용
115Lv 장비 초월 비용은 아래와 같습니다.
[TABLE]
| 장비 종류 | 구분 | 소울 | 골드 |
| 무기 | 레어 | 75개 | 10,000골드 |
| 유니크 | 60개 | 20,000골드 |
[/TABLE]"""
    facts, audit = build_table_atomic_facts([_chunk(text)], [_document()])

    unique_gold = next(
        row
        for row in facts
        if row["subject"] == "115Lv 장비 초월 무기 유니크"
        and row["attribute"] == "골드"
    )
    assert unique_gold["value"] == "20,000골드"
    assert unique_gold["unit"] == "골드"
    assert text[unique_gold["start_offset"] : unique_gold["end_offset"]] == unique_gold["row_text"]
    assert text[
        unique_gold["value_start_offset"] : unique_gold["value_end_offset"]
    ] == unique_gold["value"]
    assert audit["row_offset_mismatches"] == 0
    assert audit["value_offset_mismatches"] == 0


def test_transposed_shop_table_emits_subject_attribute_value() -> None:
    text = """### 상품 가격
판매 가격은 아래와 같습니다.
[TABLE]
| 아이템명 | A 상자 | B 상자 |
| 가격 | 1,000세라 | 2,000세라 |
| 삭제일 | 8월 1일 | 9월 1일 |
[/TABLE]"""
    facts, _ = build_table_atomic_facts([_chunk(text)], [_document()])

    selected = next(
        row
        for row in facts
        if row["subject"].endswith("B 상자") and row["attribute"] == "삭제일"
    )
    assert selected["value"] == "9월 1일"
    assert selected["orientation"] == "attributes_in_rows"
    assert "B 상자 | 삭제일 | 9월 1일" in selected["retrieval_text"]


def test_identity_alias_binds_item_name_without_dropping_source_value() -> None:
    text = """### 상품 가격
[TABLE]
| 아이템 명칭 | 아이템 가격 | 기간제한 |
| 황토색 염색약 | 2 골드 코인 | 무제한 |
[/TABLE]"""
    facts, _ = build_table_atomic_facts([_chunk(text)], [_document()])

    price = next(row for row in facts if row["attribute"] == "아이템 가격")
    assert price["subject"].endswith("황토색 염색약")
    assert "황토색 염색약 | 아이템 가격 | 2 골드 코인" in price["retrieval_text"]
    assert any(
        row["attribute"] == "아이템 명칭" and row["value"] == "황토색 염색약"
        for row in facts
    )


def test_repeated_header_matrix_is_preserved_but_quarantined() -> None:
    text = """### 기간 무제한 카드
[TABLE]
| A 카드 | B 카드 |
| 옵션 A | 옵션 B |
| A 카드 | B 카드 |
[/TABLE]"""
    facts, audit = build_table_atomic_facts([_chunk(text)], [_document()])

    assert facts
    assert audit["tables_requiring_structural_review"] == 1
    assert {row["table_structure_status"] for row in facts} == {
        "ambiguous_repeated_header_matrix"
    }
    assert all(row["table_review_required"] for row in facts)
    assert all(row["review_required"] for row in facts)


def test_parent_gap_does_not_leak_replacement_character_into_fact_text() -> None:
    heading = "### NPC 상점"
    table = """### 상점
[TABLE]
| 구분 | 가격 |
| A | 100골드 |
[/TABLE]"""
    chunks = [
        _chunk(heading, chunk_id="chunk_1"),
        _chunk(table, chunk_id="chunk_2", start_offset=len(heading) + 1),
    ]

    facts, audit = build_table_atomic_facts(chunks, [_document()])

    assert facts
    assert audit["parent_gap_character_count"] == 1
    assert audit["replacement_character_count"] == 0
    assert {row["table_caption"] for row in facts} == {"상점"}
    assert all(
        "\ufffd" not in row[field]
        for row in facts
        for field in ("table_caption", "subject", "retrieval_text")
    )


def test_requirement_table_emits_entry_and_recommended_fame() -> None:
    text = """## 콘텐츠 정보
[TABLE]
| 구분 | 내용 |
| 입장 명성 | 63,257 |
| 권장 명성 | 63,257 / 76,599 / 81,799 |
| 입장 시 소모 피로도 | 없음 |
[/TABLE]"""

    facts, audit = build_table_atomic_facts([_chunk(text)], [_document()])

    assert any(
        row["subject"].endswith("입장 명성")
        and row["attribute"] == "내용"
        and row["value"] == "63,257"
        for row in facts
    )
    assert any(
        row["subject"].endswith("권장 명성")
        and row["attribute"] == "내용"
        and row["value"] == "63,257 / 76,599 / 81,799"
        for row in facts
    )
    assert audit["target_tables"] == 1
    assert audit["row_offset_mismatches"] == 0
    assert audit["value_offset_mismatches"] == 0


def test_update_source_requirement_table_is_in_scope() -> None:
    text = """## 시나리오 던전 정보
[TABLE]
| 구분 | 내용 |
| 던전명 | 최후의 과업 |
| 입장 조건 | 115레벨 액트 퀘스트 수락 |
| 입장 명성 | 없음 |
[/TABLE]"""

    facts, _ = build_table_atomic_facts(
        [_chunk(text, source_id="dnf_update")],
        [_document()],
    )

    assert any(
        row["subject"].endswith("입장 명성")
        and row["value"] == "없음"
        and row["source_id"] == "dnf_update"
        for row in facts
    )


def test_structured_term_in_caption_alone_does_not_expand_scope() -> None:
    text = """### 아포칼립스 3단계 당첨자
[TABLE]
| 서버 | 캐릭터명 | 서버 | 캐릭터명 |
| 디레지에 | 모험가A | 카인 | 모험가B |
[/TABLE]"""

    facts, audit = build_table_atomic_facts(
        [
            _chunk(
                text,
                source_id="dnf_notice",
                heading_path=["아포칼립스 3단계 당첨자"],
            )
        ],
        [_document()],
    )

    assert facts == []
    assert audit["tables_outside_arm1_scope"] == 1


def test_freeze_is_deterministic_and_input_is_unchanged(tmp_path: Path) -> None:
    text = """가격
[TABLE]
| 구분 | 가격 |
| A | 100골드 |
[/TABLE]"""
    chunks_path = tmp_path / "chunks.jsonl"
    documents_path = tmp_path / "documents.jsonl"
    contract_path = tmp_path / "contract.md"
    chunks_path.write_text(json.dumps(_chunk(text), ensure_ascii=False) + "\n", encoding="utf-8")
    documents_path.write_text(json.dumps(_document(), ensure_ascii=False) + "\n", encoding="utf-8")
    contract_path.write_text("contract\n", encoding="utf-8")
    chunk_hash = file_sha256(chunks_path)

    first = freeze_table_atomic_facts(
        root=tmp_path,
        chunks_path=chunks_path,
        documents_path=documents_path,
        output_dir=tmp_path / "out",
        contract_path=contract_path,
    )
    second = freeze_table_atomic_facts(
        root=tmp_path,
        chunks_path=chunks_path,
        documents_path=documents_path,
        output_dir=tmp_path / "out",
        contract_path=contract_path,
    )

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert file_sha256(chunks_path) == chunk_hash
