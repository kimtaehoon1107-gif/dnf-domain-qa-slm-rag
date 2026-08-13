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
from src.v3.build_bm25 import SearchPolicy, _allowed, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.build_dense_pilot import search_dense
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)


EVALUATOR_VERSION = "retrieval-ab-evaluator-v3.1.0"
RESULT_SCHEMA_VERSION = "retrieval-ab-result-v3.1"
MANIFEST_SCHEMA_VERSION = "retrieval-ab-manifest-v3.1"
REPORT_SCHEMA_VERSION = "retrieval-ab-report-v3.1"
TOP_K_VALUES = (1, 3, 5, 10, 20)
EXPECTED_DEV_ROWS = 63
EXPECTED_EVALUATED_ROWS = 55

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_DEV_MANIFEST = Path(
    "data/v3/evaluation/"
    "retrieval_dev_manifest_bb5a858702d8b8c0c267f35309db75221f8e9d5515e30f34b4e6b9dfb17dcec3.json"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/"
    "bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_DENSE_MANIFEST = Path(
    "data/v3/indexes/"
    "dense_full_manifest_51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)


def _resolve(root: Path, path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verify_content_hash(path: Path, expected: str | None = None) -> str:
    if not path.is_file():
        raise RuntimeError(f"Artifact does not exist: {path}")
    actual = file_sha256(path)
    if expected is not None and actual != expected:
        raise RuntimeError(f"Artifact hash mismatch: {path}")
    return actual


def load_retrieval_artifacts(
    root: Path,
    bm25_manifest_path: Path,
    dense_manifest_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], np.ndarray, dict[str, Any], dict[str, Any]]:
    bm25_manifest_hash = _verify_content_hash(bm25_manifest_path)
    dense_manifest_hash = _verify_content_hash(dense_manifest_path)
    bm25_manifest = json.loads(bm25_manifest_path.read_text(encoding="utf-8"))
    dense_manifest = json.loads(dense_manifest_path.read_text(encoding="utf-8"))

    bm25_index_path = _resolve(root, bm25_manifest["index"]["path"])
    _verify_content_hash(bm25_index_path, bm25_manifest["index"]["sha256"])
    bm25_index = json.loads(bm25_index_path.read_text(encoding="utf-8"))

    metadata_path = _resolve(root, dense_manifest["metadata"]["path"])
    embeddings_path = _resolve(root, dense_manifest["embeddings"]["path"])
    _verify_content_hash(metadata_path, dense_manifest["metadata"]["sha256"])
    _verify_content_hash(embeddings_path, dense_manifest["embeddings"]["sha256"])
    metadata = read_jsonl(metadata_path)
    row_count = dense_manifest["embeddings"]["row_count"]
    dimension = dense_manifest["embeddings"]["dimension"]
    embeddings = np.fromfile(embeddings_path, dtype="<f4")
    if embeddings.size != row_count * dimension:
        raise RuntimeError("Dense embedding byte length differs from manifest shape")
    embeddings = embeddings.reshape(row_count, dimension)
    if len(metadata) != row_count:
        raise RuntimeError("Dense metadata row count differs from embedding matrix")
    if [row["ordinal"] for row in metadata] != list(range(row_count)):
        raise RuntimeError("Dense metadata ordinals are not contiguous")
    if [row["chunk_id"] for row in bm25_index["entries"]] != [
        row["chunk_id"] for row in metadata
    ]:
        raise RuntimeError("BM25 and dense chunk ordering differs")

    provenance = {
        "bm25_manifest_path": _relative(root, bm25_manifest_path),
        "bm25_manifest_sha256": bm25_manifest_hash,
        "bm25_index_path": _relative(root, bm25_index_path),
        "bm25_index_sha256": bm25_manifest["index"]["sha256"],
        "dense_manifest_path": _relative(root, dense_manifest_path),
        "dense_manifest_sha256": dense_manifest_hash,
        "dense_metadata_path": _relative(root, metadata_path),
        "dense_metadata_sha256": dense_manifest["metadata"]["sha256"],
        "dense_embeddings_path": _relative(root, embeddings_path),
        "dense_embeddings_sha256": dense_manifest["embeddings"]["sha256"],
    }
    return bm25_index, metadata, embeddings, dense_manifest["model"], provenance


def encode_queries(
    questions: list[str],
    model_info: dict[str, Any],
    *,
    device: str | None,
    batch_size: int,
) -> tuple[np.ndarray, dict[str, Any]]:
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
        model_info["model_name"],
        device=selected_device,
        local_files_only=True,
    )
    model.max_seq_length = model_info["max_sequence_length"]
    encoded = model.encode(
        questions,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    embeddings = np.asarray(encoded, dtype="<f4")
    if embeddings.shape != (len(questions), model_info["embedding_dimension"]):
        raise RuntimeError("Query embedding shape differs from dense model contract")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("Query embeddings contain NaN or Inf")
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(np.abs(norms - 1.0) > 1e-5):
        raise RuntimeError("Query embeddings are not normalized")
    query_model = {
        "model_name": model_info["model_name"],
        "model_revision": model_info["model_revision"],
        "max_sequence_length": model_info["max_sequence_length"],
        "embedding_dimension": model_info["embedding_dimension"],
        "normalize_embeddings": True,
        "device": selected_device,
        "device_name": torch.cuda.get_device_name(0) if selected_device == "cuda" else "cpu",
        "batch_size": batch_size,
        "sentence_transformers_version": sentence_transformers.__version__,
        "torch_version": torch.__version__,
        "numpy_version": np.__version__,
    }
    return embeddings, query_model


def policy_from_dev(row: dict[str, Any]) -> SearchPolicy:
    policy = row["query_policy"]
    statuses = policy["allowed_statuses"]
    return SearchPolicy(
        default_exposure_only=policy["default_exposure_only"],
        allowed_statuses=tuple(statuses) if statuses is not None else None,
        include_review_required=policy["include_review_required"],
        as_of=policy["as_of"],
        source_ids=None,
    )


def score_ranked_hits(
    evidence_groups: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    *,
    top_k_values: tuple[int, ...] = TOP_K_VALUES,
) -> dict[str, Any]:
    if not evidence_groups:
        return {
            "evaluated": False,
            "group_first_ranks": [],
            "reciprocal_rank": None,
            "at_k": {},
        }
    rank_by_chunk = {row["chunk_id"]: row["rank"] for row in hits}
    group_first_ranks: list[int | None] = []
    for group in evidence_groups:
        ranks = [
            rank_by_chunk[chunk_id]
            for chunk_id in group["acceptable_chunk_ids"]
            if chunk_id in rank_by_chunk
        ]
        group_first_ranks.append(min(ranks) if ranks else None)
    first_rank = min((rank for rank in group_first_ranks if rank is not None), default=None)
    at_k = {}
    for top_k in top_k_values:
        hit_count = sum(rank is not None and rank <= top_k for rank in group_first_ranks)
        at_k[str(top_k)] = {
            "any_hit": hit_count > 0,
            "all_groups_hit": hit_count == len(group_first_ranks),
            "evidence_group_recall": round(hit_count / len(group_first_ranks), 6),
        }
    return {
        "evaluated": True,
        "group_first_ranks": group_first_ranks,
        "reciprocal_rank": round(1.0 / first_rank, 8) if first_rank else 0.0,
        "at_k": at_k,
    }


def _compact_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": row["rank"],
            "score": round(float(row["score"]), 8),
            "chunk_id": row["chunk_id"],
            "parent_document_id": row["parent_document_id"],
            "source_id": row["source_id"],
            "status": row["status"],
            "default_exposure": row["default_exposure"],
            "review_required": row["review_required"],
        }
        for row in hits
    ]


