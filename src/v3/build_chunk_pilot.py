from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    normalize_space,
    parse_fixed_timestamp,
    write_immutable,
)
from src.v3.schemas import NORMALIZED_CHUNK_SCHEMA_VERSION


CHUNKER_VERSION = "dnf_offset_chunk_pilot_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_chunk_pilot_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_chunk_pilot_report_v3.1"
TOKEN_COUNT_METHOD = "unicode_word_punct_v1"
MIN_MULTI_CHUNK_CHARS = 80

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CONTENTS = Path(
    "data/v3/normalized/"
    "document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl"
)
DEFAULT_NORMALIZED_MANIFEST = Path(
    "data/v3/normalized/"
    "normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json"
)
DEFAULT_CHUNK_DIR = Path("data/v3/chunks")
DEFAULT_REPORT_DIR = Path("reports/v3")

SOURCE_TARGETS = {
    "dnf_account_policy": 5,
    "dnf_event": 6,
    "dnf_faq": 16,
    "dnf_game_guide": 8,
    "dnf_monthly_item": 4,
    "dnf_notice": 12,
    "dnf_seria_shop": 6,
    "dnf_update": 6,
}

SOURCE_CONFIG = {
    "dnf_account_policy": (1800, 200),
    "dnf_event": (1400, 160),
    "dnf_faq": (1200, 120),
    "dnf_game_guide": (1400, 160),
    "dnf_monthly_item": (1400, 160),
    "dnf_notice": (1200, 120),
    "dnf_seria_shop": (1400, 160),
    "dnf_update": (1400, 160),
}


