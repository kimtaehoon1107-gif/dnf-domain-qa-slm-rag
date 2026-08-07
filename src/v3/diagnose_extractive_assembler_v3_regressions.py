from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_extractive_assembler import (
    DEFAULT_CANARY,
    DEFAULT_CANARY_BASELINE_CASES,
    DEFAULT_CANARY_BASELINE_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_DEV_BASELINE_CASES,
    DEFAULT_DEV_BASELINE_MANIFEST,
    DEFAULT_ENUMERATION,
    DEFAULT_RERANK_MANIFEST,
    DEFAULT_RERANK_RESULTS,
    DEFAULT_RERANK_SCORES,
    _git_head,
    _relative,
    _sha256_bytes,
    build_cases,
)
from src.v3.evaluate_extractive_assembler_v2 import aggregate_v2, score_cases_v2
from src.v3.evaluate_extractive_assembler_v3 import (
    THRESHOLDS,
    assemble_configuration,
    build_segment_rows,
    run_segment_reranker,
)


EVALUATOR_VERSION = "assembler-v3-regression-attribution-repair-v3.4"
ATTRIBUTION_SCHEMA_VERSION = "assembler-v3-regression-attribution-v3.4"
SEGMENT_SCHEMA_VERSION = "sentence-table-adjacent-merge-2-3-v3.4"
GRID_SCHEMA_VERSION = "assembler-v3-regression-repair-grid-v3.4"
REPORT_SCHEMA_VERSION = "assembler-v3-regression-repair-report-v3.4"
MANIFEST_SCHEMA_VERSION = "assembler-v3-regression-repair-manifest-v3.4"
K_VALUES = (1, 2, 3, 4, 5, 6)
CURRENT_V3_DEV_HITS = 54
CURRENT_V3_FULLY_CITED_QUESTIONS = 69

DEFAULT_V3_SEGMENTS = Path(
    "data/v3/evidence/extractive_assembler_v3_segments_"
    "1c18bd77771a3d8d773277b7149bbb5faa73fc2d652c3bdf45025277f386a05e.jsonl"
)
DEFAULT_V3_SCORES = Path(
    "data/v3/evidence/extractive_assembler_v3_scores_"
    "1d0199ee1754c84d91342c960e8eb37b54740ecb8ce832f7391f81bcad5fb5f6.jsonl"
)
DEFAULT_V3_DIAGNOSTICS = Path(
    "data/v3/evidence/extractive_assembler_v3_diagnostics_"
    "d894ad603ac49c651fa697c8bdcb282485e047d8a796be2401dac89752bd5458.jsonl"
)
DEFAULT_V3_REPORT = Path(
    "reports/v3/extractive_assembler_v3_pilot_"
    "1a5b26488fb8df5141c1586290119239208e2c2bf655fccdbdaa4222f80615f1.json"
)
DEFAULT_V3_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_manifest_"
    "d2a11898764bbedeb6d6aeb61af30f6f98cdfbbd33c57f7a080ce9ee5a800374.json"
)
DEFAULT_CONTRACT = Path(
    "docs/v3/extractive_assembler_v3_regression_diagnostic.md"
)

MERGE_SPEC = """assembler-v3-regression-repair-v3.4
base: frozen non-overlap sentence and table-row segments
merge windows: every consecutive window of size 2 and 3 within each chunk
gap condition: source text between consecutive segments contains whitespace only
merged text: exact source slice from first.start_char through last.end_char
question-specific merge decisions: prohibited
"""


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _ranked(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        requirement["candidates"],
        key=lambda row: (
            -float(row["reranker_score"]),
            row["chunk_id"],
            int(row["start_char"]),
            int(row["end_char"]),
            row["span_id"],
        ),
    )


