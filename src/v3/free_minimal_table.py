from __future__ import annotations

import re
from typing import Any

from src.v3.assemble_table_group_answers import (
    assemble_table_group_answers,
)


_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_EQUIPMENT_OPERATIONS = ("초월", "조율", "승급", "강화")
_GENERIC_QUERY_TOKENS = frozenset(
    {
        "가격",
        "비용",
        "알려줘",
        "필요",
        "장비",
        "개",
        "몇",
        "때",
        "하려면",
        "얼마",
        "확률",
    }
)
_ATTRIBUTE_KEYWORDS = (
    "가격",
    "거래타입",
    "거래유형",
    "삭제",
    "구매제한",
    "판매기간",
    "순례의인장",
    "상급원소결정",
    "레어리티별소울",
    "보이드소울",
    "성공확률",
    "확률",
)
_GENERIC_VALUE_ATTRIBUTES = frozenset({"내용", "값"})
_TABLE_TARGET_CUES = (
    "비용",
    "가격",
    "표",
    "목록",
    "종류",
    "확률",
)
_TABLE_TARGET_NOISE = (
    "알려주세요",
    "알려줘",
    "보여주세요",
    "보여줘",
    "필요한",
    "필요",
    "비용",
    "가격",
    "목록",
    "종류",
    "확률",
    "얼마",
    "몇개",
    "몇",
    "하려면",
)


def _compact(value: Any) -> str:
    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(value or "").casefold(),
    )


def _tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN.findall(str(value or ""))
        if len(token) > 1
    }


def requested_equipment_operations(question: str) -> set[str]:
    return {
        operation
        for operation in _EQUIPMENT_OPERATIONS
        if operation in question
    }


def operation_identity_matches(
    question: str,
    *,
    title: str,
    heading_path: list[str] | tuple[str, ...],
    evidence_text: str = "",
) -> bool:
    return (
        operation_identity_state(
            question,
            title=title,
            heading_path=heading_path,
            evidence_text=evidence_text,
        )
        == "match"
    )


def operation_identity_state(
    question: str,
    *,
    title: str,
    heading_path: list[str] | tuple[str, ...],
    evidence_text: str = "",
) -> str:
    requested = requested_equipment_operations(question)
    if not requested:
        return "match"
    evidence_identity = " ".join(
        [title, *heading_path, evidence_text]
    )
    found = {
        operation
        for operation in _EQUIPMENT_OPERATIONS
        if operation in evidence_identity
    }
    if requested.issubset(found):
        return "match"
    if found:
        return "conflict"
    return "neutral"


