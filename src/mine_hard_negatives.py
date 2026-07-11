from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from retrieval_config import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RANK_MODE,
    DEFAULT_RERANK_CANDIDATES,
    DEFAULT_RERANKER_BATCH_SIZE,
    DEFAULT_RERANKER_MAX_LENGTH,
    DEFAULT_RERANKER_MODEL,
    RANK_MODES,
)
from retrieve import apply_reranker, retrieve


def parent_id(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") or {}
    return str(metadata.get("parent_doc_id") or row.get("parent_doc_id") or row.get("doc_id") or "")


def expected_chunk_ids(row: dict[str, Any]) -> set[str]:
    values = {str(item) for item in row.get("expected_chunk_ids", []) if item}
    if row.get("expected_chunk_id"):
        values.add(str(row["expected_chunk_id"]))
    return values


def expected_parent_ids(row: dict[str, Any]) -> set[str]:
    values = {str(item) for item in row.get("expected_evidence_doc_ids", []) if item}
    if row.get("expected_doc_id"):
        values.add(str(row["expected_doc_id"]))
    return values


def heldout_ids(rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    chunks = {chunk for row in rows for chunk in expected_chunk_ids(row)}
    parents = {parent for row in rows for parent in expected_parent_ids(row)}
    return chunks, parents


def filter_hard_negatives(
    hits: list[dict[str, Any]],
    gold_chunk_ids: set[str],
    gold_parent_ids: set[str],
    heldout_chunk_ids: set[str],
    heldout_parent_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    selected = []
    seen = set()
    for hit in hits:
        doc_id = str(hit.get("doc_id") or "")
        doc_parent = parent_id(hit)
        if not doc_id or doc_id in seen:
            continue
        if doc_id in gold_chunk_ids or doc_parent in gold_parent_ids:
            continue
        if doc_id in heldout_chunk_ids or doc_parent in heldout_parent_ids:
            continue
        seen.add(doc_id)
        selected.append(
            {
                "doc_id": doc_id,
                "parent_doc_id": doc_parent,
                "retrieval_rank": int(hit.get("rank") or len(selected) + 1),
                "rerank_score": hit.get("rerank_score"),
                "distance": hit.get("distance"),
                "lexical_score": hit.get("lexical_score"),
                "title": str(hit.get("title") or ""),
                "selection_tier": str(hit.get("selection_tier") or "unknown"),
            }
        )
        if len(selected) >= limit:
            break
    return selected


def mine(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    qa_rows = read_jsonl(args.qa)
    heldout_rows = [row for path in args.exclude_eval_set for row in read_jsonl(path)]
    heldout_chunks, heldout_parents = heldout_ids(heldout_rows)
    output_rows = []
    insufficient = []

    for index, row in enumerate(qa_rows, start=1):
        source_qa_id = str(row.get("qa_id") or row.get("eval_id") or f"row_{index:04d}")
        gold_chunks = expected_chunk_ids(row)
        gold_parents = expected_parent_ids(row)
        base_hits = retrieve(
            str(row["question"]),
            persist_dir=args.persist_dir,
            top_k=args.candidate_k,
            model_name=args.model_name,
            candidate_k=args.candidate_k,
            rank_mode=args.rank_mode,
        )
        reranked_head = apply_reranker(
            str(row["question"]),
            base_hits[: args.rerank_candidates],
            args.reranker_model,
            max_length=args.reranker_max_length,
            batch_size=args.reranker_batch_size,
        )
        hits = reranked_head + base_hits[args.rerank_candidates :]
        for rank, hit in enumerate(hits, start=1):
            hit["rank"] = rank
            hit["selection_tier"] = "reranked_head" if rank <= len(reranked_head) else "hybrid_tail"
        negatives = filter_hard_negatives(
            hits,
            gold_chunk_ids=gold_chunks,
            gold_parent_ids=gold_parents,
            heldout_chunk_ids=heldout_chunks,
            heldout_parent_ids=heldout_parents,
            limit=args.negatives_per_row,
        )
        if len(negatives) < args.negatives_per_row:
            insufficient.append(source_qa_id)
        output_rows.append(
            {
                "source_qa_id": source_qa_id,
                "question": row["question"],
                "answerability": row.get("answerability", ""),
                "gold_chunk_ids": sorted(gold_chunks),
                "gold_parent_ids": sorted(gold_parents),
                "hard_negatives": negatives,
            }
        )

    report = {
        "status": "ok" if not insufficient else "incomplete",
        "qa": str(args.qa),
        "output": str(args.output),
        "rows": len(output_rows),
        "rows_with_full_negative_count": len(output_rows) - len(insufficient),
        "insufficient_rows": insufficient,
        "excluded_eval_sets": [str(path) for path in args.exclude_eval_set],
        "excluded_heldout_chunks": len(heldout_chunks),
        "excluded_heldout_parents": len(heldout_parents),
        "config": {
            "persist_dir": str(args.persist_dir),
            "embedding_model": args.model_name,
            "rank_mode": args.rank_mode,
            "candidate_k": args.candidate_k,
            "reranker_model": args.reranker_model,
            "rerank_candidates": args.rerank_candidates,
            "reranker_max_length": args.reranker_max_length,
            "reranker_batch_size": args.reranker_batch_size,
            "negatives_per_row": args.negatives_per_row,
            "fallback": "hybrid ranks after the reranked head; never random",
        },
    }
    return output_rows, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine reranked, leakage-safe hard negatives for each QA row.")
    parser.add_argument("--qa", type=Path, default=Path("data/processed/domain_train_qa_measurement_fixed.jsonl"))
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma_domain_chunks"))
    parser.add_argument(
        "--exclude-eval-set",
        type=Path,
        nargs="+",
        default=[
            Path("data/processed/domain_eval_set_expanded.jsonl"),
            Path("data/processed/official_eval_set.jsonl"),
            Path("data/processed/fresh_paraphrase_eval_set.jsonl"),
            Path("data/review/blind_test_v1_candidate.jsonl"),
        ],
    )
    parser.add_argument("--output", type=Path, default=Path("data/processed/domain_hard_negatives.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("reports/domain_hard_negatives.json"))
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    parser.add_argument("--candidate-k", type=int, default=DEFAULT_CANDIDATE_K)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--rerank-candidates", type=int, default=DEFAULT_RERANK_CANDIDATES)
    parser.add_argument("--reranker-max-length", type=int, default=DEFAULT_RERANKER_MAX_LENGTH)
    parser.add_argument("--reranker-batch-size", type=int, default=DEFAULT_RERANKER_BATCH_SIZE)
    parser.add_argument("--negatives-per-row", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.rerank_candidates < args.negatives_per_row:
        raise ValueError("rerank_candidates must cover negatives_per_row.")
    rows, report = mine(args)
    write_jsonl(args.output, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ok":
        raise RuntimeError("Hard-negative mining produced rows with too few safe candidates.")


if __name__ == "__main__":
    main()
