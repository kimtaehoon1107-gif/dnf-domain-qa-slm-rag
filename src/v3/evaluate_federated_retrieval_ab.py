from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import sentence_transformers
import torch
import transformers
from sentence_transformers import CrossEncoder

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_extractive_assembler import (
    DEFAULT_CANARY_BASELINE_CASES,
    DEFAULT_DEV_BASELINE_CASES,
    build_cases as build_assembler_cases,
)
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_requirement_retrieval_ab import (
    ASSEMBLER_K,
    ASSEMBLER_THRESHOLD,
    DEFAULT_ASSEMBLER_CASES,
    DEFAULT_ASSEMBLER_MANIFEST,
    DEFAULT_BACKBONE_CASES,
    DEFAULT_BACKBONE_MANIFEST,
    DEFAULT_FALSE_FULL_CASES,
    DEFAULT_FALSE_FULL_MANIFEST,
    DEFAULT_RERANK_MANIFEST,
    DEFAULT_RERANK_RESULTS,
    DEFAULT_RERANK_SCORES,
    _cross_parent_metrics,
    _model_snapshot_fingerprint,
    _percentile,
    _policy_from_dict,
    _ratio,
    _selection_metrics,
    build_requirement_segments,
    run_segment_reranker,
    summarize_arm,
)
from src.v3.evaluate_router_backbone_ab import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
    DEFAULT_TAXONOMY,
    _answerability_target,
    _score_arm,
    simulate_arm,
)
from src.v3.retrieve_v3 import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DOCUMENTS,
    RuntimeArtifacts,
    load_runtime_artifacts,
    retrieve_with_embedding,
)
from src.v3.score_evidence_reranker import (
    BATCH_SIZE,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
)
from src.v3.temporal_policy import resolve_policy_revisions
from src.v3.temporal_router import DEFAULT_OVERLAY, route_temporal_query


EVALUATOR_VERSION = "federated-retrieval-ab-v3.1.0"
RETRIEVAL_SCHEMA_VERSION = "federated-retrieval-ab-candidates-v3.1"
CASE_SCHEMA_VERSION = "federated-retrieval-ab-case-v3.1"
REPORT_SCHEMA_VERSION = "federated-retrieval-ab-report-v3.1"
MANIFEST_SCHEMA_VERSION = "federated-retrieval-ab-manifest-v3.1"

ARM_QUOTA = "federated_quota"
ARM_GLOBAL = "federated_global"
FEDERATED_ARMS = (ARM_QUOTA, ARM_GLOBAL)
GLOBAL_TOP_K = 10
SOURCE_QUOTA = 3
SOURCE_DEPTH = 20
PARENT_CHUNK_CAP = 2
RRF_K = 60

DEFAULT_PRIOR_CANDIDATES = Path(
    "data/v3/retrieval/requirement_retrieval_ab_candidates_"
    "e4415535221f405f807de7776a76e163364db4c7821b58b6bac34a0dc50c04f9.jsonl"
)
DEFAULT_PRIOR_MANIFEST = Path(
    "data/v3/retrieval/requirement_retrieval_ab_manifest_"
    "40fc2122cb462f97ac930f201e817e7784c4c17a5be07485e2b244d926597788.json"
)
DEFAULT_QUERY_EMBEDDINGS = Path(
    "data/v3/retrieval/requirement_retrieval_query_embeddings_"
    "b3aa1d0062caa9b82ab432200a5928f7a1e65a76fb728e7ce3f549c21cd7e02f.f32"
)
DEFAULT_CONTRACT = Path("docs/v3/federated_retrieval_ab.md")