def _minimum_covering_window(
    case: dict[str, Any],
    group: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    max_width: int = 3,
) -> dict[str, Any] | None:
    gold = _normalize_ws(str(group.get("evidence_span", "")))
    if not gold:
        return None
    for chunk_id in group["acceptable_chunk_ids"]:
        if chunk_id not in case["selected_chunks"]:
            continue
        source = case["selected_chunks"][chunk_id]
        rows = sorted(
            [row for row in segments if row["chunk_id"] == chunk_id],
            key=lambda row: (row["start_char"], row["end_char"]),
        )
        for width in range(1, max_width + 1):
            for index in range(len(rows) - width + 1):
                window = rows[index : index + width]
                text = source[window[0]["start_char"] : window[-1]["end_char"]]
                if gold in _normalize_ws(text):
                    return {
                        "chunk_id": chunk_id,
                        "width": width,
                        "start_char": window[0]["start_char"],
                        "end_char": window[-1]["end_char"],
                    }
    return None


def attribute_regressions(
    cases: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    *,
    threshold: float = 0.001,
    k: int = 3,
) -> list[dict[str, Any]]:
    cases_by_id = {row["case_id"]: row for row in cases}
    segments_by_id = {row["case_id"]: row["segments"] for row in segment_rows}
    scores_by_id = {row["case_id"]: row for row in score_rows}
    regressions = [
        (row["case_id"], group["group_id"])
        for row in diagnostics
        for group in row["groups"]
        if group["selected_bound"]
        and group["baseline_cited"]
        and not group["assembler_cited"]
    ]
    output = []
    for case_id, group_id in regressions:
        case = cases_by_id[case_id]
        group = next(
            row for row in case["evidence_groups"] if row["group_id"] == group_id
        )
        requirements = case["requirements"]
        acceptable = set(group["acceptable_chunk_ids"])
        selected = set(case["selected_chunk_ids"])
        window = _minimum_covering_window(
            case, group, segments_by_id[case_id], max_width=3
        )
        requirement_ranks = []
        for requirement in scores_by_id[case_id]["requirements"]:
            ranked = _ranked(requirement)
            acceptable_rows = [
                (index + 1, row)
                for index, row in enumerate(ranked)
                if row["chunk_id"] in acceptable
            ]
            answer_rows = [
                (rank, row)
                for rank, row in acceptable_rows
                if _normalize_ws(str(group.get("evidence_span", "")))
                in _normalize_ws(row["text"])
            ]
            requirement_ranks.append(
                {
                    "requirement_index": requirement["requirement_index"],
                    "query": requirement["query"],
                    "best_acceptable_chunk_segment_rank": acceptable_rows[0][0]
                    if acceptable_rows
                    else None,
                    "best_acceptable_chunk_segment_score": acceptable_rows[0][1][
                        "reranker_score"
                    ]
                    if acceptable_rows
                    else None,
                    "best_answer_bearing_segment_rank": answer_rows[0][0]
                    if answer_rows
                    else None,
                    "best_answer_bearing_segment_score": answer_rows[0][1][
                        "reranker_score"
                    ]
                    if answer_rows
                    else None,
                }
            )
        answer_ranks = [
            row["best_answer_bearing_segment_rank"]
            for row in requirement_ranks
            if row["best_answer_bearing_segment_rank"] is not None
        ]
        answer_scores = [
            row["best_answer_bearing_segment_score"]
            for row in requirement_ranks
            if row["best_answer_bearing_segment_score"] is not None
        ]
        if not requirements:
            stage = "ENUM_MISS"
            repair = "planner_track"
        elif window is not None and window["width"] > 1:
            stage = "SEGMENTATION_BOUNDARY"
            repair = f"uniform_adjacent_merge_up_to_{window['width']}"
        elif not (acceptable & selected):
            stage = "SELECTION_BOUND"
            repair = "upstream_stage2_selection_track"
        elif answer_ranks and min(answer_ranks) > k:
            stage = "K_BOUNDARY"
            repair = "aggregate_k_threshold_grid"
        elif answer_ranks and min(answer_ranks) <= k and max(answer_scores) < threshold:
            stage = "THRESHOLD"
            repair = "aggregate_k_threshold_grid"
        elif answer_ranks:
            stage = "QUERY_REPRESENTATION"
            repair = "report_only_planner_query_track"
        else:
            stage = "PER_REQ_VS_WHOLE"
            repair = "report_only_upstream_tradeoff"
        output.append(
            {
                "attribution_schema_version": ATTRIBUTION_SCHEMA_VERSION,
                "case_id": case_id,
                "group_id": group_id,
                "dataset": case["dataset"],
                "primary_stage": stage,
                "repair_route": repair,
                "planner_requirement_count": len(requirements),
                "acceptable_chunk_selected": bool(acceptable & selected),
                "minimum_adjacent_covering_window": window,
                "requirement_rank_diagnostics": requirement_ranks,
                "baseline_cited": True,
                "v3_cited": False,
            }
        )
    return sorted(output, key=lambda row: (row["case_id"], row["group_id"]))


