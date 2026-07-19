from __future__ import annotations

import math
import re
from typing import Any

from src.v3.build_bm25 import tokenize_lexical


CLAIM_RERANKER_VERSION = "dnf-v3-claim-aware-reranker-v3.1.0"
MAX_QUOTE_CHARS = 700
MAX_SEGMENT_WINDOW = 8

GENERIC_QUERY_TERMS = {
    "알려줘",
    "뭐야",
    "무엇",
    "설명해줘",
    "설명해주면서",
    "정리해줘",
    "하고",
    "내",
    "상황",
    "맞게",
    "정해줘",
    "수",
    "있어",
}
TERM_ALIASES = {"사용": ("이용",)}
TERM_SUFFIXES = (
    "으로부터",
    "으로는",
    "에서는",
    "이라면",
    "하려면",
    "해야",
    "인지",
    "까지",
    "부터",
    "에서",
    "에게",
    "으로",
    "라고",
    "이면",
    "에는",
    "와의",
    "과의",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "과",
    "와",
    "로",
    "도",
)
DATE_PATTERN = re.compile(
    r"(?:20\d{2}[년./-]\s*\d{1,2}[월./-](?:\s*\d{1,2}일?)?|"
    r"\d{1,2}[./-]\d{1,2}|\d{1,2}월\s*\d{1,2}일)"
)
NUMBER_LITERAL_PATTERN = re.compile(
    r"\d[\d,]*\s*(?:개|회|시간|세라|골드)"
)


def _stem_term(value: str) -> str:
    term = value.lower().strip()
    for suffix in TERM_SUFFIXES:
        if term.endswith(suffix) and len(term) >= len(suffix) + 2:
            return term[: -len(suffix)]
    return term


def _question_terms(question: str) -> list[str]:
    terms = []
    for token in tokenize_lexical(question):
        term = _stem_term(token)
        if len(term) >= 2 and term not in GENERIC_QUERY_TERMS and term not in terms:
            terms.append(term)
    return terms


def _segment_offsets(text: str) -> list[tuple[int, int]]:
    output = []
    for block in re.finditer(r"[^\n|]+", text):
        for sentence in re.finditer(r"[^.!?]+(?:[.!?]+|$)", block.group(0)):
            start = block.start() + sentence.start()
            end = block.start() + sentence.end()
            if text[start:end].strip(" \t\r\n|#*-"):
                output.append((start, end))
    return output


def _quote_candidates(text: str) -> list[str]:
    segments = _segment_offsets(text)
    candidates = []
    seen = set()
    for start in range(len(segments)):
        for width in range(1, MAX_SEGMENT_WINDOW + 1):
            end_index = start + width - 1
            if end_index >= len(segments):
                break
            quote = text[segments[start][0] : segments[end_index][1]].strip(
                " \t\r\n|"
            )
            if not quote or len(quote) > MAX_QUOTE_CHARS:
                break
            if quote not in seen and quote in text:
                candidates.append(quote)
                seen.add(quote)
    if not candidates and text.strip():
        quote = text.strip()[:MAX_QUOTE_CHARS]
        if quote in text:
            candidates.append(quote)
    return candidates


def _required_aspects(question: str) -> list[str]:
    aspects = []
    rules = (
        ("price", ("가격", "판매가")),
        ("trade_type", ("거래 타입", "거래타입")),
        ("deletion", ("삭제",)),
        ("date_or_period", ("언제", "기간", "기한", "날짜")),
        ("duration", ("얼마나", "며칠", "보관기간", "보관 기간")),
        ("contact", ("문의", "신고")),
        ("unavailable", ("불가능", "불가")),
        ("location", ("어디", "위치")),
        ("fatigue", ("피로도",)),
        ("method", ("방법", "어떻게")),
        ("knowledge_independent", ("몰랐", "인지 여부", "인지했")),
        ("safety_action", ("주의사항", "주의 사항")),
        ("unauthorized_program_consequence", ("비인가 프로그램",)),
    )
    for name, markers in rules:
        if any(marker in question for marker in markers):
            aspects.append(name)
    return aspects