def evaluate_rows(
    dev_rows: list[dict[str, Any]],
    bm25_index: dict[str, Any],
    dense_metadata: list[dict[str, Any]],
    dense_embeddings: np.ndarray,
    query_embeddings: np.ndarray,
    *,
    top_k_values: tuple[int, ...] = TOP_K_VALUES,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if len(dev_rows) != query_embeddings.shape[0]:
        raise RuntimeError("Dev row and query embedding counts differ")
    if tuple(sorted(top_k_values)) != top_k_values or top_k_values[0] <= 0:
        raise RuntimeError("top_k_values must be positive and increasing")
    max_k = top_k_values[-1]
    bm25_entries = bm25_index["entries"]
    results = []
    parity_mismatches = 0
    excluded_gold = 0
    empty_candidate_queries = 0
    for query_ordinal, (dev, query_embedding) in enumerate(zip(dev_rows, query_embeddings)):
        policy = policy_from_dev(dev)
        bm25_allowed = {
            row["chunk_id"] for row in bm25_entries if _allowed(row, policy)
        }
        dense_allowed = {
            row["chunk_id"] for row in dense_metadata if _allowed(row, policy)
        }
        parity_mismatches += len(bm25_allowed ^ dense_allowed)
        excluded_gold += sum(chunk_id not in bm25_allowed for chunk_id in dev["gold_chunk_ids"])
        if not bm25_allowed:
            empty_candidate_queries += 1
        bm25_hits = search_bm25(
            bm25_index, dev["question"], top_k=max_k, policy=policy
        )
        dense_hits = search_dense(
            dense_embeddings,
            dense_metadata,
            query_embedding,
            top_k=max_k,
            policy=policy,
        )
        systems = {}
        for system_name, hits in (("bm25", bm25_hits), ("dense", dense_hits)):
            systems[system_name] = {
                "metrics": score_ranked_hits(
                    dev["evidence_groups"], hits, top_k_values=top_k_values
                ),
                "hits": _compact_hits(hits),
            }
        results.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "query_ordinal": query_ordinal,
                "dev_id": dev["dev_id"],
                "question": dev["question"],
                "answerability": dev["answerability"],
                "query_kind": dev["query_kind"],
                "source_ids": dev["source_ids"],
                "target_statuses": dev["target_statuses"],
                "query_policy": dev["query_policy"],
                "candidate_count": len(bm25_allowed),
                "required_evidence_group_count": dev["required_evidence_group_count"],
                "systems": systems,
            }
        )
    audit = {
        "filter_candidate_set_mismatches": parity_mismatches,
        "gold_chunks_excluded_by_policy": excluded_gold,
        "empty_candidate_queries": empty_candidate_queries,
    }
    return results, audit


