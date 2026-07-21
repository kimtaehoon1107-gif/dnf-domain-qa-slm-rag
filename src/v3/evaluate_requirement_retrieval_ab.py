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
from src.v3.evaluate_extractive_assembler_v3 import segment_chunk_nonoverlap
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_requirement_reranker import requirement_text
from src.v3.evaluate_retrieval import encode_queries
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
    load_runtime_artifacts,
    retrieve_with_embedding,
)
from src.v3.score_evidence_reranker import (
    BATCH_SIZE,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
)


EVALUATOR_VERSION = "requirement-retrieval-ab-v3.1.0"
RETRIEVAL_SCHEMA_VERSION = "requirement-retrieval-ab-candidates-v3.1"
SCORE_SCHEMA_VERSION = "requirement-retrieval-ab-segment-scores-v3.1"
CASE_SCHEMA_VERSION = "requirement-retrieval-ab-case-v3.1"
REPORT_SCHEMA_VERSION = "requirement-retrieval-ab-report-v3.1"
MANIFEST_SCHEMA_VERSION = "requirement-retrieval-ab-manifest-v3.1"

TOP_K = 10
ASSEMBLER_THRESHOLD = 0.001
ASSEMBLER_K = 3
ARM_REQUIREMENT_ONLY = "requirement_only"
ARM_UNION = "question_union_requirement"
NEW_ARMS = (ARM_REQUIREMENT_ONLY, ARM_UNION)

DEFAULT_RERANK_RESULTS = Path(
    "data/v3/evidence/requirement_reranker_ab_results_"
    "db7dbd2281687c07aebf88dc43a07bd90cf280e690188c06a79cf9e3a2b04913.jsonl"
)
DEFAULT_RERANK_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_RERANK_MANIFEST = Path(
    "data/v3/evidence/requirement_reranker_manifest_"
    "9d55090789cee5baebc026fc735658896807db73ef2076bcb3bbce61f67a70e4.json"
)
DEFAULT_ASSEMBLER_CASES = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_ASSEMBLER_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_"
    "9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json"
)
DEFAULT_BACKBONE_CASES = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_BACKBONE_MANIFEST = Path(
    "data/v3/router/router_backbone_answer_source_ab_manifest_"
    "1dc7f770f17b5426ef434b8a10ecd7395b6705cb0cf9a4626bc4ca8527d81e29.json"
)
DEFAULT_FALSE_FULL_CASES = Path(
    "data/v3/evidence/false_full_case_audit_"
    "c2f0bee2fbcc9e0d8941c47aaa7912429fad62b23c7bf35a3baf6fcbba0d1ec0.jsonl"
)
DEFAULT_FALSE_FULL_MANIFEST = Path(
    "data/v3/evidence/false_full_audit_manifest_"
    "1830d97afd819836df95bdc0ddce2db9a09cbeab7ad7d8fbb8b77ebc4a4efab1.json"
)
DEFAULT_CONTRACT = Path("docs/v3/requirement_retrieval_ab.md")


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
        "small_sample_limit": total < 5,
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * quantile))
    return round(float(ordered[index]), 3)


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
        "source_ids": list(policy.source_ids) if policy.source_ids is not None else None,
    }


def policy_from_frozen_route(
    route: dict[str, Any], *, as_of: str | None
) -> SearchPolicy | None:
    """Reuse the frozen runtime route without consulting evaluation gold."""
    if route["route_action"] not in {"retrieve", "decompose"}:
        return None
    return SearchPolicy(
        default_exposure_only=route["default_exposure_only"],
        allowed_statuses=tuple(route["allowed_statuses"]),
        include_review_required=False,
        as_of=route.get("temporal_as_of") or as_of,
        source_ids=tuple(route["source_ids"]) if route["source_ids"] else None,
    )


