from __future__ import annotations

import re
from typing import Any, Callable

from src.v3.minimal_evidence_contract import (
    NARRATIVE,
    evidence_contract_for_unit,
)


_SUBJECT_DISCRIMINATOR_FAMILIES = (
    (
        ("흑색", "검은색", "검정"),
        ("흰색", "백색", "하얀색"),
        ("적색", "빨간색"),
        ("청색", "파란색"),
        ("녹색", "초록색"),
        ("무색",),
    ),
    (
        ("안드로이드", "android"),
        ("ios", "아이폰"),
    ),
    (
        ("남성", "(남)"),
        ("여성", "(여)"),
    ),
)


def _compact(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value).casefold())


def _requested_discriminators(
    requirement: dict[str, Any],
) -> list[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]]:
    subject = _compact(requirement.get("subject", ""))
    requested = []
    for family in _SUBJECT_DISCRIMINATOR_FAMILIES:
        for group in family:
            if any(_compact(alias) in subject for alias in group):
                requested.append((group, family))
                break
    return requested


def _group_is_present(group: tuple[str, ...], text: str) -> bool:
    return any(_compact(alias) in text for alias in group)


def _subject_discriminator_state(
    requested: list[
        tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]
    ],
    semantic_text: str,
    title: str,
) -> str:
    evidence = _compact(f"{semantic_text} {title}")
    states = []
    for requested_group, family in requested:
        if _group_is_present(requested_group, evidence):
            states.append("matched")
        elif any(
            _group_is_present(group, evidence)
            for group in family
            if group != requested_group
        ):
            states.append("conflict")
        else:
            states.append("unobserved")
    if "conflict" in states:
        return "conflict"
    if states and all(state == "matched" for state in states):
        return "matched"
    return "unobserved"


def verify_atomic_claim_proof(
    requirement: dict[str, Any],
    value: Any,
    evidence_units: list[dict[str, Any]],
    *,
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ],
    subject_matches: Callable[
        [dict[str, Any], str, str], bool
    ],
    relation_matches: Callable[
        [dict[str, Any], str, str], bool
    ],
    value_matches: Callable[[Any, str], bool],
) -> dict[str, Any]:
    """Require one linked narrative unit to prove subject, relation, and value."""

    if not evidence_units:
        return {
            "state": "not_applicable",
            "failures": [],
            "facts": [],
        }
    if any(
        evidence_contract_for_unit(
            unit,
            structured_rows_by_coordinate=structured_rows_by_coordinate,
        )
        != NARRATIVE
        for unit in evidence_units
    ):
        return {
            "state": "not_applicable",
            "failures": [],
            "facts": [],
        }

    requested_discriminators = _requested_discriminators(requirement)
    if not requested_discriminators:
        return {
            "state": "not_applicable",
            "failures": [],
            "facts": [],
        }
    combined_evidence = "\n".join(
        str(unit.get("context_text") or "")
        + "\n"
        + str(unit.get("text") or "")
        + "\n"
        + str(unit.get("title") or "")
        for unit in evidence_units
    )
    if all(
        _subject_discriminator_state(
            [requested],
            combined_evidence,
            "",
        )
        == "unobserved"
        for requested in requested_discriminators
    ):
        return {
            "state": "not_applicable",
            "failures": [],
            "facts": [],
        }

    facts = []
    for unit in evidence_units:
        semantic_text = "\n".join(
            text
            for text in (
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
            if text
        )
        title = str(unit.get("title") or "")
        subject_matched = subject_matches(
            requirement,
            semantic_text,
            title,
        )
        discriminator_state = _subject_discriminator_state(
            requested_discriminators,
            semantic_text,
            title,
        )
        fact = {
            "evidence_ref": unit.get("evidence_ref"),
            "subject_matched": subject_matched,
            "subject_discriminator_state": discriminator_state,
            "subject_discriminator_matched": (
                discriminator_state == "matched"
            ),
            "relation_matched": relation_matches(
                requirement,
                semantic_text,
                title,
            ),
            "value_matched": value_matches(
                value,
                str(unit.get("text") or ""),
            ),
        }
        fact["matched"] = all(
            fact[key]
            for key in (
                "subject_matched",
                "subject_discriminator_matched",
                "relation_matched",
                "value_matched",
            )
        )
        facts.append(fact)

    if any(fact["matched"] for fact in facts):
        return {
            "state": "matched",
            "failures": [],
            "facts": facts,
        }
    return {
        "state": "mismatch",
        "failures": ["atomic_subject_relation_value_not_colocated"],
        "facts": facts,
    }
