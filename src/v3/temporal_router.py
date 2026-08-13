from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.retrieve_temporal import retrieve_policy_with_embedding
from src.v3.retrieve_v3 import RuntimeArtifacts
from src.v3.select_evidence import select_evidence
from src.v3.temporal_policy import (
    restrict_bm25_index,
    resolve_policy_revisions,
    search_policy_for_resolution,
)


ROUTER_SCHEMA_VERSION = "dnf_account_policy_temporal_router_v3.1"
GENERATOR_ENTRY_SCHEMA_VERSION = "dnf_temporal_generator_entry_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_temporal_router_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_temporal_router_report_v3.1"
ROUTER_VERSION = "dnf-account-policy-temporal-router-v3.1.0"
BUILT_AT = "2026-07-19T05:30:00+09:00"

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
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/"
    "account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_CONFLICT_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_revision_conflict_packet_"
    "8c2b64e9844458503e771a8a8f5d622eccdb857ae6629c4113f1c5b4e957ce4f.jsonl"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/temporal_router.py")
DEFAULT_RETRIEVER_SOURCE = Path("src/v3/retrieve_temporal.py")
DEFAULT_SELECTOR_SOURCE = Path("src/v3/select_evidence.py")
DEFAULT_SCHEMA_SOURCE = Path("src/v3/schemas.py")
DEFAULT_CONTRACT = Path("docs/v3/temporal_router.md")

ISO_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)")
KOREAN_DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})\s*년")

CURRENT_MARKERS = ("현재", "최신", "지금")
HISTORICAL_MARKERS = ("예전", "과거", "당시", "그때", "옛날", "이전 정책")
ADJACENT_COMPARISON_MARKERS = (
    "최신과 직전",
    "최신 정책과 직전",
    "직전 정책",
    "변경 전후",
    "변경 전과 후",
)
COMPARISON_MARKERS = ("비교", "차이", "달라졌", "변경 전후", "변경 전과 후")

REGRESSION_CASES = (
    {
        "case_id": "current_duration_number_not_date",
        "query": "해킹 피해 복구 신청은 발생 후 15일 이내여야 해?",
        "expected_mode": "current",
        "expected_as_of": None,
        "expected_clarification": False,
    },
    {
        "case_id": "current_explicit",
        "query": "현재 운영정책의 사기 이용제한은 어떻게 돼?",
        "expected_mode": "current",
        "expected_as_of": None,
        "expected_clarification": False,
    },
    {
        "case_id": "historical_korean_exact_date",
        "query": "2024년 1월 31일 당시 운영정책의 복구 기준은?",
        "expected_mode": "historical",
        "expected_as_of": "2024-01-31",
        "expected_clarification": False,
    },
    {
        "case_id": "historical_iso_exact_date",
        "query": "2025-09-18 기준 운영정책의 거래정지 의무 기간은?",
        "expected_mode": "historical",
        "expected_as_of": "2025-09-18",
        "expected_clarification": False,
    },
    {
        "case_id": "historical_missing_date",
        "query": "예전 운영정책에서 우편정책 위반 제재는 어땠어?",
        "expected_mode": "historical",
        "expected_as_of": None,
        "expected_clarification": True,
    },
    {
        "case_id": "historical_year_only",
        "query": "2024년 운영정책에서 사기 제재는 어떻게 됐어?",
        "expected_mode": "historical",
        "expected_as_of": None,
        "expected_clarification": True,
    },
    {
        "case_id": "comparison_latest_previous",
        "query": "최신 정책과 직전 정책의 사기 제재를 비교해줘.",
        "expected_mode": "comparison",
        "expected_as_of": "2026-03-15",
        "expected_clarification": False,
    },
    {
        "case_id": "comparison_change_boundary",
        "query": "운영정책 변경 전후의 복구 기준 차이를 알려줘.",
        "expected_mode": "comparison",
        "expected_as_of": "2026-03-15",
        "expected_clarification": False,
    },
    {
        "case_id": "comparison_historical_exact_date",
        "query": "2025년 9월 18일 정책과 직전 정책의 차이를 비교해줘.",
        "expected_mode": "comparison",
        "expected_as_of": "2025-09-18",
        "expected_clarification": False,
    },
    {
        "case_id": "comparison_ambiguous_past",
        "query": "현재와 과거 운영정책의 사기 제재를 비교해줘.",
        "expected_mode": "comparison",
        "expected_as_of": None,
        "expected_clarification": True,
    },
    {
        "case_id": "comparison_multiple_dates",
        "query": "2024년 1월 31일과 2025년 9월 18일 정책을 비교해줘.",
        "expected_mode": "comparison",
        "expected_as_of": None,
        "expected_clarification": True,
    },
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _extract_dates(query: str) -> list[str]:
    values = []
    for pattern in (ISO_DATE_PATTERN, KOREAN_DATE_PATTERN):
        for year, month, day in pattern.findall(query):
            try:
                value = date(int(year), int(month), int(day)).isoformat()
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid explicit date: {year}-{month}-{day}"
                ) from exc
            values.append(value)
    return sorted(set(values))


