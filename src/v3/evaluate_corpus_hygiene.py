from __future__ import annotations

import argparse
import gc
import hashlib
import json
import statistics
import subprocess
import sys
import time
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
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_extractive_assembler import (
    DEFAULT_CANARY_BASELINE_CASES,
    DEFAULT_DEV_BASELINE_CASES,
    build_cases as build_assembler_cases,
)
from src.v3.evaluate_extractive_assembler_v2 import aggregate_v2, score_cases_v2
from src.v3.evaluate_extractive_assembler_v3 import (
    build_segment_rows,
    run_segment_reranker,
)
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_federated_retrieval_ab import (
    ARM_GLOBAL,
    ARM_QUOTA,
    ASSEMBLER_K,
    ASSEMBLER_THRESHOLD,
    BATCH_SIZE,
    FEDERATED_ARMS,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
    build_federated_arm_cases,
    build_federated_requests,
    build_requirement_segments,
    build_scored_cases as build_federated_scored_cases,
    execute_federated_retrieval,
    run_segment_reranker as run_federated_segment_reranker,
    summarize_arm as summarize_federated_arm,
    temporal_safety_metrics,
)
from src.v3.evaluate_requirement_reranker import (
    build_cases as build_requirement_cases,
    evaluate_rows as evaluate_requirement_rows,
    run_model as run_requirement_model,
)
from src.v3.evaluate_router_backbone_ab import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_CANARY,
    DEFAULT_CLASSIFIER_DIAGNOSTICS,
    DEFAULT_CLASSIFIER_PREDICTIONS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
    DEFAULT_TAXONOMY,
    build_cases as build_backbone_cases,
    summarize_arm as summarize_backbone_arm,
    summarize_cross_parent,
)
from src.v3.retrieve_v3 import load_runtime_artifacts


EVALUATOR_VERSION = "retrieval-corpus-hygiene-remeasurement-v3.1.0"
REPORT_SCHEMA_VERSION = "retrieval-corpus-hygiene-report-v3.1"
MANIFEST_SCHEMA_VERSION = "retrieval-corpus-hygiene-manifest-v3.1"

DEFAULT_DIRTY_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_DIRTY_CANARY_CANDIDATES = Path(
    "data/v3/evaluation/authored_canary_reranker_scores_"
    "589eb3b27a7c6757bee3b4d393f27a01c5dd59b0bb85af7f0331ee2601cf517e.jsonl"
)
DEFAULT_DIRTY_DEV_CANDIDATES = Path(
    "data/v3/evidence/evidence_reranker_scores_"
    "ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl"
)
DEFAULT_DIRTY_ASSEMBLER = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_DIRTY_BACKBONE = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_PRIOR_REQUIREMENT_CANDIDATES = Path(
    "data/v3/retrieval/requirement_retrieval_ab_candidates_"
    "e4415535221f405f807de7776a76e163364db4c7821b58b6bac34a0dc50c04f9.jsonl"
)
DEFAULT_PRIOR_REQUIREMENT_MANIFEST = Path(
    "data/v3/retrieval/requirement_retrieval_ab_manifest_"
    "40fc2122cb462f97ac930f201e817e7784c4c17a5be07485e2b244d926597788.json"
)
DEFAULT_REQUIREMENT_EMBEDDINGS = Path(
    "data/v3/retrieval/requirement_retrieval_query_embeddings_"
    "b3aa1d0062caa9b82ab432200a5928f7a1e65a76fb728e7ce3f549c21cd7e02f.f32"
)
DEFAULT_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_P1_ADJUDICATION = Path(
    "data/v3/evaluation/federated_quota_regression_adjudication_"
    "e977562162a361f33decbcfc7f38ac136b53252bef81ad7a22de394a1eab4fcd.jsonl"
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


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
    }


