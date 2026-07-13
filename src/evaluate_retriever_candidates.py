from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from retrieve import retrieve
from retrieval_config import DEFAULT_EMBEDDING_MODEL, DEFAULT_RANK_MODE, RANK_MODES


DEFAULT_CUTOFFS = (3, 5, 10, 20)


def parent_doc_id(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") or {}
    return str(metadata.get("parent_doc_id") or hit.get("doc_id"))


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    values = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        values = [str(row["expected_chunk_id"])]
    return values


def expected_match_ids(row: dict[str, Any]) -> tuple[list[str], str]:
    chunk_ids = expected_chunk_ids(row)
    if chunk_ids:
        return chunk_ids, "chunk"
    parent_ids = [str(item) for item in row.get("expected_evidence_doc_ids", []) if item]
    return parent_ids, "parent_doc"


def min_gold_rank(retrieved_ids: list[str], expected_ids: list[str]) -> int | None:
    ranks = [retrieved_ids.index(expected_id) + 1 for expected_id in expected_ids if expected_id in retrieved_ids]
    return min(ranks) if ranks else None


def reciprocal_rank_at(rank: int | None, cutoff: int) -> float:
    if rank is None or rank > cutoff:
        return 0.0
    return 1.0 / rank


def evaluate_candidates(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.eval_set)
    answerable_rows = [row for row in rows if expected_match_ids(row)[0]]
    if not answerable_rows:
        raise ValueError("Evaluation set has no rows with expected evidence IDs.")

    cutoffs = sorted({int(item) for item in args.cutoffs})
    top_k = max(cutoffs)
    details = []
    rank_counter: Counter[str] = Counter()
    hit_totals = {cutoff: 0 for cutoff in cutoffs}
    mrr_at_10_total = 0.0
    query_latencies = []

    if not args.skip_warmup:
        retrieve(
            answerable_rows[0]["question"],
            persist_dir=args.persist_dir,
            top_k=top_k,
            model_name=args.model_name,
            candidate_k=args.candidate_k,
            rank_mode=args.rank_mode,
        )

    for row in answerable_rows:
        started_at = time.perf_counter()
        hits = retrieve(
            row["question"],
            persist_dir=args.persist_dir,
            top_k=top_k,
            model_name=args.model_name,
            candidate_k=args.candidate_k,
            rank_mode=args.rank_mode,
        )
        query_latencies.append(time.perf_counter() - started_at)
        expected_ids, match_scope = expected_match_ids(row)
        retrieved_chunk_ids = [str(hit["doc_id"]) for hit in hits]
        retrieved_parent_ids = [parent_doc_id(hit) for hit in hits]
        retrieved_match_ids = retrieved_chunk_ids if match_scope == "chunk" else retrieved_parent_ids
        gold_rank = min_gold_rank(retrieved_match_ids, expected_ids)
        rank_bucket = f"rank_{gold_rank}" if gold_rank is not None else "missing"
        rank_counter[rank_bucket] += 1

        hit_by_cutoff = {}
        for cutoff in cutoffs:
            hit = gold_rank is not None and gold_rank <= cutoff
            hit_by_cutoff[f"hit@{cutoff}"] = hit
            hit_totals[cutoff] += int(hit)
        mrr_at_10_total += reciprocal_rank_at(gold_rank, cutoff=10)

        details.append(
            {
                "eval_id": row.get("eval_id"),
                "question": row.get("question"),
                "answerability": row.get("answerability"),
                "match_scope": match_scope,
                "expected_ids": expected_ids,
                "gold_rank": gold_rank,
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "retrieved_parent_ids": retrieved_parent_ids,
                **hit_by_cutoff,
            }
        )

    total = len(answerable_rows)
    sorted_latencies = sorted(query_latencies)
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    summary = {
        "answerable_rows": total,
        "rank_mode": args.rank_mode,
        "top_k_single_retrieve": top_k,
        "candidate_k": args.candidate_k,
        "mrr@10": mrr_at_10_total / total,
        "avg_query_latency_sec": sum(query_latencies) / total,
        "p95_query_latency_sec": sorted_latencies[p95_index],
        "latency_excludes_model_load": not args.skip_warmup,
        "gold_rank_distribution": dict(sorted(rank_counter.items())),
    }
    for cutoff in cutoffs:
        summary[f"hit_rate@{cutoff}"] = hit_totals[cutoff] / total

    return {
        "eval_set": str(args.eval_set),
        "persist_dir": str(args.persist_dir),
        "model_name": args.model_name,
        "summary": summary,
        "details": details,
    }


def parse_cutoffs(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retriever candidate recall from one top-k retrieval pass.")
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--persist-dir", type=Path, required=True)
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--cutoffs", type=parse_cutoffs, default=DEFAULT_CUTOFFS)
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = evaluate_candidates(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in report.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
