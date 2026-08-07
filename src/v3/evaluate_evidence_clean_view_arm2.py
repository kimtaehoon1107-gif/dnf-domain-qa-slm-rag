from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.build_evidence_clean_view import span_is_eligible
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_router_backbone_ab import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_CANARY,
    DEFAULT_CLASSIFIER_DIAGNOSTICS,
    DEFAULT_CLASSIFIER_PREDICTIONS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
    build_cases,
    summarize_arm,
)


EVALUATOR_VERSION = "evidence-clean-view-arm2-ab-v3.2.0"
REPORT_SCHEMA_VERSION = "evidence-clean-view-arm2-report-v3.2"
CASE_SCHEMA_VERSION = "evidence-clean-view-arm2-case-v3.2"
MANIFEST_SCHEMA_VERSION = "evidence-clean-view-arm2-manifest-v3.2"

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_VIEW = Path(
    "data/v3/evidence/evidence_clean_view_v3.2_"
    "07ece90aedc0eb5cb87ba29cbd1300f9ae19764504fd6ec005eb07423d75a1d5.jsonl"
)
DEFAULT_VIEW_MANIFEST = Path(
    "data/v3/evidence/evidence_clean_view_manifest_"
    "0a473c8762a072d88b9ffccae84e71202fec6f098a1f1eabb07cdc4a9c040f93.json"
)
DEFAULT_DIRTY_ASSEMBLER = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_P2_CLEAN_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_retrieval_clean_v3.1_"
    "61d858ef5b7df3a3c157e65dba9dd6991f1daa74bbd2067f17b2438e1c01b5b8.jsonl"
)
DEFAULT_P2_ASSEMBLER = Path(
    "data/v3/evidence/corpus_hygiene_assembler_cases_"
    "7502b4630f3230586bc4c53b20c385324a15ab344621a46d31fa6e203cd82901.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/evidence_clean_view_arm2.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/evidence")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reason_for_span(
    view: dict[str, Any], *, start_offset: int, end_offset: int
) -> list[str]:
    return sorted(
        {
            reason
            for excluded in view["excluded_ranges"]
            if start_offset < excluded["end_offset"]
            and end_offset > excluded["start_offset"]
            for reason in excluded["reasons"]
        }
    )


def apply_evidence_mask(
    assembler_rows: list[dict[str, Any]],
    *,
    views_by_chunk: dict[str, dict[str, Any]],
    evaluation_arm: str = "fixture",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    masked = copy.deepcopy(assembler_rows)
    removals = []
    for row in masked:
        for requirement_index, decision in enumerate(row["decisions"], 1):
            kept = []
            for span in decision["spans"]:
                view = views_by_chunk.get(span["chunk_id"])
                if span_is_eligible(
                    view,
                    start_offset=int(span["start_char"]),
                    end_offset=int(span["end_char"]),
                ):
                    kept.append(span)
                    continue
                removals.append(
                    {
                        "case_schema_version": CASE_SCHEMA_VERSION,
                        "evaluation_arm": evaluation_arm,
                        "case_id": row["case_id"],
                        "dataset": row["dataset"],
                        "requirement_index": requirement_index,
                        "span_id": span["span_id"],
                        "chunk_id": span["chunk_id"],
                        "start_char": span["start_char"],
                        "end_char": span["end_char"],
                        "text": span["text"],
                        "excluded_reasons": _reason_for_span(
                            view,
                            start_offset=int(span["start_char"]),
                            end_offset=int(span["end_char"]),
                        )
                        if view
                        else [],
                    }
                )
            decision["spans"] = kept
            if decision["status"] == "supported_exact" and not kept:
                decision["status"] = "unsupported"
                decision["unsupported_message"] = "문서에서 확인 불가"
    removals.sort(key=lambda item: (item["evaluation_arm"], item["dataset"], item["case_id"], item["requirement_index"], item["span_id"]))
    return masked, removals


def _case_inputs(root: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        "ground_truth_rows": read_jsonl(root / DEFAULT_GROUND_TRUTH),
        "evaluation_rows": read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV),
        "attribution_rows": read_jsonl(root / DEFAULT_ATTRIBUTION),
        "enumeration_rows": read_jsonl(root / DEFAULT_ENUMERATION),
        "prediction_rows": read_jsonl(root / DEFAULT_CLASSIFIER_PREDICTIONS),
        "classifier_diagnostic_rows": read_jsonl(root / DEFAULT_CLASSIFIER_DIAGNOSTICS),
    }


