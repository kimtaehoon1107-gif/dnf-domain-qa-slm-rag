from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import (
    BGE_M3_MODEL,
    SearchPolicy,
    _allowed,
    _pick_title_document,
    build_bm25_index,
    search_bm25,
    tokenize_lexical,
)
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    parse_fixed_timestamp,
    write_immutable,
)


DENSE_PILOT_VERSION = "dnf_bge_m3_dense_pilot_v3.1"
SELECTION_SCHEMA_VERSION = "dnf_dense_pilot_selection_v3.1"
METADATA_SCHEMA_VERSION = "dnf_dense_pilot_metadata_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_dense_pilot_manifest_v3.1"
DIAGNOSTIC_SCHEMA_VERSION = "dnf_dense_pilot_diagnostic_v3.1"
REPORT_SCHEMA_VERSION = "dnf_dense_pilot_report_v3.1"
MAX_SEQUENCE_LENGTH = 2048
EXPECTED_DOCUMENTS = 63
EXPECTED_CHUNKS = 467
EXPECTED_DEFAULT_CHUNKS = 272
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
DEFAULT_PILOT_SELECTION = Path(
    "data/v3/chunks/"
    "chunk_pilot_selection_af717de4e375b7c6f74a4a6da41640280c1ea2c4c5550278c1811c2954553b2b.jsonl"
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
DEFAULT_RETRIEVAL_DIR = Path("data/v3/retrieval")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0.0}
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


def select_dense_pilot_chunks(
    chunks: list[dict[str, Any]], pilot_selection: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    selected_document_ids = {row["document_id"] for row in pilot_selection}
    if len(selected_document_ids) != EXPECTED_DOCUMENTS:
        raise RuntimeError(
            f"Dense pilot requires {EXPECTED_DOCUMENTS} unique pilot documents"
        )
    selected = [
        row for row in chunks if row["parent_document_id"] in selected_document_ids
    ]
    if len(selected) != EXPECTED_CHUNKS:
        raise RuntimeError(f"Dense pilot requires {EXPECTED_CHUNKS} full-corpus chunks")
    return sorted(selected, key=lambda row: row["chunk_id"])


def build_selection_rows(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "selection_schema_version": SELECTION_SCHEMA_VERSION,
            "dense_pilot_version": DENSE_PILOT_VERSION,
            "chunk_id": row["chunk_id"],
            "parent_document_id": row["parent_document_id"],
            "source_id": row["source_id"],
            "source_kind": row["source_kind"],
            "status": row["status"],
            "default_exposure": row["default_exposure"],
            "review_required": row["review_required"],
            "offset_source": row["offset_source"],
            "retrieval_text_sha256": _sha256_bytes(row["retrieval_text"].encode("utf-8")),
        }
        for row in chunks
    ]