FAILURE_BUCKETS = (
    "ENUM_MISS",
    "SOURCE_SCOPE_MISS",
    "RETRIEVAL_MISS",
    "ATTRIBUTE_MISMATCH",
    "ASSEMBLY_MISS",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _policy_dict(policy: SearchPolicy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "default_exposure_only": policy.default_exposure_only,
        "allowed_statuses": list(policy.allowed_statuses)
        if policy.allowed_statuses is not None
        else None,
        "include_review_required": policy.include_review_required,
        "as_of": policy.as_of,
        "source_ids": list(policy.source_ids) if policy.source_ids else None,
    }


def federated_policy_from_frozen(value: dict[str, Any] | None) -> SearchPolicy | None:
    """Remove only the hard source choice and keep the frozen temporal mode."""
    if value is None:
        return None
    statuses = tuple(value["allowed_statuses"]) if value["allowed_statuses"] else None
    if value["default_exposure_only"]:
        statuses = ("current", "active")
    return SearchPolicy(
        default_exposure_only=value["default_exposure_only"],
        allowed_statuses=statuses,
        include_review_required=False,
        as_of=value["as_of"],
        source_ids=None,
    )


def _with_source(policy: SearchPolicy, source_id: str) -> SearchPolicy:
    return SearchPolicy(
        default_exposure_only=policy.default_exposure_only,
        allowed_statuses=policy.allowed_statuses,
        include_review_required=policy.include_review_required,
        as_of=policy.as_of,
        source_ids=(source_id,),
    )


def _iso_day(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:10] if len(value) >= 10 else None


def policy_allows_chunk(chunk: dict[str, Any], policy: SearchPolicy) -> bool:
    if policy.default_exposure_only and not chunk["default_exposure"]:
        return False
    if policy.allowed_statuses is not None and chunk["status"] not in policy.allowed_statuses:
        return False
    if not policy.include_review_required and chunk["review_required"]:
        return False
    if policy.source_ids is not None and chunk["source_id"] not in policy.source_ids:
        return False
    if policy.as_of is not None:
        as_of = _iso_day(policy.as_of)
        valid_from = _iso_day(chunk.get("valid_from"))
        valid_to = _iso_day(chunk.get("valid_to"))
        if as_of is None:
            raise RuntimeError(f"Invalid as_of date: {policy.as_of}")
        if valid_from is not None and valid_from > as_of:
            return False
        if valid_to is not None and valid_to < as_of:
            return False
    return True


def account_policy_parent_guard(
    *,
    question: str,
    frozen_source_ids: list[str],
    overlay_rows: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    if "dnf_account_policy" not in frozen_source_ids:
        resolution = resolve_policy_revisions(overlay_rows, mode="current")
        return list(resolution["allowed_document_ids"]), {
            "mode": "current",
            "needs_clarification": False,
            "source": "current-only guard outside frozen policy route",
        }
    route = route_temporal_query(question, overlay_rows)
    if route["needs_clarification"]:
        return [], {**route, "source": "existing temporal router"}
    resolution = resolve_policy_revisions(
        overlay_rows, mode=route["mode"], as_of=route["as_of"]
    )
    return list(resolution["allowed_document_ids"]), {
        **route,
        "source": "existing temporal router",
    }


def build_federated_requests(
    prior_rows: list[dict[str, Any]],
    assembler_cases: list[dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cases = {row["case_id"]: row for row in assembler_cases}
    output = []
    for prior in prior_rows:
        case = cases[prior["case_id"]]
        frozen_policy = prior["policy"]
        frozen_sources = list((frozen_policy or {}).get("source_ids") or [])
        policy = federated_policy_from_frozen(frozen_policy)
        allowed_policy_parents, policy_route = account_policy_parent_guard(
            question=case["question"],
            frozen_source_ids=frozen_sources,
            overlay_rows=overlay_rows,
        )
        output.append(
            {
                "case_id": prior["case_id"],
                "dataset": prior["dataset"],
                "requirement_index": prior["requirement_index"],
                "requirement_id": prior["requirement_id"],
                "query": prior["query"],
                "search_enabled": prior["search_enabled"] and policy is not None,
                "federated_policy": _policy_dict(policy),
                "frozen_source_ids_removed": frozen_sources,
                "allowed_account_policy_document_ids": sorted(allowed_policy_parents),
                "account_policy_temporal_route": policy_route,
                "gold_ids_available_to_query_policy_or_hygiene": False,
            }
        )
    return sorted(output, key=lambda row: (row["case_id"], row["requirement_index"]))


def apply_candidate_hygiene(
    hits: list[dict[str, Any]],
    artifacts: RuntimeArtifacts,
    *,
    allowed_account_policy_document_ids: set[str],
    max_parent_chunks: int = PARENT_CHUNK_CAP,
    max_total: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output = []
    content_hash_parents: dict[str, str] = {}
    parent_counts: Counter[str] = Counter()
    counters: Counter[str] = Counter()
    for hit in hits:
        parent_id = hit["parent_document_id"]
        document = artifacts.documents_by_id[parent_id]
        if (
            hit["source_id"] == "dnf_account_policy"
            and parent_id not in allowed_account_policy_document_ids
        ):
            counters["policy_revision_filtered"] += 1
            continue
        content_hash = document["content_hash"]
        prior_parent = content_hash_parents.get(content_hash)
        if prior_parent is not None and prior_parent != parent_id:
            counters["content_hash_deduplicated"] += 1
            continue
        if parent_counts[parent_id] >= max_parent_chunks:
            counters["parent_cap_filtered"] += 1
            continue
        content_hash_parents.setdefault(content_hash, parent_id)
        parent_counts[parent_id] += 1
        output.append({**hit, "document_content_hash": content_hash})
        if max_total is not None and len(output) >= max_total:
            break
    return output, dict(sorted(counters.items()))


def rrf_fuse_source_hits(
    source_hits: dict[str, list[dict[str, Any]]], *, rrf_k: int = RRF_K
) -> list[dict[str, Any]]:
    fused = []
    for source_id, hits in sorted(source_hits.items()):
        for source_rank, hit in enumerate(hits, 1):
            fused.append(
                {
                    **hit,
                    "federated_source_rank": source_rank,
                    "federated_rrf_score": round(1.0 / (rrf_k + source_rank), 10),
                    "federated_source_id": source_id,
                }
            )
    return sorted(
        fused,
        key=lambda row: (
            -row["federated_rrf_score"],
            row["federated_source_id"],
            row["chunk_id"],
        ),
    )


def _hit_record(hit: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "chunk_id": hit["chunk_id"],
        "parent_document_id": hit["parent_document_id"],
        "source_id": hit["source_id"],
        "source_kind": hit["source_kind"],
        "status": hit["status"],
        "default_exposure": hit["default_exposure"],
        "valid_from": hit["valid_from"],
        "valid_to": hit["valid_to"],
        "base_hybrid_rank": hit["base_hybrid_rank"],
        "base_hybrid_score": hit["base_hybrid_score"],
        "guardrail_injected": hit["guardrail_injected"],
        "document_content_hash": hit["document_content_hash"],
        "federated_source_rank": hit.get("federated_source_rank"),
        "federated_rrf_score": hit.get("federated_rrf_score"),
    }


def execute_federated_retrieval(
    requests: list[dict[str, Any]],
    embeddings: np.ndarray,
    artifacts: RuntimeArtifacts,
    source_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if embeddings.shape[0] != len(requests):
        raise RuntimeError("Frozen requirement embedding count differs from requests")
    output = []
    timings: dict[str, list[float]] = {arm: [] for arm in FEDERATED_ARMS}
    by_case: dict[str, dict[str, float]] = {arm: {} for arm in FEDERATED_ARMS}
    call_counts: Counter[str] = Counter()
    for request, embedding in zip(requests, embeddings, strict=True):
        variants: dict[str, Any] = {}
        if not request["search_enabled"]:
            for arm in FEDERATED_ARMS:
                variants[arm] = {"hits": [], "elapsed_ms": 0.0, "hygiene": {}}
        else:
            policy = _policy_from_dict(request["federated_policy"])
            if policy is None:
                raise RuntimeError("Enabled federated request has no policy")
            allowed_policy_parents = set(
                request["allowed_account_policy_document_ids"]
            )

            started = time.perf_counter()
            raw_global = retrieve_with_embedding(
                request["query"],
                embedding,
                artifacts,
                top_k=SOURCE_DEPTH,
                policy=policy,
            )
            global_hits, global_hygiene = apply_candidate_hygiene(
                raw_global,
                artifacts,
                allowed_account_policy_document_ids=allowed_policy_parents,
                max_total=GLOBAL_TOP_K,
            )
            global_ms = (time.perf_counter() - started) * 1000
            call_counts[ARM_GLOBAL] += 1
            timings[ARM_GLOBAL].append(global_ms)
            by_case[ARM_GLOBAL][request["case_id"]] = (
                by_case[ARM_GLOBAL].get(request["case_id"], 0.0) + global_ms
            )
            variants[ARM_GLOBAL] = {
                "hits": [_hit_record(hit, rank) for rank, hit in enumerate(global_hits, 1)],
                "elapsed_ms": round(global_ms, 3),
                "hygiene": global_hygiene,
            }

            started = time.perf_counter()
            per_source: dict[str, list[dict[str, Any]]] = {}
            quota_counters: Counter[str] = Counter()
            for source_id in source_ids:
                raw = retrieve_with_embedding(
                    request["query"],
                    embedding,
                    artifacts,
                    top_k=SOURCE_DEPTH,
                    policy=_with_source(policy, source_id),
                )
                call_counts[ARM_QUOTA] += 1
                hygienic, counters = apply_candidate_hygiene(
                    raw,
                    artifacts,
                    allowed_account_policy_document_ids=allowed_policy_parents,
                    max_total=SOURCE_QUOTA,
                )
                quota_counters.update(counters)
                per_source[source_id] = hygienic
            rrf_hits = rrf_fuse_source_hits(per_source)
            quota_hits, final_counters = apply_candidate_hygiene(
                rrf_hits,
                artifacts,
                allowed_account_policy_document_ids=allowed_policy_parents,
                max_total=None,
            )
            quota_counters.update(final_counters)
            quota_ms = (time.perf_counter() - started) * 1000
            timings[ARM_QUOTA].append(quota_ms)
            by_case[ARM_QUOTA][request["case_id"]] = (
                by_case[ARM_QUOTA].get(request["case_id"], 0.0) + quota_ms
            )
            variants[ARM_QUOTA] = {
                "hits": [_hit_record(hit, rank) for rank, hit in enumerate(quota_hits, 1)],
                "elapsed_ms": round(quota_ms, 3),
                "hygiene": dict(sorted(quota_counters.items())),
                "source_hit_counts": {
                    source_id: len(hits) for source_id, hits in sorted(per_source.items())
                },
            }
        output.append(
            {
                "candidate_schema_version": RETRIEVAL_SCHEMA_VERSION,
                **request,
                "variants": variants,
            }
        )
    latency = {}
    for arm in FEDERATED_ARMS:
        values = timings[arm]
        question_values = list(by_case[arm].values())
        latency[arm] = {
            "search_call_count": call_counts[arm],
            "requirement_count": len(values),
            "requirement_median_ms": round(statistics.median(values), 3)
            if values
            else None,
            "requirement_p95_ms": _percentile(values, 0.95),
            "question_sum_median_ms": round(statistics.median(question_values), 3)
            if question_values
            else None,
            "question_sum_p95_ms": _percentile(question_values, 0.95),
            "total_search_ms": round(sum(values), 3),
        }
    return output, latency


def build_federated_arm_cases(
    assembler_cases: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    arm: str,
) -> list[dict[str, Any]]:
    if arm not in FEDERATED_ARMS:
        raise RuntimeError(f"Unknown federated arm: {arm}")
    retrieval = {
        (row["case_id"], int(row["requirement_index"])): row
        for row in retrieval_rows
    }
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    output = []
    for source in assembler_cases:
        pools = []
        selected_ids: list[str] = []
        seen: set[str] = set()
        for index, requirement in enumerate(source["requirements"], 1):
            hit_ids = [
                hit["chunk_id"]
                for hit in retrieval[(source["case_id"], index)]["variants"][arm]["hits"]
            ]
            pools.append(
                {
                    "requirement_index": index,
                    "requirement_id": requirement["requirement_id"],
                    "candidate_chunk_ids": hit_ids,
                }
            )
            for chunk_id in hit_ids:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    selected_ids.append(chunk_id)
        output.append(
            {
                **source,
                "retrieval_arm": arm,
                "selected_chunk_ids": selected_ids,
                "selected_chunks": {
                    chunk_id: chunks_by_id[chunk_id]["display_text"]
                    for chunk_id in selected_ids
                },
                "requirement_candidate_pools": pools,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def build_scored_cases(
    *,
    ground_truth_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    attribution_rows: list[dict[str, Any]],
    frozen_backbone_rows: list[dict[str, Any]],
    frozen_assembler_rows: list[dict[str, Any]],
    arm_assembler_rows: dict[str, list[dict[str, Any]]],
    arm_cases: dict[str, list[dict[str, Any]]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    attributions = {row["case_id"]: row for row in attribution_rows}
    frozen_backbone = {row["case_id"]: row for row in frozen_backbone_rows}
    frozen_assembler = {row["case_id"]: row for row in frozen_assembler_rows}
    assemblers = {
        arm: {row["case_id"]: row for row in rows}
        for arm, rows in arm_assembler_rows.items()
    }
    cases = {
        arm: {row["case_id"]: row for row in rows} for arm, rows in arm_cases.items()
    }
    chunk_to_parent = {row["chunk_id"]: row["parent_document_id"] for row in chunks}
    output = []
    for truth in ground_truth_rows:
        case_id = truth["case_id"]
        target = _answerability_target(truth, attributions.get(case_id))
        row = {
            "case_schema_version": CASE_SCHEMA_VERSION,
            "case_id": case_id,
            "dataset": truth["dataset"],
            "answerability_target": target,
            "arm_a": frozen_backbone[case_id]["arm0"],
            "gold_ids_used_for_scoring_only": True,
            "gold_ids_available_to_retrieval_reranker_or_assembler": False,
            "question_or_gold_text_included": False,
        }
        for arm in FEDERATED_ARMS:
            decisions = assemblers[arm][case_id]["decisions"]
            simulated = simulate_arm(
                placement="arm0",
                question=evaluations[case_id]["question"],
                assembler_decisions=decisions,
                classifier_predictions=[],
                chunk_to_parent=chunk_to_parent,
            )
            score = _score_arm(
                simulated,
                target=target,
                evidence_groups=evaluations[case_id]["evidence_groups"],
                expected_docs_flags=[True] * len(decisions),
                baseline_supported_indices=set(),
            )
            candidate_ids = sorted(
                {
                    chunk_id
                    for pool in cases[arm][case_id]["requirement_candidate_pools"]
                    for chunk_id in pool["candidate_chunk_ids"]
                }
            )
            row[arm] = {**simulated, "score": score, "candidate_chunk_ids": candidate_ids}
        row["frozen_assembler_supported_requirement_count"] = sum(
            decision["status"] == "supported_exact"
            for decision in frozen_assembler[case_id]["decisions"]
        )
        output.append(row)
    return sorted(output, key=lambda row: (row["dataset"], row["case_id"]))


def retrieval_bound_metrics(
    case_rows: list[dict[str, Any]],
    false_full_rows: list[dict[str, Any]],
    arm: str,
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in case_rows}
    targets = [
        row
        for row in false_full_rows
        if row["classification"] in {"B_RETRIEVAL_MISS", "D_CROSS_PARENT_MISS"}
    ]
    question_hits = group_hits = grounded = 0
    group_total = 0
    details = []
    for audit in targets:
        case = cases[audit["case_id"]]
        candidates = set(case[arm].get("candidate_chunk_ids", []))
        groups = []
        for group in audit["gold_evidence"]:
            acceptable = {row["chunk_id"] for row in group["acceptable"]}
            hit = bool(candidates & acceptable)
            group_hits += hit
            group_total += 1
            groups.append({"group_id": group["group_id"], "candidate_present": hit})
        all_present = bool(groups) and all(row["candidate_present"] for row in groups)
        is_grounded = case[arm]["score"]["grounded_answer"]
        question_hits += all_present
        grounded += is_grounded
        details.append(
            {
                "case_id": audit["case_id"],
                "classification": audit["classification"],
                "all_gold_groups_candidate_present": all_present,
                "grounded_after_assembly": is_grounded,
                "cross_parent_candidate": case[arm]["cross_parent_candidate"],
                "groups": groups,
            }
        )
    return {
        "question_candidate_recovery": _ratio(question_hits, len(targets)),
        "evidence_group_candidate_recovery": _ratio(group_hits, group_total),
        "false_full_to_grounded_recovery": _ratio(grounded, len(targets)),
        "details": details,
    }


def temporal_safety_metrics(
    retrieval_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    requests = {
        (row["case_id"], row["requirement_id"]): row
        for row in retrieval_rows
    }
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    violations = []
    allowed_noncurrent = 0
    for assembled in assembler_rows:
        case_id = assembled["case_id"]
        for decision in assembled["decisions"]:
            if decision["status"] != "supported_exact":
                continue
            requirement_id = decision["requirement_id"]
            request = requests[(case_id, requirement_id)]
            index = int(request["requirement_index"])
            policy = _policy_from_dict(request["federated_policy"])
            if policy is None:
                violations.append(
                    {"case_id": case_id, "requirement_index": index, "reason": "no_policy"}
                )
                continue
            allowed_policy = set(request["allowed_account_policy_document_ids"])
            for span in decision["spans"]:
                chunk = chunks_by_id[span["chunk_id"]]
                reason = None
                if not policy_allows_chunk(chunk, policy):
                    reason = "outside_temporal_search_policy"
                elif (
                    chunk["source_id"] == "dnf_account_policy"
                    and chunk["parent_document_id"] not in allowed_policy
                ):
                    reason = "outside_resolved_policy_revision"
                elif policy.default_exposure_only and (
                    chunk["status"] != "current" or not chunk["default_exposure"]
                ):
                    reason = "current_mode_noncurrent_or_nondefault"
                if reason is not None:
                    violations.append(
                        {
                            "case_id": case_id,
                            "requirement_index": index,
                            "chunk_id": chunk["chunk_id"],
                            "source_id": chunk["source_id"],
                            "status": chunk["status"],
                            "reason": reason,
                        }
                    )
                elif chunk["status"] != "current" or not chunk["default_exposure"]:
                    allowed_noncurrent += 1
    return {
        "arm": arm,
        "violation_count": len(violations),
        "violations": violations,
        "contextually_allowed_noncurrent_citation_count": allowed_noncurrent,
    }


def classify_failure(
    *,
    requirements: list[dict[str, Any]],
    evidence_groups: list[dict[str, Any]],
    candidate_ids: set[str],
    cited_ids: set[str],
    eligible_ids: set[str],
    chunks_by_id: dict[str, dict[str, Any]],
) -> str | None:
    if not requirements:
        return "ENUM_MISS"
    group_sets = [set(group["acceptable_chunk_ids"]) for group in evidence_groups]
    if any(not (group & eligible_ids) for group in group_sets):
        return "SOURCE_SCOPE_MISS"
    if any(not (group & candidate_ids) for group in group_sets):
        return "RETRIEVAL_MISS"
    if all(group & cited_ids for group in group_sets):
        return None
    acceptable_parents = {
        chunks_by_id[chunk_id]["parent_document_id"]
        for group in group_sets
        for chunk_id in group
        if chunk_id in chunks_by_id
    }
    cited_parents = {
        chunks_by_id[chunk_id]["parent_document_id"]
        for chunk_id in cited_ids
        if chunk_id in chunks_by_id
    }
    return "ATTRIBUTE_MISMATCH" if acceptable_parents & cited_parents else "ASSEMBLY_MISS"


def failure_taxonomy(
    *,
    case_rows: list[dict[str, Any]],
    assembler_cases: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    false_full_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    arm: str,
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in case_rows}
    assembler = {row["case_id"]: row for row in assembler_cases}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    requests_by_case: dict[str, list[dict[str, Any]]] = {}
    for row in retrieval_rows:
        requests_by_case.setdefault(row["case_id"], []).append(row)
    target_ids = {
        row["case_id"]
        for row in false_full_rows
        if row["classification"] in {"B_RETRIEVAL_MISS", "D_CROSS_PARENT_MISS"}
    }
    baseline_false = {
        row["case_id"] for row in case_rows if row["arm_a"]["score"]["false_full_answer"]
    }
    new_false = {
        row["case_id"]
        for row in case_rows
        if row[arm]["score"]["false_full_answer"]
        and row["case_id"] not in baseline_false
    }
    details = []
    counts: Counter[str] = Counter()
    for case_id in sorted(target_ids | new_false):
        case = cases[case_id]
        evaluation = evaluations[case_id]
        candidate_ids = set(case[arm]["candidate_chunk_ids"])
        cited_ids = set(case[arm]["cited_chunk_ids"])
        eligible_ids: set[str] = set()
        for request in requests_by_case[case_id]:
            policy = _policy_from_dict(request["federated_policy"])
            if policy is None:
                continue
            allowed_policy = set(request["allowed_account_policy_document_ids"])
            for group in evaluation["evidence_groups"]:
                for chunk_id in group["acceptable_chunk_ids"]:
                    chunk = chunks_by_id.get(chunk_id)
                    if chunk is None or not policy_allows_chunk(chunk, policy):
                        continue
                    if (
                        chunk["source_id"] == "dnf_account_policy"
                        and chunk["parent_document_id"] not in allowed_policy
                    ):
                        continue
                    eligible_ids.add(chunk_id)
        bucket = classify_failure(
            requirements=assembler[case_id]["requirements"],
            evidence_groups=evaluation["evidence_groups"],
            candidate_ids=candidate_ids,
            cited_ids=cited_ids,
            eligible_ids=eligible_ids,
            chunks_by_id=chunks_by_id,
        )
        recovered = bucket is None and case[arm]["score"]["grounded_answer"]
        label = "RECOVERED" if recovered else bucket or "ASSEMBLY_MISS"
        if label in FAILURE_BUCKETS:
            counts[label] += 1
        details.append(
            {
                "case_id": case_id,
                "scope": "retrieval_bound_target" if case_id in target_ids else "new_false_full",
                "bucket": label,
                "candidate_count": len(candidate_ids),
                "cited_count": len(cited_ids),
                "eligible_gold_chunk_count": len(eligible_ids),
                "grounded": case[arm]["score"]["grounded_answer"],
            }
        )
    return {
        "arm": arm,
        "failure_counts": {bucket: counts[bucket] for bucket in FAILURE_BUCKETS},
        "recovered_count": sum(row["bucket"] == "RECOVERED" for row in details),
        "details": details,
    }


def evaluate_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_selection: dict[str, Any],
    candidate_selection: dict[str, Any],
    retrieval: dict[str, Any],
    cross_parent: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "retrieval_bound_grounded_recovery_at_least_1": retrieval[
            "false_full_to_grounded_recovery"
        ]["successes"]
        >= 1,
        "grounded_at_least_73": candidate["answerable"]["grounded_answer"]["successes"]
        >= 73,
        "grounded_not_reduced": candidate["answerable"]["grounded_answer"]["successes"]
        >= baseline["answerable"]["grounded_answer"]["successes"],
        "new_false_full_zero": candidate["answerable"]["new_false_full_case_count"] == 0,
        "temporal_safety_violations_zero": safety["violation_count"] == 0,
        "exact_span_validity_100_percent": candidate_selection["span_validity"]["invalid"]
        == 0,
        "mean_spans_not_increased": candidate_selection[
            "mean_spans_per_supported_requirement"
        ]
        <= baseline_selection["mean_spans_per_supported_requirement"],
        "nonacceptable_citations_not_increased": candidate_selection[
            "question_level_nonacceptable_unique_citation_count"
        ]
        <= baseline_selection["question_level_nonacceptable_unique_citation_count"],
        "same_parent_7_of_7": cross_parent["same_parent_not_decomposed"]["successes"] == 7,
        "reject_11_of_11": candidate["reject"]["correct_abstain_or_reject"]["successes"]
        == 11,
        "realtime_safe_abstain_2_of_2": candidate["realtime"]["safe_abstain"]["successes"]
        == 2,
        "realtime_static_exposure_zero": candidate["realtime"]["static_exposure"]["successes"]
        == 0,
    }
    return {"checks": checks, "pass": all(checks.values())}


def _markdown(report: dict[str, Any]) -> bytes:
    lines = [
        "# Federated retrieval A/B",
        "",
        f"Decision: **{report['decision']}**",
        "",
        f"Integrated index confirmed: **{report['index_audit']['integrated_index']}** "
        f"({report['index_audit']['chunk_count']} chunks, "
        f"{report['index_audit']['source_count']} sources)",
        "",
        "| Arm | pool recovery | grounded recovery | grounded | false-full | new false-full | exact | safety leaks | same-parent | reject | realtime | gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm in ("arm_a", *FEDERATED_ARMS):
        metrics = report["arms"][arm]
        retrieval = report["retrieval_bound"][arm]
        cross = report["cross_parent"][arm]
        selection = report["selection"][arm]
        safety = report["safety"].get(arm, {"violation_count": 0})
        gate = report["gates"].get(arm)
        lines.append(
            "| {} | {}/7 | {}/7 | {}/82 | {}/82 | {} | {} | {} | {}/7 | {}/11 | {}/2 | {} |".format(
                arm,
                retrieval["question_candidate_recovery"]["successes"],
                retrieval["false_full_to_grounded_recovery"]["successes"],
                metrics["answerable"]["grounded_answer"]["successes"],
                metrics["answerable"]["false_full_answer"]["successes"],
                metrics["answerable"]["new_false_full_case_count"],
                selection["span_validity"]["rate"],
                safety["violation_count"],
                cross["same_parent_not_decomposed"]["successes"],
                metrics["reject"]["correct_abstain_or_reject"]["successes"],
                metrics["realtime"]["safe_abstain"]["successes"],
                "baseline" if gate is None else ("PASS" if gate["pass"] else "FAIL"),
            )
        )
    lines.extend(["", "## Failure taxonomy", ""])
    for arm in FEDERATED_ARMS:
        taxonomy = report["failure_taxonomy"][arm]
        values = ", ".join(
            f"{name}={taxonomy['failure_counts'][name]}" for name in FAILURE_BUCKETS
        )
        lines.append(f"- {arm}: RECOVERED={taxonomy['recovered_count']}; {values}")
    lines.extend(["", "## Cost", ""])
    for arm in FEDERATED_ARMS:
        search = report["cost"]["retrieval"][arm]
        reranker = report["cost"]["reranker"][arm]
        lines.append(
            f"- {arm}: searches={search['search_call_count']}, "
            f"question median/p95={search['question_sum_median_ms']}/{search['question_sum_p95_ms']} ms, "
            f"reranker pairs={reranker['pair_count']}, "
            f"reranker question median/p95={reranker['question_sum_median_ms']}/{reranker['question_sum_p95_ms']} ms"
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Hard source filtering was disabled only in the two development arms.",
            "- Frozen planner output, indexes, bge segment reranker, assembler threshold/K, gold, labels, and questions were unchanged.",
            "- No reindex, training, soft-router arm, sealed canary, frozen blind access, or runtime promotion occurred.",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    device: str,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "attribution": root / DEFAULT_ATTRIBUTION,
        "taxonomy": root / DEFAULT_TAXONOMY,
        "enumeration": root / DEFAULT_ENUMERATION,
        "reranker_results": root / DEFAULT_RERANK_RESULTS,
        "reranker_scores": root / DEFAULT_RERANK_SCORES,
        "reranker_manifest": root / DEFAULT_RERANK_MANIFEST,
        "frozen_assembler_cases": root / DEFAULT_ASSEMBLER_CASES,
        "frozen_assembler_manifest": root / DEFAULT_ASSEMBLER_MANIFEST,
        "frozen_backbone_cases": root / DEFAULT_BACKBONE_CASES,
        "frozen_backbone_manifest": root / DEFAULT_BACKBONE_MANIFEST,
        "false_full_cases": root / DEFAULT_FALSE_FULL_CASES,
        "false_full_manifest": root / DEFAULT_FALSE_FULL_MANIFEST,
        "chunks": root / DEFAULT_CHUNKS,
        "documents": root / DEFAULT_DOCUMENTS,
        "bm25_manifest": root / DEFAULT_BM25_MANIFEST,
        "dense_manifest": root / DEFAULT_DENSE_MANIFEST,
        "dev_baseline_cases": root / DEFAULT_DEV_BASELINE_CASES,
        "canary_baseline_cases": root / DEFAULT_CANARY_BASELINE_CASES,
        "prior_candidates": root / DEFAULT_PRIOR_CANDIDATES,
        "prior_manifest": root / DEFAULT_PRIOR_MANIFEST,
        "query_embeddings": root / DEFAULT_QUERY_EMBEDDINGS,
        "temporal_overlay": root / DEFAULT_OVERLAY,
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": root / "src/v3/evaluate_federated_retrieval_ab.py",
        "retriever_source": root / "src/v3/retrieve_v3.py",
        "temporal_router_source": root / "src/v3/temporal_router.py",
        "assembler_source": root / "src/v3/evaluate_extractive_assembler_v3_chunk_diverse.py",
    }
    before = {name: file_sha256(path) for name, path in input_paths.items()}
    prior_manifest = json.loads(input_paths["prior_manifest"].read_text(encoding="utf-8"))
    if prior_manifest["artifacts"]["retrieval_candidates"]["sha256"] != before[
        "prior_candidates"
    ]:
        raise RuntimeError("Prior requirement retrieval candidates lineage mismatch")
    if prior_manifest["artifacts"]["query_embeddings"]["sha256"] != before[
        "query_embeddings"
    ]:
        raise RuntimeError("Frozen requirement embeddings lineage mismatch")

    ground_truth = read_jsonl(input_paths["ground_truth"])
    dev_rows = read_jsonl(input_paths["adaptive_dev"])
    canary_rows = read_jsonl(input_paths["downgraded_canary"])
    evaluation_rows = dev_rows + canary_rows
    chunks = read_jsonl(input_paths["chunks"])
    assembler_cases = build_assembler_cases(
        canary_rows,
        dev_rows,
        read_jsonl(input_paths["enumeration"]),
        read_jsonl(input_paths["reranker_results"]),
        read_jsonl(input_paths["reranker_scores"]),
        read_jsonl(input_paths["canary_baseline_cases"]),
        read_jsonl(input_paths["dev_baseline_cases"]),
        chunks,
    )
    prior_rows = read_jsonl(input_paths["prior_candidates"])
    requests = build_federated_requests(
        prior_rows,
        assembler_cases,
        read_jsonl(input_paths["temporal_overlay"]),
    )
    embedding_meta = prior_manifest["artifacts"]["query_embeddings"]
    embeddings = np.fromfile(input_paths["query_embeddings"], dtype="<f4")
    embeddings = embeddings.reshape(
        int(embedding_meta["row_count"]), int(embedding_meta["dimension"])
    )
    artifacts = load_runtime_artifacts(root)
    source_ids = sorted({row["source_id"] for row in chunks})
    index_audit = {
        "integrated_index": (
            len(artifacts.dense_metadata) == len(chunks)
            == artifacts.bm25_index["document_count"]
            and len(source_ids) > 1
        ),
        "chunk_count": len(chunks),
        "dense_row_count": len(artifacts.dense_metadata),
        "bm25_row_count": artifacts.bm25_index["document_count"],
        "source_count": len(source_ids),
        "source_ids": source_ids,
        "reindex": False,
    }
    if not index_audit["integrated_index"]:
        raise RuntimeError("Federated A/B requires the frozen integrated index")

    retrieval_rows, retrieval_latency = execute_federated_retrieval(
        requests, embeddings, artifacts, source_ids
    )
    arm_cases = {
        arm: build_federated_arm_cases(
            assembler_cases, retrieval_rows, chunks, arm=arm
        )
        for arm in FEDERATED_ARMS
    }
    segment_rows = {
        arm: build_requirement_segments(cases) for arm, cases in arm_cases.items()
    }
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    load_started = time.perf_counter()
    model = CrossEncoder(
        MODEL_NAME,
        revision=MODEL_REVISION,
        max_length=MAX_LENGTH,
        device=device,
        local_files_only=True,
    )
    model_load_ms = (time.perf_counter() - load_started) * 1000
    score_rows: dict[str, list[dict[str, Any]]] = {}
    reranker_latency = {}
    assembled = {}
    for arm in FEDERATED_ARMS:
        score_rows[arm], reranker_latency[arm] = run_segment_reranker(
            arm_cases[arm], segment_rows[arm], model, arm=arm, device=device
        )
        assembled[arm] = assemble_chunk_diverse_configuration(
            arm_cases[arm],
            score_rows[arm],
            threshold=ASSEMBLER_THRESHOLD,
            k=ASSEMBLER_K,
        )

    frozen_assembler_rows = read_jsonl(input_paths["frozen_assembler_cases"])
    case_rows = build_scored_cases(
        ground_truth_rows=ground_truth,
        evaluation_rows=evaluation_rows,
        attribution_rows=read_jsonl(input_paths["attribution"]),
        frozen_backbone_rows=read_jsonl(input_paths["frozen_backbone_cases"]),
        frozen_assembler_rows=frozen_assembler_rows,
        arm_assembler_rows=assembled,
        arm_cases=arm_cases,
        chunks=chunks,
    )
    baseline_false = {
        row["case_id"] for row in case_rows if row["arm_a"]["score"]["false_full_answer"]
    }
    arms = {
        "arm_a": summarize_arm(case_rows, "arm_a", baseline_false_full_ids=baseline_false),
        **{
            arm: summarize_arm(case_rows, arm, baseline_false_full_ids=baseline_false)
            for arm in FEDERATED_ARMS
        },
    }
    baseline_grounded = set(arms["arm_a"]["grounded_case_ids"])
    for arm in FEDERATED_ARMS:
        arms[arm]["answerable"]["baseline_grounded_regression_count"] = len(
            baseline_grounded - set(arms[arm]["grounded_case_ids"])
        )
    taxonomy_rows = read_jsonl(input_paths["taxonomy"])
    cross_parent = {
        arm: _cross_parent_metrics(case_rows, taxonomy_rows, arm)
        for arm in ("arm_a", *FEDERATED_ARMS)
    }
    false_full_rows = read_jsonl(input_paths["false_full_cases"])
    retrieval_bound = {
        arm: retrieval_bound_metrics(case_rows, false_full_rows, arm)
        for arm in ("arm_a", *FEDERATED_ARMS)
    }
    selection = {
        "arm_a": _selection_metrics(
            evaluation_rows, ground_truth, frozen_assembler_rows, chunks
        ),
        **{
            arm: _selection_metrics(evaluation_rows, ground_truth, assembled[arm], chunks)
            for arm in FEDERATED_ARMS
        },
    }
    safety = {
        arm: temporal_safety_metrics(
            retrieval_rows, assembled[arm], chunks, arm=arm
        )
        for arm in FEDERATED_ARMS
    }
    failure = {
        arm: failure_taxonomy(
            case_rows=case_rows,
            assembler_cases=assembler_cases,
            retrieval_rows=retrieval_rows,
            evaluation_rows=evaluation_rows,
            false_full_rows=false_full_rows,
            chunks=chunks,
            arm=arm,
        )
        for arm in FEDERATED_ARMS
    }
    gates = {
        arm: evaluate_gate(
            arms["arm_a"],
            arms[arm],
            selection["arm_a"],
            selection[arm],
            retrieval_bound[arm],
            cross_parent[arm],
            safety[arm],
        )
        for arm in FEDERATED_ARMS
    }
    passing = [arm for arm in FEDERATED_ARMS if gates[arm]["pass"]]
    if not passing:
        decision = "NO_GO_FEDERATED_RETRIEVAL"
    else:
        passing.sort(
            key=lambda arm: (
                -retrieval_bound[arm]["false_full_to_grounded_recovery"]["successes"],
                reranker_latency[arm]["pair_count"],
                arm,
            )
        )
        decision = f"ADOPT_RECOMMENDATION_{passing[0].upper()}_DEV_ONLY"

    evaluated_at = evaluated_at or datetime.now(timezone.utc).isoformat()
    model_meta = {
        "name": MODEL_NAME,
        "revision": MODEL_REVISION,
        "max_length": MAX_LENGTH,
        "batch_size": BATCH_SIZE,
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "model_load_ms": round(model_load_ms, 3),
        "libraries": {
            "sentence_transformers": sentence_transformers.__version__,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "numpy": np.__version__,
        },
        **_model_snapshot_fingerprint(),
    }
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluation_role": "development_only_federated_recall_first_ab",
        "evaluated_at": evaluated_at,
        "source_commit": _git_head(root),
        "decision": decision,
        "index_audit": index_audit,
        "arms": arms,
        "retrieval_bound": retrieval_bound,
        "cross_parent": cross_parent,
        "selection": selection,
        "safety": safety,
        "failure_taxonomy": failure,
        "gates": gates,
        "configuration": {
            "arm_a": "frozen hard-route backbone and assembler",
            ARM_QUOTA: "per-source top-3 after hygiene, rank-only RRF, no hard source filter",
            ARM_GLOBAL: "integrated all-source hygienic global top-10, no hard source filter",
            "query": "frozen planner subject + relation",
            "query_embeddings_reused": True,
            "source_quota": SOURCE_QUOTA,
            "global_top_k": GLOBAL_TOP_K,
            "source_depth": SOURCE_DEPTH,
            "parent_chunk_cap": PARENT_CHUNK_CAP,
            "rrf_k": RRF_K,
            "assembler_threshold": ASSEMBLER_THRESHOLD,
            "assembler_k_distinct_chunks": ASSEMBLER_K,
            "gold_available_before_scoring": False,
        },
        "cost": {
            "query_embedding": {
                "reused_path": _relative(root, input_paths["query_embeddings"]),
                "row_count": embeddings.shape[0],
                "dimension": embeddings.shape[1],
                "new_encoding_calls": 0,
            },
            "retrieval": retrieval_latency,
            "reranker": reranker_latency,
        },
        "model": model_meta,
        "retrieval_provenance": artifacts.provenance,
        "scope": {
            "canonical_or_runtime_promotion": False,
            "sealed_canary_run": False,
            "training": False,
            "reindex": False,
            "planner_reexecuted": False,
            "planner_changed": False,
            "assembler_selection_logic_changed": False,
            "assembler_threshold_or_k_changed": False,
            "soft_router_arm_executed": False,
            "frozen_blind_accessed": False,
            "gold_label_question_changed": False,
        },
        "input_hashes": before,
    }

    retrieval_dir = root / "data/v3/retrieval"
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"

    def freeze_jsonl(
        directory: Path, prefix: str, rows: list[dict[str, Any]], key: Any
    ) -> tuple[Path, str]:
        payload = _serialize_jsonl(rows, key)
        sha = _sha256_bytes(payload)
        path = directory / f"{prefix}_{sha}.jsonl"
        write_immutable(path, payload)
        return path, sha

    retrieval_path, retrieval_sha = freeze_jsonl(
        retrieval_dir,
        "federated_retrieval_ab_candidates",
        retrieval_rows,
        lambda row: (row["case_id"], row["requirement_index"]),
    )
    combined_scores = [row for arm in FEDERATED_ARMS for row in score_rows[arm]]
    scores_path, scores_sha = freeze_jsonl(
        evidence_dir,
        "federated_retrieval_ab_segment_scores",
        combined_scores,
        lambda row: (row["retrieval_arm"], row["case_id"]),
    )
    cases_path, cases_sha = freeze_jsonl(
        evidence_dir,
        "federated_retrieval_ab_cases",
        case_rows,
        lambda row: (row["dataset"], row["case_id"]),
    )
    report["artifacts"] = {
        "retrieval_candidates": {
            "path": _relative(root, retrieval_path),
            "sha256": retrieval_sha,
            "row_count": len(retrieval_rows),
        },
        "segment_scores": {
            "path": _relative(root, scores_path),
            "sha256": scores_sha,
            "row_count": len(combined_scores),
        },
        "cases": {
            "path": _relative(root, cases_path),
            "sha256": cases_sha,
            "row_count": len(case_rows),
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"federated_retrieval_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"federated_retrieval_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at,
        "source_commit": report["source_commit"],
        "decision": decision,
        "inputs": {
            name: {"path": _relative(root, input_paths[name]), "sha256": sha}
            for name, sha in before.items()
        },
        "artifacts": {
            **report["artifacts"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "configuration": report["configuration"],
        "index_audit": index_audit,
        "model": {key: value for key, value in model_meta.items() if key != "model_load_ms"},
        "scope": report["scope"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = retrieval_dir / f"federated_retrieval_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    after = {name: file_sha256(path) for name, path in input_paths.items()}
    changed = sorted(name for name in before if before[name] != after[name])
    if changed:
        raise RuntimeError(f"Inputs changed during federated retrieval A/B: {changed}")
    return {
        "decision": decision,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "markdown_path": str(markdown_path),
        "markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "artifacts": report["artifacts"],
        "gates": gates,
        "lineage_hashes_unchanged": not changed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the development-only all-source federated retrieval A/B"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(
        json.dumps(
            evaluate_and_freeze(
                args.root, device=args.device, evaluated_at=args.evaluated_at
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
