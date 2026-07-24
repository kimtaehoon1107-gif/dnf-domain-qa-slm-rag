from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


ENTITY_ANCHOR_VERSION = "official-longest-exact-entity-anchor-v3.3.1"
_LEADING_STRUCTURE = re.compile(r"^[\s#■▒]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_entity_phrase(value: str) -> str:
    phrase = _LEADING_STRUCTURE.sub("", str(value or "")).strip()
    return _WHITESPACE.sub(" ", phrase)


def build_official_entity_index(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Index exact official titles/headings without domain keyword lists."""

    values: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"document_ids": set(), "source_ids": set(), "origins": set()}
    )
    documents_by_id = {row["document_id"]: row for row in documents}

    def add(phrase: str, document_id: str, source_id: str, origin: str) -> None:
        normalized = normalize_entity_phrase(phrase)
        if len(normalized) < 2 or len(normalized) > 80:
            return
        if not re.search(r"[0-9A-Za-z가-힣]", normalized):
            return
        values[normalized]["document_ids"].add(document_id)
        values[normalized]["source_ids"].add(source_id)
        values[normalized]["origins"].add(origin)

    for document in documents:
        add(
            document.get("title") or "",
            document["document_id"],
            document["source_id"],
            "document_title",
        )
    for chunk in chunks:
        document = documents_by_id.get(chunk["parent_document_id"])
        if document is None:
            continue
        for heading in chunk.get("heading_path") or []:
            add(
                heading,
                document["document_id"],
                document["source_id"],
                "heading_path",
            )

    return {
        phrase: {
            "phrase": phrase,
            "document_ids": sorted(metadata["document_ids"]),
            "source_ids": sorted(metadata["source_ids"]),
            "origins": sorted(metadata["origins"]),
        }
        for phrase, metadata in sorted(values.items())
    }


def anchor_requirement_subject(
    question: str,
    requirement: dict[str, Any],
    entity_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Expand a planner subject only to an exact official phrase in the question."""

    original = normalize_entity_phrase(requirement.get("subject") or "")
    if len(original) < 2:
        return dict(requirement)
    exact = entity_index.get(original)
    if exact is not None and original in question:
        return {
            **requirement,
            "subject": original,
            "planner_subject": requirement.get("subject"),
            "entity_anchor": {
                **exact,
                "match_type": "exact_official_phrase_in_question",
                "version": ENTITY_ANCHOR_VERSION,
            },
        }
    candidates = [
        metadata
        for phrase, metadata in entity_index.items()
        if phrase != original
        and len(phrase) > len(original)
        and phrase in question
        and original in phrase
    ]
    if not candidates:
        return dict(requirement)
    selected = sorted(candidates, key=lambda row: (-len(row["phrase"]), row["phrase"]))[0]
    return {
        **requirement,
        "subject": selected["phrase"],
        "planner_subject": requirement.get("subject"),
        "entity_anchor": {
            **selected,
            "match_type": "longest_exact_official_phrase_in_question",
            "version": ENTITY_ANCHOR_VERSION,
        },
    }


def anchor_requirements(
    question: str,
    requirements: list[dict[str, Any]],
    entity_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        anchor_requirement_subject(question, requirement, entity_index)
        for requirement in requirements
    ]
