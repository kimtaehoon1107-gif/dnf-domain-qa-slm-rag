from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_retrieval import TOP_K_VALUES, score_ranked_hits


EVALUATOR_VERSION = "hybrid-minmax-grid-v3.1.0"
RESULT_SCHEMA_VERSION = "hybrid-grid-result-v3.1"
MANIFEST_SCHEMA_VERSION = "hybrid-grid-manifest-v3.1"
REPORT_SCHEMA_VERSION = "hybrid-grid-report-v3.1"
DENSE_WEIGHTS = (0.25, 0.50, 0.75)
MAX_INPUT_RANK = 20

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_RETRIEVAL_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_ab_results_c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620.jsonl"
)
DEFAULT_RETRIEVAL_MANIFEST = Path(
    "data/v3/retrieval/"
    "retrieval_ab_manifest_5d96c252d65aed8632f2a72581641150fe04f04903f283c97cfae29686abc0ca.json"
)
DEFAULT_RETRIEVAL_REPORT = Path(
    "reports/v3/"
    "retrieval_ab_5c8ebeb3606d785e7c898f32eef036b2fa2f8c8c1dbfbe49957602f23e907550.json"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verify_hash(path: Path, expected: str | None = None) -> str:
    if not path.is_file():
        raise RuntimeError(f"Artifact does not exist: {path}")
    actual = file_sha256(path)
    if expected is not None and actual != expected:
        raise RuntimeError(f"Artifact hash mismatch: {path}")
    return actual


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def config_name(dense_weight: float) -> str:
    return f"dense_{int(round(dense_weight * 100)):02d}_bm25_{int(round((1.0 - dense_weight) * 100)):02d}"


def normalize_minmax(hits: list[dict[str, Any]]) -> dict[str, float]:
    if not hits:
        return {}
    values = [float(row["score"]) for row in hits]
    low = min(values)
    high = max(values)
    if high == low:
        return {row["chunk_id"]: 1.0 for row in hits}
    return {
        row["chunk_id"]: (float(row["score"]) - low) / (high - low)
        for row in hits
    }


def fuse_hits(
    bm25_hits: list[dict[str, Any]],
    dense_hits: list[dict[str, Any]],
    *,
    dense_weight: float,
    top_k: int = MAX_INPUT_RANK,
) -> list[dict[str, Any]]:
    if not 0.0 < dense_weight < 1.0:
        raise RuntimeError("dense_weight must be strictly between 0 and 1")
    if top_k <= 0:
        raise RuntimeError("top_k must be positive")
    bm25_scores = normalize_minmax(bm25_hits)
    dense_scores = normalize_minmax(dense_hits)
    metadata: dict[str, dict[str, Any]] = {}
    for row in bm25_hits + dense_hits:
        existing = metadata.get(row["chunk_id"])
        if existing is not None:
            for key in (
                "parent_document_id",
                "source_id",
                "status",
                "default_exposure",
                "review_required",
            ):
                if existing[key] != row[key]:
                    raise RuntimeError(f"Hybrid metadata mismatch for {row['chunk_id']}")
        else:
            metadata[row["chunk_id"]] = row
    weighted = []
    for chunk_id in sorted(bm25_scores.keys() | dense_scores.keys()):
        bm25_score = bm25_scores.get(chunk_id, 0.0)
        dense_score = dense_scores.get(chunk_id, 0.0)
        score = (1.0 - dense_weight) * bm25_score + dense_weight * dense_score
        weighted.append((chunk_id, score, bm25_score, dense_score))
    weighted.sort(key=lambda item: (-item[1], item[0]))
    results = []
    for rank, (chunk_id, score, bm25_score, dense_score) in enumerate(
        weighted[:top_k], start=1
    ):
        row = metadata[chunk_id]
        results.append(
            {
                "rank": rank,
                "score": round(score, 8),
                "bm25_normalized_score": round(bm25_score, 8),
                "dense_normalized_score": round(dense_score, 8),
                "chunk_id": chunk_id,
                "parent_document_id": row["parent_document_id"],
                "source_id": row["source_id"],
                "status": row["status"],
                "default_exposure": row["default_exposure"],
                "review_required": row["review_required"],
            }
        )
    return results


def evaluate_grid(
    dev_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    *,
    dense_weights: tuple[float, ...] = DENSE_WEIGHTS,
) -> list[dict[str, Any]]:
    dev_by_id = {row["dev_id"]: row for row in dev_rows}
    if len(dev_by_id) != len(dev_rows):
        raise RuntimeError("Duplicate dev_id in retrieval dev set")
    if len({row["dev_id"] for row in retrieval_rows}) != len(retrieval_rows):
        raise RuntimeError("Duplicate dev_id in retrieval results")
    if set(dev_by_id) != {row["dev_id"] for row in retrieval_rows}:
        raise RuntimeError("Retrieval results and dev set IDs differ")
    output = []
    for retrieval in sorted(retrieval_rows, key=lambda row: row["query_ordinal"]):
        dev = dev_by_id[retrieval["dev_id"]]
        configurations = {}
        for dense_weight in dense_weights:
            name = config_name(dense_weight)
            hits = fuse_hits(
                retrieval["systems"]["bm25"]["hits"],
                retrieval["systems"]["dense"]["hits"],
                dense_weight=dense_weight,
            )
            configurations[name] = {
                "dense_weight": dense_weight,
                "bm25_weight": 1.0 - dense_weight,
                "metrics": score_ranked_hits(dev["evidence_groups"], hits),
                "hits": hits,
            }
        output.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "query_ordinal": retrieval["query_ordinal"],
                "dev_id": retrieval["dev_id"],
                "question": retrieval["question"],
                "answerability": retrieval["answerability"],
                "query_kind": retrieval["query_kind"],
                "source_ids": retrieval["source_ids"],
                "required_evidence_group_count": retrieval[
                    "required_evidence_group_count"
                ],
                "configurations": configurations,
            }
        )
    return output


