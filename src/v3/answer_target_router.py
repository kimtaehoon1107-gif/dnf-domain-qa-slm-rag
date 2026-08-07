from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

from kiwipiepy import Kiwi


ANSWER_TARGET_SCHEMA_VERSION = "dnf-answer-target-analysis-v3.2"
ANSWER_TARGET_ANALYZER_VERSION = "kiwi-grammar-answer-target-v3.2.0"

NOMINAL_TAG_PREFIXES = ("N",)
NOMINAL_TAGS = frozenset({"SL", "SN", "XR"})
NOMINAL_MODIFIER_TAGS = frozenset({"MM", "XPN", "XSN"})
PREDICATE_TAGS = frozenset({"VV", "VA", "VCP", "VCN", "XSV", "XSA"})
FOCUS_TAGS = frozenset({"MAG"})
ARGUMENT_PARTICLE_TAGS = frozenset({"JKS", "JKO", "JKB", "JKC", "JX"})


def _base_tag(token: Any) -> str:
    return str(token.tag).split("-", 1)[0]


def _is_nominal_tag(tag: str) -> bool:
    return tag.startswith(NOMINAL_TAG_PREFIXES) or tag in NOMINAL_TAGS


def _is_content_tag(tag: str) -> bool:
    return (
        _is_nominal_tag(tag)
        or tag in NOMINAL_MODIFIER_TAGS
        or tag in PREDICATE_TAGS
        or tag in FOCUS_TAGS
    )


@lru_cache(maxsize=1)
def _kiwi() -> Kiwi:
    return Kiwi()


def _signature(tokens: list[Any]) -> str | None:
    values = [
        f"{token.form}/{_base_tag(token)}"
        for token in tokens
        if _is_content_tag(_base_tag(token))
    ]
    if not values:
        return None
    return hashlib.sha256("\u241f".join(values).encode("utf-8")).hexdigest()


def _content_key(tokens: list[Any]) -> frozenset[str]:
    return frozenset(
        f"{token.form}/{_base_tag(token)}"
        for token in tokens
        if _is_content_tag(_base_tag(token))
    )


def _segment_is_independent(tokens: list[Any]) -> bool:
    tags = [_base_tag(token) for token in tokens]
    if not any(tag in PREDICATE_TAGS for tag in tags):
        return False
    content_count = sum(_is_content_tag(tag) for tag in tags)
    has_argument = any(tag in ARGUMENT_PARTICLE_TAGS for tag in tags)
    return has_argument or content_count >= 2


def _segment_can_answer(tokens: list[Any]) -> bool:
    tags = [_base_tag(token) for token in tokens]
    if any(tag in PREDICATE_TAGS for tag in tags):
        return True
    return any(_is_nominal_tag(tag) for tag in tags) and any(
        tag in ARGUMENT_PARTICLE_TAGS for tag in tags
    )


def _clause_boundaries(tokens: list[Any]) -> list[int]:
    boundaries = []
    segment_start = 0
    for index, token in enumerate(tokens):
        if _base_tag(token) != "EC":
            continue
        left = tokens[segment_start:index]
        right = tokens[index + 1 :]
        if _segment_is_independent(left) and _segment_can_answer(right):
            boundaries.append(index)
            segment_start = index + 1
    return boundaries


def _nominal_phrase_left(tokens: list[Any], conjunction_index: int) -> list[Any]:
    phrase = []
    for index in range(conjunction_index - 1, -1, -1):
        token = tokens[index]
        tag = _base_tag(token)
        if _is_nominal_tag(tag) or tag in NOMINAL_MODIFIER_TAGS:
            phrase.append(token)
            continue
        break
    return list(reversed(phrase))


def _nominal_phrase_right(tokens: list[Any], conjunction_index: int) -> list[Any]:
    phrase = []
    for token in tokens[conjunction_index + 1 :]:
        tag = _base_tag(token)
        if _is_nominal_tag(tag) or tag in NOMINAL_MODIFIER_TAGS:
            phrase.append(token)
            continue
        break
    return phrase


def _coordinated_nominal_signatures(tokens: list[Any]) -> set[str]:
    signatures: set[str] = set()
    for index, token in enumerate(tokens):
        if _base_tag(token) != "JC":
            continue
        left = _signature(_nominal_phrase_left(tokens, index))
        right = _signature(_nominal_phrase_right(tokens, index))
        left_key = _content_key(_nominal_phrase_left(tokens, index))
        right_key = _content_key(_nominal_phrase_right(tokens, index))
        repeated_focus = bool(
            left_key
            and right_key
            and (left_key.issubset(right_key) or right_key.issubset(left_key))
        )
        if left and right and left != right and not repeated_focus:
            signatures.update((left, right))
    return signatures


def analyze_answer_targets(question: str) -> dict[str, Any]:
    normalized = " ".join(question.strip().split())
    if not normalized:
        raise RuntimeError("question must not be empty")
    tokens = list(_kiwi().tokenize(normalized))
    boundaries = _clause_boundaries(tokens)
    clause_segments = []
    start = 0
    for boundary in boundaries:
        clause_segments.append(tokens[start:boundary])
        start = boundary + 1
    clause_segments.append(tokens[start:])
    clause_signatures = {
        signature
        for signature in (_signature(segment) for segment in clause_segments)
        if signature is not None
    }
    clause_target_count = len(clause_signatures) if boundaries else 1
    coordinated_signatures = _coordinated_nominal_signatures(tokens)
    coordinated_target_count = len(coordinated_signatures)
    answer_target_count = max(
        1,
        clause_target_count,
        coordinated_target_count,
    )
    return {
        "answer_target_schema_version": ANSWER_TARGET_SCHEMA_VERSION,
        "answer_target_analyzer_version": ANSWER_TARGET_ANALYZER_VERSION,
        "answer_target_count": answer_target_count,
        "needs_decomposition": answer_target_count >= 2,
        "independent_clause_target_count": clause_target_count,
        "coordinated_nominal_target_count": coordinated_target_count,
        "distinct_focus_count": max(
            clause_target_count, coordinated_target_count
        ),
        "clause_boundary_count": len(boundaries),
        "domain_keyword_rule_count": 0,
        "surface_marker_rule_count": 0,
        "signal_b_applied": False,
    }