def prefer_exact_title_parent_ids(
    question: str,
    *,
    parent_ids: tuple[str, ...],
    documents_by_id: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Prefer an exact document title when the query names one plainly."""

    subject_tokens = _tokens(question) - _GENERIC_QUERY_TOKENS
    if not subject_tokens:
        return parent_ids
    exact = tuple(
        parent_id
        for parent_id in parent_ids
        if _tokens(
            documents_by_id.get(parent_id, {}).get("title")
        )
        == subject_tokens
    )
    return exact or parent_ids


def _matching_attributes(
    question: str,
    attributes: list[str],
) -> list[str]:
    compact_question = _compact(question)
    question_tokens = _tokens(question)
    matches = []
    for attribute in attributes:
        compact_attribute = _compact(attribute)
        attribute_tokens = _tokens(attribute)
        if (
            compact_attribute in compact_question
            or any(
                keyword in compact_question
                and keyword in compact_attribute
                for keyword in _ATTRIBUTE_KEYWORDS
            )
            or any(
                len(token) >= 2
                and _compact(token) in compact_attribute
                for token in question_tokens
            )
            or (
                attribute_tokens
                and attribute_tokens.issubset(question_tokens)
            )
        ):
            matches.append(attribute)
    return matches


def _best_unique_row(
    question: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    question_tokens = _tokens(question) - _GENERIC_QUERY_TOKENS
    compact_question = _compact(question)
    scored = []
    for row in rows:
        row_tokens = _tokens(
            f"{row.get('label', '')} {row.get('subject', '')}"
        ) - _GENERIC_QUERY_TOKENS
        exact_hits = question_tokens & row_tokens
        compact_hits = {
            token
            for token in row_tokens
            if len(_compact(token)) >= 2
            and _compact(token) in compact_question
        }
        score = len(exact_hits | compact_hits)
        scored.append((score, str(row.get("row_id") or ""), row))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score = scored[0][0]
    if best_score < 2:
        return None
    if len(scored) > 1 and scored[1][0] == best_score:
        return None
    return scored[0][2]


def _view_matches_operation(
    question: str,
    view: dict[str, Any],
) -> bool:
    requested = requested_equipment_operations(question)
    if not requested:
        return True
    identity = " ".join(
        [
            str(view.get("title") or ""),
            *[
                str(value)
                for value in view.get("heading_path") or []
            ],
            str(view.get("caption") or ""),
            str(view.get("table_subject") or ""),
        ]
    )
    return requested.issubset(
        {
            operation
            for operation in _EQUIPMENT_OPERATIONS
            if operation in identity
        }
    )


def _requested_table_targets(question: str) -> list[dict[str, Any]]:
    normalized = " ".join(str(question or "").split())
    for cue in _TABLE_TARGET_CUES:
        normalized = re.sub(
            rf"({re.escape(cue)})(?:과|와)\s+"
            rf"(?=[^,;/]*(?:{'|'.join(_EQUIPMENT_OPERATIONS)}))",
            r"\1|",
            normalized,
        )
    normalized = re.sub(r"\s+(?:그리고|및)\s+", "|", normalized)
    parts = [
        part.strip()
        for part in re.split(r"\s*[,;/|]\s*", normalized)
        if part.strip()
    ]
    if len(parts) > 1 and not all(
        any(operation in part for operation in _EQUIPMENT_OPERATIONS)
        or any(cue in part for cue in _TABLE_TARGET_CUES)
        for part in parts
    ):
        parts = [str(question or "").strip()]

    targets = []
    for part in parts or [str(question or "").strip()]:
        operations = tuple(
            operation
            for operation in _EQUIPMENT_OPERATIONS
            if operation in part
        )
        anchor = _compact(part)
        for noise in _TABLE_TARGET_NOISE:
            anchor = anchor.replace(_compact(noise), "")
        for operation in operations:
            anchor = anchor.replace(_compact(operation), "")
        anchor = re.sub(r"(?:은|는|이|가|을|를|의)$", "", anchor)
        targets.append(
            {
                "surface": part,
                "operations": operations,
                "anchor": anchor,
            }
        )
    return targets


def _view_identity_text(view: dict[str, Any]) -> str:
    primary = " ".join(
        [
            str(view.get("table_subject") or ""),
            str(view.get("caption") or ""),
        ]
    ).strip()
    return primary or str(view.get("title") or "")


def _view_matches_target(
    target: dict[str, Any],
    view: dict[str, Any],
) -> bool:
    identity = _view_identity_text(view)
    compact_identity = _compact(identity)
    if target["operations"] and not all(
        operation in identity
        for operation in target["operations"]
    ):
        return False
    anchor = str(target.get("anchor") or "")
    if not anchor:
        return True
    if anchor in compact_identity:
        return True
    anchor_tokens = (
        _tokens(target["surface"])
        - set(target["operations"])
        - _GENERIC_QUERY_TOKENS
    )
    return bool(anchor_tokens) and all(
        _compact(token) in compact_identity
        for token in anchor_tokens
    )


def _view_supports_target_relation(
    target: dict[str, Any],
    view: dict[str, Any],
) -> bool:
    compact_surface = _compact(target["surface"])
    rows = list(view.get("rows") or [])
    if any(
        cue in compact_surface
        for cue in ("비용", "가격")
    ):
        return bool(rows) and all(
            any(
                re.search(r"\d", str(value or ""))
                for value in row.get("values", {}).values()
            )
            for row in rows
        )
    if "확률" in compact_surface:
        return bool(rows) and all(
            any(
                "%" in str(value or "")
                for value in row.get("values", {}).values()
            )
            for row in rows
        )
    return True


def _logical_table_signature(view: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _compact(view.get("table_subject")),
        tuple(
            sorted(
                _compact(attribute)
                for attribute in view.get("attributes") or []
            )
        ),
        tuple(
            sorted(
                " ".join(
                    str(row.get("exact_row_text") or "").split()
                )
                for row in view.get("rows") or []
            )
        ),
    )


def _choose_from_single_view(
    question: str,
    view: dict[str, Any],
) -> dict[str, Any] | None:
    compact_question = _compact(question)
    broad_cue = any(
        cue in compact_question
        for cue in _TABLE_TARGET_CUES
    )
    subject_overlap = (
        _tokens(question)
        & _tokens(
            f"{view['title']} {view['caption']} "
            f"{view['table_subject']}"
        )
    )
    matching_attributes = _matching_attributes(
        question,
        list(view["attributes"]),
    )
    row = _best_unique_row(question, list(view["rows"]))
    if matching_attributes:
        if row is not None:
            values = {
                attribute: row["values"].get(attribute)
                for attribute in matching_attributes
            }
            if any(value is None for value in values.values()):
                return None
            return {
                "kind": "table_cells",
                "view": view,
                "row": row,
                "values": values,
            }
    if (
        row is not None
        and len(view["attributes"]) == 1
        and _compact(view["attributes"][0])
        in {_compact(value) for value in _GENERIC_VALUE_ATTRIBUTES}
    ):
        attribute = view["attributes"][0]
        value = row["values"].get(attribute)
        if value is None:
            return None
        relation_label = str(row.get("label") or "").strip()
        if not relation_label:
            return None
        return {
            "kind": "table_cells",
            "view": view,
            "row": row,
            "values": {relation_label: value},
        }
    if (
        broad_cue
        and subject_overlap
        and view["all_rows_have_all_attributes"]
    ):
        display_attributes = list(matching_attributes)
        if display_attributes:
            row_key = next(
                (
                    attribute
                    for attribute in view["attributes"]
                    if any(
                        cue in _compact(attribute)
                        for cue in ("구간", "단계", "종류", "구분")
                    )
                ),
                None,
            )
            if row_key is not None:
                display_attributes = list(
                    dict.fromkeys([row_key, *display_attributes])
                )
        return {
            "kind": "complete_table",
            "view": view,
            "display_attributes": display_attributes,
        }
    return None


def choose_structured_table_answer(
    *,
    question: str,
    ranked_seed_facts: list[dict[str, Any]],
    all_facts: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return an exact table or row/column answer when identity is unambiguous."""

    targets = _requested_table_targets(question)
    if len(targets) == 1:
        views = assemble_table_group_answers(
            query=question,
            ranked_seed_facts=ranked_seed_facts,
            all_facts=all_facts,
            chunks_by_id=chunks_by_id,
        )
    else:
        views_by_id = {}
        parent_ids = tuple(
            dict.fromkeys(
                fact["parent_document_id"]
                for fact in ranked_seed_facts
            )
        )
        for target in targets:
            for parent_id in parent_ids:
                parent_seeds = [
                    fact
                    for fact in ranked_seed_facts
                    if fact["parent_document_id"] == parent_id
                ]
                for view in assemble_table_group_answers(
                    query=target["surface"],
                    ranked_seed_facts=parent_seeds,
                    all_facts=all_facts,
                    chunks_by_id=chunks_by_id,
                ):
                    views_by_id[view["table_id"]] = view
        views = list(views_by_id.values())
    views = [
        view
        for view in views
        if view["exact_offset_mismatch_count"] == 0
    ]
    if len(targets) == 1:
        views = [
            view
            for view in views
            if _view_matches_operation(question, view)
        ]
    if not views:
        return None
    if len(targets) == 1 and len(views) == 1:
        return _choose_from_single_view(question, views[0])

    matched_items = []
    unresolved_targets = []
    ambiguous_targets = []
    for target in targets:
        matches = [
            view
            for view in views
            if _view_matches_target(target, view)
            and _view_supports_target_relation(target, view)
        ]
        logical_matches = {}
        for view in matches:
            logical_matches.setdefault(
                _logical_table_signature(view),
                view,
            )
        matches = list(logical_matches.values())
        if not matches:
            unresolved_targets.append(target["surface"])
            continue
        if len(matches) > 1:
            ambiguous_targets.append(target["surface"])
            continue
        selected = _choose_from_single_view(
            target["surface"],
            matches[0],
        )
        if selected is None:
            unresolved_targets.append(target["surface"])
            continue
        matched_items.append(selected)

    if ambiguous_targets:
        return {
            "kind": "table_group_clarification",
            "ambiguous_targets": ambiguous_targets,
            "requested_targets": [
                target["surface"] for target in targets
            ],
            "views": [],
        }
    if unresolved_targets:
        if not matched_items:
            return None
        return {
            "kind": "partial_table_group",
            "items": matched_items,
            "unresolved_targets": unresolved_targets,
            "requested_targets": [
                target["surface"] for target in targets
            ],
            "views": [
                item["view"]
                for item in matched_items
            ],
        }
    if len(matched_items) == 1:
        return matched_items[0]
    if not all(
        item["kind"] == "complete_table"
        for item in matched_items
    ):
        return None
    return {
        "kind": "complete_table_group",
        "items": matched_items,
        "requested_targets": [
            target["surface"] for target in targets
        ],
        "views": [
            item["view"]
            for item in matched_items
        ],
    }