def aggregate_configuration(
    rows: list[dict[str, Any]], config: str
) -> dict[str, Any]:
    evaluated = [
        row for row in rows if row["configurations"][config]["metrics"]["evaluated"]
    ]
    at_k = {}
    for top_k in TOP_K_VALUES:
        key = str(top_k)
        metrics = [row["configurations"][config]["metrics"]["at_k"][key] for row in evaluated]
        group_total = sum(row["required_evidence_group_count"] for row in evaluated)
        group_hits = sum(
            metric["evidence_group_recall"] * row["required_evidence_group_count"]
            for row, metric in zip(evaluated, metrics)
        )
        at_k[key] = {
            "hit_rate": round(sum(metric["any_hit"] for metric in metrics) / len(metrics), 6),
            "all_groups_hit_rate": round(
                sum(metric["all_groups_hit"] for metric in metrics) / len(metrics), 6
            ),
            "evidence_group_recall_micro": round(group_hits / group_total, 6),
            "evidence_group_recall_macro": round(
                sum(metric["evidence_group_recall"] for metric in metrics) / len(metrics),
                6,
            ),
        }
    return {
        "row_count": len(rows),
        "evaluated_count": len(evaluated),
        "mrr": round(
            sum(row["configurations"][config]["metrics"]["reciprocal_rank"] for row in evaluated)
            / len(evaluated),
            6,
        ),
        "at_k": at_k,
    }


def aggregate_grid(rows: list[dict[str, Any]]) -> dict[str, Any]:
    configs = sorted(rows[0]["configurations"])
    overall = {config: aggregate_configuration(rows, config) for config in configs}
    sources = sorted({source_id for row in rows for source_id in row["source_ids"]})
    by_source = {
        source_id: {
            config: aggregate_configuration(
                [row for row in rows if source_id in row["source_ids"]], config
            )
            for config in configs
        }
        for source_id in sources
    }
    by_query_kind = {
        query_kind: {
            config: aggregate_configuration(
                [row for row in rows if row["query_kind"] == query_kind], config
            )
            for config in configs
        }
        for query_kind in sorted({row["query_kind"] for row in rows})
        if query_kind != "unanswerable"
    }
    return {
        "overall": overall,
        "by_source": by_source,
        "by_query_kind": by_query_kind,
    }


def choose_best_config(aggregate: dict[str, Any]) -> str:
    def key(config: str) -> tuple[float, ...]:
        metrics = aggregate["overall"][config]
        at_10 = metrics["at_k"]["10"]
        return (
            at_10["hit_rate"],
            at_10["all_groups_hit_rate"],
            at_10["evidence_group_recall_micro"],
            metrics["mrr"],
            -abs(float(config.split("_")[1]) / 100.0 - 0.5),
        )

    return max(sorted(aggregate["overall"]), key=key)


