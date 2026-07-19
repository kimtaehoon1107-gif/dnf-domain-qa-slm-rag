from __future__ import annotations

from typing import Any


RERANK_SELECTOR_VERSION = "dnf-v3-adaptive-rerank-selector-v3.1.0"
DEFAULT_DEPTH = 3
FALLBACK_DEPTH = 8
LOW_CONFIDENCE_THRESHOLD = 0.1
MULTI_EVIDENCE_MARKERS = ("각각", "비교", "함께")


def is_multi_evidence_query(query: str) -> bool:
    normalized = " ".join(query.split())
    return any(marker in normalized for marker in MULTI_EVIDENCE_MARKERS)


def selection_depth(query: str, candidates: list[dict[str, Any]]) -> tuple[int, str]:
    if not query.strip():
        raise RuntimeError("query must not be empty")
    if not candidates:
        return 0, "no_candidates"
    top_score = max(float(row["reranker_score"]) for row in candidates)
    if is_multi_evidence_query(query):
        return FALLBACK_DEPTH, "multi_evidence_marker"
    if top_score < LOW_CONFIDENCE_THRESHOLD:
        return FALLBACK_DEPTH, "low_reranker_confidence"
    return DEFAULT_DEPTH, "confident_single_evidence"


def select_reranked_evidence(
    query: str,
    candidates: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    depth, reason = selection_depth(query, candidates)
    ranked = sorted(
        candidates,
        key=lambda row: (
            -float(row["reranker_score"]),
            int(row["retrieval_rank"]),
            row["chunk_id"],
        ),
    )
    output = []
    for selected_rank, candidate in enumerate(ranked[:depth], start=1):
        chunk = chunks_by_id.get(candidate["chunk_id"])
        if chunk is None:
            raise RuntimeError(f"Unknown candidate chunk: {candidate['chunk_id']}")
        output.append(
            {
                "rerank_selector_version": RERANK_SELECTOR_VERSION,
                "selected_rank": selected_rank,
                "retrieval_rank": candidate["retrieval_rank"],
                "chunk_id": candidate["chunk_id"],
                "parent_document_id": candidate["parent_document_id"],
                "source_id": candidate["source_id"],
                "status": candidate["status"],
                "default_exposure": candidate["default_exposure"],
                "review_required": candidate["review_required"],
                "heading_path": chunk["heading_path"],
                "chunk_type": chunk["chunk_type"],
                "display_text": chunk["display_text"],
                "reranker_score": candidate["reranker_score"],
                "selection_depth": depth,
                "selection_reason": reason,
                "guardrail_injected": candidate["guardrail_injected"],
            }
        )
    return output
