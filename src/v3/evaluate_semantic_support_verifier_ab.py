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
from huggingface_hub import snapshot_download
from sentence_transformers import CrossEncoder
from transformers import AutoModelForSequenceClassification, AutoTokenizer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_router_backbone_ab import _ratio
from src.v3.score_entailment_pilot import normalize_id2label


EVALUATOR_VERSION = "semantic-support-verifier-ab-v3.1.0"
PAIR_SCHEMA_VERSION = "semantic-support-pair-score-v3.1"
CASE_SCHEMA_VERSION = "semantic-support-verifier-case-v3.1"
GRID_SCHEMA_VERSION = "semantic-support-verifier-grid-v3.1"
REPORT_SCHEMA_VERSION = "semantic-support-verifier-report-v3.1"
MANIFEST_SCHEMA_VERSION = "semantic-support-verifier-manifest-v3.1"
LATENCY_SCHEMA_VERSION = "semantic-support-verifier-latency-v3.1"

BGE_MODEL = "BAAI/bge-reranker-v2-m3"
BGE_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
NLI_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
NLI_REVISION = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
NLI_CACHE_DIR = "mdeberta_v3_base_mnli_xnli_8adb042"
MAX_LENGTH = 512
BGE_BATCH_SIZE = 8
NLI_BATCH_SIZE = 8
SCORE_DECIMALS = 8
BGE_BARS = (0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
NLI_BARS = (0.0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99)

DEFAULT_GROUND_TRUTH = Path(
    "data/v3/evaluation/semantic_answerability_ground_truth_"
    "53cd8ae72ad4ee2f7c9b1d4370991ad74b5044d154e3657fd2008f45f71fe609.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_ASSEMBLER = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_ASSEMBLER_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_"
    "9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json"
)
DEFAULT_BACKBONE = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_BACKBONE_MANIFEST = Path(
    "data/v3/router/router_backbone_answer_source_ab_manifest_"
    "1dc7f770f17b5426ef434b8a10ecd7395b6705cb0cf9a4626bc4ca8527d81e29.json"
)
DEFAULT_TAXONOMY = Path(
    "data/v3/router/routing_bottleneck_taxonomy_"
    "905182d088873485059415d4dcbda95f15db42c091392c7b3d21dfeefd734679.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/semantic_support_verifier_ab.md")


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


def requirement_text(requirement: dict[str, Any]) -> str:
    return (
        f"{requirement['subject']}의 {requirement['relation']} "
        f"({requirement['value_type']})"
    )


def bge_query(requirement: dict[str, Any]) -> str:
    return f"요구: {requirement_text(requirement)}\n이 요구에 직접 답하는 근거"


def nli_hypothesis(requirement: dict[str, Any], span_text: str) -> str:
    return (
        f"{requirement_text(requirement)}에 대한 직접 답은 다음과 같습니다: "
        f"{span_text}"
    )


def prepare_pairs(
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    if len(enumerations) != 95 or set(enumerations) != set(assemblers):
        raise RuntimeError("Verifier requires the frozen aligned 95 cases")
    output = []
    for case_id in sorted(enumerations):
        enumeration = enumerations[case_id]
        assembler = assemblers[case_id]
        requirements = enumeration["requirements"]
        decisions = assembler["decisions"]
        if len(requirements) != len(decisions):
            raise RuntimeError(f"Requirement/decision count mismatch: {case_id}")
        for index, (requirement, decision) in enumerate(
            zip(requirements, decisions, strict=True), 1
        ):
            if requirement["requirement_id"] != decision["requirement_id"]:
                raise RuntimeError(f"Requirement ID mismatch: {case_id}/{index}")
            for span in decision["spans"]:
                pair_key = {
                    "case_id": case_id,
                    "requirement_index": index,
                    "span_id": span["span_id"],
                    "chunk_id": span["chunk_id"],
                }
                output.append(
                    {
                        "pair_id": "support_pair_sha256_"
                        + _sha256_bytes(_canonical_json_bytes(pair_key)),
                        "case_id": case_id,
                        "dataset": assembler["dataset"],
                        "requirement_index": index,
                        "requirement_id": requirement["requirement_id"],
                        "requirement": requirement,
                        "span": span,
                    }
                )
    return sorted(output, key=lambda row: row["pair_id"])


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * quantile)))
    return round(ordered[index], 3)


