from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


ASSEMBLER_VERSION = "dnf-table-group-completeness-v3.2-arm1.2"
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(value) if len(token) > 1}


def _table_subject(caption: str) -> str:
    value = " ".join(caption.split())
    value = re.sub(r"(?:은|는)?\s*(?:아래와\s*같습니다|다음과\s*같습니다)[.]?$", "", value)
    value = re.sub(r"\s*(?:비용|가격|판매가)(?:은|는)?\s*$", "", value)
    return value.strip()


def _row_label(subject: str, table_subject: str) -> str:
    if table_subject and subject.startswith(table_subject):
        label = subject[len(table_subject) :].strip()
        if label:
            return label
    return subject


def _escape_markdown(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def build_complete_table_view(
    table_facts: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not table_facts:
        raise RuntimeError("A table view requires at least one atomic fact")
    table_ids = {row["table_id"] for row in table_facts}
    parent_ids = {row["parent_document_id"] for row in table_facts}
    if len(table_ids) != 1 or len(parent_ids) != 1:
        raise RuntimeError("A complete table view must use one table and one parent")

    caption = table_facts[0]["table_caption"]
    table_subject = _table_subject(caption)
    heading_path = list(table_facts[0].get("heading_path") or [])
    scope_parts = list(
        dict.fromkeys(
            value
            for value in [table_facts[0]["title"], *heading_path]
            if value
        )
    )
    by_row: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in table_facts:
        by_row[fact["row_id"]].append(fact)

    attribute_positions: dict[str, int] = {}
    for fact in table_facts:
        relative = int(fact["value_start_offset"]) - int(fact["start_offset"])
        attribute_positions[fact["attribute"]] = min(
            relative,
            attribute_positions.get(fact["attribute"], relative),
        )
    attributes = sorted(
        attribute_positions,
        key=lambda value: (attribute_positions[value], value),
    )

    rows = []
    exact_mismatches = 0
    for row_id, facts in sorted(
        by_row.items(),
        key=lambda item: (
            min(int(row["parent_start_offset"]) for row in item[1]),
            item[0],
        ),
    ):
        representative = min(facts, key=lambda row: row["fact_id"])
        chunk = chunks_by_id[representative["source_chunk_id"]]
        exact = chunk["display_text"][
            representative["start_offset"] : representative["end_offset"]
        ]
        if exact != representative["row_text"]:
            exact_mismatches += 1
        values = {row["attribute"]: row["value"] for row in facts}
        rows.append(
            {
                "row_id": row_id,
                "label": _row_label(representative["subject"], table_subject),
                "subject": representative["subject"],
                "values": {attribute: values.get(attribute) for attribute in attributes},
                "source_chunk_id": representative["source_chunk_id"],
                "start_offset": representative["start_offset"],
                "end_offset": representative["end_offset"],
                "exact_row_text": exact,
                "complete_attribute_count": sum(
                    values.get(attribute) is not None for attribute in attributes
                ),
            }
        )

    header = ["구분", *attributes]
    markdown = [
        f"### {caption}",
        "",
        "| " + " | ".join(_escape_markdown(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        markdown.append(
            "| "
            + " | ".join(
                [_escape_markdown(row["label"])]
                + [
                    _escape_markdown(row["values"].get(attribute) or "—")
                    for attribute in attributes
                ]
            )
            + " |"
        )
    markdown.extend(
        [
            "",
            "각 행은 원본 표의 exact slice이며, 행 선택 시 부모 표 문맥을 함께 표시합니다.",
        ]
    )
    return {
        "assembler_version": ASSEMBLER_VERSION,
        "table_id": table_facts[0]["table_id"],
        "parent_document_id": table_facts[0]["parent_document_id"],
        "caption": caption,
        "table_subject": table_subject,
        "title": table_facts[0]["title"],
        "heading_path": heading_path,
        "scope_title": " > ".join(scope_parts),
        "canonical_url": table_facts[0]["canonical_url"],
        "attributes": attributes,
        "rows": rows,
        "row_count": len(rows),
        "exact_offset_mismatch_count": exact_mismatches,
        "all_rows_have_all_attributes": all(
            row["complete_attribute_count"] == len(attributes) for row in rows
        ),
        "rendered_markdown": "\n".join(markdown) + "\n",
    }


def assemble_table_group_answers(
    *,
    query: str,
    ranked_seed_facts: list[dict[str, Any]],
    all_facts: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not ranked_seed_facts:
        return []
    preferred_parent = ranked_seed_facts[0]["parent_document_id"]
    parent_facts = [
        row for row in all_facts if row["parent_document_id"] == preferred_parent
    ]
    if not parent_facts:
        return []
    by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in parent_facts:
        by_table[fact["table_id"]].append(fact)

    query_tokens = _tokens(query)
    scored = []
    for table_id, facts in by_table.items():
        searchable = " ".join(
            [
                facts[0]["table_caption"],
                facts[0]["title"],
                *list(facts[0].get("heading_path") or []),
                *[row["subject"] for row in facts],
                *[row["attribute"] for row in facts],
            ]
        )
        score = len(query_tokens & _tokens(searchable))
        seeded = any(row["table_id"] == table_id for row in ranked_seed_facts)
        scored.append((score, seeded, table_id, facts))
    max_score = max(score for score, _, _, _ in scored)
    if max_score == 0:
        selected = [row for row in scored if row[1]]
    else:
        selected = [row for row in scored if row[0] == max_score]
    return [
        build_complete_table_view(facts, chunks_by_id=chunks_by_id)
        for _, _, _, facts in sorted(
            selected,
            key=lambda row: (
                min(int(fact["parent_start_offset"]) for fact in row[3]),
                row[2],
            ),
        )
    ]
