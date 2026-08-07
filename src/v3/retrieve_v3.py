from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, search_bm25
from src.v3.build_dense_pilot import search_dense
from src.v3.evaluate_hybrid import fuse_hits
from src.v3.evaluate_retrieval import encode_queries, load_retrieval_artifacts
from src.v3.evaluate_retrieval_signals import (
    apply_structured_parent_lead_guard,
    build_lead_chunk_index,
)


RUNTIME_VERSION = "dnf-v3-retriever-v3.1.0"
DENSE_WEIGHT = 0.75
BM25_WEIGHT = 0.25
CANDIDATE_DEPTH = 20
MAX_TOP_K = 20
VALID_STATUSES = ("current", "upcoming", "expired", "superseded", "unknown")

DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/"
    "bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_DENSE_MANIFEST = Path(
    "data/v3/indexes/"
    "dense_full_manifest_51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)


@dataclass(frozen=True)
class RuntimeArtifacts:
    bm25_index: dict[str, Any]
    dense_metadata: list[dict[str, Any]]
    dense_embeddings: np.ndarray
    dense_model: dict[str, Any]
    chunks_by_id: dict[str, dict[str, Any]]
    documents_by_id: dict[str, dict[str, Any]]
    lead_by_parent: dict[str, dict[str, Any]]
    provenance: dict[str, Any]


def load_runtime_artifacts(
    root: Path,
    *,
    bm25_manifest_path: Path = DEFAULT_BM25_MANIFEST,
    dense_manifest_path: Path = DEFAULT_DENSE_MANIFEST,
    chunks_path: Path = DEFAULT_CHUNKS,
    documents_path: Path = DEFAULT_DOCUMENTS,
) -> RuntimeArtifacts:
    bm25_path = bm25_manifest_path if bm25_manifest_path.is_absolute() else root / bm25_manifest_path
    dense_path = dense_manifest_path if dense_manifest_path.is_absolute() else root / dense_manifest_path
    chunks_path = chunks_path if chunks_path.is_absolute() else root / chunks_path
    documents_path = documents_path if documents_path.is_absolute() else root / documents_path
    bm25, metadata, embeddings, model, provenance = load_retrieval_artifacts(
        root, bm25_path, dense_path
    )
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    if len(chunks_by_id) != len(chunks):
        raise RuntimeError("Duplicate ChunkV3 chunk_id")
    if len(documents_by_id) != len(documents):
        raise RuntimeError("Duplicate DocumentV3 document_id")
    if set(chunks_by_id) != {row["chunk_id"] for row in metadata}:
        raise RuntimeError("Runtime chunks differ from dense metadata")
    return RuntimeArtifacts(
        bm25_index=bm25,
        dense_metadata=metadata,
        dense_embeddings=embeddings,
        dense_model=model,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
        lead_by_parent=build_lead_chunk_index(chunks),
        provenance={
            **provenance,
            "chunks_path": chunks_path.resolve().relative_to(root.resolve()).as_posix(),
            "documents_path": documents_path.resolve().relative_to(root.resolve()).as_posix(),
        },
    )


def _policy_dict(policy: SearchPolicy) -> dict[str, Any]:
    return {
        "default_exposure_only": policy.default_exposure_only,
        "allowed_statuses": list(policy.allowed_statuses)
        if policy.allowed_statuses is not None
        else None,
        "include_review_required": policy.include_review_required,
        "as_of": policy.as_of,
    }


def _round_scores(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "score": round(float(row["score"]), 8)} for row in hits]


def retrieve_with_embedding(
    query: str,
    query_embedding: np.ndarray,
    artifacts: RuntimeArtifacts,
    *,
    top_k: int = 10,
    policy: SearchPolicy | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        raise RuntimeError("query must not be empty")
    if not 1 <= top_k <= MAX_TOP_K:
        raise RuntimeError(f"top_k must be between 1 and {MAX_TOP_K}")
    policy = SearchPolicy(as_of=date.today().isoformat()) if policy is None else policy
    query_vector = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
    if query_vector.shape != (artifacts.dense_embeddings.shape[1],):
        raise RuntimeError("Query embedding dimension differs from dense index")
    bm25_hits = _round_scores(
        search_bm25(
            artifacts.bm25_index,
            query,
            top_k=CANDIDATE_DEPTH,
            policy=policy,
        )
    )
    dense_hits = _round_scores(
        search_dense(
            artifacts.dense_embeddings,
            artifacts.dense_metadata,
            query_vector,
            top_k=CANDIDATE_DEPTH,
            policy=policy,
        )
    )
    fused = fuse_hits(
        bm25_hits,
        dense_hits,
        dense_weight=DENSE_WEIGHT,
        top_k=CANDIDATE_DEPTH,
    )
    guarded, signal = apply_structured_parent_lead_guard(
        query,
        _policy_dict(policy),
        fused,
        bm25_hits,
        artifacts.lead_by_parent,
    )
    output = []
    for row in guarded[:top_k]:
        chunk = artifacts.chunks_by_id[row["chunk_id"]]
        document = artifacts.documents_by_id[chunk["parent_document_id"]]
        output.append(
            {
                "runtime_version": RUNTIME_VERSION,
                "rank": row["rank"],
                "chunk_id": row["chunk_id"],
                "parent_document_id": chunk["parent_document_id"],
                "title": document["title"],
                "canonical_url": document["canonical_url"],
                "source_id": chunk["source_id"],
                "source_kind": chunk["source_kind"],
                "status": chunk["status"],
                "default_exposure": chunk["default_exposure"],
                "review_required": chunk["review_required"],
                "valid_from": chunk["valid_from"],
                "valid_to": chunk["valid_to"],
                "chunk_type": chunk["chunk_type"],
                "heading_path": chunk["heading_path"],
                "display_text": chunk["display_text"],
                "retrieval_text": chunk["retrieval_text"],
                "base_hybrid_rank": row["base_rank"],
                "base_hybrid_score": row["base_score"],
                "guardrail_injected": row["guardrail_injected"],
                "structured_field_query": signal["structured_field_query"],
            }
        )
    return output


def retrieve_v3(
    query: str,
    *,
    root: Path | None = None,
    top_k: int = 10,
    policy: SearchPolicy | None = None,
    device: str | None = None,
    artifacts: RuntimeArtifacts | None = None,
    query_embedding: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[2] if root is None else root.resolve()
    artifacts = load_runtime_artifacts(root) if artifacts is None else artifacts
    if query_embedding is None:
        encoded, _ = encode_queries(
            [query], artifacts.dense_model, device=device, batch_size=1
        )
        query_embedding = encoded[0]
    return retrieve_with_embedding(
        query, query_embedding, artifacts, top_k=top_k, policy=policy
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the promoted DNF RAG v3 hybrid retriever")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--device", choices=("cpu", "cuda"))
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
    policy = SearchPolicy(
        default_exposure_only=not args.include_non_default,
        allowed_statuses=statuses,
        include_review_required=args.include_review_required,
        as_of=None if args.no_time_filter else args.as_of,
        source_ids=tuple(args.source_ids) if args.source_ids else None,
    )
    results = retrieve_v3(
        args.query,
        top_k=args.top_k,
        policy=policy,
        device=args.device,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