def classify_temporal_query(query: str) -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise RuntimeError("query must not be empty")

    exact_dates = _extract_dates(normalized)
    year_mentions = sorted(set(YEAR_PATTERN.findall(normalized)))
    current_markers = [marker for marker in CURRENT_MARKERS if marker in normalized]
    historical_markers = [
        marker for marker in HISTORICAL_MARKERS if marker in normalized
    ]
    adjacent_markers = [
        marker for marker in ADJACENT_COMPARISON_MARKERS if marker in normalized
    ]
    comparison_markers = [
        marker for marker in COMPARISON_MARKERS if marker in normalized
    ]
    has_historical_anchor = bool(historical_markers or exact_dates or year_mentions)
    is_comparison = bool(adjacent_markers) or bool(
        comparison_markers
        and (
            len(exact_dates) > 1
            or (current_markers and has_historical_anchor)
        )
    )

    mode = (
        "comparison"
        if is_comparison
        else "historical"
        if has_historical_anchor
        else "current"
    )
    as_of = exact_dates[0] if len(exact_dates) == 1 else None
    needs_clarification = False
    clarification_reason = None
    as_of_source = "explicit_full_date" if as_of else None

    if len(exact_dates) > 1:
        needs_clarification = True
        clarification_reason = "multiple_explicit_dates_require_target_pair"
    elif mode == "historical" and as_of is None:
        needs_clarification = True
        clarification_reason = "historical_mode_requires_exact_date"
    elif mode == "comparison" and as_of is None:
        if adjacent_markers and not historical_markers and not year_mentions:
            as_of_source = "latest_current_revision"
        else:
            needs_clarification = True
            clarification_reason = "comparison_mode_requires_exact_past_anchor"

    matched_markers = sorted(
        set(
            current_markers
            + historical_markers
            + adjacent_markers
            + comparison_markers
            + [f"date:{value}" for value in exact_dates]
            + [f"year:{value}" for value in year_mentions if not exact_dates]
        )
    )
    return {
        "temporal_router_schema_version": ROUTER_SCHEMA_VERSION,
        "query": normalized,
        "mode": mode,
        "as_of": as_of,
        "as_of_source": as_of_source,
        "needs_clarification": needs_clarification,
        "clarification_reason": clarification_reason,
        "matched_markers": matched_markers,
        "router_decision": (
            "request_temporal_clarification"
            if needs_clarification
            else "route_current_revision"
            if mode == "current"
            else "route_as_of_revision"
            if mode == "historical"
            else "route_revision_pair"
        ),
    }