def _evaluate(
    *,
    shared_inputs: dict[str, list[dict[str, Any]]],
    assembler_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = build_cases(
        **shared_inputs,
        assembler_rows=assembler_rows,
        chunks=chunks,
    )
    return cases, summarize_arm(cases, "arm0")


def _false_full_ids(rows: list[dict[str, Any]]) -> set[str]:
    return {
        row["case_id"]
        for row in rows
        if row["arm0"]["score"]["false_full_answer"]
    }


def _exact_metrics(
    assembler_rows: list[dict[str, Any]], chunks_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    total = invalid = 0
    for row in assembler_rows:
        for decision in row["decisions"]:
            for span in decision["spans"]:
                total += 1
                source = chunks_by_id[span["chunk_id"]]["display_text"]
                invalid += source[span["start_char"] : span["end_char"]] != span["text"]
    return {
        "total": total,
        "invalid": invalid,
        "valid": total - invalid,
        "rate": round((total - invalid) / total, 8) if total else 1.0,
    }


def _compact(metrics: dict[str, Any]) -> dict[str, int]:
    return {
        "grounded": metrics["answerable"]["grounded_answer"]["successes"],
        "false_full": metrics["answerable"]["false_full_answer"]["successes"],
        "honest_partial": metrics["answerable"]["honest_partial"]["successes"],
        "overreject": metrics["answerable"]["overreject"]["successes"],
        "reject_correct": metrics["reject"]["correct_abstain_or_reject"]["successes"],
        "realtime_safe_abstain": metrics["realtime"]["safe_abstain"]["successes"],
        "realtime_static_exposure": metrics["realtime"]["static_document_exposure"]["successes"],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# v3.2 Arm 2 — Evidence clean view A/B",
        "",
        f"Decision: **{report['gate']['decision']}**. No canonical/runtime promotion was performed.",
        "",
        "| Evaluation | Grounded | False-full | Honest partial | Reject | Realtime safe |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, metrics in report["metrics"].items():
        lines.append(
            f"| {label} | {metrics['grounded']} | {metrics['false_full']} | {metrics['honest_partial']} | {metrics['reject_correct']} | {metrics['realtime_safe_abstain']} |"
        )
    lines.extend(
        [
            "",
            f"Removed contaminated spans: {report['mask']['removed_span_count']} across {report['mask']['affected_question_count']} questions.",
            f"Remaining exact spans: {report['integrity']['exact']['valid']}/{report['integrity']['exact']['total']}.",
            "",
            "The prior global retrieval-clean replacement remains NO-GO. This Arm changes evidence eligibility only and keeps retrieval ordering frozen.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate evidence clean-view mask Arm 2")
    parser.add_argument("--view", type=Path, default=DEFAULT_VIEW)
    parser.add_argument("--view-manifest", type=Path, default=DEFAULT_VIEW_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    resolve = lambda value: value if value.is_absolute() else root / value

    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    clean_chunks = read_jsonl(root / DEFAULT_P2_CLEAN_CHUNKS)
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    views = read_jsonl(resolve(args.view))
    views_by_chunk = {row["chunk_id"]: row for row in views}
    shared = _case_inputs(root)

    dirty_assembler = read_jsonl(root / DEFAULT_DIRTY_ASSEMBLER)
    dirty_baseline_cases, dirty_baseline_metrics = _evaluate(
        shared_inputs=shared, assembler_rows=dirty_assembler, chunks=chunks
    )
    masked_dirty, dirty_removals = apply_evidence_mask(
        dirty_assembler, views_by_chunk=views_by_chunk, evaluation_arm="dirty"
    )
    dirty_arm_cases, dirty_arm_metrics = _evaluate(
        shared_inputs=shared, assembler_rows=masked_dirty, chunks=chunks
    )

    p2_assembler = read_jsonl(root / DEFAULT_P2_ASSEMBLER)
    p2_baseline_cases, p2_baseline_metrics = _evaluate(
        shared_inputs=shared, assembler_rows=p2_assembler, chunks=clean_chunks
    )
    masked_p2, p2_removals = apply_evidence_mask(
        p2_assembler, views_by_chunk=views_by_chunk, evaluation_arm="p2_clean"
    )
    p2_arm_cases, p2_arm_metrics = _evaluate(
        shared_inputs=shared, assembler_rows=masked_p2, chunks=clean_chunks
    )

    primary_before = _compact(dirty_baseline_metrics)
    primary_after = _compact(dirty_arm_metrics)
    p2_before = _compact(p2_baseline_metrics)
    p2_after = _compact(p2_arm_metrics)
    new_false_full = _false_full_ids(dirty_arm_cases) - _false_full_ids(dirty_baseline_cases)
    exact = _exact_metrics(masked_dirty, chunks_by_id)
    gate_checks = {
        "frozen_baseline_reproduced_73_9": primary_before["grounded"] == 73 and primary_before["false_full"] == 9,
        "primary_grounded_at_least_73": primary_after["grounded"] >= 73,
        "primary_false_full_not_increased": primary_after["false_full"] <= 9,
        "new_false_full_zero": not new_false_full,
        "p2_grounded_not_decreased": p2_after["grounded"] >= p2_before["grounded"],
        "p2_false_full_reduced": p2_after["false_full"] < p2_before["false_full"],
        "contaminated_span_removed": bool(dirty_removals or p2_removals),
        "exact_span_100_percent": exact["invalid"] == 0,
        "reject_11_of_11": primary_after["reject_correct"] == 11,
        "realtime_safe_2_of_2": primary_after["realtime_safe_abstain"] == 2,
        "realtime_static_exposure_zero": primary_after["realtime_static_exposure"] == 0,
    }
    gate_pass = all(gate_checks.values())
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "status": "development_only_not_promoted",
        "suitability": {
            "global_retrieval_clean_replacement": "SKIPPED_AS_PRIOR_NO_GO",
            "offset_preserving_evidence_mask": "A_B_EVALUATED",
            "rationale": "preserve candidate ordering while excluding measured non-evidence ranges",
        },
        "metrics": {
            "dirty_baseline": primary_before,
            "dirty_plus_mask": primary_after,
            "p2_clean_baseline": p2_before,
            "p2_clean_plus_mask": p2_after,
        },
        "mask": {
            "view_count": len(views),
            "dirty_removed_span_count": len(dirty_removals),
            "p2_removed_span_count": len(p2_removals),
            "removed_span_count": len(dirty_removals) + len(p2_removals),
            "affected_question_count": len({row["case_id"] for row in [*dirty_removals, *p2_removals]}),
            "new_false_full_ids": sorted(new_false_full),
        },
        "integrity": {
            "exact": exact,
            "dirty_chunks_sha256": file_sha256(root / DEFAULT_CHUNKS),
            "dirty_canonical_hash_unchanged": file_sha256(root / DEFAULT_CHUNKS) == DEFAULT_CHUNKS.stem.rsplit("_", 1)[-1],
            "retrieval_ranking_changed": False,
            "gold_changed": False,
            "citation_offsets_changed": False,
        },
        "gate": {
            "checks": gate_checks,
            "pass": gate_pass,
            "decision": "GO_ARM2_CANDIDATE_NOT_PROMOTED" if gate_pass else "NO_GO_DIRTY_CANONICAL_REMAINS",
            "promoted": False,
        },
    }

    removal_payload = _serialize_jsonl(
        [*dirty_removals, *p2_removals],
        lambda row: (row["evaluation_arm"], row["dataset"], row["case_id"], row["requirement_index"], row["span_id"]),
    )
    removal_sha = _sha256_bytes(removal_payload)
    output_dir = resolve(args.output_dir)
    removal_path = output_dir / f"evidence_clean_view_arm2_removed_spans_{removal_sha}.jsonl"
    write_immutable(removal_path, removal_payload)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_dir = resolve(args.report_dir)
    report_path = report_dir / f"evidence_clean_view_arm2_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"evidence_clean_view_arm2_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {
            "view": {"path": args.view.as_posix(), "sha256": file_sha256(resolve(args.view))},
            "view_manifest": {"path": args.view_manifest.as_posix(), "sha256": file_sha256(resolve(args.view_manifest))},
            "dirty_chunks": {"path": DEFAULT_CHUNKS.as_posix(), "sha256": file_sha256(root / DEFAULT_CHUNKS)},
            "dirty_assembler": {"path": DEFAULT_DIRTY_ASSEMBLER.as_posix(), "sha256": file_sha256(root / DEFAULT_DIRTY_ASSEMBLER)},
            "p2_clean_chunks": {"path": DEFAULT_P2_CLEAN_CHUNKS.as_posix(), "sha256": file_sha256(root / DEFAULT_P2_CLEAN_CHUNKS)},
            "p2_assembler": {"path": DEFAULT_P2_ASSEMBLER.as_posix(), "sha256": file_sha256(root / DEFAULT_P2_ASSEMBLER)},
            "contract": {"path": DEFAULT_CONTRACT.as_posix(), "sha256": file_sha256(root / DEFAULT_CONTRACT)},
            "evaluator_source": {"path": Path(__file__).resolve().relative_to(root).as_posix(), "sha256": file_sha256(Path(__file__).resolve())},
        },
        "artifacts": {
            "removed_spans": {"path": removal_path.relative_to(root).as_posix(), "sha256": removal_sha, "row_count": len(dirty_removals) + len(p2_removals)},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "gate": report["gate"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"evidence_clean_view_arm2_evaluation_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), "removed_spans": removal_path.relative_to(root).as_posix(), "manifest": manifest_path.relative_to(root).as_posix(), "metrics": report["metrics"], "gate": report["gate"]}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
