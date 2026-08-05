from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_bm25 import search_bm25
from src.v3.build_dense_pilot import search_dense
from src.v3.evaluate_hybrid import DENSE_WEIGHTS, fuse_hits
from src.v3.product_candidate_identity import (
    candidate_row_from_chunk,
    reserve_then_fill,
    shortlist_document_chunks,
    shortlist_identity_documents,
)
from src.v3.product_free_rag import (
    DEFAULT_RETRIEVAL_DEPTH,
    ProductFreeRAG,
    normalize_product_question,
    search_policy_for_product_question,
)
from src.v3.retrieve_v3 import retrieve_with_embedding


DIAGNOSTIC_VERSION = "product-gold-chunk-rank-v1"
DEPTH = 200
CLEAR_SOURCE_RATE_GAP = 0.20
CLEAR_ABS_SPEARMAN = 0.30
FROZEN_A6 = Path(
    "data/v3/evaluation/"
    "product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_gold_chunk_rank_diagnostic_20260805.jsonl"
)
HUMAN_SUCCESS_SLOTS = frozenset(
    {3, 5, 8, 9, 12, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 27, 29, 30, 31}
)


def _rank(chunk_ids: list[str], gold_ids: set[str]) -> int | None:
    ranks = [
        index
        for index, chunk_id in enumerate(chunk_ids, 1)
        if chunk_id in gold_ids
    ]
    return min(ranks) if ranks else None


def _rank_bucket(rank: int | None) -> str:
    if rank is None:
        return "null"
    if rank <= 20:
        return "1_20"
    if rank <= 40:
        return "21_40"
    return "41_200"


def _rankdata(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = average_rank
        index = end
    return ranks


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right):
        raise RuntimeError("Spearman inputs differ in length")
    if len(left) < 2:
        return None
    left_ranks = _rankdata(left)
    right_ranks = _rankdata(right)
    left_mean = sum(left_ranks) / len(left_ranks)
    right_mean = sum(right_ranks) / len(right_ranks)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left_ranks, right_ranks, strict=True)
    )
    left_scale = math.sqrt(
        sum((value - left_mean) ** 2 for value in left_ranks)
    )
    right_scale = math.sqrt(
        sum((value - right_mean) ** 2 for value in right_ranks)
    )
    if left_scale == 0.0 or right_scale == 0.0:
        return None
    return round(numerator / (left_scale * right_scale), 6)


