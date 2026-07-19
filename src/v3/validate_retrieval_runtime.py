from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_retrieval import policy_from_dev
from src.v3.evaluate_retrieval_signals import CANDIDATE_CONFIG
from src.v3.retrieve_v3 import load_runtime_artifacts, retrieve_with_embedding


VALIDATOR_VERSION = "retrieval-runtime-replay-v3.1.0"
RESULT_SCHEMA_VERSION = "retrieval-runtime-replay-result-v3.1"
MANIFEST_SCHEMA_VERSION = "retrieval-runtime-replay-manifest-v3.1"
REPORT_SCHEMA_VERSION = "retrieval-runtime-replay-report-v3.1"

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_QUERY_EMBEDDINGS = Path(
    "data/v3/retrieval/"
    "retrieval_dev_query_embeddings_323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32"
)
DEFAULT_EXPECTED_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_signal_results_c8f5c902f237ef70b4add45ee63815bd1cdafeb84741c86c1bd634b1df02127e.jsonl"
)
DEFAULT_ANNOTATION_MANIFEST = Path(
    "data/v3/evaluation/"
    "retrieval_annotation_review_manifest_a73c22708fa24fd4311cde62675d59137358d185cdca1eb223d284d2e7e0d258.json"
)
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
DEFAULT_RUNTIME_SOURCE = Path("src/v3/retrieve_v3.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def validate_runtime_replay(
    root: Path,
    dev_rows: list[dict[str, Any]],
    query_embeddings: np.ndarray,
    expected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if query_embeddings.shape != (len(dev_rows), 1024):
        raise RuntimeError("Frozen query embedding shape differs from dev rows")
    expected_by_id = {row["dev_id"]: row for row in expected_rows}
    if set(expected_by_id) != {row["dev_id"] for row in dev_rows}:
        raise RuntimeError("Expected signal results differ from dev IDs")
    artifacts = load_runtime_artifacts(root)
    results = []
    for ordinal, (dev, embedding) in enumerate(zip(dev_rows, query_embeddings)):
        runtime_hits = retrieve_with_embedding(
            dev["question"],
            embedding,
            artifacts,
            top_k=20,
            policy=policy_from_dev(dev),
        )
        expected_hits = expected_by_id[dev["dev_id"]]["configurations"][
            CANDIDATE_CONFIG
        ]["hits"]
        actual_ids = [row["chunk_id"] for row in runtime_hits]
        expected_ids = [row["chunk_id"] for row in expected_hits]
        first_mismatch = next(
            (
                rank
                for rank, (actual, expected) in enumerate(
                    zip(actual_ids, expected_ids), start=1
                )
                if actual != expected
            ),
            None,
        )
        if first_mismatch is None and len(actual_ids) != len(expected_ids):
            first_mismatch = min(len(actual_ids), len(expected_ids)) + 1
        results.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "query_ordinal": ordinal,
                "dev_id": dev["dev_id"],
                "question": dev["question"],
                "query_kind": dev["query_kind"],
                "query_policy": dev["query_policy"],
                "actual_chunk_ids": actual_ids,
                "expected_chunk_ids": expected_ids,
                "top_10_exact_match": actual_ids[:10] == expected_ids[:10],
                "top_20_exact_match": actual_ids == expected_ids,
                "first_mismatch_rank": first_mismatch,
                "structured_field_query": bool(runtime_hits)
                and runtime_hits[0]["structured_field_query"],
            }
        )
    return results


