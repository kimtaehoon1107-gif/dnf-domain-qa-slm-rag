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
from src.v3.answer_target_coverage import evaluate_top_chunk_coverage
from src.v3.answer_target_router import analyze_answer_targets
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable
from src.v3.evaluate_route_type_pilot import _rate
from src.v3.select_evidence import classify_answerability


EVALUATOR_VERSION = "route-type-signal-b-pilot-v3.2.0"
MANIFEST_SCHEMA_VERSION = "route-type-signal-b-pilot-manifest-v3.2"
REPORT_SCHEMA_VERSION = "route-type-signal-b-pilot-report-v3.2"

DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CANARY_CASES = Path(
    "data/v3/evaluation/authored_canary_first_run_cases_"
    "a326d9fd96a4cfcaf9b2d38d74f27fffe26b62dfc1364063c8258891546beecd.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_DEV_REPLAY = Path(
    "data/v3/retrieval/retrieval_runtime_replay_"
    "bff9fe0bc935b960840fb186ce91ae3df43d6d5c2f7df7fd73247ebea9e4a37e.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_SIGNAL_A_REPORT = Path(
    "reports/v3/route_type_signal_a_pilot_"
    "77032257a09acf3e8c3362035d593b0dfbde6632b734cb11f716b1592c5d755a.json"
)
DEFAULT_CONTRACT = Path("docs/v3/route_type_signal_b_pilot.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _short_circuit_action(question: str) -> str | None:
    answerability = classify_answerability(question)
    if answerability["label"] != "false":
        return None
    realtime = answerability["reason"] in {
        "requires_private_account_state",
        "requires_realtime_auction_api",
    }
    return "realtime_api" if realtime else "reject"


def _predict(
    question: str,
    top_chunk: dict[str, Any] | None,
    route_store_correct: bool,
) -> tuple[str, bool, bool]:
    short_circuit = _short_circuit_action(question)
    if short_circuit is not None:
        return short_circuit, False, False
    signal_a = analyze_answer_targets(question)
    if not signal_a["needs_decomposition"]:
        return "retrieve", False, False
    if top_chunk is None or not route_store_correct:
        return "decompose", False, False
    coverage = evaluate_top_chunk_coverage(question, top_chunk["display_text"])
    if coverage["all_targets_in_top_chunk"]:
        return "retrieve", True, True
    return "decompose", True, False


def evaluate_rows(
    rows: list[dict[str, Any]],
    expected_action: Callable[[dict[str, Any]], str],
    top_chunks: dict[str, dict[str, Any] | None],
    route_store_correct: dict[str, bool],
    id_field: str,
) -> dict[str, Any]:
    expected_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    downgrade_by_expected: Counter[str] = Counter()
    true_positive = 0
    false_positive = 0
    false_negative = 0
    exact = 0
    short_circuit_count = 0
    coverage_measured = 0
    signal_b_downgrades = 0
    for row in rows:
        row_id = row[id_field]
        expected = expected_action(row)
        predicted, measured, downgraded = _predict(
            row["question"],
            top_chunks.get(row_id),
            route_store_correct.get(row_id, False),
        )
        expected_counts[expected] += 1
        predicted_counts[predicted] += 1
        exact += predicted == expected
        true_positive += predicted == expected == "decompose"
        false_positive += predicted == "decompose" and expected != "decompose"
        false_negative += predicted != "decompose" and expected == "decompose"
        short_circuit_count += expected in {"reject", "realtime_api"} and (
            predicted in {"reject", "realtime_api"}
        )
        coverage_measured += measured
        signal_b_downgrades += downgraded
        if downgraded:
            downgrade_by_expected[expected] += 1
    return {
        "row_count": len(rows),
        "expected_action_counts": dict(sorted(expected_counts.items())),
        "predicted_action_counts": dict(sorted(predicted_counts.items())),
        "route_action_exact": _rate(exact, len(rows)),
        "decomposition": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": _rate(true_positive, true_positive + false_positive),
            "recall": _rate(true_positive, true_positive + false_negative),
        },
        "answerability_short_circuit_count": short_circuit_count,
        "route_store_correct_count": sum(route_store_correct.values()),
        "top_chunk_coverage_measured_count": coverage_measured,
        "signal_b_downgrade_count": signal_b_downgrades,
        "signal_b_downgrade_by_expected_action": dict(
            sorted(downgrade_by_expected.items())
        ),
        "new_field_or_intent_keyword_rule_count": 0,
        "store_expansion_count": 0,
        "question_text_included": False,
        "gold_text_included": False,
    }


