from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, tokenize_lexical
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.retrieve_temporal import retrieve_policy_with_embedding
from src.v3.retrieve_v3 import (
    RuntimeArtifacts,
    load_runtime_artifacts,
    retrieve_with_embedding,
)
from src.v3.select_evidence import classify_answerability
from src.v3.temporal_policy import restrict_bm25_index
from src.v3.temporal_router import classify_temporal_query, route_temporal_query


QUESTION_ROUTER_SCHEMA_VERSION = "dnf_question_router_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_question_router_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_question_router_report_v3.1"
ROUTER_VERSION = "dnf-question-router-v3.1.0"
BUILT_AT = "2026-07-19T07:00:00+09:00"
DEFAULT_AS_OF = "2026-07-18"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BM25_INDEX = Path(
    "data/v3/indexes/"
    "bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/"
    "bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_DENSE_MANIFEST = Path(
    "data/v3/indexes/"
    "dense_full_manifest_51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/"
    "account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_QUERY_EMBEDDINGS = Path(
    "data/v3/retrieval/"
    "retrieval_dev_query_embeddings_"
    "323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/question_router.py")
DEFAULT_RUNTIME_SOURCE = Path("src/v3/retrieve_v3.py")
DEFAULT_TEMPORAL_SOURCE = Path("src/v3/temporal_router.py")
DEFAULT_SCHEMA_SOURCE = Path("src/v3/schemas.py")
DEFAULT_CONTRACT = Path("docs/v3/question_router.md")

SOURCE_TO_INTENT = {
    "dnf_account_policy": "account_policy",
    "dnf_event": "active_event",
    "dnf_faq": "faq_support",
    "dnf_game_guide": "guide_rule",
    "dnf_monthly_item": "shop_price",
    "dnf_notice": "official_notice",
    "dnf_seria_shop": "shop_price",
    "dnf_update": "patch_change",
}
SOURCE_TO_STORE = {
    "dnf_account_policy": "account_policy_index",
    "dnf_event": "event_store",
    "dnf_faq": "faq_index",
    "dnf_game_guide": "game_guide_index",
    "dnf_monthly_item": "monthly_item_store",
    "dnf_notice": "notice_index",
    "dnf_seria_shop": "shop_price_store",
    "dnf_update": "patch_note_index",
}
SOURCE_TO_KIND = {
    "dnf_account_policy": ("account_policy",),
    "dnf_event": ("event",),
    "dnf_faq": ("faq",),
    "dnf_game_guide": ("game_guide",),
    "dnf_monthly_item": ("monthly_item",),
    "dnf_seria_shop": ("shop_product",),
}

DECOMPOSITION_MARKERS = ("함께", "비교", "차이를", "구분해서")
PREVIEW_MARKERS = ("퍼스트 서버", "퍼섭", "테스트 서버")
PAST_MARKERS = ("과거", "예전", "당시", "이었던", "진행됐", "종료된", "지난")
MONTH_PATTERN = re.compile(r"(?<!\d)(\d{1,2})월")
YEAR_MONTH_PATTERN = re.compile(r"(?<!\d)20\d{2}\s*년\s*\d{1,2}\s*월")
BRACKET_HEADING_PATTERN = re.compile(r"\[([^\]\r\n]{2,60})\]")

