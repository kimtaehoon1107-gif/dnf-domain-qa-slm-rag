from __future__ import annotations

import copy
from typing import Any

from src.v3.answer_target_router import _base_tag, _is_nominal_tag, _kiwi


SURFACE_QUERY_VERSION = "entity-preserving-surface-query-v3.3.3"
COORDINATING_JKB_FORMS = frozenset({"과", "와", "랑"})


def _is_coordinator(token: Any) -> bool:
    tag = _base_tag(token)
    return tag == "JC" or (
        tag == "JKB" and str(token.form) in COORDINATING_JKB_FORMS
    )


def _trim_right_question_tail(text: str) -> str:
    tokens = list(_kiwi().tokenize(text))
    nominal_seen = False
    for token in tokens:
        tag = _base_tag(token)
        nominal_seen = nominal_seen or _is_nominal_tag(tag)
        if nominal_seen and tag in {"JX", "JKS"}:
            return text[: int(token.start)].strip()
    return text.strip().rstrip("?？. ")


def _planner_subject_surface(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


def _shared_entity_phrase(
    question: str,
    requirements: list[dict[str, Any]],
) -> tuple[str, str] | None:
    anchor_phrases = [
        str(row.get("entity_anchor", {}).get("phrase") or "").strip()
        for row in requirements
    ]
    if any(anchor_phrases):
        if not all(anchor_phrases) or len(set(anchor_phrases)) != 1:
            return None
        phrase = anchor_phrases[0]
        return (
            (phrase, "verified_entity_anchor")
            if phrase in question
            else None
        )

    subjects = [_planner_subject_surface(row.get("subject")) for row in requirements]
    if not all(subjects) or len(set(subjects)) != 1:
        return None
    phrase = subjects[0]
    if phrase not in question:
        return None
    return phrase, "shared_planner_subject_exact_question_match"


def extract_entity_coordinated_surfaces(
    question: str,
    requirements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return two exact question spans only for a high-confidence grammar shape.

    The function deliberately requires one shared, previously verified official entity
    anchor and exactly two planner requirements. It does not translate normalized
    relation labels and does not contain domain field keywords.
    """

    normalized = " ".join(question.strip().split())
    if not normalized or len(requirements) != 2:
        return None
    resolved_entity = _shared_entity_phrase(normalized, requirements)
    if resolved_entity is None:
        return None
    entity_phrase, entity_resolution = resolved_entity
    entity_start = normalized.find(entity_phrase)
    if entity_start < 0:
        return None
    entity_end = entity_start + len(entity_phrase)

    tokens = list(_kiwi().tokenize(normalized))
    coordinators = [token for token in tokens if _is_coordinator(token)]
    if len(coordinators) != 1:
        return None
    coordinator = coordinators[0]
    coordinator_start = int(coordinator.start)
    coordinator_end = coordinator_start + int(coordinator.len)
    if not (entity_end <= coordinator_start < coordinator_end):
        return None

    left_start = entity_end
    first_left_token = next(
        (
            token
            for token in tokens
            if int(token.start) >= entity_end
            and int(token.start) < coordinator_start
        ),
        None,
    )
    if (
        first_left_token is not None
        and int(first_left_token.start) == entity_end
        and str(first_left_token.form) == "의"
        and _base_tag(first_left_token) == "JKG"
    ):
        left_start = entity_end + int(first_left_token.len)

    left = normalized[left_start:coordinator_start].strip(" ,")
    right = _trim_right_question_tail(normalized[coordinator_end:])
    if not left or not right:
        return None
    if not any(
        _is_nominal_tag(_base_tag(token)) for token in _kiwi().tokenize(left)
    ):
        return None
    if not any(
        _is_nominal_tag(_base_tag(token)) for token in _kiwi().tokenize(right)
    ):
        return None

    surfaces = [left, right]
    return {
        "version": SURFACE_QUERY_VERSION,
        "entity_phrase": entity_phrase,
        "entity_resolution": entity_resolution,
        "coordinator": str(coordinator.form),
        "coordinator_tag": _base_tag(coordinator),
        "requirement_surfaces": [
            {
                "requirement_id": requirement["requirement_id"],
                "surface": surface,
                "exact_question_substring": surface in normalized,
            }
            for requirement, surface in zip(requirements, surfaces, strict=True)
        ],
        "mapping": "planner_question_order_to_surface_order",
        "domain_keyword_rule_count": 0,
    }


def build_surface_scoring_requirements(
    requirements: list[dict[str, Any]],
    extraction: dict[str, Any],
) -> list[dict[str, Any]]:
    surfaces = extraction["requirement_surfaces"]
    if len(requirements) != len(surfaces):
        raise RuntimeError("surface count must match requirement count")
    entity_phrase = str(extraction.get("entity_phrase") or "").strip()
    if not entity_phrase:
        raise RuntimeError("surface scoring requires one preserved entity phrase")
    output = []
    for requirement, surface in zip(requirements, surfaces, strict=True):
        if requirement["requirement_id"] != surface["requirement_id"]:
            raise RuntimeError("surface order must preserve requirement ids")
        row = copy.deepcopy(requirement)
        attribute_surface = str(surface["surface"]).strip()
        if not attribute_surface:
            raise RuntimeError("surface scoring requires a non-empty attribute surface")
        row["surface_query"] = f"{entity_phrase} {attribute_surface}"
        row["surface_query_version"] = SURFACE_QUERY_VERSION
        row["surface_query_entity"] = entity_phrase
        row["surface_query_attribute"] = attribute_surface
        row["planner_subject"] = requirement.get("subject")
        row["planner_relation"] = requirement.get("relation")
        row["subject"] = entity_phrase
        row["relation"] = attribute_surface
        output.append(row)
    return output