def promotion_audit(
    aggregate: dict[str, Any],
    baseline_report: dict[str, Any],
    best_config: str,
) -> dict[str, Any]:
    candidate = aggregate["overall"][best_config]
    dense = baseline_report["aggregate"]["systems"]["dense"]
    candidate_at_10 = candidate["at_k"]["10"]
    dense_at_10 = dense["at_k"]["10"]
    source_deltas = {}
    for source_id, source_metrics in aggregate["by_source"].items():
        candidate_value = source_metrics[best_config]["at_k"]["10"][
            "all_groups_hit_rate"
        ]
        dense_value = baseline_report["aggregate"]["breakdowns"]["source_id"][
            source_id
        ]["dense"]["at_k"]["10"]["all_groups_hit_rate"]
        source_deltas[source_id] = round(candidate_value - dense_value, 6)
    candidate_worst = min(
        source_metrics[best_config]["at_k"]["10"]["all_groups_hit_rate"]
        for source_metrics in aggregate["by_source"].values()
    )
    dense_worst = min(
        source_metrics["dense"]["at_k"]["10"]["all_groups_hit_rate"]
        for source_metrics in baseline_report["aggregate"]["breakdowns"]["source_id"].values()
    )
    gates = {
        "hit_rate_at_10_strictly_improved": candidate_at_10["hit_rate"]
        > dense_at_10["hit_rate"],
        "all_groups_at_10_strictly_improved": candidate_at_10["all_groups_hit_rate"]
        > dense_at_10["all_groups_hit_rate"],
        "group_recall_at_10_strictly_improved": candidate_at_10[
            "evidence_group_recall_micro"
        ]
        > dense_at_10["evidence_group_recall_micro"],
        "mrr_not_regressed": candidate["mrr"] >= dense["mrr"],
        "source_regression_0": all(delta >= 0.0 for delta in source_deltas.values()),
        "worst_source_at_10_strictly_improved": candidate_worst > dense_worst,
    }
    return {
        "best_config": best_config,
        "candidate": candidate,
        "dense_baseline": dense,
        "source_all_groups_at_10_deltas": source_deltas,
        "candidate_worst_source_all_groups_at_10": candidate_worst,
        "dense_worst_source_all_groups_at_10": dense_worst,
        "gates": gates,
        "promotion_pass": all(gates.values()),
    }


