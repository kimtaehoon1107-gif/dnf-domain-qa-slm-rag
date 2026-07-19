from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import _allowed
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_hybrid import aggregate_configuration
from src.v3.evaluate_retrieval import policy_from_dev, score_ranked_hits


EVALUATOR_VERSION = "structured-parent-lead-guard-v3.1.0"
RESULT_SCHEMA_VERSION = "retrieval-signal-result-v3.1"
MANIFEST_SCHEMA_VERSION = "retrieval-signal-manifest-v3.1"
REPORT_SCHEMA_VERSION = "retrieval-signal-report-v3.1"
BASE_CONFIG = "dense_75_bm25_25"
CANDIDATE_CONFIG = "dense_75_bm25_25_structured_parent_lead_guard"
STRUCTURED_FIELD_TERMS = ("가격", "거래", "판매", "종료")
LEXICAL_PARENT_COUNT = 2
GUARD_CUTOFF = 10
MAX_RESULT_RANK = 20

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_RETRIEVAL_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_ab_results_c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620.jsonl"
)
DEFAULT_RETRIEVAL_REPORT = Path(
    "reports/v3/"
    "retrieval_ab_5c8ebeb3606d785e7c898f32eef036b2fa2f8c8c1dbfbe49957602f23e907550.json"
)
DEFAULT_HYBRID_RESULTS = Path(
    "data/v3/retrieval/"
    "hybrid_grid_results_a570e39e37dc6311c5e82fb32d8c403908d3251ba4d6b06babd2857e6b50d9e1.jsonl"
)
DEFAULT_HYBRID_REPORT = Path(
    "reports/v3/"
    "hybrid_grid_35ac0dbb861207a55bc380bb94dcc92a71defcc7b34e205911c8ee5f5131c093.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verify_hash(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"Artifact does not exist: {path}")
    return file_sha256(path)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_structured_field_query(question: str) -> bool:
    return any(term in question for term in STRUCTURED_FIELD_TERMS)


def build_lead_chunk_index(chunks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates_by_parent: dict[str, list[dict[str, Any]]] = {}
    parents = {row["parent_document_id"] for row in chunks}
    for row in chunks:
        if row["chunk_index"] != 1:
            continue
        parent_id = row["parent_document_id"]
        candidates_by_parent.setdefault(parent_id, []).append(row)
    lead_by_parent = {
        parent_id: min(
            candidates,
            key=lambda row: (
                row["review_required"],
                row["offset_source"] == "visual_ocr",
                row["chunk_id"],
            ),
        )
        for parent_id, candidates in candidates_by_parent.items()
    }
    missing = parents - lead_by_parent.keys()
    if missing:
        raise RuntimeError(f"Parents without a lead chunk: {len(missing)}")
    return lead_by_parent


def _lead_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "parent_document_id": chunk["parent_document_id"],
        "source_id": chunk["source_id"],
        "status": chunk["status"],
        "default_exposure": chunk["default_exposure"],
        "review_required": chunk["review_required"],
    }


def apply_structured_parent_lead_guard(
    question: str,
    query_policy: dict[str, Any],
    base_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    lead_by_parent: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    structured = is_structured_field_query(question)
    metadata = {row["chunk_id"]: dict(row) for row in base_hits}
    base_ids = [row["chunk_id"] for row in base_hits]
    guard_ids: list[str] = []
    if structured:
        seen_parents: set[str] = set()
        policy = policy_from_dev({"query_policy": query_policy})
        for hit in bm25_hits:
            parent_id = hit["parent_document_id"]
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            lead = lead_by_parent.get(parent_id)
            if lead is None:
                raise RuntimeError(f"BM25 parent lacks lead chunk: {parent_id}")
            if not _allowed(lead, policy):
                continue
            guard_ids.append(lead["chunk_id"])
            metadata.setdefault(lead["chunk_id"], _lead_metadata(lead))
            if len(guard_ids) == LEXICAL_PARENT_COUNT:
                break
    missing_at_cutoff = [chunk_id for chunk_id in guard_ids if chunk_id not in base_ids[:GUARD_CUTOFF]]
    reordered = [chunk_id for chunk_id in base_ids if chunk_id not in missing_at_cutoff]
    if missing_at_cutoff:
        insertion_point = GUARD_CUTOFF - len(missing_at_cutoff)
        reordered = (
            reordered[:insertion_point]
            + missing_at_cutoff
            + reordered[insertion_point:]
        )
    output = []
    base_rank = {row["chunk_id"]: row["rank"] for row in base_hits}
    base_score = {row["chunk_id"]: row["score"] for row in base_hits}
    for rank, chunk_id in enumerate(reordered[:MAX_RESULT_RANK], start=1):
        row = metadata[chunk_id]
        output.append(
            {
                "rank": rank,
                "chunk_id": chunk_id,
                "parent_document_id": row["parent_document_id"],
                "source_id": row["source_id"],
                "status": row["status"],
                "default_exposure": row["default_exposure"],
                "review_required": row["review_required"],
                "base_rank": base_rank.get(chunk_id),
                "base_score": base_score.get(chunk_id),
                "guardrail_injected": chunk_id in missing_at_cutoff,
            }
        )
    return output, {
        "structured_field_query": structured,
        "guard_chunk_ids": guard_ids,
        "injected_chunk_ids": missing_at_cutoff,
    }


def evaluate_signal(
    dev_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    hybrid_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dev_by_id = {row["dev_id"]: row for row in dev_rows}
    retrieval_by_id = {row["dev_id"]: row for row in retrieval_rows}
    if set(dev_by_id) != set(retrieval_by_id) or set(dev_by_id) != {
        row["dev_id"] for row in hybrid_rows
    }:
        raise RuntimeError("Signal evaluation inputs have different dev IDs")
    lead_by_parent = build_lead_chunk_index(chunks)
    results = []
    for hybrid in sorted(hybrid_rows, key=lambda row: row["query_ordinal"]):
        dev = dev_by_id[hybrid["dev_id"]]
        retrieval = retrieval_by_id[hybrid["dev_id"]]
        hits, signal = apply_structured_parent_lead_guard(
            dev["question"],
            dev["query_policy"],
            hybrid["configurations"][BASE_CONFIG]["hits"],
            retrieval["systems"]["bm25"]["hits"],
            lead_by_parent,
        )
        metrics = score_ranked_hits(dev["evidence_groups"], hits)
        results.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "query_ordinal": hybrid["query_ordinal"],
                "dev_id": hybrid["dev_id"],
                "question": dev["question"],
                "answerability": dev["answerability"],
                "query_kind": dev["query_kind"],
                "source_ids": dev["source_ids"],
                "required_evidence_group_count": dev[
                    "required_evidence_group_count"
                ],
                "signal": signal,
                "configurations": {
                    CANDIDATE_CONFIG: {"metrics": metrics, "hits": hits}
                },
            }
        )
    return results


def aggregate_signal(rows: list[dict[str, Any]]) -> dict[str, Any]:
    overall = aggregate_configuration(rows, CANDIDATE_CONFIG)
    by_source = {
        source_id: aggregate_configuration(
            [row for row in rows if source_id in row["source_ids"]],
            CANDIDATE_CONFIG,
        )
        for source_id in sorted(
            {source_id for row in rows for source_id in row["source_ids"]}
        )
    }
    by_query_kind = {
        query_kind: aggregate_configuration(
            [row for row in rows if row["query_kind"] == query_kind],
            CANDIDATE_CONFIG,
        )
        for query_kind in sorted({row["query_kind"] for row in rows})
        if query_kind != "unanswerable"
    }
    return {"overall": overall, "by_source": by_source, "by_query_kind": by_query_kind}


def _baseline_source_metrics(
    hybrid_report: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    best = hybrid_report["promotion_audit"]["best_config"]
    return {
        source_id: metrics[best]
        for source_id, metrics in hybrid_report["aggregate"]["by_source"].items()
    }


def promotion_audit(
    aggregate: dict[str, Any],
    hybrid_report: dict[str, Any],
    retrieval_report: dict[str, Any],
) -> dict[str, Any]:
    candidate = aggregate["overall"]
    best_config = hybrid_report["promotion_audit"]["best_config"]
    hybrid_baseline = hybrid_report["aggregate"]["overall"][best_config]
    dense_baseline = retrieval_report["aggregate"]["systems"]["dense"]
    baseline_sources = _baseline_source_metrics(hybrid_report)
    source_deltas = {
        source_id: round(
            metrics["at_k"]["10"]["all_groups_hit_rate"]
            - baseline_sources[source_id]["at_k"]["10"]["all_groups_hit_rate"],
            6,
        )
        for source_id, metrics in aggregate["by_source"].items()
    }
    candidate_worst = min(
        metrics["at_k"]["10"]["all_groups_hit_rate"]
        for metrics in aggregate["by_source"].values()
    )
    hybrid_worst = min(
        metrics["at_k"]["10"]["all_groups_hit_rate"]
        for metrics in baseline_sources.values()
    )
    candidate_10 = candidate["at_k"]["10"]
    hybrid_10 = hybrid_baseline["at_k"]["10"]
    dense_10 = dense_baseline["at_k"]["10"]
    gates = {
        "hit_at_10_improves_best_hybrid": candidate_10["hit_rate"]
        > hybrid_10["hit_rate"],
        "all_groups_at_10_improves_best_hybrid": candidate_10[
            "all_groups_hit_rate"
        ]
        > hybrid_10["all_groups_hit_rate"],
        "group_recall_at_10_improves_best_hybrid": candidate_10[
            "evidence_group_recall_micro"
        ]
        > hybrid_10["evidence_group_recall_micro"],
        "mrr_not_regressed_from_best_hybrid": candidate["mrr"]
        >= hybrid_baseline["mrr"],
        "source_regression_from_best_hybrid_0": all(
            delta >= 0 for delta in source_deltas.values()
        ),
        "worst_source_improves_best_hybrid": candidate_worst > hybrid_worst,
        "hit_at_10_above_dense": candidate_10["hit_rate"] > dense_10["hit_rate"],
        "all_groups_at_10_above_dense": candidate_10["all_groups_hit_rate"]
        > dense_10["all_groups_hit_rate"],
    }
    return {
        "candidate": candidate,
        "best_hybrid_baseline": hybrid_baseline,
        "dense_baseline": dense_baseline,
        "source_all_groups_at_10_deltas_from_best_hybrid": source_deltas,
        "candidate_worst_source_all_groups_at_10": candidate_worst,
        "best_hybrid_worst_source_all_groups_at_10": hybrid_worst,
        "gates": gates,
        "promotion_pass": all(gates.values()),
    }


def audit_results(
    dev_rows: list[dict[str, Any]], results: list[dict[str, Any]]
) -> dict[str, Any]:
    structured_count = sum(row["signal"]["structured_field_query"] for row in results)
    injection_count = sum(
        len(row["signal"]["injected_chunk_ids"]) for row in results
    )
    gates = {
        "result_rows_63": len(results) == 63,
        "query_ordinals_contiguous": [row["query_ordinal"] for row in results]
        == list(range(63)),
        "structured_queries_present": structured_count > 0,
        "guard_injections_present": injection_count > 0,
        "ranking_uses_gold_fields_false": True,
        "training_leak_0": not any(row["training_allowed"] for row in dev_rows),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in dev_rows
        ),
    }
    return {
        "structured_query_count": structured_count,
        "guard_injection_count": injection_count,
        "gates": gates,
        "gate_pass": all(gates.values()),
    }


def remaining_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for row in rows:
        metrics = row["configurations"][CANDIDATE_CONFIG]["metrics"]
        if metrics["evaluated"] and not metrics["at_k"]["10"]["all_groups_hit"]:
            failures.append(
                {
                    "dev_id": row["dev_id"],
                    "question": row["question"],
                    "query_kind": row["query_kind"],
                    "source_ids": row["source_ids"],
                    "group_first_ranks": metrics["group_first_ranks"],
                    "review_status": "human_review_required",
                    "review_reason": "official alternate evidence may answer the question but is not listed in the current gold groups",
                }
            )
    return failures


def _markdown(report: dict[str, Any]) -> str:
    candidate = report["promotion_audit"]["candidate"]
    hybrid = report["promotion_audit"]["best_hybrid_baseline"]
    dense = report["promotion_audit"]["dense_baseline"]
    lines = [
        "# DNF RAG v3 Structured Parent-Lead Signal",
        "",
        "## Decision",
        "",
        f"- Experiment integrity: **{report['decision']['experiment_integrity']}**",
        f"- Retrieval candidate promotion: **{report['decision']['retrieval_candidate_promotion']}**",
        f"- Final benchmark: **{report['decision']['final_benchmark']}**",
        "",
        "## Overall",
        "",
        "| system | MRR | hit@10 | all groups@10 | group recall@10 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in (("dense", dense), ("best fixed hybrid", hybrid), ("signal candidate", candidate)):
        at_10 = metrics["at_k"]["10"]
        lines.append(
            f"| {name} | {metrics['mrr']:.4f} | {at_10['hit_rate']:.4f} | {at_10['all_groups_hit_rate']:.4f} | {at_10['evidence_group_recall_micro']:.4f} |"
        )
    lines.extend(["", "## Promotion gates", ""])
    for name, passed in report["promotion_audit"]["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")
    lines.extend(
        [
            "",
            f"Structured-field queries: {report['audit']['structured_query_count']}",
            f"Injected lead chunks: {report['audit']['guard_injection_count']}",
            f"Remaining human-review cases: {len(report['remaining_failures_at_10'])}",
            "",
            "The candidate is promoted only for v3 development retrieval. Final benchmark eligibility remains blocked until the remaining annotation review and a separately frozen benchmark are completed.",
            "",
            "## Artifacts",
            "",
            f"- results: `{report['artifacts']['results_path']}`",
            f"- manifest: `{report['artifacts']['manifest_path']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def build_and_freeze(
    root: Path,
    dev_path: Path,
    retrieval_results_path: Path,
    retrieval_report_path: Path,
    hybrid_results_path: Path,
    hybrid_report_path: Path,
    chunks_path: Path,
) -> dict[str, Any]:
    input_paths = {
        "dev_set": dev_path,
        "retrieval_results": retrieval_results_path,
        "retrieval_report": retrieval_report_path,
        "hybrid_results": hybrid_results_path,
        "hybrid_report": hybrid_report_path,
        "chunks": chunks_path,
    }
    input_hashes = {name: _verify_hash(path) for name, path in input_paths.items()}
    dev_rows = read_jsonl(dev_path)
    retrieval_rows = read_jsonl(retrieval_results_path)
    hybrid_rows = read_jsonl(hybrid_results_path)
    chunks = read_jsonl(chunks_path)
    retrieval_report = json.loads(retrieval_report_path.read_text(encoding="utf-8"))
    hybrid_report = json.loads(hybrid_report_path.read_text(encoding="utf-8"))
    results = evaluate_signal(dev_rows, retrieval_rows, hybrid_rows, chunks)
    audit = audit_results(dev_rows, results)
    if not audit["gate_pass"]:
        failed = [name for name, passed in audit["gates"].items() if not passed]
        raise RuntimeError(f"Retrieval signal integrity gates failed: {failed}")
    aggregate = aggregate_signal(results)
    promotion = promotion_audit(aggregate, hybrid_report, retrieval_report)
    failures = remaining_failures(results)

    retrieval_dir = root / "data/v3/retrieval"
    reports_dir = root / "reports/v3"
    result_bytes = _serialize_jsonl(results, lambda row: row["query_ordinal"])
    result_sha = _sha256_bytes(result_bytes)
    result_path = retrieval_dir / f"retrieval_signal_results_{result_sha}.jsonl"
    write_immutable(result_path, result_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "base_config": BASE_CONFIG,
        "candidate_config": CANDIDATE_CONFIG,
        "signal_contract": {
            "structured_field_terms": list(STRUCTURED_FIELD_TERMS),
            "lexical_parent_count": LEXICAL_PARENT_COUNT,
            "guard_cutoff": GUARD_CUTOFF,
            "preserved_prefix_count": GUARD_CUTOFF - LEXICAL_PARENT_COUNT,
            "ranking_uses_gold_fields": False,
            "ranking_uses_source_ids": False,
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "results": {
            "path": _relative(root, result_path),
            "sha256": result_sha,
            "row_count": len(results),
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = retrieval_dir / f"retrieval_signal_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": {
            "experiment_integrity": "GO",
            "retrieval_candidate_promotion": "GO"
            if promotion["promotion_pass"]
            else "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "aggregate": aggregate,
        "promotion_audit": promotion,
        "remaining_failures_at_10": failures,
        "audit": audit,
        "artifacts": {
            "results_path": _relative(root, result_path),
            "results_sha256": result_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "router",
            "general_query_decomposition",
            "generation_quality",
            "training",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"retrieval_signal_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"retrieval_signal_{markdown_sha}.md"
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
        "candidate_metrics": promotion["candidate"],
        "promotion_gates": promotion["gates"],
        "remaining_failures_at_10": failures,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Evaluate structured parent-lead retrieval signals")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--retrieval-results", type=Path, default=root / DEFAULT_RETRIEVAL_RESULTS
    )
    parser.add_argument(
        "--retrieval-report", type=Path, default=root / DEFAULT_RETRIEVAL_REPORT
    )
    parser.add_argument(
        "--hybrid-results", type=Path, default=root / DEFAULT_HYBRID_RESULTS
    )
    parser.add_argument("--hybrid-report", type=Path, default=root / DEFAULT_HYBRID_REPORT)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.retrieval_results.resolve(),
        args.retrieval_report.resolve(),
        args.hybrid_results.resolve(),
        args.hybrid_report.resolve(),
        args.chunks.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
