from __future__ import annotations

import argparse
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
from huggingface_hub import snapshot_download
from sentence_transformers import CrossEncoder

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.rerank_evidence import (
    DEFAULT_DEPTH,
    FALLBACK_DEPTH,
    LOW_CONFIDENCE_THRESHOLD,
    MULTI_EVIDENCE_MARKERS,
    RERANK_SELECTOR_VERSION,
    selection_depth,
)
from src.v3.score_evidence_reranker import (
    BATCH_SIZE,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
)


EVALUATOR_VERSION = "requirement-aware-reranker-pilot-v3.0"
SCORE_SCHEMA_VERSION = "requirement-aware-reranker-score-v3.0"
RESULT_SCHEMA_VERSION = "requirement-aware-reranker-result-v3.0"
MANIFEST_SCHEMA_VERSION = "requirement-aware-reranker-manifest-v3.0"
REPORT_SCHEMA_VERSION = "requirement-aware-reranker-report-v3.0"
LATENCY_SCHEMA_VERSION = "requirement-aware-reranker-latency-v3.0"

DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY_CANDIDATES = Path(
    "data/v3/evaluation/authored_canary_reranker_scores_"
    "589eb3b27a7c6757bee3b4d393f27a01c5dd59b0bb85af7f0331ee2601cf517e.jsonl"
)
DEFAULT_DEV_CANDIDATES = Path(
    "data/v3/evidence/evidence_reranker_scores_"
    "ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl"
)
DEFAULT_CANARY_MANIFEST = Path(
    "data/v3/evaluation/authored_canary_first_run_manifest_"
    "4a2aef81660a13b113ab63a3739126afcddcb6b0b60f2af740becf3bfbdd93dd.json"
)
DEFAULT_DEV_RERANKER_MANIFEST = Path(
    "data/v3/evidence/evidence_reranker_manifest_"
    "ad6b3f074d8f6edf848c0129d0ea3d8de1c9438aa3de98dde0bfac0fb7a2f26c.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/requirement_aware_reranker_pilot.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def requirement_text(requirement: dict[str, Any]) -> str:
    return " ".join(
        part.strip()
        for part in (str(requirement["subject"]), str(requirement["relation"]))
        if part.strip()
    )


def _normalize_candidates(row: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for fallback_rank, candidate in enumerate(row.get("candidates", []), 1):
        original_rank = int(
            candidate.get(
                "retrieval_rank", candidate.get("selected_rank", fallback_rank)
            )
        )
        output.append(
            {
                "chunk_id": candidate["chunk_id"],
                "original_rank": original_rank,
                "question_reranker_score": float(candidate["reranker_score"]),
            }
        )
    if len({row["chunk_id"] for row in output}) != len(output):
        raise RuntimeError("Duplicate candidate chunk in one question")
    return sorted(output, key=lambda item: (item["original_rank"], item["chunk_id"]))


def build_cases(
    canary_rows: list[dict[str, Any]],
    dev_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    canary_candidate_rows: list[dict[str, Any]],
    dev_candidate_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enumeration_by_id = {row["case_id"]: row for row in enumeration_rows}
    chunk_ids = {row["chunk_id"] for row in chunks}
    if len(enumeration_by_id) != len(enumeration_rows):
        raise RuntimeError("Duplicate enumeration case_id")

    output = []
    for dataset, gold_rows, candidate_rows in (
        ("downgraded_canary_32", canary_rows, canary_candidate_rows),
        ("adaptive_dev_63", dev_rows, dev_candidate_rows),
    ):
        candidates_by_id = {row["dev_id"]: row for row in candidate_rows}
        gold_ids = {row["dev_id"] for row in gold_rows}
        if set(candidates_by_id) != gold_ids:
            raise RuntimeError(f"Candidate IDs differ from {dataset} gold IDs")
        for gold in gold_rows:
            case_id = gold["dev_id"]
            enumeration = enumeration_by_id.get(case_id)
            if enumeration is None:
                raise RuntimeError(f"Missing clean enumeration: {case_id}")
            candidates = _normalize_candidates(candidates_by_id[case_id])
            unknown = {row["chunk_id"] for row in candidates} - chunk_ids
            if unknown:
                raise RuntimeError(f"Unknown candidate chunks: {sorted(unknown)}")
            output.append(
                {
                    "case_id": case_id,
                    "dataset": dataset,
                    "question": gold["question"],
                    "source_ids": sorted(set(gold.get("source_ids", []))),
                    "gold_answerability": gold.get("answerability"),
                    "evidence_groups": gold.get("evidence_groups", []),
                    "requirements": enumeration["requirements"],
                    "candidates": candidates,
                }
            )
    if len(output) != 95 or len(enumeration_by_id) != 95:
        raise RuntimeError("Requirement reranker pilot requires the frozen 32+63")
    if {row["case_id"] for row in output} != set(enumeration_by_id):
        raise RuntimeError("Enumeration contains IDs outside the 32+63 population")
    return sorted(output, key=lambda row: row["case_id"])


def prepare_model_pairs(
    cases: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    requests = []
    for case in cases:
        for requirement_index, requirement in enumerate(case["requirements"], 1):
            query = requirement_text(requirement)
            requests.append(
                {
                    "case_id": case["case_id"],
                    "requirement_index": requirement_index,
                    "requirement_id": requirement["requirement_id"],
                    "requirement_text": query,
                    "pairs": [
                        (query, chunks_by_id[candidate["chunk_id"]]["retrieval_text"])
                        for candidate in case["candidates"]
                    ],
                    "candidate_ids": [
                        candidate["chunk_id"] for candidate in case["candidates"]
                    ],
                }
            )
    return requests


def attach_requirement_scores(
    cases: list[dict[str, Any]],
    scored_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests_by_case: dict[str, list[dict[str, Any]]] = {}
    for request in scored_requests:
        requests_by_case.setdefault(request["case_id"], []).append(request)
    output = []
    for case in cases:
        requirements = []
        requests = sorted(
            requests_by_case.get(case["case_id"], []),
            key=lambda row: row["requirement_index"],
        )
        if len(requests) != len(case["requirements"]):
            raise RuntimeError(f"Missing requirement scores: {case['case_id']}")
        for request in requests:
            scores = np.asarray(request["scores"], dtype=np.float64).reshape(-1)
            if len(scores) != len(case["candidates"]) or not np.isfinite(scores).all():
                raise RuntimeError("Requirement scores are missing or misaligned")
            requirements.append(
                {
                    "requirement_index": request["requirement_index"],
                    "requirement_id": request["requirement_id"],
                    "requirement_text": request["requirement_text"],
                    "candidates": [
                        {
                            "chunk_id": candidate["chunk_id"],
                            "original_rank": candidate["original_rank"],
                            "reranker_score": round(float(score), 8),
                        }
                        for candidate, score in zip(
                            case["candidates"], scores, strict=True
                        )
                    ],
                }
            )
        output.append(
            {
                "score_schema_version": SCORE_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "requirements": requirements,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * quantile)))
    return round(ordered[index], 3)


def _model_snapshot_fingerprint() -> dict[str, Any]:
    snapshot = Path(
        snapshot_download(
            MODEL_NAME,
            revision=MODEL_REVISION,
            local_files_only=True,
        )
    )
    files = []
    for path in sorted(item for item in snapshot.rglob("*") if item.is_file()):
        relative = path.relative_to(snapshot).as_posix()
        files.append(
            {"path": relative, "size": path.stat().st_size, "sha256": file_sha256(path)}
        )
    return {
        "snapshot_file_count": len(files),
        "snapshot_content_sha256": _sha256_bytes(_canonical_json_bytes(files)),
        "weight_files": [
            row for row in files if row["path"].endswith((".safetensors", ".bin"))
        ],
    }


def run_model(
    cases: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    requests = prepare_model_pairs(cases, chunks)
    load_start = time.perf_counter()
    model = CrossEncoder(
        MODEL_NAME,
        revision=MODEL_REVISION,
        max_length=MAX_LENGTH,
        device=device,
        local_files_only=True,
    )
    model_load_ms = (time.perf_counter() - load_start) * 1000
    requirement_latencies = []
    question_latencies: dict[str, float] = {}
    pair_count = 0
    for request in requests:
        pairs = request.pop("pairs")
        pair_count += len(pairs)
        started = time.perf_counter()
        if pairs:
            scores = model.predict(
                pairs,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            if device == "cuda":
                torch.cuda.synchronize()
            values = np.asarray(scores, dtype=np.float64).reshape(-1).tolist()
        else:
            values = []
        elapsed_ms = (time.perf_counter() - started) * 1000
        request["scores"] = values
        requirement_latencies.append(elapsed_ms)
        question_latencies[request["case_id"]] = (
            question_latencies.get(request["case_id"], 0.0) + elapsed_ms
        )
    scored_rows = attach_requirement_scores(cases, requests)
    latency = {
        "latency_schema_version": LATENCY_SCHEMA_VERSION,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "model_load_ms": round(model_load_ms, 3),
        "requirement_call_count": len(requirement_latencies),
        "question_count": len(question_latencies),
        "pair_count": pair_count,
        "requirement_call_median_ms": round(
            statistics.median(requirement_latencies), 3
        ),
        "requirement_call_p95_ms": _percentile(requirement_latencies, 0.95),
        "question_sum_median_ms": round(
            statistics.median(question_latencies.values()), 3
        ),
        "question_sum_p95_ms": _percentile(list(question_latencies.values()), 0.95),
        "total_inference_ms": round(sum(requirement_latencies), 3),
    }
    model_meta = {
        "name": MODEL_NAME,
        "revision": MODEL_REVISION,
        "max_length": MAX_LENGTH,
        "batch_size": BATCH_SIZE,
        "device": device,
        "temperature": "not_applicable",
        **_model_snapshot_fingerprint(),
        "libraries": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "numpy": np.__version__,
        },
    }
    return scored_rows, latency, model_meta


def _rank_candidates(
    candidates: list[dict[str, Any]], score_key: str
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda row: (
            -float(row[score_key]),
            int(row["original_rank"]),
            row["chunk_id"],
        ),
    )


def _select(
    query: str, candidates: list[dict[str, Any]], score_key: str
) -> tuple[list[dict[str, Any]], int, str]:
    adapted = [
        {**candidate, "reranker_score": candidate[score_key]}
        for candidate in candidates
    ]
    depth, reason = selection_depth(query, adapted)
    return _rank_candidates(candidates, score_key)[:depth], depth, reason


def evaluate_rows(
    cases: list[dict[str, Any]], scored_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scores_by_id = {row["case_id"]: row for row in scored_rows}
    output = []
    for case in cases:
        scored = scores_by_id[case["case_id"]]
        baseline_selected, baseline_depth, baseline_reason = _select(
            case["question"], case["candidates"], "question_reranker_score"
        )
        requirement_membership: dict[str, list[dict[str, Any]]] = {}
        requirement_selections = []
        for requirement in scored["requirements"]:
            selected, depth, reason = _select(
                requirement["requirement_text"],
                requirement["candidates"],
                "reranker_score",
            )
            requirement_selections.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "requirement_text": requirement["requirement_text"],
                    "selection_depth": depth,
                    "selection_reason": reason,
                    "selected_chunk_ids": [row["chunk_id"] for row in selected],
                }
            )
            ranked = _rank_candidates(requirement["candidates"], "reranker_score")
            rank_by_id = {
                candidate["chunk_id"]: rank for rank, candidate in enumerate(ranked, 1)
            }
            score_by_id = {
                candidate["chunk_id"]: candidate["reranker_score"]
                for candidate in requirement["candidates"]
            }
            for candidate in selected:
                requirement_membership.setdefault(candidate["chunk_id"], []).append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "rank": rank_by_id[candidate["chunk_id"]],
                        "score": score_by_id[candidate["chunk_id"]],
                    }
                )
        requirement_selected = sorted(
            requirement_membership,
            key=lambda chunk_id: (
                min(row["rank"] for row in requirement_membership[chunk_id]),
                -max(row["score"] for row in requirement_membership[chunk_id]),
                chunk_id,
            ),
        )
        candidate_ids = {row["chunk_id"] for row in case["candidates"]}
        baseline_ids = {row["chunk_id"] for row in baseline_selected}
        requirement_ids = set(requirement_selected)
        groups = []
        all_acceptable = set()
        for group in case["evidence_groups"]:
            acceptable = set(group["acceptable_chunk_ids"])
            all_acceptable.update(acceptable)
            candidate_bound = bool(candidate_ids & acceptable)
            best_requirement_rank = None
            if candidate_bound and scored["requirements"]:
                ranks = []
                for requirement in scored["requirements"]:
                    ranked = _rank_candidates(
                        requirement["candidates"], "reranker_score"
                    )
                    ranks.extend(
                        index
                        for index, candidate in enumerate(ranked, 1)
                        if candidate["chunk_id"] in acceptable
                    )
                best_requirement_rank = min(ranks) if ranks else None
            groups.append(
                {
                    "group_id": group["group_id"],
                    "candidate_bound": candidate_bound,
                    "baseline_hit": bool(baseline_ids & acceptable),
                    "requirement_hit": bool(requirement_ids & acceptable),
                    "best_requirement_rank": best_requirement_rank,
                }
            )
        bound_groups = [group for group in groups if group["candidate_bound"]]
        retrieval_bound_groups = [
            group for group in groups if not group["candidate_bound"]
        ]
        question_gate_eligible = bool(groups) and not retrieval_bound_groups
        output.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "source_ids": case["source_ids"],
                "gold_answerability": case["gold_answerability"],
                "requirement_count": len(case["requirements"]),
                "candidate_count": len(case["candidates"]),
                "evidence_group_count": len(groups),
                "candidate_bound_evidence_group_count": len(bound_groups),
                "retrieval_bound_group_ids": [
                    group["group_id"] for group in retrieval_bound_groups
                ],
                "question_gate_eligible": question_gate_eligible,
                "groups": groups,
                "baseline": {
                    "selection_depth": baseline_depth,
                    "selection_reason": baseline_reason,
                    "selected_chunk_ids": [
                        row["chunk_id"] for row in baseline_selected
                    ],
                    "selected_count": len(baseline_ids),
                    "over_selection_count": len(baseline_ids - all_acceptable)
                    if groups
                    else None,
                    "all_groups_covered": all(
                        group["baseline_hit"] for group in groups
                    )
                    if question_gate_eligible
                    else None,
                },
                "requirement_aware": {
                    "selected_chunk_ids": requirement_selected,
                    "selected_count": len(requirement_ids),
                    "over_selection_count": len(requirement_ids - all_acceptable)
                    if groups
                    else None,
                    "all_groups_covered": all(
                        group["requirement_hit"] for group in groups
                    )
                    if question_gate_eligible
                    else None,
                    "requirement_selections": requirement_selections,
                },
                "gold_ids_available_to_reranker": False,
                "gold_ids_used_for_scoring_only": True,
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_rows = [row for row in rows if row["evidence_group_count"]]
    eligible_rows = [row for row in rows if row["question_gate_eligible"]]
    bound_groups = [
        group
        for row in evidence_rows
        for group in row["groups"]
        if group["candidate_bound"]
    ]
    retrieval_bound_groups = [
        group
        for row in evidence_rows
        for group in row["groups"]
        if not group["candidate_bound"]
    ]

    def arm_metrics(arm: str, hit_key: str) -> dict[str, Any]:
        question_hits = sum(bool(row[arm]["all_groups_covered"]) for row in eligible_rows)
        group_hits = sum(bool(group[hit_key]) for group in bound_groups)
        selected_total = sum(row[arm]["selected_count"] for row in evidence_rows)
        over_total = sum(
            int(row[arm]["over_selection_count"] or 0) for row in evidence_rows
        )
        return {
            "per_evidence_group_coverage": {
                "successes": group_hits,
                "total": len(bound_groups),
                "rate": round(group_hits / len(bound_groups), 6)
                if bound_groups
                else None,
            },
            "all_evidence_groups_covered_question_rate": {
                "successes": question_hits,
                "total": len(eligible_rows),
                "rate": round(question_hits / len(eligible_rows), 6)
                if eligible_rows
                else None,
            },
            "selected_chunk_count": selected_total,
            "average_selected_count": round(selected_total / len(evidence_rows), 6)
            if evidence_rows
            else None,
            "annotated_over_selection_count": over_total,
            "annotated_over_selection_rate": round(over_total / selected_total, 6)
            if selected_total
            else None,
        }

    baseline = arm_metrics("baseline", "baseline_hit")
    requirement = arm_metrics("requirement_aware", "requirement_hit")
    question_improvements = [
        row["case_id"]
        for row in eligible_rows
        if not row["baseline"]["all_groups_covered"]
        and row["requirement_aware"]["all_groups_covered"]
    ]
    question_regressions = [
        row["case_id"]
        for row in eligible_rows
        if row["baseline"]["all_groups_covered"]
        and not row["requirement_aware"]["all_groups_covered"]
    ]
    group_improvements = sum(
        not group["baseline_hit"] and group["requirement_hit"]
        for group in bound_groups
    )
    group_regressions = sum(
        group["baseline_hit"] and not group["requirement_hit"]
        for group in bound_groups
    )
    missed_bound_groups = [
        group for group in bound_groups if not group["requirement_hit"]
    ]
    return {
        "row_count": len(rows),
        "evidence_bearing_question_count": len(evidence_rows),
        "question_gate_eligible_count": len(eligible_rows),
        "retrieval_bound_question_count": sum(
            bool(row["retrieval_bound_group_ids"]) for row in evidence_rows
        ),
        "retrieval_bound_evidence_group_count": len(retrieval_bound_groups),
        "candidate_bound_evidence_group_count": len(bound_groups),
        "baseline": baseline,
        "requirement_aware": requirement,
        "comparison": {
            "all_groups_question_improvement_count": len(question_improvements),
            "all_groups_question_regression_count": len(question_regressions),
            "all_groups_question_net_delta": len(question_improvements)
            - len(question_regressions),
            "evidence_group_improvement_count": group_improvements,
            "evidence_group_regression_count": group_regressions,
        },
        "failure_cause_summary": {
            "candidate_shortage_group_count": len(retrieval_bound_groups),
            "candidate_present_but_requirement_not_selected_group_count": len(
                missed_bound_groups
            ),
            "candidate_present_miss_best_rank_median": (
                statistics.median(
                    group["best_requirement_rank"]
                    for group in missed_bound_groups
                    if group["best_requirement_rank"] is not None
                )
                if any(
                    group["best_requirement_rank"] is not None
                    for group in missed_bound_groups
                )
                else None
            ),
            "interpretation": "candidate_shortage_is_retrieval; candidate_present_miss_is_requirement_expression_or_reranker_depth",
        },
    }


def gate(metrics: dict[str, Any]) -> dict[str, Any]:
    baseline = metrics["baseline"]["all_evidence_groups_covered_question_rate"]
    requirement = metrics["requirement_aware"][
        "all_evidence_groups_covered_question_rate"
    ]
    checks = {
        "all_groups_covered_improves": requirement["successes"]
        > baseline["successes"],
        "strict_question_regression_zero": metrics["comparison"][
            "all_groups_question_regression_count"
        ]
        == 0,
        "gold_not_available_to_reranker": True,
        "retrieval_bound_excluded_from_gate": True,
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "decision": "GO_TO_ENTAILMENT_AND_ASSEMBLY"
        if all(checks.values())
        else "NO_GO_CAUSE_ANALYSIS",
    }


def _markdown(report: dict[str, Any]) -> bytes:
    metrics = report["metrics"]["combined"]
    baseline = metrics["baseline"]
    requirement = metrics["requirement_aware"]
    lines = [
        "# Requirement-aware BGE reranker pilot",
        "",
        f"- Decision: **{report['decision']}**",
        f"- Retrieval-bound questions: {metrics['retrieval_bound_question_count']}",
        f"- Retrieval-bound evidence groups: {metrics['retrieval_bound_evidence_group_count']}",
        "",
        "| arm | evidence-group coverage | all-groups questions | avg selected | annotated over-selection |",
        "|---|---:|---:|---:|---:|",
        (
            f"| whole-question baseline | {baseline['per_evidence_group_coverage']['successes']}/"
            f"{baseline['per_evidence_group_coverage']['total']} | "
            f"{baseline['all_evidence_groups_covered_question_rate']['successes']}/"
            f"{baseline['all_evidence_groups_covered_question_rate']['total']} | "
            f"{baseline['average_selected_count']} | {baseline['annotated_over_selection_count']} |"
        ),
        (
            f"| requirement-aware | {requirement['per_evidence_group_coverage']['successes']}/"
            f"{requirement['per_evidence_group_coverage']['total']} | "
            f"{requirement['all_evidence_groups_covered_question_rate']['successes']}/"
            f"{requirement['all_evidence_groups_covered_question_rate']['total']} | "
            f"{requirement['average_selected_count']} | {requirement['annotated_over_selection_count']} |"
        ),
        "",
        f"- Strict improvements: {metrics['comparison']['all_groups_question_improvement_count']}",
        f"- Strict regressions: {metrics['comparison']['all_groups_question_regression_count']}",
        "",
        "Gold chunk IDs were used only after scoring for exact set membership.",
        "No semantic matcher, answerability component, training, or generation was used.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    device: str = "cuda",
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "enumeration": root / DEFAULT_ENUMERATION,
        "canary_32": root / DEFAULT_CANARY,
        "dev_63": root / DEFAULT_DEV,
        "canary_candidates": root / DEFAULT_CANARY_CANDIDATES,
        "dev_candidates": root / DEFAULT_DEV_CANDIDATES,
        "canary_manifest": root / DEFAULT_CANARY_MANIFEST,
        "dev_reranker_manifest": root / DEFAULT_DEV_RERANKER_MANIFEST,
        "chunks": root / DEFAULT_CHUNKS,
        "selector_source": root / "src/v3/rerank_evidence.py",
        "prior_scorer_source": root / "src/v3/score_evidence_reranker.py",
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    chunks = read_jsonl(input_paths["chunks"])
    cases = build_cases(
        read_jsonl(input_paths["canary_32"]),
        read_jsonl(input_paths["dev_63"]),
        read_jsonl(input_paths["enumeration"]),
        read_jsonl(input_paths["canary_candidates"]),
        read_jsonl(input_paths["dev_candidates"]),
        chunks,
    )
    scored_rows, latency, model_meta = run_model(cases, chunks, device=device)
    results = evaluate_rows(cases, scored_rows)

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    scores_bytes = _serialize_jsonl(scored_rows, lambda row: row["case_id"])
    scores_sha = _sha256_bytes(scores_bytes)
    scores_path = evidence_dir / f"requirement_reranker_scores_{scores_sha}.jsonl"
    write_immutable(scores_path, scores_bytes)
    results_bytes = _serialize_jsonl(results, lambda row: row["case_id"])
    results_sha = _sha256_bytes(results_bytes)
    results_path = evidence_dir / f"requirement_reranker_ab_results_{results_sha}.jsonl"
    write_immutable(results_path, results_bytes)

    combined_metrics = aggregate(results)
    metrics = {
        "combined": combined_metrics,
        "downgraded_canary_32": aggregate(
            [row for row in results if row["dataset"] == "downgraded_canary_32"]
        ),
        "adaptive_dev_63": aggregate(
            [row for row in results if row["dataset"] == "adaptive_dev_63"]
        ),
    }
    gate_result = gate(combined_metrics)
    latency_bytes = _canonical_json_bytes(latency)
    latency_sha = _sha256_bytes(latency_bytes)
    latency_path = reports_dir / f"requirement_reranker_latency_{latency_sha}.json"
    write_immutable(latency_path, latency_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_32_plus_63",
        "decision": gate_result["decision"],
        "gate": gate_result,
        "metrics": metrics,
        "latency": latency,
        "model": model_meta,
        "contract": {
            "baseline": "whole_question_existing_adaptive_3_or_8",
            "requirement_arm": "subject_plus_relation_each_existing_adaptive_3_or_8_then_union",
            "candidate_sets_changed": False,
            "gold_membership_scoring_only": True,
            "semantic_matcher_used": False,
            "retrieval_bound_excluded_from_gate": True,
        },
        "scope": {
            "answerability": "parked",
            "reranker_only": True,
            "retrieval_changed": False,
            "training": False,
            "new_keyword_rules": False,
            "entailment_judge": False,
            "answer_generation": False,
            "new_canary": False,
            "frozen_blind_accessed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"requirement_reranker_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"requirement_reranker_pilot_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "model": model_meta,
        "selector": {
            "version": RERANK_SELECTOR_VERSION,
            "default_depth": DEFAULT_DEPTH,
            "fallback_depth": FALLBACK_DEPTH,
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
            "multi_evidence_markers": list(MULTI_EVIDENCE_MARKERS),
        },
        "artifacts": {
            "scores": {
                "path": _relative(root, scores_path),
                "sha256": scores_sha,
                "row_count": len(scored_rows),
                "requirement_count": sum(
                    len(row["requirements"]) for row in scored_rows
                ),
            },
            "results": {
                "path": _relative(root, results_path),
                "sha256": results_sha,
                "row_count": len(results),
            },
            "latency": {"path": _relative(root, latency_path), "sha256": latency_sha},
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "decision": gate_result["decision"],
        "gold_ids_available_to_reranker": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"requirement_reranker_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during reranker pilot: {name}")
    return {
        "decision": gate_result["decision"],
        "gate": gate_result,
        "combined_metrics": combined_metrics,
        "latency": latency,
        "model": model_meta,
        "scores": str(scores_path),
        "scores_sha256": scores_sha,
        "results": str(results_path),
        "results_sha256": results_sha,
        "report": str(report_path),
        "report_sha256": report_sha,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the requirement-aware BGE reranker pilot"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        device=args.device,
        evaluated_at=args.evaluated_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
