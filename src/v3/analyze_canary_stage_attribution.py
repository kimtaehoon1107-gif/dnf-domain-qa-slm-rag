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
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.evaluate_authored_canary import wilson_interval


ANALYZER_VERSION = "canary-stage-attribution-v3.1.0"
ATTRIBUTION_SCHEMA_VERSION = "canary-stage-attribution-row-v3.1"
MANIFEST_SCHEMA_VERSION = "canary-stage-attribution-manifest-v3.1"
REPORT_SCHEMA_VERSION = "canary-stage-attribution-report-v3.1"
STAGE_ORDER = (
    "ROUTING",
    "RETRIEVAL",
    "SELECTION",
    "CLAIM_COVERAGE",
    "VERIFY",
)

DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CASES = Path(
    "data/v3/evaluation/authored_canary_first_run_cases_"
    "a326d9fd96a4cfcaf9b2d38d74f27fffe26b62dfc1364063c8258891546beecd.jsonl"
)
DEFAULT_RUN_MANIFEST = Path(
    "data/v3/evaluation/authored_canary_first_run_manifest_"
    "4a2aef81660a13b113ab63a3739126afcddcb6b0b60f2af740becf3bfbdd93dd.json"
)
DEFAULT_RUN_REPORT = Path(
    "reports/v3/authored_canary_first_run_"
    "394f11964df7da2768fd836bc08674ae3b1e83ba4d7010a34f639a4e051b9f5c.json"
)
DEFAULT_CONTRACT = Path("docs/v3/early_generalization_canary.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _histogram(values: list[str], denominator: int) -> dict[str, dict[str, Any]]:
    counts = Counter(values)
    return {
        bucket: {
            "count": counts[bucket],
            "denominator": denominator,
            "rate": round(counts[bucket] / denominator, 8) if denominator else 0.0,
            "wilson_95_percent": wilson_interval(counts[bucket], denominator),
        }
        for bucket in (*STAGE_ORDER, "PASS")
    }


def _type_tags(dev: dict[str, Any]) -> list[str]:
    tags = [
        *(f"source:{source_id}" for source_id in dev["source_ids"]),
        f"query_kind:{dev['query_kind']}",
        f"time_scope:{dev['time_scope']}",
        f"answerability:{dev['answerability']}",
        f"expected_route:{dev['query_policy']['expected_route_action']}",
    ]
    if dev["query_kind"] in {"multi", "comparison"}:
        tags.append("compound_field_requirement")
    if dev["query_kind"] == "multi" and not any(
        marker in dev["question"] for marker in ("각각", "비교", "함께")
    ):
        tags.append("multi_without_surface_keywords")
    if dev["query_kind"] == "comparison" or dev["time_scope"] in {
        "historical",
        "mixed",
        "preview",
    }:
        tags.append("historical_preview_or_comparison_mode")
    if "dnf_notice" in dev["source_ids"]:
        tags.append("notice_source")
    if dev["answerability"] == "partial":
        tags.append("partial")
    if dev["query_policy"]["expected_route_action"] in {"reject", "realtime_api"}:
        tags.append("zero_evidence_control")
    return sorted(set(tags))


def _first_group_failure(
    route_exact: bool,
    group: dict[str, Any],
    verify_failed: bool,
) -> str:
    if not route_exact:
        return "ROUTING"
    if not group["retrieval_hit"]:
        return "RETRIEVAL"
    if not group["selected_hit"]:
        return "SELECTION"
    if not group["canonical_cited_hit"] or not group["claim_complete"]:
        return "CLAIM_COVERAGE"
    if verify_failed:
        return "VERIFY"
    return "PASS"


def attribute_case(dev: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    if dev["dev_id"] != case["case_id"]:
        raise RuntimeError("Canary and case IDs differ")
    route_exact = bool(case["route_action_exact"])
    verify_failed = bool(
        case["temporal_revision_violations"]
        or case["false_realtime_evidence_exposure"]
    )
    partial_disclaimer_failed = bool(
        dev["answerability"] == "partial" and not case["partial_disclaimer"]
    )
    groups = [
        {
            "group_id": group["group_id"],
            "first_failure_stage": _first_group_failure(
                route_exact, group, verify_failed
            ),
        }
        for group in case["group_results"]
    ]
    if not route_exact:
        first_stage = "ROUTING"
    elif case["group_results"] and not all(
        group["retrieval_hit"] for group in case["group_results"]
    ):
        first_stage = "RETRIEVAL"
    elif case["group_results"] and not all(
        group["selected_hit"] for group in case["group_results"]
    ):
        first_stage = "SELECTION"
    elif case["group_results"] and not all(
        group["canonical_cited_hit"] and group["claim_complete"]
        for group in case["group_results"]
    ):
        first_stage = "CLAIM_COVERAGE"
    elif partial_disclaimer_failed:
        first_stage = "CLAIM_COVERAGE"
    elif verify_failed:
        first_stage = "VERIFY"
    else:
        first_stage = "PASS"
    return {
        "attribution_schema_version": ATTRIBUTION_SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "case_id": case["case_id"],
        "query_ordinal": case["query_ordinal"],
        "source_ids": dev["source_ids"],
        "query_kind": dev["query_kind"],
        "time_scope": dev["time_scope"],
        "answerability": dev["answerability"],
        "expected_route_action": dev["query_policy"]["expected_route_action"],
        "actual_route_action": None
        if case["actual_route"] is None
        else case["actual_route"]["route_action"],
        "first_failure_stage": first_stage,
        "type_tags": _type_tags(dev),
        "required_evidence_group_count": len(groups),
        "group_attribution": groups,
        "question_text_included": False,
        "gold_text_included": False,
    }


def _dominance(histogram: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failure_counts = {
        stage: histogram[stage]["count"] for stage in STAGE_ORDER
    }
    maximum = max(failure_counts.values(), default=0)
    dominant = sorted(
        stage
        for stage, count in failure_counts.items()
        if count == maximum and count >= 5
    )
    hints = sorted(
        stage for stage, count in failure_counts.items() if 0 < count < 5
    )
    supported = sorted(
        stage for stage, count in failure_counts.items() if count >= 5
    )
    secondary_supported = [stage for stage in supported if stage not in dominant]
    routing_dominant = "ROUTING" in dominant
    return {
        "dominant_buckets": dominant,
        "dominance_status": "none"
        if not dominant
        else "co_dominant"
        if len(dominant) > 1
        else "dominant",
        "buckets_below_five_are_hints_only": hints,
        "buckets_with_at_least_five_failures": supported,
        "secondary_supported_buckets": secondary_supported,
        "routing_is_dominant": routing_dominant,
        "required_first_approach": "ROBUST_ROUTING"
        if routing_dominant
        else dominant[0]
        if dominant
        else None,
        "downstream_change_before_routing_gate": "PROHIBITED"
        if routing_dominant
        else "NOT_APPLICABLE",
    }


def _retrieval_source_memo(
    attributions: list[dict[str, Any]], cases_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows = [row for row in attributions if row["required_evidence_group_count"]]
    source_rows = {}
    for source_id in sorted({source for row in rows for source in row["source_ids"]}):
        subset = [row for row in rows if source_id in row["source_ids"]]
        route_exact = [row for row in subset if row["first_failure_stage"] != "ROUTING"]
        raw_success = sum(
            all(
                group["retrieval_hit"]
                for group in cases_by_id[row["case_id"]]["group_results"]
            )
            for row in subset
        )
        route_exact_success = sum(
            all(
                group["retrieval_hit"]
                for group in cases_by_id[row["case_id"]]["group_results"]
            )
            for row in route_exact
        )
        source_rows[source_id] = {
            "raw_all_required_retrieval": {
                "successes": raw_success,
                "total": len(subset),
                "rate": round(raw_success / len(subset), 8) if subset else 0.0,
            },
            "route_exact_subset": {
                "successes": route_exact_success,
                "total": len(route_exact),
                "rate": round(route_exact_success / len(route_exact), 8)
                if route_exact
                else 0.0,
            },
            "first_failure_buckets": dict(
                sorted(Counter(row["first_failure_stage"] for row in subset).items())
            ),
        }
    minimum = min(
        (entry["raw_all_required_retrieval"]["rate"] for entry in source_rows.values()),
        default=0.0,
    )
    lowest = sorted(
        source_id
        for source_id, entry in source_rows.items()
        if entry["raw_all_required_retrieval"]["rate"] == minimum
    )
    return {
        "by_source": source_rows,
        "lowest_sources": lowest,
        "cause_note": (
            "Raw source recall is confounded by earlier routing failures. "
            "Only route-exact RETRIEVAL cases justify chunking or Korean-tokenization inspection; "
            "no chunking/tokenization change is authorized by this attribution alone."
        ),
    }


def _approach_matrix(routing_dominant: bool) -> dict[str, Any]:
    return {
        "ROUTING": {
            "wrong_fix": "add intent keyword rules",
            "correct_approach": "uncertainty-aware multi-store retrieval or confidence-gated broad-search fallback",
            "gate": "replacement canary route accuracy does not collapse relative to development",
            "priority": "FIRST" if routing_dominant else "AFTER_DOMINANT_BUCKET",
        },
        "RETRIEVAL": {
            "wrong_fix": "add the failed question chunk to gold",
            "correct_approach": "inspect route-exact lowest-source chunking and Korean morphological candidate recall",
            "gate": "replacement canary minimum source retrieval meets preregistered threshold",
            "priority": "DEFER_UNTIL_ROUTING_GATE" if routing_dominant else "STRUCTURAL_AUDIT",
        },
        "SELECTION": {
            "wrong_fix": "add per-question selector bonuses",
            "correct_approach": "semantic requirement coverage and evidence diversity without query-specific keywords",
            "gate": "replacement canary selected evidence-group hit improves without source regression",
            "priority": "DEFER_UNTIL_UPSTREAM_GATES",
        },
        "CLAIM_COVERAGE": {
            "wrong_fix": "add requirement keywords such as price, period, or deletion date",
            "correct_approach": "semantic or entailment-based requirement-slot coverage that requires evidence for every compound slot",
            "gate": "replacement canary claim completeness and strict citation improve with zero regression",
            "priority": "DEFER_UNTIL_UPSTREAM_GATES",
        },
        "VERIFY": {
            "wrong_fix": "expand lottery, weather, or market-price keyword lists",
            "correct_approach": "structural status, revision, and route-based exposure blocking",
            "gate": "zero temporal or revision violations and zero false or realtime exposure",
            "priority": "SAFETY_GATE_AFTER_ROUTING",
        },
    }


def analyze_and_freeze(
    *,
    root: Path,
    canary_path: Path = DEFAULT_CANARY,
    cases_path: Path = DEFAULT_CASES,
    run_manifest_path: Path = DEFAULT_RUN_MANIFEST,
    run_report_path: Path = DEFAULT_RUN_REPORT,
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    canary_path = resolve(canary_path)
    cases_path = resolve(cases_path)
    run_manifest_path = resolve(run_manifest_path)
    run_report_path = resolve(run_report_path)
    contract_path = resolve(contract_path)
    input_paths = {
        "adaptive_canary": canary_path,
        "sealed_first_run_cases": cases_path,
        "sealed_first_run_manifest": run_manifest_path,
        "sealed_first_run_report": run_report_path,
        "original_canary_contract": contract_path,
        "analyzer_source": root / "src/v3/analyze_canary_stage_attribution.py",
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    canary_rows = sorted(read_jsonl(canary_path), key=lambda row: row["query_ordinal"])
    case_rows = sorted(read_jsonl(cases_path), key=lambda row: row["query_ordinal"])
    if len(canary_rows) != 32 or len(case_rows) != 32:
        raise RuntimeError("Expected 32 aligned canary and case rows")
    canary_ids = [row["dev_id"] for row in canary_rows]
    if len(set(canary_ids)) != 32:
        raise RuntimeError("Duplicate or missing canary dev IDs")
    cases_by_id = {row["case_id"]: row for row in case_rows}
    if len(cases_by_id) != 32:
        raise RuntimeError("Duplicate or missing canary case IDs")
    if set(canary_ids) != set(cases_by_id):
        raise RuntimeError("Canary and case ID sets differ")
    attributions = [
        attribute_case(dev, cases_by_id[dev["dev_id"]]) for dev in canary_rows
    ]
    question_histogram = _histogram(
        [row["first_failure_stage"] for row in attributions], len(attributions)
    )
    required_rows = [
        row for row in attributions if row["required_evidence_group_count"]
    ]
    if len(required_rows) != 27:
        raise RuntimeError("Expected 27 canary rows with required evidence")
    required_row_histogram = _histogram(
        [row["first_failure_stage"] for row in required_rows], len(required_rows)
    )
    group_stages = [
        group["first_failure_stage"]
        for row in attributions
        for group in row["group_attribution"]
    ]
    if len(group_stages) != 50:
        raise RuntimeError("Expected 50 required evidence groups")
    group_histogram = _histogram(group_stages, len(group_stages))
    dominance = _dominance(question_histogram)
    tag_histogram = {
        bucket: dict(
            sorted(
                Counter(
                    tag
                    for row in attributions
                    if row["first_failure_stage"] == bucket
                    for tag in row["type_tags"]
                ).items()
            )
        )
        for bucket in (*STAGE_ORDER, "PASS")
    }
    retrieval_memo = _retrieval_source_memo(attributions, cases_by_id)
    approach_matrix = _approach_matrix(dominance["routing_is_dominant"])
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"

    downgrade = {
        "record_schema_version": "canary-adaptive-downgrade-v1",
        "sealed_baseline": {
            "canary": {"path": _relative(root, canary_path), "sha256": input_hashes["adaptive_canary"]},
            "cases": {"path": _relative(root, cases_path), "sha256": input_hashes["sealed_first_run_cases"]},
            "manifest": {"path": _relative(root, run_manifest_path), "sha256": input_hashes["sealed_first_run_manifest"]},
            "report": {"path": _relative(root, run_report_path), "sha256": input_hashes["sealed_first_run_report"]},
        },
        "status_before": "authored_canary_first_sealed_run_no_go",
        "status_after": "adaptive_validation_diagnostic_only",
        "questions_or_gold_modified": False,
        "sealed_artifacts_deleted_or_overwritten": False,
        "future_sealed_reuse_allowed": False,
        "frozen_blind_accessed": False,
    }
    downgrade_bytes = _canonical_json_bytes(downgrade)
    downgrade_sha = _sha256_bytes(downgrade_bytes)
    downgrade_path = reports_dir / f"authored_canary_adaptive_downgrade_{downgrade_sha}.json"
    write_immutable(downgrade_path, downgrade_bytes)

    attribution_bytes = _serialize_jsonl(attributions, lambda row: row["query_ordinal"])
    attribution_sha = _sha256_bytes(attribution_bytes)
    attribution_path = evaluation_dir / f"canary_stage_attribution_{attribution_sha}.jsonl"
    write_immutable(attribution_path, attribution_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "stage_order": list(STAGE_ORDER),
        "first_failure_only": True,
        "downstream_double_counting": False,
        "questions_or_gold_modified": False,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "downgrade": {"path": _relative(root, downgrade_path), "sha256": downgrade_sha},
        "attribution": {
            "path": _relative(root, attribution_path),
            "sha256": attribution_sha,
            "row_count": len(attributions),
            "question_text_included": False,
            "gold_text_included": False,
        },
        "histograms": {
            "questions_32": question_histogram,
            "required_evidence_rows_27": required_row_histogram,
            "evidence_groups_50": group_histogram,
        },
        "dominance": dominance,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"canary_stage_attribution_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "evaluation_status": "adaptive_validation_diagnostic_only",
        "sealed_generalization_baseline_preserved": True,
        "questions_or_gold_modified": False,
        "new_dev_fit_rules_added": 0,
        "runtime_approach_changes_implemented": [],
        "group_verify_attribution_limit": (
            "The sealed case artifact exposes temporal and realtime violations only at case level. "
            "An otherwise-passing evidence group in such a case is therefore tagged VERIFY; "
            "the artifact cannot identify a narrower offending group."
        ),
        "histograms": manifest["histograms"],
        "type_tag_histograms": tag_histogram,
        "dominance": dominance,
        "retrieval_lowest_source_memo": retrieval_memo,
        "approach_matrix": approach_matrix,
        "next_gate": "implement dominant-stage approach, then use a new separately authored and reviewed sealed canary",
        "artifacts": {
            "attribution_path": _relative(root, attribution_path),
            "attribution_sha256": attribution_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
            "downgrade_path": _relative(root, downgrade_path),
            "downgrade_sha256": downgrade_sha,
        },
        "frozen_blind_accessed": False,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"canary_stage_attribution_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = "\n".join(
        [
            "# DNF RAG v3 canary stage attribution",
            "",
            "- status: **adaptive_validation_diagnostic_only**",
            "- questions/gold modified: **no**",
            "- new dev-fit rules added: **0**",
            "- stage order: route -> candidate_retrieval -> evidence_selection -> claim_citation -> temporal_safety_verify",
            "",
            "## Question-level first-failure histogram",
            "",
            *[
                f"- {bucket}: {entry['count']}/{entry['denominator']} ({entry['rate']:.4f}), Wilson 95% {entry['wilson_95_percent']}"
                for bucket, entry in question_histogram.items()
            ],
            "",
            "## Interpretation",
            "",
            f"- dominant buckets: {dominance['dominant_buckets']}",
            f"- required first approach: {dominance['required_first_approach']}",
            f"- downstream change before routing gate: {dominance['downstream_change_before_routing_gate']}",
            "",
            "Question text and gold text are intentionally absent from attribution artifacts.",
            "",
        ]
    ).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown)
    markdown_path = reports_dir / f"canary_stage_attribution_{markdown_sha}.md"
    write_immutable(markdown_path, markdown)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during stage attribution: {name}")
    return {
        "question_histogram": question_histogram,
        "required_row_histogram": required_row_histogram,
        "group_histogram": group_histogram,
        "dominance": dominance,
        "retrieval_lowest_source_memo": retrieval_memo,
        "attribution_path": str(attribution_path),
        "attribution_sha256": attribution_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "downgrade_path": str(downgrade_path),
        "downgrade_sha256": downgrade_sha,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Attribute adaptive canary failures by first pipeline stage")
    parser.add_argument("--root", type=Path, default=root)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(analyze_and_freeze(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
