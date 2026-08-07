from __future__ import annotations

import math
import re
from typing import Any, Callable

from src.v3.product_evidence_pack import (
    _atomic_reranker_text,
    explicit_question_clauses,
    surface_requirement_queries,
)
from src.v3.simple_evidence_refs import (
    _compact_char_ngrams,
    _compact_tokens,
)


RELATION_SEMANTIC_SHADOW_VERSION = (
    "product-relation-semantic-shadow-v1"
)

_REQUEST_TAIL = re.compile(
    r"\s*(?:을|를)?\s*(?:"
    r"알려\s*줘|설명해\s*줘|말해\s*줘|정리해\s*줘|보여\s*줘|"
    r"답해\s*줘|뭐(?:였)?어|뭐야|무엇이야|"
    r"언제(?:였)?어|언제야|얼마(?:였)?어|얼마야|어디(?:였)?어|"
    r"왜\s*이럴까|어떻게\s*(?:돼|됐어|해야\s*해)"
    r")[?？.\s]*$"
)
_LEADING_TOPIC = re.compile(
    r"^.{1,48}?(?:은|는|이|가)\s+(?=.{2,}$)"
)
_TRAILING_PARTICLE = re.compile(r"(?<=[가-힣])(?:은|는|이|가|을|를)$")
_GENERIC_RELATION_SUFFIX = re.compile(
    r"\s*(?:각각|모두)(?:\s+몇\s+[A-Za-z가-힣%]+(?:이야|야|였어)?)?$"
)
_KOREAN_PARTICLE = re.compile(r"(?:에서|으로|은|는|이|가|을|를|의|로|와|과)$")


def _normalize(value: str) -> str:
    return " ".join(str(value or "").strip(" ?？.").split())


def _relation_phrase(clause: str) -> str:
    normalized = _normalize(clause)
    without_request = _REQUEST_TAIL.sub("", normalized).strip()
    without_request = _GENERIC_RELATION_SUFFIX.sub(
        "",
        without_request,
    ).strip()
    if "의 " in without_request:
        prefix, relation = without_request.rsplit("의 ", 1)
        relation = relation.strip()
        if len(relation.split()) == 1:
            prefix_tail = prefix.split()[-1:]
            relation = " ".join((*prefix_tail, relation)).strip()
    else:
        relation = without_request
    relation = _LEADING_TOPIC.sub("", relation).strip()
    relation = _TRAILING_PARTICLE.sub("", relation).strip()
    if relation == normalized and len(relation.split()) > 7:
        relation = " ".join(relation.split()[-7:])
    if len(relation) >= 2:
        return relation
    return without_request or normalized


def _surface_focus_phrase(query: str) -> str:
    normalized = _normalize(query)
    relation = _REQUEST_TAIL.sub("", normalized).strip()
    relation = _GENERIC_RELATION_SUFFIX.sub("", relation).strip()
    return _TRAILING_PARTICLE.sub("", relation).strip() or normalized


def relation_focused_question_clauses(question: str) -> list[str]:
    """Extract surface relation clauses without a domain relation registry."""

    normalized = _normalize(question)
    if not normalized:
        raise RuntimeError("question must not be empty")
    explicit_clauses = explicit_question_clauses(question)
    focused_queries = surface_requirement_queries(question)[1:]
    relations = [
        relation
        for clause in (explicit_clauses or [normalized])
        if (relation := _relation_phrase(clause))
    ]
    relations.extend(
        relation
        for query in focused_queries
        if (relation := _surface_focus_phrase(query))
    )
    return list(dict.fromkeys(relations))


def _claim_clause_score(
    relation_clause: str,
    claim_text: str,
) -> tuple[int, int, int, int]:
    def semantic_tokens(value: str) -> set[str]:
        tokens = set()
        for token in _compact_tokens(value):
            stripped = _KOREAN_PARTICLE.sub("", token)
            tokens.add(stripped if len(stripped) >= 2 else token)
        return tokens

    clause_tokens = semantic_tokens(relation_clause)
    claim_tokens = semantic_tokens(claim_text)
    clause_ngrams = _compact_char_ngrams(relation_clause)
    claim_ngrams = _compact_char_ngrams(claim_text)
    token_overlap = clause_tokens & claim_tokens
    token_overlap_weight = sum(len(token) ** 2 for token in token_overlap)
    token_weight = sum(len(token) ** 2 for token in clause_tokens)
    token_coverage = (
        round(10_000 * token_overlap_weight / token_weight)
        if token_weight
        else 0
    )
    ngram_overlap = clause_ngrams & claim_ngrams
    ngram_coverage = (
        round(10_000 * len(ngram_overlap) / len(clause_ngrams))
        if clause_ngrams
        else 0
    )
    return (
        token_coverage,
        token_overlap_weight,
        ngram_coverage,
        len(ngram_overlap),
    )


