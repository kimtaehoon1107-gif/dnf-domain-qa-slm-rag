from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


def title_tokens(value: Any) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in _TOKEN.findall(str(value or ""))
        if len(token) >= 2 and not token.isdigit()
    )


def build_title_token_idf(
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    document_count = len(documents_by_id)
    frequencies: Counter[str] = Counter()
    for document in documents_by_id.values():
        frequencies.update(title_tokens(document.get("title")))
    return {
        token: math.log((document_count + 1) / (count + 1)) + 1.0
        for token, count in frequencies.items()
    }


def _question_mentions_title_token(
    title_token: str,
    question_tokens: frozenset[str],
) -> bool:
    return any(
        title_token == question_token
        or title_token in question_token
        or question_token in title_token
        for question_token in question_tokens
    )


def bind_parent_ids_by_title_mention(
    question: str,
    *,
    parent_ids: tuple[str, ...],
    documents_by_id: dict[str, dict[str, Any]],
    title_token_idf: dict[str, float] | None = None,
    minimum_idf: float = 3.0,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Prefer parents whose rare title terms are explicitly named.

    If no candidate title has a sufficiently distinctive term in the question,
    the original parent order is returned unchanged.
    """

    if not parent_ids:
        return parent_ids, {
            "applied": False,
            "reason": "no_parent_candidates",
        }
    idf = title_token_idf or build_title_token_idf(documents_by_id)
    question_tokens = title_tokens(question)
    scored = []
    for parent_id in parent_ids:
        document = documents_by_id.get(parent_id, {})
        matched = sorted(
            token
            for token in title_tokens(document.get("title"))
            if idf.get(token, 0.0) >= minimum_idf
            and _question_mentions_title_token(token, question_tokens)
        )
        score = sum(idf[token] for token in matched)
        scored.append(
            {
                "parent_document_id": parent_id,
                "title": str(document.get("title") or ""),
                "matched_tokens": matched,
                "score": score,
            }
        )
    best_score = max(row["score"] for row in scored)
    if best_score <= 0:
        return parent_ids, {
            "applied": False,
            "reason": "no_distinctive_title_mention",
            "minimum_idf": minimum_idf,
        }
    selected = tuple(
        row["parent_document_id"]
        for row in scored
        if math.isclose(row["score"], best_score)
    )
    return selected, {
        "applied": True,
        "reason": "distinctive_title_mention",
        "minimum_idf": minimum_idf,
        "best_score": round(best_score, 8),
        "selected": [
            {
                **row,
                "score": round(row["score"], 8),
                "matched_token_idf": {
                    token: round(idf[token], 8)
                    for token in row["matched_tokens"]
                },
            }
            for row in scored
            if row["parent_document_id"] in selected
        ],
    }