def merge_candidate_ids(*groups: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for chunk_id in group:
            if chunk_id not in seen:
                seen.add(chunk_id)
                output.append(chunk_id)
    return output


def build_retrieval_requests(
    assembler_cases: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    frozen_runtime_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    runtime = {row["case_id"]: row for row in frozen_runtime_rows}
    output = []
    for case in assembler_cases:
        case_id = case["case_id"]
        evaluation = evaluations[case_id]
        runtime_row = runtime[case_id]
        route = runtime_row.get("actual_route") or runtime_row.get("route")
        if route is None:
            raise RuntimeError(f"Frozen route missing: {case_id}")
        policy = policy_from_frozen_route(
            route, as_of=evaluation.get("as_of")
        )
        for index, requirement in enumerate(case["requirements"], 1):
            output.append(
                {
                    "case_id": case_id,
                    "dataset": case["dataset"],
                    "requirement_index": index,
                    "requirement_id": requirement["requirement_id"],
                    "query": requirement_text(requirement),
                    "policy": _policy_dict(policy),
                    "search_enabled": bool(case["evidence_groups"] and policy is not None),
                    "frozen_route_action": route["route_action"],
                    "frozen_assembler_chunk_ids": list(case["selected_chunk_ids"]),
                    "gold_ids_available_to_query_or_policy": False,
                }
            )
    return sorted(output, key=lambda row: (row["case_id"], row["requirement_index"]))


def _policy_from_dict(value: dict[str, Any] | None) -> SearchPolicy | None:
    if value is None:
        return None
    return SearchPolicy(
        default_exposure_only=value["default_exposure_only"],
        allowed_statuses=tuple(value["allowed_statuses"])
        if value["allowed_statuses"] is not None
        else None,
        include_review_required=value["include_review_required"],
        as_of=value["as_of"],
        source_ids=tuple(value["source_ids"]) if value["source_ids"] else None,
    )


def execute_requirement_retrieval(
    requests: list[dict[str, Any]],
    embeddings: np.ndarray,
    artifacts: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if embeddings.shape[0] != len(requests):
        raise RuntimeError("Requirement embedding count differs from requests")
    output = []
    latencies = []
    by_case: dict[str, float] = {}
    call_count = 0
    for request, embedding in zip(requests, embeddings, strict=True):
        hits = []
        elapsed = 0.0
        if request["search_enabled"]:
            started = time.perf_counter()
            hits = retrieve_with_embedding(
                request["query"],
                embedding,
                artifacts,
                top_k=TOP_K,
                policy=_policy_from_dict(request["policy"]),
            )
            elapsed = (time.perf_counter() - started) * 1000
            latencies.append(elapsed)
            by_case[request["case_id"]] = by_case.get(request["case_id"], 0.0) + elapsed
            call_count += 1
        output.append(
            {
                "candidate_schema_version": RETRIEVAL_SCHEMA_VERSION,
                **request,
                "hits": [
                    {
                        "rank": hit["rank"],
                        "chunk_id": hit["chunk_id"],
                        "parent_document_id": hit["parent_document_id"],
                        "source_id": hit["source_id"],
                        "status": hit["status"],
                        "default_exposure": hit["default_exposure"],
                        "base_hybrid_rank": hit["base_hybrid_rank"],
                        "base_hybrid_score": hit["base_hybrid_score"],
                        "guardrail_injected": hit["guardrail_injected"],
                    }
                    for hit in hits
                ],
                "retrieval_elapsed_ms": round(elapsed, 3),
            }
        )
    latency = {
        "requirement_search_call_count": call_count,
        "evidence_bearing_question_count": len(by_case),
        "requirement_search_median_ms": round(statistics.median(latencies), 3)
        if latencies
        else None,
        "requirement_search_p95_ms": _percentile(latencies, 0.95),
        "question_added_search_median_ms": round(statistics.median(by_case.values()), 3)
        if by_case
        else None,
        "question_added_search_p95_ms": _percentile(list(by_case.values()), 0.95),
        "total_search_ms": round(sum(latencies), 3),
    }
    return output, latency


def build_arm_cases(
    assembler_cases: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    arm: str,
) -> list[dict[str, Any]]:
    if arm not in NEW_ARMS:
        raise RuntimeError(f"Unknown retrieval arm: {arm}")
    retrieval_by_key = {
        (row["case_id"], int(row["requirement_index"])): row
        for row in retrieval_rows
    }
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    output = []
    for source in assembler_cases:
        requirement_candidates = []
        union_ids: list[str] = []
        for index, requirement in enumerate(source["requirements"], 1):
            retrieved = [
                row["chunk_id"]
                for row in retrieval_by_key[(source["case_id"], index)]["hits"]
            ]
            candidate_ids = (
                retrieved
                if arm == ARM_REQUIREMENT_ONLY
                else merge_candidate_ids(source["selected_chunk_ids"], retrieved)
            )
            requirement_candidates.append(
                {
                    "requirement_index": index,
                    "requirement_id": requirement["requirement_id"],
                    "candidate_chunk_ids": candidate_ids,
                }
            )
            union_ids = merge_candidate_ids(union_ids, candidate_ids)
        output.append(
            {
                **source,
                "retrieval_arm": arm,
                "selected_chunk_ids": union_ids,
                "selected_chunks": {
                    chunk_id: chunks_by_id[chunk_id]["display_text"]
                    for chunk_id in union_ids
                },
                "requirement_candidate_pools": requirement_candidates,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def build_requirement_segments(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for case in cases:
        requirements = []
        for pool in case["requirement_candidate_pools"]:
            segments = []
            for chunk_id in pool["candidate_chunk_ids"]:
                segments.extend(
                    segment_chunk_nonoverlap(chunk_id, case["selected_chunks"][chunk_id])
                )
            if len({row["span_id"] for row in segments}) != len(segments):
                raise RuntimeError(
                    f"Duplicate requirement segment ID: {case['case_id']}:{pool['requirement_index']}"
                )
            requirements.append({**pool, "segments": segments})
        output.append(
            {
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "requirements": requirements,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def _model_snapshot_fingerprint() -> dict[str, Any]:
    from huggingface_hub import snapshot_download

    snapshot = Path(
        snapshot_download(
            repo_id=MODEL_NAME,
            revision=MODEL_REVISION,
            local_files_only=True,
        )
    )
    files = sorted(path for path in snapshot.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    weights = []
    for path in files:
        relative = path.relative_to(snapshot).as_posix()
        sha = file_sha256(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\n")
        if path.suffix in {".bin", ".safetensors"}:
            weights.append({"path": relative, "sha256": sha, "size": path.stat().st_size})
    return {
        "snapshot_content_sha256": digest.hexdigest(),
        "snapshot_file_count": len(files),
        "weight_files": weights,
    }


def run_segment_reranker(
    cases: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    model: CrossEncoder,
    *,
    arm: str,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segments_by_case = {row["case_id"]: row for row in segment_rows}
    output = []
    latencies = []
    by_case: dict[str, float] = {}
    pair_count = 0
    call_count = 0
    for case in cases:
        scored_requirements = []
        segment_requirements = {
            int(row["requirement_index"]): row
            for row in segments_by_case[case["case_id"]]["requirements"]
        }
        for index, requirement in enumerate(case["requirements"], 1):
            segments = segment_requirements[index]["segments"]
            query = requirement_text(requirement)
            candidates = []
            if case["evidence_groups"] and segments:
                pairs = [(query, row["text"]) for row in segments]
                started = time.perf_counter()
                scores = model.predict(
                    pairs,
                    batch_size=BATCH_SIZE,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
                if device == "cuda":
                    torch.cuda.synchronize()
                elapsed = (time.perf_counter() - started) * 1000
                values = np.asarray(scores, dtype=np.float64).reshape(-1)
                if len(values) != len(segments) or not np.isfinite(values).all():
                    raise RuntimeError("Segment reranker scores are missing or non-finite")
                candidates = [
                    {**segment, "reranker_score": round(float(score), 8)}
                    for segment, score in zip(segments, values.tolist(), strict=True)
                ]
                latencies.append(elapsed)
                by_case[case["case_id"]] = by_case.get(case["case_id"], 0.0) + elapsed
                pair_count += len(pairs)
                call_count += 1
            scored_requirements.append(
                {
                    "requirement_index": index,
                    "requirement_id": requirement["requirement_id"],
                    "query": query,
                    "candidates": candidates,
                }
            )
        output.append(
            {
                "score_schema_version": SCORE_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "retrieval_arm": arm,
                "requirements": scored_requirements,
                "gold_ids_available_to_segment_reranker": False,
            }
        )
    return sorted(output, key=lambda row: row["case_id"]), {
        "requirement_call_count": call_count,
        "question_count": len(by_case),
        "pair_count": pair_count,
        "requirement_call_median_ms": round(statistics.median(latencies), 3)
        if latencies
        else None,
        "requirement_call_p95_ms": _percentile(latencies, 0.95),
        "question_sum_median_ms": round(statistics.median(by_case.values()), 3)
        if by_case
        else None,
        "question_sum_p95_ms": _percentile(list(by_case.values()), 0.95),
        "total_inference_ms": round(sum(latencies), 3),
    }


def build_scored_router_cases(
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
    new_assemblers = {
        arm: {row["case_id"]: row for row in rows}
        for arm, rows in arm_assembler_rows.items()
    }
    new_cases = {
        arm: {row["case_id"]: row for row in rows}
        for arm, rows in arm_cases.items()
    }
    chunk_to_parent = {
        row["chunk_id"]: row["parent_document_id"] for row in chunks
    }
    output = []
    for truth in ground_truth_rows:
        case_id = truth["case_id"]
        evaluation = evaluations[case_id]
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
        for arm in NEW_ARMS:
            decisions = new_assemblers[arm][case_id]["decisions"]
            simulated = simulate_arm(
                placement="arm0",
                question=evaluation["question"],
                assembler_decisions=decisions,
                classifier_predictions=[],
                chunk_to_parent=chunk_to_parent,
            )
            score = _score_arm(
                simulated,
                target=target,
                evidence_groups=evaluation["evidence_groups"],
                expected_docs_flags=[True] * len(decisions),
                baseline_supported_indices=set(),
            )
            candidate_ids = sorted(
                {
                    chunk_id
                    for pool in new_cases[arm][case_id]["requirement_candidate_pools"]
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


def _selection_metrics(
    evaluation_rows: list[dict[str, Any]],
    ground_truth_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    targets = {row["case_id"]: row for row in ground_truth_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    span_count = 0
    supported_count = 0
    invalid = 0
    extra_citation_count = 0
    extra_questions = 0
    for assembled in assembler_rows:
        case_id = assembled["case_id"]
        if targets[case_id]["answerability_label"] == "false":
            continue
        acceptable = {
            chunk_id
            for group in evaluations[case_id]["evidence_groups"]
            for chunk_id in group["acceptable_chunk_ids"]
        }
        cited: set[str] = set()
        for decision in assembled["decisions"]:
            if decision["status"] != "supported_exact":
                continue
            supported_count += 1
            span_count += len(decision["spans"])
            for span in decision["spans"]:
                cited.add(span["chunk_id"])
                source = chunks_by_id[span["chunk_id"]]["display_text"]
                invalid += source[span["start_char"] : span["end_char"]] != span["text"]
        extras = cited - acceptable
        extra_citation_count += len(extras)
        extra_questions += bool(extras)
    return {
        "span_validity": {
            "exact_slices": span_count - invalid,
            "invalid": invalid,
            "rate": round((span_count - invalid) / span_count, 8) if span_count else 1.0,
        },
        "supported_requirement_count": supported_count,
        "selected_span_count": span_count,
        "mean_spans_per_supported_requirement": round(span_count / supported_count, 8)
        if supported_count
        else 0.0,
        "question_level_nonacceptable_unique_citation_count": extra_citation_count,
        "questions_with_nonacceptable_citation": extra_questions,
        "overselection_proxy_note": "Question-level acceptable-chunk union; reported with mean spans because requirement-to-group mapping is many-to-many.",
    }


def summarize_arm(
    case_rows: list[dict[str, Any]],
    arm: str,
    *,
    baseline_false_full_ids: set[str],
) -> dict[str, Any]:
    docs = [row for row in case_rows if row["answerability_target"] == "answerable_docs"]
    reject = [row for row in case_rows if row["answerability_target"] == "reject"]
    realtime = [row for row in case_rows if row["answerability_target"] == "realtime_api"]
    grounded_ids = {
        row["case_id"] for row in docs if row[arm]["score"]["grounded_answer"]
    }
    false_full_ids = {
        row["case_id"] for row in docs if row[arm]["score"]["false_full_answer"]
    }
    return {
        "answerable": {
            "grounded_answer": _ratio(len(grounded_ids), len(docs)),
            "false_full_answer": _ratio(len(false_full_ids), len(docs)),
            "honest_partial": _ratio(
                sum(row[arm]["score"]["honest_partial"] for row in docs), len(docs)
            ),
            "overreject": _ratio(
                sum(row[arm]["score"]["answerable_overreject"] for row in docs), len(docs)
            ),
            "new_false_full_case_count": len(false_full_ids - baseline_false_full_ids),
            "baseline_grounded_regression_count": 0,
        },
        "reject": {
            "correct_abstain_or_reject": _ratio(
                sum(row[arm]["score"]["reject_correct"] for row in reject), len(reject)
            )
        },
        "realtime": {
            "safe_abstain": _ratio(
                sum(row[arm]["score"]["realtime_safe_abstain"] for row in realtime),
                len(realtime),
            ),
            "static_exposure": _ratio(
                sum(row[arm]["score"]["realtime_static_exposure"] for row in realtime),
                len(realtime),
            ),
        },
        "grounded_case_ids": sorted(grounded_ids),
        "false_full_case_ids": sorted(false_full_ids),
    }


def _cross_parent_metrics(
    case_rows: list[dict[str, Any]], taxonomy_rows: list[dict[str, Any]], arm: str
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in case_rows}
    same_ids = [row["case_id"] for row in taxonomy_rows if row["single_parent_coverable"]]
    cross_ids = [row["case_id"] for row in taxonomy_rows if row["cross_parent"]]
    return {
        "same_parent_not_decomposed": _ratio(
            sum(not cases[case_id][arm]["cross_parent_candidate"] for case_id in same_ids),
            len(same_ids),
        ),
        "cross_parent_trigger": _ratio(
            sum(cases[case_id][arm]["cross_parent_candidate"] for case_id in cross_ids),
            len(cross_ids),
        ),
        "cross_parent_grounded": _ratio(
            sum(cases[case_id][arm]["score"]["grounded_answer"] for case_id in cross_ids),
            len(cross_ids),
        ),
    }


def _retrieval_bound_metrics(
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
    recovered_candidates = 0
    recovered_grounded = 0
    group_hits = 0
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
        grounded = case[arm]["score"]["grounded_answer"]
        recovered_candidates += all_present
        recovered_grounded += grounded
        details.append(
            {
                "case_id": audit["case_id"],
                "classification": audit["classification"],
                "all_gold_groups_candidate_present": all_present,
                "grounded_after_assembly": grounded,
                "cross_parent_candidate": case[arm]["cross_parent_candidate"],
                "groups": groups,
            }
        )
    return {
        "question_candidate_recovery": _ratio(recovered_candidates, len(targets)),
        "evidence_group_candidate_recovery": _ratio(group_hits, group_total),
        "false_full_to_grounded_recovery": _ratio(recovered_grounded, len(targets)),
        "details": details,
    }


def evaluate_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_selection: dict[str, Any],
    candidate_selection: dict[str, Any],
    retrieval_bound: dict[str, Any],
    cross_parent: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "at_least_one_retrieval_bound_false_full_recovered": retrieval_bound[
            "false_full_to_grounded_recovery"
        ]["successes"]
        >= 1,
        "grounded_at_least_73": candidate["answerable"]["grounded_answer"]["successes"]
        >= 73,
        "grounded_not_reduced": candidate["answerable"]["grounded_answer"]["successes"]
        >= baseline["answerable"]["grounded_answer"]["successes"],
        "new_false_full_zero": candidate["answerable"]["new_false_full_case_count"] == 0,
        "mean_spans_not_increased": candidate_selection[
            "mean_spans_per_supported_requirement"
        ]
        <= baseline_selection["mean_spans_per_supported_requirement"],
        "nonacceptable_citations_not_increased": candidate_selection[
            "question_level_nonacceptable_unique_citation_count"
        ]
        <= baseline_selection["question_level_nonacceptable_unique_citation_count"],
        "exact_span_validity_100_percent": candidate_selection["span_validity"]["invalid"]
        == 0,
        "same_parent_7_of_7_preserved": cross_parent["same_parent_not_decomposed"][
            "successes"
        ]
        == 7,
        "reject_11_of_11_preserved": candidate["reject"]["correct_abstain_or_reject"][
            "successes"
        ]
        == 11,
        "realtime_safe_abstain_2_of_2_preserved": candidate["realtime"]["safe_abstain"][
            "successes"
        ]
        == 2,
    }
    return {"checks": checks, "pass": all(checks.values())}


def _markdown(report: dict[str, Any]) -> bytes:
    lines = [
        "# Requirement-query retrieval A/B",
        "",
        f"Decision: **{report['decision']}**",
        "",
        "This is a development-only A/B. No arm was promoted to canonical or runtime.",
        "",
        "## Arm metrics",
        "",
        "| arm | retrieval-bound candidate | false-full→grounded | grounded | false-full | new false-full | exact | mean spans | same-parent | reject | realtime safe | gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm in ("arm_a", ARM_REQUIREMENT_ONLY, ARM_UNION):
        metrics = report["arms"][arm]
        retrieval = report["retrieval_bound"][arm]
        cross = report["cross_parent"][arm]
        selection = report["selection"][arm]
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
                selection["mean_spans_per_supported_requirement"],
                cross["same_parent_not_decomposed"]["successes"],
                metrics["reject"]["correct_abstain_or_reject"]["successes"],
                metrics["realtime"]["safe_abstain"]["successes"],
                "baseline" if gate is None else ("PASS" if gate["pass"] else "FAIL"),
            )
        )
    lines.extend(
        [
            "",
            "## Cost",
            "",
            f"- Added requirement searches: {report['cost']['requirement_retrieval']['requirement_search_call_count']}",
            f"- Requirement search median/p95: {report['cost']['requirement_retrieval']['requirement_search_median_ms']} / {report['cost']['requirement_retrieval']['requirement_search_p95_ms']} ms",
            f"- Requirement-only segment pairs: {report['cost'][ARM_REQUIREMENT_ONLY]['pair_count']}",
            f"- Union segment pairs: {report['cost'][ARM_UNION]['pair_count']}",
            "",
            "## Guardrails and limits",
            "",
            "- Planner outputs, indexes, frozen question candidates, and assembler threshold/K were unchanged.",
            "- Route/filter scope was reconstructed from frozen question candidates; gold source or chunk IDs were not available to retrieval or assembly.",
            "- Reject/realtime cases have no human-gold evidence groups, so the existing assembler evaluation leaves them unsupported; their safety counts are inherited controls, not a new answerability solution.",
            "- The seven retrieval-bound cases use gold IDs only after execution for scoring.",
            "- Wrong-attribute cases remain outside this cycle.",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    device: str,
    batch_size: int,
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
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": root / "src/v3/evaluate_requirement_retrieval_ab.py",
        "retriever_source": root / "src/v3/retrieve_v3.py",
        "assembler_source": root / "src/v3/evaluate_extractive_assembler_v3_chunk_diverse.py",
    }
    before = {name: file_sha256(path) for name, path in input_paths.items()}
    reranker_manifest = json.loads(input_paths["reranker_manifest"].read_text(encoding="utf-8"))
    if reranker_manifest["artifacts"]["results"]["sha256"] != before["reranker_results"]:
        raise RuntimeError("Requirement reranker lineage mismatch")
    assembler_manifest = json.loads(
        input_paths["frozen_assembler_manifest"].read_text(encoding="utf-8")
    )
    if assembler_manifest["artifacts"]["cases"]["sha256"] != before[
        "frozen_assembler_cases"
    ]:
        raise RuntimeError("Frozen assembler lineage mismatch")
    backbone_manifest = json.loads(
        input_paths["frozen_backbone_manifest"].read_text(encoding="utf-8")
    )
    if backbone_manifest["artifacts"]["cases"]["sha256"] != before[
        "frozen_backbone_cases"
    ]:
        raise RuntimeError("Frozen backbone lineage mismatch")
    false_manifest = json.loads(
        input_paths["false_full_manifest"].read_text(encoding="utf-8")
    )
    if false_manifest["artifacts"]["cases"]["sha256"] != before["false_full_cases"]:
        raise RuntimeError("False-full audit lineage mismatch")

    ground_truth = read_jsonl(input_paths["ground_truth"])
    dev_rows = read_jsonl(input_paths["adaptive_dev"])
    canary_rows = read_jsonl(input_paths["downgraded_canary"])
    evaluation_rows = dev_rows + canary_rows
    enumeration = read_jsonl(input_paths["enumeration"])
    chunks = read_jsonl(input_paths["chunks"])
    rerank_results = read_jsonl(input_paths["reranker_results"])
    rerank_scores = read_jsonl(input_paths["reranker_scores"])
    assembler_cases = build_assembler_cases(
        canary_rows,
        dev_rows,
        enumeration,
        rerank_results,
        rerank_scores,
        read_jsonl(input_paths["canary_baseline_cases"]),
        read_jsonl(input_paths["dev_baseline_cases"]),
        chunks,
    )
    requests = build_retrieval_requests(
        assembler_cases,
        evaluation_rows,
        read_jsonl(input_paths["canary_baseline_cases"])
        + read_jsonl(input_paths["dev_baseline_cases"]),
    )
    artifacts = load_runtime_artifacts(root)
    embedding_started = time.perf_counter()
    embeddings, query_model = encode_queries(
        [row["query"] for row in requests],
        artifacts.dense_model,
        device=device,
        batch_size=batch_size,
    )
    embedding_ms = (time.perf_counter() - embedding_started) * 1000
    retrieval_rows, retrieval_latency = execute_requirement_retrieval(
        requests, embeddings, artifacts
    )

    arm_cases = {
        arm: build_arm_cases(assembler_cases, retrieval_rows, chunks, arm=arm)
        for arm in NEW_ARMS
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
    segment_latency = {}
    assembled = {}
    for arm in NEW_ARMS:
        score_rows[arm], segment_latency[arm] = run_segment_reranker(
            arm_cases[arm], segment_rows[arm], model, arm=arm, device=device
        )
        assembled[arm] = assemble_chunk_diverse_configuration(
            arm_cases[arm],
            score_rows[arm],
            threshold=ASSEMBLER_THRESHOLD,
            k=ASSEMBLER_K,
        )

    frozen_assembler_rows = read_jsonl(input_paths["frozen_assembler_cases"])
    frozen_backbone_rows = read_jsonl(input_paths["frozen_backbone_cases"])
    case_rows = build_scored_router_cases(
        ground_truth_rows=ground_truth,
        evaluation_rows=evaluation_rows,
        attribution_rows=read_jsonl(input_paths["attribution"]),
        frozen_backbone_rows=frozen_backbone_rows,
        frozen_assembler_rows=frozen_assembler_rows,
        arm_assembler_rows=assembled,
        arm_cases=arm_cases,
        chunks=chunks,
    )
    baseline_false_full = {
        row["case_id"]
        for row in case_rows
        if row["arm_a"]["score"]["false_full_answer"]
    }
    arms = {
        "arm_a": summarize_arm(
            case_rows, "arm_a", baseline_false_full_ids=baseline_false_full
        ),
        **{
            arm: summarize_arm(
                case_rows, arm, baseline_false_full_ids=baseline_false_full
            )
            for arm in NEW_ARMS
        },
    }
    taxonomy = read_jsonl(input_paths["taxonomy"])
    cross_parent = {
        arm: _cross_parent_metrics(case_rows, taxonomy, arm)
        for arm in ("arm_a", *NEW_ARMS)
    }
    false_full_rows = read_jsonl(input_paths["false_full_cases"])
    retrieval_bound = {
        arm: _retrieval_bound_metrics(case_rows, false_full_rows, arm)
        for arm in ("arm_a", *NEW_ARMS)
    }
    selection = {
        "arm_a": _selection_metrics(
            evaluation_rows, ground_truth, frozen_assembler_rows, chunks
        ),
        **{
            arm: _selection_metrics(evaluation_rows, ground_truth, assembled[arm], chunks)
            for arm in NEW_ARMS
        },
    }
    baseline_grounded_ids = set(arms["arm_a"]["grounded_case_ids"])
    for arm in NEW_ARMS:
        arms[arm]["answerable"]["baseline_grounded_regression_count"] = len(
            baseline_grounded_ids - set(arms[arm]["grounded_case_ids"])
        )
    gates = {
        arm: evaluate_gate(
            arms["arm_a"],
            arms[arm],
            selection["arm_a"],
            selection[arm],
            retrieval_bound[arm],
            cross_parent[arm],
        )
        for arm in NEW_ARMS
    }
    passing = [arm for arm in NEW_ARMS if gates[arm]["pass"]]
    decision = (
        f"ADOPT_RECOMMENDATION_{passing[0].upper()}_DEV_ONLY"
        if len(passing) == 1
        else (
            "ADOPT_RECOMMENDATION_UNION_DEV_ONLY"
            if len(passing) > 1 and ARM_UNION in passing
            else "NO_GO_REQUIREMENT_RETRIEVAL"
        )
    )
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
        "evaluation_role": "development_only_requirement_query_retrieval_ab",
        "evaluated_at": evaluated_at,
        "source_commit": _git_head(root),
        "decision": decision,
        "arms": arms,
        "retrieval_bound": retrieval_bound,
        "cross_parent": cross_parent,
        "selection": selection,
        "gates": gates,
        "configuration": {
            "arm_a": "frozen question-query selected chunks and frozen assembler",
            ARM_REQUIREMENT_ONLY: "per-requirement hybrid top-10 only",
            ARM_UNION: "frozen question selected chunks union per-requirement hybrid top-10",
            "query": "planner subject + relation",
            "top_k": TOP_K,
            "assembler_threshold": ASSEMBLER_THRESHOLD,
            "assembler_k_distinct_chunks": ASSEMBLER_K,
            "index_changed": False,
            "planner_reexecuted": False,
            "gold_source_or_chunk_ids_available_to_runtime": False,
            "route_policy_source": "frozen runtime route for the same case",
        },
        "cost": {
            "query_embedding": {
                **query_model,
                "query_count": len(requests),
                "total_ms": round(embedding_ms, 3),
                "amortized_ms_per_requirement": round(embedding_ms / len(requests), 3),
            },
            "requirement_retrieval": retrieval_latency,
            ARM_REQUIREMENT_ONLY: segment_latency[ARM_REQUIREMENT_ONLY],
            ARM_UNION: segment_latency[ARM_UNION],
            "logical_search_calls_per_population": {
                "arm_a_frozen_question_searches": 95,
                ARM_REQUIREMENT_ONLY: retrieval_latency["requirement_search_call_count"],
                ARM_UNION: 95 + retrieval_latency["requirement_search_call_count"],
            },
        },
        "model": model_meta,
        "retrieval_provenance": artifacts.provenance,
        "scope": {
            "canonical_or_runtime_promotion": False,
            "sealed_canary_run": False,
            "training": False,
            "reindex": False,
            "planner_changed": False,
            "assembler_selection_logic_changed": False,
            "wrong_attribute_cases_targeted": False,
            "frozen_blind_accessed": False,
            "gold_label_question_changed": False,
            "reject_realtime_controls_inherited_from_existing_no_gold_evidence_evaluation": True,
        },
        "input_hashes": before,
    }

    retrieval_dir = root / "data/v3/retrieval"
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    retrieval_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    embedding_bytes = np.asarray(embeddings, dtype="<f4").tobytes(order="C")
    embedding_sha = _sha256_bytes(embedding_bytes)
    embedding_path = retrieval_dir / f"requirement_retrieval_query_embeddings_{embedding_sha}.f32"
    write_immutable(embedding_path, embedding_bytes)

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
        "requirement_retrieval_ab_candidates",
        retrieval_rows,
        lambda row: (row["case_id"], row["requirement_index"]),
    )
    combined_scores = [row for arm in NEW_ARMS for row in score_rows[arm]]
    scores_path, scores_sha = freeze_jsonl(
        evidence_dir,
        "requirement_retrieval_ab_segment_scores",
        combined_scores,
        lambda row: (row["retrieval_arm"], row["case_id"]),
    )
    cases_path, cases_sha = freeze_jsonl(
        evidence_dir,
        "requirement_retrieval_ab_cases",
        case_rows,
        lambda row: (row["dataset"], row["case_id"]),
    )
    report["artifacts"] = {
        "query_embeddings": {
            "path": _relative(root, embedding_path),
            "sha256": embedding_sha,
            "row_count": len(requests),
            "dimension": embeddings.shape[1],
        },
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
    report_path = reports_dir / f"requirement_retrieval_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"requirement_retrieval_ab_{markdown_sha}.md"
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
            "report": {
                "path": _relative(root, report_path),
                "sha256": report_sha,
            },
            "markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "configuration": report["configuration"],
        "model": {key: value for key, value in model_meta.items() if key != "model_load_ms"},
        "scope": report["scope"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = retrieval_dir / f"requirement_retrieval_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    after = {name: file_sha256(path) for name, path in input_paths.items()}
    changed = sorted(name for name in before if before[name] != after[name])
    if changed:
        raise RuntimeError(f"Inputs changed during requirement retrieval A/B: {changed}")
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
        description="Run requirement-query hybrid retrieval A/B without promotion"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(
        json.dumps(
            evaluate_and_freeze(
                args.root,
                device=args.device,
                batch_size=args.batch_size,
                evaluated_at=args.evaluated_at,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