def candidate_recall(
    dev_rows: list[dict[str, Any]],
    canary_rows: list[dict[str, Any]],
    dev_candidates: list[dict[str, Any]],
    canary_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    question_hits = 0
    question_total = 0
    group_hits = 0
    group_total = 0
    by_dataset = {}
    for name, gold_rows, candidate_rows in (
        ("adaptive_dev_63", dev_rows, dev_candidates),
        ("downgraded_canary_32", canary_rows, canary_candidates),
    ):
        candidates = {
            row["dev_id"]: {item["chunk_id"] for item in row.get("candidates", [])}
            for row in candidate_rows
        }
        local_questions = local_question_hits = local_groups = local_group_hits = 0
        for row in gold_rows:
            groups = row.get("evidence_groups", [])
            if not groups:
                continue
            local_questions += 1
            hits = []
            for group in groups:
                hit = bool(
                    candidates.get(row["dev_id"], set())
                    & set(group["acceptable_chunk_ids"])
                )
                hits.append(hit)
                local_groups += 1
                local_group_hits += hit
            local_question_hits += all(hits)
        by_dataset[name] = {
            "all_groups_candidate_present_questions": _ratio(
                local_question_hits, local_questions
            ),
            "evidence_groups_candidate_present": _ratio(
                local_group_hits, local_groups
            ),
        }
        question_hits += local_question_hits
        question_total += local_questions
        group_hits += local_group_hits
        group_total += local_groups
    return {
        "combined": {
            "all_groups_candidate_present_questions": _ratio(
                question_hits, question_total
            ),
            "evidence_groups_candidate_present": _ratio(group_hits, group_total),
        },
        **by_dataset,
    }


def exact_span_metrics(
    assembler_cases: list[dict[str, Any]], assembled: list[dict[str, Any]]
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in assembler_cases}
    valid = invalid = spans = 0
    for row in assembled:
        source = cases[row["case_id"]]["selected_chunks"]
        for decision in row["decisions"]:
            for span in decision["spans"]:
                spans += 1
                exact = source[span["chunk_id"]][span["start_char"] : span["end_char"]]
                if exact == span["text"]:
                    valid += 1
                else:
                    invalid += 1
    return {
        "valid": valid,
        "invalid": invalid,
        "total": spans,
        "rate": round(valid / spans, 8) if spans else 1.0,
    }


def _false_full_ids(rows: list[dict[str, Any]], arm: str = "arm0") -> set[str]:
    return {
        row["case_id"]
        for row in rows
        if row[arm]["score"]["false_full_answer"]
    }


def _freeze_jsonl(
    directory: Path, prefix: str, rows: list[dict[str, Any]], key: Any
) -> tuple[Path, str]:
    payload = _serialize_jsonl(rows, key)
    sha = _sha256_bytes(payload)
    path = directory / f"{prefix}_{sha}.jsonl"
    write_immutable(path, payload)
    return path, sha


def _run_clean_federated(
    *,
    root: Path,
    artifacts: Any,
    assembler_cases: list[dict[str, Any]],
    clean_chunks: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    attribution_rows: list[dict[str, Any]],
    dirty_backbone: list[dict[str, Any]],
    dirty_assembler: list[dict[str, Any]],
    prior_candidates: list[dict[str, Any]],
    prior_manifest: dict[str, Any],
    requirement_embeddings_path: Path,
    temporal_overlay: list[dict[str, Any]],
    device: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    requests = build_federated_requests(
        prior_candidates, assembler_cases, temporal_overlay
    )
    embedding_meta = prior_manifest["artifacts"]["query_embeddings"]
    embeddings = np.fromfile(requirement_embeddings_path, dtype="<f4").reshape(
        int(embedding_meta["row_count"]), int(embedding_meta["dimension"])
    )
    source_ids = sorted({row["source_id"] for row in clean_chunks})
    retrieval_rows, retrieval_latency = execute_federated_retrieval(
        requests, embeddings, artifacts, source_ids
    )
    arm_cases = {
        arm: build_federated_arm_cases(
            assembler_cases, retrieval_rows, clean_chunks, arm=arm
        )
        for arm in FEDERATED_ARMS
    }
    segment_rows = {
        arm: build_requirement_segments(cases) for arm, cases in arm_cases.items()
    }
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    load_started = time.perf_counter()
    model = CrossEncoder(
        MODEL_NAME,
        revision=MODEL_REVISION,
        max_length=MAX_LENGTH,
        device=device,
        local_files_only=True,
    )
    score_rows: dict[str, list[dict[str, Any]]] = {}
    reranker_latency = {}
    assembled = {}
    for arm in FEDERATED_ARMS:
        score_rows[arm], reranker_latency[arm] = run_federated_segment_reranker(
            arm_cases[arm], segment_rows[arm], model, arm=arm, device=device
        )
        assembled[arm] = assemble_chunk_diverse_configuration(
            arm_cases[arm],
            score_rows[arm],
            threshold=ASSEMBLER_THRESHOLD,
            k=ASSEMBLER_K,
        )
    case_rows = build_federated_scored_cases(
        ground_truth_rows=ground_truth,
        evaluation_rows=evaluation_rows,
        attribution_rows=attribution_rows,
        frozen_backbone_rows=dirty_backbone,
        frozen_assembler_rows=dirty_assembler,
        arm_assembler_rows=assembled,
        arm_cases=arm_cases,
        chunks=clean_chunks,
    )
    baseline_false = _false_full_ids(case_rows, "arm_a")
    arms = {
        "arm_a": summarize_federated_arm(
            case_rows, "arm_a", baseline_false_full_ids=baseline_false
        ),
        **{
            arm: summarize_federated_arm(
                case_rows, arm, baseline_false_full_ids=baseline_false
            )
            for arm in FEDERATED_ARMS
        },
    }
    safety = {
        arm: temporal_safety_metrics(retrieval_rows, assembled[arm], clean_chunks, arm=arm)
        for arm in FEDERATED_ARMS
    }
    return (
        {
            "arms": arms,
            "safety": safety,
            "retrieval_latency": retrieval_latency,
            "reranker_latency": reranker_latency,
            "model_load_ms": round((time.perf_counter() - load_started) * 1000, 3),
        },
        score_rows,
        case_rows,
    )


def evaluate_and_freeze(
    root: Path,
    *,
    clean_chunks_path: Path,
    clean_corpus_manifest_path: Path,
    bm25_manifest_path: Path,
    dense_manifest_path: Path,
    clean_dev_candidates_path: Path,
    clean_canary_candidates_path: Path,
    clean_canary_cases_path: Path,
    device: str,
    evaluated_at: str,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    fixed = {
        "ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "attribution": root / DEFAULT_ATTRIBUTION,
        "taxonomy": root / DEFAULT_TAXONOMY,
        "enumeration": root / DEFAULT_ENUMERATION,
        "classifier_predictions": root / DEFAULT_CLASSIFIER_PREDICTIONS,
        "classifier_diagnostics": root / DEFAULT_CLASSIFIER_DIAGNOSTICS,
        "dirty_chunks": root / DEFAULT_DIRTY_CHUNKS,
        "documents": root / DEFAULT_DOCUMENTS,
        "dirty_dev_candidates": root / DEFAULT_DIRTY_DEV_CANDIDATES,
        "dirty_canary_candidates": root / DEFAULT_DIRTY_CANARY_CANDIDATES,
        "dirty_dev_baseline": root / DEFAULT_DEV_BASELINE_CASES,
        "dirty_canary_baseline": root / DEFAULT_CANARY_BASELINE_CASES,
        "dirty_assembler": root / DEFAULT_DIRTY_ASSEMBLER,
        "dirty_backbone": root / DEFAULT_DIRTY_BACKBONE,
        "prior_requirement_candidates": root / DEFAULT_PRIOR_REQUIREMENT_CANDIDATES,
        "prior_requirement_manifest": root / DEFAULT_PRIOR_REQUIREMENT_MANIFEST,
        "requirement_embeddings": root / DEFAULT_REQUIREMENT_EMBEDDINGS,
        "temporal_overlay": root / DEFAULT_TEMPORAL_OVERLAY,
        "p1_adjudication": root / DEFAULT_P1_ADJUDICATION,
    }
    inputs = {
        **fixed,
        "clean_chunks": resolve(clean_chunks_path),
        "clean_corpus_manifest": resolve(clean_corpus_manifest_path),
        "clean_bm25_manifest": resolve(bm25_manifest_path),
        "clean_dense_manifest": resolve(dense_manifest_path),
        "clean_dev_candidates": resolve(clean_dev_candidates_path),
        "clean_canary_candidates": resolve(clean_canary_candidates_path),
        "clean_canary_cases": resolve(clean_canary_cases_path),
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    ground_truth = read_jsonl(inputs["ground_truth"])
    dev_rows = read_jsonl(inputs["adaptive_dev"])
    canary_rows = read_jsonl(inputs["downgraded_canary"])
    evaluation_rows = dev_rows + canary_rows
    enumeration = read_jsonl(inputs["enumeration"])
    clean_chunks = read_jsonl(inputs["clean_chunks"])
    dirty_chunks = read_jsonl(inputs["dirty_chunks"])
    clean_dev_candidates = read_jsonl(inputs["clean_dev_candidates"])
    clean_canary_candidates = read_jsonl(inputs["clean_canary_candidates"])

    dirty_recall = candidate_recall(
        dev_rows,
        canary_rows,
        read_jsonl(inputs["dirty_dev_candidates"]),
        read_jsonl(inputs["dirty_canary_candidates"]),
    )
    clean_recall = candidate_recall(
        dev_rows, canary_rows, clean_dev_candidates, clean_canary_candidates
    )

    requirement_cases = build_requirement_cases(
        canary_rows,
        dev_rows,
        enumeration,
        clean_canary_candidates,
        clean_dev_candidates,
        clean_chunks,
    )
    requirement_scores, requirement_latency, requirement_model = run_requirement_model(
        requirement_cases, clean_chunks, device=device
    )
    requirement_results = evaluate_requirement_rows(requirement_cases, requirement_scores)
    assembler_cases = build_assembler_cases(
        canary_rows,
        dev_rows,
        enumeration,
        requirement_results,
        requirement_scores,
        read_jsonl(inputs["dirty_canary_baseline"]),
        read_jsonl(inputs["dirty_dev_baseline"]),
        clean_chunks,
    )
    segment_rows = build_segment_rows(assembler_cases)
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    assembler_scores, assembler_latency, assembler_model = run_segment_reranker(
        assembler_cases, segment_rows, device=device
    )
    assembled = assemble_chunk_diverse_configuration(
        assembler_cases,
        assembler_scores,
        threshold=ASSEMBLER_THRESHOLD,
        k=ASSEMBLER_K,
    )
    assembler_scored = score_cases_v2(assembler_cases, assembled)
    assembler_metrics = aggregate_v2(assembler_scored)
    exact = exact_span_metrics(assembler_cases, assembled)

    attribution = read_jsonl(inputs["attribution"])
    taxonomy = read_jsonl(inputs["taxonomy"])
    backbone = build_backbone_cases(
        ground_truth_rows=ground_truth,
        evaluation_rows=evaluation_rows,
        attribution_rows=attribution,
        enumeration_rows=enumeration,
        prediction_rows=read_jsonl(inputs["classifier_predictions"]),
        classifier_diagnostic_rows=read_jsonl(inputs["classifier_diagnostics"]),
        assembler_rows=assembled,
        chunks=clean_chunks,
    )
    dirty_backbone = read_jsonl(inputs["dirty_backbone"])
    dirty_backbone_metrics = summarize_backbone_arm(dirty_backbone, "arm0")
    clean_backbone_metrics = summarize_backbone_arm(backbone, "arm0")
    dirty_false = _false_full_ids(dirty_backbone)
    clean_false = _false_full_ids(backbone)
    cross_parent = summarize_cross_parent(backbone, taxonomy, "arm0")

    clean_canary_cases = read_jsonl(inputs["clean_canary_cases"])
    dirty_canary_cases = read_jsonl(inputs["dirty_canary_baseline"])
    dirty_canary_temporal_violations = sum(
        len(row["temporal_revision_violations"]) for row in dirty_canary_cases
    )
    dirty_canary_realtime_exposures = sum(
        row["false_realtime_evidence_exposure"] for row in dirty_canary_cases
    )
    canary_temporal_violations = sum(
        len(row["temporal_revision_violations"]) for row in clean_canary_cases
    )
    canary_realtime_exposures = sum(
        row["false_realtime_evidence_exposure"] for row in clean_canary_cases
    )

    artifacts = load_runtime_artifacts(
        root,
        bm25_manifest_path=inputs["clean_bm25_manifest"],
        dense_manifest_path=inputs["clean_dense_manifest"],
        chunks_path=inputs["clean_chunks"],
        documents_path=inputs["documents"],
    )
    prior_manifest = json.loads(
        inputs["prior_requirement_manifest"].read_text(encoding="utf-8")
    )
    federated, federated_scores, federated_cases = _run_clean_federated(
        root=root,
        artifacts=artifacts,
        assembler_cases=assembler_cases,
        clean_chunks=clean_chunks,
        ground_truth=ground_truth,
        evaluation_rows=evaluation_rows,
        attribution_rows=attribution,
        dirty_backbone=dirty_backbone,
        dirty_assembler=read_jsonl(inputs["dirty_assembler"]),
        prior_candidates=read_jsonl(inputs["prior_requirement_candidates"]),
        prior_manifest=prior_manifest,
        requirement_embeddings_path=inputs["requirement_embeddings"],
        temporal_overlay=read_jsonl(inputs["temporal_overlay"]),
        device=device,
    )
    nav_ids = {
        row["case_id"]
        for row in read_jsonl(inputs["p1_adjudication"])
        if row["classification"] == "NAVIGATION_CONTAMINATION"
    }
    clean_federated = {row["case_id"]: row for row in federated_cases}
    nav_behavior = {
        arm: {
            "dirty_p1_false_full": len(nav_ids),
            "clean_false_full": sum(
                clean_federated[case_id][arm]["score"]["false_full_answer"]
                for case_id in nav_ids
            ),
            "resolved": sum(
                not clean_federated[case_id][arm]["score"]["false_full_answer"]
                for case_id in nav_ids
            ),
            "case_ids": sorted(nav_ids),
        }
        for arm in FEDERATED_ARMS
    }
    federated_temporal_violations = sum(
        federated["safety"][arm]["violation_count"] for arm in FEDERATED_ARMS
    )

    dirty_by_id = {row["chunk_id"]: row for row in dirty_chunks}
    clean_by_id = {row["chunk_id"]: row for row in clean_chunks}
    changed_retrieval_rows = sum(
        dirty_by_id[chunk_id]["retrieval_text"]
        != clean_by_id[chunk_id]["retrieval_text"]
        for chunk_id in dirty_by_id
    )

    dirty_grounded = dirty_backbone_metrics["answerable"]["grounded_answer"][
        "successes"
    ]
    clean_grounded = clean_backbone_metrics["answerable"]["grounded_answer"][
        "successes"
    ]
    gates = {
        "grounded_at_least_dirty_73": clean_grounded >= dirty_grounded == 73,
        "false_full_reduced": len(clean_false) < len(dirty_false),
        "new_false_full_zero": len(clean_false - dirty_false) == 0,
        "exact_slice_100_percent": exact["invalid"] == 0,
        "federated_temporal_revision_preview_exposure_zero": federated_temporal_violations
        == 0,
        "no_new_legacy_canary_temporal_violation": canary_temporal_violations
        <= dirty_canary_temporal_violations,
        "no_new_legacy_canary_realtime_exposure": canary_realtime_exposures
        <= dirty_canary_realtime_exposures,
        "reject_11_of_11": clean_backbone_metrics["reject"][
            "correct_abstain_or_reject"
        ]["successes"]
        == 11,
        "realtime_safe_abstain_2_of_2": clean_backbone_metrics["realtime"][
            "safe_abstain"
        ]["successes"]
        == 2,
    }
    decision = "GO_DEV_ONLY_NO_PROMOTION" if all(gates.values()) else "NO_GO"

    evidence_dir = root / "data/v3/evidence"
    router_dir = root / "data/v3/router"
    reports_dir = root / "reports/v3"
    requirement_scores_path, requirement_scores_sha = _freeze_jsonl(
        evidence_dir,
        "corpus_hygiene_requirement_scores",
        requirement_scores,
        lambda row: row["case_id"],
    )
    requirement_results_path, requirement_results_sha = _freeze_jsonl(
        evidence_dir,
        "corpus_hygiene_requirement_results",
        requirement_results,
        lambda row: row["case_id"],
    )
    assembler_scores_path, assembler_scores_sha = _freeze_jsonl(
        evidence_dir,
        "corpus_hygiene_assembler_scores",
        assembler_scores,
        lambda row: row["case_id"],
    )
    assembled_path, assembled_sha = _freeze_jsonl(
        evidence_dir,
        "corpus_hygiene_assembler_cases",
        assembled,
        lambda row: row["case_id"],
    )
    backbone_path, backbone_sha = _freeze_jsonl(
        router_dir,
        "corpus_hygiene_backbone_cases",
        backbone,
        lambda row: (row["dataset"], row["case_id"]),
    )
    combined_federated_scores = [
        row for arm in FEDERATED_ARMS for row in federated_scores[arm]
    ]
    fed_scores_path, fed_scores_sha = _freeze_jsonl(
        evidence_dir,
        "corpus_hygiene_federated_segment_scores",
        combined_federated_scores,
        lambda row: (row["retrieval_arm"], row["case_id"]),
    )
    fed_cases_path, fed_cases_sha = _freeze_jsonl(
        evidence_dir,
        "corpus_hygiene_federated_cases",
        federated_cases,
        lambda row: (row["dataset"], row["case_id"]),
    )

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at,
        "evaluation_role": "development_only_dirty_vs_retrieval_clean_blast_radius",
        "decision": decision,
        "corpus_change": {
            "row_count": len(clean_chunks),
            "changed_retrieval_text_rows": changed_retrieval_rows,
            "non_retrieval_fields_changed": 0,
            "reindexed": True,
        },
        "retrieval_candidate_recall": {
            "dirty": dirty_recall,
            "clean": clean_recall,
        },
        "backbone": {
            "dirty": dirty_backbone_metrics,
            "clean": clean_backbone_metrics,
            "dirty_false_full_case_ids": sorted(dirty_false),
            "clean_false_full_case_ids": sorted(clean_false),
            "new_false_full_case_ids": sorted(clean_false - dirty_false),
            "resolved_false_full_case_ids": sorted(dirty_false - clean_false),
            "cross_parent_clean": cross_parent,
        },
        "assembler": {
            "metrics": assembler_metrics,
            "exact_span_validity": exact,
            "threshold": ASSEMBLER_THRESHOLD,
            "k_distinct_chunks": ASSEMBLER_K,
            "requirement_latency": requirement_latency,
            "segment_latency": assembler_latency,
        },
        "safety": {
            "legacy_canary_dirty_temporal_revision_violations": dirty_canary_temporal_violations,
            "legacy_canary_clean_temporal_revision_violations": canary_temporal_violations,
            "legacy_canary_dirty_false_realtime_evidence_exposures": dirty_canary_realtime_exposures,
            "legacy_canary_clean_false_realtime_evidence_exposures": canary_realtime_exposures,
            "federated_temporal_revision_preview_violations": federated_temporal_violations,
            "interpretation": "the legacy authored-canary router retains its pre-existing 4/5 violations; the post-canary federated temporal gate is the zero-leak hard guard",
        },
        "federated_contamination_recheck": {
            **federated,
            "p1_navigation_cases": nav_behavior,
        },
        "gates": gates,
        "models": {
            "requirement_reranker": requirement_model,
            "assembler_segment_reranker": assembler_model,
            "federated_segment_reranker": {
                "name": MODEL_NAME,
                "revision": MODEL_REVISION,
                "max_length": MAX_LENGTH,
                "batch_size": BATCH_SIZE,
                "device": device,
                "libraries": {
                    "sentence_transformers": sentence_transformers.__version__,
                    "torch": torch.__version__,
                    "transformers": transformers.__version__,
                    "numpy": np.__version__,
                },
            },
        },
        "scope": {
            "search_model_changed": False,
            "planner_changed": False,
            "reranker_logic_changed": False,
            "assembler_logic_changed": False,
            "gold_label_or_question_changed": False,
            "canonical_or_runtime_promoted": False,
            "training": False,
            "frozen_blind_accessed": False,
        },
        "artifacts": {
            "requirement_scores": {"path": _relative(root, requirement_scores_path), "sha256": requirement_scores_sha},
            "requirement_results": {"path": _relative(root, requirement_results_path), "sha256": requirement_results_sha},
            "assembler_scores": {"path": _relative(root, assembler_scores_path), "sha256": assembler_scores_sha},
            "assembler_cases": {"path": _relative(root, assembled_path), "sha256": assembled_sha},
            "backbone_cases": {"path": _relative(root, backbone_path), "sha256": backbone_sha},
            "federated_scores": {"path": _relative(root, fed_scores_path), "sha256": fed_scores_sha},
            "federated_cases": {"path": _relative(root, fed_cases_path), "sha256": fed_cases_sha},
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"corpus_hygiene_remeasurement_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    lines = [
        "# DNF RAG v3 corpus hygiene remeasurement",
        "",
        f"- Decision: **{decision}** (development only; no promotion)",
        f"- Retrieval-only rows changed: {changed_retrieval_rows}/{len(clean_chunks)}",
        f"- Grounded answers: {dirty_grounded}/82 -> {clean_grounded}/82",
        f"- False full answers: {len(dirty_false)}/82 -> {len(clean_false)}/82",
        f"- New false full answers: {len(clean_false - dirty_false)}",
        f"- Exact spans: {exact['valid']}/{exact['total']}",
        f"- Federated temporal violations: {federated_temporal_violations}",
        f"- Legacy canary temporal/realtime (pre-existing): {dirty_canary_temporal_violations}/{dirty_canary_realtime_exposures} -> {canary_temporal_violations}/{canary_realtime_exposures}",
        "",
        "The entire development baseline was replayed because changing retrieval_text required new BM25 and BGE-M3 indexes. Dirty artifacts remain preserved, and this report does not promote the clean corpus.",
        "",
    ]
    markdown_bytes = "\n".join(lines).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"corpus_hygiene_remeasurement_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at,
        "source_commit": _git_head(root),
        "decision": decision,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "artifacts": {
            **report["artifacts"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "gates": gates,
        "scope": report["scope"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/chunks" / f"corpus_hygiene_remeasurement_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    changed = [name for name, path in inputs.items() if file_sha256(path) != before[name]]
    if changed:
        raise RuntimeError(f"Inputs changed during corpus hygiene remeasurement: {changed}")
    return {
        "decision": decision,
        "gates": gates,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "markdown_path": str(markdown_path),
        "markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "grounded_before": dirty_grounded,
        "grounded_after": clean_grounded,
        "false_full_before": len(dirty_false),
        "false_full_after": len(clean_false),
        "lineage_hashes_unchanged": not changed,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Replay the 95-case baseline after retrieval-only corpus cleaning"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--clean-chunks", type=Path, required=True)
    parser.add_argument("--clean-corpus-manifest", type=Path, required=True)
    parser.add_argument("--bm25-manifest", type=Path, required=True)
    parser.add_argument("--dense-manifest", type=Path, required=True)
    parser.add_argument("--clean-dev-candidates", type=Path, required=True)
    parser.add_argument("--clean-canary-candidates", type=Path, required=True)
    parser.add_argument("--clean-canary-cases", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--evaluated-at", default=datetime.now(timezone.utc).isoformat())
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        clean_chunks_path=args.clean_chunks,
        clean_corpus_manifest_path=args.clean_corpus_manifest,
        bm25_manifest_path=args.bm25_manifest,
        dense_manifest_path=args.dense_manifest,
        clean_dev_candidates_path=args.clean_dev_candidates,
        clean_canary_candidates_path=args.clean_canary_candidates,
        clean_canary_cases_path=args.clean_canary_cases,
        device=args.device,
        evaluated_at=args.evaluated_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