def audit_results(
    dev_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    hybrid_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    scores_finite = all(
        math.isfinite(hit["score"])
        for row in hybrid_rows
        for config in row["configurations"].values()
        for hit in config["hits"]
    )
    unique_hits = all(
        len({hit["chunk_id"] for hit in config["hits"]}) == len(config["hits"])
        for row in hybrid_rows
        for config in row["configurations"].values()
    )
    gates = {
        "dev_rows_63": len(dev_rows) == 63,
        "retrieval_rows_63": len(retrieval_rows) == 63,
        "hybrid_rows_63": len(hybrid_rows) == 63,
        "query_ordinals_contiguous": [row["query_ordinal"] for row in hybrid_rows]
        == list(range(63)),
        "config_grid_exact": all(
            set(row["configurations"])
            == {config_name(weight) for weight in DENSE_WEIGHTS}
            for row in hybrid_rows
        ),
        "scores_finite": scores_finite,
        "duplicate_hit_0": unique_hits,
        "training_leak_0": not any(row["training_allowed"] for row in dev_rows),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in dev_rows
        ),
    }
    return {"gates": gates, "gate_pass": all(gates.values())}


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DNF RAG v3 Hybrid Fusion Grid",
        "",
        "## Decision",
        "",
        f"- Experiment integrity: **{report['decision']['experiment_integrity']}**",
        f"- Best measured config: `{report['promotion_audit']['best_config']}`",
        f"- Hybrid promotion: **{report['decision']['hybrid_promotion']}**",
        f"- Final benchmark: **{report['decision']['final_benchmark']}**",
        "",
        "## Overall",
        "",
        "| configuration | MRR | hit@10 | all groups@10 | group recall@10 |",
        "|---|---:|---:|---:|---:|",
    ]
    dense = report["baseline"]["dense"]
    lines.append(
        f"| dense baseline | {dense['mrr']:.4f} | {dense['at_k']['10']['hit_rate']:.4f} | {dense['at_k']['10']['all_groups_hit_rate']:.4f} | {dense['at_k']['10']['evidence_group_recall_micro']:.4f} |"
    )
    for config, metrics in report["aggregate"]["overall"].items():
        at_10 = metrics["at_k"]["10"]
        lines.append(
            f"| {config} | {metrics['mrr']:.4f} | {at_10['hit_rate']:.4f} | {at_10['all_groups_hit_rate']:.4f} | {at_10['evidence_group_recall_micro']:.4f} |"
        )
    lines.extend(["", "## Promotion gates", ""])
    for name, passed in report["promotion_audit"]["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")
    lines.extend(
        [
            "",
            "The selected configuration remains a development diagnostic unless every promotion gate passes. No Router, generation, training, or frozen blind evaluation was run.",
            "",
            "## Artifacts",
            "",
            f"- results: `{report['artifacts']['results_path']}`",
            f"- results SHA-256: `{report['artifacts']['results_sha256']}`",
            f"- manifest: `{report['artifacts']['manifest_path']}`",
            f"- manifest SHA-256: `{report['artifacts']['manifest_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def build_and_freeze(
    root: Path,
    dev_path: Path,
    retrieval_results_path: Path,
    retrieval_manifest_path: Path,
    retrieval_report_path: Path,
) -> dict[str, Any]:
    input_hashes = {
        "dev_set": _verify_hash(dev_path),
        "retrieval_results": _verify_hash(retrieval_results_path),
        "retrieval_manifest": _verify_hash(retrieval_manifest_path),
        "retrieval_report": _verify_hash(retrieval_report_path),
    }
    retrieval_manifest = json.loads(
        retrieval_manifest_path.read_text(encoding="utf-8")
    )
    if retrieval_manifest["results"]["sha256"] != input_hashes["retrieval_results"]:
        raise RuntimeError("Retrieval result hash differs from its manifest")
    baseline_report = json.loads(retrieval_report_path.read_text(encoding="utf-8"))
    dev_rows = read_jsonl(dev_path)
    retrieval_rows = read_jsonl(retrieval_results_path)
    hybrid_rows = evaluate_grid(dev_rows, retrieval_rows)
    audit = audit_results(dev_rows, retrieval_rows, hybrid_rows)
    if not audit["gate_pass"]:
        failed = [name for name, passed in audit["gates"].items() if not passed]
        raise RuntimeError(f"Hybrid evaluation integrity gates failed: {failed}")
    aggregate = aggregate_grid(hybrid_rows)
    best_config = choose_best_config(aggregate)
    promotion = promotion_audit(aggregate, baseline_report, best_config)

    retrieval_dir = root / "data/v3/retrieval"
    reports_dir = root / "reports/v3"
    result_bytes = _serialize_jsonl(hybrid_rows, lambda row: row["query_ordinal"])
    result_sha = _sha256_bytes(result_bytes)
    result_path = retrieval_dir / f"hybrid_grid_results_{result_sha}.jsonl"
    write_immutable(result_path, result_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "fusion": {
            "candidate_pool": "union_of_bm25_and_dense_top_20",
            "normalization": "per_query_per_system_minmax",
            "missing_system_score": 0.0,
            "tie_break": "chunk_id_ascending",
            "dense_weights": list(DENSE_WEIGHTS),
        },
        "inputs": {
            "dev_set": {"path": _relative(root, dev_path), "sha256": input_hashes["dev_set"]},
            "retrieval_results": {
                "path": _relative(root, retrieval_results_path),
                "sha256": input_hashes["retrieval_results"],
            },
            "retrieval_manifest": {
                "path": _relative(root, retrieval_manifest_path),
                "sha256": input_hashes["retrieval_manifest"],
            },
            "retrieval_report": {
                "path": _relative(root, retrieval_report_path),
                "sha256": input_hashes["retrieval_report"],
            },
        },
        "results": {
            "path": _relative(root, result_path),
            "sha256": result_sha,
            "row_count": len(hybrid_rows),
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = retrieval_dir / f"hybrid_grid_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": {
            "experiment_integrity": "GO",
            "hybrid_promotion": "GO" if promotion["promotion_pass"] else "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "baseline": baseline_report["aggregate"]["systems"],
        "aggregate": aggregate,
        "promotion_audit": promotion,
        "audit": audit,
        "artifacts": {
            "results_path": _relative(root, result_path),
            "results_sha256": result_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "source_or_query_router",
            "generation_quality",
            "answerability_classification",
            "training",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"hybrid_grid_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"hybrid_grid_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "results_path": str(result_path),
        "results_sha256": result_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
        "best_config": best_config,
        "promotion_gates": promotion["gates"],
        "aggregate": aggregate["overall"],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Evaluate a fixed v3 BM25/dense fusion grid")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--retrieval-results", type=Path, default=root / DEFAULT_RETRIEVAL_RESULTS
    )
    parser.add_argument(
        "--retrieval-manifest", type=Path, default=root / DEFAULT_RETRIEVAL_MANIFEST
    )
    parser.add_argument(
        "--retrieval-report", type=Path, default=root / DEFAULT_RETRIEVAL_REPORT
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.retrieval_results.resolve(),
        args.retrieval_manifest.resolve(),
        args.retrieval_report.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
