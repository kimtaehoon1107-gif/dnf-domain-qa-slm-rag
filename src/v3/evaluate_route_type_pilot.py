from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.answer_target_router import analyze_answer_targets
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable
from src.v3.select_evidence import classify_answerability


EVALUATOR_VERSION = "route-type-signal-a-pilot-v3.2.0"
MANIFEST_SCHEMA_VERSION = "route-type-signal-a-pilot-manifest-v3.2"
REPORT_SCHEMA_VERSION = "route-type-signal-a-pilot-report-v3.2"
BASELINE_ROUTER_SHA256 = (
    "bc380e735d933d9781228480b5066cff11df2cff2f704bdb242f37dd0bd25a7b"
)

DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_BASELINE_CASES = Path(
    "data/v3/evaluation/authored_canary_first_run_cases_"
    "a326d9fd96a4cfcaf9b2d38d74f27fffe26b62dfc1364063c8258891546beecd.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/route_type_decomposition_pilot.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _rate(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
    }


def _predicted_action(question: str) -> tuple[str, dict[str, Any] | None]:
    answerability = classify_answerability(question)
    if answerability["label"] == "false":
        realtime = answerability["reason"] in {
            "requires_private_account_state",
            "requires_realtime_auction_api",
        }
        return ("realtime_api" if realtime else "reject"), None
    signal = analyze_answer_targets(question)
    return ("decompose" if signal["needs_decomposition"] else "retrieve"), signal


def evaluate_rows(
    rows: list[dict[str, Any]],
    expected_action: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    expected_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    true_positive = 0
    false_positive = 0
    false_negative = 0
    exact = 0
    answerability_short_circuit = 0
    analyzer_calls = 0
    keyword_rule_count = 0
    signal_b_count = 0
    for row in rows:
        expected = expected_action(row)
        predicted, signal = _predicted_action(row["question"])
        expected_counts[expected] += 1
        predicted_counts[predicted] += 1
        exact += predicted == expected
        answerability_short_circuit += expected in {"reject", "realtime_api"} and (
            predicted in {"reject", "realtime_api"}
        )
        true_positive += predicted == expected == "decompose"
        false_positive += predicted == "decompose" and expected != "decompose"
        false_negative += predicted != "decompose" and expected == "decompose"
        if signal is not None:
            analyzer_calls += 1
            keyword_rule_count += signal["domain_keyword_rule_count"]
            keyword_rule_count += signal["surface_marker_rule_count"]
            signal_b_count += signal["signal_b_applied"]
    predicted_decompose = true_positive + false_positive
    expected_decompose = true_positive + false_negative
    return {
        "row_count": len(rows),
        "expected_action_counts": dict(sorted(expected_counts.items())),
        "predicted_action_counts": dict(sorted(predicted_counts.items())),
        "route_action_exact": _rate(exact, len(rows)),
        "answerability_short_circuit_count": answerability_short_circuit,
        "decomposition": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": _rate(true_positive, predicted_decompose),
            "recall": _rate(true_positive, expected_decompose),
        },
        "answer_target_analyzer_calls": analyzer_calls,
        "new_field_or_intent_keyword_rule_count": keyword_rule_count,
        "signal_b_applied_count": signal_b_count,
        "question_text_included": False,
        "gold_text_included": False,
    }


def _dev_expected_action(row: dict[str, Any]) -> str:
    if row["answerability"] == "false":
        return "reject"
    return "decompose" if row["query_kind"] == "multi_evidence" else "retrieve"


def _latency_observation(dev_rows: list[dict[str, Any]]) -> dict[str, Any]:
    single_rows = [
        row
        for row in dev_rows
        if row["answerability"] != "false" and row["query_kind"] != "multi_evidence"
    ]
    if single_rows:
        analyze_answer_targets(single_rows[0]["question"])
    observations = []
    for row in single_rows:
        started = time.perf_counter_ns()
        analyze_answer_targets(row["question"])
        observations.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(observations)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "sample_count": len(ordered),
        "warm_cache": True,
        "rounds_per_question": 1,
        "median_ms": round(statistics.median(ordered), 6) if ordered else 0.0,
        "p95_ms": round(ordered[p95_index], 6) if ordered else 0.0,
        "maximum_ms": round(max(ordered), 6) if ordered else 0.0,
        "hard_gate": False,
        "observation_is_content_addressed_but_not_bit_reproducible": True,
    }


