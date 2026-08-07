from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_retrieval import encode_queries
from src.v3.question_router import (
    DEFAULT_AS_OF,
    build_source_entity_index,
    restrict_runtime_artifacts,
    route_and_retrieve_with_embedding,
    search_policy_from_route,
)
from src.v3.retrieve_v3 import RuntimeArtifacts, load_runtime_artifacts, retrieve_with_embedding
from src.v3.select_evidence import select_evidence
from src.v3.temporal_policy import restrict_bm25_index


RETRIEVAL_SCHEMA_VERSION = "dnf_decomposed_retrieval_v3.1"
MERGE_SCHEMA_VERSION = "dnf_decomposed_evidence_merge_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_decomposed_retrieval_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_decomposed_retrieval_report_v3.1"
RETRIEVER_VERSION = "dnf-decomposed-hybrid-retriever-v3.1.0"
BUILT_AT = "2026-07-19T11:30:00+09:00"
TOP_K = 10

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
DEFAULT_DECOMPOSITION_CASES = Path(
    "data/v3/decomposition/"
    "question_decomposition_cases_"
    "fe4cba7df94c9ed78f847bb86a4e0afc611514773f26f76389c7d32ed192fef5.jsonl"
)
DEFAULT_DECOMPOSITION_MANIFEST = Path(
    "data/v3/decomposition/"
    "question_decomposition_manifest_"
    "208c644990956c2caeb787918b623abe89c1d79fcd7cfa6bfedb4daf51f12150.json"
)
DEFAULT_QUERY_EMBEDDINGS = Path(
    "data/v3/decomposition/"
    "decomposed_query_embeddings_"
    "b12bb4365b6a1678548d503dab60ecfc10a92081aadadc93662a200e80afa54b.f32"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/retrieve_decomposed.py")
DEFAULT_RUNTIME_SOURCE = Path("src/v3/retrieve_v3.py")
DEFAULT_ROUTER_SOURCE = Path("src/v3/question_router.py")
DEFAULT_DECOMPOSER_SOURCE = Path("src/v3/question_decomposer.py")
DEFAULT_SELECTOR_SOURCE = Path("src/v3/select_evidence.py")
DEFAULT_CONTRACT = Path("docs/v3/decomposed_hybrid_retrieval.md")

YEAR_MONTH_PATTERN = re.compile(r"(?P<year>20\d{2})년\s*(?P<month>\d{1,2})월")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else None


def infer_historical_month_window(
    question: str, time_scope: str
) -> tuple[str, str] | None:
    if time_scope != "historical":
        return None
    matches = list(YEAR_MONTH_PATTERN.finditer(question))
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError("Historical child must contain exactly one year-month")
    year = int(matches[0].group("year"))
    month = int(matches[0].group("month"))
    if not 1 <= month <= 12:
        raise RuntimeError(f"Invalid historical month: {month}")
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def document_overlaps_window(
    document: dict[str, Any], window: tuple[str, str]
) -> bool:
    valid_from = _iso_date(document.get("valid_from"))
    valid_to = _iso_date(document.get("valid_to"))
    if valid_from is None and valid_to is None:
        return False
    start, end = window
    return (valid_from is None or valid_from <= end) and (
        valid_to is None or valid_to >= start
    )


def _restrict_to_document_ids(
    artifacts: RuntimeArtifacts, allowed_document_ids: set[str]
) -> RuntimeArtifacts:
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


def _restrict_month_window(
    artifacts: RuntimeArtifacts,
    route: dict[str, Any],
    window: tuple[str, str],
) -> RuntimeArtifacts:
    source_restricted = restrict_runtime_artifacts(artifacts, route)
    allowed_document_ids = {
        document_id
        for document_id, document in source_restricted.documents_by_id.items()
        if document_overlaps_window(document, window)
    }
    if not allowed_document_ids:
        raise RuntimeError(f"No routed documents overlap historical window {window}")
    return _restrict_to_document_ids(source_restricted, allowed_document_ids)


def retrieve_decomposed_child(
    subquestion: dict[str, Any],
    query_embedding: np.ndarray,
    artifacts: RuntimeArtifacts,
    overlay_rows: list[dict[str, Any]],
    *,
    current_as_of: str = DEFAULT_AS_OF,
    top_k: int = TOP_K,
    source_entity_index: dict[str, list[frozenset[str]]] | None = None,
) -> dict[str, Any]:
    question = subquestion["question"]
    routed = route_and_retrieve_with_embedding(
        question,
        query_embedding,
        artifacts,
        overlay_rows,
        top_k=top_k,
        current_as_of=current_as_of,
        source_entity_index=source_entity_index,
    )
    route = routed["route"]
    if route["route_action"] != "retrieve":
        return {
            "subquestion": subquestion,
            "route": route,
            "temporal_resolution": routed["temporal_resolution"],
            "temporal_window": None,
            "hits": [],
            "selected_evidence": [],
        }
    temporal_window = infer_historical_month_window(question, route["time_scope"])
    hits = routed["hits"]
    if temporal_window is not None:
        restricted = _restrict_month_window(artifacts, route, temporal_window)
        hits = retrieve_with_embedding(
            question,
            query_embedding,
            restricted,
            top_k=top_k,
            policy=search_policy_from_route(route, current_as_of=current_as_of),
        )
        hits = [
            {
                **row,
                "question_time_scope": route["time_scope"],
                "temporal_window_start": temporal_window[0],
                "temporal_window_end": temporal_window[1],
            }
            for row in hits
        ]
    selected = select_evidence(question, hits, artifacts.chunks_by_id)
    return {
        "subquestion": subquestion,
        "route": route,
        "temporal_resolution": routed["temporal_resolution"],
        "temporal_window": list(temporal_window) if temporal_window else None,
        "hits": hits,
        "selected_evidence": selected,
    }


def _policy_violations(child: dict[str, Any]) -> list[str]:
    route = child["route"]
    subquestion_id = child["subquestion"]["subquestion_id"]
    allowed_sources = set(route["source_ids"])
    allowed_kinds = set(route["source_kinds"])
    violations = []
    for row in child["selected_evidence"]:
        prefix = f"{subquestion_id}:{row['chunk_id']}"
        if row["source_id"] not in allowed_sources:
            violations.append(f"{prefix}:source_id")
        if allowed_kinds and row["source_kind"] not in allowed_kinds:
            violations.append(f"{prefix}:source_kind")
        if row.get("review_required"):
            violations.append(f"{prefix}:review_required")
        if route["time_scope"] == "current":
            if row["status"] not in {"current", "upcoming"}:
                violations.append(f"{prefix}:current_status")
            if not row["default_exposure"]:
                violations.append(f"{prefix}:current_default_exposure")
    return violations


def merge_decomposed_evidence(
    parent_id: str,
    children: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered_children = sorted(
        children, key=lambda row: row["subquestion"]["ordinal"]
    )
    policy_violations = sorted(
        violation
        for child in ordered_children
        for violation in _policy_violations(child)
    )
    candidates: dict[str, dict[str, Any]] = {}
    for child in ordered_children:
        subquestion = child["subquestion"]
        time_scope = child["route"]["time_scope"]
        for row in child["selected_evidence"]:
            document_id = row["parent_document_id"]
            document = documents_by_id.get(document_id)
            if document is None:
                raise RuntimeError(f"Unknown selected evidence document: {document_id}")
            chunk_id = row["chunk_id"]
            attachment = {
                "subquestion_id": subquestion["subquestion_id"],
                "child_ordinal": subquestion["ordinal"],
                "time_scope": time_scope,
                "selected_rank": row["selected_rank"],
                "retrieval_rank": row["retrieval_rank"],
            }
            if chunk_id not in candidates:
                candidates[chunk_id] = {
                    "chunk_id": chunk_id,
                    "parent_document_id": document_id,
                    "lineage_id": document["lineage_id"],
                    "revision_id": document["revision_id"],
                    "source_id": row["source_id"],
                    "source_kind": row["source_kind"],
                    "status": row["status"],
                    "default_exposure": row["default_exposure"],
                    "valid_from": document.get("valid_from"),
                    "valid_to": document.get("valid_to"),
                    "display_text": row["display_text"],
                    "attachments": [],
                }
            existing = candidates[chunk_id]
            if existing["parent_document_id"] != document_id:
                raise RuntimeError(f"Chunk parent changed during merge: {chunk_id}")
            existing["attachments"].append(attachment)

    normalized = []
    for row in candidates.values():
        attachments = sorted(
            row["attachments"],
            key=lambda value: (
                value["child_ordinal"],
                value["selected_rank"],
                value["subquestion_id"],
            ),
        )
        normalized.append(
            {
                **row,
                "attachments": attachments,
                "subquestion_ids": sorted(
                    {value["subquestion_id"] for value in attachments}
                ),
                "child_ordinals": sorted(
                    {value["child_ordinal"] for value in attachments}
                ),
                "time_scopes": sorted(
                    {value["time_scope"] for value in attachments}
                ),
                "best_selected_rank": min(
                    value["selected_rank"] for value in attachments
                ),
            }
        )
    normalized.sort(
        key=lambda row: (
            min(row["child_ordinals"]),
            row["best_selected_rank"],
            row["chunk_id"],
        )
    )

    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        by_lineage.setdefault(row["lineage_id"], []).append(row)
    revision_conflicts = []
    temporal_revision_pairs = []
    for lineage_id, rows in sorted(by_lineage.items()):
        revisions = sorted({row["revision_id"] for row in rows})
        if len(revisions) <= 1:
            continue
        time_scopes = sorted(
            {scope for row in rows for scope in row["time_scopes"]}
        )
        detail = {
            "lineage_id": lineage_id,
            "revision_ids": revisions,
            "document_ids": sorted({row["parent_document_id"] for row in rows}),
            "time_scopes": time_scopes,
        }
        if "comparison" in time_scopes or {
            "current",
            "historical",
        }.issubset(time_scopes):
            temporal_revision_pairs.append(detail)
        else:
            revision_conflicts.append(detail)

    if policy_violations:
        merge_status = "blocked_policy_violation"
    elif revision_conflicts:
        merge_status = "blocked_revision_conflict"
    elif not normalized:
        merge_status = "blocked_empty_evidence"
    elif temporal_revision_pairs:
        merge_status = "explicit_temporal_separation"
    else:
        merge_status = "resolved_no_conflict"
    return {
        "merge_schema_version": MERGE_SCHEMA_VERSION,
        "parent_id": parent_id,
        "merge_status": merge_status,
        "policy_violations": policy_violations,
        "revision_conflicts": revision_conflicts,
        "temporal_revision_pairs": temporal_revision_pairs,
        "merged_candidates": []
        if merge_status.startswith("blocked_")
        else normalized,
    }


def _query_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case["case_id"],
            "subquestion": child["subquestion"],
        }
        for case in sorted(cases, key=lambda row: row["case_id"])
        for child in sorted(
            case["children"], key=lambda row: row["subquestion"]["ordinal"]
        )
    ]


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    decisions = report["decisions"]
    return "\n".join(
        [
            "# DNF RAG v3 decomposed hybrid retrieval pilot",
            "",
            "## 결과",
            "",
            f"- adaptive multi parents: {metrics['adaptive_multi_parents']}",
            f"- child questions: {metrics['children']}",
            f"- hybrid evidence groups@10: {metrics['hybrid_evidence_group_hits_at_10']}/{metrics['evidence_group_count']}",
            f"- selected evidence groups: {metrics['selected_evidence_group_hits']}/{metrics['evidence_group_count']}",
            f"- merged evidence groups: {metrics['merged_evidence_group_hits']}/{metrics['evidence_group_count']}",
            f"- policy violations: {metrics['policy_violations']}",
            f"- unresolved revision conflicts: {metrics['unresolved_revision_conflicts']}",
            f"- historical window leaks: {metrics['historical_window_leaks']}",
            "",
            "## 판정",
            "",
            *[f"- {name}: **{value}**" for name, value in decisions.items()],
            "",
            "이 결과는 adaptive development pilot이며 final blind 성능이 아니다.",
            "",
        ]
    )