def _aspect_hits(quote: str, aspects: list[str]) -> dict[str, bool]:
    compact = " ".join(quote.split())
    return {
        "price": bool(
            re.search(r"\d[\d,]*(?:만|억)?\s*(?:세라|골드|원)", compact)
            or ("가격" in compact and re.search(r"\d", compact))
        ),
        "trade_type": any(
            marker in compact for marker in ("교환가능", "교환불가", "계정귀속")
        ),
        "deletion": "삭제" in compact and bool(DATE_PATTERN.search(compact)),
        "date_or_period": bool(DATE_PATTERN.search(compact)),
        "duration": bool(
            re.search(r"\d[\d,]*\s*(?:일|회|시간|개월|년)", compact)
        ),
        "contact": any(
            marker in compact
            for marker in ("문의", "고객센터", "신고", "1:1")
        ),
        "unavailable": any(marker in compact for marker in ("불가", "불가능")),
        "location": any(
            marker in compact for marker in ("위치", "영역", "고객센터", "문의")
        ),
        "fatigue": "피로도" in compact
        and any(marker in compact for marker in ("소모", "사용", "회복")),
        "method": any(
            marker in compact
            for marker in ("클릭", "입력", "선택", "사용", "장착", "문의")
        ),
        "knowledge_independent": "인지" in compact
        and any(marker in compact for marker in ("무관", "몰랐", "여부")),
        "safety_action": any(
            marker in compact
            for marker in (
                "문의",
                "신고",
                "멈춰",
                "응하지",
                "조심",
                "확인",
                "제재",
                "이용제한",
            )
        ),
        "unauthorized_program_consequence": bool(
            re.search(
                r"비인가\s*프로그램.{0,50}(?:제재|이용제한|사용하지|대여하지|정상 참작)",
                compact,
            )
        ),
    }


def _score_quote(
    question: str,
    quote: str,
    terms: list[str],
    term_weights: dict[str, float],
    aspects: list[str],
) -> tuple[float, dict[str, Any]]:
    compact = " ".join(quote.lower().split())
    matched_terms = [
        term
        for term in terms
        if term in compact
        or any(alias in compact for alias in TERM_ALIASES.get(term, ()))
    ]
    denominator = sum(term_weights.values()) or 1.0
    lexical_coverage = sum(term_weights[term] for term in matched_terms) / denominator
    literals = NUMBER_LITERAL_PATTERN.findall(question)
    literal_hits = [literal for literal in literals if literal in compact]
    aspect_values = _aspect_hits(quote, aspects)
    aspect_count = sum(aspect_values[name] for name in aspects)
    aspect_coverage = aspect_count / len(aspects) if aspects else 0.0
    short_penalty = 0.5 if len(quote) < 12 else 0.0
    image_penalty = 0.5 if "[image_alt]" in compact and len(quote) < 80 else 0.0
    missing_literal_penalty = 1.5 * (len(literals) - len(literal_hits))
    score = (
        6.0 * lexical_coverage
        + 4.0 * aspect_coverage
        + 0.75 * len(literal_hits)
        - missing_literal_penalty
        - short_penalty
        - image_penalty
    )
    return score, {
        "lexical_coverage": round(lexical_coverage, 8),
        "matched_terms": matched_terms,
        "required_aspects": aspects,
        "matched_aspects": [name for name in aspects if aspect_values[name]],
        "query_literals": literals,
        "matched_literals": literal_hits,
    }


