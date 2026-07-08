from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")


def normalize_space(text: Any) -> str:
    return " ".join(str(text or "").split())


def tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) >= 2}


def chunk_parent_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("parent_doc_id") or chunk["doc_id"])


def index_chunks(chunks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        by_parent[chunk_parent_id(chunk)].append(chunk)
    return by_parent


def exact_span_matches(span: str, chunks: list[dict[str, Any]]) -> list[str]:
    normalized_span = normalize_space(span)
    if not normalized_span:
        return []
    return [
        chunk["doc_id"]
        for chunk in chunks
        if normalized_span in normalize_space(chunk.get("text", ""))
    ]


def best_overlap_match(span: str, chunks: list[dict[str, Any]]) -> tuple[str | None, float]:
    span_tokens = tokens(span)
    if not span_tokens:
        return None, 0.0
    best_id = None
    best_score = 0.0
    for chunk in chunks:
        chunk_tokens = tokens(chunk.get("text", ""))
        score = len(span_tokens & chunk_tokens) / len(span_tokens)
        if score > best_score:
            best_id = chunk["doc_id"]
            best_score = score
    return best_id, best_score


def remap_row(row: dict[str, Any], chunks_by_parent: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if row.get("answerability") == "false" or not row.get("expected_doc_id"):
        return dict(row)

    parent_id = str(row["expected_doc_id"])
    parent_chunks = chunks_by_parent.get(parent_id, [])
    if not parent_chunks:
        updated = dict(row)
        updated["original_expected_chunk_ids"] = row.get("expected_chunk_ids", [])
        updated["expected_chunk_id"] = None
        updated["expected_chunk_ids"] = []
        updated["chunk_remap_method"] = "missing_parent"
        updated["chunk_remap_score"] = 0.0
        return updated

    span = row.get("evidence_span") or row.get("gold_answer") or row.get("expected_answer") or ""
    exact_ids = exact_span_matches(span, parent_chunks)
    updated = dict(row)
    updated["original_expected_chunk_ids"] = row.get("expected_chunk_ids", [])
    if exact_ids:
        updated["expected_chunk_id"] = exact_ids[0]
        updated["expected_chunk_ids"] = exact_ids
        updated["chunk_remap_method"] = "exact_span"
        updated["chunk_remap_score"] = 1.0
        return updated

    best_id, score = best_overlap_match(span, parent_chunks)
    updated["expected_chunk_id"] = best_id
    updated["expected_chunk_ids"] = [best_id] if best_id else []
    updated["chunk_remap_method"] = "token_overlap" if best_id else "missing_span"
    updated["chunk_remap_score"] = round(score, 4)
    return updated


def remap_eval(eval_rows: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks_by_parent = index_chunks(chunks)
    return [remap_row(row, chunks_by_parent) for row in eval_rows]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remap expected eval chunk IDs to a different chunking variant.")
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/official_eval_set.jsonl"))
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.eval_set)
    chunks = read_jsonl(args.chunks)
    remapped = remap_eval(rows, chunks)
    write_jsonl(args.output, remapped)
    methods: dict[str, int] = defaultdict(int)
    for row in remapped:
        if row.get("answerability") != "false":
            methods[str(row.get("chunk_remap_method", "unchanged"))] += 1
    print(
        json.dumps(
            {
                "output": str(args.output),
                "eval_rows": len(remapped),
                "chunks": len(chunks),
                "remap_methods": dict(sorted(methods.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