def _median_rank(values: list[int | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(float(median(present)), 3) if present else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_count": len({int(row["slot_ordinal"]) for row in rows}),
        "requirement_count": len(rows),
        "bm25_median_rank": _median_rank([row["bm25_rank"] for row in rows]),
        "dense_median_rank": _median_rank([row["dense_rank"] for row in rows]),
        "hybrid_median_rank": _median_rank(
            [row["hybrid_union_rank"] for row in rows]
        ),
        "hybrid_rank_buckets": dict(
            Counter(_rank_bucket(row["hybrid_union_rank"]) for row in rows)
        ),
        "hybrid_top20_rate": _rate(
            sum(bool(row["in_hybrid_union"]) for row in rows),
            len(rows),
        ),
        "final_candidate_rate": _rate(
            sum(bool(row["in_final_candidates"]) for row in rows),
            len(rows),
        ),
        "bm25_top200_null_count": sum(row["bm25_rank"] is None for row in rows),
        "dense_top200_null_count": sum(row["dense_rank"] is None for row in rows),
        "hybrid_top200_null_count": sum(
            row["hybrid_union_rank"] is None for row in rows
        ),
    }


def _primary_decision(failed_rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = Counter(_rank_bucket(row["hybrid_union_rank"]) for row in failed_rows)
    if not buckets:
        return {"decision": "no_supported_failed_requirements", "buckets": {}}
    largest = max(buckets.values())
    leaders = sorted(bucket for bucket, count in buckets.items() if count == largest)
    if len(leaders) != 1:
        decision = "mixed_tied_rank_buckets"
    else:
        decision = {
            "1_20": "depth_not_primary_downstream_loss",
            "21_40": "A_expand_retrieval_depth",
            "41_200": "B_or_C_depth_too_expensive",
            "null": "C_sentence_level_retrieval",
        }[leaders[0]]
    return {"decision": decision, "buckets": dict(buckets), "leaders": leaders}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure A6 gold chunk ranks without calling Qwen"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")

    frozen = read_jsonl(root / FROZEN_A6)
    if len(frozen) != 32 or {int(row["slot_ordinal"]) for row in frozen} != set(
        range(1, 33)
    ):
        raise RuntimeError("A6 frozen set must contain slots 1 through 32")
    if len(HUMAN_SUCCESS_SLOTS) != 19:
        raise RuntimeError("official A6 human success labels must contain 19 slots")

    rag = ProductFreeRAG(
        root=root,
        device=args.device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    questions = [normalize_product_question(str(row["question_text"])) for row in frozen]
    embeddings = rag._encode_queries(questions)

    chunks_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in rag._artifacts.chunks_by_id.values():
        chunks_by_parent[str(chunk["parent_document_id"])].append(chunk)

    cases = []
    requirement_rows = []
    size_rows = []
    for frozen_row, question, embedding in zip(
        frozen, questions, embeddings, strict=True
    ):
        slot = int(frozen_row["slot_ordinal"])
        human_result = "success" if slot in HUMAN_SUCCESS_SLOTS else "failure"
        policy = search_policy_for_product_question(
            question,
            default_as_of=str(frozen_row["as_of"]),
        )
        bm25_hits = search_bm25(
            rag._artifacts.bm25_index,
            question,
            top_k=DEPTH,
            policy=policy,
        )
        dense_hits = search_dense(
            rag._artifacts.dense_embeddings,
            rag._artifacts.dense_metadata,
            embedding,
            top_k=DEPTH,
            policy=policy,
        )
        expanded_hybrid = fuse_hits(
            bm25_hits,
            dense_hits,
            dense_weight=DENSE_WEIGHTS[-1],
            top_k=len({row["chunk_id"] for row in [*bm25_hits, *dense_hits]}),
        )
        runtime_hybrid = retrieve_with_embedding(
            question,
            embedding,
            rag._artifacts,
            top_k=DEFAULT_RETRIEVAL_DEPTH,
            policy=policy,
        )

        shortlisted_documents = shortlist_identity_documents(
            question,
            documents_by_id=rag._artifacts.documents_by_id,
            chunks_by_parent=chunks_by_parent,
        )
        shortlisted_chunks = shortlist_document_chunks(
            question,
            shortlisted_documents,
            chunks_by_parent=chunks_by_parent,
        )
        union_by_chunk = {str(row["chunk_id"]): row for row in runtime_hybrid}
        identity_ids = set()
        for chunk in shortlisted_chunks:
            chunk_id = str(chunk["chunk_id"])
            if chunk_id not in union_by_chunk:
                identity_ids.add(chunk_id)
                union_by_chunk[chunk_id] = candidate_row_from_chunk(
                    chunk,
                    rag._artifacts.documents_by_id[chunk["parent_document_id"]],
                    fallback_rank=DEFAULT_RETRIEVAL_DEPTH + 1,
                )
        reranker_input = list(union_by_chunk.values())
        scores = rag._score_pairs(
            [
                (
                    question,
                    rag._artifacts.chunks_by_id[row["chunk_id"]]["retrieval_text"],
                )
                for row in reranker_input
            ]
        )
        reranked = sorted(
            (
                {**row, "reranker_score": round(float(score), 8)}
                for row, score in zip(reranker_input, scores, strict=True)
            ),
            key=lambda row: (
                -float(row["reranker_score"]),
                int(row.get("rank") or 0),
                str(row["chunk_id"]),
            ),
        )
        reserved = []
        for document in shortlisted_documents:
            parent_id = str(document["document_id"])
            parent_rows = [
                row
                for row in reranked
                if str(row["parent_document_id"]) == parent_id
            ]
            if parent_rows:
                reserved.append([parent_rows[0]])
        final_candidates = reserve_then_fill(reserved, reranked)

        bm25_ids = [str(row["chunk_id"]) for row in bm25_hits]
        dense_ids = [str(row["chunk_id"]) for row in dense_hits]
        expanded_ids = [str(row["chunk_id"]) for row in expanded_hybrid]
        runtime_ids = [str(row["chunk_id"]) for row in runtime_hybrid]
        reranked_ids = [str(row["chunk_id"]) for row in reranked]
        final_ids = [str(row["chunk_id"]) for row in final_candidates]
        case_requirements = []
        for requirement in frozen_row["requirements"]:
            gold_units = list(requirement.get("acceptable_evidence_units") or [])
            if not gold_units:
                continue
            gold_ids = {str(unit["chunk_id"]) for unit in gold_units}
            source_ids = sorted({str(unit["source_id"]) for unit in gold_units})
            gold_chunk_details = []
            for unit in gold_units:
                chunk_id = str(unit["chunk_id"])
                chunk = rag._artifacts.chunks_by_id[chunk_id]
                chunk_length = len(str(chunk.get("display_text") or ""))
                evidence_length = len(str(unit.get("text") or ""))
                signal_ratio = (
                    round(evidence_length / chunk_length, 8) if chunk_length else None
                )
                detail = {
                    "chunk_id": chunk_id,
                    "source_id": str(unit["source_id"]),
                    "chunk_length": chunk_length,
                    "evidence_length": evidence_length,
                    "signal_ratio": signal_ratio,
                    "bm25_rank": _rank(bm25_ids, {chunk_id}),
                    "dense_rank": _rank(dense_ids, {chunk_id}),
                    "hybrid_union_rank": _rank(expanded_ids, {chunk_id}),
                }
                gold_chunk_details.append(detail)
                size_rows.append(
                    {
                        "slot_ordinal": slot,
                        "human_result": human_result,
                        "requirement_id": str(requirement["requirement_id"]),
                        **detail,
                    }
                )
            row = {
                "slot_ordinal": slot,
                "human_result": human_result,
                "requirement_id": str(requirement["requirement_id"]),
                "source_ids": source_ids,
                "gold_chunk_ids": sorted(gold_ids),
                "bm25_rank": _rank(bm25_ids, gold_ids),
                "dense_rank": _rank(dense_ids, gold_ids),
                "hybrid_union_rank": _rank(expanded_ids, gold_ids),
                "in_hybrid_union": _rank(runtime_ids, gold_ids) is not None,
                "runtime_hybrid_rank": _rank(runtime_ids, gold_ids),
                "identity_injected": bool(gold_ids & identity_ids),
                "reranker_rank": _rank(reranked_ids, gold_ids),
                "in_final_candidates": _rank(final_ids, gold_ids) is not None,
                "final_candidate_rank": _rank(final_ids, gold_ids),
                "gold_chunks": gold_chunk_details,
            }
            case_requirements.append(row)
            requirement_rows.append(row)

        final_source_distribution = dict(
            Counter(str(row["source_id"]) for row in final_candidates)
        )
        gold_source_ids = sorted(
            {
                source_id
                for requirement in case_requirements
                for source_id in requirement["source_ids"]
            }
        )
        cases.append(
            {
                "type": "case",
                "slot_ordinal": slot,
                "question": question,
                "human_result": human_result,
                "supported_requirement_count": len(case_requirements),
                "requirements": case_requirements,
                "final_candidates": [
                    {
                        "rank": index,
                        "chunk_id": str(row["chunk_id"]),
                        "source_id": str(row["source_id"]),
                        "parent_document_id": str(row["parent_document_id"]),
                        "title": str(row.get("title") or ""),
                    }
                    for index, row in enumerate(final_candidates, 1)
                ],
                "final_source_distribution": final_source_distribution,
                "gold_source_ids": gold_source_ids,
                "gold_source_absent_from_final": bool(gold_source_ids)
                and not bool(set(gold_source_ids) & set(final_source_distribution)),
            }
        )
        print(
            json.dumps(
                {
                    "slot": slot,
                    "human_result": human_result,
                    "supported_requirements": len(case_requirements),
                    "gold_in_final": sum(
                        bool(row["in_final_candidates"]) for row in case_requirements
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in requirement_rows:
        for source_id in row["source_ids"]:
            source_groups[source_id].append(row)
    source_summary = {}
    for source_id, rows in sorted(source_groups.items()):
        source_summary[source_id] = {
            "case_count": len({int(row["slot_ordinal"]) for row in rows}),
            "requirement_count": len(rows),
            "hybrid_union_entry_rate": _rate(
                sum(bool(row["in_hybrid_union"]) for row in rows), len(rows)
            ),
            "final_candidate_entry_rate": _rate(
                sum(bool(row["in_final_candidates"]) for row in rows), len(rows)
            ),
            "hybrid_median_rank": _median_rank(
                [row["hybrid_union_rank"] for row in rows]
            ),
            "hybrid_top200_null_count": sum(
                row["hybrid_union_rank"] is None for row in rows
            ),
        }

    policy_rows = source_groups.get("dnf_account_policy", [])
    other_rows = [
        row
        for row in requirement_rows
        if "dnf_account_policy" not in row["source_ids"]
    ]
    policy_union_rate = _rate(
        sum(bool(row["in_hybrid_union"]) for row in policy_rows), len(policy_rows)
    )
    other_union_rate = _rate(
        sum(bool(row["in_hybrid_union"]) for row in other_rows), len(other_rows)
    )
    policy_final_rate = _rate(
        sum(bool(row["in_final_candidates"]) for row in policy_rows), len(policy_rows)
    )
    other_final_rate = _rate(
        sum(bool(row["in_final_candidates"]) for row in other_rows), len(other_rows)
    )
    union_gap = (
        round(other_union_rate - policy_union_rate, 6)
        if policy_union_rate is not None and other_union_rate is not None
        else None
    )
    final_gap = (
        round(other_final_rate - policy_final_rate, 6)
        if policy_final_rate is not None and other_final_rate is not None
        else None
    )

    censored_hybrid_ranks = [
        float(row["hybrid_union_rank"] or (DEPTH + 1)) for row in size_rows
    ]
    chunk_length_correlation = _spearman(
        [float(row["chunk_length"]) for row in size_rows], censored_hybrid_ranks
    )
    signal_ratio_correlation = _spearman(
        [float(row["signal_ratio"] or 0.0) for row in size_rows],
        censored_hybrid_ranks,
    )
    failed_rows = [row for row in requirement_rows if row["human_result"] == "failure"]
    zero_source_cases = [
        {
            "slot_ordinal": row["slot_ordinal"],
            "human_result": row["human_result"],
            "gold_source_ids": row["gold_source_ids"],
            "final_source_distribution": row["final_source_distribution"],
        }
        for row in cases
        if row["gold_source_absent_from_final"]
    ]
    top200_missing = [
        {
            "slot_ordinal": row["slot_ordinal"],
            "human_result": row["human_result"],
            "requirement_id": row["requirement_id"],
            "source_ids": row["source_ids"],
            "bm25_rank": row["bm25_rank"],
            "dense_rank": row["dense_rank"],
            "hybrid_union_rank": row["hybrid_union_rank"],
        }
        for row in requirement_rows
        if row["bm25_rank"] is None and row["dense_rank"] is None
    ]
    summary = {
        "type": "summary",
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "status": "diagnostic_complete_no_runtime_change",
        "case_count": len(cases),
        "supported_requirement_count": len(requirement_rows),
        "unsupported_requirement_count": sum(
            not requirement.get("acceptable_evidence_units")
            for row in frozen
            for requirement in row["requirements"]
        ),
        "qwen_calls": 0,
        "runtime_modified": False,
        "measurement_depth": DEPTH,
        "success_label_source": "official_a6_human_adjudication_19_of_32",
        "instruction_20_of_32_conflict": True,
        "preregistered_operational_thresholds": {
            "clear_source_rate_gap": CLEAR_SOURCE_RATE_GAP,
            "clear_abs_spearman": CLEAR_ABS_SPEARMAN,
            "primary_branch_rule": "largest_failed_requirement_hybrid_rank_bucket_ties_mixed",
        },
        "d1": {
            "success": _distribution(
                [row for row in requirement_rows if row["human_result"] == "success"]
            ),
            "failure": _distribution(failed_rows),
            "overall": _distribution(requirement_rows),
            "top200_missing_both_systems": top200_missing,
        },
        "d2": {
            "by_source": source_summary,
            "account_policy_vs_other": {
                "account_policy_requirement_count": len(policy_rows),
                "other_requirement_count": len(other_rows),
                "account_policy_union_rate": policy_union_rate,
                "other_union_rate": other_union_rate,
                "union_rate_gap": union_gap,
                "account_policy_final_rate": policy_final_rate,
                "other_final_rate": other_final_rate,
                "final_rate_gap": final_gap,
                "clearly_lower": bool(
                    max(union_gap or 0.0, final_gap or 0.0)
                    >= CLEAR_SOURCE_RATE_GAP
                ),
            },
        },
        "d3": {
            "observation_count": len(size_rows),
            "null_rank_censor_value": DEPTH + 1,
            "chunk_length_vs_hybrid_rank_spearman": chunk_length_correlation,
            "signal_ratio_vs_hybrid_rank_spearman": signal_ratio_correlation,
            "clear_chunk_length_relationship": bool(
                chunk_length_correlation is not None
                and chunk_length_correlation >= CLEAR_ABS_SPEARMAN
            ),
            "clear_signal_ratio_relationship": bool(
                signal_ratio_correlation is not None
                and signal_ratio_correlation <= -CLEAR_ABS_SPEARMAN
            ),
        },
        "d4": {
            "gold_source_absent_case_count": len(zero_source_cases),
            "gold_source_absent_cases": zero_source_cases,
        },
        "decision": {
            "primary": _primary_decision(failed_rows),
            "account_policy_series_problem": bool(
                max(union_gap or 0.0, final_gap or 0.0)
                >= CLEAR_SOURCE_RATE_GAP
            ),
            "chunk_size_problem": bool(
                chunk_length_correlation is not None
                and chunk_length_correlation >= CLEAR_ABS_SPEARMAN
            ),
        },
    }
    write_jsonl(output, [*cases, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