def audit_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gates = {
        "rows_63": len(rows) == 63,
        "query_ordinals_contiguous": [row["query_ordinal"] for row in rows]
        == list(range(63)),
        "top_10_exact_match_63": sum(row["top_10_exact_match"] for row in rows) == 63,
        "top_20_exact_match_63": sum(row["top_20_exact_match"] for row in rows) == 63,
        "first_mismatch_0": not any(row["first_mismatch_rank"] for row in rows),
        "structured_queries_7": sum(row["structured_field_query"] for row in rows)
        == 7,
    }
    return {
        "top_10_exact_match_count": sum(row["top_10_exact_match"] for row in rows),
        "top_20_exact_match_count": sum(row["top_20_exact_match"] for row in rows),
        "structured_query_count": sum(row["structured_field_query"] for row in rows),
        "gates": gates,
        "gate_pass": all(gates.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    audit = report["audit"]
    return f"""# DNF RAG v3 Runtime Retrieval Replay

## Decision

- Runtime entrypoint: **{report['decision']['runtime_entrypoint']}**
- Development retrieval candidate: **{report['decision']['development_retriever']}**
- Annotation human review: **{report['decision']['annotation_human_review']}**
- Final benchmark: **{report['decision']['final_benchmark']}**

## Replay

- rows: 63
- exact top-10: {audit['top_10_exact_match_count']}/63
- exact top-20: {audit['top_20_exact_match_count']}/63
- structured-field queries: {audit['structured_query_count']}

The runtime uses BGE-M3 dense 0.75, BM25 0.25, and the structured parent-lead guard. Gold IDs and source IDs are not used by the ranking policy.

The development retriever is usable, but final benchmark readiness remains blocked by the pending human annotation review.

## Artifacts

- replay: `{report['artifacts']['replay_path']}`
- manifest: `{report['artifacts']['manifest_path']}`
"""


def build_and_freeze(
    root: Path,
    dev_path: Path,
    query_embeddings_path: Path,
    expected_results_path: Path,
    annotation_manifest_path: Path,
    bm25_manifest_path: Path,
    dense_manifest_path: Path,
    chunks_path: Path,
    documents_path: Path,
    runtime_source_path: Path,
) -> dict[str, Any]:
    input_paths = {
        "dev_set": dev_path,
        "query_embeddings": query_embeddings_path,
        "expected_signal_results": expected_results_path,
        "annotation_review_manifest": annotation_manifest_path,
        "bm25_manifest": bm25_manifest_path,
        "dense_manifest": dense_manifest_path,
        "chunks": chunks_path,
        "documents": documents_path,
        "runtime_source": runtime_source_path,
    }
    hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    dev_rows = read_jsonl(dev_path)
    embeddings = np.fromfile(query_embeddings_path, dtype="<f4")
    if embeddings.size != len(dev_rows) * 1024:
        raise RuntimeError("Frozen query embedding bytes have invalid length")
    embeddings = embeddings.reshape(len(dev_rows), 1024)
    rows = validate_runtime_replay(
        root, dev_rows, embeddings, read_jsonl(expected_results_path)
    )
    audit = audit_replay(rows)
    if not audit["gate_pass"]:
        failed = [name for name, passed in audit["gates"].items() if not passed]
        raise RuntimeError(f"Runtime replay gates failed: {failed}")
    annotation_manifest = json.loads(
        annotation_manifest_path.read_text(encoding="utf-8")
    )
    annotation_pending = annotation_manifest["audit"]["gates"]["human_review_pending"]

    retrieval_dir = root / "data/v3/retrieval"
    reports_dir = root / "reports/v3"
    replay_bytes = _serialize_jsonl(rows, lambda row: row["query_ordinal"])
    replay_sha = _sha256_bytes(replay_bytes)
    replay_path = retrieval_dir / f"retrieval_runtime_replay_{replay_sha}.jsonl"
    write_immutable(replay_path, replay_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "runtime_contract": {
            "dense_weight": 0.75,
            "bm25_weight": 0.25,
            "candidate_depth": 20,
            "structured_parent_lead_guard": True,
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": hashes[name]}
            for name, path in input_paths.items()
        },
        "replay": {
            "path": _relative(root, replay_path),
            "sha256": replay_sha,
            "row_count": len(rows),
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = retrieval_dir / f"retrieval_runtime_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "decision": {
            "runtime_entrypoint": "GO",
            "development_retriever": "GO",
            "annotation_human_review": "PENDING" if annotation_pending else "COMPLETE",
            "final_benchmark": "NO-GO" if annotation_pending else "NOT_RUN",
        },
        "audit": audit,
        "artifacts": {
            "replay_path": _relative(root, replay_path),
            "replay_sha256": replay_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "generation",
            "answerability",
            "router",
            "training",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"retrieval_runtime_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"retrieval_runtime_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "replay_path": str(replay_path),
        "replay_sha256": replay_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Replay the frozen dev set through the v3 runtime retriever")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--query-embeddings", type=Path, default=root / DEFAULT_QUERY_EMBEDDINGS
    )
    parser.add_argument(
        "--expected-results", type=Path, default=root / DEFAULT_EXPECTED_RESULTS
    )
    parser.add_argument(
        "--annotation-manifest", type=Path, default=root / DEFAULT_ANNOTATION_MANIFEST
    )
    parser.add_argument("--bm25-manifest", type=Path, default=root / DEFAULT_BM25_MANIFEST)
    parser.add_argument("--dense-manifest", type=Path, default=root / DEFAULT_DENSE_MANIFEST)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--runtime-source", type=Path, default=root / DEFAULT_RUNTIME_SOURCE)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.query_embeddings.resolve(),
        args.expected_results.resolve(),
        args.annotation_manifest.resolve(),
        args.bm25_manifest.resolve(),
        args.dense_manifest.resolve(),
        args.chunks.resolve(),
        args.documents.resolve(),
        args.runtime_source.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