def rerank_evidence(
    question: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rerank selected evidence without accepting evaluation labels."""
    if not question.strip():
        raise RuntimeError("question must not be empty")
    if not candidates:
        return []
    terms = _question_terms(question)
    document_frequency = {
        term: sum(term in row["display_text"].lower() for row in candidates)
        for term in terms
    }
    term_weights = {
        term: 1.0 + math.log((len(candidates) + 1) / (frequency + 1))
        for term, frequency in document_frequency.items()
    }
    aspects = _required_aspects(question)
    scored = []
    for fallback_rank, candidate in enumerate(candidates, start=1):
        quotes = _quote_candidates(candidate["display_text"])
        quote_scores = [
            (
                *_score_quote(question, quote, terms, term_weights, aspects),
                quote,
            )
            for quote in quotes
        ]
        if not quote_scores:
            raise RuntimeError(f"No exact quote candidate: {candidate['chunk_id']}")
        prefer_short = "unauthorized_program_consequence" in aspects
        quote_scores.sort(
            key=lambda row: (
                row[0],
                -len(row[2]) if prefer_short else len(row[2]),
                row[2],
            ),
            reverse=True,
        )
        quote_score, components, preferred_quote = quote_scores[0]
        original_rank = int(candidate.get("selected_rank", fallback_rank))
        model_score_available = "reranker_score" in candidate
        model_score = float(candidate.get("reranker_score", 0.0))
        scored.append(
            {
                **candidate,
                "claim_reranker_version": CLAIM_RERANKER_VERSION,
                "original_selected_rank": original_rank,
                "preferred_quote": preferred_quote,
                "claim_relevance_score": round(
                    quote_score + model_score + 0.05 / original_rank, 8
                ),
                "claim_relevance_components": {
                    **components,
                    "quote_score": round(quote_score, 8),
                    "model_score": round(model_score, 8),
                    "model_score_available": model_score_available,
                },
            }
        )

    baseline = min(scored, key=lambda row: row["original_selected_rank"])
    baseline_components = baseline["claim_relevance_components"]
    baseline_aspects = len(baseline_components["matched_aspects"])
    baseline_literals = len(baseline_components["matched_literals"])
    baseline_lexical = float(baseline_components["lexical_coverage"])
    baseline_model_available = bool(baseline_components["model_score_available"])
    baseline_model_score = float(baseline_components["model_score"])
    for row in scored:
        components = row["claim_relevance_components"]
        aspect_gain = len(components["matched_aspects"]) - baseline_aspects
        literal_gain = len(components["matched_literals"]) - baseline_literals
        lexical_gain = float(components["lexical_coverage"]) - baseline_lexical
        strong_model_gain = bool(
            baseline_model_available
            and components["model_score_available"]
            and float(components["model_score"]) >= 0.80
            and float(components["model_score"]) - baseline_model_score >= 0.30
        )
        if strong_model_gain:
            promotion_tier = 4
            promotion_reason = "strong_bge_relevance_gain"
        elif literal_gain > 0:
            promotion_tier = 3
            promotion_reason = "query_literal_coverage_gain"
        elif aspect_gain > 0 and lexical_gain >= 0 and (
            len(aspects) >= 2
            or bool(
                {"knowledge_independent", "safety_action"}.intersection(
                    components["matched_aspects"]
                )
            )
        ):
            promotion_tier = 2
            promotion_reason = "required_aspect_coverage_gain"
        elif (
            lexical_gain >= 0.35
            and aspects
            and len(components["matched_aspects"]) == len(aspects)
        ):
            promotion_tier = 1
            promotion_reason = "material_lexical_coverage_gain"
        else:
            promotion_tier = 0
            promotion_reason = "retain_original_order"
        row["promotion_tier"] = promotion_tier
        row["promotion_reason"] = promotion_reason
        row["score_first_within_tier"] = bool(
            promotion_tier in {3, 4}
            or bool(
                {"knowledge_independent", "safety_action"}.intersection(
                    components["matched_aspects"]
                )
            )
        )
    scored.sort(
        key=lambda row: (
            -row["promotion_tier"],
            -row["claim_relevance_score"]
            if row["score_first_within_tier"]
            else 0.0,
            row["original_selected_rank"],
            -row["claim_relevance_score"]
            if row["promotion_tier"] and not row["score_first_within_tier"]
            else 0.0,
            row["chunk_id"],
        )
    )
    return [
        {**row, "rerank_rank": rank}
        for rank, row in enumerate(scored, start=1)
    ]
