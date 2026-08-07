from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


PARSER_VERSION = "dnf-table-row-atomic-facts-v3.2-arm1.3"
TABLE_IDENTITY_VERSION = "dnf-table-row-atomic-facts-v3.2-arm1.2"
FACT_SCHEMA_VERSION = "dnf-table-row-atomic-fact-v3.2-arm1.1"
MANIFEST_SCHEMA_VERSION = "dnf-table-row-atomic-facts-manifest-v3.2-arm1.1"

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/v3/structured")
DEFAULT_CONTRACT = Path("docs/v3/table_atomic_facts_arm1.md")

TARGET_SOURCE_IDS = frozenset(
    {
        "dnf_account_policy",
        "dnf_event",
        "dnf_faq",
        "dnf_game_guide",
        "dnf_monthly_item",
        "dnf_notice",
        "dnf_seria_shop",
        "dnf_update",
    }
)
SCOPE_TERMS = (
    "비용",
    "가격",
    "판매가",
    "판매 기간",
    "판매기간",
    "삭제일",
    "삭제 일",
    "유효기간",
    "유효 기간",
    "적용 기간",
    "시행일",
    "시행 일",
    "기간",
)
STRUCTURED_SCOPE_TERMS = (
    "명성",
    "입장 조건",
    "입장 레벨",
    "인원 제한",
    "피로도",
    "제한 횟수",
    "보상 횟수",
    "성공 확률",
    "보정치",
    "소모 재료",
    "필요 재료",
    "거래타입",
    "거래 타입",
    "거래유형",
    "거래 유형",
    "구매 제한",
    "구매제한",
    "수량",
    "상태",
    "구성품",
)
SUPPRESSED_IDENTITY_HEADERS = frozenset(
    {
        "구분",
        "분류",
        "항목",
        "대상",
        "단계",
        "등급",
        "레어리티",
        "장비 종류",
        "장비종류",
        "아이템명",
        "아이템 명",
        "상품명",
        "상품 명",
    }
)
ADDITIONAL_IDENTITY_HEADERS = frozenset(
    {
        "아이템 명칭",
        "상품 명칭",
        "판매 아이템",
        "구매 가능 아이템",
        "아바타 부위",
    }
)
IDENTITY_HEADERS = SUPPRESSED_IDENTITY_HEADERS | ADDITIONAL_IDENTITY_HEADERS
TRANSPOSED_SUBJECT_HEADERS = frozenset(
    {
        "아이템명",
        "아이템 명",
        "상품명",
        "상품 명",
    }
)
UNIT_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z])(?:골드|세라|원|개|회|일|시간|분|초|%|개월|주|M)(?![가-힣A-Za-z])"
)
TABLE_PATTERN = re.compile(r"\[TABLE\]\s*\n?(.*?)\n?\[/TABLE\]", re.DOTALL)
PIPE_ROW_PATTERN = re.compile(r"(?m)^\|.*\|[ \t]*$")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest_path(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    return f"{prefix}_sha256_{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"


def _normalized_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).strip("-:：")


def _extract_units(value: str) -> str | None:
    units = []
    for match in UNIT_PATTERN.finditer(value):
        unit = match.group(0)
        if unit not in units:
            units.append(unit)
    return "|".join(units) if units else None


def _pipe_cells(row_text: str) -> list[dict[str, Any]]:
    bars = [index for index, char in enumerate(row_text) if char == "|"]
    cells = []
    for start_bar, end_bar in zip(bars, bars[1:]):
        raw_start = start_bar + 1
        raw_end = end_bar
        raw = row_text[raw_start:raw_end]
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        cells.append(
            {
                "text": raw.strip(),
                "start": raw_start + left,
                "end": raw_start + right,
            }
        )
    return cells


