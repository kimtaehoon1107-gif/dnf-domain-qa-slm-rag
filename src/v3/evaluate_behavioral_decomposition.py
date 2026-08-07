from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.answer_target_router import analyze_answer_targets
from src.v3.behavioral_decomposition_filter import evaluate_behavioral_coverage
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.evaluate_authored_canary import wilson_interval
from src.v3.evaluate_retrieval import encode_queries
from src.v3.question_decomposer import apply_parent_source_hints, decompose_question
from src.v3.question_router import (
    DEFAULT_AS_OF,
    _retrieve_for_route,
    build_source_entity_index,
    route_and_retrieve_with_embedding,
)
from src.v3.retrieve_decomposed import retrieve_decomposed_child
from src.v3.retrieve_v3 import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DOCUMENTS,
    load_runtime_artifacts,
)


EVALUATOR_VERSION = "behavioral-decomposition-coverage-pilot-v3.2.0"
REPORT_SCHEMA_VERSION = "behavioral-decomposition-coverage-report-v3.2"
MANIFEST_SCHEMA_VERSION = "behavioral-decomposition-coverage-manifest-v3.2"
DIAGNOSTIC_SCHEMA_VERSION = "behavioral-decomposition-diagnostic-v3.2"
THRESHOLD_GRID = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
TOP_K = 10

DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY_EMBEDDINGS = Path(
    "data/v3/evaluation/authored_canary_full_query_embeddings_"
    "b73dae45841e1e98278d8b50a22243432c56a0d66635ad4179dd1a0815a39777.f32"
)
DEFAULT_DEV_EMBEDDINGS = Path(
    "data/v3/retrieval/retrieval_dev_query_embeddings_"
    "323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/behavioral_decomposition_coverage_pilot.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _rate(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "wilson_95_percent": wilson_interval(successes, total),
    }


def build_runtime_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": row["dev_id"],
            "question": row["question"],
            "as_of": row.get("as_of") or DEFAULT_AS_OF,
        }
        for row in rows
    ]


def _load_embeddings(path: Path, row_count: int, dimension: int) -> np.ndarray:
    values = np.fromfile(path, dtype="<f4")
    if values.size != row_count * dimension:
        raise RuntimeError(f"Embedding shape differs from input rows: {path}")
    return values.reshape(row_count, dimension)