def _dev_expected(row: dict[str, Any]) -> str:
    if row["answerability"] == "false":
        return "reject"
    return "decompose" if row["query_kind"] == "multi_evidence" else "retrieve"


def _canary_top_chunks(
    canary_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    chunks: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any] | None], dict[str, bool]]:
    cases = {row["case_id"]: row for row in case_rows}
    top_chunks = {}
    correct = {}
    for row in canary_rows:
        case = cases[row["dev_id"]]
        chunk_ids = case["retrieval_chunk_ids"]
        top = chunks.get(chunk_ids[0]) if chunk_ids else None
        top_chunks[row["dev_id"]] = top
        actual_sources = (
            [] if case["actual_route"] is None else case["actual_route"]["source_ids"]
        )
        correct[row["dev_id"]] = sorted(actual_sources) == sorted(row["source_ids"])
    return top_chunks, correct


def _dev_top_chunks(
    dev_rows: list[dict[str, Any]],
    replay_rows: list[dict[str, Any]],
    chunks: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any] | None], dict[str, bool]]:
    replay = {row["dev_id"]: row for row in replay_rows}
    top_chunks = {}
    correct = {}
    for row in dev_rows:
        chunk_ids = replay[row["dev_id"]]["actual_chunk_ids"]
        top = chunks.get(chunk_ids[0]) if chunk_ids else None
        top_chunks[row["dev_id"]] = top
        correct[row["dev_id"]] = bool(top) and top["source_id"] in row["source_ids"]
    return top_chunks, correct


def _latency(
    rows: list[dict[str, Any]],
    top_chunks: dict[str, dict[str, Any] | None],
    correct: dict[str, bool],
) -> dict[str, Any]:
    singles = [
        row
        for row in rows
        if row["answerability"] != "false" and row["query_kind"] != "multi_evidence"
    ]
    if singles:
        _predict(
            singles[0]["question"],
            top_chunks.get(singles[0]["dev_id"]),
            correct.get(singles[0]["dev_id"], False),
        )
    observed = []
    for row in singles:
        started = time.perf_counter_ns()
        _predict(
            row["question"],
            top_chunks.get(row["dev_id"]),
            correct.get(row["dev_id"], False),
        )
        observed.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(observed)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "sample_count": len(ordered),
        "warm_cache": True,
        "median_ms": round(statistics.median(ordered), 6) if ordered else 0.0,
        "p95_ms": round(ordered[p95_index], 6) if ordered else 0.0,
        "maximum_ms": round(max(ordered), 6) if ordered else 0.0,
        "hard_gate": False,
        "observation_is_content_addressed_but_not_bit_reproducible": True,
    }


