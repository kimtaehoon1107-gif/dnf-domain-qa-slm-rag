from __future__ import annotations

import re
from typing import Any, Iterable

from src.v3.product_question_semantics import reward_kind_requested

_ITEM_HEADER = frozenset({"아이템", "아이템명"})
_AVAILABILITY_MARKERS = frozenset({"-", "O", "X"})


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _line_spans(text: str) -> Iterable[tuple[int, int, str]]:
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        yield offset, offset + len(line), line
        offset += len(raw_line)


def _is_reward_kind_question(question: str) -> bool:
    return reward_kind_requested(question)


def _is_clear_reward_chunk(chunk: dict[str, Any]) -> bool:
    return any(
        "클리어" in str(part) and "보상" in str(part)
        for part in chunk.get("heading_path") or []
    )


def _reward_group(intro: str) -> str:
    if "확정" in intro:
        return "확정 보상"
    if "확률" in intro:
        return "확률 보상"
    return "클리어 보상"


def _parent_reward_fragments(
    *,
    candidate_index: int,
    parent_id: str,
    chunks: list[dict[str, Any]],
    document: dict[str, Any],
    temporal: dict[str, Any],
) -> list[dict[str, Any]]:
    in_table = False
    qualifying_table = False
    qualifying_table_open = False
    active_header = False
    active_group = "클리어 보상"
    last_context_line = ""
    seen_items: set[tuple[str, str]] = set()
    fragments: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        source_text = str(chunk.get("display_text") or "")
        for start, end, line in _line_spans(source_text):
            stripped = line.strip()
            if stripped == "[TABLE]":
                in_table = True
                qualifying_table = False
                active_header = False
                active_group = _reward_group(last_context_line)
                continue
            if stripped == "[/TABLE]":
                if qualifying_table:
                    qualifying_table_open = False
                in_table = False
                qualifying_table = False
                active_header = False
                continue
            if not in_table:
                if stripped and not stripped.startswith("#"):
                    last_context_line = stripped
                continue

            cells = _cells(stripped)
            if not cells:
                continue
            first = _compact(cells[0])
            if first in _ITEM_HEADER:
                if not qualifying_table:
                    qualifying_table = True
                    qualifying_table_open = True
                active_header = True
                continue
            if not active_header or len(cells) < 3:
                continue
            if not any(
                cell.strip().upper() in _AVAILABILITY_MARKERS
                for cell in cells[1:]
            ):
                continue
            item = cells[0].strip()
            item_key = (active_group, _compact(item))
            if not item or not item_key[1] or item_key in seen_items:
                continue
            seen_items.add(item_key)
            chunk_id = str(chunk["chunk_id"])
            fragment = fragments.setdefault(
                chunk_id,
                {
                    "chunk": chunk,
                    "start_char": start,
                    "end_char": end,
                    "reward_kind_groups": {},
                },
            )
            fragment["start_char"] = min(fragment["start_char"], start)
            fragment["end_char"] = max(fragment["end_char"], end)
            fragment["reward_kind_groups"].setdefault(active_group, []).append(
                item
            )

    if qualifying_table_open or not fragments:
        return []

    units = []
    for fragment in fragments.values():
        chunk = fragment["chunk"]
        source_text = str(chunk.get("display_text") or "")
        start = int(fragment["start_char"])
        end = int(fragment["end_char"])
        heading = " > ".join(
            str(part).strip()
            for part in chunk.get("heading_path") or []
            if str(part).strip()
        )
        units.append(
            {
                "candidate_ref": str(candidate_index),
                "chunk_id": str(chunk["chunk_id"]),
                "parent_document_id": parent_id,
                "source_id": document.get("source_id"),
                "title": document.get("title") or "",
                "published_at": document.get("published_at"),
                "valid_from": temporal.get(
                    "valid_from", document.get("valid_from")
                ),
                "valid_to": temporal.get("valid_to", document.get("valid_to")),
                "revision_id": document.get("revision_id"),
                "status": temporal.get(
                    "status", document.get("status") or chunk.get("status")
                ),
                "start_char": start,
                "end_char": end,
                "text": source_text[start:end],
                "context_text": heading,
                "unit_kind": "reward_kind_fragment",
                "reward_kind_complete": True,
                "reward_kind_groups": fragment["reward_kind_groups"],
            }
        )
    return units


def build_reward_kind_reservation(
    question: str,
    *,
    parent_ids: list[str],
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    max_fragments: int = 8,
) -> list[dict[str, Any]]:
    """Reserve one complete raid-clear reward list without item allowlists."""

    if not _is_reward_kind_question(question) or max_fragments < 1:
        return []
    for candidate_index, parent_id in enumerate(parent_ids, 1):
        document = documents_by_id.get(parent_id)
        if document is None:
            continue
        chunks = sorted(
            (
                chunk
                for chunk in chunks_by_parent.get(parent_id, [])
                if bool(chunk.get("default_exposure", False))
                and not bool(chunk.get("review_required", False))
                and _is_clear_reward_chunk(chunk)
            ),
            key=lambda row: (
                int(row.get("chunk_index") or 0),
                int(row.get("start_offset") or 0),
                str(row.get("chunk_id") or ""),
            ),
        )
        units = _parent_reward_fragments(
            candidate_index=candidate_index,
            parent_id=parent_id,
            chunks=chunks,
            document=document,
            temporal=temporal_by_document.get(parent_id, {}),
        )
        if units and len(units) <= max_fragments:
            return [
                {**unit, "evidence_ref": f"E{index}"}
                for index, unit in enumerate(units, 1)
            ]
    return []


def build_server_reward_kind_output(
    question: str,
    evidence_units: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Render complete reward item kinds from exact source fragments."""

    if not _is_reward_kind_question(question) or not evidence_units:
        return None
    parent_ids = {
        str(unit.get("parent_document_id") or "") for unit in evidence_units
    }
    if len(parent_ids) != 1 or "" in parent_ids:
        return None
    grouped: dict[str, list[str]] = {}
    refs_by_group: dict[str, list[str]] = {}
    seen_by_group: dict[str, set[str]] = {}
    for unit in evidence_units:
        evidence_ref = str(unit.get("evidence_ref") or "").strip()
        groups = unit.get("reward_kind_groups")
        if (
            not evidence_ref
            or unit.get("unit_kind") != "reward_kind_fragment"
            or not unit.get("reward_kind_complete")
            or not isinstance(groups, dict)
        ):
            return None
        for raw_group, raw_items in groups.items():
            group = str(raw_group).strip()
            if not group or not isinstance(raw_items, list) or not raw_items:
                return None
            grouped.setdefault(group, [])
            refs_by_group.setdefault(group, [])
            seen_by_group.setdefault(group, set())
            for raw_item in raw_items:
                item = str(raw_item).strip()
                key = _compact(item)
                if not item or not key or key in seen_by_group[group]:
                    continue
                grouped[group].append(item)
                seen_by_group[group].add(key)
            if evidence_ref not in refs_by_group[group]:
                refs_by_group[group].append(evidence_ref)
    claims = [
        {
            "text": f"{group} 종류는 {', '.join(items)}입니다.",
            "evidence_refs": refs_by_group[group],
        }
        for group, items in grouped.items()
        if items
    ]
    if not claims:
        return None
    return {"mode": "answer", "claims": claims, "clarification": ""}
