from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


_GENERIC_ATTRIBUTES = frozenset({"", "내용", "값"})
_FACTUAL_TOKEN = re.compile(r"\d")


def split_markdown_row(row_text: str) -> list[str]:
    """Split one Markdown table row while preserving escaped pipes."""

    text = str(row_text or "").strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if char == "\\" and not escaped:
            escaped = True
            current.append(char)
            continue
        if char == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        escaped = False
    cells.append("".join(current).strip())
    return cells


def _compact(value: Any) -> str:
    return re.sub(r"[\s,]+", "", str(value or "").casefold())


def _relation_row(
    facts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    representative = min(facts, key=lambda row: str(row["fact_id"]))
    cells = split_markdown_row(str(representative.get("row_text") or ""))
    if len(cells) < 2 or not cells[0]:
        return None
    label, values = cells[0], cells[1:]
    ordered_facts = sorted(
        facts,
        key=lambda row: (
            int(row.get("value_start_offset") or 0),
            str(row["fact_id"]),
        ),
    )
    value_facts = [
        row
        for row in ordered_facts
        if str(row.get("attribute") or "").strip()
        not in _GENERIC_ATTRIBUTES
        and _compact(row.get("value")) != _compact(label)
    ]
    qualifiers: list[str] = []
    if len(value_facts) == len(values) and all(
        _compact(fact.get("value")) == _compact(value)
        for fact, value in zip(value_facts, values, strict=True)
    ):
        qualifiers = [
            str(fact.get("attribute") or "").strip()
            for fact in value_facts
        ]
    return {
        "table_id": representative["table_id"],
        "row_id": representative["row_id"],
        "parent_document_id": representative["parent_document_id"],
        "source_chunk_id": representative["source_chunk_id"],
        "title": str(representative.get("title") or ""),
        "heading_path": list(representative.get("heading_path") or []),
        "table_caption": str(representative.get("table_caption") or ""),
        "relation_label": label,
        "values": values,
        "qualifiers": qualifiers,
        "row_text": str(representative.get("row_text") or ""),
        "start_offset": int(representative["start_offset"]),
        "end_offset": int(representative["end_offset"]),
        "status": representative.get("status"),
    }


def _looks_like_structural_header(
    values: list[str],
) -> bool:
    return bool(values) and all(
        value
        and not _FACTUAL_TOKEN.search(value)
        and len(value) <= 40
        for value in values
    )


def build_relation_rows(
    facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build selectable relation rows from exact table rows.

    The relation is always taken from the first source-table cell. Multi-value
    rows reuse atomic-fact column labels when available. When the source parser
    flattened those labels, a unique same-width textual row is used only as a
    structural header.
    """

    by_row: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        by_row[(str(fact["table_id"]), str(fact["row_id"]))].append(fact)
    rows = [
        row
        for grouped in by_row.values()
        if (row := _relation_row(grouped)) is not None
    ]
    by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_table[row["table_id"]].append(row)
    for row in rows:
        if row["qualifiers"] or len(row["values"]) < 2:
            continue
        candidates = [
            sibling
            for sibling in by_table[row["table_id"]]
            if sibling["row_id"] != row["row_id"]
            and len(sibling["values"]) == len(row["values"])
            and _looks_like_structural_header(sibling["values"])
        ]
        if len(candidates) == 1:
            row["qualifiers"] = list(candidates[0]["values"])
            row["qualifier_source_row_id"] = candidates[0]["row_id"]
    return sorted(
        rows,
        key=lambda row: (
            row["title"],
            row["table_caption"],
            row["start_offset"],
            row["row_id"],
        ),
    )


def relation_selector_text(row: dict[str, Any]) -> str:
    heading = " > ".join(str(value) for value in row["heading_path"])
    return "\n".join(
        value
        for value in (
            f"문서: {row['title']}",
            f"섹션: {heading}" if heading else "",
            f"표: {row['table_caption']}" if row["table_caption"] else "",
            f"질문 가능한 항목: {row['relation_label']}",
        )
        if value
    )


def rank_relation_rows(
    rows: list[dict[str, Any]],
    scores: list[float],
) -> list[dict[str, Any]]:
    if len(rows) != len(scores):
        raise RuntimeError("relation row score count mismatch")
    ranked = [
        {**row, "relation_score": round(float(score), 8)}
        for row, score in zip(rows, scores, strict=True)
    ]
    return sorted(
        ranked,
        key=lambda row: (
            -float(row["relation_score"]),
            row["table_id"],
            row["row_id"],
        ),
    )


def render_relation_value(row: dict[str, Any]) -> str:
    values = list(row["values"])
    qualifiers = list(row.get("qualifiers") or [])
    if qualifiers and len(qualifiers) == len(values):
        return ", ".join(
            f"{qualifier} {value}"
            for qualifier, value in zip(qualifiers, values, strict=True)
        )
    return ", ".join(values)


def select_explicit_qualifier_values(
    question: str,
    row: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Select one table column only when its exact header occurs in the question."""

    values = list(row.get("values") or [])
    qualifiers = list(row.get("qualifiers") or [])
    if not qualifiers or len(qualifiers) != len(values):
        return values, qualifiers, {
            "applied": False,
            "matched_qualifiers": [],
            "reason": "qualifiers_unavailable",
        }
    compact_question = _compact(question)
    matched = [
        qualifier
        for qualifier in qualifiers
        if _compact(qualifier)
        and _compact(qualifier) in compact_question
    ]
    if len(matched) != 1:
        return values, qualifiers, {
            "applied": False,
            "matched_qualifiers": matched,
            "reason": (
                "no_explicit_qualifier"
                if not matched
                else "multiple_explicit_qualifiers"
            ),
        }
    qualifier = matched[0]
    index = qualifiers.index(qualifier)
    return [values[index]], [qualifier], {
        "applied": True,
        "matched_qualifiers": [qualifier],
        "reason": "one_explicit_qualifier",
    }
