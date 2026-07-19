from __future__ import annotations

from typing import Any

from src.v3.build_bm25 import tokenize_lexical


SELECTOR_VERSION = "dnf-v3-evidence-selector-v3.1.0"
CANDIDATE_DEPTH = 10
BASE_SELECTION_LIMIT = 8
HYBRID_SCORE_WEIGHT = 0.75
QUERY_COVERAGE_WEIGHT = 0.25


def classify_answerability(query: str) -> dict[str, str]:
    normalized = " ".join(query.lower().split())
    if not normalized:
        raise RuntimeError("query must not be empty")

    unsupported_rules = (
        (
            "protected_internal_instruction",
            any(term in normalized for term in ("시스템 프롬프트", "내부 평가", "숨겨진 지침")),
        ),
        (
            "unsupported_lottery_prediction",
            any(term in normalized for term in ("로또", "복권"))
            and any(term in normalized for term in ("번호", "예측", "찍어")),
        ),
        (
            "unsupported_financial_prediction",
            any(term in normalized for term in ("비트코인", "주식", "가상화폐"))
            and any(term in normalized for term in ("오를", "내려갈", "예측", "전망")),
        ),
        (
            "unsupported_weather_forecast",
            any(term in normalized for term in ("날씨", "비 와", "비와", "기온", "미세먼지"))
            and any(term in normalized for term in ("오늘", "내일", "모레", "이번 주")),
        ),
        (
            "requires_private_account_state",
            "내 계정" in normalized
            and any(term in normalized for term in ("제재 상태", "정지 상태", "지금 확인")),
        ),
        (
            "requires_realtime_auction_api",
            "경매장" in normalized
            and "시세" in normalized
            and any(term in normalized for term in ("지금", "현재", "실시간")),
        ),
        (
            "unsafe_abuse_instruction",
            any(term in normalized for term in ("꼼수", "악용", "버그 이용"))
            and any(term in normalized for term in ("순서", "방법", "알려")),
        ),
        (
            "unsupported_subjective_prediction",
            any(term in normalized for term in ("네 생각", "순위 매겨", "최강 직업"))
            and any(term in normalized for term in ("앞으로", "될지", "순위")),
        ),
    )
    for reason, matched in unsupported_rules:
        if matched:
            return {"label": "false", "reason": reason}

    advice_markers = (
        "정해줘",
        "판단해줘",
        "골라줘",
        "바꿔야 할지",
        "게 좋을지",
        "게 좋아",
        "제일 좋아",
        "내 상황에 맞게",
    )
    if any(marker in normalized for marker in advice_markers):
        return {"label": "partial", "reason": "official_fact_plus_personal_judgment"}
    return {"label": "true", "reason": "official_document_fact_request"}


def _query_coverage(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    evidence_tokens = set(tokenize_lexical(text))
    return len(query_tokens & evidence_tokens) / len(query_tokens)


def select_evidence(
    query: str,
    retrieval_hits: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not query.strip():
        raise RuntimeError("query must not be empty")
    if not retrieval_hits:
        return []

    query_tokens = set(tokenize_lexical(query))
    scored = []
    for fallback_rank, hit in enumerate(retrieval_hits[:CANDIDATE_DEPTH], start=1):
        chunk_id = hit["chunk_id"]
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            raise RuntimeError(f"Unknown candidate chunk: {chunk_id}")
        coverage = _query_coverage(query_tokens, chunk["retrieval_text"])
        base_score = float(hit.get("base_hybrid_score", hit.get("base_score")) or 0.0)
        selector_score = (
            HYBRID_SCORE_WEIGHT * base_score + QUERY_COVERAGE_WEIGHT * coverage
        )
        scored.append(
            {
                "hit": hit,
                "chunk": chunk,
                "retrieval_rank": int(hit.get("rank", fallback_rank)),
                "query_token_coverage": round(coverage, 8),
                "selector_score": round(selector_score, 8),
            }
        )

    scored.sort(
        key=lambda row: (
            -row["selector_score"],
            row["retrieval_rank"],
            row["hit"]["chunk_id"],
        )
    )
    selected = [
        {**row, "selection_reason": "selector_score_top_8"}
        for row in scored[:BASE_SELECTION_LIMIT]
    ]
    selected_ids = {row["hit"]["chunk_id"] for row in selected}
    for row in sorted(scored, key=lambda value: value["retrieval_rank"]):
        hit = row["hit"]
        is_guard = bool(hit.get("guardrail_injected"))
        if is_guard and hit["chunk_id"] not in selected_ids:
            selected.append({**row, "selection_reason": "structured_parent_lead_guard"})
            selected_ids.add(hit["chunk_id"])

    output = []
    for selected_rank, row in enumerate(selected, start=1):
        hit = row["hit"]
        chunk = row["chunk"]
        output.append(
            {
                "selector_version": SELECTOR_VERSION,
                "selected_rank": selected_rank,
                "retrieval_rank": row["retrieval_rank"],
                "chunk_id": hit["chunk_id"],
                "parent_document_id": hit.get(
                    "parent_document_id", chunk["parent_document_id"]
                ),
                "source_id": hit.get("source_id", chunk["source_id"]),
                "source_kind": hit.get("source_kind", chunk["source_kind"]),
                "status": hit.get("status", chunk["status"]),
                "default_exposure": hit.get(
                    "default_exposure", chunk["default_exposure"]
                ),
                "review_required": hit.get(
                    "review_required", chunk["review_required"]
                ),
                "heading_path": chunk["heading_path"],
                "chunk_type": chunk["chunk_type"],
                "display_text": chunk["display_text"],
                "query_token_coverage": row["query_token_coverage"],
                "selector_score": row["selector_score"],
                "selection_reason": row["selection_reason"],
                "guardrail_injected": bool(hit.get("guardrail_injected")),
            }
        )
    return output
