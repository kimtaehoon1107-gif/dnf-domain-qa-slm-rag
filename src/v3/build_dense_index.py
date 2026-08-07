from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import BGE_M3_MODEL, SearchPolicy, _allowed
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    parse_fixed_timestamp,
    write_immutable,
)


DENSE_FULL_VERSION = "dnf_bge_m3_dense_full_v3.1"
METADATA_SCHEMA_VERSION = "dnf_dense_full_metadata_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_dense_full_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_dense_full_report_v3.1"
MAX_SEQUENCE_LENGTH = 2048
EXPECTED_DOCUMENTS = 980
EXPECTED_CHUNKS = 3599
EXPECTED_DEFAULT_CHUNKS = 2527
EXPECTED_VISUAL_CHUNKS = 22
DEFAULT_AS_OF = "2026-07-18"

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CHUNK_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/"
    "bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_INDEX_DIR = Path("data/v3/indexes")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {
            "min": 0,
            "p50": 0,
            "p90": 0,
            "p95": 0,
            "p99": 0,
            "max": 0,
            "mean": 0.0,
        }
    ordered = sorted(values)

    def percentile(value: float) -> int:
        return ordered[max(0, math.ceil(value * len(ordered)) - 1)]

    return {
        "min": ordered[0],
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 2),
    }