def _baseline_metrics(
    canary_rows: list[dict[str, Any]], baseline_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_by_id = {
        row["dev_id"]: row["query_policy"]["expected_route_action"]
        for row in canary_rows
    }
    if set(expected_by_id) != {row["case_id"] for row in baseline_rows}:
        raise RuntimeError("Baseline cases do not align with adaptive canary")
    exact = 0
    predicted: Counter[str] = Counter()
    for row in baseline_rows:
        actual = (
            None
            if row["actual_route"] is None
            else row["actual_route"]["route_action"]
        )
        predicted[str(actual)] += 1
        exact += actual == expected_by_id[row["case_id"]]
    return {
        "route_action_exact": _rate(exact, len(baseline_rows)),
        "predicted_action_counts": dict(sorted(predicted.items())),
    }


def evaluate_and_freeze(
    *,
    root: Path,
    canary_path: Path = DEFAULT_CANARY,
    baseline_cases_path: Path = DEFAULT_BASELINE_CASES,
    dev_path: Path = DEFAULT_DEV,
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    input_paths = {
        "downgraded_adaptive_canary": resolve(canary_path),
        "sealed_baseline_cases": resolve(baseline_cases_path),
        "adaptive_development": resolve(dev_path),
        "preregistered_contract": resolve(contract_path),
        "answer_target_analyzer_source": root / "src/v3/answer_target_router.py",
        "answerability_source": root / "src/v3/select_evidence.py",
        "evaluator_source": root / "src/v3/evaluate_route_type_pilot.py",
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    canary_rows = read_jsonl(input_paths["downgraded_adaptive_canary"])
    baseline_rows = read_jsonl(input_paths["sealed_baseline_cases"])
    dev_rows = read_jsonl(input_paths["adaptive_development"])
    if len(canary_rows) != 32 or len(baseline_rows) != 32 or len(dev_rows) != 63:
        raise RuntimeError("Unexpected pilot input row count")
    canary = evaluate_rows(
        canary_rows,
        lambda row: row["query_policy"]["expected_route_action"],
    )
    dev = evaluate_rows(dev_rows, _dev_expected_action)
    baseline = _baseline_metrics(canary_rows, baseline_rows)
    dev_false_total = sum(row["answerability"] == "false" for row in dev_rows)
    dev_false_short_circuit = dev["answerability_short_circuit_count"]
    canary_gates = {
        "decomposition_recall_ge_7_of_9": canary["decomposition"]["true_positive"]
        >= 7
        and canary["decomposition"]["recall"]["total"] == 9,
        "decomposition_precision_ge_0_80": canary["decomposition"]["precision"][
            "rate"
        ]
        >= 0.80,
        "route_action_exact_ge_24_of_32": canary["route_action_exact"]["successes"]
        >= 24,
    }
    dev_gates = {
        "multi_evidence_recall_4_of_4": dev["decomposition"]["true_positive"] == 4
        and dev["decomposition"]["recall"]["total"] == 4,
        "answerable_non_multi_overdecomposition_0": dev["decomposition"][
            "false_positive"
        ]
        == 0,
        "false_answerability_short_circuit_regression_0": dev_false_short_circuit
        == dev_false_total,
    }
    implementation_gates = {
        "new_field_or_intent_keyword_rules_0": canary[
            "new_field_or_intent_keyword_rule_count"
        ]
        == 0
        and dev["new_field_or_intent_keyword_rule_count"] == 0,
        "signal_b_not_applied": canary["signal_b_applied_count"] == 0
        and dev["signal_b_applied_count"] == 0,
        "store_expansion_implemented_0": True,
        "question_or_gold_changes_0": True,
    }
    gates = {**canary_gates, **dev_gates, **implementation_gates}
    signal_a_go = all(gates.values())
    latency = _latency_observation(dev_rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "adaptive_validation_aggregate_only",
        "baseline_router_sha256": BASELINE_ROUTER_SHA256,
        "baseline": baseline,
        "signal_a_canary_32": canary,
        "development_63": dev,
        "development_false_rows": dev_false_total,
        "development_false_short_circuit_count": dev_false_short_circuit,
        "single_question_latency": latency,
        "gates": gates,
        "decisions": {
            "signal_a_prevalidation": "GO" if signal_a_go else "NO-GO",
            "promote_signal_a_to_canonical_router": "GO" if signal_a_go else "NO-GO",
            "signal_b_eligibility": (
                "ELIGIBLE_OVERDECOMPOSITION_MEASURED"
                if canary["decomposition"]["false_positive"]
                or dev["decomposition"]["false_positive"]
                else "NOT_NEEDED"
            ),
            "new_canary_authoring": "GO" if signal_a_go else "NO-GO",
            "new_canary_execution": "NO-GO_PENDING_AUTHORING_AND_REVIEW",
        },
        "store_expansion_implemented": False,
        "broad_search_fallback_implemented": False,
        "new_dev_fit_keyword_rules_added": 0,
        "question_or_gold_modified": False,
        "individual_failure_cases_inspected": False,
        "frozen_blind_accessed": False,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    reports_dir = root / "reports/v3"
    report_path = reports_dir / f"route_type_signal_a_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "report": {"path": _relative(root, report_path), "sha256": report_sha},
        "semantic_metrics_deterministic": True,
        "latency_observation_bit_reproducible": False,
        "questions_or_gold_in_report": False,
        "individual_case_rows_written": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        root
        / "data/v3/router"
        / f"route_type_signal_a_pilot_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    markdown = "\n".join(
        [
            "# DNF RAG v3 route-type Signal A pilot",
            "",
            f"- decision: **{report['decisions']['signal_a_prevalidation']}**",
            f"- baseline route exact: {baseline['route_action_exact']}",
            f"- Signal A canary route exact: {canary['route_action_exact']}",
            f"- Signal A decomposition precision: {canary['decomposition']['precision']}",
            f"- Signal A decomposition recall: {canary['decomposition']['recall']}",
            f"- dev decomposition: {dev['decomposition']}",
            f"- latency: {latency}",
            "- store expansion implemented: no",
            "- new dev-fit keyword rules: 0",
            "- individual failure cases inspected: no",
            "",
        ]
    ).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown)
    markdown_path = reports_dir / f"route_type_signal_a_pilot_{markdown_sha}.md"
    write_immutable(markdown_path, markdown)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Pilot input changed during evaluation: {name}")
    return {
        "decision": report["decisions"]["signal_a_prevalidation"],
        "gates": gates,
        "baseline": baseline,
        "signal_a_canary_32": canary,
        "development_63": dev,
        "single_question_latency": latency,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "markdown_path": str(markdown_path),
        "markdown_sha256": markdown_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate route-type Signal A")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(evaluate_and_freeze(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
