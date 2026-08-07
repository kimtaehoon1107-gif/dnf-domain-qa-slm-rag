from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from functools import lru_cache
from typing import Any

from src.v3.answer_target_coverage import extract_target_token_sets
from src.v3.answer_target_router import (
    _base_tag,
    _is_content_tag,
    _kiwi,
    analyze_answer_targets,
)
from src.v3.claim_aware_reranker import _quote_candidates
from src.v3.run_unified_runtime import PARTIAL_DISCLAIMER


SLOT_COVERAGE_SCHEMA_VERSION = "dnf-requirement-slot-coverage-v3.1"
SLOT_COVERAGE_VERSION = "kiwi-requirement-slot-extractive-v3.1.1"
MISSING_SLOT_TEMPLATE = "검색된 공식 문서에서 확인할 수 없습니다."


def _slot_id(terms: frozenset[str]) -> str:
    payload = "\u241f".join(sorted(terms)).encode("utf-8")
    return f"slot_sha256_{hashlib.sha256(payload).hexdigest()}"


def _slot_label(terms: frozenset[str]) -> str:
    return "·".join(sorted(term.rsplit("/", 1)[0] for term in terms))


def enumerate_requirement_slots(question: str) -> list[dict[str, Any]]:
    signal = analyze_answer_targets(question)
    if signal["coordinated_nominal_target_count"] < 2:
        return []
    return [
        {
            "slot_id": _slot_id(terms),
            "slot_label": _slot_label(terms),
            "content_morphs": sorted(terms),
        }
        for terms in extract_target_token_sets(question)
    ]


@lru_cache(maxsize=32768)
def _content_morphs(text: str) -> frozenset[str]:
    return frozenset(
        f"{token.form}/{_base_tag(token)}"
        for token in _kiwi().tokenize(text)
        if _is_content_tag(_base_tag(token))
    )


@lru_cache(maxsize=4096)
def _cached_quote_candidates(text: str) -> tuple[str, ...]:
    return tuple(_quote_candidates(text))


