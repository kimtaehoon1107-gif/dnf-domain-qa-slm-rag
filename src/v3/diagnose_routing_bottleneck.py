from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


DIAGNOSTIC_VERSION = "routing-bottleneck-diagnostic-v3.1.0"
ROW_SCHEMA_VERSION = "routing-failure-taxonomy-row-v3.1"
REPORT_SCHEMA_VERSION = "routing-bottleneck-diagnostic-report-v3.1"
MANIFEST_SCHEMA_VERSION = "routing-bottleneck-diagnostic-manifest-v3.1"

DEFAULT_ATTRIBUTION = Path(
    "data/v3/evaluation/canary_stage_attribution_"
    "a132069a231a64225bfe78b86fbfa3e81dbc9cf9fc538df8469d5e33ef4dce35.jsonl"
)
DEFAULT_ATTRIBUTION_MANIFEST = Path(
    "data/v3/evaluation/canary_stage_attribution_manifest_"
    "9e25fe54e91bfd133febc44de355b5df7beab370153769196cc9cc905bb3251c.json"
)
DEFAULT_ATTRIBUTION_REPORT = Path(
    "reports/v3/canary_stage_attribution_"
    "aea9decd7b8df794e9e04100d74d25ca571893fb47f6b746e0327cc19edf820a.json"
)
DEFAULT_FIRST_RUN_MANIFEST = Path(
    "data/v3/evaluation/authored_canary_first_run_manifest_"
    "4a2aef81660a13b113ab63a3739126afcddcb6b0b60f2af740becf3bfbdd93dd.json"
)
DEFAULT_PARENT_REPORT = Path(
    "reports/v3/same_parent_cross_parent_diagnostic_"
    "c81250970c2d1545a0c9071dceea16e9d9855850706bda2f6eb3568280db6cf1.json"
)
DEFAULT_PARENT_ROWS = Path(
    "data/v3/evidence/requirement_slot_coverage_cases_"
    "4c79c8861b59b56fd10207749930cc10e194faaf61ce704187028e2d308dffc2.jsonl"
)
DEFAULT_PARENT_MANIFEST = Path(
    "data/v3/evidence/requirement_slot_coverage_manifest_"
    "d5bff8acc11069cca9b2136e2473c4ae7abd22fbd35b9dc801f518ecb5d5a2fe.json"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_ENUMERATION_REPORT = Path(
    "reports/v3/planner_enumeration_answerability_ab_"
    "3e708a8d9f2352d58ed4a962b790d1269d65fad2249a835f8f04cf2e7a5ce006.json"
)
DEFAULT_ROUTE_FINAL_REPORT = Path(
    "reports/v3/route_type_pilot_final_"
    "78870cd8f5c4ef4ea56b0c77872f7d3a196f6a6c7e35316492b72fc9ff5f0f0f.json"
)
DEFAULT_ROUTE_FINAL_MANIFEST = Path(
    "data/v3/router/route_type_pilot_final_manifest_"
    "d1276658d963842660e89aeb431279c3b5517d269ef3a5665a90027f247b281b.json"
)
DEFAULT_CONTRACT = Path("docs/v3/routing_bottleneck_diagnostic.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _rate(successes: int, total: int) -> dict[str, Any]:
    if total == 0:
        return {
            "successes": successes,
            "total": total,
            "rate": 0.0,
            "wilson_95_percent": [0.0, 0.0],
        }
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return {
        "successes": successes,
        "total": total,
        "rate": round(proportion, 8),
        "wilson_95_percent": [
            round(max(0.0, center - margin), 8),
            round(min(1.0, center + margin), 8),
        ],
    }


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def classify_failure(
    attribution: dict[str, Any], parent_row: dict[str, Any]
) -> str:
    if attribution["first_failure_stage"] != "ROUTING":
        raise RuntimeError("Only ROUTING failures can be classified")
    expected = attribution["expected_route_action"]
    if expected == "realtime_api":
        return "REALTIME_MISS"
    if expected == "reject":
        return "REJECT_MISS"
    if expected != "decompose":
        return "LABEL_SUSPECT"
    same_parent = bool(parent_row["single_parent_coverable"])
    cross_parent = bool(parent_row["cross_parent"])
    if same_parent == cross_parent:
        raise RuntimeError(
            f"Expected exactly one parent classification: {attribution['case_id']}"
        )
    return "LABEL_SUSPECT" if same_parent else "DECOMPOSE_MISS"


def build_taxonomy_rows(
    attribution_rows: list[dict[str, Any]],
    parent_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    parents = {
        row["case_id"]: row
        for row in parent_rows
        if row["dataset"] == "downgraded_canary_32"
    }
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    output = []
    for attribution in attribution_rows:
        if attribution["first_failure_stage"] != "ROUTING":
            continue
        case_id = attribution["case_id"]
        if case_id not in parents or case_id not in enumerations:
            raise RuntimeError(f"Missing frozen diagnostic join row: {case_id}")
        parent = parents[case_id]
        requirement_count = len(enumerations[case_id]["requirements"])
        failure_type = classify_failure(attribution, parent)
        output.append(
            {
                "row_schema_version": ROW_SCHEMA_VERSION,
                "case_id": case_id,
                "query_ordinal": attribution["query_ordinal"],
                "failure_type": failure_type,
                "expected_route_action": attribution["expected_route_action"],
                "actual_route_action": attribution["actual_route_action"],
                "required_evidence_group_count": attribution[
                    "required_evidence_group_count"
                ],
                "single_parent_coverable": bool(
                    parent["single_parent_coverable"]
                ),
                "cross_parent": bool(parent["cross_parent"]),
                "planner_requirement_count": requirement_count,
                "planner_multi_field_signal": requirement_count >= 2,
                "tractability": (
                    "planner_path"
                    if failure_type in {"DECOMPOSE_MISS", "LABEL_SUSPECT"}
                    else "parked_answerability"
                ),
                "question_text_included": False,
                "gold_text_included": False,
            }
        )
    return sorted(output, key=lambda row: row["query_ordinal"])


def summarize(
    attribution_rows: list[dict[str, Any]],
    taxonomy_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    *,
    router_sha256: str,
    answerability_sha256: str,
) -> dict[str, Any]:
    if len(attribution_rows) != 32 or len(taxonomy_rows) != 14:
        raise RuntimeError("Expected 32 canary rows and 14 routing failures")
    if any(
        row["question_text_included"] or row["gold_text_included"]
        for row in attribution_rows
    ):
        raise RuntimeError("Text-bearing attribution artifact is out of scope")
    confusion = Counter(
        (row["expected_route_action"], row["actual_route_action"])
        for row in attribution_rows
    )
    route_exact = sum(expected == actual for expected, actual in confusion.elements())
    type_counts = Counter(row["failure_type"] for row in taxonomy_rows)
    group_counts = {
        failure_type: sum(
            row["required_evidence_group_count"]
            for row in taxonomy_rows
            if row["failure_type"] == failure_type
        )
        for failure_type in (
            "DECOMPOSE_MISS",
            "REALTIME_MISS",
            "REJECT_MISS",
            "LABEL_SUSPECT",
        )
    }
    expected_decompose = [
        row
        for row in taxonomy_rows
        if row["expected_route_action"] == "decompose"
    ]
    label_suspect = [
        row for row in taxonomy_rows if row["failure_type"] == "LABEL_SUSPECT"
    ]
    genuine_decompose = [
        row for row in taxonomy_rows if row["failure_type"] == "DECOMPOSE_MISS"
    ]
    parked = [
        row
        for row in taxonomy_rows
        if row["tractability"] == "parked_answerability"
    ]
    tractable = [
        row for row in taxonomy_rows if row["tractability"] == "planner_path"
    ]
    planner_detected_tractable = [
        row for row in tractable if row["planner_multi_field_signal"]
    ]
    enumeration_by_id = {row["case_id"]: row for row in enumeration_rows}
    all_canary_multi = sum(
        len(enumeration_by_id[row["case_id"]]["requirements"]) >= 2
        for row in attribution_rows
    )
    expected_retrieve_multi = sum(
        len(enumeration_by_id[row["case_id"]]["requirements"]) >= 2
        for row in attribution_rows
        if row["expected_route_action"] == "retrieve"
    )
    parked_false_multi = sum(row["planner_multi_field_signal"] for row in parked)
    routing_group_total = sum(
        row["required_evidence_group_count"] for row in taxonomy_rows
    )
    if Counter(type_counts) != Counter(
        {
            "LABEL_SUSPECT": 7,
            "DECOMPOSE_MISS": 2,
            "REJECT_MISS": 3,
            "REALTIME_MISS": 2,
        }
    ):
        raise RuntimeError("Routing taxonomy no longer matches frozen attribution")
    if routing_group_total != 23:
        raise RuntimeError("Expected 23 routing-attributed evidence groups")
    return {
        "current_router": {
            "component": "src.v3.question_router.route_question",
            "router_version": "dnf-question-router-v3.1.0",
            "router_source_sha256": router_sha256,
            "answerability_component": "src.v3.select_evidence.classify_answerability",
            "answerability_source_sha256": answerability_sha256,
            "canonical_status": "baseline_retained_after_signal_a_and_b_no_go",
            "decision_order": [
                "rule_based_answerability_short_circuit",
                "explicit_entity_title_candidate_source_resolution",
                "surface_decomposition_marker_or_multiple_sources",
                "temporal_scope_and_clarification",
                "route_action",
            ],
            "actions": {
                "realtime_api": "false answerability requiring private state or realtime auction data",
                "reject": "other false answerability or no resolved source",
                "decompose": "multiple resolved sources or a decomposition marker",
                "retrieve": "one resolved source, including account-policy comparison",
                "clarify": "temporal target is underspecified",
            },
            "signals": {
                "answerability": "fixed lexical/structural unsupported rules",
                "source": "explicit markers, candidate rank, entity overlap, title overlap",
                "decomposition": "surface coordination markers, month/candidate interaction, or source count",
                "planner_requirements_used": False,
            },
        },
        "route_action_exact": _rate(route_exact, len(attribution_rows)),
        "confusion_matrix": [
            {
                "expected": expected,
                "actual": actual,
                "count": count,
            }
            for (expected, actual), count in sorted(confusion.items())
        ],
        "failure_taxonomy": {
            failure_type: {
                "questions": _rate(type_counts[failure_type], len(taxonomy_rows)),
                "evidence_group_count": group_counts[failure_type],
            }
            for failure_type in (
                "DECOMPOSE_MISS",
                "REALTIME_MISS",
                "REJECT_MISS",
                "LABEL_SUSPECT",
            )
        },
        "label_reliability_audit": {
            "expected_decompose_questions": len(expected_decompose),
            "single_parent_label_suspect": _rate(
                len(label_suspect), len(expected_decompose)
            ),
            "genuine_cross_parent_decompose": _rate(
                len(genuine_decompose), len(expected_decompose)
            ),
            "single_parent_evidence_groups": sum(
                row["required_evidence_group_count"] for row in label_suspect
            ),
            "cross_parent_evidence_groups": sum(
                row["required_evidence_group_count"] for row in genuine_decompose
            ),
            "cross_parent_same_source_count": 2,
            "label_audited_route_exact_counterfactual": _rate(
                route_exact + len(label_suspect), len(attribution_rows)
            ),
            "labels_modified": False,
            "counterfactual_is_not_a_promoted_metric": True,
        },
        "tractable_vs_parked": {
            "question_denominator": len(taxonomy_rows),
            "structurally_planner_path": _rate(len(tractable), len(taxonomy_rows)),
            "parked_answerability": _rate(len(parked), len(taxonomy_rows)),
            "planner_detected_tractable_now": _rate(
                len(planner_detected_tractable), len(taxonomy_rows)
            ),
            "genuine_cross_parent_planner_enumeration_miss": _rate(
                len(tractable) - len(planner_detected_tractable),
                len(taxonomy_rows),
            ),
            "evidence_group_denominator_note": (
                "The 23/50 routing groups all belong to expected-decompose questions; "
                "the five parked controls have zero required evidence groups."
            ),
            "routing_groups_same_parent_label_suspect": _rate(
                group_counts["LABEL_SUSPECT"], routing_group_total
            ),
            "routing_groups_genuine_cross_parent": _rate(
                group_counts["DECOMPOSE_MISS"], routing_group_total
            ),
            "routing_groups_parked_answerability": _rate(0, routing_group_total),
        },
        "planner_hypothesis": {
            "hypothesis": "always enumerate; requirement_count >= 2 marks multi-field path",
            "model_or_prompt_rerun": False,
            "all_canary_multi_field_signals": _rate(
                all_canary_multi, len(attribution_rows)
            ),
            "expected_retrieve_with_multi_field_signal": _rate(
                expected_retrieve_multi,
                sum(
                    row["expected_route_action"] == "retrieve"
                    for row in attribution_rows
                ),
            ),
            "all_expected_decompose_detected": _rate(
                sum(row["planner_multi_field_signal"] for row in expected_decompose),
                len(expected_decompose),
            ),
            "same_parent_label_suspect_detected": _rate(
                sum(row["planner_multi_field_signal"] for row in label_suspect),
                len(label_suspect),
            ),
            "genuine_decompose_miss_detected": _rate(
                sum(row["planner_multi_field_signal"] for row in genuine_decompose),
                len(genuine_decompose),
            ),
            "routing_failure_groups_on_detected_planner_path": _rate(
                sum(
                    row["required_evidence_group_count"]
                    for row in planner_detected_tractable
                ),
                routing_group_total,
            ),
            "parked_answerability_false_multi_signal": _rate(
                parked_false_multi, len(parked)
            ),
            "interpretation": (
                "Planner enumeration covers every same-parent label suspect but only one "
                "of two genuine cross-parent cases, and it also emits a multi-field signal "
                "for one realtime control. It cannot replace answerability."
            ),
        },
    }


def _markdown(report: dict[str, Any]) -> bytes:
    summary = report["summary"]
    taxonomy = summary["failure_taxonomy"]
    audit = summary["label_reliability_audit"]
    split = summary["tractable_vs_parked"]
    hypothesis = summary["planner_hypothesis"]
    lines = [
        "# Routing bottleneck diagnostic",
        "",
        f"- decision: **{report['decision']}**",
        f"- current route exact: {summary['route_action_exact']['successes']}/{summary['route_action_exact']['total']}",
        f"- DECOMPOSE_MISS: {taxonomy['DECOMPOSE_MISS']['questions']['successes']}/14",
        f"- REALTIME_MISS: {taxonomy['REALTIME_MISS']['questions']['successes']}/14",
        f"- REJECT_MISS: {taxonomy['REJECT_MISS']['questions']['successes']}/14",
        f"- LABEL_SUSPECT: {taxonomy['LABEL_SUSPECT']['questions']['successes']}/14",
        f"- expected decompose same/cross parent: {audit['single_parent_label_suspect']['successes']}/{audit['genuine_cross_parent_decompose']['successes']}",
        f"- structurally planner-path vs parked: {split['structurally_planner_path']['successes']}/{split['parked_answerability']['successes']}",
        f"- frozen planner catches genuine decomposition: {hypothesis['genuine_decompose_miss_detected']['successes']}/{hypothesis['genuine_decompose_miss_detected']['total']}",
        "",
        "No router, label, question, gold, model, or runtime artifact was changed.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def diagnose_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "stage_attribution": root / DEFAULT_ATTRIBUTION,
        "stage_attribution_manifest": root / DEFAULT_ATTRIBUTION_MANIFEST,
        "stage_attribution_report": root / DEFAULT_ATTRIBUTION_REPORT,
        "first_run_manifest": root / DEFAULT_FIRST_RUN_MANIFEST,
        "same_parent_report": root / DEFAULT_PARENT_REPORT,
        "text_free_parent_rows": root / DEFAULT_PARENT_ROWS,
        "parent_rows_manifest": root / DEFAULT_PARENT_MANIFEST,
        "planner_enumeration": root / DEFAULT_ENUMERATION,
        "planner_enumeration_report": root / DEFAULT_ENUMERATION_REPORT,
        "route_type_final_report": root / DEFAULT_ROUTE_FINAL_REPORT,
        "route_type_final_manifest": root / DEFAULT_ROUTE_FINAL_MANIFEST,
        "question_router_source": root / "src/v3/question_router.py",
        "answerability_source": root / "src/v3/select_evidence.py",
        "contract": root / DEFAULT_CONTRACT,
        "diagnostic_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    route_final = json.loads(
        input_paths["route_type_final_report"].read_text(encoding="utf-8")
    )
    if route_final["canonical_router"]["sha256"] != input_hashes[
        "question_router_source"
    ]:
        raise RuntimeError("Current router differs from retained canonical router")
    first_run = json.loads(
        input_paths["first_run_manifest"].read_text(encoding="utf-8")
    )
    if first_run["inputs"]["question_router_source"]["sha256"] != input_hashes[
        "question_router_source"
    ]:
        raise RuntimeError("First-run router lineage no longer matches current source")
    if first_run["inputs"]["selector_source"]["sha256"] != input_hashes[
        "answerability_source"
    ]:
        raise RuntimeError("First-run answerability lineage no longer matches current source")
    attributions = read_jsonl(input_paths["stage_attribution"])
    taxonomy = build_taxonomy_rows(
        attributions,
        read_jsonl(input_paths["text_free_parent_rows"]),
        read_jsonl(input_paths["planner_enumeration"]),
    )
    summary = summarize(
        attributions,
        taxonomy,
        read_jsonl(input_paths["planner_enumeration"]),
        router_sha256=input_hashes["question_router_source"],
        answerability_sha256=input_hashes["answerability_source"],
    )
    router_dir = root / "data/v3/router"
    reports_dir = root / "reports/v3"
    rows_bytes = _serialize_jsonl(taxonomy, lambda row: row["query_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = router_dir / f"routing_bottleneck_taxonomy_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "evaluation_role": "adaptive_validation_diagnostic_only",
        "decision": "DIAGNOSTIC_COMPLETE_ROUTING_FIX_NOT_AUTHORIZED",
        "summary": summary,
        "interpretation": {
            "primary_next_approach": (
                "planner-first multi-field path with same-parent retrieval/assembly; "
                "reserve decomposition for cross-parent cases"
            ),
            "answerability_status": "PARKED_UNRESOLVED_AND_NOT_REOPENED",
            "label_contract_status": "SEVEN_DECOMPOSE_LABELS_REQUIRE_SEPARATE_REVIEW",
            "new_sealed_canary": "NOT_RUN",
        },
        "scope": {
            "routing_logic_changed": False,
            "labels_changed": False,
            "questions_or_gold_changed": False,
            "planner_changed": False,
            "model_or_prompt_run": False,
            "keyword_rules_added": 0,
            "answerability_reopened": False,
            "training": False,
            "new_canary": False,
            "frozen_blind_accessed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"routing_bottleneck_diagnostic_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"routing_bottleneck_diagnostic_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "artifacts": {
            "taxonomy": {
                "path": _relative(root, rows_path),
                "sha256": rows_sha,
                "row_count": len(taxonomy),
                "question_or_gold_text_included": False,
            },
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "decision": report["decision"],
        "routing_fix_implemented": False,
        "new_canary_run": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = router_dir / f"routing_bottleneck_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during routing diagnosis: {name}")
    return {
        "decision": report["decision"],
        "summary": summary,
        "taxonomy_path": str(rows_path),
        "taxonomy_sha256": rows_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose the frozen authored-canary routing bottleneck"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = diagnose_and_freeze(parse_args().root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