def route_temporal_query(
    query: str, overlay_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    route = classify_temporal_query(query)
    if (
        route["mode"] == "comparison"
        and not route["needs_clarification"]
        and route["as_of_source"] == "latest_current_revision"
    ):
        current = [row for row in overlay_rows if row["is_current_revision"]]
        if len(current) != 1:
            raise RuntimeError("Temporal overlay must contain exactly one current revision")
        route = {**route, "as_of": current[0]["valid_from"]}
    return route


def _revision_context(
    overlay_rows: list[dict[str, Any]], resolution: dict[str, Any]
) -> list[dict[str, Any]]:
    by_id = {row["document_id"]: row for row in overlay_rows}
    return [
        {
            "document_id": document_id,
            "temporal_role": resolution["document_roles"][document_id],
            "revision_id": by_id[document_id]["revision_id"],
            "valid_from": by_id[document_id]["valid_from"],
            "valid_to": by_id[document_id]["valid_to"],
            "status": by_id[document_id]["status"],
            "is_current_revision": by_id[document_id]["is_current_revision"],
            "last_verified_at": by_id[document_id]["last_verified_at"],
        }
        for document_id in resolution["allowed_document_ids"]
    ]


def _routed_result(
    route: dict[str, Any],
    overlay_rows: list[dict[str, Any]],
    resolution: dict[str, Any] | None,
    hits: list[dict[str, Any]],
) -> dict[str, Any]:
    if resolution is None:
        return {
            "route": route,
            "resolution": None,
            "revision_context": [],
            "hits": [],
        }
    roles = resolution["document_roles"]
    decorated_hits = [
        {
            **hit,
            "temporal_router_version": ROUTER_VERSION,
            "temporal_mode": route["mode"],
            "temporal_as_of": route["as_of"],
            "temporal_role": roles[hit["parent_document_id"]],
        }
        for hit in hits
    ]
    return {
        "route": route,
        "resolution": resolution,
        "revision_context": _revision_context(overlay_rows, resolution),
        "hits": decorated_hits,
    }


def route_and_retrieve_with_embedding(
    query: str,
    query_embedding: np.ndarray,
    artifacts: RuntimeArtifacts,
    overlay_rows: list[dict[str, Any]],
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    route = route_temporal_query(query, overlay_rows)
    if route["needs_clarification"]:
        return _routed_result(route, overlay_rows, None, [])
    retrieved = retrieve_policy_with_embedding(
        query,
        query_embedding,
        artifacts,
        overlay_rows,
        mode=route["mode"],
        as_of=route["as_of"],
        top_k=top_k,
    )
    return _routed_result(
        route,
        overlay_rows,
        retrieved["resolution"],
        retrieved["hits"],
    )


def select_temporal_evidence(
    query: str,
    routed_result: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if routed_result["route"]["needs_clarification"]:
        return []
    resolution = routed_result["resolution"]
    if resolution is None:
        raise RuntimeError("Resolved route is missing temporal resolution")
    roles = resolution["document_roles"]
    selected = select_evidence(query, routed_result["hits"], chunks_by_id)
    output = []
    for row in selected:
        parent_id = row["parent_document_id"]
        if parent_id not in roles:
            raise RuntimeError(f"Evidence escaped temporal resolution: {parent_id}")
        output.append(
            {
                **row,
                "temporal_mode": routed_result["route"]["mode"],
                "temporal_as_of": routed_result["route"]["as_of"],
                "temporal_role": roles[parent_id],
            }
        )
    return output


def build_temporal_generator_entry(
    query: str,
    routed_result: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    route = routed_result["route"]
    resolution = routed_result["resolution"]
    violations = []
    if route["needs_clarification"]:
        violations.append("temporal_clarification_required")
    if resolution is None:
        violations.append("temporal_resolution_missing")
    if not evidence_rows:
        violations.append("evidence_missing")

    roles = resolution["document_roles"] if resolution is not None else {}
    allowed_ids = set(resolution["allowed_document_ids"]) if resolution else set()
    evidence_roles = set()
    decorated_evidence = []
    for row in evidence_rows:
        parent_id = row["parent_document_id"]
        if parent_id not in allowed_ids:
            violations.append("evidence_document_not_allowed")
            temporal_role = "disallowed"
        else:
            temporal_role = roles[parent_id]
            evidence_roles.add(temporal_role)
        if route["mode"] == "current" and (
            row["status"] != "current" or not row["default_exposure"]
        ):
            violations.append("non_current_evidence_in_current_mode")
        decorated_evidence.append({**row, "temporal_role": temporal_role})

    if route["mode"] == "comparison" and resolution is not None:
        required_roles = set(roles.values())
        if not required_roles.issubset(evidence_roles):
            violations.append("comparison_revision_pair_incomplete")

    revision_context = routed_result["revision_context"]
    disclosures = []
    if revision_context:
        if route["mode"] == "current":
            disclosures.append(
                f"현재 정책 시행일: {revision_context[0]['valid_from']}"
            )
        elif route["mode"] == "historical":
            disclosures.append(f"답변 기준일: {route['as_of']}")
            disclosures.append(
                "해당 시점 정책의 유효기간: "
                f"{revision_context[0]['valid_from']}~"
                f"{revision_context[0]['valid_to'] or '현재'}"
            )
        else:
            disclosures.extend(
                f"{row['temporal_role']} 시행일: {row['valid_from']}"
                for row in revision_context
            )

    return {
        "generator_entry_schema_version": GENERATOR_ENTRY_SCHEMA_VERSION,
        "query": query,
        "temporal_mode": route["mode"],
        "temporal_as_of": route["as_of"],
        "generation_allowed": not violations,
        "blocked_reasons": sorted(set(violations)),
        "required_answer_disclosures": disclosures,
        "revision_context": revision_context,
        "evidence": decorated_evidence,
    }


def _audit_regression_cases(
    overlay_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    rows = []
    errors = 0
    for case in REGRESSION_CASES:
        route = route_temporal_query(case["query"], overlay_rows)
        resolution = None
        if not route["needs_clarification"]:
            resolution = resolve_policy_revisions(
                overlay_rows, mode=route["mode"], as_of=route["as_of"]
            )
        matches = (
            route["mode"] == case["expected_mode"]
            and route["as_of"] == case["expected_as_of"]
            and route["needs_clarification"] == case["expected_clarification"]
        )
        errors += not matches
        rows.append(
            {
                "case_id": case["case_id"],
                "case_kind": "authored_temporal_regression",
                "query": case["query"],
                "expected_mode": case["expected_mode"],
                "expected_as_of": case["expected_as_of"],
                "expected_clarification": case["expected_clarification"],
                "route": route,
                "selected_document_id": (
                    resolution["selected_document_id"] if resolution else None
                ),
                "allowed_document_ids": (
                    resolution["allowed_document_ids"] if resolution else []
                ),
                "matches_expected": matches,
            }
        )
    return rows, errors


def freeze_temporal_router(
    *,
    root: Path,
    artifact_root: Path | None = None,
    documents_path: Path,
    chunks_path: Path,
    bm25_index_path: Path,
    overlay_path: Path,
    conflict_packet_path: Path,
    builder_source_path: Path,
    retriever_source_path: Path,
    selector_source_path: Path,
    schema_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    documents = read_jsonl(documents_path)
    chunks = read_jsonl(chunks_path)
    overlay_rows = read_jsonl(overlay_path)
    conflict_rows = read_jsonl(conflict_packet_path)
    index = json.loads(bm25_index_path.read_text(encoding="utf-8"))
    chunks_by_id = {row["chunk_id"]: row for row in chunks}

    input_paths = {
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_index": bm25_index_path,
        "temporal_overlay": overlay_path,
        "cancelled_revision_conflict_packet": conflict_packet_path,
        "builder_source": builder_source_path,
        "retriever_source": retriever_source_path,
        "selector_source": selector_source_path,
        "schema_source": schema_source_path,
        "contract": contract_path,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}

    current_case_rows = []
    current_errors = 0
    non_current_leaks = 0
    generator_blocks = 0
    current_resolution = resolve_policy_revisions(overlay_rows, mode="current")
    current_index = restrict_bm25_index(
        index, current_resolution["allowed_document_ids"]
    )
    for ordinal, packet_row in enumerate(conflict_rows, start=1):
        query = packet_row["question"]
        route = route_temporal_query(query, overlay_rows)
        hits = search_bm25(
            current_index,
            query,
            top_k=10,
            policy=search_policy_for_resolution(current_resolution),
        )
        hits = [{**row, "base_score": row["score"]} for row in hits]
        routed = _routed_result(
            route, overlay_rows, current_resolution if not route["needs_clarification"] else None, hits
        )
        evidence = select_temporal_evidence(query, routed, chunks_by_id)
        generator_entry = build_temporal_generator_entry(query, routed, evidence)
        route_ok = route["mode"] == "current" and not route["needs_clarification"]
        current_errors += not route_ok
        non_current_leaks += sum(
            row["parent_document_id"] != current_resolution["selected_document_id"]
            for row in hits
        )
        generator_blocks += not generator_entry["generation_allowed"]
        current_case_rows.append(
            {
                "case_id": f"cancelled_conflict_current_{ordinal:02d}",
                "case_kind": "actual_cancelled_conflict_current_regression",
                "query": query,
                "expected_mode": "current",
                "expected_as_of": None,
                "expected_clarification": False,
                "route": route,
                "selected_document_id": current_resolution["selected_document_id"],
                "allowed_document_ids": current_resolution["allowed_document_ids"],
                "retrieval_hit_count": len(hits),
                "selected_evidence_count": len(evidence),
                "generation_allowed": generator_entry["generation_allowed"],
                "matches_expected": route_ok and generator_entry["generation_allowed"],
            }
        )

    regression_rows, regression_errors = _audit_regression_cases(overlay_rows)
    leak_candidate = next(
        row
        for row in chunks
        if row["source_id"] == "dnf_account_policy" and row["status"] == "superseded"
    )
    reference = current_case_rows[0]
    reference_query = reference["query"]
    reference_route = route_temporal_query(reference_query, overlay_rows)
    reference_hits = search_bm25(
        current_index,
        reference_query,
        top_k=3,
        policy=search_policy_for_resolution(current_resolution),
    )
    reference_hits = [{**row, "base_score": row["score"]} for row in reference_hits]
    reference_result = _routed_result(
        reference_route, overlay_rows, current_resolution, reference_hits
    )
    reference_evidence = select_temporal_evidence(
        reference_query, reference_result, chunks_by_id
    )
    injected = {
        **reference_evidence[0],
        "chunk_id": leak_candidate["chunk_id"],
        "parent_document_id": leak_candidate["parent_document_id"],
        "status": leak_candidate["status"],
        "default_exposure": leak_candidate["default_exposure"],
    }
    leak_guard = build_temporal_generator_entry(
        reference_query, reference_result, reference_evidence + [injected]
    )

    case_rows = sorted(
        current_case_rows + regression_rows, key=lambda row: row["case_id"]
    )
    cases_bytes = _serialize_jsonl(case_rows, lambda row: row["case_id"])
    cases_sha = _sha256_bytes(cases_bytes)
    temporal_dir = artifact_root / "data/v3/temporal"
    reports_dir = artifact_root / "reports/v3"
    cases_path = temporal_dir / f"temporal_router_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)

    gates = {
        "authored_regression_errors_0": regression_errors == 0,
        "actual_current_route_errors_0": current_errors == 0,
        "actual_current_non_current_leaks_0": non_current_leaks == 0,
        "actual_current_generator_blocks_0": generator_blocks == 0,
        "ambiguous_historical_requires_clarification": all(
            row["route"]["needs_clarification"]
            for row in regression_rows
            if row["case_id"] in {"historical_missing_date", "historical_year_only"}
        ),
        "comparison_pair_resolves_two_documents": all(
            len(row["allowed_document_ids"]) == 2
            for row in regression_rows
            if row["route"]["mode"] == "comparison"
            and not row["route"]["needs_clarification"]
        ),
        "generator_guard_rejects_injected_superseded_evidence": (
            not leak_guard["generation_allowed"]
            and "evidence_document_not_allowed" in leak_guard["blocked_reasons"]
            and "non_current_evidence_in_current_mode" in leak_guard["blocked_reasons"]
        ),
    }
    router_go = all(gates.values())
    decisions = {
        "account_policy_temporal_intent_router": "GO" if router_go else "NO-GO",
        "current_mode_pipeline": "GO" if router_go else "NO-GO",
        "historical_mode_pipeline": "GO" if router_go else "NO-GO",
        "comparison_mode_pipeline": "GO" if router_go else "NO-GO",
        "temporal_generator_entry_guard": "GO" if router_go else "NO-GO",
        "free_form_generator_generation": "NO-GO",
        "broad_question_router": "NO-GO",
        "final_benchmark": "NO-GO",
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "router_version": ROUTER_VERSION,
        "built_at": BUILT_AT,
        "inputs": {
            name: {
                "path": _relative(root, path),
                "sha256": input_hashes[name],
            }
            for name, path in input_paths.items()
        },
        "cases": {
            "path": _relative(artifact_root, cases_path),
            "sha256": cases_sha,
            "row_count": len(case_rows),
            "actual_current_rows": len(current_case_rows),
            "authored_regression_rows": len(regression_rows),
        },
        "gates": gates,
        "decisions": decisions,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = temporal_dir / f"temporal_router_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "router_version": ROUTER_VERSION,
        "built_at": BUILT_AT,
        "cases_sha256": cases_sha,
        "manifest_sha256": manifest_sha,
        "summary": {
            "actual_current_cases": len(current_case_rows),
            "authored_regression_cases": len(regression_rows),
            "current_route_errors": current_errors,
            "authored_regression_errors": regression_errors,
            "current_non_current_leaks": non_current_leaks,
            "current_generator_blocks": generator_blocks,
            "clarification_cases": sum(
                row["route"]["needs_clarification"] for row in regression_rows
            ),
            "generator_leak_guard_blocked": not leak_guard["generation_allowed"],
        },
        "gates": gates,
        "decisions": decisions,
        "generator_leak_guard": {
            "generation_allowed": leak_guard["generation_allowed"],
            "blocked_reasons": leak_guard["blocked_reasons"],
        },
        "input_row_counts": {
            "documents": len(documents),
            "chunks": len(chunks),
            "policy_revisions": len(overlay_rows),
            "cancelled_conflict_questions": len(conflict_rows),
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"temporal_router_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Temporal Router

## Decision

- account-policy temporal intent router: **{decisions['account_policy_temporal_intent_router']}**
- current / historical / comparison pipelines: **{decisions['current_mode_pipeline']}**
- temporal Generator entry guard: **{decisions['temporal_generator_entry_guard']}**
- free-form generation / broad Router / final benchmark: **NO-GO**

## Regression

- actual current-policy questions: {len(current_case_rows)}
- authored temporal boundary cases: {len(regression_rows)}
- route errors: {current_errors + regression_errors}
- non-current retrieval leaks: {non_current_leaks}
- current Generator entry blocks: {generator_blocks}
- ambiguous cases stopped for clarification: {report['summary']['clarification_cases']}
- injected superseded evidence blocked: {not leak_guard['generation_allowed']}

The Router defaults unmarked policy questions to current mode. Historical questions
need one exact date. Latest-versus-immediately-previous comparisons can resolve from
the current revision boundary; generic past-versus-current comparisons and multiple
dates stop for clarification. The Generator entry guard is a request contract, not
an answer Generator, and rejects evidence outside the routed revision set.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"temporal_router_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed while freezing temporal Router: {name}")
    return {
        "cases_path": str(cases_path),
        "cases_sha256": cases_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "gates": gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build and audit the v3 account-policy temporal intent Router"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--bm25-index", type=Path, default=root / DEFAULT_BM25_INDEX)
    parser.add_argument("--overlay", type=Path, default=root / DEFAULT_OVERLAY)
    parser.add_argument(
        "--conflict-packet", type=Path, default=root / DEFAULT_CONFLICT_PACKET
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument(
        "--retriever-source", type=Path, default=root / DEFAULT_RETRIEVER_SOURCE
    )
    parser.add_argument(
        "--selector-source", type=Path, default=root / DEFAULT_SELECTOR_SOURCE
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
    result = freeze_temporal_router(
        root=args.root.resolve(),
        documents_path=args.documents.resolve(),
        chunks_path=args.chunks.resolve(),
        bm25_index_path=args.bm25_index.resolve(),
        overlay_path=args.overlay.resolve(),
        conflict_packet_path=args.conflict_packet.resolve(),
        builder_source_path=args.builder_source.resolve(),
        retriever_source_path=args.retriever_source.resolve(),
        selector_source_path=args.selector_source.resolve(),
        schema_source_path=args.schema_source.resolve(),
        contract_path=args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