def build_dense_metadata(
    chunks: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    documents_by_id = {row["document_id"]: row for row in documents}
    if len(documents_by_id) != len(documents):
        raise RuntimeError("Duplicate document_id in normalized documents")
    rows = []
    for ordinal, chunk in enumerate(sorted(chunks, key=lambda row: row["chunk_id"])):
        document = documents_by_id.get(chunk["parent_document_id"])
        if document is None:
            raise RuntimeError(f"Unknown dense parent: {chunk['parent_document_id']}")
        rows.append(
            {
                "metadata_schema_version": METADATA_SCHEMA_VERSION,
                "ordinal": ordinal,
                "chunk_id": chunk["chunk_id"],
                "parent_document_id": chunk["parent_document_id"],
                "parent_content_hash": chunk["parent_content_hash"],
                "canonical_url": document["canonical_url"],
                "title": document["title"],
                "source_id": chunk["source_id"],
                "source_kind": chunk["source_kind"],
                "status": chunk["status"],
                "default_exposure": chunk["default_exposure"],
                "review_required": chunk["review_required"],
                "offset_source": chunk["offset_source"],
                "valid_from": chunk["valid_from"],
                "valid_to": chunk["valid_to"],
                "retrieval_text_sha256": _sha256_bytes(
                    chunk["retrieval_text"].encode("utf-8")
                ),
            }
        )
    return rows


def _load_bm25_index(
    manifest_path: Path,
) -> tuple[dict[str, Any], Path, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    index_path = Path(manifest["index"]["path"])
    if not index_path.is_file():
        raise RuntimeError(f"BM25 index does not exist: {index_path}")
    index_sha256 = file_sha256(index_path)
    if index_sha256 != manifest["index"]["sha256"]:
        raise RuntimeError("BM25 index hash differs from its manifest")
    return json.loads(index_path.read_text(encoding="utf-8")), index_path, index_sha256


def _filter_policies(source_ids: list[str]) -> list[tuple[str, SearchPolicy]]:
    policies = [
        ("default", SearchPolicy()),
        ("default_as_of", SearchPolicy(as_of=DEFAULT_AS_OF)),
        (
            "all_statuses_without_review",
            SearchPolicy(
                default_exposure_only=False,
                allowed_statuses=None,
                include_review_required=False,
            ),
        ),
        (
            "all_statuses_with_review",
            SearchPolicy(
                default_exposure_only=False,
                allowed_statuses=None,
                include_review_required=True,
            ),
        ),
    ]
    for status in ("current", "expired", "superseded", "unknown"):
        policies.append(
            (
                f"status:{status}",
                SearchPolicy(
                    default_exposure_only=False,
                    allowed_statuses=(status,),
                    include_review_required=True,
                ),
            )
        )
    for source_id in source_ids:
        policies.append(
            (
                f"source:{source_id}",
                SearchPolicy(
                    default_exposure_only=False,
                    allowed_statuses=None,
                    include_review_required=True,
                    source_ids=(source_id,),
                ),
            )
        )
    return policies


def audit_bm25_parity(
    metadata: list[dict[str, Any]], bm25_index: dict[str, Any]
) -> dict[str, int]:
    entries = bm25_index["entries"]
    metadata_by_id = {row["chunk_id"]: row for row in metadata}
    entries_by_id = {row["chunk_id"]: row for row in entries}
    comparable_fields = (
        "ordinal",
        "parent_document_id",
        "canonical_url",
        "title",
        "source_id",
        "source_kind",
        "status",
        "default_exposure",
        "review_required",
        "offset_source",
        "valid_from",
        "valid_to",
    )
    field_mismatches = 0
    for chunk_id in sorted(metadata_by_id.keys() & entries_by_id.keys()):
        dense_row = metadata_by_id[chunk_id]
        bm25_row = entries_by_id[chunk_id]
        field_mismatches += sum(
            dense_row[field] != bm25_row[field] for field in comparable_fields
        )

    policies = _filter_policies(sorted({row["source_id"] for row in metadata}))
    filter_mismatches = 0
    for _, policy in policies:
        for chunk_id in sorted(metadata_by_id.keys() & entries_by_id.keys()):
            filter_mismatches += _allowed(metadata_by_id[chunk_id], policy) != _allowed(
                entries_by_id[chunk_id], policy
            )
    return {
        "bm25_entry_count_mismatch": abs(len(entries) - len(metadata)),
        "bm25_chunk_id_set_mismatch": len(metadata_by_id.keys() ^ entries_by_id.keys()),
        "bm25_metadata_field_mismatches": field_mismatches,
        "bm25_filter_policy_count": len(policies),
        "bm25_filter_parity_mismatches": filter_mismatches,
    }


def encode_bge_m3_full(
    chunks: list[dict[str, Any]],
    *,
    model_name: str,
    max_sequence_length: int,
    batch_size: int,
    device: str | None,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    import sentence_transformers
    import torch
    from sentence_transformers import SentenceTransformer

    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(0)
    selected_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model = SentenceTransformer(
        model_name,
        device=selected_device,
        local_files_only=True,
    )
    model.max_seq_length = max_sequence_length
    texts = [row["retrieval_text"] for row in chunks]
    token_lengths = []
    for start in range(0, len(texts), 32):
        encoded = model.tokenizer(
            texts[start : start + 32],
            add_special_tokens=True,
            truncation=False,
            return_length=True,
        )
        token_lengths.extend(int(value) for value in encoded["length"])
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
        precision="float32",
    ).astype(np.float32, copy=False)
    repeat_count = min(16, len(texts))
    repeat_embeddings = model.encode(
        texts[:repeat_count],
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
        precision="float32",
    ).astype(np.float32, copy=False)
    repeat_max_abs_diff = float(
        np.max(np.abs(embeddings[:repeat_count] - repeat_embeddings))
    )
    config = model[0].auto_model.config
    model_info = {
        "model_name": model_name,
        "model_revision": getattr(config, "_commit_hash", None),
        "sentence_transformers_version": sentence_transformers.__version__,
        "torch_version": torch.__version__,
        "numpy_version": np.__version__,
        "device": selected_device,
        "device_name": torch.cuda.get_device_name(0)
        if selected_device.startswith("cuda") and torch.cuda.is_available()
        else "cpu",
        "max_sequence_length": max_sequence_length,
        "batch_size": batch_size,
        "embedding_dimension": int(embeddings.shape[1]),
        "embedding_dtype": "float32",
        "normalize_embeddings": True,
        "similarity": "cosine_via_normalized_dot_product",
        "repeat_encode_rows": repeat_count,
        "repeat_encode_max_abs_diff": repeat_max_abs_diff,
    }
    token_measurement = {
        "row_count": len(token_lengths),
        "token_length": _distribution(token_lengths),
        "requested_max_sequence_length": max_sequence_length,
        "over_requested_max": sum(
            value > max_sequence_length for value in token_lengths
        ),
        "truncation_detected": any(
            value > max_sequence_length for value in token_lengths
        ),
    }
    return embeddings, model_info, token_measurement


def _render_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    token = report["token_measurement"]
    lines = [
        "# DNF RAG v3 BGE-M3 full dense artifact",
        "",
        f"- built_at: `{report['built_at']}`",
        f"- dense artifact decision: **{report['dense_artifact_decision']}**",
        "",
        "## Corpus",
        "",
        f"- documents: {summary['documents']}",
        f"- chunks: {summary['chunks']}",
        f"- default searchable chunks: {summary['default_exposure_chunks']}",
        f"- visual OCR chunks: {summary['visual_ocr_chunks']}",
        f"- embedding shape: {summary['embedding_shape']}",
        "",
        "## Token length",
        "",
        f"- requested max: {token['requested_max_sequence_length']}",
        f"- distribution: `{json.dumps(token['token_length'], ensure_ascii=False, sort_keys=True)}`",
        f"- over requested max: {token['over_requested_max']}",
        "",
        "## Filter parity",
        "",
        f"- BM25 policies compared: {report['audit']['bm25_filter_policy_count']}",
        f"- BM25 metadata mismatches: {report['audit']['bm25_metadata_field_mismatches']}",
        f"- BM25 filter parity mismatches: {report['audit']['bm25_filter_parity_mismatches']}",
        "",
        "## Gates",
        "",
        *[f"- {key}: `{value}`" for key, value in report["gates"].items()],
        "",
        "이 GO는 전체 dense matrix와 검색 필터 배관이 안전하게 freeze됐다는 뜻이다.",
        "자연어 retrieval 품질, hybrid 우월성, Router 성능은 아직 측정하지 않았다.",
        "",
    ]
    return "\n".join(lines)


def build_dense_full_artifacts(
    *,
    built_at: str,
    chunks_path: Path,
    chunk_manifest_path: Path,
    documents_path: Path,
    bm25_manifest_path: Path,
    index_dir: Path,
    report_dir: Path,
    model_name: str = BGE_M3_MODEL,
    max_sequence_length: int = MAX_SEQUENCE_LENGTH,
    batch_size: int = 2,
    device: str | None = None,
    embeddings_override: np.ndarray | None = None,
    model_info_override: dict[str, Any] | None = None,
    token_measurement_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_fixed_timestamp(built_at)
    input_paths = [
        chunks_path,
        chunk_manifest_path,
        documents_path,
        bm25_manifest_path,
    ]
    for path in input_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    input_hashes = {path: file_sha256(path) for path in input_paths}
    chunks = sorted(read_jsonl(chunks_path), key=lambda row: row["chunk_id"])
    documents = read_jsonl(documents_path)
    metadata = build_dense_metadata(chunks, documents)
    bm25_index, bm25_index_path, bm25_index_sha256 = _load_bm25_index(
        bm25_manifest_path
    )
    input_hashes[bm25_index_path] = bm25_index_sha256

    if embeddings_override is None:
        embeddings, model_info, token_measurement = encode_bge_m3_full(
            chunks,
            model_name=model_name,
            max_sequence_length=max_sequence_length,
            batch_size=batch_size,
            device=device,
        )
    else:
        if model_info_override is None or token_measurement_override is None:
            raise RuntimeError(
                "Dense override requires model info and token measurement"
            )
        embeddings = np.asarray(embeddings_override, dtype=np.float32)
        model_info = model_info_override
        token_measurement = token_measurement_override

    if embeddings.shape != (len(chunks), model_info["embedding_dimension"]):
        raise RuntimeError("Dense full embedding matrix shape differs from metadata")
    embeddings = np.asarray(embeddings, dtype="<f4", order="C")
    metadata_bytes = _serialize_jsonl(metadata, lambda row: row["ordinal"])
    metadata_sha256 = _sha256_bytes(metadata_bytes)
    metadata_path = index_dir / f"dense_full_metadata_{metadata_sha256}.jsonl"
    write_immutable(metadata_path, metadata_bytes)
    embedding_bytes = embeddings.tobytes(order="C")
    embedding_sha256 = _sha256_bytes(embedding_bytes)
    embedding_path = index_dir / f"dense_full_embeddings_{embedding_sha256}.f32"
    write_immutable(embedding_path, embedding_bytes)

    norms = np.linalg.norm(embeddings, axis=1)
    finite_values = bool(np.isfinite(embeddings).all())
    audit = audit_bm25_parity(metadata, bm25_index)
    parent_ids = {row["parent_document_id"] for row in metadata}
    gates: dict[str, bool | int] = {
        "document_count_is_980": len(parent_ids) == EXPECTED_DOCUMENTS,
        "chunk_count_is_3599": len(chunks) == EXPECTED_CHUNKS,
        "all_eight_sources_represented": len({row["source_id"] for row in metadata})
        == 8,
        "all_four_statuses_represented": {row["status"] for row in metadata}
        == {"current", "expired", "superseded", "unknown"},
        "default_chunk_count_is_2527": sum(
            row["default_exposure"] for row in metadata
        )
        == EXPECTED_DEFAULT_CHUNKS,
        "visual_chunk_count_is_22": sum(
            row["offset_source"] == "visual_ocr" for row in metadata
        )
        == EXPECTED_VISUAL_CHUNKS,
        "duplicate_chunk_ids": len(metadata)
        - len({row["chunk_id"] for row in metadata}),
        "metadata_ordinal_mismatches": sum(
            row["ordinal"] != ordinal for ordinal, row in enumerate(metadata)
        ),
        "non_finite_embedding_values": 0 if finite_values else 1,
        "non_unit_embedding_rows": int(np.sum(np.abs(norms - 1.0) > 1e-5)),
        "tokenizer_rows_mismatch": abs(token_measurement["row_count"] - len(chunks)),
        "tokens_over_requested_max": token_measurement["over_requested_max"],
        "repeat_encode_nondeterminism": int(
            model_info["repeat_encode_max_abs_diff"] > 1e-6
        ),
        "bm25_entry_count_mismatch": audit["bm25_entry_count_mismatch"],
        "bm25_chunk_id_set_mismatch": audit["bm25_chunk_id_set_mismatch"],
        "bm25_metadata_field_mismatches": audit["bm25_metadata_field_mismatches"],
        "bm25_filter_parity_mismatches": audit["bm25_filter_parity_mismatches"],
    }
    gate_go = all(
        value is True if isinstance(value, bool) else value == 0
        for value in gates.values()
    )

    manifest_inputs = [
        ("chunk_v3", chunks_path, len(chunks)),
        ("chunk_corpus_manifest", chunk_manifest_path, None),
        ("document_v3", documents_path, len(documents)),
        ("bm25_manifest", bm25_manifest_path, None),
        ("bm25_index", bm25_index_path, bm25_index["document_count"]),
    ]
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "dense_full_version": DENSE_FULL_VERSION,
        "built_at": built_at,
        "inputs": [
            {
                "role": role,
                "path": path.as_posix(),
                "sha256": input_hashes[path],
                "row_count": row_count,
            }
            for role, path, row_count in manifest_inputs
        ],
        "indexed_text_field": "retrieval_text",
        "default_filter": {
            "default_exposure_only": True,
            "allowed_statuses": ["current", "upcoming"],
            "include_review_required": False,
        },
        "model": model_info,
        "token_measurement": token_measurement,
        "metadata": {
            "path": metadata_path.as_posix(),
            "sha256": metadata_sha256,
            "row_count": len(metadata),
        },
        "embeddings": {
            "path": embedding_path.as_posix(),
            "sha256": embedding_sha256,
            "row_count": embeddings.shape[0],
            "dimension": embeddings.shape[1],
            "dtype": "little_endian_float32",
            "normalized": True,
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_path = index_dir / f"dense_full_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "dense_full_version": DENSE_FULL_VERSION,
        "built_at": built_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "summary": {
            "documents": len(parent_ids),
            "chunks": len(metadata),
            "default_exposure_chunks": sum(
                row["default_exposure"] for row in metadata
            ),
            "visual_ocr_chunks": sum(
                row["offset_source"] == "visual_ocr" for row in metadata
            ),
            "embedding_shape": list(embeddings.shape),
            "embedding_norm_min": float(norms.min()),
            "embedding_norm_max": float(norms.max()),
            "source": dict(
                sorted(Counter(row["source_id"] for row in metadata).items())
            ),
            "status": dict(
                sorted(Counter(row["status"] for row in metadata).items())
            ),
        },
        "model": model_info,
        "token_measurement": token_measurement,
        "audit": audit,
        "gates": gates,
        "dense_artifact_decision": "GO" if gate_go else "NO-GO",
        "retrieval_quality_measured": False,
        "hybrid_promotion_decision": "NOT_MEASURED",
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = _sha256_bytes(report_bytes)
    report_json_path = report_dir / f"dense_full_index_{report_sha256}.json"
    report_markdown_path = report_dir / f"dense_full_index_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_markdown_path, _render_report(report).encode("utf-8"))

    for path, digest in input_hashes.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f"Input changed while building full dense artifact: {path}")
    return {
        "metadata_path": metadata_path.as_posix(),
        "metadata_sha256": metadata_sha256,
        "embedding_path": embedding_path.as_posix(),
        "embedding_sha256": embedding_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_markdown_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "model": model_info,
        "token_measurement": token_measurement,
        "audit": audit,
        "dense_artifact_decision": report["dense_artifact_decision"],
        "hybrid_promotion_decision": report["hybrid_promotion_decision"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the full BGE-M3 dense artifact for canonical ChunkV3."
    )
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--chunk-manifest", type=Path, default=DEFAULT_CHUNK_MANIFEST)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--bm25-manifest", type=Path, default=DEFAULT_BM25_MANIFEST)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--model-name", default=BGE_M3_MODEL)
    parser.add_argument("--max-sequence-length", type=int, default=MAX_SEQUENCE_LENGTH)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--device", choices=("cpu", "cuda"), default=None)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_dense_full_artifacts(
        built_at=args.built_at,
        chunks_path=args.chunks,
        chunk_manifest_path=args.chunk_manifest,
        documents_path=args.documents,
        bm25_manifest_path=args.bm25_manifest,
        index_dir=args.index_dir,
        report_dir=args.report_dir,
        model_name=args.model_name,
        max_sequence_length=args.max_sequence_length,
        batch_size=args.batch_size,
        device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