def _caption_before(text: str, table_start: int) -> str:
    window = text[max(0, table_start - 500) : table_start]
    lines = [line.strip() for line in window.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(("|", "[TABLE]", "[/TABLE]", "※", "-")):
            continue
        if any(term in line for term in SCOPE_TERMS):
            return _normalized_label(line.lstrip("# "))
    for line in reversed(lines):
        if not line.startswith(("|", "[TABLE]", "[/TABLE]", "※", "-")):
            return _normalized_label(line.lstrip("# "))
    return ""


def _context_subject(caption: str, heading_path: list[str]) -> str:
    value = caption
    value = re.sub(r"(?:은|는)?\s*(?:아래와\s*같습니다|다음과\s*같습니다)[.]?$", "", value)
    value = re.sub(r"\s*(?:비용|가격|판매가|판매 기간|판매기간|삭제일|유효기간|시행일)(?:은|는)?\s*$", "", value)
    value = _normalized_label(value)
    if value:
        return value
    return _normalized_label(" ".join(heading_path[-2:]))


def _reconstruct_parents(
    chunks: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        if chunk.get("offset_source") == "dom_text":
            grouped[chunk["parent_document_id"]].append(chunk)

    parent_texts: dict[str, str] = {}
    gap_counts: dict[str, int] = {}
    for parent_id, parent_chunks in grouped.items():
        end = max(int(row["end_offset"]) for row in parent_chunks)
        characters: list[str | None] = [None] * end
        for chunk in sorted(parent_chunks, key=lambda row: (row["start_offset"], row["chunk_id"])):
            start = int(chunk["start_offset"])
            display = chunk["display_text"]
            if start + len(display) != int(chunk["end_offset"]):
                raise RuntimeError(f"Chunk offset length mismatch: {chunk['chunk_id']}")
            for index, character in enumerate(display, start=start):
                existing = characters[index]
                if existing is not None and existing != character:
                    raise RuntimeError(f"Conflicting DOM overlap: {parent_id}@{index}")
                characters[index] = character
        gap_counts[parent_id] = sum(value is None for value in characters)
        # Keep parent offsets stable without letting an audit gap marker leak
        # into table captions, subjects, or retrieval text. A line break also
        # prevents headings on either side of a gap from being concatenated.
        parent_texts[parent_id] = "".join(
            value if value is not None else "\n" for value in characters
        )
    return parent_texts, grouped, gap_counts


def _owner_chunk(
    chunks: list[dict[str, Any]], parent_start: int, parent_end: int
) -> dict[str, Any] | None:
    owners = [
        chunk
        for chunk in chunks
        if int(chunk["start_offset"]) <= parent_start
        and int(chunk["end_offset"]) >= parent_end
    ]
    if not owners:
        return None
    return min(
        owners,
        key=lambda row: (
            int(row["end_offset"]) - int(row["start_offset"]),
            row["chunk_id"],
        ),
    )


def _is_target_table(
    *,
    caption: str,
    heading_path: list[str],
    header_cells: list[str],
    data_cells: list[str],
) -> bool:
    scope_text = " ".join([caption, *heading_path, *header_cells])
    if any(term in scope_text for term in SCOPE_TERMS):
        return True
    structured_text = " ".join([*header_cells, *data_cells])
    return any(term in structured_text for term in STRUCTURED_SCOPE_TERMS)


def _row_orientation(header_cells: list[str]) -> str:
    if header_cells and _normalized_label(header_cells[0]) in TRANSPOSED_SUBJECT_HEADERS:
        return "attributes_in_rows"
    return "records_in_rows"


def _has_repeated_header_row(
    header_labels: list[str], row_matches: list[re.Match[str]]
) -> bool:
    for row_match in row_matches:
        row_labels = [
            _normalized_label(cell["text"])
            for cell in _pipe_cells(row_match.group(0))
        ]
        if row_labels == header_labels:
            return True
    return False


def _aligned_row_cells(
    header: list[dict[str, Any]],
    row: list[dict[str, Any]],
    previous_identity: dict[str, str],
) -> tuple[list[dict[str, Any] | None], dict[str, str]]:
    header_labels = [_normalized_label(cell["text"]) for cell in header]
    if len(row) == len(header):
        aligned: list[dict[str, Any] | None] = list(row)
    elif (
        len(row) == len(header) - 1
        and header_labels
        and header_labels[0] in IDENTITY_HEADERS
        and header_labels[0] in previous_identity
    ):
        aligned = [None, *row]
    else:
        aligned = [*row, *([None] * max(0, len(header) - len(row)))]
        aligned = aligned[: len(header)]

    updated = dict(previous_identity)
    for label, cell in zip(header_labels, aligned):
        if label in IDENTITY_HEADERS and cell is not None and cell["text"]:
            updated[label] = _normalized_label(cell["text"])
    return aligned, updated


def _fact_common(
    *,
    table_id: str,
    row_id: str,
    subject: str,
    attribute: str,
    value_cell: dict[str, Any],
    row_text: str,
    row_parent_start: int,
    row_parent_end: int,
    owner: dict[str, Any],
    document: dict[str, Any],
    caption: str,
    orientation: str,
    table_structure_status: str,
    table_review_required: bool,
) -> dict[str, Any]:
    value = value_cell["text"]
    chunk_start = int(owner["start_offset"])
    row_start = row_parent_start - chunk_start
    row_end = row_parent_end - chunk_start
    value_parent_start = row_parent_start + int(value_cell["start"])
    value_parent_end = row_parent_start + int(value_cell["end"])
    attribute = _normalized_label(attribute)
    subject = _normalized_label(subject)
    identity = {
        "table_id": table_id,
        "row_id": row_id,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "source_chunk_id": owner["chunk_id"],
    }
    fact_id = _stable_id("table_fact", identity)
    return {
        "fact_schema_version": FACT_SCHEMA_VERSION,
        "fact_id": fact_id,
        "table_id": table_id,
        "row_id": row_id,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "unit": _extract_units(value),
        "source_chunk_id": owner["chunk_id"],
        "start_offset": row_start,
        "end_offset": row_end,
        "value_start_offset": value_parent_start - chunk_start,
        "value_end_offset": value_parent_end - chunk_start,
        "parent_document_id": owner["parent_document_id"],
        "parent_start_offset": row_parent_start,
        "parent_end_offset": row_parent_end,
        "row_text": row_text,
        "retrieval_text": " | ".join(
            part for part in (caption, subject, attribute, value) if part
        ),
        "table_caption": caption,
        "heading_path": owner.get("heading_path", []),
        "orientation": orientation,
        "table_structure_status": table_structure_status,
        "table_review_required": table_review_required,
        "source_id": owner["source_id"],
        "source_kind": owner["source_kind"],
        "status": owner["status"],
        "default_exposure": owner["default_exposure"],
        "review_required": bool(owner["review_required"] or table_review_required),
        "valid_from": owner.get("valid_from"),
        "valid_to": owner.get("valid_to"),
        "title": document["title"],
        "canonical_url": document["canonical_url"],
    }


def build_table_atomic_facts(
    chunks: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    documents_by_id = {row["document_id"]: row for row in documents}
    parent_texts, chunks_by_parent, gap_counts = _reconstruct_parents(chunks)
    facts: list[dict[str, Any]] = []
    audit = Counter()
    source_tables = Counter()
    source_facts = Counter()

    for parent_id in sorted(parent_texts):
        parent_chunks = chunks_by_parent[parent_id]
        representative = min(parent_chunks, key=lambda row: row["chunk_id"])
        if representative["source_id"] not in TARGET_SOURCE_IDS:
            continue
        document = documents_by_id.get(parent_id)
        if document is None:
            raise RuntimeError(f"Missing normalized document: {parent_id}")
        text = parent_texts[parent_id]
        for table_match in TABLE_PATTERN.finditer(text):
            audit["complete_tables_seen"] += 1
            row_matches = list(PIPE_ROW_PATTERN.finditer(table_match.group(1)))
            if len(row_matches) < 2:
                audit["tables_without_data_rows"] += 1
                continue
            header = _pipe_cells(row_matches[0].group(0))
            header_labels = [_normalized_label(cell["text"]) for cell in header]
            table_parent_start = table_match.start()
            caption = _caption_before(text, table_parent_start)
            heading_owner = _owner_chunk(parent_chunks, table_match.start(), table_match.end())
            heading_path = (
                heading_owner.get("heading_path", []) if heading_owner is not None else []
            )
            if not _is_target_table(
                caption=caption,
                heading_path=heading_path,
                header_cells=header_labels,
                data_cells=[
                    _normalized_label(cell["text"])
                    for row_match in row_matches[1:]
                    for cell in _pipe_cells(row_match.group(0))
                    if cell["text"]
                ],
            ):
                audit["tables_outside_arm1_scope"] += 1
                continue
            audit["target_tables"] += 1
            source_tables[representative["source_id"]] += 1
            table_id = _stable_id(
                "table",
                {
                    "parent_document_id": parent_id,
                    "start": table_match.start(),
                    "end": table_match.end(),
                    "parser_version": TABLE_IDENTITY_VERSION,
                },
            )
            orientation = _row_orientation(header_labels)
            table_review_required = _has_repeated_header_row(
                header_labels, row_matches[1:]
            )
            table_structure_status = (
                "ambiguous_repeated_header_matrix"
                if table_review_required
                else "atomic_rows"
            )
            if table_review_required:
                audit["tables_requiring_structural_review"] += 1
            context_subject = _context_subject(caption, heading_path)
            previous_identity: dict[str, str] = {}

            for row_match in row_matches[1:]:
                row_text = row_match.group(0)
                row_cells = _pipe_cells(row_text)
                if not row_cells or all(not cell["text"] for cell in row_cells):
                    audit["empty_rows_skipped"] += 1
                    continue
                row_parent_start = table_match.start(1) + row_match.start()
                row_parent_end = table_match.start(1) + row_match.end()
                owner = _owner_chunk(parent_chunks, row_parent_start, row_parent_end)
                if owner is None:
                    audit["rows_without_single_chunk_owner"] += 1
                    continue
                row_id = _stable_id(
                    "table_row",
                    {
                        "table_id": table_id,
                        "parent_start": row_parent_start,
                        "parent_end": row_parent_end,
                        "row_text": row_text,
                    },
                )
                row_facts = []
                if orientation == "attributes_in_rows":
                    attribute = _normalized_label(row_cells[0]["text"])
                    for column, value_cell in enumerate(row_cells[1:], start=1):
                        if column >= len(header) or not value_cell["text"]:
                            continue
                        subject = _normalized_label(
                            " ".join(
                                value
                                for value in (context_subject, header[column]["text"])
                                if value
                            )
                        )
                        row_facts.append(
                            _fact_common(
                                table_id=table_id,
                                row_id=row_id,
                                subject=subject,
                                attribute=attribute,
                                value_cell=value_cell,
                                row_text=row_text,
                                row_parent_start=row_parent_start,
                                row_parent_end=row_parent_end,
                                owner=owner,
                                document=document,
                                caption=caption,
                                orientation=orientation,
                                table_structure_status=table_structure_status,
                                table_review_required=table_review_required,
                            )
                        )
                else:
                    aligned, previous_identity = _aligned_row_cells(
                        header, row_cells, previous_identity
                    )
                    identity_values = []
                    additional_identity_present = False
                    for label, cell in zip(header_labels, aligned):
                        value = (
                            _normalized_label(cell["text"])
                            if cell is not None and cell["text"]
                            else previous_identity.get(label, "")
                        )
                        if label in IDENTITY_HEADERS and value:
                            identity_values.append(value)
                            additional_identity_present = (
                                additional_identity_present
                                or label in ADDITIONAL_IDENTITY_HEADERS
                            )
                    subject = _normalized_label(
                        " ".join(
                            value for value in [context_subject, *identity_values] if value
                        )
                    )
                    for label, value_cell in zip(header_labels, aligned):
                        if (
                            label in SUPPRESSED_IDENTITY_HEADERS
                            or value_cell is None
                            or not value_cell["text"]
                        ):
                            continue
                        row_facts.append(
                            _fact_common(
                                table_id=table_id,
                                row_id=row_id,
                                subject=subject,
                                attribute=label,
                                value_cell=value_cell,
                                row_text=row_text,
                                row_parent_start=row_parent_start,
                                row_parent_end=row_parent_end,
                                owner=owner,
                                document=document,
                                caption=caption,
                                orientation=orientation,
                                table_structure_status=table_structure_status,
                                table_review_required=table_review_required,
                            )
                        )
                if not row_facts:
                    audit["rows_without_atomic_facts"] += 1
                    continue
                audit["rows_emitted"] += 1
                audit["facts_emitted"] += len(row_facts)
                if orientation == "records_in_rows" and additional_identity_present:
                    audit["rows_with_additional_identity_alias"] += 1
                    audit["facts_with_additional_identity_alias"] += len(row_facts)
                if table_review_required:
                    audit["facts_requiring_structural_review"] += len(row_facts)
                source_facts[owner["source_id"]] += len(row_facts)
                facts.extend(row_facts)

    facts.sort(
        key=lambda row: (
            row["parent_document_id"],
            row["parent_start_offset"],
            row["source_chunk_id"],
            row["subject"],
            row["attribute"],
            row["fact_id"],
        )
    )
    if len({row["fact_id"] for row in facts}) != len(facts):
        raise RuntimeError("Duplicate table atomic fact IDs")
    replacement_character_count = sum(
        value.count("\ufffd")
        for fact in facts
        for value in (
            fact["table_caption"],
            fact["subject"],
            fact["retrieval_text"],
        )
    )
    if replacement_character_count:
        raise RuntimeError(
            "Replacement character leaked into table atomic fact text: "
            f"{replacement_character_count}"
        )
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    offset_mismatches = 0
    value_offset_mismatches = 0
    for fact in facts:
        chunk = chunks_by_id[fact["source_chunk_id"]]
        if chunk["display_text"][fact["start_offset"] : fact["end_offset"]] != fact["row_text"]:
            offset_mismatches += 1
        if (
            chunk["display_text"][
                fact["value_start_offset"] : fact["value_end_offset"]
            ]
            != fact["value"]
        ):
            value_offset_mismatches += 1
    audit_payload = {
        **dict(sorted(audit.items())),
        "source_table_counts": dict(sorted(source_tables.items())),
        "source_fact_counts": dict(sorted(source_facts.items())),
        "parent_gap_character_count": sum(gap_counts.values()),
        "row_offset_mismatches": offset_mismatches,
        "value_offset_mismatches": value_offset_mismatches,
        "replacement_character_count": replacement_character_count,
        "fact_count": len(facts),
        "row_count": len({row["row_id"] for row in facts}),
        "table_count": len({row["table_id"] for row in facts}),
    }
    return facts, audit_payload


def freeze_table_atomic_facts(
    *,
    root: Path,
    chunks_path: Path,
    documents_path: Path,
    output_dir: Path,
    contract_path: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    facts, audit = build_table_atomic_facts(chunks, documents)
    fact_bytes = _serialize_jsonl(facts, lambda row: row["fact_id"])
    fact_sha256 = hashlib.sha256(fact_bytes).hexdigest()
    fact_path = output_dir / f"table_atomic_facts_v3.2_{fact_sha256}.jsonl"
    write_immutable(fact_path, fact_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "arm": "arm1_table_row_atomic_facts_additive",
        "parser_version": PARSER_VERSION,
        "table_identity_version": TABLE_IDENTITY_VERSION,
        "inputs": {
            "dirty_canonical_chunks": {
                "path": chunks_path.relative_to(root).as_posix(),
                "sha256": file_sha256(chunks_path),
                "row_count": len(chunks),
            },
            "normalized_documents": {
                "path": documents_path.relative_to(root).as_posix(),
                "sha256": file_sha256(documents_path),
                "row_count": len(documents),
            },
            "contract": {
                "path": contract_path.relative_to(root).as_posix(),
                "sha256": file_sha256(contract_path),
            },
            "parser_source": {
                "path": _manifest_path(root, Path(__file__)),
                "sha256": file_sha256(Path(__file__).resolve()),
            },
        },
        "scope": {
            "source_ids": sorted(TARGET_SOURCE_IDS),
            "scope_terms": list(SCOPE_TERMS),
            "structured_scope_terms": list(STRUCTURED_SCOPE_TERMS),
            "complete_dom_tables_only": True,
            "additive_parent_preservation": True,
        },
        "artifact": {
            "path": fact_path.relative_to(root).as_posix(),
            "sha256": fact_sha256,
            "row_count": len(facts),
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest) + b"\n"
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output_dir / f"table_atomic_facts_arm1_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)
    return fact_path, manifest_path, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build additive v3.2 table row facts")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    fact_path, manifest_path, manifest = freeze_table_atomic_facts(
        root=root,
        chunks_path=(root / args.chunks).resolve(),
        documents_path=(root / args.documents).resolve(),
        output_dir=(root / args.output_dir).resolve(),
        contract_path=(root / args.contract).resolve(),
    )
    print(
        json.dumps(
            {
                "artifact": fact_path.relative_to(root).as_posix(),
                "manifest": manifest_path.relative_to(root).as_posix(),
                "audit": manifest["audit"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