def _aggregate_subset(rows: list[dict[str, Any]], system_name: str) -> dict[str, Any]:
    evaluated = [row for row in rows if row["systems"][system_name]["metrics"]["evaluated"]]
    if not evaluated:
        return {"row_count": len(rows), "evaluated_count": 0, "mrr": None, "at_k": {}}
    at_k = {}
    for top_k in TOP_K_VALUES:
        key = str(top_k)
        metrics = [row["systems"][system_name]["metrics"]["at_k"][key] for row in evaluated]
        group_total = sum(row["required_evidence_group_count"] for row in evaluated)
        group_hits = sum(
            metric["evidence_group_recall"] * row["required_evidence_group_count"]
            for metric, row in zip(metrics, evaluated)
        )
        at_k[key] = {
            "hit_rate": round(sum(metric["any_hit"] for metric in metrics) / len(metrics), 6),
            "all_groups_hit_rate": round(
                sum(metric["all_groups_hit"] for metric in metrics) / len(metrics), 6
            ),
            "evidence_group_recall_micro": round(group_hits / group_total, 6),
            "evidence_group_recall_macro": round(
                sum(metric["evidence_group_recall"] for metric in metrics) / len(metrics), 6
            ),
        }
    return {
        "row_count": len(rows),
        "evaluated_count": len(evaluated),
        "mrr": round(
            sum(row["systems"][system_name]["metrics"]["reciprocal_rank"] for row in evaluated)
            / len(evaluated),
            6,
        ),
        "at_k": at_k,
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    systems = {
        system_name: _aggregate_subset(results, system_name)
        for system_name in ("bm25", "dense")
    }
    breakdowns: dict[str, dict[str, dict[str, Any]]] = {}
    for field in ("answerability", "query_kind"):
        values = sorted({row[field] for row in results})
        breakdowns[field] = {
            value: {
                system_name: _aggregate_subset(
                    [row for row in results if row[field] == value], system_name
                )
                for system_name in ("bm25", "dense")
            }
            for value in values
        }
    source_ids = sorted({source_id for row in results for source_id in row["source_ids"]})
    breakdowns["source_id"] = {
        source_id: {
            system_name: _aggregate_subset(
                [row for row in results if source_id in row["source_ids"]], system_name
            )
            for system_name in ("bm25", "dense")
        }
        for source_id in source_ids
    }
    complementarity = {}
    for top_k in TOP_K_VALUES:
        key = str(top_k)
        counts = Counter()
        for row in results:
            bm = row["systems"]["bm25"]["metrics"]
            dense = row["systems"]["dense"]["metrics"]
            if not bm["evaluated"]:
                continue
            bm_hit = bm["at_k"][key]["any_hit"]
            dense_hit = dense["at_k"][key]["any_hit"]
            counts[
                "both" if bm_hit and dense_hit else "bm25_only" if bm_hit else "dense_only" if dense_hit else "neither"
            ] += 1
        complementarity[key] = {
            name: counts[name] for name in ("both", "bm25_only", "dense_only", "neither")
        }
    return {
        "row_count": len(results),
        "evaluated_count": sum(row["answerability"] != "false" for row in results),
        "unanswerable_count": sum(row["answerability"] == "false" for row in results),
        "systems": systems,
        "complementarity": complementarity,
        "breakdowns": breakdowns,
    }


def audit_evaluation(
    dev_rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
    runtime_audit: dict[str, int],
    dense_embeddings: np.ndarray,
    query_embeddings: np.ndarray,
) -> dict[str, Any]:
    finite_scores = all(
        math.isfinite(hit["score"])
        for row in results
        for system in row["systems"].values()
        for hit in system["hits"]
    )
    gates = {
        "dev_row_count_63": len(dev_rows) == EXPECTED_DEV_ROWS,
        "evaluated_row_count_55": sum(row["answerability"] != "false" for row in dev_rows)
        == EXPECTED_EVALUATED_ROWS,
        "result_row_count_matches_dev": len(results) == len(dev_rows),
        "duplicate_dev_id_0": len({row["dev_id"] for row in results}) == len(results),
        "filter_candidate_set_mismatch_0": runtime_audit["filter_candidate_set_mismatches"] == 0,
        "gold_excluded_by_policy_0": runtime_audit["gold_chunks_excluded_by_policy"] == 0,
        "empty_candidate_query_0": runtime_audit["empty_candidate_queries"] == 0,
        "dense_matrix_finite": bool(np.isfinite(dense_embeddings).all()),
        "query_matrix_finite": bool(np.isfinite(query_embeddings).all()),
        "embedding_dimensions_match": dense_embeddings.shape[1] == query_embeddings.shape[1],
        "retrieval_scores_finite": finite_scores,
        "training_leak_0": not any(row["training_allowed"] for row in dev_rows),
        "final_benchmark_leak_0": not any(row["final_benchmark_eligible"] for row in dev_rows),
    }
    return {
        **runtime_audit,
        "gates": gates,
        "gate_pass": all(gates.values()),
    }


def _failure_cases(results: list[dict[str, Any]], top_k: int = 10) -> dict[str, list[dict[str, Any]]]:
    failures = {}
    for system_name in ("bm25", "dense"):
        rows = []
        for row in results:
            metrics = row["systems"][system_name]["metrics"]
            if metrics["evaluated"] and not metrics["at_k"][str(top_k)]["all_groups_hit"]:
                rows.append(
                    {
                        "dev_id": row["dev_id"],
                        "question": row["question"],
                        "query_kind": row["query_kind"],
                        "source_ids": row["source_ids"],
                        "group_first_ranks": metrics["group_first_ranks"],
                    }
                )
        failures[system_name] = rows
    return failures


def _markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        "# DNF RAG v3 BM25 vs Dense Retrieval Dev Evaluation",
        "",
        "## Decision",
        "",
        f"- Evaluation integrity: **{report['decision']['evaluation_integrity']}**",
        f"- Hybrid experiment entry: **{report['decision']['hybrid_experiment_entry']}**",
        f"- Hybrid promotion: **{report['decision']['hybrid_promotion']}**",
        f"- Final benchmark: **{report['decision']['final_benchmark']}**",
        "",
        "## Overall metrics (55 answerable/partial rows)",
        "",
        "| system | MRR | hit@1 | hit@5 | hit@10 | hit@20 | group recall@10 | all groups@10 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for system_name in ("bm25", "dense"):
        metrics = aggregate["systems"][system_name]
        lines.append(
            "| {name} | {mrr:.4f} | {h1:.4f} | {h5:.4f} | {h10:.4f} | {h20:.4f} | {g10:.4f} | {a10:.4f} |".format(
                name=system_name,
                mrr=metrics["mrr"],
                h1=metrics["at_k"]["1"]["hit_rate"],
                h5=metrics["at_k"]["5"]["hit_rate"],
                h10=metrics["at_k"]["10"]["hit_rate"],
                h20=metrics["at_k"]["20"]["hit_rate"],
                g10=metrics["at_k"]["10"]["evidence_group_recall_micro"],
                a10=metrics["at_k"]["10"]["all_groups_hit_rate"],
            )
        )
    comp = aggregate["complementarity"]["10"]
    lines.extend(
        [
            "",
            "## Complementarity at 10",
            "",
            f"- both: {comp['both']}",
            f"- BM25 only: {comp['bm25_only']}",
            f"- dense only: {comp['dense_only']}",
            f"- neither: {comp['neither']}",
            "",
            "## Artifacts",
            "",
            f"- results: `{report['artifacts']['results_path']}`",
            f"- results SHA-256: `{report['artifacts']['results_sha256']}`",
            f"- query embeddings: `{report['artifacts']['query_embeddings_path']}`",
            f"- query embeddings SHA-256: `{report['artifacts']['query_embeddings_sha256']}`",
            f"- manifest: `{report['artifacts']['manifest_path']}`",
            f"- manifest SHA-256: `{report['artifacts']['manifest_sha256']}`",
            "",
            "The 8 unanswerable rows are retained for later answerability evaluation but are excluded from gold retrieval metrics. No hybrid weights, Router, generation, training, or frozen blind benchmark were evaluated.",
        ]
    )
    return "\n".join(lines) + "\n"


def freeze_evaluation(
    root: Path,
    dev_path: Path,
    dev_manifest_path: Path,
    bm25_manifest_path: Path,
    dense_manifest_path: Path,
    query_embeddings: np.ndarray,
    query_model: dict[str, Any],
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    dev_hash = _verify_content_hash(dev_path)
    dev_manifest_hash = _verify_content_hash(dev_manifest_path)
    dev_rows = read_jsonl(dev_path)
    bm25_index, dense_metadata, dense_embeddings, dense_model, input_provenance = load_retrieval_artifacts(
        root, bm25_manifest_path, dense_manifest_path
    )
    query_embeddings = np.asarray(query_embeddings, dtype="<f4")
    if query_embeddings.shape != (len(dev_rows), dense_embeddings.shape[1]):
        raise RuntimeError("Frozen query embedding shape differs from dev/dense inputs")
    results, runtime_audit = evaluate_rows(
        dev_rows,
        bm25_index,
        dense_metadata,
        dense_embeddings,
        query_embeddings,
    )
    audit = audit_evaluation(
        dev_rows, results, runtime_audit, dense_embeddings, query_embeddings
    )
    if not audit["gate_pass"]:
        failed = [name for name, passed in audit["gates"].items() if not passed]
        raise RuntimeError(f"Retrieval evaluation gates failed: {failed}")
    aggregate = aggregate_results(results)

    retrieval_dir = artifact_root / "data/v3/retrieval"
    reports_dir = artifact_root / "reports/v3"
    query_bytes = query_embeddings.astype("<f4", copy=False).tobytes(order="C")
    query_sha = _sha256_bytes(query_bytes)
    query_path = retrieval_dir / f"retrieval_dev_query_embeddings_{query_sha}.f32"
    write_immutable(query_path, query_bytes)

    result_bytes = _serialize_jsonl(results, lambda row: row["query_ordinal"])
    result_sha = _sha256_bytes(result_bytes)
    result_path = retrieval_dir / f"retrieval_ab_results_{result_sha}.jsonl"
    write_immutable(result_path, result_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "top_k_values": list(TOP_K_VALUES),
        "inputs": {
            "dev_set": {"path": _relative(root, dev_path), "sha256": dev_hash},
            "dev_manifest": {
                "path": _relative(root, dev_manifest_path),
                "sha256": dev_manifest_hash,
            },
            **input_provenance,
        },
        "query_embeddings": {
            "path": _relative(artifact_root, query_path),
            "sha256": query_sha,
            "row_count": query_embeddings.shape[0],
            "dimension": query_embeddings.shape[1],
            "dtype": "little_endian_float32",
            "row_order": "dev_set_query_ordinal",
        },
        "query_model": query_model,
        "dense_model": dense_model,
        "results": {
            "path": _relative(artifact_root, result_path),
            "sha256": result_sha,
            "row_count": len(results),
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = retrieval_dir / f"retrieval_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    comp10 = aggregate["complementarity"]["10"]
    hybrid_entry = (
        "GO"
        if comp10["bm25_only"] > 0 and comp10["dense_only"] > 0
        else "REVIEW"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": {
            "evaluation_integrity": "GO",
            "hybrid_experiment_entry": hybrid_entry,
            "hybrid_promotion": "NOT_RUN",
            "final_benchmark": "NO-GO",
        },
        "aggregate": aggregate,
        "audit": audit,
        "failure_cases_at_10": _failure_cases(results, 10),
        "artifacts": {
            "results_path": _relative(artifact_root, result_path),
            "results_sha256": result_sha,
            "query_embeddings_path": _relative(artifact_root, query_path),
            "query_embeddings_sha256": query_sha,
            "manifest_path": _relative(artifact_root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "hybrid_weights",
            "router_behavior",
            "answerability_classification",
            "generation_quality",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"retrieval_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown)
    markdown_path = reports_dir / f"retrieval_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown)
    return {
        "query_embeddings_path": str(query_path),
        "query_embeddings_sha256": query_sha,
        "results_path": str(result_path),
        "results_sha256": result_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
        "aggregate": aggregate,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Evaluate frozen v3 BM25 and dense retrieval")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument("--dev-manifest", type=Path, default=root / DEFAULT_DEV_MANIFEST)
    parser.add_argument("--bm25-manifest", type=Path, default=root / DEFAULT_BM25_MANIFEST)
    parser.add_argument("--dense-manifest", type=Path, default=root / DEFAULT_DENSE_MANIFEST)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--query-embeddings", type=Path)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    dev_path = args.dev_set.resolve()
    dense_manifest = json.loads(args.dense_manifest.read_text(encoding="utf-8"))
    dev_rows = read_jsonl(dev_path)
    model_info = dense_manifest["model"]
    if args.query_embeddings:
        dimension = model_info["embedding_dimension"]
        query_embeddings = np.fromfile(args.query_embeddings, dtype="<f4")
        if query_embeddings.size != len(dev_rows) * dimension:
            raise RuntimeError("Provided query embedding byte length is invalid")
        query_embeddings = query_embeddings.reshape(len(dev_rows), dimension)
        query_model = {
            **model_info,
            "device": "frozen_override",
            "batch_size": None,
            "source_path": _relative(root, args.query_embeddings.resolve()),
            "source_sha256": _verify_content_hash(args.query_embeddings.resolve()),
        }
    else:
        query_embeddings, query_model = encode_queries(
            [row["question"] for row in dev_rows],
            model_info,
            device=args.device,
            batch_size=args.batch_size,
        )
    result = freeze_evaluation(
        root,
        dev_path,
        args.dev_manifest.resolve(),
        args.bm25_manifest.resolve(),
        args.dense_manifest.resolve(),
        query_embeddings,
        query_model,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