def _best_quote_for_slot(
    slot: dict[str, Any],
    question_morphs: frozenset[str],
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    slot_morphs = frozenset(slot["content_morphs"])
    best = None
    for quote in _cached_quote_candidates(candidate["display_text"]):
        quote_morphs = _content_morphs(quote)
        matched = slot_morphs & quote_morphs
        coverage_ratio = len(matched) / len(slot_morphs)
        novel_morphs = quote_morphs - question_morphs
        if not novel_morphs:
            continue
        row = {
            "slot_id": slot["slot_id"],
            "slot_label": slot["slot_label"],
            "chunk_id": candidate["chunk_id"],
            "parent_document_id": candidate["parent_document_id"],
            "source_id": candidate["source_id"],
            "source_kind": candidate["source_kind"],
            "retrieval_rank": int(candidate["retrieval_rank"]),
            "quote": quote,
            "coverage_ratio": round(coverage_ratio, 8),
            "matched_morph_count": len(matched),
            "answer_value_proxy_morph_count": len(novel_morphs),
        }
        key = (
            row["coverage_ratio"],
            min(row["answer_value_proxy_morph_count"], 8),
            -len(quote),
            -row["retrieval_rank"],
            row["chunk_id"],
        )
        if best is None or key > best[0]:
            best = (key, row)
    return None if best is None else best[1]


def match_slots_within_one_parent(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    overlap_threshold: float,
    preferred_parent_document_id: str | None = None,
) -> dict[str, Any]:
    if not 0.0 <= overlap_threshold <= 1.0:
        raise RuntimeError("overlap_threshold must be between 0 and 1")
    slots = enumerate_requirement_slots(question)
    if len(slots) < 2:
        return {
            "slots": slots,
            "selected_parent_document_id": None,
            "matches": [],
            "missing_slots": [],
            "coverage_state": "not_multi_slot",
        }
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_parent[candidate["parent_document_id"]].append(candidate)
    if preferred_parent_document_id in by_parent:
        by_parent = defaultdict(
            list,
            {
                preferred_parent_document_id: by_parent[
                    preferred_parent_document_id
                ]
            },
        )
    question_morphs = _content_morphs(question)
    parent_rows = []
    for parent_document_id, parent_candidates in sorted(by_parent.items()):
        matches = []
        for slot in slots:
            choices = [
                row
                for row in (
                    _best_quote_for_slot(slot, question_morphs, candidate)
                    for candidate in parent_candidates
                )
                if row is not None
                and row["coverage_ratio"] >= overlap_threshold
            ]
            if choices:
                choices.sort(
                    key=lambda row: (
                        -row["coverage_ratio"],
                        -min(row["answer_value_proxy_morph_count"], 8),
                        len(row["quote"]),
                        row["retrieval_rank"],
                        row["chunk_id"],
                    )
                )
                matches.append(choices[0])
        parent_rows.append(
            {
                "parent_document_id": parent_document_id,
                "matches": matches,
                "covered_slot_count": len(matches),
                "coverage_sum": round(
                    sum(row["coverage_ratio"] for row in matches), 8
                ),
                "answer_value_proxy_sum": sum(
                    min(row["answer_value_proxy_morph_count"], 8)
                    for row in matches
                ),
                "best_retrieval_rank": min(
                    (row["retrieval_rank"] for row in matches),
                    default=10**9,
                ),
            }
        )
    parent_rows.sort(
        key=lambda row: (
            -row["covered_slot_count"],
            -row["coverage_sum"],
            -row["answer_value_proxy_sum"],
            row["best_retrieval_rank"],
            row["parent_document_id"],
        )
    )
    selected = parent_rows[0] if parent_rows else None
    matches = [] if selected is None else selected["matches"]
    covered_slot_ids = {row["slot_id"] for row in matches}
    missing_slots = [
        slot for slot in slots if slot["slot_id"] not in covered_slot_ids
    ]
    return {
        "slots": slots,
        "selected_parent_document_id": None
        if selected is None
        else selected["parent_document_id"],
        "matches": sorted(matches, key=lambda row: row["slot_id"]),
        "missing_slots": sorted(missing_slots, key=lambda row: row["slot_id"]),
        "coverage_state": "full" if not missing_slots else "partial",
    }


def _claim_id(case_id: str, slot_id: str, chunk_id: str, quote: str) -> str:
    payload = f"{case_id}\n{slot_id}\n{chunk_id}\n{quote}".encode("utf-8")
    return f"slot_claim_sha256_{hashlib.sha256(payload).hexdigest()}"


def verify_slot_claim(
    claim: dict[str, Any],
    route: dict[str, Any],
    chunk: dict[str, Any],
    document: dict[str, Any],
    *,
    current_policy_document_id: str | None,
) -> dict[str, Any]:
    current = route["time_scope"] == "current"
    allowed_sources = set(route["source_ids"])
    allowed_kinds = set(route["source_kinds"])
    gates = {
        "citation_chunk_exact": claim["citation_chunk_id"] == chunk["chunk_id"],
        "citation_parent_exact": claim["citation_parent_document_id"]
        == chunk["parent_document_id"]
        == document["document_id"],
        "exact_canonical_quote": bool(claim["claim_text"])
        and claim["claim_text"] in chunk["display_text"],
        "source_policy": chunk["source_id"] in allowed_sources
        and (not allowed_kinds or chunk["source_kind"] in allowed_kinds)
        and document["source_id"] == chunk["source_id"]
        and document["source_kind"] == chunk["source_kind"],
        "temporal_policy": (not current)
        or (
            chunk["status"] in {"current", "upcoming"}
            and chunk["default_exposure"]
            and document["status"] in {"current", "upcoming"}
            and document["default_exposure"]
        ),
        "revision_exact": claim["revision_id"] == document["revision_id"],
        "current_policy_revision": not (
            current and document["source_id"] == "dnf_account_policy"
        )
        or document["document_id"] == current_policy_document_id,
    }
    return {"gates": gates, "verified": all(gates.values())}


def build_requirement_slot_response(
    *,
    case_id: str,
    question: str,
    answerability: str,
    route: dict[str, Any],
    candidates: list[dict[str, Any]],
    baseline_response: dict[str, Any],
    documents_by_id: dict[str, dict[str, Any]],
    current_policy_document_id: str | None,
    overlap_threshold: float,
) -> dict[str, Any]:
    """Build a slot response without accepting evaluation labels or gold IDs."""
    if route["route_action"] in {"reject", "realtime_api", "clarify"}:
        return {
            "mode": "answerability_passthrough",
            "response": copy.deepcopy(baseline_response),
            "slot_coverage": None,
            "verification_results": [],
        }
    slots = enumerate_requirement_slots(question)
    if len(slots) < 2:
        return {
            "mode": "single_slot_passthrough",
            "response": copy.deepcopy(baseline_response),
            "slot_coverage": {
                "slots": slots,
                "coverage_state": "not_multi_slot",
                "matches": [],
                "missing_slots": [],
            },
            "verification_results": [],
        }
    coverage = match_slots_within_one_parent(
        question,
        candidates,
        overlap_threshold=overlap_threshold,
        preferred_parent_document_id=next(
            iter(
                sorted(
                    {
                    row["parent_document_id"]
                    for row in candidates
                    if row["chunk_id"]
                    in set(baseline_response.get("citation_chunk_ids", []))
                    }
                )
            ),
            None,
        ),
    )
    candidate_by_id = {row["chunk_id"]: row for row in candidates}
    claims = []
    verification_results = []
    for match in coverage["matches"]:
        chunk = candidate_by_id[match["chunk_id"]]
        document = documents_by_id[chunk["parent_document_id"]]
        claim = {
            "claim_id": _claim_id(
                case_id,
                match["slot_id"],
                match["chunk_id"],
                match["quote"],
            ),
            "slot_id": match["slot_id"],
            "slot_label": match["slot_label"],
            "claim_mode": "requirement_slot_exact_extractive_quote",
            "claim_text": match["quote"],
            "citation_chunk_id": match["chunk_id"],
            "citation_parent_document_id": match["parent_document_id"],
            "source_id": match["source_id"],
            "source_kind": match["source_kind"],
            "revision_id": document["revision_id"],
            "status": chunk["status"],
            "default_exposure": chunk["default_exposure"],
            "coverage_ratio": match["coverage_ratio"],
        }
        verification = verify_slot_claim(
            claim,
            route,
            chunk,
            document,
            current_policy_document_id=current_policy_document_id,
        )
        claims.append(claim)
        verification_results.append(
            {"slot_id": match["slot_id"], **verification}
        )
    if any(not row["verified"] for row in verification_results):
        return {
            "mode": "verification_failed_passthrough",
            "response": copy.deepcopy(baseline_response),
            "slot_coverage": coverage,
            "verification_results": verification_results,
        }
    baseline_claims = copy.deepcopy(baseline_response.get("claims", []))
    baseline_claim_keys = {
        (claim["citation_chunk_id"], claim["claim_text"])
        for claim in baseline_claims
    }
    new_claims = [
        claim
        for claim in claims
        if (claim["citation_chunk_id"], claim["claim_text"])
        not in baseline_claim_keys
    ]
    rendered_lines = []
    baseline_rendered = baseline_response.get("rendered_answer", "").strip()
    if baseline_rendered:
        rendered_lines.append(baseline_rendered)
    else:
        rendered_lines.extend(
            f"- [기존 근거] {claim['claim_text']} "
            f"[{claim['citation_chunk_id']}]"
            for claim in baseline_claims
        )
    rendered_lines.extend(
        f"- [{claim['slot_label']}] {claim['claim_text']} "
        f"[{claim['citation_chunk_id']}]"
        for claim in new_claims
    )
    rendered_lines.extend(
        f"- [확인 불가: {slot['slot_label']}] {MISSING_SLOT_TEMPLATE}"
        for slot in coverage["missing_slots"]
    )
    rendered = "\n".join(rendered_lines)
    if answerability == "partial" and not rendered.startswith(PARTIAL_DISCLAIMER):
        rendered = PARTIAL_DISCLAIMER + rendered
    citation_chunk_ids = sorted(
        set(baseline_response.get("citation_chunk_ids", []))
        | {claim["citation_chunk_id"] for claim in new_claims}
    )
    return {
        "mode": "slot_coverage",
        "response": {
            "runtime_status": "success",
            "response_type": "verified_slot_extractive_answer"
            if coverage["coverage_state"] == "full"
            else "verified_slot_extractive_partial",
            "rendered_answer": rendered,
            "citation_chunk_ids": citation_chunk_ids,
            "claims": baseline_claims + new_claims,
        },
        "slot_coverage": coverage,
        "verification_results": verification_results,
        "runtime_contract": {
            "slot_coverage_schema_version": SLOT_COVERAGE_SCHEMA_VERSION,
            "slot_coverage_version": SLOT_COVERAGE_VERSION,
            "gold_ids_available": False,
            "freeform_generation_used": False,
            "domain_keyword_rule_count": 0,
            "single_parent_only": True,
            "canonical_citations_replaced": False,
            "slot_enumerator_refinement": "coordinated_nominal_targets_only",
        },
    }