def build_merged_segment_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_rows = build_segment_rows(cases)
    cases_by_id = {row["case_id"]: row for row in cases}
    output = []
    for base_row in base_rows:
        case = cases_by_id[base_row["case_id"]]
        by_chunk: dict[str, list[dict[str, Any]]] = {}
        for segment in base_row["segments"]:
            by_chunk.setdefault(segment["chunk_id"], []).append(segment)
        merged = list(base_row["segments"])
        boundaries = {
            (row["chunk_id"], row["start_char"], row["end_char"])
            for row in merged
        }
        for chunk_id, rows in by_chunk.items():
            rows.sort(key=lambda row: (row["start_char"], row["end_char"]))
            source = case["selected_chunks"][chunk_id]
            for width in (2, 3):
                for index in range(len(rows) - width + 1):
                    window = rows[index : index + width]
                    if any(
                        source[left["end_char"] : right["start_char"]].strip()
                        for left, right in zip(window, window[1:])
                    ):
                        continue
                    start, end = window[0]["start_char"], window[-1]["end_char"]
                    key = (chunk_id, start, end)
                    if key in boundaries:
                        continue
                    exact = source[start:end]
                    digest = hashlib.sha256(
                        f"{chunk_id}\0{start}\0{end}\0{exact}".encode("utf-8")
                    ).hexdigest()[:24]
                    merged.append(
                        {
                            "span_id": f"span_merge_{digest}",
                            "chunk_id": chunk_id,
                            "start_char": start,
                            "end_char": end,
                            "text": exact,
                            "kind": f"adjacent_merge_{width}",
                        }
                    )
                    boundaries.add(key)
        output.append(
            {
                "segment_schema_version": SEGMENT_SCHEMA_VERSION,
                "case_id": base_row["case_id"],
                "segments": sorted(
                    merged,
                    key=lambda row: (
                        case["selected_chunk_ids"].index(row["chunk_id"]),
                        row["start_char"],
                        row["end_char"],
                        row["span_id"],
                    ),
                ),
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def adjusted_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    combined = metrics["combined"]
    dev = metrics["adaptive_dev_63"]
    mean_selected = combined["mean_spans_per_supported_requirement"]
    checks = {
        "dev_hits_at_least_v3_54": dev[
            "all_human_gold_evidence_group_citation"
        ]["assembler_successes"]
        >= CURRENT_V3_DEV_HITS,
        "fully_cited_questions_at_least_v3_69": combined[
            "all_groups_cited_questions"
        ]["assembler_successes"]
        >= CURRENT_V3_FULLY_CITED_QUESTIONS,
        "strict_evidence_group_regression_zero": combined["comparison"][
            "evidence_group_regression_count"
        ]
        == 0,
        "strict_question_regression_zero": combined["comparison"][
            "all_groups_question_regression_count"
        ]
        == 0,
        "mean_selected_segments_at_most_3": mean_selected is not None
        and mean_selected <= 3.0,
        "span_validity_100_percent": combined["span_validity"]["rate"] == 1.0,
        "malformed_zero": combined["malformed_requirement_count"] == 0,
        "assembler_llm_calls_zero": True,
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "pass": passed,
        "decision": "GO_NEW_SEALED_CANARY"
        if passed
        else "NO_GO_STRICT_REGRESSION_REMAINS",
    }


def evaluate_extended_grid(
    cases: list[dict[str, Any]], score_rows: list[dict[str, Any]]
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    grid_rows = []
    materialized = {}
    for threshold in THRESHOLDS:
        for k in K_VALUES:
            assembled = assemble_configuration(
                cases, score_rows, threshold=threshold, k=k
            )
            diagnostics = score_cases_v2(cases, assembled)
            metrics = {
                "combined": aggregate_v2(diagnostics),
                "downgraded_canary_32": aggregate_v2(
                    [
                        row
                        for row in diagnostics
                        if row["dataset"] == "downgraded_canary_32"
                    ]
                ),
                "adaptive_dev_63": aggregate_v2(
                    [
                        row
                        for row in diagnostics
                        if row["dataset"] == "adaptive_dev_63"
                    ]
                ),
            }
            gate = adjusted_gate(metrics)
            config_id = f"threshold_{threshold:.3f}_k_{k}"
            grid_rows.append(
                {
                    "grid_schema_version": GRID_SCHEMA_VERSION,
                    "config_id": config_id,
                    "threshold": threshold,
                    "k": k,
                    "gate": gate,
                    "metrics": metrics,
                }
            )
            materialized[config_id] = (assembled, diagnostics, metrics)
    passing = [row for row in grid_rows if row["gate"]["pass"]]

    def mean_or_inf(row: dict[str, Any]) -> float:
        value = row["metrics"]["combined"][
            "mean_spans_per_supported_requirement"
        ]
        return float(value) if value is not None else float("inf")

    pool = passing or grid_rows
    chosen = min(
        pool,
        key=lambda row: (
            0
            if passing
            else row["metrics"]["combined"]["comparison"][
                "evidence_group_regression_count"
            ],
            0
            if passing
            else row["metrics"]["combined"]["comparison"][
                "all_groups_question_regression_count"
            ],
            -row["metrics"]["adaptive_dev_63"][
                "all_human_gold_evidence_group_citation"
            ]["assembler_successes"],
            -row["metrics"]["combined"]["all_groups_cited_questions"][
                "assembler_successes"
            ],
            mean_or_inf(row),
            row["k"],
            -row["threshold"],
        ),
    )
    assembled, diagnostics, metrics = materialized[chosen["config_id"]]
    selection = {
        "config_id": chosen["config_id"],
        "threshold": chosen["threshold"],
        "k": chosen["k"],
        "passing_configuration_count": len(passing),
        "grid_configuration_count": len(grid_rows),
        "choice_reason": "full_adjusted_gate_pass"
        if passing
        else "no_go_fallback_prefrozen_objective",
    }
    return (
        sorted(grid_rows, key=lambda row: row["config_id"]),
        selection,
        assembled,
        diagnostics,
        metrics,
    )


def _markdown(report: dict[str, Any]) -> bytes:
    combined = report["metrics"]["combined"]
    dev = report["metrics"]["adaptive_dev_63"]
    lines = [
        "# Assembler v3 regression attribution and aggregate repair",
        "",
        f"- Decision: **{report['decision']}**",
        f"- Attribution: {report['attribution_histogram']}",
        f"- K-only repair pass: {report['k_only_diagnostic']['gate_pass']}",
        f"- Selected adjusted configuration: threshold={report['selected_configuration']['threshold']}, K={report['selected_configuration']['k']}",
        f"- Dev evidence groups: {dev['all_human_gold_evidence_group_citation']['assembler_successes']}/59",
        f"- Fully cited questions: {combined['all_groups_cited_questions']['assembler_successes']}/73",
        f"- Group/question regressions: {combined['comparison']['evidence_group_regression_count']}/{combined['comparison']['all_groups_question_regression_count']}",
        f"- Mean selected segments: {combined['mean_spans_per_supported_requirement']}",
        f"- Exact validity: {combined['span_validity']['rate']}",
        "",
        "No individual-question rule, LLM, planner change, retrieval change, or",
        "new canary was used.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    device: str = "cuda",
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "enumeration": root / DEFAULT_ENUMERATION,
        "canary_32": root / DEFAULT_CANARY,
        "dev_63": root / DEFAULT_DEV,
        "reranker_results": root / DEFAULT_RERANK_RESULTS,
        "reranker_scores": root / DEFAULT_RERANK_SCORES,
        "reranker_manifest": root / DEFAULT_RERANK_MANIFEST,
        "dev_baseline_cases": root / DEFAULT_DEV_BASELINE_CASES,
        "dev_baseline_manifest": root / DEFAULT_DEV_BASELINE_MANIFEST,
        "canary_baseline_cases": root / DEFAULT_CANARY_BASELINE_CASES,
        "canary_baseline_manifest": root / DEFAULT_CANARY_BASELINE_MANIFEST,
        "chunks": root / DEFAULT_CHUNKS,
        "v3_segments": root / DEFAULT_V3_SEGMENTS,
        "v3_scores": root / DEFAULT_V3_SCORES,
        "v3_diagnostics": root / DEFAULT_V3_DIAGNOSTICS,
        "v3_report": root / DEFAULT_V3_REPORT,
        "v3_manifest": root / DEFAULT_V3_MANIFEST,
        "contract": root / DEFAULT_CONTRACT,
        "v3_evaluator_source": root / "src/v3/evaluate_extractive_assembler_v3.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    cases = build_cases(
        read_jsonl(input_paths["canary_32"]),
        read_jsonl(input_paths["dev_63"]),
        read_jsonl(input_paths["enumeration"]),
        read_jsonl(input_paths["reranker_results"]),
        read_jsonl(input_paths["reranker_scores"]),
        read_jsonl(input_paths["canary_baseline_cases"]),
        read_jsonl(input_paths["dev_baseline_cases"]),
        read_jsonl(input_paths["chunks"]),
    )
    frozen_segments = read_jsonl(input_paths["v3_segments"])
    frozen_scores = read_jsonl(input_paths["v3_scores"])
    frozen_diagnostics = read_jsonl(input_paths["v3_diagnostics"])
    attribution = attribute_regressions(
        cases, frozen_segments, frozen_scores, frozen_diagnostics
    )
    k_only_grid, k_only_selection, _, _, k_only_metrics = evaluate_extended_grid(
        cases, frozen_scores
    )

    merged_segments = build_merged_segment_rows(cases)
    merged_scores, latency, model_meta = run_segment_reranker(
        cases, merged_segments, device=device
    )
    adjusted_grid, selection, assembled, diagnostics, metrics = evaluate_extended_grid(
        cases, merged_scores
    )
    gate = adjusted_gate(metrics)
    histogram: dict[str, int] = {}
    for row in attribution:
        histogram[row["primary_stage"]] = histogram.get(row["primary_stage"], 0) + 1

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"

    def freeze_jsonl(prefix: str, rows: list[dict[str, Any]], key: Any) -> tuple[Path, str]:
        payload = _serialize_jsonl(rows, key)
        digest = _sha256_bytes(payload)
        path = evidence_dir / f"{prefix}_{digest}.jsonl"
        write_immutable(path, payload)
        return path, digest

    attribution_path, attribution_sha = freeze_jsonl(
        "extractive_assembler_v3_regression_attribution",
        attribution,
        lambda row: (row["case_id"], row["group_id"]),
    )
    k_grid_path, k_grid_sha = freeze_jsonl(
        "extractive_assembler_v3_k_only_grid",
        k_only_grid,
        lambda row: row["config_id"],
    )
    segments_path, segments_sha = freeze_jsonl(
        "extractive_assembler_v3_merged_segments",
        merged_segments,
        lambda row: row["case_id"],
    )
    scores_path, scores_sha = freeze_jsonl(
        "extractive_assembler_v3_merged_scores",
        merged_scores,
        lambda row: row["case_id"],
    )
    grid_path, grid_sha = freeze_jsonl(
        "extractive_assembler_v3_adjusted_grid",
        adjusted_grid,
        lambda row: row["config_id"],
    )
    cases_path, cases_sha = freeze_jsonl(
        "extractive_assembler_v3_adjusted_cases",
        assembled,
        lambda row: row["case_id"],
    )
    diagnostics_path, diagnostics_sha = freeze_jsonl(
        "extractive_assembler_v3_adjusted_diagnostics",
        diagnostics,
        lambda row: row["case_id"],
    )

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_regression_attribution_and_aggregate_repair",
        "decision": gate["decision"],
        "gate": gate,
        "gate_recommendation": "PROCEED_TO_NEW_SEALED_CANARY"
        if gate["pass"]
        else "USER_DECISION_STRICT_ZERO_VS_DOCUMENTED_EXCEPTION",
        "attribution_histogram": dict(sorted(histogram.items())),
        "attribution_count": len(attribution),
        "k_only_diagnostic": {
            "selected_configuration": k_only_selection,
            "gate": adjusted_gate(k_only_metrics),
            "gate_pass": adjusted_gate(k_only_metrics)["pass"],
            "metrics": k_only_metrics,
        },
        "selected_configuration": selection,
        "metrics": metrics,
        "latency": latency,
        "segmentation": {
            "version": SEGMENT_SCHEMA_VERSION,
            "spec_sha256": _sha256_bytes(MERGE_SPEC.encode("utf-8")),
            "base_candidate_count": sum(len(row["segments"]) for row in frozen_segments),
            "adjusted_candidate_count": sum(
                len(row["segments"]) for row in merged_segments
            ),
            "merge_2_count": sum(
                row["kind"] == "adjacent_merge_2"
                for case in merged_segments
                for row in case["segments"]
            ),
            "merge_3_count": sum(
                row["kind"] == "adjacent_merge_3"
                for case in merged_segments
                for row in case["segments"]
            ),
        },
        "model": model_meta,
        "tuning_contract": {
            "thresholds": list(THRESHOLDS),
            "k_values": list(K_VALUES),
            "aggregate_only": True,
            "individual_question_rules": 0,
            "grid_fixed_before_merged_scores": True,
        },
        "scope": {
            "assembler_llm_calls": 0,
            "freeform_generation": False,
            "training": False,
            "planner_changed": False,
            "stage2_reranker_changed": False,
            "retrieval_changed": False,
            "entailment_judge": "parked",
            "answerability": "parked",
            "new_canary": False,
            "frozen_blind_accessed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"extractive_assembler_v3_regression_repair_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"extractive_assembler_v3_regression_repair_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    artifacts = {
        "attribution": (attribution_path, attribution_sha, len(attribution)),
        "k_only_grid": (k_grid_path, k_grid_sha, len(k_only_grid)),
        "merged_segments": (segments_path, segments_sha, len(merged_segments)),
        "merged_scores": (scores_path, scores_sha, len(merged_scores)),
        "adjusted_grid": (grid_path, grid_sha, len(adjusted_grid)),
        "adjusted_cases": (cases_path, cases_sha, len(assembled)),
        "adjusted_diagnostics": (diagnostics_path, diagnostics_sha, len(diagnostics)),
        "report": (report_path, report_sha, None),
        "report_markdown": (markdown_path, markdown_sha, None),
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "model": model_meta,
        "selected_configuration": selection,
        "artifacts": {
            name: {
                "path": _relative(root, value[0]),
                "sha256": value[1],
                **({"row_count": value[2]} if value[2] is not None else {}),
            }
            for name, value in artifacts.items()
        },
        "decision": gate["decision"],
        "gold_available_to_reranker": False,
        "assembler_llm_calls": 0,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"extractive_assembler_v3_regression_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during v3 regression repair: {name}")
    return {
        "decision": gate["decision"],
        "gate": gate,
        "gate_recommendation": report["gate_recommendation"],
        "attribution_histogram": report["attribution_histogram"],
        "k_only_diagnostic": report["k_only_diagnostic"],
        "selected_configuration": selection,
        "metrics": metrics,
        "latency": latency,
        "segmentation": report["segmentation"],
        "model": model_meta,
        "artifacts": {
            name: {"path": str(value[0]), "sha256": value[1]}
            for name, value in artifacts.items()
        },
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose and aggregate-repair the three assembler v3 regressions"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(
        args.root, device=args.device, evaluated_at=args.evaluated_at
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
