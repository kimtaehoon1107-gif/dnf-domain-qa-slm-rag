from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import sentence_transformers
import torch
import transformers
from sentence_transformers import CrossEncoder

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_retrieval_signals import CANDIDATE_CONFIG
from src.v3.select_evidence import classify_answerability


SCORER_VERSION = "evidence-reranker-scorer-v3.1.0"
SCORE_SCHEMA_VERSION = "evidence-reranker-score-v3.1"
MANIFEST_SCHEMA_VERSION = "evidence-reranker-score-manifest-v3.1"
LATENCY_SCHEMA_VERSION = "evidence-reranker-latency-v3.1"
MODEL_NAME = "BAAI/bge-reranker-v2-m3"
MODEL_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MAX_LENGTH = 512
BATCH_SIZE = 4
CANDIDATE_DEPTH = 10

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_RETRIEVAL_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_signal_results_c8f5c902f237ef70b4add45ee63815bd1cdafeb84741c86c1bd634b1df02127e.jsonl"
)
DEFAULT_RUNTIME_MANIFEST = Path(
    "data/v3/retrieval/"
    "retrieval_runtime_manifest_6605e9885a6c45d59d9852edc09ef0f93fcff427d8d29747e3d85ef8b7c94f65.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_ANSWERABILITY_SOURCE = Path("src/v3/select_evidence.py")
DEFAULT_SCORER_SOURCE = Path("src/v3/score_evidence_reranker.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def prepare_pairs(
    dev_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    retrieval_by_id = {row["dev_id"]: row for row in retrieval_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    if len(retrieval_by_id) != len(retrieval_rows):
        raise RuntimeError("Duplicate retrieval dev_id")
    if len(chunks_by_id) != len(chunks):
        raise RuntimeError("Duplicate ChunkV3 chunk_id")
    if set(retrieval_by_id) != {row["dev_id"] for row in dev_rows}:
        raise RuntimeError("Retrieval results differ from dev IDs")

    rows = []
    pairs: list[tuple[str, str]] = []
    for ordinal, dev in enumerate(dev_rows):
        decision = classify_answerability(dev["question"])
        hits = retrieval_by_id[dev["dev_id"]]["configurations"][CANDIDATE_CONFIG][
            "hits"
        ][:CANDIDATE_DEPTH]
        candidates = []
        if decision["label"] != "false":
            for hit in hits:
                chunk = chunks_by_id.get(hit["chunk_id"])
                if chunk is None:
                    raise RuntimeError(f"Unknown candidate chunk: {hit['chunk_id']}")
                pair_ordinal = len(pairs)
                pairs.append((dev["question"], chunk["retrieval_text"]))
                candidates.append(
                    {
                        "pair_ordinal": pair_ordinal,
                        "retrieval_rank": hit["rank"],
                        "chunk_id": hit["chunk_id"],
                        "parent_document_id": hit["parent_document_id"],
                        "source_id": hit["source_id"],
                        "status": hit["status"],
                        "default_exposure": hit["default_exposure"],
                        "review_required": hit["review_required"],
                        "base_score": hit["base_score"],
                        "guardrail_injected": hit["guardrail_injected"],
                    }
                )
        rows.append(
            {
                "score_schema_version": SCORE_SCHEMA_VERSION,
                "query_ordinal": ordinal,
                "dev_id": dev["dev_id"],
                "question": dev["question"],
                "predicted_answerability": decision["label"],
                "answerability_reason": decision["reason"],
                "scoring_status": "skipped_predicted_false"
                if decision["label"] == "false"
                else "pending",
                "candidates": candidates,
            }
        )
    return rows, pairs


def attach_scores(
    rows: list[dict[str, Any]], scores: np.ndarray | list[float]
) -> list[dict[str, Any]]:
    values = np.asarray(scores, dtype=np.float64).reshape(-1)
    expected = sum(len(row["candidates"]) for row in rows)
    if values.shape != (expected,) or not np.isfinite(values).all():
        raise RuntimeError("Reranker scores are missing, non-finite, or misaligned")

    output = []
    for row in rows:
        candidates = []
        for candidate in row["candidates"]:
            pair_ordinal = candidate["pair_ordinal"]
            candidates.append(
                {
                    **candidate,
                    "reranker_score": round(float(values[pair_ordinal]), 8),
                }
            )
        output.append(
            {
                **row,
                "scoring_status": "success" if candidates else row["scoring_status"],
                "candidates": candidates,
            }
        )
    return output


def run_model(
    pairs: list[tuple[str, str]], *, device: str
) -> tuple[np.ndarray, dict[str, Any]]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started_at = datetime.now(timezone.utc).isoformat()
    load_start = time.perf_counter()
    model = CrossEncoder(
        MODEL_NAME,
        revision=MODEL_REVISION,
        max_length=MAX_LENGTH,
        device=device,
        local_files_only=True,
    )
    load_seconds = time.perf_counter() - load_start
    score_start = time.perf_counter()
    scores = model.predict(
        pairs,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    if device == "cuda":
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - score_start
    latency = {
        "latency_schema_version": LATENCY_SCHEMA_VERSION,
        "measured_at": started_at,
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "pair_count": len(pairs),
        "batch_size": BATCH_SIZE,
        "max_length": MAX_LENGTH,
        "model_load_seconds": round(load_seconds, 6),
        "inference_seconds": round(inference_seconds, 6),
        "pairs_per_second": round(len(pairs) / inference_seconds, 6),
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated())
        if device == "cuda"
        else None,
    }
    return np.asarray(scores), latency


def freeze_outputs(
    root: Path,
    rows: list[dict[str, Any]],
    latency: dict[str, Any],
    input_paths: dict[str, Path],
    *,
    device: str,
) -> dict[str, Any]:
    hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    scores_bytes = _serialize_jsonl(rows, lambda row: row["query_ordinal"])
    scores_sha = _sha256_bytes(scores_bytes)
    scores_path = evidence_dir / f"evidence_reranker_scores_{scores_sha}.jsonl"
    write_immutable(scores_path, scores_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "model": {
            "name": MODEL_NAME,
            "revision": MODEL_REVISION,
            "max_length": MAX_LENGTH,
            "batch_size": BATCH_SIZE,
            "device": device,
            "score_rounding_decimals": 8,
        },
        "libraries": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "sentence_transformers": sentence_transformers.__version__,
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": hashes[name]}
            for name, path in input_paths.items()
        },
        "scores": {
            "path": _relative(root, scores_path),
            "sha256": scores_sha,
            "row_count": len(rows),
            "pair_count": sum(len(row["candidates"]) for row in rows),
            "skipped_predicted_false_count": sum(
                row["scoring_status"] == "skipped_predicted_false" for row in rows
            ),
        },
        "gold_ids_available_to_scorer": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"evidence_reranker_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    latency_report = {
        **latency,
        "scores_path": _relative(root, scores_path),
        "scores_sha256": scores_sha,
        "manifest_path": _relative(root, manifest_path),
        "manifest_sha256": manifest_sha,
        "observational_not_reproducibility_input": True,
    }
    latency_bytes = _canonical_json_bytes(latency_report)
    latency_sha = _sha256_bytes(latency_bytes)
    latency_path = reports_dir / f"evidence_reranker_latency_{latency_sha}.json"
    write_immutable(latency_path, latency_bytes)
    return {
        "scores_path": str(scores_path),
        "scores_sha256": scores_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "latency_report_path": str(latency_path),
        "latency_report_sha256": latency_sha,
        "latency": latency,
    }


def build_and_freeze(
    root: Path,
    dev_path: Path,
    retrieval_results_path: Path,
    runtime_manifest_path: Path,
    chunks_path: Path,
    answerability_source_path: Path,
    scorer_source_path: Path,
    *,
    device: str,
) -> dict[str, Any]:
    rows, pairs = prepare_pairs(
        read_jsonl(dev_path), read_jsonl(retrieval_results_path), read_jsonl(chunks_path)
    )
    scores, latency = run_model(pairs, device=device)
    scored_rows = attach_scores(rows, scores)
    return freeze_outputs(
        root,
        scored_rows,
        latency,
        {
            "dev_set": dev_path,
            "retrieval_results": retrieval_results_path,
            "runtime_manifest": runtime_manifest_path,
            "chunks": chunks_path,
            "answerability_source": answerability_source_path,
            "scorer_source": scorer_source_path,
        },
        device=device,
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Score v3 evidence candidates with BGE reranker")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--retrieval-results", type=Path, default=root / DEFAULT_RETRIEVAL_RESULTS
    )
    parser.add_argument(
        "--runtime-manifest", type=Path, default=root / DEFAULT_RUNTIME_MANIFEST
    )
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument(
        "--answerability-source", type=Path, default=root / DEFAULT_ANSWERABILITY_SOURCE
    )
    parser.add_argument("--scorer-source", type=Path, default=root / DEFAULT_SCORER_SOURCE)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.retrieval_results.resolve(),
        args.runtime_manifest.resolve(),
        args.chunks.resolve(),
        args.answerability_source.resolve(),
        args.scorer_source.resolve(),
        device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
