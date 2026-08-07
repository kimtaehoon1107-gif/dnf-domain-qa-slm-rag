from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_retrieval_signals import CANDIDATE_CONFIG
from src.v3.select_evidence import classify_answerability, select_evidence


EVALUATOR_VERSION = "evidence-selector-pilot-v3.1.0"
RESULT_SCHEMA_VERSION = "evidence-selector-pilot-result-v3.1"
MANIFEST_SCHEMA_VERSION = "evidence-selector-pilot-manifest-v3.1"
REPORT_SCHEMA_VERSION = "evidence-selector-pilot-report-v3.1"

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
DEFAULT_ANNOTATION_MANIFEST = Path(
    "data/v3/evaluation/"
    "retrieval_annotation_review_manifest_a73c22708fa24fd4311cde62675d59137358d185cdca1eb223d284d2e7e0d258.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_SELECTOR_SOURCE = Path("src/v3/select_evidence.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def evaluate_rows(
    dev_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    retrieval_by_id = {row["dev_id"]: row for row in retrieval_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    if len(retrieval_by_id) != len(retrieval_rows):
        raise RuntimeError("Duplicate retrieval dev_id")
    if len(chunks_by_id) != len(chunks):
        raise RuntimeError("Duplicate ChunkV3 chunk_id")
    if set(retrieval_by_id) != {row["dev_id"] for row in dev_rows}:
        raise RuntimeError("Retrieval results differ from dev IDs")

    output = []
    for ordinal, dev in enumerate(dev_rows):
        retrieval = retrieval_by_id[dev["dev_id"]]
        hits = retrieval["configurations"][CANDIDATE_CONFIG]["hits"]
        decision = classify_answerability(dev["question"])
        selected = (
            []
            if decision["label"] == "false"
            else select_evidence(dev["question"], hits, chunks_by_id)
        )
        selected_ids = {row["chunk_id"] for row in selected}
        groups = dev["evidence_groups"]
        group_hits = [
            bool(selected_ids & set(group["acceptable_chunk_ids"])) for group in groups
        ]
        candidate_ids = {row["chunk_id"] for row in hits[:10]}
        candidate_group_hits = [
            bool(candidate_ids & set(group["acceptable_chunk_ids"])) for group in groups
        ]
        acceptable_ids = {
            chunk_id
            for group in groups
            for chunk_id in group["acceptable_chunk_ids"]
        }
        annotated_hit_count = sum(
            row["chunk_id"] in acceptable_ids for row in selected
        )
        output.append(
            {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "query_ordinal": ordinal,
                "dev_id": dev["dev_id"],
                "question": dev["question"],
                "query_kind": dev["query_kind"],
                "gold_answerability": dev["answerability"],
                "predicted_answerability": decision["label"],
                "answerability_reason": decision["reason"],
                "answerability_exact": decision["label"] == dev["answerability"],
                "candidate_count": len(hits),
                "selected_count": len(selected),
                "selected_evidence": selected,
                "required_evidence_group_count": len(groups),
                "selected_evidence_group_hits": group_hits,
                "candidate_top_10_group_hits": candidate_group_hits,
                "all_required_evidence_selected": all(group_hits) if groups else None,
                "all_required_evidence_in_candidate_top_10": all(candidate_group_hits)
                if groups
                else None,
                "annotated_selected_chunk_count": annotated_hit_count,
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return output


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row["gold_answerability"] != "false"]
    unsupported = [row for row in rows if row["gold_answerability"] == "false"]
    selected_total = sum(row["selected_count"] for row in answerable)
    annotated_total = sum(row["annotated_selected_chunk_count"] for row in answerable)
    required_total = sum(row["required_evidence_group_count"] for row in answerable)
    selected_group_hits = sum(
        sum(row["selected_evidence_group_hits"]) for row in answerable
    )
    candidate_group_hits = sum(
        sum(row["candidate_top_10_group_hits"]) for row in answerable
    )
    precision = annotated_total / selected_total
    predicted_counts = Counter(row["predicted_answerability"] for row in rows)
    reason_counts = Counter(row["answerability_reason"] for row in rows)
    return {
        "row_count": len(rows),
        "answerability": {
            "gold_counts": dict(Counter(row["gold_answerability"] for row in rows)),
            "predicted_counts": dict(predicted_counts),
            "reason_counts": dict(sorted(reason_counts.items())),
            "exact_accuracy": round(
                sum(row["answerability_exact"] for row in rows) / len(rows), 6
            ),
            "unsupported_abstention_rate": round(
                sum(row["predicted_answerability"] == "false" for row in unsupported)
                / len(unsupported),
                6,
            ),
            "answerable_false_rejection_rate": round(
                sum(row["predicted_answerability"] == "false" for row in answerable)
                / len(answerable),
                6,
            ),
            "false_rows_with_selected_evidence": sum(
                bool(row["selected_evidence"]) for row in unsupported
            ),
        },
        "selector": {
            "evaluated_answerable_count": len(answerable),
            "candidate_top_10_all_groups_hit_rate": round(
                sum(row["all_required_evidence_in_candidate_top_10"] for row in answerable)
                / len(answerable),
                6,
            ),
            "selected_all_groups_hit_rate": round(
                sum(row["all_required_evidence_selected"] for row in answerable)
                / len(answerable),
                6,
            ),
            "candidate_top_10_group_recall_micro": round(
                candidate_group_hits / required_total, 6
            ),
            "selected_group_recall_micro": round(
                selected_group_hits / required_total, 6
            ),
            "annotated_evidence_precision": round(precision, 6),
            "annotated_noise_rate": round(1.0 - precision, 6),
            "average_selected_count": round(selected_total / len(answerable), 6),
            "max_selected_count": max(row["selected_count"] for row in answerable),
            "candidate_reduction_from_top_10": round(
                1.0 - selected_total / (10 * len(answerable)), 6
            ),
        },
    }


def audit(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    answerability = metrics["answerability"]
    selector = metrics["selector"]
    integrity_gates = {
        "rows_63": len(rows) == 63,
        "query_ordinals_contiguous": [row["query_ordinal"] for row in rows]
        == list(range(63)),
        "answerability_exact_63": answerability["exact_accuracy"] == 1.0,
        "unsupported_abstention_1": answerability["unsupported_abstention_rate"]
        == 1.0,
        "answerable_false_rejection_0": answerability[
            "answerable_false_rejection_rate"
        ]
        == 0.0,
        "false_evidence_exposure_0": answerability[
            "false_rows_with_selected_evidence"
        ]
        == 0,
        "training_leak_0": not any(row["training_allowed"] for row in rows),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in rows
        ),
    }
    compression_gates = {
        "all_groups_recall_no_regression": selector[
            "selected_all_groups_hit_rate"
        ]
        == selector["candidate_top_10_all_groups_hit_rate"],
        "group_recall_micro_no_regression": selector[
            "selected_group_recall_micro"
        ]
        == selector["candidate_top_10_group_recall_micro"],
        "average_selected_below_10": selector["average_selected_count"] < 10,
        "maximum_selected_at_most_10": selector["max_selected_count"] <= 10,
    }
    production_gates = {
        "annotated_evidence_precision_at_least_0_5": selector[
            "annotated_evidence_precision"
        ]
        >= 0.5,
        "semantic_contradiction_measured": False,
        "independent_answerability_holdout_measured": False,
    }
    return {
        "integrity_gates": integrity_gates,
        "integrity_pass": all(integrity_gates.values()),
        "compression_gates": compression_gates,
        "compression_pass": all(compression_gates.values()),
        "production_gates": production_gates,
        "production_pass": all(production_gates.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    answerability = metrics["answerability"]
    selector = metrics["selector"]
    return f"""# DNF RAG v3 Answerability / Evidence Selector Pilot

## Decision

- Answerability dev baseline: **{report['decision']['answerability_dev_baseline']}**
- Selector compression candidate: **{report['decision']['selector_compression_candidate']}**
- Production evidence selector: **{report['decision']['production_evidence_selector']}**
- Generator entry: **{report['decision']['generator_entry']}**
- Final benchmark: **{report['decision']['final_benchmark']}**

## Answerability

- exact dev accuracy: {answerability['exact_accuracy']}
- unsupported abstention: {answerability['unsupported_abstention_rate']}
- answerable false rejection: {answerability['answerable_false_rejection_rate']}
- false rows with selected evidence: {answerability['false_rows_with_selected_evidence']}

This is a deterministic dev-fit safety baseline, not an independent generalization result. Answerability accuracy is not interpreted without the evidence metrics below.

## Evidence selector

- candidate top-10 all-groups hit: {selector['candidate_top_10_all_groups_hit_rate']}
- selected all-groups hit: {selector['selected_all_groups_hit_rate']}
- candidate top-10 group recall micro: {selector['candidate_top_10_group_recall_micro']}
- selected group recall micro: {selector['selected_group_recall_micro']}
- average selected chunks: {selector['average_selected_count']}
- candidate reduction: {selector['candidate_reduction_from_top_10']}
- annotated evidence precision: {selector['annotated_evidence_precision']}
- annotated noise rate: {selector['annotated_noise_rate']}

The selector preserves the frozen top-10 evidence recall while reducing the candidate set. Its sparse-annotation precision is too low for production or generator promotion, and semantic contradiction has not been measured.

## Artifacts

- results: `{report['artifacts']['results_path']}`
- manifest: `{report['artifacts']['manifest_path']}`
"""


def build_and_freeze(
    root: Path,
    dev_path: Path,
    retrieval_results_path: Path,
    runtime_manifest_path: Path,
    annotation_manifest_path: Path,
    chunks_path: Path,
    selector_source_path: Path,
) -> dict[str, Any]:
    input_paths = {
        "dev_set": dev_path,
        "retrieval_results": retrieval_results_path,
        "runtime_manifest": runtime_manifest_path,
        "annotation_manifest": annotation_manifest_path,
        "chunks": chunks_path,
        "selector_source": selector_source_path,
    }
    hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    rows = evaluate_rows(
        read_jsonl(dev_path), read_jsonl(retrieval_results_path), read_jsonl(chunks_path)
    )
    metrics = aggregate(rows)
    gates = audit(rows, metrics)
    if not gates["integrity_pass"] or not gates["compression_pass"]:
        raise RuntimeError("Evidence selector pilot integrity or compression gates failed")

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    results_bytes = _serialize_jsonl(rows, lambda row: row["query_ordinal"])
    results_sha = _sha256_bytes(results_bytes)
    results_path = evidence_dir / f"evidence_selector_pilot_results_{results_sha}.jsonl"
    write_immutable(results_path, results_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": hashes[name]}
            for name, path in input_paths.items()
        },
        "selector_contract": {
            "candidate_depth": 10,
            "base_selection_limit": 8,
            "hybrid_score_weight": 0.75,
            "query_coverage_weight": 0.25,
            "preserve_structured_parent_leads": True,
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
    manifest_path = evidence_dir / f"evidence_selector_pilot_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": {
            "answerability_dev_baseline": "GO",
            "selector_compression_candidate": "GO",
            "production_evidence_selector": "NO-GO",
            "generator_entry": "NO-GO",
            "annotation_human_review": "PENDING",
            "final_benchmark": "NO-GO",
        },
        "metrics": metrics,
        "audit": gates,
        "artifacts": {
            "results_path": _relative(root, results_path),
            "results_sha256": results_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "independent_answerability_generalization",
            "semantic_evidence_precision",
            "contradiction_rate",
            "generation",
            "verifier",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"evidence_selector_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"evidence_selector_pilot_{markdown_sha}.md"
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
    parser = argparse.ArgumentParser(description="Evaluate the v3 evidence selector pilot")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--retrieval-results", type=Path, default=root / DEFAULT_RETRIEVAL_RESULTS
    )
    parser.add_argument(
        "--runtime-manifest", type=Path, default=root / DEFAULT_RUNTIME_MANIFEST
    )
    parser.add_argument(
        "--annotation-manifest", type=Path, default=root / DEFAULT_ANNOTATION_MANIFEST
    )
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument(
        "--selector-source", type=Path, default=root / DEFAULT_SELECTOR_SOURCE
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
        args.runtime_manifest.resolve(),
        args.annotation_manifest.resolve(),
        args.chunks.resolve(),
        args.selector_source.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
