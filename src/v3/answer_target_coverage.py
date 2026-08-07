from __future__ import annotations

import hashlib
from typing import Any

from src.v3.answer_target_router import (
    _base_tag,
    _clause_boundaries,
    _content_key,
    _is_nominal_tag,
    _kiwi,
    _nominal_phrase_left,
    _nominal_phrase_right,
)


COVERAGE_SCHEMA_VERSION = "dnf-answer-target-top-chunk-coverage-v3.2"
COVERAGE_VERSION = "kiwi-structural-top-chunk-coverage-v3.2.0"


def _nominal_key(tokens: list[Any]) -> frozenset[str]:
    values = []
    for index, token in enumerate(tokens):
        tag = _base_tag(token)
        if not _is_nominal_tag(tag):
            continue
        next_tag = _base_tag(tokens[index + 1]) if index + 1 < len(tokens) else None
        if next_tag in {"XSV", "XSA"}:
            continue
        values.append(f"{token.form}/{tag}")
    return frozenset(values)


def _coordination_targets(tokens: list[Any]) -> list[frozenset[str]]:
    targets = []
    for index, token in enumerate(tokens):
        if _base_tag(token) != "JC":
            continue
        left_tokens = _nominal_phrase_left(tokens, index)
        right_tokens = _nominal_phrase_right(tokens, index)
        left_content = _content_key(left_tokens)
        right_content = _content_key(right_tokens)
        if not left_content or not right_content:
            continue
        if left_content.issubset(right_content) or right_content.issubset(left_content):
            continue
        left = _nominal_key(left_tokens)
        right = _nominal_key(right_tokens)
        if left and right and left != right:
            targets.extend((left, right))
    return targets


def _clause_targets(tokens: list[Any]) -> list[frozenset[str]]:
    boundaries = _clause_boundaries(tokens)
    if not boundaries:
        return []
    segments = []
    start = 0
    for boundary in boundaries:
        segments.append(tokens[start:boundary])
        start = boundary + 1
    segments.append(tokens[start:])
    return [target for target in (_nominal_key(row) for row in segments) if target]


def extract_target_token_sets(question: str) -> list[frozenset[str]]:
    normalized = " ".join(question.strip().split())
    if not normalized:
        raise RuntimeError("question must not be empty")
    tokens = list(_kiwi().tokenize(normalized))
    coordination = _coordination_targets(tokens)
    clauses = _clause_targets(tokens)
    selected = coordination if len(coordination) >= len(clauses) else clauses
    unique = sorted(set(selected), key=lambda row: tuple(sorted(row)))
    return unique if len(unique) >= 2 else []


def _group_hash(group: frozenset[str]) -> str:
    payload = "\u241f".join(sorted(group)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluate_top_chunk_coverage(question: str, chunk_text: str) -> dict[str, Any]:
    targets = extract_target_token_sets(question)
    chunk_tokens = list(_kiwi().tokenize(chunk_text))
    chunk_key = frozenset(
        f"{token.form}/{_base_tag(token)}"
        for token in chunk_tokens
        if _is_nominal_tag(_base_tag(token))
    )
    covered = [target for target in targets if target.issubset(chunk_key)]
    return {
        "coverage_schema_version": COVERAGE_SCHEMA_VERSION,
        "coverage_version": COVERAGE_VERSION,
        "target_group_count": len(targets),
        "covered_target_group_count": len(covered),
        "all_targets_in_top_chunk": bool(targets) and len(covered) == len(targets),
        "target_group_hashes": [_group_hash(group) for group in targets],
        "domain_keyword_rule_count": 0,
        "store_expansion_applied": False,
    }
