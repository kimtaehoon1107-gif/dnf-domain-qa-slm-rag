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
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.rerank_evidence import select_reranked_evidence


EVALUATOR_VERSION = "evidence-reranker-ab-v3.1.0"
RESULT_SCHEMA_VERSION = "evidence-reranker-ab-result-v3.1"
MANIFEST_SCHEMA_VERSION = "evidence-reranker-ab-manifest-v3.1"
REPORT_SCHEMA_VERSION = "evidence-reranker-ab-report-v3.1"
BASELINE_ARM = "hybrid_token_selector"
TOP_3_ARM = "bge_reranker_top_3"
TOP_8_ARM = "bge_reranker_top_8"
ADAPTIVE_ARM = "bge_reranker_adaptive_3_or_8"

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_BASELINE_RESULTS = Path(
    "data/v3/evidence/"
    "evidence_selector_pilot_results_c5f0f49ae0e519a8533d7672ba72208a73169c14263a3d77e70768ff6bef31e2.jsonl"
)
DEFAULT_BASELINE_MANIFEST = Path(
    "data/v3/evidence/"
    "evidence_selector_pilot_manifest_268a6e48243f6a21a5f36706692186af1a3081799d5b6f72de98948fe3fda16b.json"
)
DEFAULT_RERANKER_SCORES = Path(
    "data/v3/evidence/"
    "evidence_reranker_scores_ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl"
)
DEFAULT_RERANKER_MANIFEST = Path(
    "data/v3/evidence/"
    "evidence_reranker_manifest_ad6b3f074d8f6edf848c0129d0ea3d8de1c9438aa3de98dde0bfac0fb7a2f26c.json"
)
DEFAULT_LATENCY_REPORT = Path(
    "reports/v3/"
    "evidence_reranker_latency_823dcb4d60ad4af02343389ad1610a6d27ad9a9a8c80eb644121df839e7a8547.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_SELECTOR_SOURCE = Path("src/v3/rerank_evidence.py")
DEFAULT_EVALUATOR_SOURCE = Path("src/v3/evaluate_evidence_reranker.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _fixed_top_k(
    candidates: list[dict[str, Any]], k: int
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda row: (
            -float(row["reranker_score"]),
            int(row["retrieval_rank"]),
            row["chunk_id"],
        ),
    )[:k]


def _selected_metrics(
    selected_ids: set[str], groups: list[dict[str, Any]]
) -> dict[str, Any]:
    group_hits = [
        bool(selected_ids & set(group["acceptable_chunk_ids"])) for group in groups
    ]
    acceptable_ids = {
        chunk_id for group in groups for chunk_id in group["acceptable_chunk_ids"]
    }
    return {
        "selected_evidence_group_hits": group_hits,
        "all_required_evidence_selected": all(group_hits) if groups else None,
        "annotated_selected_chunk_count": len(selected_ids & acceptable_ids),
    }


def evaluate_rows(
    dev_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    reranker_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_by_id = {row["dev_id"]: row for row in baseline_rows}
    reranker_by_id = {row["dev_id"]: row for row in reranker_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    dev_ids = {row["dev_id"] for row in dev_rows}
    if set(baseline_by_id) != dev_ids or set(reranker_by_id) != dev_ids:
        raise RuntimeError("Selector inputs differ from dev IDs")
    if len(chunks_by_id) != len(chunks):
        raise RuntimeError("Duplicate ChunkV3 chunk_id")

    output = []
    for ordinal, dev in enumerate(dev_rows):
        baseline = baseline_by_id[dev["dev_id"]]
        reranker = reranker_by_id[dev["dev_id"]]
        if baseline["predicted_answerability"] != reranker["predicted_answerability"]:
            raise RuntimeError("Answerability prediction differs between A/B inputs")
        candidates = reranker["candidates"]
        if reranker["predicted_answerability"] == "false":
            arm_selected: dict[str, list[dict[str, Any]]] = {
                BASELINE_ARM: [],
                TOP_3_ARM: [],
                TOP_8_ARM: [],
                ADAPTIVE_ARM: [],
            }
        else:
            arm_selected = {
                BASELINE_ARM: baseline["selected_evidence"],
                TOP_3_ARM: _fixed_top_k(candidates, 3),
                TOP_8_ARM: _fixed_top_k(candidates, 8),
                ADAPTIVE_ARM: select_reranked_evidence(
                    dev["question"], candidates, chunks_by_id
                ),
            }
        arms = {}
        for arm_name, selected in arm_selected.items():
            selected_ids = {row["chunk_id"] for row in selected}
            arms[arm_name] = {
                "selected_chunk_ids": [row["chunk_id"] for row in selected],
                "selected_count": len(selected),
                **_selected_metrics(selected_ids, dev["evidence_groups"]),
            }
            if arm_name == ADAPTIVE_ARM and selected:
                arms[arm_name]["selection_reason"] = selected[0]["selection_reason"]
                arms[arm_name]["selection_depth"] = selected[0]["selection_depth"]
        output.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "query_ordinal": ordinal,
                "dev_id": dev["dev_id"],
                "question": dev["question"],
                "query_kind": dev["query_kind"],
                "gold_answerability": dev["answerability"],
                "predicted_answerability": reranker["predicted_answerability"],
                "required_evidence_group_count": len(dev["evidence_groups"]),
                "arms": arms,
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return output


def aggregate_arm(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    answerable = [row for row in rows if row["gold_answerability"] != "false"]
    selected_total = sum(row["arms"][arm]["selected_count"] for row in answerable)
    annotated_total = sum(
        row["arms"][arm]["annotated_selected_chunk_count"] for row in answerable
    )
    required_total = sum(row["required_evidence_group_count"] for row in answerable)
    group_hits = sum(
        sum(row["arms"][arm]["selected_evidence_group_hits"]) for row in answerable
    )
    precision = annotated_total / selected_total
    return {
        "evaluated_answerable_count": len(answerable),
        "all_groups_hit_rate": round(
            sum(row["arms"][arm]["all_required_evidence_selected"] for row in answerable)
            / len(answerable),
            6,
        ),
        "evidence_group_recall_micro": round(group_hits / required_total, 6),
        "annotated_evidence_precision": round(precision, 6),
        "annotated_noise_rate": round(1.0 - precision, 6),
        "average_selected_count": round(selected_total / len(answerable), 6),
        "max_selected_count": max(row["arms"][arm]["selected_count"] for row in answerable),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {
        arm: aggregate_arm(rows, arm)
        for arm in (BASELINE_ARM, TOP_3_ARM, TOP_8_ARM, ADAPTIVE_ARM)
    }
    answerable = [row for row in rows if row["gold_answerability"] != "false"]
    reason_counts: dict[str, int] = {}
    for row in answerable:
        reason = row["arms"][ADAPTIVE_ARM]["selection_reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    baseline = arms[BASELINE_ARM]
    adaptive = arms[ADAPTIVE_ARM]
    return {
        "row_count": len(rows),
        "arms": arms,
        "adaptive_selection_reason_counts": dict(sorted(reason_counts.items())),
        "adaptive_vs_baseline": {
            "all_groups_hit_delta": round(
                adaptive["all_groups_hit_rate"] - baseline["all_groups_hit_rate"], 6
            ),
            "group_recall_micro_delta": round(
                adaptive["evidence_group_recall_micro"]
                - baseline["evidence_group_recall_micro"],
                6,
            ),
            "annotated_precision_delta": round(
                adaptive["annotated_evidence_precision"]
                - baseline["annotated_evidence_precision"],
                6,
            ),
            "average_selected_reduction": round(
                1.0
                - adaptive["average_selected_count"]
                / baseline["average_selected_count"],
                6,
            ),
        },
    }


def audit(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    baseline = metrics["arms"][BASELINE_ARM]
    adaptive = metrics["arms"][ADAPTIVE_ARM]
    delta = metrics["adaptive_vs_baseline"]
    integrity_gates = {
        "rows_63": len(rows) == 63,
        "query_ordinals_contiguous": [row["query_ordinal"] for row in rows]
        == list(range(63)),
        "false_evidence_exposure_0": not any(
            any(arm["selected_count"] for arm in row["arms"].values())
            for row in rows
            if row["predicted_answerability"] == "false"
        ),
        "training_leak_0": not any(row["training_allowed"] for row in rows),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in rows
        ),
    }
    promotion_gates = {
        "all_groups_recall_no_regression": adaptive["all_groups_hit_rate"]
        == baseline["all_groups_hit_rate"],
        "group_recall_micro_no_regression": adaptive[
            "evidence_group_recall_micro"
        ]
        == baseline["evidence_group_recall_micro"],
        "annotated_precision_delta_at_least_0_1": delta[
            "annotated_precision_delta"
        ]
        >= 0.1,
        "average_selected_reduction_at_least_0_4": delta[
            "average_selected_reduction"
        ]
        >= 0.4,
    }
    production_gates = {
        "annotated_evidence_precision_at_least_0_5": adaptive[
            "annotated_evidence_precision"
        ]
        >= 0.5,
        "semantic_contradiction_measured": False,
        "independent_holdout_measured": False,
        "annotation_human_review_complete": False,
    }
    return {
        "integrity_gates": integrity_gates,
        "integrity_pass": all(integrity_gates.values()),
        "promotion_gates": promotion_gates,
        "promotion_pass": all(promotion_gates.values()),
        "production_gates": production_gates,
        "production_pass": all(production_gates.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    arms = metrics["arms"]
    baseline = arms[BASELINE_ARM]
    adaptive = arms[ADAPTIVE_ARM]
    latency = report["latency"]
    return f"""# DNF RAG v3 Evidence Reranker A/B

## Decision

- A/B integrity: **{report['decision']['ab_integrity']}**
- Adaptive reranker development candidate: **{report['decision']['adaptive_reranker_development']}**
- Production Evidence Selector: **{report['decision']['production_evidence_selector']}**
- Generator entry: **{report['decision']['generator_entry']}**
- Final benchmark: **{report['decision']['final_benchmark']}**

## A/B

| arm | all-groups hit | group recall micro | annotated precision | noise | avg selected |
|---|---:|---:|---:|---:|---:|
| baseline | {baseline['all_groups_hit_rate']} | {baseline['evidence_group_recall_micro']} | {baseline['annotated_evidence_precision']} | {baseline['annotated_noise_rate']} | {baseline['average_selected_count']} |
| reranker top-3 | {arms[TOP_3_ARM]['all_groups_hit_rate']} | {arms[TOP_3_ARM]['evidence_group_recall_micro']} | {arms[TOP_3_ARM]['annotated_evidence_precision']} | {arms[TOP_3_ARM]['annotated_noise_rate']} | {arms[TOP_3_ARM]['average_selected_count']} |
| reranker top-8 | {arms[TOP_8_ARM]['all_groups_hit_rate']} | {arms[TOP_8_ARM]['evidence_group_recall_micro']} | {arms[TOP_8_ARM]['annotated_evidence_precision']} | {arms[TOP_8_ARM]['annotated_noise_rate']} | {arms[TOP_8_ARM]['average_selected_count']} |
| adaptive 3/8 | {adaptive['all_groups_hit_rate']} | {adaptive['evidence_group_recall_micro']} | {adaptive['annotated_evidence_precision']} | {adaptive['annotated_noise_rate']} | {adaptive['average_selected_count']} |

Adaptive selection uses top-8 only for explicit multi-evidence markers or a reranker top score below 0.1; otherwise it uses top-3. This rule was selected on the development set and has no independent holdout evidence.

## Observed scoring cost

- pairs: {latency['pair_count']}
- inference seconds: {latency['inference_seconds']}
- pairs/second: {latency['pairs_per_second']}
- peak CUDA bytes: {latency['peak_cuda_memory_bytes']}

This is batched evaluation throughput, not online p50/p95 request latency.

## Limits

The BGE model is a relevance reranker, not an entailment or contradiction verifier. The adaptive arm preserves development recall and improves sparse-annotation precision, but its precision remains below the production gate.

## Artifacts

- results: `{report['artifacts']['results_path']}`
- manifest: `{report['artifacts']['manifest_path']}`
"""


def build_and_freeze(
    root: Path,
    dev_path: Path,
    baseline_results_path: Path,
    baseline_manifest_path: Path,
    reranker_scores_path: Path,
    reranker_manifest_path: Path,
    latency_report_path: Path,
    chunks_path: Path,
    selector_source_path: Path,
    evaluator_source_path: Path,
) -> dict[str, Any]:
    input_paths = {
        "dev_set": dev_path,
        "baseline_results": baseline_results_path,
        "baseline_manifest": baseline_manifest_path,
        "reranker_scores": reranker_scores_path,
        "reranker_manifest": reranker_manifest_path,
        "latency_report": latency_report_path,
        "chunks": chunks_path,
        "selector_source": selector_source_path,
        "evaluator_source": evaluator_source_path,
    }
    hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    rows = evaluate_rows(
        read_jsonl(dev_path),
        read_jsonl(baseline_results_path),
        read_jsonl(reranker_scores_path),
        read_jsonl(chunks_path),
    )
    metrics = aggregate(rows)
    gates = audit(rows, metrics)
    if not gates["integrity_pass"] or not gates["promotion_pass"]:
        raise RuntimeError("Evidence reranker A/B integrity or promotion gates failed")
    latency = json.loads(latency_report_path.read_text(encoding="utf-8"))

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    results_bytes = _serialize_jsonl(rows, lambda row: row["query_ordinal"])
    results_sha = _sha256_bytes(results_bytes)
    results_path = evidence_dir / f"evidence_reranker_ab_results_{results_sha}.jsonl"
    write_immutable(results_path, results_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": hashes[name]}
            for name, path in input_paths.items()
        },
        "arms": [BASELINE_ARM, TOP_3_ARM, TOP_8_ARM, ADAPTIVE_ARM],
        "adaptive_contract": {
            "default_depth": 3,
            "fallback_depth": 8,
            "low_confidence_threshold": 0.1,
            "multi_evidence_markers": ["각각", "비교", "함께"],
            "gold_ids_available_to_selector": False,
        },
        "results": {
            "path": _relative(root, results_path),
            "sha256": results_sha,
            "row_count": len(rows),
        },
        "metrics": metrics,
        "audit": gates,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"evidence_reranker_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": {
            "ab_integrity": "GO",
            "adaptive_reranker_development": "GO",
            "production_evidence_selector": "NO-GO",
            "generator_entry": "NO-GO",
            "annotation_human_review": "PENDING",
            "final_benchmark": "NO-GO",
        },
        "metrics": metrics,
        "audit": gates,
        "latency": latency,
        "artifacts": {
            "results_path": _relative(root, results_path),
            "results_sha256": results_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "independent_reranker_holdout",
            "entailment",
            "contradiction_rate",
            "online_latency_p50_p95",
            "generation",
            "verifier",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"evidence_reranker_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"evidence_reranker_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "results_path": str(results_path),
        "results_sha256": results_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
        "metrics": metrics,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Evaluate v3 BGE evidence reranker A/B")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--baseline-results", type=Path, default=root / DEFAULT_BASELINE_RESULTS
    )
    parser.add_argument(
        "--baseline-manifest", type=Path, default=root / DEFAULT_BASELINE_MANIFEST
    )
    parser.add_argument(
        "--reranker-scores", type=Path, default=root / DEFAULT_RERANKER_SCORES
    )
    parser.add_argument(
        "--reranker-manifest", type=Path, default=root / DEFAULT_RERANKER_MANIFEST
    )
    parser.add_argument(
        "--latency-report", type=Path, default=root / DEFAULT_LATENCY_REPORT
    )
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--selector-source", type=Path, default=root / DEFAULT_SELECTOR_SOURCE)
    parser.add_argument(
        "--evaluator-source", type=Path, default=root / DEFAULT_EVALUATOR_SOURCE
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.baseline_results.resolve(),
        args.baseline_manifest.resolve(),
        args.reranker_scores.resolve(),
        args.reranker_manifest.resolve(),
        args.latency_report.resolve(),
        args.chunks.resolve(),
        args.selector_source.resolve(),
        args.evaluator_source.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