def freeze_decomposed_hybrid(
    *,
    root: Path,
    documents_path: Path,
    chunks_path: Path,
    bm25_manifest_path: Path,
    dense_manifest_path: Path,
    overlay_path: Path,
    dev_set_path: Path,
    decomposition_cases_path: Path,
    decomposition_manifest_path: Path,
    builder_source_path: Path,
    runtime_source_path: Path,
    router_source_path: Path,
    decomposer_source_path: Path,
    selector_source_path: Path,
    contract_path: Path,
    query_embeddings: np.ndarray,
) -> dict[str, Any]:
    cases = read_jsonl(decomposition_cases_path)
    dev_rows = read_jsonl(dev_set_path)
    overlay_rows = read_jsonl(overlay_path)
    artifacts = load_runtime_artifacts(
        root,
        bm25_manifest_path=bm25_manifest_path,
        dense_manifest_path=dense_manifest_path,
        chunks_path=chunks_path,
        documents_path=documents_path,
    )
    query_rows = _query_rows(cases)
    embeddings = np.asarray(query_embeddings, dtype="<f4")
    if embeddings.shape != (
        len(query_rows),
        artifacts.dense_embeddings.shape[1],
    ):
        raise RuntimeError("Child query embeddings differ from decomposition order")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("Child query embeddings contain NaN or Inf")
    source_entity_index = build_source_entity_index(
        list(artifacts.documents_by_id.values()),
        list(artifacts.chunks_by_id.values()),
    )
    embedding_by_subquestion = {
        row["subquestion"]["subquestion_id"]: embeddings[ordinal]
        for ordinal, row in enumerate(query_rows)
    }
    dev_by_id = {row["dev_id"]: row for row in dev_rows}

    output_cases = []
    bm25_baseline_group_hits = 0
    hybrid_group_hits = 0
    selected_group_hits = 0
    merged_group_hits = 0
    evidence_group_count = 0
    empty_hybrid_children = 0
    empty_selected_children = 0
    source_hint_errors = 0
    child_group_specificity_errors = 0
    policy_violation_count = 0
    unresolved_revision_conflicts = 0
    historical_window_leaks = 0
    blocked_merges = 0
    for case in sorted(cases, key=lambda row: row["case_id"]):
        dev = dev_by_id[case["case_id"]]
        expected_groups = {group["group_id"] for group in dev["evidence_groups"]}
        bm25_baseline_group_hits += len(
            expected_groups & set(case["covered_evidence_group_ids"])
        )
        child_results = []
        hybrid_groups_by_child = []
        selected_groups_by_child = []
        for child_row in sorted(
            case["children"], key=lambda row: row["subquestion"]["ordinal"]
        ):
            subquestion = child_row["subquestion"]
            result = retrieve_decomposed_child(
                subquestion,
                embedding_by_subquestion[subquestion["subquestion_id"]],
                artifacts,
                overlay_rows,
                source_entity_index=source_entity_index,
            )
            empty_hybrid_children += not result["hits"]
            empty_selected_children += not result["selected_evidence"]
            source_hint_errors += (
                subquestion["source_hint"] not in result["route"]["source_ids"]
            )
            hit_ids = {row["chunk_id"] for row in result["hits"]}
            selected_ids = {
                row["chunk_id"] for row in result["selected_evidence"]
            }
            hybrid_groups = sorted(
                group["group_id"]
                for group in dev["evidence_groups"]
                if hit_ids.intersection(group["acceptable_chunk_ids"])
            )
            selected_groups = sorted(
                group["group_id"]
                for group in dev["evidence_groups"]
                if selected_ids.intersection(group["acceptable_chunk_ids"])
            )
            hybrid_groups_by_child.append(hybrid_groups)
            selected_groups_by_child.append(selected_groups)
            child_group_specificity_errors += len(hybrid_groups) != 1
            if result["temporal_window"] is not None:
                window = tuple(result["temporal_window"])
                historical_window_leaks += sum(
                    not document_overlaps_window(
                        artifacts.documents_by_id[row["parent_document_id"]], window
                    )
                    for row in result["hits"]
                )
            child_results.append(
                {
                    "subquestion": subquestion,
                    "route": result["route"],
                    "temporal_resolution": result["temporal_resolution"],
                    "temporal_window": result["temporal_window"],
                    "hybrid_hit_chunk_ids": [row["chunk_id"] for row in result["hits"]],
                    "selected_evidence": result["selected_evidence"],
                    "matched_hybrid_evidence_group_ids": hybrid_groups,
                    "matched_selected_evidence_group_ids": selected_groups,
                }
            )
        hybrid_covered = {
            group_id for groups in hybrid_groups_by_child for group_id in groups
        }
        selected_covered = {
            group_id for groups in selected_groups_by_child for group_id in groups
        }
        evidence_group_count += len(expected_groups)
        hybrid_group_hits += len(expected_groups & hybrid_covered)
        selected_group_hits += len(expected_groups & selected_covered)
        merged = merge_decomposed_evidence(
            case["case_id"], child_results, artifacts.documents_by_id
        )
        policy_violation_count += len(merged["policy_violations"])
        unresolved_revision_conflicts += len(merged["revision_conflicts"])
        blocked_merges += merged["merge_status"].startswith("blocked_")
        merged_ids = {row["chunk_id"] for row in merged["merged_candidates"]}
        merged_groups = sorted(
            group["group_id"]
            for group in dev["evidence_groups"]
            if merged_ids.intersection(group["acceptable_chunk_ids"])
        )
        merged_group_hits += len(set(merged_groups) & expected_groups)
        output_cases.append(
            {
                "retrieval_schema_version": RETRIEVAL_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "evaluation_role": "adaptive_dev_not_final_benchmark",
                "parent_question": case["parent_question"],
                "children": child_results,
                "merge": merged,
                "expected_evidence_group_ids": sorted(expected_groups),
                "hybrid_covered_evidence_group_ids": sorted(hybrid_covered),
                "selected_covered_evidence_group_ids": sorted(selected_covered),
                "merged_covered_evidence_group_ids": merged_groups,
            }
        )

    metrics = {
        "adaptive_multi_parents": len(output_cases),
        "children": len(query_rows),
        "evidence_group_count": evidence_group_count,
        "bm25_baseline_evidence_group_hits_at_10": bm25_baseline_group_hits,
        "hybrid_evidence_group_hits_at_10": hybrid_group_hits,
        "selected_evidence_group_hits": selected_group_hits,
        "merged_evidence_group_hits": merged_group_hits,
        "empty_hybrid_children": empty_hybrid_children,
        "empty_selected_children": empty_selected_children,
        "source_hint_errors": source_hint_errors,
        "child_group_specificity_errors": child_group_specificity_errors,
        "policy_violations": policy_violation_count,
        "unresolved_revision_conflicts": unresolved_revision_conflicts,
        "historical_window_leaks": historical_window_leaks,
        "blocked_merges": blocked_merges,
    }
    gates = {
        "adaptive_multi_parent_count_4": len(output_cases) == 4,
        "child_count_8": len(query_rows) == 8,
        "empty_hybrid_children_0": empty_hybrid_children == 0,
        "empty_selected_children_0": empty_selected_children == 0,
        "source_hint_errors_0": source_hint_errors == 0,
        "hybrid_evidence_group_hit_at_10_all": hybrid_group_hits
        == evidence_group_count,
        "hybrid_not_below_bm25_baseline": hybrid_group_hits
        >= bm25_baseline_group_hits,
        "selected_evidence_group_hit_all": selected_group_hits
        == evidence_group_count,
        "merged_evidence_group_hit_all": merged_group_hits
        == evidence_group_count,
        "each_child_matches_one_hybrid_group": child_group_specificity_errors == 0,
        "policy_violations_0": policy_violation_count == 0,
        "unresolved_revision_conflicts_0": unresolved_revision_conflicts == 0,
        "historical_window_leaks_0": historical_window_leaks == 0,
        "blocked_merges_0": blocked_merges == 0,
    }
    hybrid_go = all(
        gates[name]
        for name in (
            "adaptive_multi_parent_count_4",
            "child_count_8",
            "empty_hybrid_children_0",
            "source_hint_errors_0",
            "hybrid_evidence_group_hit_at_10_all",
            "hybrid_not_below_bm25_baseline",
            "each_child_matches_one_hybrid_group",
            "historical_window_leaks_0",
        )
    )
    merge_go = all(gates.values())
    decisions = {
        "child_hybrid_retrieval": "GO" if hybrid_go else "NO-GO",
        "child_source_time_filter": "GO"
        if gates["source_hint_errors_0"]
        and gates["policy_violations_0"]
        and gates["historical_window_leaks_0"]
        else "NO-GO",
        "evidence_merge_and_conflict_policy": "GO" if merge_go else "NO-GO",
        "free_form_generator_generation": "NO-GO",
        "final_benchmark": "NO-GO",
    }

    decomposition_dir = root / "data/v3/decomposition"
    reports_dir = root / "reports/v3"
    query_bytes = embeddings.astype("<f4", copy=False).tobytes(order="C")
    query_sha = _sha256_bytes(query_bytes)
    query_path = decomposition_dir / f"decomposed_query_embeddings_{query_sha}.f32"
    write_immutable(query_path, query_bytes)
    cases_bytes = _serialize_jsonl(output_cases, lambda row: row["case_id"])
    cases_sha = _sha256_bytes(cases_bytes)
    cases_path = decomposition_dir / f"decomposed_hybrid_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)

    input_paths = {
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_manifest": bm25_manifest_path,
        "dense_manifest": dense_manifest_path,
        "temporal_overlay": overlay_path,
        "adaptive_retrieval_dev": dev_set_path,
        "decomposition_cases": decomposition_cases_path,
        "decomposition_manifest": decomposition_manifest_path,
        "builder_source": builder_source_path,
        "runtime_source": runtime_source_path,
        "router_source": router_source_path,
        "decomposer_source": decomposer_source_path,
        "selector_source": selector_source_path,
        "contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "retriever_version": RETRIEVER_VERSION,
        "built_at": BUILT_AT,
        "top_k": TOP_K,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in input_paths.items()
        },
        "query_embeddings": {
            "path": _relative(root, query_path),
            "sha256": query_sha,
            "row_count": embeddings.shape[0],
            "dimension": embeddings.shape[1],
            "dtype": "little_endian_float32",
            "row_order": "case_id_then_child_ordinal",
            "model_name": artifacts.dense_model["model_name"],
            "model_revision": artifacts.dense_model["model_revision"],
            "normalized": True,
        },
        "cases": {
            "path": _relative(root, cases_path),
            "sha256": cases_sha,
            "row_count": len(output_cases),
        },
        "metrics": metrics,
        "gates": gates,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = decomposition_dir / f"decomposed_hybrid_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "retriever_version": RETRIEVER_VERSION,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "metrics": metrics,
        "gates": gates,
        "decisions": decisions,
        "artifacts": {
            "query_embeddings_path": _relative(root, query_path),
            "query_embeddings_sha256": query_sha,
            "cases_path": _relative(root, cases_path),
            "cases_sha256": cases_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "free_form_generation",
            "claim_level_verification",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"decomposed_hybrid_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"decomposed_hybrid_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "query_embeddings_path": str(query_path),
        "query_embeddings_sha256": query_sha,
        "cases_path": str(cases_path),
        "cases_sha256": cases_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "metrics": metrics,
        "gates": gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Run decomposed child hybrid retrieval and evidence merge pilot"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--query-embeddings", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--batch-size", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    cases_path = root / DEFAULT_DECOMPOSITION_CASES
    query_rows = _query_rows(read_jsonl(cases_path))
    artifacts = load_runtime_artifacts(root)
    if args.query_embeddings is None:
        embeddings, _ = encode_queries(
            [row["subquestion"]["question"] for row in query_rows],
            artifacts.dense_model,
            device=args.device,
            batch_size=args.batch_size,
        )
    else:
        path = args.query_embeddings.resolve()
        embeddings = np.fromfile(path, dtype="<f4")
        dimension = artifacts.dense_embeddings.shape[1]
        if embeddings.size != len(query_rows) * dimension:
            raise RuntimeError("Frozen child embedding byte length differs from row order")
        embeddings = embeddings.reshape(len(query_rows), dimension)
    result = freeze_decomposed_hybrid(
        root=root,
        documents_path=root / DEFAULT_DOCUMENTS,
        chunks_path=root / DEFAULT_CHUNKS,
        bm25_manifest_path=root / DEFAULT_BM25_MANIFEST,
        dense_manifest_path=root / DEFAULT_DENSE_MANIFEST,
        overlay_path=root / DEFAULT_OVERLAY,
        dev_set_path=root / DEFAULT_DEV_SET,
        decomposition_cases_path=cases_path,
        decomposition_manifest_path=root / DEFAULT_DECOMPOSITION_MANIFEST,
        builder_source_path=root / DEFAULT_BUILDER_SOURCE,
        runtime_source_path=root / DEFAULT_RUNTIME_SOURCE,
        router_source_path=root / DEFAULT_ROUTER_SOURCE,
        decomposer_source_path=root / DEFAULT_DECOMPOSER_SOURCE,
        selector_source_path=root / DEFAULT_SELECTOR_SOURCE,
        contract_path=root / DEFAULT_CONTRACT,
        query_embeddings=embeddings,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
