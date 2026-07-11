from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from retrieve import apply_reranker, retrieve
from retrieval_config import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RANK_MODE,
    DEFAULT_RERANKER_BATCH_SIZE,
    DEFAULT_RERANKER_MAX_LENGTH,
    DEFAULT_RERANKER_MODEL,
    RANK_MODES,
)


DEFAULT_CUTOFFS = (1, 3, 5, 10)


def parent_doc_id(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") or {}
    return str(metadata.get("parent_doc_id") or hit.get("doc_id"))


def expected_match_ids(row: dict[str, Any]) -> tuple[list[str], str]:
    chunk_ids = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        chunk_ids = [str(row["expected_chunk_id"])]
    if chunk_ids:
        return chunk_ids, "chunk"
    parent_ids = [str(item) for item in row.get("expected_evidence_doc_ids", []) if item]
    return parent_ids, "parent_doc"


def min_gold_rank(retrieved_ids: list[str], expected_ids: list[str]) -> int | None:
    ranks = [retrieved_ids.index(expected_id) + 1 for expected_id in expected_ids if expected_id in retrieved_ids]
    return min(ranks) if ranks else None


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"

    rows = read_jsonl(args.eval_set)
    answerable = [row for row in rows if expected_match_ids(row)[0]]

    cutoffs = sorted(set(DEFAULT_CUTOFFS))
    before_hits = {c: 0 for c in cutoffs}
    after_hits = {c: 0 for c in cutoffs}
    before_mrr = 0.0
    after_mrr = 0.0
    before_ranks: Counter[str] = Counter()
    after_ranks: Counter[str] = Counter()
    details = []

    for row in answerable:
        hits = retrieve(
            row["question"],
            persist_dir=args.persist_dir,
            top_k=args.candidate_top_k,
            model_name=args.model_name,
            candidate_k=args.candidate_k,
            rank_mode=args.rank_mode,
        )
        expected_ids, match_scope = expected_match_ids(row)

        def match_ids(ordered_hits: list[dict[str, Any]]) -> list[str]:
            if match_scope == "chunk":
                return [str(hit["doc_id"]) for hit in ordered_hits]
            return [parent_doc_id(hit) for hit in ordered_hits]

        reranked = apply_reranker(
            row["question"],
            hits,
            args.reranker_model,
            max_length=args.reranker_max_length,
            batch_size=args.reranker_batch_size,
        )

        rank_before = min_gold_rank(match_ids(hits), expected_ids)
        rank_after = min_gold_rank(match_ids(reranked), expected_ids)
        before_ranks[f"rank_{rank_before}" if rank_before else "missing"] += 1
        after_ranks[f"rank_{rank_after}" if rank_after else "missing"] += 1
        for c in cutoffs:
            before_hits[c] += int(rank_before is not None and rank_before <= c)
            after_hits[c] += int(rank_after is not None and rank_after <= c)
        before_mrr += (1.0 / rank_before) if (rank_before and rank_before <= 10) else 0.0
        after_mrr += (1.0 / rank_after) if (rank_after and rank_after <= 10) else 0.0

        details.append(
            {
                "eval_id": row.get("eval_id"),
                "question": row.get("question"),
                "gold_rank_before": rank_before,
                "gold_rank_after": rank_after,
            }
        )

    total = len(answerable)
    summary: dict[str, Any] = {
        "answerable_rows": total,
        "reranker_model": args.reranker_model,
        "reranker_max_length": args.reranker_max_length,
        "reranker_batch_size": args.reranker_batch_size,
        "candidate_top_k": args.candidate_top_k,
        "candidate_k": args.candidate_k,
        "embedding_model_name": args.model_name,
        "rank_mode": args.rank_mode,
        "device": device,
        "mrr@10_before": before_mrr / total,
        "mrr@10_after": after_mrr / total,
        "gold_rank_distribution_before": dict(sorted(before_ranks.items())),
        "gold_rank_distribution_after": dict(sorted(after_ranks.items())),
    }
    for c in cutoffs:
        summary[f"hit_rate@{c}_before"] = before_hits[c] / total
        summary[f"hit_rate@{c}_after"] = after_hits[c] / total

    return {
        "eval_set": str(args.eval_set),
        "persist_dir": str(args.persist_dir),
        "summary": summary,
        "details": details,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A/B a cross-encoder reranker over dense+lexical retrieval.")
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma_domain_chunks"))
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--candidate-top-k", type=int, default=20)
    parser.add_argument("--candidate-k", type=int, default=DEFAULT_CANDIDATE_K)
    parser.add_argument("--reranker-max-length", type=int, default=DEFAULT_RERANKER_MAX_LENGTH)
    parser.add_argument("--reranker-batch-size", type=int, default=DEFAULT_RERANKER_BATCH_SIZE)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = evaluate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in report.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
