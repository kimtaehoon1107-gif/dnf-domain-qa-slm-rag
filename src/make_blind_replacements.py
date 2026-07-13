from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from make_blind_test_candidate import (
    add_review_fields,
    enrich_pool,
    expected_chunk_ids,
    expected_parent_ids,
    select_balanced,
)
from make_domain_expanded_data import (
    candidate_rows,
    normalize_space,
    parent_id,
)


def blocked_values(rows: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str], set[str]]:
    parents = {parent for row in rows for parent in expected_parent_ids(row)}
    chunks = {chunk for row in rows for chunk in expected_chunk_ids(row)}
    questions = {
        normalize_space(row.get("question", "")).lower()
        for row in rows
        if row.get("question")
    }
    spans = {
        normalize_space(row.get("evidence_span", "")).lower()
        for row in rows
        if row.get("evidence_span")
    }
    return parents, chunks, questions, spans


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create leakage-safe blind replacement candidates.")
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument(
        "--train-qa", type=Path, default=Path("data/processed/domain_train_qa_measurement_fixed.jsonl")
    )
    parser.add_argument(
        "--existing-eval-set",
        type=Path,
        nargs="+",
        default=[
            Path("data/processed/domain_eval_set_expanded.jsonl"),
            Path("data/processed/official_eval_set.jsonl"),
            Path("data/processed/fresh_paraphrase_eval_set.jsonl"),
        ],
    )
    parser.add_argument("--reviewed-candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--true-rows", type=int, default=1)
    parser.add_argument("--partial-rows", type=int, default=3)
    parser.add_argument("--span-max-chars", type=int, default=200)
    parser.add_argument("--preferred-true-chunks", nargs="*", default=[])
    parser.add_argument("--preferred-partial-chunks", nargs="*", default=[])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    chunks = read_jsonl(args.chunks)
    train_rows = read_jsonl(args.train_qa)
    eval_rows = [row for path in args.existing_eval_set for row in read_jsonl(path)]
    candidate_rows_existing = read_jsonl(args.reviewed_candidate)
    blocked_rows = train_rows + eval_rows + candidate_rows_existing
    blocked_parents, blocked_chunks, blocked_questions, blocked_spans = blocked_values(blocked_rows)
    seen_questions = set(blocked_questions)
    seen_spans = set(blocked_spans)
    chunks_by_id = {str(chunk["doc_id"]): chunk for chunk in chunks}
    available_parents = {parent_id(chunk) for chunk in chunks} - blocked_parents

    partial_pool = enrich_pool(
        candidate_rows(chunks, available_parents, "partial", "blind_replacement", 1.0, 8, args.span_max_chars),
        chunks_by_id,
        partial=True,
    )
    true_pool = enrich_pool(
        candidate_rows(chunks, available_parents, "true", "blind_replacement", 1.0, 8, args.span_max_chars),
        chunks_by_id,
        partial=False,
    )
    parent_counts: dict[str, int] = defaultdict(int)
    if args.preferred_true_chunks or args.preferred_partial_chunks:
        def select_chunks(pool: list[dict[str, Any]], chunk_ids: list[str]) -> list[dict[str, Any]]:
            first_by_chunk: dict[str, dict[str, Any]] = {}
            for row in pool:
                chunk_id = str(row.get("expected_chunk_id", ""))
                if chunk_id and chunk_id not in first_by_chunk:
                    first_by_chunk[chunk_id] = row
            missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in first_by_chunk]
            if missing:
                raise RuntimeError(
                    f"Preferred chunks are not available in the leakage-safe pool: {missing}"
                )
            return [first_by_chunk[chunk_id] for chunk_id in chunk_ids]

        true = select_chunks(true_pool, args.preferred_true_chunks)
        partial = select_chunks(partial_pool, args.preferred_partial_chunks)
    else:
        partial = select_balanced(
            partial_pool,
            args.partial_rows,
            parent_counts,
            seen_questions,
            seen_spans,
            max_per_parent=1,
        )
        true = select_balanced(
            true_pool,
            args.true_rows,
            parent_counts,
            seen_questions,
            seen_spans,
            max_per_parent=1,
        )
    if len(true) != args.true_rows or len(partial) != args.partial_rows:
        raise RuntimeError(
            f"Insufficient replacement drafts: true={len(true)}/{args.true_rows}, "
            f"partial={len(partial)}/{args.partial_rows}."
        )

    rows = add_review_fields(true + partial)
    for index, row in enumerate(rows, start=1):
        row["eval_id"] = f"blind_v1_replacement_{index:04d}"
        row["evaluation_role"] = "blind_test_replacement_candidate"
        row["source_split"] = "blind_replacement"

    output_parents, output_chunks, output_questions, _ = blocked_values(rows)
    if (
        output_parents & blocked_parents
        or output_chunks & blocked_chunks
        or output_questions & blocked_questions
    ):
        raise RuntimeError("Replacement candidate overlaps blocked train/eval/blind data.")

    write_jsonl(args.output, rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(rows),
                "answerability_counts": dict(Counter(row["answerability"] for row in rows)),
                "available_parent_docs": len(available_parents),
                "blocked_parent_overlap": len(output_parents & blocked_parents),
                "blocked_chunk_overlap": len(output_chunks & blocked_chunks),
                "blocked_question_overlap": len(output_questions & blocked_questions),
                "model_evaluation_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