def _deduplicate_hits(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for child in sorted(children, key=lambda row: row["subquestion"]["ordinal"]):
        for hit in child["hits"]:
            if hit["chunk_id"] in seen:
                continue
            seen.add(hit["chunk_id"])
            output.append(hit)
    return output


def _prepare_parent_executions(
    runtime_rows: list[dict[str, Any]],
    full_embeddings: np.ndarray,
    artifacts: Any,
    overlay_rows: list[dict[str, Any]],
    source_entity_index: dict[str, list[frozenset[str]]],
) -> tuple[list[dict[str, Any]], list[tuple[int, dict[str, Any]]]]:
    executions = []
    child_specs = []
    for runtime, embedding in zip(runtime_rows, full_embeddings, strict=True):
        started = time.perf_counter_ns()
        routed = route_and_retrieve_with_embedding(
            runtime["question"],
            embedding,
            artifacts,
            overlay_rows,
            top_k=TOP_K,
            current_as_of=runtime["as_of"],
            source_entity_index=source_entity_index,
        )
        route = routed["route"]
        action = route["route_action"]
        signal = None
        single_hits = routed["hits"]
        decomposition = None
        decomposition_status = "not_candidate"
        decomposition_error = None
        if action not in {"reject", "realtime_api", "clarify"}:
            signal = analyze_answer_targets(runtime["question"])
            if action != "retrieve":
                single_route = copy.deepcopy(route)
                single_route["route_action"] = "retrieve"
                single_route["needs_decomposition"] = False
                single_hits = _retrieve_for_route(
                    runtime["question"],
                    embedding,
                    artifacts,
                    overlay_rows,
                    single_route,
                    top_k=TOP_K,
                    current_as_of=runtime["as_of"],
                )["hits"]
            if signal["needs_decomposition"]:
                try:
                    decomposition = decompose_question(
                        runtime["case_id"],
                        runtime["question"],
                        as_of=runtime["as_of"],
                    )
                    decomposition = apply_parent_source_hints(
                        decomposition,
                        route,
                        artifacts.bm25_index,
                        as_of=runtime["as_of"],
                    )
                    decomposition_status = "supported"
                except RuntimeError as exc:
                    decomposition_status = "unsupported"
                    decomposition_error = f"{type(exc).__name__}:{exc}"
        execution = {
            "case_id": runtime["case_id"],
            "question": runtime["question"],
            "as_of": runtime["as_of"],
            "baseline_route_action": action,
            "route_source_count": len(route["source_ids"]),
            "answerability_short_circuit": action in {"reject", "realtime_api"},
            "signal_a_candidate": bool(signal and signal["needs_decomposition"]),
            "signal_a_target_count": 0 if signal is None else signal["answer_target_count"],
            "single_hits": single_hits,
            "decomposition": decomposition,
            "decomposition_status": decomposition_status,
            "decomposition_error": decomposition_error,
            "children": [],
            "decomposed_union_hits": [],
            "single_search_and_plan_ms": round(
                (time.perf_counter_ns() - started) / 1_000_000, 6
            ),
            "child_retrieval_ms": 0.0,
        }
        execution_index = len(executions)
        executions.append(execution)
        if decomposition is not None:
            child_specs.extend(
                (execution_index, child) for child in decomposition["subquestions"]
            )
    return executions, child_specs


def _run_children(
    executions: list[dict[str, Any]],
    child_specs: list[tuple[int, dict[str, Any]]],
    artifacts: Any,
    overlay_rows: list[dict[str, Any]],
    source_entity_index: dict[str, list[frozenset[str]]],
    *,
    device: str | None,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    questions = [child["question"] for _, child in child_specs]
    dimension = artifacts.dense_embeddings.shape[1]
    if questions:
        started = time.perf_counter_ns()
        embeddings, model = encode_queries(
            questions,
            artifacts.dense_model,
            device=device,
            batch_size=16,
        )
        embedding_ms = (time.perf_counter_ns() - started) / 1_000_000
    else:
        embeddings = np.empty((0, dimension), dtype="<f4")
        model = {**artifacts.dense_model, "device": "not_used"}
        embedding_ms = 0.0
    for (execution_index, child), embedding in zip(
        child_specs, embeddings, strict=True
    ):
        execution = executions[execution_index]
        started = time.perf_counter_ns()
        try:
            result = retrieve_decomposed_child(
                child,
                embedding,
                artifacts,
                overlay_rows,
                current_as_of=execution["as_of"],
                top_k=TOP_K,
                source_entity_index=source_entity_index,
            )
            execution["children"].append(result)
        except RuntimeError as exc:
            execution["decomposition_status"] = "child_failed"
            execution["decomposition_error"] = f"{type(exc).__name__}:{exc}"
        execution["child_retrieval_ms"] += (
            time.perf_counter_ns() - started
        ) / 1_000_000
    for execution in executions:
        execution["child_retrieval_ms"] = round(
            execution["child_retrieval_ms"], 6
        )
        execution["decomposed_union_hits"] = _deduplicate_hits(
            execution["children"]
        )
    candidate_count = sum(
        execution["decomposition"] is not None for execution in executions
    )
    observation = {
        "child_query_count": len(questions),
        "candidate_count_with_supported_decomposition": candidate_count,
        "batch_embedding_total_ms": round(embedding_ms, 6),
        "batch_embedding_amortized_per_candidate_ms": round(
            embedding_ms / candidate_count, 6
        )
        if candidate_count
        else 0.0,
        "bit_reproducible": False,
    }
    gc.collect()
    return embeddings, model, observation


def _coverage(execution: dict[str, Any], threshold: float) -> dict[str, Any]:
    if not execution["signal_a_candidate"] or execution["decomposition"] is None:
        return {
            "coverage_single": 0,
            "coverage_decomposed": 0,
            "coverage_measurable": False,
            "commit_decomposition": False,
            "single_target_coverage_ratios": [],
            "decomposed_target_coverage_ratios": [],
        }
    return evaluate_behavioral_coverage(
        execution["question"],
        execution["single_hits"],
        execution["decomposed_union_hits"],
        threshold=threshold,
    )


def predicted_action(execution: dict[str, Any], threshold: float) -> str:
    if execution["baseline_route_action"] in {"reject", "realtime_api", "clarify"}:
        return execution["baseline_route_action"]
    return "decompose" if _coverage(execution, threshold)["commit_decomposition"] else "retrieve"


def score_executions(
    executions: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    expected_action: Callable[[dict[str, Any]], str],
    threshold: float,
) -> dict[str, Any]:
    if len(executions) != len(rows):
        raise RuntimeError("Execution and scoring rows differ")
    true_positive = 0
    false_positive = 0
    false_negative = 0
    exact = 0
    expected_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    for execution, row in zip(executions, rows, strict=True):
        expected = expected_action(row)
        predicted = predicted_action(execution, threshold)
        expected_counts[expected] += 1
        predicted_counts[predicted] += 1
        exact += predicted == expected
        true_positive += predicted == expected == "decompose"
        false_positive += predicted == "decompose" and expected != "decompose"
        false_negative += predicted != "decompose" and expected == "decompose"
    return {
        "threshold": threshold,
        "row_count": len(rows),
        "expected_action_counts": dict(sorted(expected_counts.items())),
        "predicted_action_counts": dict(sorted(predicted_counts.items())),
        "route_action_exact": _rate(exact, len(rows)),
        "decomposition": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": _rate(true_positive, true_positive + false_positive),
            "recall": _rate(true_positive, true_positive + false_negative),
        },
    }


def select_threshold(sweep: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        row for row in sweep if row["decomposition"]["recall"]["rate"] >= 0.80
    ]
    candidates = eligible or sweep
    selected = max(
        candidates,
        key=lambda row: (
            row["route_action_exact"]["successes"],
            row["decomposition"]["precision"]["rate"],
            row["decomposition"]["recall"]["rate"],
            row["threshold"],
        ),
    )
    return {
        "threshold": selected["threshold"],
        "recall_floor_satisfied": bool(eligible),
        "selection_used_development_63": False,
        "selection_order": [
            "recall_ge_0.80",
            "max_route_exact",
            "max_precision",
            "max_recall",
            "higher_threshold",
        ],
    }


def _dev_expected_action(row: dict[str, Any]) -> str:
    if row["answerability"] == "false":
        return "reject"
    return "decompose" if row["query_kind"] == "multi_evidence" else "retrieve"


def _percentiles(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "count": len(ordered),
        "median_ms": round(statistics.median(ordered), 6),
        "p95_ms": round(ordered[index], 6),
        "max_ms": round(max(ordered), 6),
    }


def _finalize_diagnostics(
    executions: list[dict[str, Any]],
    threshold: float,
    embedding_observation: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    amortized = embedding_observation[
        "batch_embedding_amortized_per_candidate_ms"
    ]
    rows = []
    candidate_latencies = []
    final_latencies = []
    single_path_latencies = []
    for execution in executions:
        started = time.perf_counter_ns()
        coverage = _coverage(execution, threshold)
        coverage_ms = (time.perf_counter_ns() - started) / 1_000_000
        final_action = (
            execution["baseline_route_action"]
            if execution["baseline_route_action"]
            in {"reject", "realtime_api", "clarify"}
            else "decompose"
            if coverage["commit_decomposition"]
            else "retrieve"
        )
        embedding_share = amortized if execution["decomposition"] is not None else 0.0
        final_ms = (
            execution["single_search_and_plan_ms"]
            + execution["child_retrieval_ms"]
            + coverage_ms
            + embedding_share
        )
        single_path_latencies.append(execution["single_search_and_plan_ms"])
        final_latencies.append(final_ms)
        if execution["signal_a_candidate"]:
            candidate_latencies.append(final_ms)
        rows.append(
            {
                "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                "case_id": execution["case_id"],
                "baseline_route_action": execution["baseline_route_action"],
                "route_source_count": execution["route_source_count"],
                "answerability_short_circuit": execution[
                    "answerability_short_circuit"
                ],
                "signal_a_candidate": execution["signal_a_candidate"],
                "signal_a_target_count": execution["signal_a_target_count"],
                "decomposition_status": execution["decomposition_status"],
                "decomposition_error": execution["decomposition_error"],
                "child_count": len(execution["children"]),
                "single_hit_count": len(execution["single_hits"]),
                "decomposed_union_hit_count": len(
                    execution["decomposed_union_hits"]
                ),
                "threshold": threshold,
                "coverage_single": coverage["coverage_single"],
                "coverage_decomposed": coverage["coverage_decomposed"],
                "single_target_coverage_ratios": coverage[
                    "single_target_coverage_ratios"
                ],
                "decomposed_target_coverage_ratios": coverage[
                    "decomposed_target_coverage_ratios"
                ],
                "commit_decomposition": coverage["commit_decomposition"],
                "final_route_action": final_action,
                "single_search_and_plan_ms": execution[
                    "single_search_and_plan_ms"
                ],
                "child_retrieval_ms": execution["child_retrieval_ms"],
                "coverage_filter_ms": round(coverage_ms, 6),
                "child_embedding_amortized_ms": embedding_share,
                "observed_total_ms": round(final_ms, 6),
                "question_text_included": False,
                "gold_or_expected_identifiers_included": False,
            }
        )
    return rows, {
        "single_search_and_plan": _percentiles(single_path_latencies),
        "signal_a_candidate_dual_search_filter": _percentiles(candidate_latencies),
        "all_rows_observed_total": _percentiles(final_latencies),
        "child_embedding_batch": embedding_observation,
        "latency_is_observational_not_bit_reproducible": True,
    }


def _freeze_embeddings(
    root: Path, name: str, embeddings: np.ndarray
) -> tuple[Path, str]:
    payload = np.asarray(embeddings, dtype="<f4").tobytes(order="C")
    sha256 = _sha256_bytes(payload)
    path = root / "data/v3/router" / f"{name}_{sha256}.f32"
    write_immutable(path, payload)
    return path, sha256


def _freeze_diagnostics(
    root: Path, name: str, rows: list[dict[str, Any]]
) -> tuple[Path, str]:
    payload = _serialize_jsonl(rows, lambda row: row["case_id"])
    sha256 = _sha256_bytes(payload)
    path = root / "data/v3/router" / f"{name}_{sha256}.jsonl"
    write_immutable(path, payload)
    return path, sha256


def evaluate_and_freeze(*, root: Path, device: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "downgraded_adaptive_canary": root / DEFAULT_CANARY,
        "adaptive_development": root / DEFAULT_DEV,
        "canary_full_query_embeddings": root / DEFAULT_CANARY_EMBEDDINGS,
        "development_full_query_embeddings": root / DEFAULT_DEV_EMBEDDINGS,
        "temporal_overlay": root / DEFAULT_OVERLAY,
        "bm25_manifest": root / DEFAULT_BM25_MANIFEST,
        "dense_manifest": root / DEFAULT_DENSE_MANIFEST,
        "chunks": root / DEFAULT_CHUNKS,
        "documents": root / DEFAULT_DOCUMENTS,
        "contract": root / DEFAULT_CONTRACT,
        "signal_a_source": root / "src/v3/answer_target_router.py",
        "coverage_filter_source": root / "src/v3/behavioral_decomposition_filter.py",
        "decomposer_source": root / "src/v3/question_decomposer.py",
        "decomposed_retriever_source": root / "src/v3/retrieve_decomposed.py",
        "question_router_source": root / "src/v3/question_router.py",
        "retriever_source": root / "src/v3/retrieve_v3.py",
        "evaluator_source": root / "src/v3/evaluate_behavioral_decomposition.py",
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    canary_rows = read_jsonl(input_paths["downgraded_adaptive_canary"])
    dev_rows = read_jsonl(input_paths["adaptive_development"])
    if len(canary_rows) != 32 or len(dev_rows) != 63:
        raise RuntimeError("Unexpected behavioral pilot input row count")
    artifacts = load_runtime_artifacts(
        root,
        bm25_manifest_path=input_paths["bm25_manifest"],
        dense_manifest_path=input_paths["dense_manifest"],
        chunks_path=input_paths["chunks"],
        documents_path=input_paths["documents"],
    )
    overlay_rows = read_jsonl(input_paths["temporal_overlay"])
    dimension = artifacts.dense_embeddings.shape[1]
    source_entity_index = build_source_entity_index(
        list(artifacts.documents_by_id.values()),
        list(artifacts.chunks_by_id.values()),
    )

    canary_runtime = build_runtime_rows(canary_rows)
    canary_embeddings = _load_embeddings(
        input_paths["canary_full_query_embeddings"], len(canary_rows), dimension
    )
    canary_executions, canary_children = _prepare_parent_executions(
        canary_runtime,
        canary_embeddings,
        artifacts,
        overlay_rows,
        source_entity_index,
    )
    canary_child_embeddings, canary_model, canary_embedding_observation = (
        _run_children(
            canary_executions,
            canary_children,
            artifacts,
            overlay_rows,
            source_entity_index,
            device=device,
        )
    )
    canary_sweep = [
        score_executions(
            canary_executions,
            canary_rows,
            lambda row: row["query_policy"]["expected_route_action"],
            threshold,
        )
        for threshold in THRESHOLD_GRID
    ]
    threshold_selection = select_threshold(canary_sweep)
    threshold = threshold_selection["threshold"]
    canary_selected = next(
        row for row in canary_sweep if row["threshold"] == threshold
    )

    dev_runtime = build_runtime_rows(dev_rows)
    dev_embeddings = _load_embeddings(
        input_paths["development_full_query_embeddings"], len(dev_rows), dimension
    )
    dev_executions, dev_children = _prepare_parent_executions(
        dev_runtime,
        dev_embeddings,
        artifacts,
        overlay_rows,
        source_entity_index,
    )
    dev_child_embeddings, dev_model, dev_embedding_observation = _run_children(
        dev_executions,
        dev_children,
        artifacts,
        overlay_rows,
        source_entity_index,
        device=device,
    )
    dev_selected = score_executions(
        dev_executions, dev_rows, _dev_expected_action, threshold
    )

    canary_diagnostics, canary_latency = _finalize_diagnostics(
        canary_executions, threshold, canary_embedding_observation
    )
    dev_diagnostics, dev_latency = _finalize_diagnostics(
        dev_executions, threshold, dev_embedding_observation
    )
    dev_answerable_non_multi = {
        row["dev_id"]
        for row in dev_rows
        if row["answerability"] != "false" and row["query_kind"] != "multi_evidence"
    }
    dev_multi = {
        row["dev_id"] for row in dev_rows if row["query_kind"] == "multi_evidence"
    }
    dev_false = {
        row["dev_id"] for row in dev_rows if row["answerability"] == "false"
    }
    dev_predictions = {
        execution["case_id"]: predicted_action(execution, threshold)
        for execution in dev_executions
    }
    dev_overdecomposition = sum(
        dev_predictions[row_id] == "decompose" for row_id in dev_answerable_non_multi
    )
    dev_multi_recall = sum(
        dev_predictions[row_id] == "decompose" for row_id in dev_multi
    )
    dev_false_short_circuit = sum(
        dev_predictions[row_id] in {"reject", "realtime_api"} for row_id in dev_false
    )
    gates = {
        "canary_route_exact_gt_18_of_32": canary_selected["route_action_exact"][
            "successes"
        ]
        > 18,
        "canary_decomposition_recall_ge_0_80": canary_selected["decomposition"][
            "recall"
        ]["rate"]
        >= 0.80,
        "canary_decomposition_precision_ge_0_60": canary_selected[
            "decomposition"
        ]["precision"]["rate"]
        >= 0.60,
        "dev_multi_recall_4_of_4": dev_multi_recall == 4,
        "dev_answerable_non_multi_overdecomposition_0": dev_overdecomposition == 0,
        "dev_false_short_circuit_regression_0": dev_false_short_circuit
        == len(dev_false),
        "new_field_or_intent_keyword_rules_0": True,
        "new_store_expansion_or_broad_fallback_0": True,
    }
    go = all(gates.values())

    canary_diag_path, canary_diag_sha = _freeze_diagnostics(
        root, "behavioral_coverage_canary_diagnostics", canary_diagnostics
    )
    dev_diag_path, dev_diag_sha = _freeze_diagnostics(
        root, "behavioral_coverage_dev_diagnostics", dev_diagnostics
    )
    canary_embedding_path, canary_embedding_sha = _freeze_embeddings(
        root, "behavioral_coverage_canary_child_embeddings", canary_child_embeddings
    )
    dev_embedding_path, dev_embedding_sha = _freeze_embeddings(
        root, "behavioral_coverage_dev_child_embeddings", dev_child_embeddings
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "adaptive_validation_aggregate_threshold_tuning",
        "threshold_grid": list(THRESHOLD_GRID),
        "threshold_selection": threshold_selection,
        "canary_32_threshold_sweep": canary_sweep,
        "canary_32_selected": canary_selected,
        "development_63_selected_once": dev_selected,
        "development_63_stage_metrics": {
            "answerable_non_multi_overdecomposition": dev_overdecomposition,
            "multi_decomposition_recall": _rate(dev_multi_recall, len(dev_multi)),
            "false_answerability_short_circuit": _rate(
                dev_false_short_circuit, len(dev_false)
            ),
        },
        "latency": {"canary_32": canary_latency, "development_63": dev_latency},
        "child_embedding_models": {"canary_32": canary_model, "development_63": dev_model},
        "gates": gates,
        "decisions": {
            "behavioral_coverage_prevalidation": "GO" if go else "NO-GO",
            "promote_to_canonical_router": "GO" if go else "NO-GO",
            "new_40_canary_authoring": "GO" if go else "NO-GO",
            "new_40_canary_execution": "NO-GO_PENDING_AUTHORING_AND_REVIEW",
            "next_candidate_if_no_go": "fixed_semantic_or_llm_route_judge",
        },
        "runtime_contract": {
            "commit_rule": "coverage_decomposed_strictly_greater_than_coverage_single",
            "gold_chunk_document_source_ids_used_for_coverage": False,
            "expected_route_used_only_after_retrieval_for_aggregate_scoring": True,
            "signal_a_changed": False,
            "decomposer_changed": False,
            "retriever_changed": False,
            "new_field_or_intent_keyword_rules_added": 0,
            "new_store_expansion_implemented": False,
            "broad_fallback_implemented": False,
            "individual_adaptive_failures_inspected": False,
            "questions_or_gold_modified": False,
            "frozen_blind_accessed": False,
        },
        "artifacts": {
            "canary_diagnostics": {
                "path": _relative(root, canary_diag_path),
                "sha256": canary_diag_sha,
                "row_count": len(canary_diagnostics),
                "question_or_gold_text_included": False,
            },
            "development_diagnostics": {
                "path": _relative(root, dev_diag_path),
                "sha256": dev_diag_sha,
                "row_count": len(dev_diagnostics),
                "question_or_gold_text_included": False,
            },
            "canary_child_embeddings": {
                "path": _relative(root, canary_embedding_path),
                "sha256": canary_embedding_sha,
                "row_count": len(canary_child_embeddings),
            },
            "development_child_embeddings": {
                "path": _relative(root, dev_embedding_path),
                "sha256": dev_embedding_sha,
                "row_count": len(dev_child_embeddings),
            },
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / f"behavioral_coverage_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = "\n".join(
        [
            "# DNF RAG v3 behavioral decomposition coverage pilot",
            "",
            f"- decision: **{report['decisions']['behavioral_coverage_prevalidation']}**",
            f"- selected threshold: {threshold}",
            f"- canary route exact: {canary_selected['route_action_exact']}",
            f"- canary decomposition: {canary_selected['decomposition']}",
            f"- dev overdecomposition: {dev_overdecomposition}",
            f"- dev multi recall: {dev_multi_recall}/{len(dev_multi)}",
            f"- latency: {report['latency']}",
            "- expected/gold identifiers used by runtime coverage: no",
            "- new keyword rules: 0",
            "- new store expansion: no",
            "",
        ]
    ).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown)
    markdown_path = root / "reports/v3" / f"behavioral_coverage_pilot_{markdown_sha}.md"
    write_immutable(markdown_path, markdown)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "report": {"path": _relative(root, report_path), "sha256": report_sha},
        "report_markdown": {
            "path": _relative(root, markdown_path),
            "sha256": markdown_sha,
        },
        "artifacts": report["artifacts"],
        "latency_observation_bit_reproducible": False,
        "individual_failure_rows_inspected": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        root
        / "data/v3/router"
        / f"behavioral_coverage_pilot_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Behavioral pilot input changed: {name}")
    return {
        "decision": report["decisions"]["behavioral_coverage_prevalidation"],
        "selected_threshold": threshold,
        "gates": gates,
        "canary_32": canary_selected,
        "development_63_stage_metrics": report["development_63_stage_metrics"],
        "latency": report["latency"],
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "markdown_path": str(markdown_path),
        "markdown_sha256": markdown_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate behavioral decomposition coverage")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--device", choices=("cpu", "cuda"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(
        json.dumps(
            evaluate_and_freeze(root=args.root, device=args.device),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
