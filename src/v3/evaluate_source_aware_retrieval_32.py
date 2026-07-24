from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_bm25 import SearchPolicy
from src.v3.evaluate_grounded_llm_replay import (
    DEFAULT_BASELINE_CASES,
    DEFAULT_REVIEWED,
    DEFAULT_TEMPORAL,
)
from src.v3.evaluate_requirement_reranker import requirement_text
from src.v3.gradio_backbone_demo import (
    DEFAULT_AS_OF,
    DemoBackbone,
    filter_hits_by_global_temporal,
)
from src.v3.retrieve_v3 import retrieve_with_embedding


EVALUATOR_VERSION = "source-aware-retrieval-32-v1"
SOURCE_DEPTH = 10
SOURCE_QUOTA = 3
PARENT_CAP = 2
ARM_DEPTHS = (3, 5, 8)
SOURCE_BALANCED_ARM = "source_balanced_top_1_per_source"
UNION_ARM = "baseline_union_source_aware_top_5"
DEFAULT_OUTPUT = Path("outputs/v3/source_aware_retrieval_32.jsonl")
DEFAULT_SUMMARY = Path("reports/v3/source_aware_retrieval_32.json")


def select_ranked_candidates(
    hits: list[dict[str, Any]],
    scores: list[float],
    *,
    top_k: int,
    parent_cap: int = PARENT_CAP,
) -> list[dict[str, Any]]:
    if len(hits) != len(scores):
        raise RuntimeError("Candidate and reranker score counts differ")
    ranked = sorted(
        ({**hit, "reranker_score": round(float(score), 8)} for hit, score in zip(hits, scores, strict=True)),
        key=lambda row: (-row["reranker_score"], row["source_id"], row["chunk_id"]),
    )
    selected = []
    seen_chunks: set[str] = set()
    parent_counts: Counter[str] = Counter()
    for row in ranked:
        if row["chunk_id"] in seen_chunks:
            continue
        if parent_counts[row["parent_document_id"]] >= parent_cap:
            continue
        seen_chunks.add(row["chunk_id"])
        parent_counts[row["parent_document_id"]] += 1
        selected.append(row)
        if len(selected) >= top_k:
            break
    return selected


