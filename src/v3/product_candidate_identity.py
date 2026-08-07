from __future__ import annotations

import re
from calendar import monthrange
from collections import defaultdict
from datetime import date
from typing import Any

from src.v3.build_bm25 import tokenize_lexical
from src.v3.simple_evidence_refs import _compact_char_ngrams


_FULL_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)
_YEAR_MONTH = re.compile(
    r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월"
)
_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*년?")
DEFAULT_IDENTITY_DEPTH = 8
DEFAULT_IDENTITY_PARENT_LIMIT = 2


def explicit_temporal_interval(question: str) -> tuple[str, str] | None:
    full_date = _FULL_DATE.search(question)
    if full_date is not None:
        value = date(*(int(part) for part in full_date.groups())).isoformat()
        return value, value
    year_month = _YEAR_MONTH.search(question)
    if year_month is not None:
        year, month = (int(part) for part in year_month.groups())
        return (
            date(year, month, 1).isoformat(),
            date(year, month, monthrange(year, month)[1]).isoformat(),
        )
    year = _YEAR.search(question)
    if year is None:
        return None
    year_value = int(year.group(1))
    return date(year_value, 1, 1).isoformat(), date(year_value, 12, 31).isoformat()


def intervals_overlap(
    left: tuple[str, str],
    *,
    valid_from: str | None,
    valid_to: str | None,
) -> bool:
    start, end = left
    candidate_start = str(valid_from or "0001-01-01")[:10]
    candidate_end = str(valid_to or "9999-12-31")[:10]
    return candidate_start <= end and candidate_end >= start


def _token_overlap_score(question: str, text: str) -> int:
    question_tokens = {
        token for token in tokenize_lexical(question) if len(token) >= 2
    }
    text_tokens = set(tokenize_lexical(text))
    return sum(len(token) ** 2 for token in question_tokens & text_tokens)


def shortlist_identity_documents(
    question: str,
    *,
    documents_by_id: dict[str, dict[str, Any]],
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Rank document identities using only question and corpus metadata."""

    interval = explicit_temporal_interval(question)
    question_ngrams = _compact_char_ngrams(question)
    ranked = []
    for document_id, document in documents_by_id.items():
        chunks = [
            chunk
            for chunk in chunks_by_parent.get(document_id, [])
            if not chunk.get("review_required")
        ]
        if not chunks:
            continue
        title = str(document.get("title") or "")
        heading_text = " ".join(
            str(value)
            for chunk in chunks
            for value in (chunk.get("heading_path") or [])
        )
        identity_text = " ".join((title, heading_text))
        overlap = _token_overlap_score(question, identity_text)
        ngram_overlap = len(
            question_ngrams & _compact_char_ngrams(identity_text)
        )
        temporal_match = False
        if interval is not None:
            temporal_match = any(
                intervals_overlap(
                    interval,
                    valid_from=chunk.get("valid_from")
                    or document.get("valid_from")
                    or document.get("published_at"),
                    valid_to=chunk.get("valid_to")
                    or document.get("valid_to"),
                )
                for chunk in chunks
            )
            metadata_text = " ".join(
                str(value or "")
                for value in (
                    title,
                    document.get("published_at"),
                    document.get("valid_from"),
                    document.get("valid_to"),
                    document.get("revision_id"),
                )
            )
            exact_date_match = bool(
                _FULL_DATE.search(question)
                and interval[0] in metadata_text
            )
            year_month = _YEAR_MONTH.search(question)
            period_label_match = bool(
                year_month
                and re.search(
                    rf"(?<!\d){int(year_month.group(2))}\s*월",
                    title,
                )
                and year_month.group(1) in metadata_text
            )
        else:
            exact_date_match = False
            period_label_match = False
        if interval is not None and not temporal_match and not exact_date_match:
            continue
        if overlap == 0 and ngram_overlap < 4:
            continue
        ranked.append(
            {
                "document_id": document_id,
                "title": title,
                "temporal_match": temporal_match,
                "exact_date_match": exact_date_match,
                "period_label_match": period_label_match,
                "identity_token_score": overlap,
                "identity_ngram_score": ngram_overlap,
            }
        )
    ranked.sort(
        key=lambda row: (
            -int(row["exact_date_match"]),
            -int(row["period_label_match"]),
            -int(row["temporal_match"]),
            -int(row["identity_token_score"]),
            -int(row["identity_ngram_score"]),
            str(row["document_id"]),
        )
    )
    return ranked[:limit]


def shortlist_document_chunks(
    question: str,
    documents: list[dict[str, Any]],
    *,
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    per_document: int = 4,
) -> list[dict[str, Any]]:
    question_ngrams = _compact_char_ngrams(question)
    selected = []
    for document in documents:
        chunks = [
            chunk
            for chunk in chunks_by_parent.get(document["document_id"], [])
            if not chunk.get("review_required")
        ]
        chunks.sort(
            key=lambda chunk: (
                -_token_overlap_score(
                    question,
                    str(chunk.get("retrieval_text") or ""),
                ),
                -len(
                    question_ngrams
                    & _compact_char_ngrams(
                        str(chunk.get("retrieval_text") or "")
                    )
                ),
                str(chunk["chunk_id"]),
            )
        )
        selected.extend(chunks[:per_document])
    return selected


def candidate_row_from_chunk(
    chunk: dict[str, Any],
    document: dict[str, Any],
    *,
    fallback_rank: int,
) -> dict[str, Any]:
    return {
        "rank": fallback_rank,
        "chunk_id": chunk["chunk_id"],
        "parent_document_id": chunk["parent_document_id"],
        "title": document.get("title") or "",
        "canonical_url": document.get("canonical_url") or "",
        "source_id": chunk["source_id"],
        "source_kind": chunk["source_kind"],
        "status": chunk["status"],
        "default_exposure": chunk["default_exposure"],
        "review_required": chunk["review_required"],
        "valid_from": chunk.get("valid_from"),
        "valid_to": chunk.get("valid_to"),
        "chunk_type": chunk["chunk_type"],
        "heading_path": chunk.get("heading_path") or [],
        "display_text": chunk.get("display_text") or "",
        "retrieval_text": chunk.get("retrieval_text") or "",
        "identity_shortlist_injected": True,
    }


def reserve_then_fill(
    reserved_groups: list[list[dict[str, Any]]],
    global_ranked: list[dict[str, Any]],
    *,
    depth: int = DEFAULT_IDENTITY_DEPTH,
    max_per_parent: int = DEFAULT_IDENTITY_PARENT_LIMIT,
) -> list[dict[str, Any]]:
    selected = []
    seen = set()
    parent_counts: dict[str, int] = defaultdict(int)

    def append(row: dict[str, Any]) -> None:
        chunk_id = str(row["chunk_id"])
        parent_id = str(row["parent_document_id"])
        if chunk_id in seen or parent_counts[parent_id] >= max_per_parent:
            return
        selected.append(row)
        seen.add(chunk_id)
        parent_counts[parent_id] += 1

    for group in reserved_groups:
        for row in group:
            append(row)
            if len(selected) >= depth:
                return selected
            break
    for row in global_ranked:
        append(row)
        if len(selected) >= depth:
            break
    return selected
