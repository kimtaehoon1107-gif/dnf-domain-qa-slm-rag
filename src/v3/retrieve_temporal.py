from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.evaluate_retrieval import encode_queries
from src.v3.retrieve_v3 import (
    MAX_TOP_K,
    RuntimeArtifacts,
    load_runtime_artifacts,
    retrieve_with_embedding,
)
from src.v3.temporal_policy import (
    TemporalMode,
    restrict_bm25_index,
    resolve_policy_revisions,
    search_policy_for_resolution,
)


RUNTIME_VERSION = "dnf-account-policy-temporal-retriever-v3.1.0"


def _restrict_artifacts(
    artifacts: RuntimeArtifacts, allowed_document_ids: list[str]
) -> RuntimeArtifacts:
    allowed = set(allowed_document_ids)
    dense_ordinals = [
        ordinal
        for ordinal, row in enumerate(artifacts.dense_metadata)
        if row["parent_document_id"] in allowed
    ]
    metadata = [artifacts.dense_metadata[ordinal] for ordinal in dense_ordinals]
    embeddings = artifacts.dense_embeddings[dense_ordinals]
    chunks = {
        chunk_id: row
        for chunk_id, row in artifacts.chunks_by_id.items()
        if row["parent_document_id"] in allowed
    }
    documents = {
        document_id: row
        for document_id, row in artifacts.documents_by_id.items()
        if document_id in allowed
    }
    leads = {
        document_id: row
        for document_id, row in artifacts.lead_by_parent.items()
        if document_id in allowed
    }
    return RuntimeArtifacts(
        bm25_index=restrict_bm25_index(
            artifacts.bm25_index, tuple(sorted(allowed))
        ),
        dense_metadata=metadata,
        dense_embeddings=embeddings,
        dense_model=artifacts.dense_model,
        chunks_by_id=chunks,
        documents_by_id=documents,
        lead_by_parent=leads,
        provenance=artifacts.provenance,
    )


def _decorate(
    hits: list[dict[str, Any]],
    resolution: dict[str, Any],
) -> list[dict[str, Any]]:
    roles = resolution["document_roles"]
    return [
        {
            **row,
            "temporal_runtime_version": RUNTIME_VERSION,
            "temporal_mode": resolution["mode"],
            "temporal_as_of": resolution["as_of"],
            "temporal_decision": resolution["temporal_decision"],
            "temporal_role": roles[row["parent_document_id"]],
        }
        for row in hits
    ]


def retrieve_policy_with_embedding(
    query: str,
    query_embedding: np.ndarray,
    artifacts: RuntimeArtifacts,
    overlay_rows: list[dict[str, Any]],
    *,
    mode: TemporalMode = "current",
    as_of: str | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    if mode == "comparison" and top_k < 2:
        raise RuntimeError("comparison mode requires top_k >= 2")
    resolution = resolve_policy_revisions(overlay_rows, mode=mode, as_of=as_of)
    if mode != "comparison" or len(resolution["allowed_document_ids"]) == 1:
        restricted = _restrict_artifacts(
            artifacts, resolution["allowed_document_ids"]
        )
        hits = retrieve_with_embedding(
            query,
            query_embedding,
            restricted,
            top_k=top_k,
            policy=search_policy_for_resolution(resolution),
        )
        decorated = _decorate(hits, resolution)
    else:
        per_revision = max(1, math.ceil(top_k / 2))
        hits_by_document = []
        for document_id in resolution["allowed_document_ids"]:
            restricted = _restrict_artifacts(artifacts, [document_id])
            hits_by_document.append(
                _decorate(
                    retrieve_with_embedding(
                        query,
                        query_embedding,
                        restricted,
                        top_k=per_revision,
                        policy=search_policy_for_resolution(resolution),
                    ),
                    resolution,
                )
            )
        decorated = []
        for offset in range(per_revision):
            for document_hits in hits_by_document:
                if offset < len(document_hits):
                    decorated.append(document_hits[offset])
        decorated = decorated[:top_k]
        decorated = [
            {**row, "rank": rank} for rank, row in enumerate(decorated, start=1)
        ]
    return {"resolution": resolution, "hits": decorated}


def retrieve_policy_v3(
    query: str,
    overlay_path: Path,
    *,
    root: Path | None = None,
    mode: TemporalMode = "current",
    as_of: str | None = None,
    top_k: int = 10,
    device: str | None = None,
    artifacts: RuntimeArtifacts | None = None,
    query_embedding: np.ndarray | None = None,
) -> dict[str, Any]:
    if not 1 <= top_k <= MAX_TOP_K:
        raise RuntimeError(f"top_k must be between 1 and {MAX_TOP_K}")
    root = Path(__file__).resolve().parents[2] if root is None else root.resolve()
    overlay_path = overlay_path if overlay_path.is_absolute() else root / overlay_path
    overlay_rows = read_jsonl(overlay_path)
    artifacts = load_runtime_artifacts(root) if artifacts is None else artifacts
    if query_embedding is None:
        encoded, _ = encode_queries(
            [query], artifacts.dense_model, device=device, batch_size=1
        )
        query_embedding = encoded[0]
    return retrieve_policy_with_embedding(
        query,
        query_embedding,
        artifacts,
        overlay_rows,
        mode=mode,
        as_of=as_of,
        top_k=top_k,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search account-policy revisions with an explicit temporal mode"
    )
    parser.add_argument("query")
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("current", "historical", "comparison"), default="current"
    )
    parser.add_argument("--as-of")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.mode in {"historical", "comparison"} and args.as_of is None:
        raise RuntimeError(f"{args.mode} mode requires --as-of")
    result = retrieve_policy_v3(
        args.query,
        args.overlay,
        mode=args.mode,
        as_of=args.as_of,
        top_k=args.top_k,
        device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
