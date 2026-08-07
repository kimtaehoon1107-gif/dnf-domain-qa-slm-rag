from __future__ import annotations

import re
from typing import Any


_ENTRY_FAME_QUESTION = re.compile(
    r"(?:"
    r"입장\s*명성"
    r"|명성\s*제한"
    r"|필요(?:한)?\s*명성"
    r"|입장\s*컷"
    r"|명성\s*컷"
    r")"
)
_ENTRY_FAME_VALUE = (
    re.compile(
        r"(?:모험가\s*)?명성\s*([0-9][0-9,]*)\s*부터\s*"
        r"입장이?\s*가능"
    ),
    re.compile(r"\|\s*입장\s*명성\s*\|\s*([0-9][0-9,]*)\s*\|"),
)


def _compact(value: Any) -> str:
    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(value or "").casefold(),
    )


def _entry_subject(question: str) -> str:
    match = _ENTRY_FAME_QUESTION.search(question)
    if match is None:
        return ""
    return _compact(question[: match.start()])


def choose_direct_entry_fame(
    question: str,
    *,
    selected_hits: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Select an exact entry-fame sentence when the owner is unambiguous."""

    subject = _entry_subject(question)
    if not subject:
        return None
    for hit in selected_hits:
        chunk = chunks_by_id[hit["chunk_id"]]
        document = documents_by_id[chunk["parent_document_id"]]
        parent_identity = _compact(
            f"{document.get('title', '')} "
            f"{' '.join(chunk.get('heading_path') or [])}"
        )
        if subject not in parent_identity:
            continue
        text = str(chunk.get("display_text") or "")
        value_match = next(
            (
                match
                for pattern in _ENTRY_FAME_VALUE
                if (match := pattern.search(text)) is not None
            ),
            None,
        )
        if value_match is None:
            continue
        line_start = text.rfind("\n", 0, value_match.start()) + 1
        line_end = text.find("\n", value_match.end())
        if line_end < 0:
            line_end = len(text)
        exact_text = text[line_start:line_end]
        return {
            "subject": str(document.get("title") or "").strip(),
            "value": value_match.group(1),
            "citation": {
                "chunk_id": chunk["chunk_id"],
                "parent_document_id": chunk["parent_document_id"],
                "source_id": document["source_id"],
                "revision_id": document.get("revision_id"),
                "start_char": line_start,
                "end_char": line_end,
                "text": exact_text,
                "evidence_ref": "DIRECT_ENTRY_FAME",
            },
        }
    return None
