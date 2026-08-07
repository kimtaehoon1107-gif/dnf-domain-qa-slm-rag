from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, search_bm25
from src.v3.build_corpus import file_sha256


DEFAULT_INDEX = Path(
    "data/v3/indexes/"
    "bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
VALID_STATUSES = ("current", "upcoming", "expired", "superseded", "unknown")


def load_content_addressed_index(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"BM25 index does not exist: {path}")
    expected_hash = path.stem.rsplit("_", 1)[-1]
    actual_hash = file_sha256(path)
    if expected_hash != actual_hash:
        raise RuntimeError(f"BM25 index hash mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def retrieve_bm25(
    query: str,
    *,
    index_path: Path = DEFAULT_INDEX,
    chunks_path: Path = DEFAULT_CHUNKS,
    top_k: int = 5,
    default_exposure_only: bool = True,
    allowed_statuses: tuple[str, ...] | None = ("current", "upcoming"),
    include_review_required: bool = False,
    as_of: str | None = None,
    source_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    index = load_content_addressed_index(index_path)
    chunks = {row["chunk_id"]: row for row in read_jsonl(chunks_path)}
    hits = search_bm25(
        index,
        query,
        top_k=top_k,
        policy=SearchPolicy(
            default_exposure_only=default_exposure_only,
            allowed_statuses=allowed_statuses,
            include_review_required=include_review_required,
            as_of=as_of,
            source_ids=source_ids,
        ),
    )
    results = []
    for hit in hits:
        chunk = chunks.get(hit["chunk_id"])
        if chunk is None:
            raise RuntimeError(f"BM25 hit is absent from ChunkV3 artifact: {hit['chunk_id']}")
        results.append(
            {
                **hit,
                "heading_path": chunk["heading_path"],
                "chunk_type": chunk["chunk_type"],
                "display_text": chunk["display_text"],
                "retrieval_text": chunk["retrieval_text"],
            }
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the frozen DNF RAG v3 BM25 index.")
    parser.add_argument("query")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--include-non-default", action="store_true")
    parser.add_argument("--statuses", nargs="+", choices=VALID_STATUSES)
    parser.add_argument("--include-review-required", action="store_true")
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--no-time-filter", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.include_non_default and not args.statuses:
        raise RuntimeError("--include-non-default requires explicit --statuses")
    statuses = tuple(args.statuses) if args.statuses else ("current", "upcoming")
    hits = retrieve_bm25(
        args.query,
        index_path=args.index,
        chunks_path=args.chunks,
        top_k=args.top_k,
        default_exposure_only=not args.include_non_default,
        allowed_statuses=statuses,
        include_review_required=args.include_review_required,
        as_of=None if args.no_time_filter else args.as_of,
        source_ids=tuple(args.source_ids) if args.source_ids else None,
    )
    print(json.dumps(hits, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