def relation_clause_for_claim(question: str, claim_text: str) -> str:
    """Map a claim to a surface relation before any semantic scoring."""

    relations = relation_focused_question_clauses(question)
    return max(
        relations,
        key=lambda relation: _claim_clause_score(relation, claim_text),
    )


def relation_clauses_for_claims(
    question: str,
    claim_texts: list[str],
) -> list[str]:
    relations = [
        relation_clause_for_claim(question, claim_text)
        for claim_text in claim_texts
    ]
    if len(relations) < 2 or len(set(relations)) == len(relations):
        return relations
    explicit_relations = [
        _relation_phrase(clause)
        for clause in explicit_question_clauses(question)
    ]
    if len(explicit_relations) < len(relations):
        return relations
    if "·" in explicit_relations[-1]:
        return relations
    return explicit_relations[: len(relations)]


def citation_semantic_text(citation: dict[str, Any]) -> tuple[str, str]:
    text = str(citation.get("text") or "").strip()
    if text:
        return _atomic_reranker_text(citation), "rag_atomic_unit"
    field_refs = set(citation.get("field_refs") or [])
    labels = {
        "title": "제목",
        "published_at": "게시일",
        "valid_from": "시작일",
        "valid_to": "종료일",
    }
    parts = [
        f"{labels[field]}: {citation[field]}"
        for field in labels
        if field in field_refs and citation.get(field) not in {None, ""}
    ]
    if parts:
        return "\n".join(parts), "metadata_fields"
    return "", "missing"


def build_relation_semantic_shadow(
    *,
    question: str,
    claims: list[dict[str, Any]],
    score_pairs: Callable[[list[tuple[str, str]]], list[float]],
) -> list[dict[str, Any]]:
    """Score accepted claim citations without changing any verifier result."""

    records: list[dict[str, Any]] = []
    pairs: list[tuple[str, str]] = []
    citation_slots: list[tuple[int, int]] = []
    relation_queries = relation_clauses_for_claims(
        question,
        [str(claim.get("text") or "").strip() for claim in claims],
    )
    for claim_index, (claim, relation_query) in enumerate(
        zip(claims, relation_queries, strict=True),
        1,
    ):
        claim_text = str(claim.get("text") or "").strip()
        citations = list(claim.get("citations") or [])
        if not citations:
            raise RuntimeError(
                f"accepted claim {claim_index} has no restored citations"
            )
        record = {
            "shadow_version": RELATION_SEMANTIC_SHADOW_VERSION,
            "claim_index": claim_index,
            "claim_text": claim_text,
            "relation_query": relation_query,
            "citation_scores": [],
            "diagnostic_only": True,
            "affects_answer": False,
            "threshold": None,
        }
        records.append(record)
        for citation_index, citation in enumerate(citations, 1):
            evidence_text, citation_kind = citation_semantic_text(citation)
            if not evidence_text:
                raise RuntimeError(
                    f"accepted claim {claim_index} citation has no text"
                )
            pairs.append((relation_query, evidence_text))
            citation_slots.append((claim_index - 1, citation_index))
    scores = list(score_pairs(pairs))
    if len(scores) != len(pairs) or not all(
        math.isfinite(float(score)) for score in scores
    ):
        raise RuntimeError("semantic shadow scores are missing or non-finite")
    for (record_index, citation_index), score in zip(
        citation_slots,
        scores,
        strict=True,
    ):
        citation = claims[record_index]["citations"][citation_index - 1]
        citation_text, citation_kind = citation_semantic_text(citation)
        records[record_index]["citation_scores"].append(
            {
                "citation_index": citation_index,
                "evidence_ref": str(citation.get("evidence_ref") or ""),
                "chunk_id": str(citation.get("chunk_id") or ""),
                "title": str(citation.get("title") or ""),
                "text": citation_text,
                "citation_kind": citation_kind,
                "context_text": str(citation.get("context_text") or ""),
                "score": round(float(score), 8),
            }
        )
    for record in records:
        record["claim_score"] = max(
            citation["score"]
            for citation in record["citation_scores"]
        )
    return records
