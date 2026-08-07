from __future__ import annotations

import re
from typing import Any


_NUMBERED_FIELD = re.compile(
    r"(?m)^\s*\d+[.)]\s*(?P<label>[^:\n：]+)\s*[:：]"
)


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _listed_fields(evidence_text: str) -> list[str]:
    fields = []
    for match in _NUMBERED_FIELD.finditer(evidence_text):
        for label in re.split(r"[/·]", match.group("label")):
            normalized = label.strip()
            if normalized:
                fields.append(normalized)
    return list(dict.fromkeys(fields))


def verify_entity_list_contract(
    requirement: dict[str, Any],
    value: Any,
    evidence_text: str,
) -> dict[str, Any]:
    if requirement.get("value_type") != "entity_list":
        return {
            "state": "not_applicable",
            "failures": [],
            "required_items": [],
        }
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        return {
            "state": "mismatch",
            "failures": ["entity_list_value_shape_mismatch"],
            "required_items": [],
        }
    compact_values = [_compact(item) for item in value]
    if len(compact_values) != len(set(compact_values)):
        return {
            "state": "mismatch",
            "failures": ["entity_list_duplicate_values"],
            "required_items": [],
        }

    expected_count = requirement.get("expected_count")
    if expected_count is not None and len(value) != int(expected_count):
        return {
            "state": "mismatch",
            "failures": ["entity_list_expected_count_mismatch"],
            "required_items": [],
        }

    relation = _compact(requirement.get("relation"))
    required_items = (
        _listed_fields(evidence_text)
        if "required" in relation and "field" in relation
        else []
    )
    missing = [
        item
        for item in required_items
        if not any(
            _compact(item) in candidate or candidate in _compact(item)
            for candidate in compact_values
        )
    ]
    if missing:
        return {
            "state": "mismatch",
            "failures": ["entity_list_required_items_missing"],
            "required_items": required_items,
            "missing_items": missing,
        }
    return {
        "state": "matched",
        "failures": [],
        "required_items": required_items,
    }


def entity_list_prompt_guidance(
    requirements: list[dict[str, Any]],
) -> str:
    if not any(
        requirement.get("value_type") == "entity_list"
        for requirement in requirements
    ):
        return ""
    return (
        "\n목록 해석 규칙:\n"
        "- entity_list는 근거에 열거된 항목을 JSON 배열의 개별 원소로 "
        "반환하세요.\n"
        "- 번호 목록의 `서버/캐릭터명`처럼 `/`로 나뉜 필드는 각각 "
        "별도 항목입니다.\n"
        "- required fields 또는 cardinality=all이면 누락 없이 모두 "
        "선택하세요.\n"
    )