def build_dense_metadata(
    chunks: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    documents_by_id = {row["document_id"]: row for row in documents}
    rows = []
    for ordinal, chunk in enumerate(chunks):
        document = documents_by_id.get(chunk["parent_document_id"])
        if document is None:
            raise RuntimeError(f"Unknown dense pilot parent: {chunk['parent_document_id']}")
        rows.append(
            {
                "metadata_schema_version": METADATA_SCHEMA_VERSION,
                "ordinal": ordinal,
                "chunk_id": chunk["chunk_id"],
                "parent_document_id": chunk["parent_document_id"],
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
            }
        )
    return rows


def search_dense(
    embeddings: np.ndarray,
    metadata: list[dict[str, Any]],
    query_embedding: np.ndarray,
    *,
    top_k: int = 5,
    policy: SearchPolicy | None = None,
) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise RuntimeError("top_k must be positive")
    if embeddings.ndim != 2 or len(metadata) != embeddings.shape[0]:
        raise RuntimeError("Dense matrix and metadata row count differ")
    query = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
    if query.shape[0] != embeddings.shape[1]:
        raise RuntimeError("Dense query dimension differs from matrix")
    norm = float(np.linalg.norm(query))
    if not np.isfinite(norm) or norm == 0.0:
        raise RuntimeError("Dense query embedding is invalid")
    query = query / norm
    scores = np.asarray(embeddings, dtype=np.float32) @ query
    policy = SearchPolicy() if policy is None else policy
    candidates = [
        (ordinal, float(scores[ordinal]))
        for ordinal, entry in enumerate(metadata)
        if _allowed(entry, policy)
    ]
    candidates.sort(key=lambda item: (-item[1], metadata[item[0]]["chunk_id"]))
    return [
        {"rank": rank, "score": score, **metadata[ordinal]}
        for rank, (ordinal, score) in enumerate(candidates[:top_k], start=1)
    ]


def make_diagnostic_cases(
    bm25_index: dict[str, Any],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    parse_fixed_timestamp(f"{as_of}T00:00:00+09:00")
    selected_parent_ids = {row["parent_document_id"] for row in chunks}
    selected_documents = [
        row for row in documents if row["document_id"] in selected_parent_ids
    ]
    default_policy = SearchPolicy(as_of=as_of)
    cases = []
    for source_id in sorted({row["source_id"] for row in selected_documents}):
        document = _pick_title_document(
            bm25_index,
            selected_documents,
            [
                row
                for row in selected_documents
                if row["source_id"] == source_id
                and row["default_exposure"]
                and row["status"] in {"current", "upcoming"}
            ],
        )
        cases.append(
            {
                "case_id": f"default_title_lookup:{source_id}",
                "case_kind": "default_title_lookup",
                "query": document["title"],
                "target_parent_document_id": document["document_id"],
                "target_chunk_id": None,
                "policy": {
                    "default_exposure_only": True,
                    "allowed_statuses": ["current", "upcoming"],
                    "include_review_required": False,
                    "as_of": as_of,
                },
            }
        )

    for status in ("expired", "superseded", "unknown"):
        document = _pick_title_document(
            bm25_index,
            selected_documents,
            [row for row in selected_documents if row["status"] == status],
        )
        cases.append(
            {
                "case_id": f"historical_control:{status}",
                "case_kind": "historical_control",
                "query": document["title"],
                "target_parent_document_id": document["document_id"],
                "target_chunk_id": None,
                "policy": {
                    "default_exposure_only": False,
                    "allowed_statuses": [status],
                    "include_review_required": False,
                    "as_of": None,
                },
            }
        )

    visual_chunks = [row for row in chunks if row["review_required"]]
    visual_candidates = []
    for chunk in visual_chunks:
        tokens = sorted(
            {token for token in tokenize_lexical(chunk["display_text"]) if len(token) >= 2},
            key=lambda token: (len(bm25_index["postings"].get(token, [])), token),
        )
        if tokens:
            query_tokens = tokens[:6]
            rarity = sum(
                math.log(1.0 + bm25_index["document_count"] / max(1, len(bm25_index["postings"].get(token, []))))
                for token in query_tokens
            )
            visual_candidates.append((rarity, chunk, query_tokens))
    if not visual_candidates:
        raise RuntimeError("Dense pilot has no OCR diagnostic candidate")
    _, visual_chunk, query_tokens = sorted(
        visual_candidates, key=lambda item: (-item[0], item[1]["chunk_id"])
    )[0]
    cases.append(
        {
            "case_id": "visual_ocr_control",
            "case_kind": "visual_ocr_control",
            "query": " ".join(query_tokens),
            "target_parent_document_id": visual_chunk["parent_document_id"],
            "target_chunk_id": visual_chunk["chunk_id"],
            "policy": {
                "default_exposure_only": False,
                "allowed_statuses": [visual_chunk["status"]],
                "include_review_required": True,
                "as_of": None,
            },
        }
    )
    if len(cases) != 12:
        raise RuntimeError(f"Dense pilot diagnostic contract requires 12 cases, got {len(cases)}")
    return sorted(cases, key=lambda row: row["case_id"])


def _policy_from_payload(payload: dict[str, Any]) -> SearchPolicy:
    return SearchPolicy(
        default_exposure_only=payload["default_exposure_only"],
        allowed_statuses=tuple(payload["allowed_statuses"])
        if payload["allowed_statuses"] is not None
        else None,
        include_review_required=payload["include_review_required"],
        as_of=payload["as_of"],
    )


def run_dense_diagnostics(
    embeddings: np.ndarray,
    metadata: list[dict[str, Any]],
    bm25_index: dict[str, Any],
    cases: list[dict[str, Any]],
    query_embeddings: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if query_embeddings.shape != (len(cases), embeddings.shape[1]):
        raise RuntimeError("Dense diagnostic query matrix shape differs from contract")
    rows = []
    dense_title_hits = 0
    bm25_title_hits = 0
    dense_control_hits = 0
    bm25_control_hits = 0
    dense_default_policy_violations = 0
    top5_overlap_sum = 0.0
    for index, case in enumerate(cases):
        policy = _policy_from_payload(case["policy"])
        dense_hits = search_dense(
            embeddings, metadata, query_embeddings[index], top_k=5, policy=policy
        )
        lexical_hits = search_bm25(
            bm25_index, case["query"], top_k=5, policy=policy
        )
        if case["target_chunk_id"] is not None:
            dense_rank = next(
                (
                    row["rank"]
                    for row in dense_hits
                    if row["chunk_id"] == case["target_chunk_id"]
                ),
                None,
            )
            lexical_rank = next(
                (
                    row["rank"]
                    for row in lexical_hits
                    if row["chunk_id"] == case["target_chunk_id"]
                ),
                None,
            )
        else:
            dense_rank = next(
                (
                    row["rank"]
                    for row in dense_hits
                    if row["parent_document_id"] == case["target_parent_document_id"]
                ),
                None,
            )
            lexical_rank = next(
                (
                    row["rank"]
                    for row in lexical_hits
                    if row["parent_document_id"] == case["target_parent_document_id"]
                ),
                None,
            )
        if case["case_kind"] == "default_title_lookup":
            dense_title_hits += dense_rank is not None
            bm25_title_hits += lexical_rank is not None
            dense_default_policy_violations += sum(
                not _allowed(row, policy) for row in dense_hits
            )
        else:
            dense_control_hits += dense_rank is not None
            bm25_control_hits += lexical_rank is not None
        dense_ids = {row["chunk_id"] for row in dense_hits}
        lexical_ids = {row["chunk_id"] for row in lexical_hits}
        top5_overlap_sum += len(dense_ids & lexical_ids) / 5.0
        rows.append(
            {
                "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                **case,
                "dense_rank": dense_rank,
                "dense_hit_at_5": dense_rank is not None,
                "bm25_rank": lexical_rank,
                "bm25_hit_at_5": lexical_rank is not None,
                "dense_chunk_ids": [row["chunk_id"] for row in dense_hits],
                "bm25_chunk_ids": [row["chunk_id"] for row in lexical_hits],
            }
        )
    summary = {
        "default_title_lookup_cases": 8,
        "dense_default_title_hit_at_5": dense_title_hits,
        "bm25_default_title_hit_at_5": bm25_title_hits,
        "historical_and_visual_control_cases": 4,
        "dense_control_hit_at_5": dense_control_hits,
        "bm25_control_hit_at_5": bm25_control_hits,
        "dense_default_policy_violations": dense_default_policy_violations,
        "mean_top5_chunk_overlap": round(top5_overlap_sum / len(cases), 6),
    }
    summary["diagnostic_decision"] = (
        "GO"
        if dense_title_hits == 8
        and bm25_title_hits == 8
        and dense_control_hits == 4
        and bm25_control_hits == 4
        and dense_default_policy_violations == 0
        else "NO-GO"
    )
    return rows, summary


def encode_bge_m3_pilot(
    chunks: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    *,
    model_name: str,
    max_sequence_length: int,
    batch_size: int,
    device: str | None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any], dict[str, Any]]:
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
    query_embeddings = model.encode(
        [row["query"] for row in cases],
        batch_size=batch_size,
        show_progress_bar=False,
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
    return embeddings, query_embeddings, model_info, token_measurement


def _render_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    diagnostic = report["diagnostic"]
    token = report["token_measurement"]
    lines = [
        "# DNF RAG v3 BGE-M3 dense index pilot",
        "",
        f"- built_at: `{report['built_at']}`",
        f"- full dense index decision: **{report['full_dense_index_decision']}**",
        "",
        "## Pilot",
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
        "## Diagnostic",
        "",
        f"- dense title hit@5: {diagnostic['dense_default_title_hit_at_5']}/8",
        f"- BM25 title hit@5: {diagnostic['bm25_default_title_hit_at_5']}/8",
        f"- dense controls hit@5: {diagnostic['dense_control_hit_at_5']}/4",
        f"- BM25 controls hit@5: {diagnostic['bm25_control_hit_at_5']}/4",
        f"- mean top-5 chunk overlap: {diagnostic['mean_top5_chunk_overlap']}",
        "",
        "Title/control diagnostic은 배관 검증이며 자연어 retrieval 품질 평가가 아니다.",
        "",
        "## Gates",
        "",
        *[f"- {key}: `{value}`" for key, value in report["gates"].items()],
        "",
        "전체 dense index, hybrid, Router, 생성, 평가, 학습은 실행하지 않았다.",
        "",
    ]
    return "\n".join(lines)


def build_dense_pilot_artifacts(
    *,
    built_at: str,
    chunks_path: Path,
    chunk_manifest_path: Path,
    pilot_selection_path: Path,
    documents_path: Path,
    bm25_manifest_path: Path,
    index_dir: Path,
    retrieval_dir: Path,
    report_dir: Path,
    model_name: str = BGE_M3_MODEL,
    max_sequence_length: int = MAX_SEQUENCE_LENGTH,
    batch_size: int = 2,
    device: str | None = None,
    embeddings_override: np.ndarray | None = None,
    diagnostics_override: tuple[list[dict[str, Any]], dict[str, Any]] | None = None,
    model_info_override: dict[str, Any] | None = None,
    token_measurement_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_fixed_timestamp(built_at)
    input_paths = [
        chunks_path,
        chunk_manifest_path,
        pilot_selection_path,
        documents_path,
        bm25_manifest_path,
    ]
    for path in input_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    input_hashes = {path: file_sha256(path) for path in input_paths}
    chunks = read_jsonl(chunks_path)
    pilot_selection = read_jsonl(pilot_selection_path)
    documents = read_jsonl(documents_path)
    selected_chunks = select_dense_pilot_chunks(chunks, pilot_selection)
    selected_parent_ids = {row["parent_document_id"] for row in selected_chunks}
    selected_documents = [
        row for row in documents if row["document_id"] in selected_parent_ids
    ]
    selection_rows = build_selection_rows(selected_chunks)
    metadata = build_dense_metadata(selected_chunks, documents)
    pilot_bm25_index = build_bm25_index(selected_chunks, selected_documents)
    cases = make_diagnostic_cases(
        pilot_bm25_index,
        selected_chunks,
        selected_documents,
        as_of=DEFAULT_AS_OF,
    )

    if embeddings_override is None:
        embeddings, query_embeddings, model_info, token_measurement = encode_bge_m3_pilot(
            selected_chunks,
            cases,
            model_name=model_name,
            max_sequence_length=max_sequence_length,
            batch_size=batch_size,
            device=device,
        )
        diagnostic_rows, diagnostic_summary = run_dense_diagnostics(
            embeddings,
            metadata,
            pilot_bm25_index,
            cases,
            query_embeddings,
        )
    else:
        if diagnostics_override is None or model_info_override is None or token_measurement_override is None:
            raise RuntimeError("Dense override requires diagnostics, model info, and token measurement")
        embeddings = np.asarray(embeddings_override, dtype=np.float32)
        diagnostic_rows, diagnostic_summary = diagnostics_override
        model_info = model_info_override
        token_measurement = token_measurement_override

    if embeddings.shape != (len(selected_chunks), model_info["embedding_dimension"]):
        raise RuntimeError("Dense pilot embedding matrix shape differs from metadata")
    embeddings = np.asarray(embeddings, dtype="<f4", order="C")
    selection_bytes = _serialize_jsonl(selection_rows, lambda row: row["chunk_id"])
    selection_sha256 = _sha256_bytes(selection_bytes)
    selection_path = index_dir / f"dense_pilot_selection_{selection_sha256}.jsonl"
    write_immutable(selection_path, selection_bytes)
    metadata_bytes = _serialize_jsonl(metadata, lambda row: row["ordinal"])
    metadata_sha256 = _sha256_bytes(metadata_bytes)
    metadata_path = index_dir / f"dense_pilot_metadata_{metadata_sha256}.jsonl"
    write_immutable(metadata_path, metadata_bytes)
    embedding_bytes = embeddings.tobytes(order="C")
    embedding_sha256 = _sha256_bytes(embedding_bytes)
    embedding_path = index_dir / f"dense_pilot_embeddings_{embedding_sha256}.f32"
    write_immutable(embedding_path, embedding_bytes)

    diagnostics_bytes = _serialize_jsonl(
        diagnostic_rows, lambda row: row["case_id"]
    )
    diagnostics_sha256 = _sha256_bytes(diagnostics_bytes)
    diagnostics_path = retrieval_dir / f"dense_pilot_diagnostics_{diagnostics_sha256}.jsonl"
    write_immutable(diagnostics_path, diagnostics_bytes)

    norms = np.linalg.norm(embeddings, axis=1)
    finite_values = bool(np.isfinite(embeddings).all())
    filter_parity_mismatches = sum(
        _allowed(entry, SearchPolicy())
        != (
            entry["default_exposure"]
            and entry["status"] in {"current", "upcoming"}
            and not entry["review_required"]
        )
        for entry in metadata
    )
    gates: dict[str, bool | int] = {
        "document_count_is_63": len(selected_parent_ids) == EXPECTED_DOCUMENTS,
        "chunk_count_is_467": len(selected_chunks) == EXPECTED_CHUNKS,
        "all_eight_sources_represented": len({row["source_id"] for row in selected_chunks}) == 8,
        "all_four_statuses_represented": {row["status"] for row in selected_chunks}
        == {"current", "expired", "superseded", "unknown"},
        "default_chunk_count_is_272": sum(row["default_exposure"] for row in selected_chunks)
        == EXPECTED_DEFAULT_CHUNKS,
        "visual_chunk_count_is_22": sum(row["offset_source"] == "visual_ocr" for row in selected_chunks)
        == EXPECTED_VISUAL_CHUNKS,
        "duplicate_chunk_ids": len(selected_chunks)
        - len({row["chunk_id"] for row in selected_chunks}),
        "metadata_ordinal_mismatches": sum(
            row["ordinal"] != ordinal for ordinal, row in enumerate(metadata)
        ),
        "non_finite_embedding_values": 0 if finite_values else 1,
        "non_unit_embedding_rows": int(np.sum(np.abs(norms - 1.0) > 1e-5)),
        "tokenizer_rows_mismatch": abs(token_measurement["row_count"] - len(selected_chunks)),
        "tokens_over_2048": token_measurement["over_requested_max"],
        "repeat_encode_nondeterminism": int(
            model_info["repeat_encode_max_abs_diff"] > 1e-6
        ),
        "default_filter_parity_mismatches": filter_parity_mismatches,
        "diagnostic_decision_is_go": diagnostic_summary["diagnostic_decision"] == "GO",
    }
    gate_go = all(
        value is True if isinstance(value, bool) else value == 0
        for value in gates.values()
    )

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "dense_pilot_version": DENSE_PILOT_VERSION,
        "built_at": built_at,
        "inputs": [
            {
                "role": role,
                "path": path.as_posix(),
                "sha256": input_hashes[path],
            }
            for role, path in (
                ("chunk_v3", chunks_path),
                ("chunk_corpus_manifest", chunk_manifest_path),
                ("approved_chunk_pilot_selection", pilot_selection_path),
                ("document_v3", documents_path),
                ("bm25_manifest", bm25_manifest_path),
            )
        ],
        "model": model_info,
        "token_measurement": token_measurement,
        "selection": {
            "path": selection_path.as_posix(),
            "sha256": selection_sha256,
            "row_count": len(selection_rows),
        },
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
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_path = index_dir / f"dense_pilot_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "dense_pilot_version": DENSE_PILOT_VERSION,
        "built_at": built_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "diagnostics_path": diagnostics_path.as_posix(),
        "diagnostics_sha256": diagnostics_sha256,
        "summary": {
            "documents": len(selected_parent_ids),
            "chunks": len(selected_chunks),
            "default_exposure_chunks": sum(row["default_exposure"] for row in selected_chunks),
            "visual_ocr_chunks": sum(row["offset_source"] == "visual_ocr" for row in selected_chunks),
            "embedding_shape": list(embeddings.shape),
            "embedding_norm_min": float(norms.min()),
            "embedding_norm_max": float(norms.max()),
            "source": dict(sorted(Counter(row["source_id"] for row in selected_chunks).items())),
            "status": dict(sorted(Counter(row["status"] for row in selected_chunks).items())),
        },
        "model": model_info,
        "token_measurement": token_measurement,
        "diagnostic": diagnostic_summary,
        "gates": gates,
        "full_dense_index_decision": "GO" if gate_go else "NO-GO",
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = _sha256_bytes(report_bytes)
    report_json_path = report_dir / f"dense_pilot_{report_sha256}.json"
    report_markdown_path = report_dir / f"dense_pilot_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_markdown_path, _render_report(report).encode("utf-8"))

    for path, digest in input_hashes.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f"Input changed while building dense pilot: {path}")
    return {
        "selection_path": selection_path.as_posix(),
        "selection_sha256": selection_sha256,
        "metadata_path": metadata_path.as_posix(),
        "metadata_sha256": metadata_sha256,
        "embedding_path": embedding_path.as_posix(),
        "embedding_sha256": embedding_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "diagnostics_path": diagnostics_path.as_posix(),
        "diagnostics_sha256": diagnostics_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_markdown_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "model": model_info,
        "token_measurement": token_measurement,
        "diagnostic": diagnostic_summary,
        "full_dense_index_decision": report["full_dense_index_decision"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a BGE-M3 dense index pilot over the approved 63-document ChunkV3 sample."
    )
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--chunk-manifest", type=Path, default=DEFAULT_CHUNK_MANIFEST)
    parser.add_argument("--pilot-selection", type=Path, default=DEFAULT_PILOT_SELECTION)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--bm25-manifest", type=Path, default=DEFAULT_BM25_MANIFEST)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--retrieval-dir", type=Path, default=DEFAULT_RETRIEVAL_DIR)
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
    result = build_dense_pilot_artifacts(
        built_at=args.built_at,
        chunks_path=args.chunks,
        chunk_manifest_path=args.chunk_manifest,
        pilot_selection_path=args.pilot_selection,
        documents_path=args.documents,
        bm25_manifest_path=args.bm25_manifest,
        index_dir=args.index_dir,
        retrieval_dir=args.retrieval_dir,
        report_dir=args.report_dir,
        model_name=args.model_name,
        max_sequence_length=args.max_sequence_length,
        batch_size=args.batch_size,
        device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