def _model_files(model_dir: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in model_dir.rglob("*") if item.is_file()):
        files.append(
            {
                "path": path.relative_to(model_dir).as_posix(),
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return {
        "snapshot_file_count": len(files),
        "snapshot_content_sha256": _sha256_bytes(_canonical_json_bytes(files)),
        "weight_files": [
            row for row in files if row["path"].endswith((".safetensors", ".bin"))
        ],
    }


def score_bge(
    pairs: list[dict[str, Any]], *, device: str
) -> tuple[list[float], dict[str, Any], dict[str, Any]]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    snapshot = Path(
        snapshot_download(
            BGE_MODEL,
            revision=BGE_REVISION,
            local_files_only=True,
        )
    )
    load_started = time.perf_counter()
    model = CrossEncoder(
        BGE_MODEL,
        revision=BGE_REVISION,
        max_length=MAX_LENGTH,
        device=device,
        local_files_only=True,
    )
    load_seconds = time.perf_counter() - load_started
    model_pairs = [
        (bge_query(row["requirement"]), row["span"]["text"]) for row in pairs
    ]
    started = time.perf_counter()
    values = np.asarray(
        model.predict(
            model_pairs,
            batch_size=BGE_BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
        ),
        dtype=np.float64,
    ).reshape(-1)
    if device == "cuda":
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    if not np.isfinite(values).all() or len(values) != len(pairs):
        raise RuntimeError("BGE verifier scores are missing or invalid")
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return (
        values.tolist(),
        {
            "component": "bge_support_pair",
            "model_load_seconds": round(load_seconds, 6),
            "inference_seconds": round(inference_seconds, 6),
            "pair_count": len(pairs),
            "pairs_per_second": round(len(pairs) / inference_seconds, 6),
        },
        {
            "component": "bge_support_pair",
            "name": BGE_MODEL,
            "revision": BGE_REVISION,
            "max_length": MAX_LENGTH,
            "batch_size": BGE_BATCH_SIZE,
            **_model_files(snapshot),
        },
    )


def score_nli(
    pairs: list[dict[str, Any]], *, device: str, model_cache_root: Path
) -> tuple[list[float], dict[str, Any], dict[str, Any]]:
    model_dir = model_cache_root / NLI_CACHE_DIR
    if not model_dir.is_dir():
        raise RuntimeError(f"Local NLI snapshot is missing: {model_dir}")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir, local_files_only=True, use_fast=False
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir, local_files_only=True
    )
    labels = normalize_id2label(model.config.id2label)
    entailment_index = next(
        index for index, label in labels.items() if label == "entailment"
    )
    model.to(device)
    if device == "cuda":
        model.half()
    model.eval()
    load_seconds = time.perf_counter() - load_started
    probability_rows = []
    started = time.perf_counter()
    with torch.inference_mode():
        for offset in range(0, len(pairs), NLI_BATCH_SIZE):
            batch = pairs[offset : offset + NLI_BATCH_SIZE]
            encoded = tokenizer(
                [row["span"]["text"] for row in batch],
                [nli_hypothesis(row["requirement"], row["span"]["text"]) for row in batch],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            encoded.pop("token_type_ids", None)
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits.float()
            probability_rows.extend(
                torch.softmax(logits, dim=-1)[:, entailment_index].cpu().tolist()
            )
    if device == "cuda":
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    if len(probability_rows) != len(pairs):
        raise RuntimeError("NLI verifier scores are missing")
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return (
        probability_rows,
        {
            "component": "mdeberta_nli_support",
            "model_load_seconds": round(load_seconds, 6),
            "inference_seconds": round(inference_seconds, 6),
            "pair_count": len(pairs),
            "pairs_per_second": round(len(pairs) / inference_seconds, 6),
        },
        {
            "component": "mdeberta_nli_support",
            "name": NLI_MODEL,
            "revision": NLI_REVISION,
            "max_length": MAX_LENGTH,
            "batch_size": NLI_BATCH_SIZE,
            **_model_files(model_dir),
        },
    )


def attach_scores(
    pairs: list[dict[str, Any]],
    bge_scores: list[float],
    nli_scores: list[float],
) -> list[dict[str, Any]]:
    if len(pairs) != len(bge_scores) or len(pairs) != len(nli_scores):
        raise RuntimeError("Pair score lengths differ")
    output = []
    for row, bge_score, nli_score in zip(
        pairs, bge_scores, nli_scores, strict=True
    ):
        output.append(
            {
                "score_schema_version": PAIR_SCHEMA_VERSION,
                "pair_id": row["pair_id"],
                "case_id": row["case_id"],
                "dataset": row["dataset"],
                "requirement_index": row["requirement_index"],
                "requirement_id": row["requirement_id"],
                "span_id": row["span"]["span_id"],
                "chunk_id": row["span"]["chunk_id"],
                "bge_support_score": round(float(bge_score), SCORE_DECIMALS),
                "nli_entailment_probability": round(float(nli_score), SCORE_DECIMALS),
                "gold_ids_available_to_models": False,
            }
        )
    return sorted(output, key=lambda row: row["pair_id"])


def _score_lookup(score_rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    return {row["pair_id"]: float(row[key]) for row in score_rows}


def filter_decisions(
    pair_rows: list[dict[str, Any]],
    assembler_decisions: list[dict[str, Any]],
    baseline_supported_indices: set[int],
    score_by_pair_id: dict[str, float],
    *,
    bar: float,
) -> list[dict[str, Any]]:
    pair_ids = {
        (row["requirement_index"], row["span"]["span_id"]): row["pair_id"]
        for row in pair_rows
    }
    output = []
    for index, decision in enumerate(assembler_decisions, 1):
        kept = []
        if index in baseline_supported_indices:
            for span in decision["spans"]:
                pair_id = pair_ids[(index, span["span_id"])]
                if score_by_pair_id[pair_id] >= bar:
                    kept.append(span)
        output.append(
            {
                "requirement_id": decision["requirement_id"],
                "status": "supported_exact" if kept else "unsupported",
                "spans": kept,
            }
        )
    return output


def _shared_parent(
    decisions: list[dict[str, Any]], chunk_to_parent: dict[str, str]
) -> bool:
    parent_sets = [
        {chunk_to_parent[span["chunk_id"]] for span in decision["spans"]}
        for decision in decisions
    ]
    if len(parent_sets) < 2 or any(not values for values in parent_sets):
        return True
    return bool(set.intersection(*parent_sets))


def simulate_filtered_arm(
    baseline_arm: dict[str, Any],
    decisions: list[dict[str, Any]],
    chunk_to_parent: dict[str, str],
) -> dict[str, Any]:
    if baseline_arm["safety_reason"] is not None:
        return {key: value for key, value in baseline_arm.items() if key != "score"}
    kept = [
        (index, decision)
        for index, decision in enumerate(decisions, 1)
        if decision["status"] == "supported_exact"
    ]
    supported = [index for index, _ in kept]
    unsupported = [
        index for index in range(1, len(decisions) + 1) if index not in supported
    ]
    cited = sorted(
        {
            span["chunk_id"]
            for _, decision in kept
            for span in decision["spans"]
        }
    )
    if not kept:
        response_mode = "abstain"
        route_action = "abstain"
        cross_parent = False
    else:
        response_mode = "full_answer" if len(kept) == len(decisions) else "partial_answer"
        kept_decisions = [decision for _, decision in kept]
        cross_parent = (
            len(kept_decisions) >= 2
            and len(kept_decisions) == len(decisions)
            and not _shared_parent(kept_decisions, chunk_to_parent)
        )
        route_action = "decompose_candidate" if cross_parent else "retrieve"
    return {
        "placement": "post_assembler_semantic_support_verifier",
        "route_action": route_action,
        "response_mode": response_mode,
        "safety_reason": None,
        "supported_requirement_indices": supported,
        "unsupported_requirement_indices": unsupported,
        "classifier_non_docs": [],
        "cited_chunk_ids": cited,
        "cross_parent_candidate": cross_parent,
    }


def score_arm(
    arm: dict[str, Any], *, target: str, evidence_groups: list[dict[str, Any]]
) -> dict[str, Any]:
    cited = set(arm["cited_chunk_ids"])
    hits = [
        bool(cited & set(group["acceptable_chunk_ids"])) for group in evidence_groups
    ]
    has_answer = arm["response_mode"] in {"full_answer", "partial_answer"}
    all_groups = bool(hits) and all(hits)
    some_groups = any(hits)
    return {
        "group_hit_count": sum(hits),
        "evidence_group_count": len(hits),
        "all_groups_cited": all_groups,
        "answerable_overreject": target == "answerable_docs" and not has_answer,
        "grounded_answer": target == "answerable_docs" and has_answer and all_groups,
        "honest_partial": (
            target == "answerable_docs"
            and arm["response_mode"] == "partial_answer"
            and some_groups
            and not all_groups
        ),
        "false_full_answer": (
            target == "answerable_docs"
            and arm["response_mode"] == "full_answer"
            and not all_groups
        ),
        "false_partial": (
            target == "answerable_docs"
            and arm["response_mode"] == "partial_answer"
            and all_groups
        ),
        "reject_correct": target == "reject" and arm["route_action"] in {"reject", "abstain"},
        "realtime_safe_abstain": (
            target == "realtime_api"
            and not has_answer
            and arm["route_action"] in {"reject", "abstain"}
        ),
        "realtime_static_exposure": target == "realtime_api" and has_answer,
    }


def evaluate_bar(
    *,
    component: str,
    bar: float,
    pair_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    backbone_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    taxonomy_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    score_key = (
        "bge_support_score"
        if component == "bge_support_pair"
        else "nli_entailment_probability"
    )
    scores = _score_lookup(score_rows, score_key)
    pairs_by_case: dict[str, list[dict[str, Any]]] = {}
    for row in pair_rows:
        pairs_by_case.setdefault(row["case_id"], []).append(row)
    assemblers = {row["case_id"]: row for row in assembler_rows}
    backbones = {row["case_id"]: row for row in backbone_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunk_to_parent = {row["chunk_id"]: row["parent_document_id"] for row in chunks}
    output = []
    for case_id in sorted(backbones):
        baseline = backbones[case_id]
        assembler = assemblers[case_id]
        supported = set(baseline["arm0"]["supported_requirement_indices"])
        decisions = filter_decisions(
            pairs_by_case.get(case_id, []),
            assembler["decisions"],
            supported,
            scores,
            bar=bar,
        )
        arm = simulate_filtered_arm(baseline["arm0"], decisions, chunk_to_parent)
        scored = score_arm(
            arm,
            target=baseline["answerability_target"],
            evidence_groups=evaluations[case_id]["evidence_groups"],
        )
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": baseline["dataset"],
                "answerability_target": baseline["answerability_target"],
                "component": component,
                "bar": bar,
                "decisions": decisions,
                "arm": {**arm, "score": scored},
                "gold_ids_available_to_verifier": False,
                "gold_ids_used_for_scoring_only": True,
            }
        )

    docs = [row for row in output if row["answerability_target"] == "answerable_docs"]
    reject = [row for row in output if row["answerability_target"] == "reject"]
    realtime = [row for row in output if row["answerability_target"] == "realtime_api"]
    cross_ids = {
        row["case_id"] for row in taxonomy_rows if row["failure_type"] == "DECOMPOSE_MISS"
    }
    pair_gold: dict[str, bool] = {}
    for evaluation in evaluation_rows:
        acceptable = {
            chunk_id
            for group in evaluation["evidence_groups"]
            for chunk_id in group["acceptable_chunk_ids"]
        }
        for pair in pairs_by_case.get(evaluation["dev_id"], []):
            pair_gold[pair["pair_id"]] = pair["span"]["chunk_id"] in acceptable
    predicted = {pair_id: value >= bar for pair_id, value in scores.items()}
    tp = sum(predicted[pair_id] and label for pair_id, label in pair_gold.items())
    fp = sum(predicted[pair_id] and not label for pair_id, label in pair_gold.items())
    fn = sum(not predicted[pair_id] and label for pair_id, label in pair_gold.items())
    pair_precision = tp / (tp + fp) if tp + fp else 0.0
    pair_recall = tp / (tp + fn) if tp + fn else 0.0
    metrics = {
        "component": component,
        "bar": bar,
        "answerable": {
            "grounded_answer": _ratio(sum(row["arm"]["score"]["grounded_answer"] for row in docs), len(docs)),
            "false_full_answer": _ratio(sum(row["arm"]["score"]["false_full_answer"] for row in docs), len(docs)),
            "honest_partial": _ratio(sum(row["arm"]["score"]["honest_partial"] for row in docs), len(docs)),
            "overreject": _ratio(sum(row["arm"]["score"]["answerable_overreject"] for row in docs), len(docs)),
            "false_partial": _ratio(sum(row["arm"]["score"]["false_partial"] for row in docs), len(docs)),
        },
        "reject_correct": _ratio(sum(row["arm"]["score"]["reject_correct"] for row in reject), len(reject)),
        "realtime_safe_abstain": _ratio(sum(row["arm"]["score"]["realtime_safe_abstain"] for row in realtime), len(realtime)),
        "realtime_static_exposure": _ratio(sum(row["arm"]["score"]["realtime_static_exposure"] for row in realtime), len(realtime)),
        "cross_parent_trigger": _ratio(sum(row["arm"]["cross_parent_candidate"] for row in output if row["case_id"] in cross_ids), len(cross_ids)),
        "pair_proxy": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": round(pair_precision, 8),
            "recall": round(pair_recall, 8),
            "limitation": "question-level acceptable chunk membership; no requirement-group mapping",
        },
        "retained_span_count": sum(len(decision["spans"]) for row in output for decision in row["decisions"]),
    }
    return output, metrics


def operating_point_pass(metrics: dict[str, Any]) -> bool:
    return all(
        (
            metrics["answerable"]["grounded_answer"]["successes"] == 73,
            metrics["answerable"]["false_full_answer"]["successes"] <= 7,
            metrics["reject_correct"]["successes"] == 11,
            metrics["realtime_safe_abstain"]["successes"] == 2,
            metrics["realtime_static_exposure"]["successes"] == 0,
        )
    )


def select_operating_point(grid_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    passing = [row for row in grid_rows if operating_point_pass(row)]
    if not passing:
        return None
    return min(
        passing,
        key=lambda row: (
            row["answerable"]["false_full_answer"]["successes"],
            -row["cross_parent_trigger"]["successes"],
            -row["pair_proxy"]["recall"],
            row["bar"],
        ),
    )


def diagnostic_points(grid_rows: list[dict[str, Any]]) -> dict[str, Any]:
    guard_preserving = [
        row
        for row in grid_rows
        if row["answerable"]["grounded_answer"]["successes"] == 73
        and row["reject_correct"]["successes"] == 11
        and row["realtime_safe_abstain"]["successes"] == 2
        and row["realtime_static_exposure"]["successes"] == 0
    ]
    reduction_points = [
        row
        for row in grid_rows
        if row["answerable"]["false_full_answer"]["successes"] <= 7
    ]
    return {
        "best_guard_preserving": (
            min(
                guard_preserving,
                key=lambda row: (
                    row["answerable"]["false_full_answer"]["successes"],
                    -row["pair_proxy"]["recall"],
                    row["bar"],
                ),
            )
            if guard_preserving
            else None
        ),
        "closest_minimum_reduction": (
            max(
                reduction_points,
                key=lambda row: (
                    row["answerable"]["grounded_answer"]["successes"],
                    -row["answerable"]["overreject"]["successes"],
                    row["pair_proxy"]["recall"],
                    -row["bar"],
                ),
            )
            if reduction_points
            else None
        ),
    }


def _markdown(report: dict[str, Any]) -> bytes:
    lines = [
        "# Lightweight semantic-support verifier A/B",
        "",
        f"- recommendation: **{report['decision']['recommendation']}**",
        f"- baseline: grounded 73/82, false-full 9/82, reject 11/11, realtime safe-abstain 2/2",
        "",
        "| component | bar | grounded | false-full | honest partial | cross-parent | reject | realtime safe | pair P/R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for component in ("bge_support_pair", "mdeberta_nli_support"):
        selected = report["components"][component]["selected_operating_point"]
        if selected is None:
            lines.append(f"| {component} | none | - | - | - | - | - | - | - |")
            continue
        lines.append(
            "| {} | {} | {}/82 | {}/82 | {}/82 | {}/2 | {}/11 | {}/2 | {:.3f}/{:.3f} |".format(
                component,
                selected["bar"],
                selected["answerable"]["grounded_answer"]["successes"],
                selected["answerable"]["false_full_answer"]["successes"],
                selected["answerable"]["honest_partial"]["successes"],
                selected["cross_parent_trigger"]["successes"],
                selected["reject_correct"]["successes"],
                selected["realtime_safe_abstain"]["successes"],
                selected["pair_proxy"]["precision"],
                selected["pair_proxy"]["recall"],
            )
        )
    lines.extend(
        [
            "",
            "## Full fixed-bar curve",
            "",
            "| component | bar | grounded | false-full | honest partial | overreject | cross-parent | pair precision | pair recall |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for component in ("bge_support_pair", "mdeberta_nli_support"):
        for row in report["components"][component]["curve"]:
            lines.append(
                "| {} | {} | {}/82 | {}/82 | {}/82 | {}/82 | {}/2 | {:.4f} | {:.4f} |".format(
                    component,
                    row["bar"],
                    row["answerable"]["grounded_answer"]["successes"],
                    row["answerable"]["false_full_answer"]["successes"],
                    row["answerable"]["honest_partial"]["successes"],
                    row["answerable"]["overreject"]["successes"],
                    row["cross_parent_trigger"]["successes"],
                    row["pair_proxy"]["precision"],
                    row["pair_proxy"]["recall"],
                )
            )
    lines.extend(
        [
            "",
            "The pair P/R curve is a scoring-only question-level acceptable-chunk proxy, not a requirement-group gold mapping.",
            "No canonical/runtime promotion, sealed run, training, keyword rule, or answer-source classifier change occurred.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path, *, device: str, model_cache_root: Path
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "planner_enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": root / DEFAULT_ASSEMBLER,
        "assembler_manifest": root / DEFAULT_ASSEMBLER_MANIFEST,
        "router_backbone_cases": root / DEFAULT_BACKBONE,
        "router_backbone_manifest": root / DEFAULT_BACKBONE_MANIFEST,
        "routing_taxonomy": root / DEFAULT_TAXONOMY,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in input_paths.items()}
    assembler_manifest = json.loads(input_paths["assembler_manifest"].read_text(encoding="utf-8"))
    if assembler_manifest["artifacts"]["cases"]["sha256"] != before["assembler_cases"]:
        raise RuntimeError("Assembler lineage mismatch")
    backbone_manifest = json.loads(input_paths["router_backbone_manifest"].read_text(encoding="utf-8"))
    if backbone_manifest["artifacts"]["cases"]["sha256"] != before["router_backbone_cases"]:
        raise RuntimeError("Router backbone lineage mismatch")

    enumeration_rows = read_jsonl(input_paths["planner_enumeration"])
    assembler_rows = read_jsonl(input_paths["assembler_cases"])
    pair_inputs = prepare_pairs(enumeration_rows, assembler_rows)
    measured_at = datetime.now(timezone.utc).isoformat()
    bge_values, bge_latency, bge_meta = score_bge(pair_inputs, device=device)
    nli_values, nli_latency, nli_meta = score_nli(
        pair_inputs, device=device, model_cache_root=model_cache_root
    )
    score_rows = attach_scores(pair_inputs, bge_values, nli_values)

    evaluation_rows = read_jsonl(input_paths["adaptive_dev"]) + read_jsonl(input_paths["downgraded_canary"])
    backbone_rows = read_jsonl(input_paths["router_backbone_cases"])
    taxonomy_rows = read_jsonl(input_paths["routing_taxonomy"])
    chunks = read_jsonl(input_paths["chunks"])
    grid_rows = []
    cases_by_config: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for component, bars in (
        ("bge_support_pair", BGE_BARS),
        ("mdeberta_nli_support", NLI_BARS),
    ):
        for bar in bars:
            cases, metrics = evaluate_bar(
                component=component,
                bar=bar,
                pair_rows=pair_inputs,
                score_rows=score_rows,
                assembler_rows=assembler_rows,
                backbone_rows=backbone_rows,
                evaluation_rows=evaluation_rows,
                taxonomy_rows=taxonomy_rows,
                chunks=chunks,
            )
            cases_by_config[(component, bar)] = cases
            grid_rows.append({"grid_schema_version": GRID_SCHEMA_VERSION, **metrics})
    selected = {
        component: select_operating_point(
            [row for row in grid_rows if row["component"] == component]
        )
        for component in ("bge_support_pair", "mdeberta_nli_support")
    }
    passing = [value for value in selected.values() if value is not None]
    recommended = (
        min(
            passing,
            key=lambda row: (
                row["answerable"]["false_full_answer"]["successes"],
                -row["cross_parent_trigger"]["successes"],
                -row["pair_proxy"]["recall"],
            ),
        )
        if passing
        else None
    )
    selected_cases = (
        cases_by_config[(recommended["component"], recommended["bar"])]
        if recommended is not None
        else []
    )

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    score_bytes = _serialize_jsonl(score_rows, lambda row: row["pair_id"])
    score_sha = _sha256_bytes(score_bytes)
    score_path = evidence_dir / f"semantic_support_verifier_scores_{score_sha}.jsonl"
    write_immutable(score_path, score_bytes)
    grid_bytes = _serialize_jsonl(
        grid_rows, lambda row: (row["component"], row["bar"])
    )
    grid_sha = _sha256_bytes(grid_bytes)
    grid_path = evidence_dir / f"semantic_support_verifier_grid_{grid_sha}.jsonl"
    write_immutable(grid_path, grid_bytes)
    case_bytes = _serialize_jsonl(selected_cases, lambda row: row["case_id"])
    case_sha = _sha256_bytes(case_bytes)
    case_path = evidence_dir / f"semantic_support_verifier_cases_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    latency = {
        "latency_schema_version": LATENCY_SCHEMA_VERSION,
        "measured_at": measured_at,
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "components": [bge_latency, nli_latency],
        "observational_not_reproducibility_input": True,
    }
    latency_bytes = _canonical_json_bytes(latency)
    latency_sha = _sha256_bytes(latency_bytes)
    latency_path = reports_dir / f"semantic_support_verifier_latency_{latency_sha}.json"
    write_immutable(latency_path, latency_bytes)

    components = {}
    for component in ("bge_support_pair", "mdeberta_nli_support"):
        component_rows = [row for row in grid_rows if row["component"] == component]
        components[component] = {
            "selected_operating_point": selected[component],
            "gate_pass": selected[component] is not None,
            "diagnostic_points": diagnostic_points(component_rows),
            "curve": component_rows,
        }
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_pairwise_support_ab_no_promotion",
        "artifact_lineage": {
            "supersedes_preliminary_report_sha256": "08d869a78106ad7136bbc01291843c22e20690d8d74b4871fdfe03cc21ba584b",
            "supersedes_preliminary_manifest_sha256": "25df82ce94fe26dd346f547c15181f76d3d426ff94992cb9705fa40419b70826",
            "reason": "adds the full predeclared bar curve and nearest unsafe tradeoff to the human-readable report",
            "preliminary_artifacts_deleted": False,
        },
        "baseline": {
            "grounded_answer": _ratio(73, 82),
            "false_full_answer": _ratio(9, 82),
            "reject_correct": _ratio(11, 11),
            "realtime_safe_abstain": _ratio(2, 2),
            "cross_parent_trigger": _ratio(0, 2),
        },
        "components": components,
        "decision": {
            "recommendation": (
                f"ADOPT_RECOMMENDATION_{recommended['component']}"
                if recommended is not None
                else "REJECT_BOTH_VERIFIERS_NO_SAFE_OPERATING_POINT"
            ),
            "selected_component": recommended["component"] if recommended else None,
            "selected_bar": recommended["bar"] if recommended else None,
            "canonical_or_runtime_promotion": False,
        },
        "gate": {
            "grounded_answer_exactly_73": True,
            "false_full_minimum_reduction": 2,
            "reject_correct_exactly_11": True,
            "realtime_safe_abstain_exactly_2": True,
            "realtime_static_exposure_zero": True,
        },
        "models": [bge_meta, nli_meta],
        "latency": {
            "artifact_path": _relative(root, latency_path),
            "artifact_sha256": latency_sha,
            "components": [bge_latency, nli_latency],
        },
        "artifacts": {
            "scores": {"path": _relative(root, score_path), "sha256": score_sha, "row_count": len(score_rows)},
            "grid": {"path": _relative(root, grid_path), "sha256": grid_sha, "row_count": len(grid_rows)},
            "selected_cases": {"path": _relative(root, case_path), "sha256": case_sha, "row_count": len(selected_cases)},
        },
        "pair_proxy_limit": "acceptable chunk membership is question-level, not requirement-group gold",
        "known_model_limit": "NLI receives a templated slot-plus-extracted-value claim; task transfer is diagnostic only",
        "scope": {
            "canonical_or_runtime_promoted": False,
            "sealed_canary_run": False,
            "training_run": False,
            "answer_source_classifier_changed": False,
            "keyword_or_regex_rules_added": 0,
            "planner_retrieval_reranker_assembler_changed": False,
            "frozen_blind_accessed": False,
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in input_paths.items()
        },
        "source_commit": _git_head(root),
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"semantic_support_verifier_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"semantic_support_verifier_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": report["inputs"],
        "models": report["models"],
        "scoring_contract": {
            "bge_pair": "support-oriented requirement query, exact span",
            "nli_pair": "premise=exact span, hypothesis=atomic requirement plus proposed exact value",
            "gold_ids_available_to_models": False,
            "bars": {"bge": BGE_BARS, "nli": NLI_BARS},
        },
        "artifacts": {
            **report["artifacts"],
            "latency": {"path": _relative(root, latency_path), "sha256": latency_sha},
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "libraries": {
            "numpy": np.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "source_commit": report["source_commit"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"semantic_support_verifier_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    after = {name: file_sha256(path) for name, path in input_paths.items()}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise RuntimeError(f"Inputs changed during verifier A/B: {changed}")
    return {
        "decision": report["decision"],
        "scores_path": str(score_path),
        "scores_sha256": score_sha,
        "grid_path": str(grid_path),
        "grid_sha256": grid_sha,
        "cases_path": str(case_path),
        "cases_sha256": case_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "latency_path": str(latency_path),
        "latency_sha256": latency_sha,
        "input_hash_mismatch_count": 0,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run lightweight semantic support verifier A/B")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument(
        "--model-cache-root",
        type=Path,
        default=Path.home() / ".cache/dnf_v3_models",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        device=args.device,
        model_cache_root=args.model_cache_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