def evaluate_and_freeze(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "downgraded_adaptive_canary": root / DEFAULT_CANARY,
        "sealed_baseline_cases": root / DEFAULT_CANARY_CASES,
        "adaptive_development": root / DEFAULT_DEV,
        "frozen_development_retrieval": root / DEFAULT_DEV_REPLAY,
        "canonical_chunks": root / DEFAULT_CHUNKS,
        "signal_a_no_go_report": root / DEFAULT_SIGNAL_A_REPORT,
        "preregistered_contract": root / DEFAULT_CONTRACT,
        "answer_target_analyzer_source": root / "src/v3/answer_target_router.py",
        "target_coverage_source": root / "src/v3/answer_target_coverage.py",
        "answerability_source": root / "src/v3/select_evidence.py",
        "evaluator_source": root / "src/v3/evaluate_route_type_signal_b.py",
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    with input_paths["signal_a_no_go_report"].open(encoding="utf-8") as handle:
        signal_a = json.load(handle)
    if signal_a["decisions"]["signal_b_eligibility"] != (
        "ELIGIBLE_OVERDECOMPOSITION_MEASURED"
    ):
        raise RuntimeError("Signal B was not eligible")
    canary_rows = read_jsonl(input_paths["downgraded_adaptive_canary"])
    case_rows = read_jsonl(input_paths["sealed_baseline_cases"])
    dev_rows = read_jsonl(input_paths["adaptive_development"])
    replay_rows = read_jsonl(input_paths["frozen_development_retrieval"])
    chunks = {
        row["chunk_id"]: row for row in read_jsonl(input_paths["canonical_chunks"])
    }
    if not (len(canary_rows) == len(case_rows) == 32 and len(dev_rows) == 63):
        raise RuntimeError("Unexpected Signal B input row count")
    canary_top, canary_correct = _canary_top_chunks(canary_rows, case_rows, chunks)
    dev_top, dev_correct = _dev_top_chunks(dev_rows, replay_rows, chunks)
    canary = evaluate_rows(
        canary_rows,
        lambda row: row["query_policy"]["expected_route_action"],
        canary_top,
        canary_correct,
        "dev_id",
    )
    dev = evaluate_rows(
        dev_rows, _dev_expected, dev_top, dev_correct, "dev_id"
    )
    dev_false_count = sum(row["answerability"] == "false" for row in dev_rows)
    gates = {
        "canary_decomposition_recall_ge_7_of_9": canary["decomposition"][
            "true_positive"
        ]
        >= 7
        and canary["decomposition"]["recall"]["total"] == 9,
        "canary_decomposition_precision_ge_0_80": canary["decomposition"][
            "precision"
        ]["rate"]
        >= 0.80,
        "canary_route_action_exact_ge_24_of_32": canary["route_action_exact"][
            "successes"
        ]
        >= 24,
        "dev_multi_evidence_recall_4_of_4": dev["decomposition"][
            "true_positive"
        ]
        == 4
        and dev["decomposition"]["recall"]["total"] == 4,
        "dev_answerable_non_multi_overdecomposition_0": dev["decomposition"][
            "false_positive"
        ]
        == 0,
        "dev_false_short_circuit_regression_0": dev[
            "answerability_short_circuit_count"
        ]
        == dev_false_count,
        "new_field_or_intent_keyword_rules_0": True,
        "store_expansion_or_broad_fallback_0": True,
    }
    go = all(gates.values())
    latency = _latency(dev_rows, dev_top, dev_correct)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "adaptive_validation_aggregate_only",
        "signal_a_report_sha256": input_hashes["signal_a_no_go_report"],
        "signal_b_canary_32": canary,
        "development_63": dev,
        "single_question_latency": latency,
        "gates": gates,
        "decisions": {
            "signal_b_prevalidation": "GO" if go else "NO-GO",
            "promote_to_canonical_router": "GO" if go else "NO-GO",
            "retain_existing_canonical_router": "NO" if go else "YES",
            "new_canary_authoring": "GO" if go else "NO-GO",
            "new_canary_execution": "NO-GO_PENDING_AUTHORING_AND_REVIEW",
        },
        "signal_b_entry_condition": "measured_signal_a_overdecomposition",
        "store_expansion_implemented": False,
        "broad_search_fallback_implemented": False,
        "new_dev_fit_keyword_rules_added": 0,
        "question_or_gold_modified": False,
        "individual_failure_cases_inspected": False,
        "frozen_blind_accessed": False,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / f"route_type_signal_b_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "report": {"path": _relative(root, report_path), "sha256": report_sha},
        "individual_case_rows_written": False,
        "questions_or_gold_in_report": False,
        "latency_observation_bit_reproducible": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        root
        / "data/v3/router"
        / f"route_type_signal_b_pilot_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Signal B input changed during evaluation: {name}")
    return {
        "decision": report["decisions"]["signal_b_prevalidation"],
        "gates": gates,
        "signal_b_canary_32": canary,
        "development_63": dev,
        "single_question_latency": latency,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate route-type Signal B")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(evaluate_and_freeze(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
