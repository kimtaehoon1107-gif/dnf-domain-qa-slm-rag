from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import tokenize_lexical
from src.v3.build_corpus import file_sha256
from src.v3.claim_aware_reranker import CLAIM_RERANKER_VERSION, rerank_evidence
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.evaluate_claim_reranker import _single_response
from src.v3.evaluate_retrieval import encode_queries
from src.v3.generate_verified_answer import build_answer_plan, verify_answer_plan
from src.v3.question_decomposer import apply_parent_source_hints, decompose_question
from src.v3.question_router import build_source_entity_index, route_and_retrieve_with_embedding
from src.v3.retrieve_decomposed import merge_decomposed_evidence, retrieve_decomposed_child
from src.v3.retrieve_v3 import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DOCUMENTS,
    load_runtime_artifacts,
)
from src.v3.run_unified_runtime import (
    PARTIAL_DISCLAIMER,
    _multi_response,
    build_abstention_response,
)
from src.v3.select_evidence import select_evidence
from src.v3.temporal_policy import resolve_policy_revisions


EVALUATOR_VERSION = "authored-canary-evaluator-v3.1.0"
CASE_SCHEMA_VERSION = "authored-canary-case-v3.1"
MANIFEST_SCHEMA_VERSION = "authored-canary-evaluation-manifest-v3.1"
REPORT_SCHEMA_VERSION = "authored-canary-evaluation-report-v3.1"
TOP_K = 10
CLAIM_COMPLETENESS_TOKEN_RECALL = 0.50

DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CANARY_MANIFEST = Path(
    "data/v3/evaluation/authored_canary_final_manifest_"
    "7460bac96b781dbc55340ed0c3381b8796c36ba63c3e001c8fd1572916b1fce0.json"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/early_generalization_canary.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def wilson_interval(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return [round(max(0.0, center - margin), 8), round(min(1.0, center + margin), 8)]


def _rate(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "wilson_95_percent": wilson_interval(successes, total),
    }


def _matched_groups(dev: dict[str, Any], chunk_ids: set[str]) -> set[str]:
    return {
        group["group_id"]
        for group in dev["evidence_groups"]
        if chunk_ids.intersection(group["acceptable_chunk_ids"])
    }


def _response_claims(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("claims") is not None:
        return response["claims"]
    plan = response.get("answer_plan")
    return [] if plan is None else plan["claims"]


def _gold_span_token_recall(claim_text: str, evidence_span: str) -> float:
    gold = set(tokenize_lexical(evidence_span))
    if not gold:
        return 0.0
    return len(gold.intersection(tokenize_lexical(claim_text))) / len(gold)


def _group_rows(
    dev: dict[str, Any],
    retrieval_ids: set[str],
    selected_ids: set[str],
    baseline_response: dict[str, Any],
    canonical_response: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_ids = set(baseline_response["citation_chunk_ids"])
    canonical_ids = set(canonical_response["citation_chunk_ids"])
    canonical_claims = _response_claims(canonical_response)
    output = []
    for group in dev["evidence_groups"]:
        acceptable = set(group["acceptable_chunk_ids"])
        matching_claims = [
            claim
            for claim in canonical_claims
            if claim["citation_chunk_id"] in acceptable
        ]
        best_recall = max(
            (
                _gold_span_token_recall(claim["claim_text"], group["evidence_span"])
                for claim in matching_claims
            ),
            default=0.0,
        )
        output.append(
            {
                "group_id": group["group_id"],
                "retrieval_hit": bool(acceptable.intersection(retrieval_ids)),
                "selected_hit": bool(acceptable.intersection(selected_ids)),
                "baseline_cited_hit": bool(acceptable.intersection(baseline_ids)),
                "canonical_cited_hit": bool(acceptable.intersection(canonical_ids)),
                "canonical_claim_token_recall": round(best_recall, 8),
                "claim_complete": best_recall >= CLAIM_COMPLETENESS_TOKEN_RECALL,
            }
        )
    return output


def _expected_time_scope_matches(expected: str, actual: str | None) -> bool:
    if expected == "mixed":
        return actual in {"mixed", "comparison"}
    return expected == actual


def _temporal_revision_violations(
    dev: dict[str, Any],
    route: dict[str, Any] | None,
    evidence_ids: set[str],
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
) -> list[str]:
    violations = []
    actual_scope = None if route is None else route.get("time_scope")
    if not _expected_time_scope_matches(dev["time_scope"], actual_scope):
        violations.append("route_time_scope")
    documents = {
        documents_by_id[chunks_by_id[chunk_id]["parent_document_id"]]["document_id"]:
        documents_by_id[chunks_by_id[chunk_id]["parent_document_id"]]
        for chunk_id in evidence_ids
        if chunk_id in chunks_by_id
    }
    if dev["time_scope"] == "current":
        for document in documents.values():
            if document["status"] not in {"current", "upcoming"}:
                violations.append(f"{document['document_id']}:current_status")
            if not document["default_exposure"]:
                violations.append(f"{document['document_id']}:current_exposure")
    elif dev["time_scope"] in {"historical", "preview"}:
        expected_statuses = set(dev["target_statuses"])
        for document in documents.values():
            if expected_statuses and document["status"] not in expected_statuses:
                violations.append(f"{document['document_id']}:target_status")
            if dev["time_scope"] == "preview" and document["source_kind"] != "preview_patch":
                violations.append(f"{document['document_id']}:preview_kind")
    policy_documents = {
        document_id
        for document_id, document in documents.items()
        if document["source_id"] == "dnf_account_policy"
    }
    if policy_documents:
        mode = (
            "comparison"
            if dev["time_scope"] == "mixed"
            else dev["time_scope"]
        )
        if mode in {"current", "historical", "comparison"}:
            try:
                resolution = resolve_policy_revisions(
                    overlay_rows, mode=mode, as_of=dev["as_of"]
                )
                allowed = set(resolution["allowed_document_ids"])
                for document_id in policy_documents - allowed:
                    violations.append(f"{document_id}:policy_revision")
            except RuntimeError:
                violations.append("policy_revision_resolution")
    return sorted(set(violations))


def aggregate_canary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = [row for row in rows if row["group_results"]]
    groups = [group for row in required for group in row["group_results"]]
    retrieval_complete = sum(
        all(group["retrieval_hit"] for group in row["group_results"])
        for row in required
    )
    selected_hits = sum(group["selected_hit"] for group in groups)
    cited_hits = sum(group["canonical_cited_hit"] for group in groups)
    claim_complete = sum(
        all(group["claim_complete"] for group in row["group_results"])
        for row in required
    )
    strict_improvements = sum(
        group["canonical_cited_hit"] and not group["baseline_cited_hit"]
        for group in groups
    )
    strict_regressions = sum(
        group["baseline_cited_hit"] and not group["canonical_cited_hit"]
        for group in groups
    )
    source_metrics = {}
    for source_id in sorted({source for row in rows for source in row["source_ids"]}):
        subset = [
            row for row in required if source_id in row["source_ids"]
        ]
        successes = sum(
            all(group["retrieval_hit"] for group in row["group_results"])
            for row in subset
        )
        source_metrics[source_id] = _rate(successes, len(subset))
    minimum_source_rate = min(
        (entry["rate"] for entry in source_metrics.values()), default=0.0
    )
    zero_hit_sources = sorted(
        source_id
        for source_id, entry in source_metrics.items()
        if entry["successes"] == 0
    )
    temporal_violations = sum(
        len(row["temporal_revision_violations"]) for row in rows
    )
    exposure_count = sum(row["false_realtime_evidence_exposure"] for row in rows)
    partial_rows = [row for row in rows if row["answerability"] == "partial"]
    partial_hits = sum(row["partial_disclaimer"] for row in partial_rows)
    failure_count = sum(
        not (
            (not row["group_results"] or all(g["claim_complete"] for g in row["group_results"]))
            and not row["temporal_revision_violations"]
            and not row["false_realtime_evidence_exposure"]
            and (row["answerability"] != "partial" or row["partial_disclaimer"])
        )
        for row in rows
    )
    metrics = {
        "rows": len(rows),
        "required_evidence_rows": len(required),
        "expected_evidence_groups": len(groups),
        "retrieval_all_required_evidence_recall": _rate(
            retrieval_complete, len(required)
        ),
        "selected_evidence_group_hit": _rate(selected_hits, len(groups)),
        "cited_evidence_group_hit": _rate(cited_hits, len(groups)),
        "claim_completeness": _rate(claim_complete, len(required)),
        "strict_improvement_count": strict_improvements,
        "strict_regression_count": strict_regressions,
        "source_retrieval_all_required": source_metrics,
        "minimum_source_retrieval_rate": minimum_source_rate,
        "zero_hit_sources": zero_hit_sources,
        "temporal_revision_violation_count": temporal_violations,
        "false_realtime_evidence_exposure_count": exposure_count,
        "partial_disclaimer": _rate(partial_hits, len(partial_rows)),
        "route_action_exact": _rate(
            sum(row["route_action_exact"] for row in rows), len(rows)
        ),
        "failed_case_count": failure_count,
    }
    gates = {
        "retrieval_all_required_at_least_0_90": metrics[
            "retrieval_all_required_evidence_recall"
        ]["rate"] >= 0.90,
        "selected_evidence_group_hit_at_least_0_85": metrics[
            "selected_evidence_group_hit"
        ]["rate"] >= 0.85,
        "cited_evidence_group_hit_at_least_0_85": metrics[
            "cited_evidence_group_hit"
        ]["rate"] >= 0.85,
        "claim_completeness_at_least_0_90": metrics["claim_completeness"][
            "rate"
        ] >= 0.90,
        "strict_regression_zero": strict_regressions == 0,
        "strict_improvement_at_least_one": strict_improvements >= 1,
        "minimum_source_retrieval_at_least_0_66": minimum_source_rate >= 0.66,
        "zero_hit_source_none": not zero_hit_sources,
        "temporal_revision_violation_zero": temporal_violations == 0,
        "false_realtime_evidence_exposure_zero": exposure_count == 0,
        "partial_disclaimer_5_of_5": partial_hits == len(partial_rows) == 5,
    }
    return {"metrics": metrics, "gates": gates, "go": all(gates.values())}


def _load_embeddings(path: Path, rows: int, dimension: int) -> np.ndarray:
    values = np.fromfile(path, dtype="<f4")
    if values.size != rows * dimension:
        raise RuntimeError(f"Embedding byte length is invalid: {path}")
    return values.reshape(rows, dimension)


def _fail_closed(status: str) -> dict[str, Any]:
    return {
        "runtime_status": status,
        "response_type": "fail_closed",
        "rendered_answer": "",
        "citation_chunk_ids": [],
        "claims": [],
        "answer_plan": None,
        "verification": None,
    }


def _single_baseline_response(
    runtime: dict[str, Any],
    routed: dict[str, Any],
    selected: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    route = routed["route"]
    payload = f"{runtime['dev_id']}\n{runtime['question']}".encode("utf-8")
    child = {
        "subquestion": {
            "subquestion_id": f"subquestion_sha256_{hashlib.sha256(payload).hexdigest()}",
            "ordinal": 1,
            "question": runtime["question"],
            "relationship": "single_fact",
            "time_hint": route["time_scope"],
            "source_hint": route["source_ids"][0]
            if len(route["source_ids"]) == 1
            else None,
        },
        "route": route,
        "temporal_resolution": routed.get("temporal_resolution"),
        "temporal_window": None,
        "hits": routed.get("hits", []),
        "selected_evidence": selected,
    }
    retrieval_case = {
        "case_id": runtime["dev_id"],
        "parent_question": runtime["question"],
        "children": [child],
        "merge": merge_decomposed_evidence(
            runtime["dev_id"], [child], documents_by_id
        ),
    }
    if retrieval_case["merge"]["merge_status"].startswith("blocked_"):
        return _fail_closed("blocked_no_verified_evidence")
    plan = build_answer_plan(retrieval_case, documents_by_id)
    verification = verify_answer_plan(plan, retrieval_case, documents_by_id)
    if not verification["verified"]:
        return _fail_closed("blocked_verification_failed")
    rendered = plan["rendered_answer"]
    if route["answerability"] == "partial":
        rendered = PARTIAL_DISCLAIMER + rendered
    return {
        "runtime_status": "success",
        "response_type": "partial_official_fact"
        if route["answerability"] == "partial"
        else "verified_extractive_answer",
        "rendered_answer": rendered,
        "citation_chunk_ids": [
            claim["citation_chunk_id"] for claim in plan["claims"]
        ],
        "claims": None,
        "answer_plan": plan,
        "verification": verification,
    }


def _freeze_embedding(
    root: Path, prefix: str, embeddings: np.ndarray
) -> tuple[Path, str]:
    payload = np.asarray(embeddings, dtype="<f4").tobytes(order="C")
    sha = _sha256_bytes(payload)
    path = root / "data/v3/evaluation" / f"{prefix}_{sha}.f32"
    write_immutable(path, payload)
    return path, sha


def evaluate_and_freeze(
    *,
    root: Path,
    canary_path: Path = DEFAULT_CANARY,
    canary_manifest_path: Path = DEFAULT_CANARY_MANIFEST,
    documents_path: Path = DEFAULT_DOCUMENTS,
    chunks_path: Path = DEFAULT_CHUNKS,
    bm25_manifest_path: Path = DEFAULT_BM25_MANIFEST,
    dense_manifest_path: Path = DEFAULT_DENSE_MANIFEST,
    overlay_path: Path = DEFAULT_OVERLAY,
    contract_path: Path = DEFAULT_CONTRACT,
    device: str | None = None,
    batch_size: int = 8,
    full_query_embeddings_path: Path | None = None,
    child_query_embeddings_path: Path | None = None,
    reranker_scores_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    canary_path = resolve(canary_path)
    canary_manifest_path = resolve(canary_manifest_path)
    documents_path = resolve(documents_path)
    chunks_path = resolve(chunks_path)
    bm25_manifest_path = resolve(bm25_manifest_path)
    dense_manifest_path = resolve(dense_manifest_path)
    overlay_path = resolve(overlay_path)
    contract_path = resolve(contract_path)
    optional_inputs = {
        "frozen_full_query_embeddings": full_query_embeddings_path,
        "frozen_child_query_embeddings": child_query_embeddings_path,
        "frozen_reranker_scores": reranker_scores_path,
    }
    input_paths = {
        "sealed_canary": canary_path,
        "sealed_canary_manifest": canary_manifest_path,
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_manifest": bm25_manifest_path,
        "dense_manifest": dense_manifest_path,
        "temporal_overlay": overlay_path,
        "contract": contract_path,
        "question_router_source": root / "src/v3/question_router.py",
        "retriever_source": root / "src/v3/retrieve_v3.py",
        "selector_source": root / "src/v3/select_evidence.py",
        "decomposer_source": root / "src/v3/question_decomposer.py",
        "decomposed_retriever_source": root / "src/v3/retrieve_decomposed.py",
        "generator_verifier_source": root / "src/v3/generate_verified_answer.py",
        "claim_reranker_source": root / "src/v3/claim_aware_reranker.py",
        "reranker_scorer_source": root / "src/v3/score_evidence_reranker.py",
        "evaluator_source": root / "src/v3/evaluate_authored_canary.py",
    }
    for name, path in optional_inputs.items():
        if path is not None:
            input_paths[name] = resolve(path)
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    canary_manifest = json.loads(canary_manifest_path.read_text(encoding="utf-8"))
    dataset_entry = canary_manifest["evaluation_dataset"]
    if dataset_entry is None or dataset_entry["sha256"] != file_sha256(canary_path):
        raise RuntimeError("Sealed canary and final manifest do not match")

    dev_rows = sorted(read_jsonl(canary_path), key=lambda row: row["query_ordinal"])
    if [row["query_ordinal"] for row in dev_rows] != list(range(32)):
        raise RuntimeError("Canary query ordinals must be exactly 0..31")
    overlay_rows = read_jsonl(overlay_path)
    artifacts = load_runtime_artifacts(
        root,
        bm25_manifest_path=bm25_manifest_path,
        dense_manifest_path=dense_manifest_path,
        chunks_path=chunks_path,
        documents_path=documents_path,
    )
    dimension = artifacts.dense_embeddings.shape[1]
    if full_query_embeddings_path is None:
        full_embeddings, query_model = encode_queries(
            [row["question"] for row in dev_rows],
            artifacts.dense_model,
            device=device,
            batch_size=batch_size,
        )
    else:
        full_embeddings = _load_embeddings(
            resolve(full_query_embeddings_path), len(dev_rows), dimension
        )
        query_model = {**artifacts.dense_model, "device": "frozen_override"}
    full_embedding_path, full_embedding_sha = _freeze_embedding(
        root, "authored_canary_full_query_embeddings", full_embeddings
    )
    source_entity_index = build_source_entity_index(
        list(artifacts.documents_by_id.values()),
        list(artifacts.chunks_by_id.values()),
    )

    runtime_rows = [
        {"dev_id": row["dev_id"], "question": row["question"], "as_of": row["as_of"]}
        for row in dev_rows
    ]
    executions = []
    child_specs = []
    for runtime_row, embedding in zip(runtime_rows, full_embeddings, strict=True):
        try:
            routed = route_and_retrieve_with_embedding(
                runtime_row["question"],
                embedding,
                artifacts,
                overlay_rows,
                top_k=TOP_K,
                current_as_of=runtime_row["as_of"],
                source_entity_index=source_entity_index,
            )
            execution = {
                "runtime": runtime_row,
                "routed": routed,
                "selected": [],
                "decomposition": None,
                "children": [],
                "execution_error": None,
            }
            action = routed["route"]["route_action"]
            if action == "retrieve":
                execution["selected"] = select_evidence(
                    runtime_row["question"], routed["hits"], artifacts.chunks_by_id
                )
            elif action == "decompose":
                decomposition = decompose_question(
                    runtime_row["dev_id"],
                    runtime_row["question"],
                    as_of=runtime_row["as_of"],
                )
                decomposition = apply_parent_source_hints(
                    decomposition,
                    routed["route"],
                    artifacts.bm25_index,
                    as_of=runtime_row["as_of"],
                )
                execution["decomposition"] = decomposition
                for child in decomposition["subquestions"]:
                    child_specs.append((len(executions), child))
        except RuntimeError as exc:
            execution = {
                "runtime": runtime_row,
                "routed": None,
                "selected": [],
                "decomposition": None,
                "children": [],
                "execution_error": f"{type(exc).__name__}:{exc}",
            }
        executions.append(execution)

    child_questions = [child["question"] for _, child in child_specs]
    if child_questions:
        if child_query_embeddings_path is None:
            child_embeddings, child_query_model = encode_queries(
                child_questions,
                artifacts.dense_model,
                device=device,
                batch_size=batch_size,
            )
        else:
            child_embeddings = _load_embeddings(
                resolve(child_query_embeddings_path), len(child_questions), dimension
            )
            child_query_model = {**artifacts.dense_model, "device": "frozen_override"}
    else:
        child_embeddings = np.empty((0, dimension), dtype="<f4")
        child_query_model = {**artifacts.dense_model, "device": "not_used"}
    child_embedding_path, child_embedding_sha = _freeze_embedding(
        root, "authored_canary_child_query_embeddings", child_embeddings
    )
    for (execution_index, child), embedding in zip(
        child_specs, child_embeddings, strict=True
    ):
        execution = executions[execution_index]
        try:
            result = retrieve_decomposed_child(
                child,
                embedding,
                artifacts,
                overlay_rows,
                current_as_of=execution["runtime"]["as_of"],
                top_k=TOP_K,
                source_entity_index=source_entity_index,
            )
            execution["children"].append(result)
        except RuntimeError as exc:
            execution["execution_error"] = f"{type(exc).__name__}:{exc}"

    score_rows = []
    score_pairs = []
    score_keys = []
    for dev, execution in zip(dev_rows, executions, strict=True):
        candidates = []
        for candidate in execution["selected"]:
            pair_ordinal = len(score_pairs)
            candidates.append(
                {
                    "selected_rank": candidate["selected_rank"],
                    "chunk_id": candidate["chunk_id"],
                    "pair_ordinal": pair_ordinal,
                }
            )
            score_pairs.append((dev["question"], candidate["display_text"]))
            score_keys.append((dev["dev_id"], candidate["chunk_id"]))
        score_rows.append(
            {
                "dev_id": dev["dev_id"],
                "query_ordinal": dev["query_ordinal"],
                "candidates": candidates,
            }
        )
    if reranker_scores_path is None:
        if score_pairs:
            try:
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            from src.v3.score_evidence_reranker import (
                BATCH_SIZE as RERANKER_BATCH_SIZE,
                MAX_LENGTH as RERANKER_MAX_LENGTH,
                MODEL_NAME as RERANKER_MODEL_NAME,
                MODEL_REVISION as RERANKER_MODEL_REVISION,
                run_model,
            )

            raw_scores, latency = run_model(
                score_pairs, device=device or query_model["device"]
            )
            scores = [round(float(value), 8) for value in raw_scores]
            reranker_model = {
                "name": RERANKER_MODEL_NAME,
                "revision": RERANKER_MODEL_REVISION,
                "max_length": RERANKER_MAX_LENGTH,
                "batch_size": RERANKER_BATCH_SIZE,
                "device": latency["device"],
                "pair_count": len(scores),
            }
        else:
            scores = []
            reranker_model = {"device": "not_used", "pair_count": 0}
    else:
        frozen_score_rows = read_jsonl(resolve(reranker_scores_path))
        frozen = {
            (row["dev_id"], candidate["chunk_id"]): candidate["reranker_score"]
            for row in frozen_score_rows
            for candidate in row["candidates"]
        }
        if set(score_keys) != set(frozen):
            raise RuntimeError("Frozen reranker score keys differ from runtime candidates")
        scores = [float(frozen[key]) for key in score_keys]
        reranker_model = {"device": "frozen_override", "pair_count": len(scores)}
    for row in score_rows:
        for candidate in row["candidates"]:
            candidate["reranker_score"] = scores[candidate.pop("pair_ordinal")]
    score_bytes = _serialize_jsonl(score_rows, lambda row: row["query_ordinal"])
    score_sha = _sha256_bytes(score_bytes)
    score_path = root / "data/v3/evaluation" / f"authored_canary_reranker_scores_{score_sha}.jsonl"
    write_immutable(score_path, score_bytes)
    score_by_key = {
        (row["dev_id"], candidate["chunk_id"]): candidate["reranker_score"]
        for row in score_rows
        for candidate in row["candidates"]
    }

    current_policy_rows = [row for row in overlay_rows if row["is_current_revision"]]
    if len(current_policy_rows) != 1:
        raise RuntimeError("Expected exactly one current policy revision")
    current_policy_document_id = current_policy_rows[0]["document_id"]
    case_rows = []
    for dev, execution in zip(dev_rows, executions, strict=True):
        runtime = execution["runtime"]
        routed = execution["routed"]
        route = None if routed is None else routed["route"]
        retrieval_ids: set[str] = set()
        selected_ids: set[str] = set()
        baseline = _fail_closed("blocked_runtime_error")
        canonical = copy.deepcopy(baseline)
        if route is not None and execution["execution_error"] is None:
            action = route["route_action"]
            if action == "retrieve":
                retrieval_ids = {row["chunk_id"] for row in routed["hits"]}
                selected = execution["selected"]
                selected_ids = {row["chunk_id"] for row in selected}
                baseline = _single_baseline_response(
                    runtime, routed, selected, artifacts.documents_by_id
                )
                if selected:
                    scored_candidates = [
                        {
                            **candidate,
                            "reranker_score": score_by_key[(
                                dev["dev_id"], candidate["chunk_id"]
                            )],
                        }
                        for candidate in selected
                    ]
                    chosen = rerank_evidence(dev["question"], scored_candidates)[0]
                    chunk = artifacts.chunks_by_id[chosen["chunk_id"]]
                    document = artifacts.documents_by_id[chunk["parent_document_id"]]
                    canonical = _single_response(
                        dev["dev_id"],
                        dev["question"],
                        route["answerability"],
                        route,
                        chosen,
                        chunk,
                        document,
                        current_policy_document_id,
                    )
            elif action == "decompose":
                children = execution["children"]
                retrieval_ids = {
                    row["chunk_id"] for child in children for row in child["hits"]
                }
                selected_ids = {
                    row["chunk_id"]
                    for child in children
                    for row in child["selected_evidence"]
                }
                merged = merge_decomposed_evidence(
                    dev["dev_id"], children, artifacts.documents_by_id
                )
                retrieval_case = {
                    "case_id": dev["dev_id"],
                    "parent_question": dev["question"],
                    "children": children,
                    "merge": merged,
                }
                if merged["merge_status"].startswith("blocked_"):
                    baseline = _fail_closed("blocked_no_verified_evidence")
                else:
                    plan = build_answer_plan(retrieval_case, artifacts.documents_by_id)
                    verification = verify_answer_plan(
                        plan, retrieval_case, artifacts.documents_by_id
                    )
                    baseline = _multi_response(
                        {"answer_plan": plan, "verification": verification}
                    )
                canonical = copy.deepcopy(baseline)
            else:
                baseline = build_abstention_response(runtime, route)
                canonical = copy.deepcopy(baseline)
        group_results = _group_rows(
            dev, retrieval_ids, selected_ids, baseline, canonical
        )
        canonical_ids = set(canonical["citation_chunk_ids"])
        evidence_for_policy = selected_ids.union(canonical_ids)
        expected_action = dev["query_policy"]["expected_route_action"]
        exposure = bool(
            expected_action in {"reject", "realtime_api"}
            and (retrieval_ids or selected_ids or canonical_ids)
        )
        temporal = _temporal_revision_violations(
            dev,
            route,
            evidence_for_policy,
            artifacts.chunks_by_id,
            artifacts.documents_by_id,
            overlay_rows,
        )
        baseline_claims = _response_claims(baseline)
        canonical_claims = _response_claims(canonical)
        case_rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "evaluator_version": EVALUATOR_VERSION,
                "case_id": dev["dev_id"],
                "query_ordinal": dev["query_ordinal"],
                "question": dev["question"],
                "source_ids": dev["source_ids"],
                "answerability": dev["answerability"],
                "time_scope": dev["time_scope"],
                "expected_route_action": expected_action,
                "actual_route": route,
                "route_action_exact": route is not None
                and route["route_action"] == expected_action,
                "execution_error": execution["execution_error"],
                "retrieval_chunk_ids": sorted(retrieval_ids),
                "selected_chunk_ids": sorted(selected_ids),
                "baseline": {
                    "runtime_status": baseline["runtime_status"],
                    "citation_chunk_ids": baseline["citation_chunk_ids"],
                    "claims": [
                        {
                            "claim_text": claim["claim_text"],
                            "citation_chunk_id": claim["citation_chunk_id"],
                        }
                        for claim in baseline_claims
                    ],
                },
                "canonical": {
                    "runtime_status": canonical["runtime_status"],
                    "citation_chunk_ids": canonical["citation_chunk_ids"],
                    "claims": [
                        {
                            "claim_text": claim["claim_text"],
                            "citation_chunk_id": claim["citation_chunk_id"],
                        }
                        for claim in canonical_claims
                    ],
                },
                "group_results": group_results,
                "temporal_revision_violations": temporal,
                "false_realtime_evidence_exposure": exposure,
                "partial_disclaimer": dev["answerability"] == "partial"
                and canonical["rendered_answer"].startswith(PARTIAL_DISCLAIMER),
                "evaluation_role": "authored_canary_independently_reviewed",
                "failure_details_inspected": False,
            }
        )

    aggregate = aggregate_canary(case_rows)
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    case_bytes = _serialize_jsonl(case_rows, lambda row: row["query_ordinal"])
    case_sha = _sha256_bytes(case_bytes)
    case_path = evaluation_dir / f"authored_canary_first_run_cases_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "claim_reranker_version": CLAIM_RERANKER_VERSION,
        "evaluation_role": "authored_canary_independently_reviewed_not_independent_holdout",
        "first_sealed_run": True,
        "gold_available_to_runtime": False,
        "failure_details_inspected": False,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "runtime_artifacts": {
            "full_query_embeddings": {
                "path": _relative(root, full_embedding_path),
                "sha256": full_embedding_sha,
                "rows": len(dev_rows),
                "dimension": dimension,
            },
            "child_query_embeddings": {
                "path": _relative(root, child_embedding_path),
                "sha256": child_embedding_sha,
                "rows": len(child_questions),
                "dimension": dimension,
            },
            "reranker_scores": {
                "path": _relative(root, score_path),
                "sha256": score_sha,
                "pair_count": len(score_pairs),
            },
            "query_model": query_model,
            "child_query_model": child_query_model,
            "reranker_model": reranker_model,
        },
        "cases": {
            "path": _relative(root, case_path),
            "sha256": case_sha,
            "row_count": len(case_rows),
        },
        "metrics": aggregate["metrics"],
        "gates": aggregate["gates"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"authored_canary_first_run_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "authored_canary_independently_reviewed_not_independent_holdout",
        "metrics": aggregate["metrics"],
        "gates": aggregate["gates"],
        "decision": "GO" if aggregate["go"] else "NO-GO",
        "production_evidence_selector": "NO-GO",
        "final_benchmark": "NO-GO",
        "failure_case_details": "SEALED_NOT_INSPECTED",
        "sample_size_limitation": "32 total; four authored cases per source",
        "artifacts": {
            "cases_path": _relative(root, case_path),
            "cases_sha256": case_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "frozen_blind_accessed": False,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"authored_canary_first_run_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = "\n".join(
        [
            "# DNF RAG v3 authored canary first sealed run",
            "",
            f"- decision: **{report['decision']}**",
            "- evaluation role: authored canary, independently reviewed; not an independent holdout",
            "- failure details: sealed and not inspected",
            "",
            "## Preregistered gates",
            "",
            *[f"- {name}: **{'PASS' if value else 'FAIL'}**" for name, value in aggregate["gates"].items()],
            "",
            "The sample contains only four authored cases per source; Wilson intervals and numerators are in the JSON report.",
            "",
        ]
    ).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown)
    markdown_path = reports_dir / f"authored_canary_first_run_{markdown_sha}.md"
    write_immutable(markdown_path, markdown)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during canary execution: {name}")
    return {
        "decision": report["decision"],
        "metrics": aggregate["metrics"],
        "gates": aggregate["gates"],
        "cases_path": str(case_path),
        "cases_sha256": case_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "failure_details_inspected": False,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run the first sealed authored canary")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    parser.add_argument("--canary-manifest", type=Path, default=DEFAULT_CANARY_MANIFEST)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--bm25-manifest", type=Path, default=DEFAULT_BM25_MANIFEST)
    parser.add_argument("--dense-manifest", type=Path, default=DEFAULT_DENSE_MANIFEST)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--full-query-embeddings", type=Path)
    parser.add_argument("--child-query-embeddings", type=Path)
    parser.add_argument("--reranker-scores", type=Path)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(
        root=args.root,
        canary_path=args.canary,
        canary_manifest_path=args.canary_manifest,
        documents_path=args.documents,
        chunks_path=args.chunks,
        bm25_manifest_path=args.bm25_manifest,
        dense_manifest_path=args.dense_manifest,
        device=args.device,
        batch_size=args.batch_size,
        full_query_embeddings_path=args.full_query_embeddings,
        child_query_embeddings_path=args.child_query_embeddings,
        reranker_scores_path=args.reranker_scores,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