def score_requirement_pools(
    reviewed: dict[str, Any],
    pools: list[dict[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    if len(pools) != len(reviewed["evidence_groups"]):
        raise RuntimeError("Requirement pool count differs from reviewed evidence groups")
    groups = []
    for evidence_group, pool in zip(reviewed["evidence_groups"], pools, strict=True):
        candidate_ids = set(pool[arm]["candidate_chunk_ids"])
        acceptable_ids = set(evidence_group["acceptable_chunk_ids"])
        groups.append(
            {
                "requirement_id": pool["requirement_id"],
                "group_id": evidence_group["group_id"],
                "candidate_present": bool(candidate_ids & acceptable_ids),
            }
        )
    return {
        "all_required_candidates_present": all(row["candidate_present"] for row in groups),
        "groups": groups,
    }


def _arm_name(depth: int) -> str:
    return f"source_aware_top_{depth}"


def evaluate(
    *,
    root: Path,
    reviewed_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    baseline_by_id = {row["candidate_id"]: row for row in baseline_rows}
    if {row["candidate_id"] for row in reviewed_rows} != set(baseline_by_id):
        raise RuntimeError("Reviewed and baseline candidate IDs differ")

    demo = DemoBackbone(root=root, planner_model="qwen3:8b", enable_v3_2_candidates=True)
    demo._initialize()
    assert demo._artifacts is not None
    source_ids = sorted({row["source_id"] for row in demo._artifacts.chunks_by_id.values()})
    output = []
    for case_index, reviewed in enumerate(reviewed_rows, 1):
        started = time.perf_counter()
        requirement_pools = []
        baseline = baseline_by_id[reviewed["candidate_id"]]
        baseline_candidate_ids = list(baseline["arm0"]["candidate_chunk_ids"])
        for requirement in reviewed["requirements"]:
            query = requirement_text(requirement)
            embedding = demo._encode(query)
            pooled = []
            source_balanced = []
            source_hit_counts = {}
            for source_id in source_ids:
                policy = SearchPolicy(
                    default_exposure_only=True,
                    allowed_statuses=("current", "upcoming"),
                    include_review_required=False,
                    as_of=as_of,
                    source_ids=(source_id,),
                )
                hits = retrieve_with_embedding(
                    query,
                    embedding,
                    demo._artifacts,
                    top_k=SOURCE_DEPTH,
                    policy=policy,
                )
                hits, _ = filter_hits_by_global_temporal(
                    hits,
                    time_scope=reviewed["time_scope"],
                    temporal_by_document=demo._global_temporal_by_document,
                )
                source_hits = hits[:SOURCE_QUOTA]
                source_hit_counts[source_id] = len(source_hits)
                pooled.extend(source_hits)
                if source_hits:
                    source_balanced.append(source_hits[0])
            scores = demo._score_pairs(
                [
                    (query, demo._artifacts.chunks_by_id[hit["chunk_id"]]["retrieval_text"])
                    for hit in pooled
                ]
            )
            pool = {
                "requirement_id": requirement["requirement_id"],
                "query": query,
                "source_hit_counts": source_hit_counts,
            }
            for depth in ARM_DEPTHS:
                selected = select_ranked_candidates(pooled, scores, top_k=depth)
                pool[_arm_name(depth)] = {
                    "candidate_chunk_ids": [row["chunk_id"] for row in selected],
                    "candidates": [
                        {
                            key: row[key]
                            for key in (
                                "chunk_id",
                                "parent_document_id",
                                "source_id",
                                "reranker_score",
                            )
                        }
                        for row in selected
                    ],
                }
            pool[SOURCE_BALANCED_ARM] = {
                "candidate_chunk_ids": [row["chunk_id"] for row in source_balanced],
                "candidates": [
                    {
                        key: row[key]
                        for key in ("chunk_id", "parent_document_id", "source_id")
                    }
                    for row in source_balanced
                ],
            }
            union_ids = list(
                dict.fromkeys(
                    baseline_candidate_ids
                    + pool[_arm_name(5)]["candidate_chunk_ids"]
                )
            )
            pool[UNION_ARM] = {"candidate_chunk_ids": union_ids}
            requirement_pools.append(pool)
        row = {
            "candidate_id": reviewed["candidate_id"],
            "question_text": reviewed["question_text"],
            "expected_source_id_used_for_scoring_only": baseline["source_id"],
            "gold_available_to_retrieval_or_reranker": False,
            "source_ids_searched": source_ids,
            "requirement_candidate_pools": requirement_pools,
            "baseline": {
                "candidate_chunk_ids": baseline["arm0"]["candidate_chunk_ids"],
                "candidate_all_required_coverage": baseline["arm0_score"][
                    "candidate_all_groups_covered"
                ],
            },
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        for depth in ARM_DEPTHS:
            arm = _arm_name(depth)
            row[arm] = score_requirement_pools(reviewed, requirement_pools, arm=arm)
        for arm in (SOURCE_BALANCED_ARM, UNION_ARM):
            row[arm] = score_requirement_pools(reviewed, requirement_pools, arm=arm)
        output.append(row)
        print(f"source-aware retrieval {case_index}/{len(reviewed_rows)}", flush=True)
    return output


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    baseline_success = {
        row["candidate_id"]
        for row in rows
        if row["baseline"]["candidate_all_required_coverage"]
    }
    arms = {}
    arm_names = [*(_arm_name(depth) for depth in ARM_DEPTHS), SOURCE_BALANCED_ARM, UNION_ARM]
    for arm in arm_names:
        successes = {
            row["candidate_id"]
            for row in rows
            if row[arm]["all_required_candidates_present"]
        }
        arms[arm] = {
            "successes": len(successes),
            "total": total,
            "rate": round(len(successes) / total, 6) if total else 0.0,
            "improvement_case_ids": sorted(successes - baseline_success),
            "regression_case_ids": sorted(baseline_success - successes),
        }
    eligible = [
        arm
        for arm, metrics in arms.items()
        if metrics["successes"] > len(baseline_success) and not metrics["regression_case_ids"]
    ]
    eligible.sort(key=lambda arm: (-arms[arm]["successes"], arm_names.index(arm)))
    return {
        "evaluation_role": "adaptive_32_source_aware_retrieval_ab_not_blind",
        "evaluator_version": EVALUATOR_VERSION,
        "baseline": {
            "successes": len(baseline_success),
            "total": total,
            "rate": round(len(baseline_success) / total, 6) if total else 0.0,
        },
        "arms": arms,
        "selected_arm_for_stage3": eligible[0] if eligible else None,
        "decision": "GO_TO_STAGE3" if eligible else "NO_GO",
        "constraints": {
            "gold_available_to_retrieval_or_reranker": False,
            "all_sources_searched_independently": True,
            "temporal_status_filter_applied": True,
            "new_domain_keyword_rules": 0,
            "runtime_or_canonical_promoted": False,
        },
        "total_latency_ms": round(sum(row["latency_ms"] for row in rows), 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--baseline-cases", type=Path, default=DEFAULT_BASELINE_CASES)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def _rooted(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    rows = evaluate(
        root=root,
        reviewed_rows=read_jsonl(_rooted(root, args.reviewed)),
        baseline_rows=read_jsonl(_rooted(root, args.baseline_cases)),
        as_of=args.as_of,
    )
    summary = summarize(rows)
    output_path = _rooted(root, args.output)
    summary_path = _rooted(root, args.summary)
    write_jsonl(output_path, rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output_path), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