TITLE_STOP_TOKENS = frozenset(
    {
        "안내",
        "업데이트",
        "정기점검",
        "이벤트",
        "아이템",
        "던전앤파이터",
        "운영정책",
        "시행",
        "일반",
        "시스템",
        "게임",
        "이용",
        "방법",
        "어떻게",
        "언제",
        "뭐야",
        "알려줘",
    }
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _explicit_sources(query: str) -> tuple[set[str], list[str], list[str]]:
    normalized = query.lower()
    sources: set[str] = set()
    signals = []
    source_kinds = []

    def match(source_id: str, markers: tuple[str, ...], signal: str) -> bool:
        matched = [marker for marker in markers if marker.lower() in normalized]
        if matched:
            sources.add(source_id)
            signals.extend(f"{signal}:{marker}" for marker in matched)
            return True
        return False

    match("dnf_monthly_item", ("이달의 아이템", "이달 의 아이템"), "monthly")
    match(
        "dnf_account_policy",
        ("운영정책", "이용제한", "이의신청", "제재 단계"),
        "policy",
    )
    preview = match("dnf_update", PREVIEW_MARKERS, "preview")
    notice = match(
        "dnf_notice",
        (
            "클라이언트 패치",
            "클라 패치",
            "확인된 오류",
            "피싱",
            "주의사항",
            "비인가 프로그램",
            "개인정보",
            "인증번호",
            "외부 결제",
            "외부 메신저",
        ),
        "notice",
    )
    match("dnf_event", ("이벤트", "보급 작전", "보급품"), "event")
    match("dnf_faq", ("faq", "청약철회", "던파on"), "faq")
    match(
        "dnf_game_guide",
        (
            "게임가이드",
            "사용 방법",
            "무력화 게이지",
            "우편함",
            "강화/증폭/재련",
            "마법부여 상점",
            "세라 화폐",
            "경매장 구매 우편",
            "우편의 보관 기간",
        ),
        "guide",
    )
    if "세라" in normalized and any(
        marker in normalized for marker in ("현금", "충전", "화폐")
    ) and "청약철회" not in normalized:
        sources.add("dnf_game_guide")
        signals.append("guide:sera_currency_definition")
    match(
        "dnf_seria_shop",
        ("세리아 상점", "세리아샵", "마일리지샵", "아라드 패스", "캐릭터 이름 변경권"),
        "shop",
    )
    if MONTH_PATTERN.search(normalized) and any(
        marker in normalized
        for marker in (
            "상점판매가",
            "거래 타입",
            "일괄 삭제",
            "상자를 사용",
            "어떤 두 상자",
        )
    ):
        sources.add("dnf_monthly_item")
        signals.append("monthly:month_plus_structured_item_field")
    if "dnf_monthly_item" not in sources and any(
        marker in normalized for marker in ("가격", "판매가")
    ) and any(
        marker in normalized for marker in ("삭제일", "거래 타입", "판매 기간")
    ):
        sources.add("dnf_seria_shop")
        signals.append("shop:price_plus_structured_product_field")
    if "언제부터 플레이" in normalized:
        sources.add("dnf_update")
        signals.append("patch:availability_change")
    if not notice:
        match(
            "dnf_update",
            ("업데이트", "제거됐", "수정됐", "조정됐"),
            "patch",
        )

    if preview:
        source_kinds.append("preview_patch")
    elif "dnf_update" in sources:
        source_kinds.append("patch_note")
    if "dnf_notice" in sources:
        if any(marker in normalized for marker in ("클라이언트 패치", "클라 패치")):
            source_kinds.append("hotfix")
        elif any(
            marker in normalized
            for marker in (
                "피싱",
                "주의사항",
                "비인가 프로그램",
                "개인정보",
                "인증번호",
                "외부 결제",
                "외부 메신저",
            )
        ):
            source_kinds.extend(("account_policy", "enforcement_notice"))
        elif "확인된 오류" in normalized:
            source_kinds.extend(("known_issue", "hotfix"))
    return sources, sorted(set(signals)), sorted(set(source_kinds))


def _candidate_source_order(candidate_hits: list[dict[str, Any]]) -> list[str]:
    best: dict[str, tuple[int, float]] = {}
    for fallback_rank, row in enumerate(candidate_hits, start=1):
        source_id = row["source_id"]
        rank = int(row.get("rank", fallback_rank))
        score = float(row.get("base_hybrid_score", row.get("score", 0.0)) or 0.0)
        current = best.get(source_id)
        candidate = (rank, -score)
        if current is None or candidate < current:
            best[source_id] = candidate
    return sorted(best, key=lambda source_id: (*best[source_id], source_id))


def _title_source_order(
    query: str, documents: list[dict[str, Any]]
) -> list[tuple[str, float]]:
    query_tokens = {
        token
        for token in tokenize_lexical(query)
        if token not in TITLE_STOP_TOKENS and len(token) >= 2
    }
    title_token_rows = []
    document_frequency: Counter[str] = Counter()
    for row in documents:
        tokens = {
            token
            for token in tokenize_lexical(row["title"])
            if token not in TITLE_STOP_TOKENS and len(token) >= 2
        }
        title_token_rows.append((row["source_id"], tokens))
        document_frequency.update(tokens)
    source_scores: dict[str, float] = {}
    total = max(1, len(documents))
    for source_id, title_tokens in title_token_rows:
        overlap = query_tokens & title_tokens
        if not overlap:
            continue
        if len(overlap) < 2 and max(map(len, overlap)) < 4:
            continue
        score = sum(
            math.log(1.0 + total / document_frequency[token]) for token in overlap
        )
        score += 0.25 * sum(len(token) for token in overlap)
        source_scores[source_id] = max(source_scores.get(source_id, 0.0), score)
    return sorted(source_scores.items(), key=lambda item: (-item[1], item[0]))


def _stem_entity_token(token: str) -> str:
    for suffix in ("에서는", "으로는", "에서", "으로", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "과", "와"):
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def build_source_entity_index(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> dict[str, list[frozenset[str]]]:
    values: dict[str, set[tuple[str, ...]]] = {}

    def add(source_id: str, text: str) -> None:
        tokens = tuple(
            sorted(
                {
                    _stem_entity_token(token)
                    for token in tokenize_lexical(text)
                    if token not in TITLE_STOP_TOKENS and len(token) >= 2
                }
            )
        )
        if len(tokens) >= 2:
            values.setdefault(source_id, set()).add(tokens)

    for row in documents:
        add(row["source_id"], row["title"])
    for row in chunks:
        for heading in row["heading_path"]:
            add(row["source_id"], heading)
        for heading in BRACKET_HEADING_PATTERN.findall(row["display_text"]):
            add(row["source_id"], heading)
    return {
        source_id: [frozenset(tokens) for tokens in sorted(source_values)]
        for source_id, source_values in sorted(values.items())
    }


def _entity_source_order(
    query: str, source_entity_index: dict[str, list[frozenset[str]]]
) -> list[tuple[str, float]]:
    query_tokens = {
        _stem_entity_token(token)
        for token in tokenize_lexical(query)
        if token not in TITLE_STOP_TOKENS and len(token) >= 2
    }
    scores = {}
    for source_id, entities in source_entity_index.items():
        best = 0.0
        for entity_tokens in entities:
            overlap = query_tokens & entity_tokens
            if len(overlap) < 2:
                continue
            coverage = len(overlap) / len(entity_tokens)
            score = coverage * sum(len(token) for token in overlap)
            best = max(best, score)
        if best:
            scores[source_id] = best
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _source_kinds_for_route(
    source_ids: list[str], explicit_kinds: list[str]
) -> list[str]:
    output = set(explicit_kinds)
    for source_id in source_ids:
        output.update(SOURCE_TO_KIND.get(source_id, ()))
    if "dnf_update" in source_ids and not {
        "patch_note",
        "preview_patch",
    }.intersection(output):
        output.add("patch_note")
    return sorted(output)


def _route_time(
    query: str,
    source_ids: list[str],
    overlay_rows: list[dict[str, Any]],
    needs_decomposition: bool,
) -> dict[str, Any]:
    normalized = " ".join(query.lower().split())
    if source_ids == ["dnf_account_policy"]:
        temporal = route_temporal_query(query, overlay_rows)
        return {
            "time_scope": temporal["mode"],
            "temporal_as_of": temporal["as_of"],
            "needs_clarification": temporal["needs_clarification"],
            "clarification_reason": temporal["clarification_reason"],
            "temporal_route": temporal,
        }
    if any(marker in normalized for marker in PREVIEW_MARKERS):
        return {
            "time_scope": "preview",
            "temporal_as_of": None,
            "needs_clarification": False,
            "clarification_reason": None,
            "temporal_route": None,
        }

    temporal = classify_temporal_query(query)
    months = set(MONTH_PATTERN.findall(normalized))
    multiple_dates = temporal["clarification_reason"] == (
        "multiple_explicit_dates_require_target_pair"
    )
    if needs_decomposition and (len(months) >= 2 or multiple_dates):
        return {
            "time_scope": "mixed",
            "temporal_as_of": None,
            "needs_clarification": False,
            "clarification_reason": None,
            "temporal_route": None,
        }
    past_requested = bool(
        temporal["as_of"]
        or YEAR_MONTH_PATTERN.search(normalized)
        or any(marker in normalized for marker in PAST_MARKERS)
    )
    if past_requested:
        unsupported = set(source_ids).intersection({"dnf_faq", "dnf_game_guide"})
        if unsupported:
            return {
                "time_scope": "historical",
                "temporal_as_of": temporal["as_of"],
                "needs_clarification": True,
                "clarification_reason": "historical_revision_not_available_for_source",
                "temporal_route": None,
            }
        return {
            "time_scope": "historical",
            "temporal_as_of": temporal["as_of"],
            "needs_clarification": False,
            "clarification_reason": None,
            "temporal_route": None,
        }
    return {
        "time_scope": "current",
        "temporal_as_of": None,
        "needs_clarification": False,
        "clarification_reason": None,
        "temporal_route": None,
    }


def route_question(
    query: str,
    *,
    candidate_hits: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    source_entity_index: dict[str, list[frozenset[str]]],
    overlay_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise RuntimeError("query must not be empty")
    answerability = classify_answerability(normalized)
    if answerability["label"] == "false":
        realtime = answerability["reason"] in {
            "requires_private_account_state",
            "requires_realtime_auction_api",
        }
        return {
            "question_router_schema_version": QUESTION_ROUTER_SCHEMA_VERSION,
            "query": normalized,
            "intent": "realtime_api" if realtime else "ood_safety" if answerability["reason"] == "unsafe_abuse_instruction" else "unanswerable",
            "matched_intents": [],
            "required_sources": [],
            "source_ids": [],
            "source_kinds": [],
            "time_scope": "realtime" if realtime else "none",
            "temporal_as_of": None,
            "default_exposure_only": True,
            "allowed_statuses": [],
            "needs_decomposition": False,
            "needs_clarification": False,
            "clarification_reason": None,
            "route_action": "realtime_api" if realtime else "reject",
            "answerability": answerability["label"],
            "answerability_reason": answerability["reason"],
            "routing_signals": {
                "explicit": [],
                "entity_sources": [],
                "title_sources": [],
                "candidate_sources": [],
            },
        }

    explicit_sources, explicit_signals, explicit_kinds = _explicit_sources(normalized)
    candidate_order = _candidate_source_order(candidate_hits)
    entity_order = _entity_source_order(normalized, source_entity_index)
    entity_source = (
        entity_order[0][0]
        if entity_order and entity_order[0][1] >= 4.0
        else None
    )
    title_order = _title_source_order(normalized, documents)
    title_source = title_order[0][0] if title_order else None
    strong_decomposition_marker = any(
        marker in normalized.lower() for marker in DECOMPOSITION_MARKERS
    )
    each_marker = "각각" in normalized
    months = set(MONTH_PATTERN.findall(normalized))
    candidate_differs_from_explicit = bool(
        len(explicit_sources) == 1
        and candidate_order
        and candidate_order[0] not in explicit_sources
    )
    decomposition_marker = strong_decomposition_marker or (
        each_marker and (len(months) >= 2 or candidate_differs_from_explicit)
    )

    source_ids = set(explicit_sources)
    if source_ids:
        if (
            decomposition_marker
            and len(source_ids) == 1
            and candidate_order
            and source_ids == {"dnf_account_policy"}
        ):
            if candidate_order[0] not in source_ids:
                source_ids.add(candidate_order[0])
    elif decomposition_marker:
        source_ids.update(candidate_order[:2])
    elif entity_source is not None:
        source_ids.add(entity_source)
    elif title_source is not None:
        source_ids.add(title_source)
    elif candidate_order:
        source_ids.add(candidate_order[0])

    ordered_sources = sorted(source_ids)
    needs_decomposition = decomposition_marker or len(ordered_sources) > 1
    time = _route_time(
        normalized, ordered_sources, overlay_rows, needs_decomposition
    )
    source_kinds = _source_kinds_for_route(ordered_sources, explicit_kinds)
    matched_intents = sorted({SOURCE_TO_INTENT[source] for source in ordered_sources})
    if not ordered_sources:
        intent = "unanswerable"
        route_action = "reject"
    elif len(ordered_sources) > 1 or needs_decomposition:
        intent = "multi_document"
        route_action = "decompose"
    else:
        intent = SOURCE_TO_INTENT[ordered_sources[0]]
        route_action = "retrieve"
    if (
        ordered_sources == ["dnf_account_policy"]
        and time["time_scope"] == "comparison"
        and not time["needs_clarification"]
    ):
        route_action = "retrieve"
    if time["needs_clarification"]:
        route_action = "clarify"

    if time["time_scope"] == "current":
        default_exposure_only = True
        statuses = ["current", "upcoming"]
    elif time["time_scope"] == "preview":
        default_exposure_only = False
        statuses = ["unknown"]
    else:
        default_exposure_only = False
        statuses = ["current", "expired", "superseded", "unknown"]
    return {
        "question_router_schema_version": QUESTION_ROUTER_SCHEMA_VERSION,
        "query": normalized,
        "intent": intent,
        "matched_intents": matched_intents,
        "required_sources": sorted(
            {SOURCE_TO_STORE[source] for source in ordered_sources}
        ),
        "source_ids": ordered_sources,
        "source_kinds": source_kinds,
        "time_scope": time["time_scope"],
        "temporal_as_of": time["temporal_as_of"],
        "default_exposure_only": default_exposure_only,
        "allowed_statuses": statuses,
        "needs_decomposition": needs_decomposition,
        "needs_clarification": time["needs_clarification"],
        "clarification_reason": time["clarification_reason"],
        "route_action": route_action,
        "answerability": answerability["label"],
        "answerability_reason": answerability["reason"],
        "routing_signals": {
            "explicit": explicit_signals,
            "entity_sources": [
                {"source_id": source_id, "score": round(score, 8)}
                for source_id, score in entity_order[:3]
            ],
            "title_sources": [
                {"source_id": source_id, "score": round(score, 8)}
                for source_id, score in title_order[:3]
            ],
            "candidate_sources": candidate_order,
        },
    }


def search_policy_from_route(route: dict[str, Any], *, current_as_of: str) -> SearchPolicy:
    return SearchPolicy(
        default_exposure_only=route["default_exposure_only"],
        allowed_statuses=tuple(route["allowed_statuses"]),
        include_review_required=False,
        as_of=(
            current_as_of
            if route["time_scope"] == "current"
            else route["temporal_as_of"]
        ),
        source_ids=tuple(route["source_ids"]),
    )


def restrict_runtime_artifacts(
    artifacts: RuntimeArtifacts, route: dict[str, Any]
) -> RuntimeArtifacts:
    allowed_sources = set(route["source_ids"])
    allowed_kinds = set(route["source_kinds"])
    allowed_document_ids = {
        document_id
        for document_id, row in artifacts.documents_by_id.items()
        if row["source_id"] in allowed_sources
        and (not allowed_kinds or row["source_kind"] in allowed_kinds)
    }
    dense_ordinals = [
        ordinal
        for ordinal, row in enumerate(artifacts.dense_metadata)
        if row["parent_document_id"] in allowed_document_ids
    ]
    return RuntimeArtifacts(
        bm25_index=restrict_bm25_index(
            artifacts.bm25_index, tuple(sorted(allowed_document_ids))
        ),
        dense_metadata=[artifacts.dense_metadata[index] for index in dense_ordinals],
        dense_embeddings=artifacts.dense_embeddings[dense_ordinals],
        dense_model=artifacts.dense_model,
        chunks_by_id={
            chunk_id: row
            for chunk_id, row in artifacts.chunks_by_id.items()
            if row["parent_document_id"] in allowed_document_ids
        },
        documents_by_id={
            document_id: row
            for document_id, row in artifacts.documents_by_id.items()
            if document_id in allowed_document_ids
        },
        lead_by_parent={
            document_id: row
            for document_id, row in artifacts.lead_by_parent.items()
            if document_id in allowed_document_ids
        },
        provenance=artifacts.provenance,
    )


def _retrieve_for_route(
    query: str,
    query_embedding: np.ndarray,
    artifacts: RuntimeArtifacts,
    overlay_rows: list[dict[str, Any]],
    route: dict[str, Any],
    *,
    top_k: int,
    current_as_of: str,
) -> dict[str, Any]:
    if route["route_action"] != "retrieve":
        return {"route": route, "temporal_resolution": None, "hits": []}
    if route["source_ids"] == ["dnf_account_policy"]:
        temporal = retrieve_policy_with_embedding(
            query,
            query_embedding,
            artifacts,
            overlay_rows,
            mode=route["time_scope"],
            as_of=route["temporal_as_of"],
            top_k=top_k,
        )
        return {
            "route": route,
            "temporal_resolution": temporal["resolution"],
            "hits": [
                {**row, "question_router_version": ROUTER_VERSION}
                for row in temporal["hits"]
            ],
        }
    restricted = restrict_runtime_artifacts(artifacts, route)
    hits = retrieve_with_embedding(
        query,
        query_embedding,
        restricted,
        top_k=top_k,
        policy=search_policy_from_route(route, current_as_of=current_as_of),
    )
    return {
        "route": route,
        "temporal_resolution": None,
        "hits": [
            {
                **row,
                "question_router_version": ROUTER_VERSION,
                "question_intent": route["intent"],
                "question_time_scope": route["time_scope"],
            }
            for row in hits
        ],
    }


def route_and_retrieve_with_embedding(
    query: str,
    query_embedding: np.ndarray,
    artifacts: RuntimeArtifacts,
    overlay_rows: list[dict[str, Any]],
    *,
    top_k: int = 10,
    current_as_of: str = DEFAULT_AS_OF,
    source_entity_index: dict[str, list[frozenset[str]]] | None = None,
) -> dict[str, Any]:
    answerability = classify_answerability(query)
    global_hits = []
    if answerability["label"] != "false":
        global_hits = retrieve_with_embedding(
            query,
            query_embedding,
            artifacts,
            top_k=20,
            policy=SearchPolicy(as_of=current_as_of),
        )
    route = route_question(
        query,
        candidate_hits=global_hits,
        documents=list(artifacts.documents_by_id.values()),
        source_entity_index=(
            build_source_entity_index(
                list(artifacts.documents_by_id.values()),
                list(artifacts.chunks_by_id.values()),
            )
            if source_entity_index is None
            else source_entity_index
        ),
        overlay_rows=overlay_rows,
    )
    return _retrieve_for_route(
        query,
        query_embedding,
        artifacts,
        overlay_rows,
        route,
        top_k=top_k,
        current_as_of=current_as_of,
    )


def _gold_route_allowed(
    route: dict[str, Any], gold_documents: list[dict[str, Any]]
) -> bool:
    allowed_sources = set(route["source_ids"])
    allowed_kinds = set(route["source_kinds"])
    return all(
        row["source_id"] in allowed_sources
        and (not allowed_kinds or row["source_kind"] in allowed_kinds)
        for row in gold_documents
    )


def freeze_question_router(
    *,
    root: Path,
    artifact_root: Path | None = None,
    documents_path: Path,
    chunks_path: Path,
    bm25_index_path: Path,
    bm25_manifest_path: Path,
    dense_manifest_path: Path,
    overlay_path: Path,
    dev_set_path: Path,
    query_embeddings_path: Path,
    builder_source_path: Path,
    runtime_source_path: Path,
    temporal_source_path: Path,
    schema_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    documents = read_jsonl(documents_path)
    chunks = read_jsonl(chunks_path)
    overlay_rows = read_jsonl(overlay_path)
    dev_rows = read_jsonl(dev_set_path)
    documents_by_id = {row["document_id"]: row for row in documents}
    artifacts = load_runtime_artifacts(
        root,
        bm25_manifest_path=bm25_manifest_path,
        dense_manifest_path=dense_manifest_path,
        chunks_path=chunks_path,
        documents_path=documents_path,
    )
    query_embeddings = np.fromfile(query_embeddings_path, dtype="<f4")
    dimension = artifacts.dense_embeddings.shape[1]
    if query_embeddings.size != len(dev_rows) * dimension:
        raise RuntimeError("Frozen Router query embeddings have invalid size")
    query_embeddings = query_embeddings.reshape(len(dev_rows), dimension)
    source_entity_index = build_source_entity_index(documents, chunks)

    input_paths = {
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_index": bm25_index_path,
        "bm25_manifest": bm25_manifest_path,
        "dense_manifest": dense_manifest_path,
        "temporal_overlay": overlay_path,
        "adaptive_retrieval_dev": dev_set_path,
        "query_embeddings": query_embeddings_path,
        "builder_source": builder_source_path,
        "runtime_source": runtime_source_path,
        "temporal_source": temporal_source_path,
        "schema_source": schema_source_path,
        "contract": contract_path,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}

    cases = []
    exact_sources = 0
    exact_time_scope = 0
    exact_decomposition = 0
    gold_route_exclusions = 0
    route_policy_violations = 0
    empty_retrieve_results = 0
    unanswerable_route_errors = 0
    for ordinal, (dev, embedding) in enumerate(zip(dev_rows, query_embeddings)):
        routed = route_and_retrieve_with_embedding(
            dev["question"],
            embedding,
            artifacts,
            overlay_rows,
            top_k=10,
            current_as_of=DEFAULT_AS_OF,
            source_entity_index=source_entity_index,
        )
        route = routed["route"]
        expected_sources = sorted(dev["source_ids"])
        source_match = route["source_ids"] == expected_sources
        time_match = route["time_scope"] == dev["time_scope"]
        expected_decomposition = dev["query_kind"] == "multi_evidence"
        decomposition_match = route["needs_decomposition"] == expected_decomposition
        exact_sources += source_match
        exact_time_scope += time_match
        exact_decomposition += decomposition_match
        gold_documents = [documents_by_id[value] for value in dev["gold_document_ids"]]
        gold_allowed = (
            not gold_documents
            if not expected_sources
            else _gold_route_allowed(route, gold_documents)
        )
        gold_route_exclusions += not gold_allowed
        if not expected_sources:
            unanswerable_route_errors += bool(route["source_ids"] or routed["hits"])
        if route["route_action"] == "retrieve":
            empty_retrieve_results += not routed["hits"]
            allowed_sources = set(route["source_ids"])
            allowed_kinds = set(route["source_kinds"])
            for hit in routed["hits"]:
                route_policy_violations += hit["source_id"] not in allowed_sources
                route_policy_violations += bool(
                    allowed_kinds and hit["source_kind"] not in allowed_kinds
                )
                if route["time_scope"] == "current":
                    route_policy_violations += (
                        hit["status"] not in {"current", "upcoming"}
                        or not hit["default_exposure"]
                    )
        cases.append(
            {
                "case_id": dev["dev_id"],
                "query_ordinal": ordinal,
                "question": dev["question"],
                "adaptive_dev": True,
                "final_benchmark_eligible": False,
                "expected_source_ids": expected_sources,
                "expected_time_scope": dev["time_scope"],
                "expected_needs_decomposition": expected_decomposition,
                "route": route,
                "source_exact_match": source_match,
                "time_scope_exact_match": time_match,
                "decomposition_exact_match": decomposition_match,
                "gold_documents_allowed_by_route": gold_allowed,
                "retrieval_hit_count": len(routed["hits"]),
                "retrieval_source_ids": sorted(
                    {row["source_id"] for row in routed["hits"]}
                ),
            }
        )

    row_count = len(dev_rows)
    time_evaluable_count = sum(bool(row["source_ids"]) for row in dev_rows)
    source_exact_rate = exact_sources / row_count
    time_scope_exact_evaluable = sum(
        row["time_scope_exact_match"]
        for row in cases
        if row["expected_source_ids"]
    )
    time_scope_exact_rate = time_scope_exact_evaluable / time_evaluable_count
    decomposition_exact_rate = exact_decomposition / row_count
    unanswerable_count = sum(not row["source_ids"] for row in dev_rows)
    gates = {
        "adaptive_dev_source_exact_rate_ge_0_90": source_exact_rate >= 0.90,
        "adaptive_dev_time_scope_exact_rate_1": time_scope_exact_rate == 1.0,
        "adaptive_dev_decomposition_exact_rate_1": decomposition_exact_rate == 1.0,
        "gold_route_exclusions_0": gold_route_exclusions == 0,
        "route_policy_violations_0": route_policy_violations == 0,
        "unanswerable_route_errors_0": unanswerable_route_errors == 0,
        "all_retrieve_routes_return_hits": empty_retrieve_results == 0,
    }
    router_go = all(gates.values())
    decisions = {
        "adaptive_source_time_router": "GO" if router_go else "NO-GO",
        "route_filtered_retrieval": "GO" if router_go else "NO-GO",
        "decomposition_execution": "NO-GO",
        "free_form_generator_generation": "NO-GO",
        "final_benchmark": "NO-GO",
    }

    cases = sorted(cases, key=lambda row: row["case_id"])
    cases_bytes = _serialize_jsonl(cases, lambda row: row["case_id"])
    cases_sha = _sha256_bytes(cases_bytes)
    router_dir = artifact_root / "data/v3/router"
    reports_dir = artifact_root / "reports/v3"
    cases_path = router_dir / f"question_router_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "router_version": ROUTER_VERSION,
        "built_at": BUILT_AT,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "cases": {
            "path": _relative(artifact_root, cases_path),
            "sha256": cases_sha,
            "row_count": row_count,
        },
        "metrics": {
            "source_exact": exact_sources,
            "source_exact_rate": round(source_exact_rate, 8),
            "time_scope_exact": time_scope_exact_evaluable,
            "time_scope_evaluable_count": time_evaluable_count,
            "time_scope_exact_rate": round(time_scope_exact_rate, 8),
            "decomposition_exact": exact_decomposition,
            "decomposition_exact_rate": round(decomposition_exact_rate, 8),
            "unanswerable_cases": unanswerable_count,
            "unanswerable_route_errors": unanswerable_route_errors,
            "gold_route_exclusions": gold_route_exclusions,
            "route_policy_violations": route_policy_violations,
            "empty_retrieve_results": empty_retrieve_results,
        },
        "gates": gates,
        "decisions": decisions,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = router_dir / f"question_router_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "router_version": ROUTER_VERSION,
        "built_at": BUILT_AT,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "cases_sha256": cases_sha,
        "manifest_sha256": manifest_sha,
        "metrics": manifest["metrics"],
        "gates": gates,
        "decisions": decisions,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"question_router_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Question Router

## Decision

- adaptive source/time Router: **{decisions['adaptive_source_time_router']}**
- route-filtered retrieval: **{decisions['route_filtered_retrieval']}**
- decomposition execution / Generator / final benchmark: **NO-GO**

## Adaptive dev results

- rows: {row_count}
- exact source routes: {exact_sources}/{row_count} ({source_exact_rate:.2%})
- exact time scopes: {time_scope_exact_evaluable}/{time_evaluable_count} ({time_scope_exact_rate:.2%})
- exact decomposition decisions: {exact_decomposition}/{row_count} ({decomposition_exact_rate:.2%})
- unanswerable route errors: {unanswerable_route_errors}/{unanswerable_count}
- gold documents excluded by route: {gold_route_exclusions}
- routed retrieval policy violations: {route_policy_violations}
- empty single-route retrieval results: {empty_retrieve_results}

This is an adaptive development measurement, not a blind or final benchmark. Explicit
source rules run first; title overlap and the existing hybrid top-20 source order are
fallback signals. Multi-document questions stop at a decomposition handoff. Realtime
auction/account state requests never enter the corpus retriever.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"question_router_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed while freezing Question Router: {name}")
    return {
        "cases_path": str(cases_path),
        "cases_sha256": cases_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "metrics": manifest["metrics"],
        "gates": gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build and audit the v3 official-corpus Question Router"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--bm25-index", type=Path, default=root / DEFAULT_BM25_INDEX)
    parser.add_argument(
        "--bm25-manifest", type=Path, default=root / DEFAULT_BM25_MANIFEST
    )
    parser.add_argument(
        "--dense-manifest", type=Path, default=root / DEFAULT_DENSE_MANIFEST
    )
    parser.add_argument("--overlay", type=Path, default=root / DEFAULT_OVERLAY)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--query-embeddings", type=Path, default=root / DEFAULT_QUERY_EMBEDDINGS
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument(
        "--runtime-source", type=Path, default=root / DEFAULT_RUNTIME_SOURCE
    )
    parser.add_argument(
        "--temporal-source", type=Path, default=root / DEFAULT_TEMPORAL_SOURCE
    )
    parser.add_argument(
        "--schema-source", type=Path, default=root / DEFAULT_SCHEMA_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = freeze_question_router(
        root=args.root.resolve(),
        documents_path=args.documents.resolve(),
        chunks_path=args.chunks.resolve(),
        bm25_index_path=args.bm25_index.resolve(),
        bm25_manifest_path=args.bm25_manifest.resolve(),
        dense_manifest_path=args.dense_manifest.resolve(),
        overlay_path=args.overlay.resolve(),
        dev_set_path=args.dev_set.resolve(),
        query_embeddings_path=args.query_embeddings.resolve(),
        builder_source_path=args.builder_source.resolve(),
        runtime_source_path=args.runtime_source.resolve(),
        temporal_source_path=args.temporal_source.resolve(),
        schema_source_path=args.schema_source.resolve(),
        contract_path=args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