@dataclass(frozen=True)
class Unit:
    start: int
    end: int
    kind: str
    heading_path: tuple[str, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_rank(document: dict[str, Any]) -> str:
    return _sha256_bytes(document["document_id"].encode("utf-8"))


def _take(
    selected: dict[str, set[str]],
    documents: list[dict[str, Any]],
    reason: str,
    count: int | None = None,
) -> None:
    rows = sorted(documents, key=_stable_rank)
    if count is not None:
        rows = rows[:count]
    for document in rows:
        selected.setdefault(document["document_id"], set()).add(reason)


def _fill_diverse(
    selected: dict[str, set[str]],
    documents: list[dict[str, Any]],
    *,
    source_id: str,
    target: int,
) -> None:
    source_rows = [row for row in documents if row["source_id"] == source_id]
    current = [row for row in source_rows if row["document_id"] in selected]
    need = target - len(current)
    if need <= 0:
        return
    candidates = [row for row in source_rows if row["document_id"] not in selected]
    seen = {tuple(row["category_path"]) for row in current}
    diverse: list[dict[str, Any]] = []
    for document in sorted(
        candidates, key=lambda row: (tuple(row["category_path"]), _stable_rank(row))
    ):
        category = tuple(document["category_path"])
        if category in seen:
            continue
        diverse.append(document)
        seen.add(category)
        if len(diverse) == need:
            break
    remaining = [row for row in candidates if row not in diverse]
    picked = diverse + sorted(remaining, key=_stable_rank)[: need - len(diverse)]
    _take(selected, picked, f"{source_id}:deterministic_diverse_fill")


def select_pilot_documents(
    documents: list[dict[str, Any]],
    contents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: dict[str, set[str]] = {}
    _take(
        selected,
        [row for row in documents if contents_by_id[row["document_id"]]["visual_evidence"]],
        "all_visual_evidence_documents",
    )

    guide_lineages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        if document["source_id"] == "dnf_game_guide":
            guide_lineages[document["lineage_id"]].append(document)
    for lineage_rows in guide_lineages.values():
        if len(lineage_rows) > 1:
            _take(selected, lineage_rows, "all_material_guide_revisions")

    policy_rows = sorted(
        (row for row in documents if row["source_id"] == "dnf_account_policy"),
        key=lambda row: (row.get("valid_from") or "", row["document_id"]),
    )
    policy_indexes = sorted(
        {0, len(policy_rows) // 4, len(policy_rows) // 2, 3 * len(policy_rows) // 4, len(policy_rows) - 1}
    )
    for index in policy_indexes:
        _take(selected, [policy_rows[index]], "account_policy_time_stratum")

    notice_rows = [row for row in documents if row["source_id"] == "dnf_notice"]
    for source_kind in sorted({row["source_kind"] for row in notice_rows}):
        _take(
            selected,
            [row for row in notice_rows if row["source_kind"] == source_kind],
            f"notice_source_kind:{source_kind}",
            2,
        )

    update_rows = [row for row in documents if row["source_id"] == "dnf_update"]
    for status, count in (("current", 3), ("unknown", 3)):
        _take(
            selected,
            [row for row in update_rows if row["status"] == status],
            f"update_status:{status}",
            count,
        )

    for source_id, per_status in (("dnf_monthly_item", 2), ("dnf_seria_shop", 3)):
        source_rows = [row for row in documents if row["source_id"] == source_id]
        for status in sorted({row["status"] for row in source_rows}):
            _take(
                selected,
                [row for row in source_rows if row["status"] == status],
                f"{source_id}_status:{status}",
                per_status,
            )

    for source_id, target in SOURCE_TARGETS.items():
        _fill_diverse(selected, documents, source_id=source_id, target=target)

    selected_documents = [row for row in documents if row["document_id"] in selected]
    actual_counts = Counter(row["source_id"] for row in selected_documents)
    if actual_counts != Counter(SOURCE_TARGETS):
        raise RuntimeError(
            f"Pilot source distribution differs from contract: {dict(actual_counts)}"
        )
    rows = []
    for document in sorted(
        selected_documents, key=lambda row: (row["source_id"], row["canonical_url"], row["fetched_at"])
    ):
        content = contents_by_id[document["document_id"]]
        rows.append(
            {
                "selection_schema_version": "dnf_chunk_pilot_selection_v3.1",
                "chunker_version": CHUNKER_VERSION,
                "document_id": document["document_id"],
                "canonical_url": document["canonical_url"],
                "source_id": document["source_id"],
                "source_kind": document["source_kind"],
                "status": document["status"],
                "default_exposure": document["default_exposure"],
                "category_path": document["category_path"],
                "text_length": len(content["text"]),
                "has_visual_evidence": content["visual_evidence"] is not None,
                "selection_reasons": sorted(selected[document["document_id"]]),
            }
        )
    return rows


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_long_span(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    spans = []
    cursor = start
    while end - cursor > max_chars:
        target = cursor + max_chars
        floor = cursor + max(1, int(max_chars * 0.6))
        candidates = [
            text.rfind(". ", floor, target),
            text.rfind("다. ", floor, target),
            text.rfind(" ", floor, target),
        ]
        boundary = max(candidates)
        cut = boundary + 1 if boundary >= floor else target
        span = _trim_span(text, cursor, cut)
        if span[0] < span[1]:
            spans.append(span)
        cursor = cut
    span = _trim_span(text, cursor, end)
    if span[0] < span[1]:
        spans.append(span)
    return spans


def make_units(text: str, max_chars: int) -> list[Unit]:
    units: list[Unit] = []
    headings: list[str] = []
    position = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = position
        position += len(raw_line)
        line_end = position
        while line_end > line_start and text[line_end - 1] in "\r\n":
            line_end -= 1
        start, end = _trim_span(text, line_start, line_end)
        if start >= end:
            continue
        stripped = text[start:end]
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            label = normalize_space(heading_match.group(2))
            headings = headings[: level - 1]
            while len(headings) < level - 1:
                headings.append("")
            headings.append(label)
            units.append(Unit(start, end, "heading", tuple(value for value in headings if value)))
            continue
        kind = "table" if "|" in stripped else "text"
        if end - start <= max_chars:
            units.append(Unit(start, end, kind, tuple(value for value in headings if value)))
            continue
        for split_start, split_end in _split_long_span(text, start, end, max_chars):
            units.append(
                Unit(split_start, split_end, kind, tuple(value for value in headings if value))
            )
    if position < len(text):
        start, end = _trim_span(text, position, len(text))
        if start < end:
            for split_start, split_end in _split_long_span(text, start, end, max_chars):
                units.append(Unit(split_start, split_end, "text", tuple(headings)))
    return units


def _unit_sections(units: list[Unit]) -> list[list[Unit]]:
    sections: list[list[Unit]] = []
    current: list[Unit] = []
    for unit in units:
        if unit.kind == "heading" and current:
            sections.append(current)
            current = []
        current.append(unit)
    if current:
        sections.append(current)
    return sections


def _pack_section(
    section: list[Unit], max_chars: int, overlap_chars: int
) -> list[tuple[int, int, tuple[str, ...], list[Unit], bool]]:
    chunks = []
    index = 0
    while index < len(section):
        start = section[index].start
        end_index = index
        while end_index + 1 < len(section):
            candidate = section[end_index + 1]
            if candidate.end - start > max_chars:
                break
            end_index += 1
        end = section[end_index].end
        oversized_atomic = end - start > max_chars and index == end_index
        included = section[index : end_index + 1]
        chunks.append((start, end, section[index].heading_path, included, oversized_atomic))
        if end_index == len(section) - 1:
            break
        overlap_floor = max(start + 1, end - overlap_chars)
        next_index = end_index + 1
        for candidate_index in range(index + 1, end_index + 1):
            if section[candidate_index].start >= overlap_floor:
                next_index = candidate_index
                break
        if next_index <= index:
            next_index = index + 1
        index = next_index
    return chunks


def _merged_chunk_type(left: str, right: str) -> str:
    kinds = {left, right}
    if "mixed" in kinds or ("table" in kinds and len(kinds) > 1):
        return "mixed"
    if kinds == {"table"}:
        return "table"
    if "section" in kinds:
        return "section"
    return "text"


def _merge_short_spans(
    text: str, spans: list[dict[str, Any]], max_chars: int
) -> list[dict[str, Any]]:
    spans = [dict(span) for span in spans]
    while len(spans) > 1:
        short_index = next(
            (
                index
                for index, span in enumerate(spans)
                if len(text[span["start"] : span["end"]]) < MIN_MULTI_CHUNK_CHARS
            ),
            None,
        )
        if short_index is None:
            break
        candidates: list[tuple[int, int, str]] = []
        if short_index + 1 < len(spans):
            combined_length = spans[short_index + 1]["end"] - spans[short_index]["start"]
            if combined_length <= max_chars:
                candidates.append((combined_length, short_index + 1, "next"))
        if short_index > 0:
            combined_length = spans[short_index]["end"] - spans[short_index - 1]["start"]
            if combined_length <= max_chars:
                candidates.append((combined_length, short_index - 1, "previous"))
        if not candidates:
            short = spans[short_index]
            expanded = None
            if short_index + 1 < len(spans):
                right = spans[short_index + 1]
                new_end = min(right["end"], short["start"] + max_chars)
                if new_end - short["start"] >= MIN_MULTI_CHUNK_CHARS:
                    expanded = {
                        **short,
                        "end": new_end,
                        "chunk_type": _merged_chunk_type(
                            short["chunk_type"], right["chunk_type"]
                        ),
                        "oversized_atomic": short["oversized_atomic"]
                        or right["oversized_atomic"],
                    }
            if expanded is None and short_index > 0:
                left = spans[short_index - 1]
                new_start = max(left["start"], short["end"] - max_chars)
                if short["end"] - new_start >= MIN_MULTI_CHUNK_CHARS:
                    expanded = {
                        **short,
                        "start": new_start,
                        "chunk_type": _merged_chunk_type(
                            left["chunk_type"], short["chunk_type"]
                        ),
                        "oversized_atomic": left["oversized_atomic"]
                        or short["oversized_atomic"],
                    }
            if expanded is None:
                break
            spans[short_index] = expanded
            continue
        _, neighbor_index, direction = min(
            candidates, key=lambda item: (item[0], 0 if item[2] == "next" else 1)
        )
        left_index = min(short_index, neighbor_index)
        right_index = max(short_index, neighbor_index)
        left = spans[left_index]
        right = spans[right_index]
        heading_path = left["heading_path"] or right["heading_path"]
        merged = {
            "start": left["start"],
            "end": right["end"],
            "heading_path": heading_path,
            "chunk_type": _merged_chunk_type(left["chunk_type"], right["chunk_type"]),
            "oversized_atomic": left["oversized_atomic"] or right["oversized_atomic"],
        }
        spans[left_index : right_index + 1] = [merged]
    return spans


def split_offset_chunks(
    text: str, max_chars: int, overlap_chars: int
) -> list[dict[str, Any]]:
    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise RuntimeError("Invalid chunk max/overlap configuration")
    units = make_units(text, max_chars)
    if not units and text.strip():
        start, end = _trim_span(text, 0, len(text))
        units = [Unit(start, end, "text", ())]
    result = []
    for section in _unit_sections(units):
        for start, end, heading_path, included, oversized_atomic in _pack_section(
            section, max_chars, overlap_chars
        ):
            kinds = {unit.kind for unit in included}
            if kinds == {"table"}:
                chunk_type = "table"
            elif "table" in kinds:
                chunk_type = "mixed"
            elif "heading" in kinds:
                chunk_type = "section"
            else:
                chunk_type = "text"
            result.append(
                {
                    "start": start,
                    "end": end,
                    "heading_path": list(heading_path),
                    "chunk_type": chunk_type,
                    "oversized_atomic": oversized_atomic,
                }
            )
    return _merge_short_spans(text, result, max_chars)


def _lexical_token_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z가-힣_]+|[^\w\s]", text, re.UNICODE))


def _retrieval_text(title: str, heading_path: list[str], display_text: str) -> str:
    parts = [title]
    breadcrumb = " > ".join(heading_path)
    if breadcrumb and breadcrumb not in title:
        parts.append(breadcrumb)
    parts.append(display_text)
    return "\n".join(part for part in parts if part)


def _chunk_rows_for_source(
    *,
    document: dict[str, Any],
    text: str,
    offset_source: str,
    max_chars: int,
    overlap_chars: int,
    normalized_text_hash: str,
    chunker_version: str = CHUNKER_VERSION,
) -> list[dict[str, Any]]:
    spans = split_offset_chunks(text, max_chars, overlap_chars)
    rows = []
    for index, span in enumerate(spans, start=1):
        display_text = text[span["start"] : span["end"]]
        identity_payload = (
            f"{document['document_id']}\n{offset_source}\n{span['start']}\n{span['end']}\n"
            f"{_sha256_bytes(display_text.encode('utf-8'))}\n{chunker_version}"
        )
        identity = _sha256_bytes(identity_payload.encode("utf-8"))
        visual = offset_source == "visual_ocr"
        rows.append(
            {
                "chunk_schema_version": NORMALIZED_CHUNK_SCHEMA_VERSION,
                "chunk_id": f"chunk_sha256_{identity}",
                "parent_document_id": document["document_id"],
                "source_id": document["source_id"],
                "source_kind": document["source_kind"],
                "status": document["status"],
                "default_exposure": False if visual else document["default_exposure"],
                "heading_path": span["heading_path"],
                "chunk_type": "visual_ocr" if visual else span["chunk_type"],
                "display_text": display_text,
                "retrieval_text": _retrieval_text(
                    document["title"], span["heading_path"], display_text
                ),
                "start_offset": span["start"],
                "end_offset": span["end"],
                "offset_source": offset_source,
                "token_count": _lexical_token_count(display_text),
                "token_count_method": TOKEN_COUNT_METHOD,
                "entities": {},
                "valid_from": document["valid_from"],
                "valid_to": document["valid_to"],
                "evidence_quality": "unverified_ocr" if visual else "official_dom_text",
                "review_required": visual,
                "normalized_text_hash": normalized_text_hash,
                "parent_content_hash": document["content_hash"],
                "chunker_version": chunker_version,
                "chunk_index": index,
                "chunk_count": len(spans),
                "max_chars": max_chars,
                "overlap_chars": overlap_chars,
                "oversized_atomic": span["oversized_atomic"],
            }
        )
    return rows


def build_chunks_for_selection(
    selection: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    contents_by_id: dict[str, dict[str, Any]],
    *,
    chunker_version: str = CHUNKER_VERSION,
) -> list[dict[str, Any]]:
    rows = []
    for selected in selection:
        document = documents_by_id[selected["document_id"]]
        content = contents_by_id[selected["document_id"]]
        max_chars, overlap_chars = SOURCE_CONFIG[document["source_id"]]
        rows.extend(
            _chunk_rows_for_source(
                document=document,
                text=content["text"],
                offset_source="dom_text",
                max_chars=max_chars,
                overlap_chars=overlap_chars,
                normalized_text_hash=content["text_hash"],
                chunker_version=chunker_version,
            )
        )
        visual = content["visual_evidence"]
        if visual:
            rows.extend(
                _chunk_rows_for_source(
                    document=document,
                    text=visual["text"],
                    offset_source="visual_ocr",
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                    normalized_text_hash=visual["text_hash"],
                    chunker_version=chunker_version,
                )
            )
    return sorted(
        rows,
        key=lambda row: (
            row["source_id"],
            row["parent_document_id"],
            row["offset_source"],
            row["start_offset"],
            row["chunk_id"],
        ),
    )


def _render_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DNF RAG v3 ChunkV3 파일럿 보고서",
        "",
        f"- chunker: `{report['chunker_version']}`",
        f"- built_at: `{report['built_at']}`",
        f"- manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## 결과",
        "",
        "| documents | DOM chunks | visual OCR chunks | table/mixed | default exposure chunks |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {summary['selected_documents']} | {summary['dom_chunks']} | "
            f"{summary['visual_ocr_chunks']} | {summary['table_or_mixed_chunks']} | "
            f"{summary['default_exposure_chunks']} |"
        ),
        "",
        "## 출처별",
        "",
        "| source | documents | DOM chunks | visual chunks |",
        "|---|---:|---:|---:|",
    ]
    for source_id, values in report["by_source"].items():
        lines.append(
            f"| `{source_id}` | {values['documents']} | {values['dom_chunks']} | "
            f"{values['visual_ocr_chunks']} |"
        )
    lines.extend(
        [
            "",
            "## 게이트",
            "",
            *[f"- {key}: `{value}`" for key, value in report["gates"].items()],
            "",
            f"전체 ChunkV3 진입: **{report['full_chunking_decision']}**",
            "",
            "visual OCR chunk는 review_required이며 default exposure=false다. BM25, dense index, Router, 학습은 실행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_chunk_pilot(
    *,
    built_at: str,
    documents_path: Path,
    contents_path: Path,
    normalized_manifest_path: Path,
    chunk_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    parse_fixed_timestamp(built_at)
    input_paths = [documents_path, contents_path, normalized_manifest_path]
    for path in input_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    input_hashes = {path: file_sha256(path) for path in input_paths}
    documents = read_jsonl(documents_path)
    contents = read_jsonl(contents_path)
    documents_by_id = {row["document_id"]: row for row in documents}
    contents_by_id = {row["document_id"]: row for row in contents}
    if len(documents_by_id) != len(documents) or len(contents_by_id) != len(contents):
        raise RuntimeError("Duplicate document_id in normalized input")
    if set(documents_by_id) != set(contents_by_id):
        raise RuntimeError("Normalized document/content ID sets differ")

    selection = select_pilot_documents(documents, contents_by_id)
    chunks = build_chunks_for_selection(selection, documents_by_id, contents_by_id)
    selection_bytes = _serialize_jsonl(selection, lambda row: row["document_id"])
    selection_sha256 = _sha256_bytes(selection_bytes)
    selection_path = chunk_dir / f"chunk_pilot_selection_{selection_sha256}.jsonl"
    write_immutable(selection_path, selection_bytes)
    chunk_bytes = _serialize_jsonl(
        chunks,
        lambda row: (
            row["source_id"],
            row["parent_document_id"],
            row["offset_source"],
            row["start_offset"],
            row["chunk_id"],
        ),
    )
    chunk_sha256 = _sha256_bytes(chunk_bytes)
    chunk_path = chunk_dir / f"chunks_pilot_{chunk_sha256}.jsonl"
    write_immutable(chunk_path, chunk_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "built_at": built_at,
        "inputs": [
            {"role": "normalized_documents", "path": documents_path.as_posix(), "sha256": input_hashes[documents_path], "row_count": len(documents)},
            {"role": "normalized_contents", "path": contents_path.as_posix(), "sha256": input_hashes[contents_path], "row_count": len(contents)},
            {"role": "normalized_manifest", "path": normalized_manifest_path.as_posix(), "sha256": input_hashes[normalized_manifest_path], "row_count": None},
        ],
        "source_config": {
            key: {"max_chars": value[0], "overlap_chars": value[1]}
            for key, value in sorted(SOURCE_CONFIG.items())
        },
        "selection": {"path": selection_path.as_posix(), "sha256": selection_sha256, "row_count": len(selection)},
        "chunks": {"path": chunk_path.as_posix(), "sha256": chunk_sha256, "row_count": len(chunks)},
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_path = chunk_dir / f"chunk_pilot_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    selected_ids = {row["document_id"] for row in selection}
    dom_chunks = [row for row in chunks if row["offset_source"] == "dom_text"]
    visual_chunks = [row for row in chunks if row["offset_source"] == "visual_ocr"]
    offset_mismatches = 0
    for chunk in chunks:
        content = contents_by_id[chunk["parent_document_id"]]
        source_text = (
            content["text"]
            if chunk["offset_source"] == "dom_text"
            else content["visual_evidence"]["text"]
        )
        if source_text[chunk["start_offset"] : chunk["end_offset"]] != chunk["display_text"]:
            offset_mismatches += 1
    dom_counts = Counter(row["parent_document_id"] for row in dom_chunks)
    orphan_chunks = sum(
        dom_counts[row["parent_document_id"]] > 1
        and len(row["display_text"]) < MIN_MULTI_CHUNK_CHARS
        for row in dom_chunks
    )
    gates = {
        "selection_count_is_63": len(selection) == 63,
        "all_eight_sources_represented": len({row["source_id"] for row in selection}) == 8,
        "all_four_statuses_represented": {row["status"] for row in selection}
        == {"current", "expired", "superseded", "unknown"},
        "all_18_visual_documents_represented": sum(row["has_visual_evidence"] for row in selection) == 18,
        "selected_document_without_dom_chunk": len(selected_ids - set(dom_counts)),
        "offset_mismatches": offset_mismatches,
        "duplicate_chunk_ids": len(chunks) - len({row["chunk_id"] for row in chunks}),
        "empty_display_or_retrieval_text": sum(
            not row["display_text"] or not row["retrieval_text"] for row in chunks
        ),
        "oversized_atomic_chunks": sum(row["oversized_atomic"] for row in chunks),
        "orphan_multi_document_chunks": orphan_chunks,
        "default_exposure_policy_violations": sum(
            row["default_exposure"]
            and (
                row["status"] not in {"current", "upcoming"}
                or row["source_kind"] in {"preview_patch", "roadmap_statement"}
            )
            for row in chunks
        ),
        "visual_ocr_default_exposure_violations": sum(
            row["default_exposure"] or not row["review_required"] for row in visual_chunks
        ),
    }
    gate_go = all(
        value is True if isinstance(value, bool) else value == 0
        for value in gates.values()
    )
    by_source = {}
    for source_id in sorted(SOURCE_TARGETS):
        selected_source = [row for row in selection if row["source_id"] == source_id]
        source_chunks = [row for row in chunks if row["source_id"] == source_id]
        by_source[source_id] = {
            "documents": len(selected_source),
            "dom_chunks": sum(row["offset_source"] == "dom_text" for row in source_chunks),
            "visual_ocr_chunks": sum(row["offset_source"] == "visual_ocr" for row in source_chunks),
            "max_dom_chunk_chars": max(
                (len(row["display_text"]) for row in source_chunks if row["offset_source"] == "dom_text"),
                default=0,
            ),
        }
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "built_at": built_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "summary": {
            "selected_documents": len(selection),
            "dom_chunks": len(dom_chunks),
            "visual_ocr_chunks": len(visual_chunks),
            "table_or_mixed_chunks": sum(
                row["chunk_type"] in {"table", "mixed"} for row in dom_chunks
            ),
            "heading_path_chunks": sum(bool(row["heading_path"]) for row in dom_chunks),
            "default_exposure_chunks": sum(row["default_exposure"] for row in chunks),
            "status": dict(sorted(Counter(row["status"] for row in selection).items())),
        },
        "by_source": by_source,
        "gates": gates,
        "full_chunking_decision": "GO" if gate_go else "NO-GO",
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = _sha256_bytes(report_bytes)
    report_json_path = report_dir / f"chunk_pilot_{report_sha256}.json"
    report_markdown_path = report_dir / f"chunk_pilot_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_markdown_path, _render_report(report).encode("utf-8"))
    for path, digest in input_hashes.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f"Input changed while building chunk pilot: {path}")
    return {
        "selection_path": selection_path.as_posix(),
        "selection_sha256": selection_sha256,
        "chunk_path": chunk_path.as_posix(),
        "chunk_sha256": chunk_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_markdown_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": by_source,
        "full_chunking_decision": report["full_chunking_decision"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic source-stratified offset-preserving ChunkV3 pilot."
    )
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--contents", type=Path, default=DEFAULT_CONTENTS)
    parser.add_argument("--normalized-manifest", type=Path, default=DEFAULT_NORMALIZED_MANIFEST)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_chunk_pilot(
        built_at=args.built_at,
        documents_path=args.documents,
        contents_path=args.contents,
        normalized_manifest_path=args.normalized_manifest,
        chunk_dir=args.chunk_dir,
        report_dir=args.report_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
