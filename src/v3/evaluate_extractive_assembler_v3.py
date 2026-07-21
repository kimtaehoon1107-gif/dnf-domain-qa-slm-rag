from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import sentence_transformers
import torch
import transformers
from kiwipiepy import __version__ as kiwipiepy_version
from sentence_transformers import CrossEncoder

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
from src.v3.evaluate_extractive_assembler_v2 import (
    _default_kiwi,
    _physical_lines,
    _trim,
    aggregate_v2,
    score_cases_v2,
)
from src.v3.evaluate_requirement_reranker import (
    _model_snapshot_fingerprint,
    _percentile,
    requirement_text,
)
from src.v3.score_evidence_reranker import (
    BATCH_SIZE,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
)


EVALUATOR_VERSION = "mechanical-segment-reranker-assembler-v3.3"
SEGMENT_SCHEMA_VERSION = "nonoverlap-sentence-table-segments-v3.3"
SCORE_SCHEMA_VERSION = "mechanical-segment-reranker-scores-v3.3"
GRID_SCHEMA_VERSION = "mechanical-segment-reranker-grid-v3.3"
CASE_SCHEMA_VERSION = "mechanical-segment-assembler-case-v3.3"
REPORT_SCHEMA_VERSION = "mechanical-segment-assembler-report-v3.3"
MANIFEST_SCHEMA_VERSION = "mechanical-segment-assembler-manifest-v3.3"

THRESHOLDS = (
    0.0,
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.2,
    0.35,
    0.5,
    0.65,
    0.8,
    0.9,
    0.95,
)
K_VALUES = (1, 2, 3)

DEFAULT_CONTRACT = Path("docs/v3/extractive_answer_assembler_v3_pilot.md")
DEFAULT_V2_REPORT = Path(
    "reports/v3/extractive_assembler_v2_pilot_"
    "37fd73e6e9aff7897ebc192c1616bdfbac7a2ba0041c2c7ca58f7ae57f9467f9.json"
)
DEFAULT_V2_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v2_manifest_"
    "6e447f4bd5e39cdd33fe8ef4a34aa83bc55a7b56bf4ce817e05382cd1c6b28bd.json"
)

SEGMENTATION_SPEC = """mechanical-segment-reranker-v3.3
physical-line partition
table row: trimmed line containing at least two pipe delimiters
sentence: kiwipiepy split_into_sents on each other trimmed non-empty line
fallback: exact physical line only if kiwipiepy returns no sentence
paragraph candidates: prohibited
overlap within chunk: prohibited
span_id: sha256(chunk_id NUL start NUL end NUL exact_text), first 24 hex
"""


def _segmentation_sha256() -> str:
    return _sha256_bytes(SEGMENTATION_SPEC.encode("utf-8"))


def segment_chunk_nonoverlap(chunk_id: str, text: str) -> list[dict[str, Any]]:
    kiwi = _default_kiwi()
    boundaries: dict[tuple[int, int], str] = {}

    def add(kind: str, start: int, end: int) -> None:
        start, end = _trim(text, start, end)
        if start >= end:
            return
        key = (start, end)
        previous = boundaries.get(key)
        if previous is not None and previous != kind:
            raise RuntimeError(f"Conflicting segment kind at {chunk_id}:{start}:{end}")
        boundaries[key] = kind

    for line_start, line_end in _physical_lines(text):
        line = text[line_start:line_end]
        if line.count("|") >= 2:
            add("table_row", line_start, line_end)
            continue
        sentences = kiwi.split_into_sents(line)
        if sentences:
            for sentence in sentences:
                add(
                    "sentence",
                    line_start + sentence.start,
                    line_start + sentence.end,
                )
        else:
            add("sentence", line_start, line_end)

    output = []
    previous_end = -1
    for (start, end), kind in sorted(boundaries.items()):
        if start < previous_end:
            raise RuntimeError(f"Overlapping segments in chunk: {chunk_id}")
        previous_end = end
        exact = text[start:end]
        digest = hashlib.sha256(
            f"{chunk_id}\0{start}\0{end}\0{exact}".encode("utf-8")
        ).hexdigest()[:24]
        output.append(
            {
                "span_id": f"span_{digest}",
                "chunk_id": chunk_id,
                "start_char": start,
                "end_char": end,
                "text": exact,
                "kind": kind,
            }
        )
    if text.strip() and not output:
        raise RuntimeError(f"Non-empty chunk produced no segments: {chunk_id}")
    return output


def build_segment_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for case in cases:
        segments = []
        for chunk_id in case["selected_chunk_ids"]:
            segments.extend(
                segment_chunk_nonoverlap(
                    chunk_id, case["selected_chunks"][chunk_id]
                )
            )
        if len({row["span_id"] for row in segments}) != len(segments):
            raise RuntimeError(f"Duplicate span ID in case: {case['case_id']}")
        output.append(
            {
                "segment_schema_version": SEGMENT_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "segments": segments,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def prepare_score_requests(
    cases: list[dict[str, Any]], segment_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    segments_by_id = {row["case_id"]: row["segments"] for row in segment_rows}
    output = []
    for case in cases:
        if not case["evidence_groups"]:
            continue
        chunk_order = {
            chunk_id: index for index, chunk_id in enumerate(case["selected_chunk_ids"])
        }
        segments = sorted(
            segments_by_id[case["case_id"]],
            key=lambda row: (
                chunk_order[row["chunk_id"]],
                row["start_char"],
                row["end_char"],
                row["span_id"],
            ),
        )
        for index, requirement in enumerate(case["requirements"], 1):
            query = requirement_text(requirement)
            output.append(
                {
                    "case_id": case["case_id"],
                    "dataset": case["dataset"],
                    "requirement_index": index,
                    "requirement_id": requirement["requirement_id"],
                    "query": query,
                    "segments": segments,
                    "pairs": [(query, row["text"]) for row in segments],
                }
            )
    return output


def run_segment_reranker(
    cases: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    *,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    requests = prepare_score_requests(cases, segment_rows)
    load_started = time.perf_counter()
    model = CrossEncoder(
        MODEL_NAME,
        revision=MODEL_REVISION,
        max_length=MAX_LENGTH,
        device=device,
        local_files_only=True,
    )
    load_ms = (time.perf_counter() - load_started) * 1000
    latencies = []
    by_case: dict[str, float] = {}
    pair_count = 0
    scored_by_case: dict[str, list[dict[str, Any]]] = {}
    for ordinal, request in enumerate(requests, 1):
        pairs = request.pop("pairs")
        pair_count += len(pairs)
        started = time.perf_counter()
        scores = model.predict(
            pairs,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = (time.perf_counter() - started) * 1000
        values = np.asarray(scores, dtype=np.float64).reshape(-1)
        if len(values) != len(request["segments"]) or not np.isfinite(values).all():
            raise RuntimeError("Segment reranker scores are missing or non-finite")
        scored_by_case.setdefault(request["case_id"], []).append(
            {
                "requirement_index": request["requirement_index"],
                "requirement_id": request["requirement_id"],
                "query": request["query"],
                "candidates": [
                    {**segment, "reranker_score": round(float(score), 8)}
                    for segment, score in zip(
                        request["segments"], values.tolist(), strict=True
                    )
                ],
            }
        )
        latencies.append(elapsed)
        by_case[request["case_id"]] = by_case.get(request["case_id"], 0.0) + elapsed
        if ordinal % 20 == 0 or ordinal == len(requests):
            print(
                f"segment reranker requirements {ordinal}/{len(requests)}",
                file=sys.stderr,
                flush=True,
            )
    score_rows = [
        {
            "score_schema_version": SCORE_SCHEMA_VERSION,
            "case_id": case["case_id"],
            "dataset": case["dataset"],
            "requirements": sorted(
                scored_by_case.get(case["case_id"], []),
                key=lambda row: row["requirement_index"],
            ),
            "not_evaluated_no_gold_evidence_groups": not bool(case["evidence_groups"]),
        }
        for case in cases
    ]
    latency = {
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "model_load_ms": round(load_ms, 3),
        "requirement_call_count": len(latencies),
        "question_count": len(by_case),
        "pair_count": pair_count,
        "requirement_call_median_ms": round(statistics.median(latencies), 3),
        "requirement_call_p95_ms": _percentile(latencies, 0.95),
        "question_sum_median_ms": round(statistics.median(by_case.values()), 3),
        "question_sum_p95_ms": _percentile(list(by_case.values()), 0.95),
        "total_inference_ms": round(sum(latencies), 3),
    }
    model_meta = {
        "name": MODEL_NAME,
        "revision": MODEL_REVISION,
        "max_length": MAX_LENGTH,
        "batch_size": BATCH_SIZE,
        "device": device,
        "temperature": "not_applicable",
        **_model_snapshot_fingerprint(),
        "libraries": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "numpy": np.__version__,
        },
    }
    return sorted(score_rows, key=lambda row: row["case_id"]), latency, model_meta


def _ranked_candidates(requirement: dict[str, Any]) -> list[dict[str, Any]]:
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


def assemble_configuration(
    cases: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    *,
    threshold: float,
    k: int,
) -> list[dict[str, Any]]:
    scores_by_id = {row["case_id"]: row for row in score_rows}
    output = []
    for case in cases:
        requirement_scores = {
            row["requirement_index"]: row
            for row in scores_by_id[case["case_id"]]["requirements"]
        }
        decisions = []
        for index, requirement in enumerate(case["requirements"], 1):
            score = requirement_scores.get(index)
            if score is None:
                decisions.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "status": "unsupported",
                        "spans": [],
                        "model_output_errors": [],
                        "unsupported_message": "문서에서 확인 불가",
                    }
                )
                continue
            selected = [
                row
                for row in _ranked_candidates(score)
                if float(row["reranker_score"]) >= threshold
            ][:k]
            if not selected:
                decisions.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "status": "unsupported",
                        "spans": [],
                        "model_output_errors": [],
                        "unsupported_message": "문서에서 확인 불가",
                    }
                )
                continue
            spans = []
            for row in selected:
                source = case["selected_chunks"][row["chunk_id"]]
                exact = source[row["start_char"] : row["end_char"]]
                if exact != row["text"]:
                    raise RuntimeError(f"Segment offset mismatch: {row['span_id']}")
                spans.append(
                    {
                        "span_id": row["span_id"],
                        "chunk_id": row["chunk_id"],
                        "start_char": row["start_char"],
                        "end_char": row["end_char"],
                        "text": exact,
                        "reranker_score": row["reranker_score"],
                    }
                )
            decisions.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "status": "supported_exact",
                    "spans": spans,
                    "model_output_errors": [],
                    "unsupported_message": None,
                }
            )
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "threshold": threshold,
                "k": k,
                "decisions": decisions,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def gate_v3(metrics: dict[str, Any]) -> dict[str, Any]:
    combined = metrics["combined"]
    dev = metrics["adaptive_dev_63"]
    mean_selected = combined["mean_spans_per_supported_requirement"]
    checks = {
        "dev_evidence_group_hits_exceed_47_of_59": dev[
            "all_human_gold_evidence_group_citation"
        ]["assembler_successes"]
        > 47,
        "strict_evidence_group_regression_zero": combined["comparison"][
            "evidence_group_regression_count"
        ]
        == 0,
        "strict_question_regression_zero": combined["comparison"][
            "all_groups_question_regression_count"
        ]
        == 0,
        "all_groups_question_count_improves": combined["all_groups_cited_questions"][
            "assembler_successes"
        ]
        > combined["all_groups_cited_questions"]["baseline_successes"],
        "mean_selected_segments_at_most_3": mean_selected is not None
        and mean_selected <= 3.0,
        "span_validity_100_percent": combined["span_validity"]["rate"] == 1.0,
        "malformed_zero": combined["malformed_requirement_count"] == 0,
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "pass": passed,
        "decision": "GO_NEW_SEALED_CANARY"
        if passed
        else "NO_GO_MECHANICAL_SEGMENT_RERANKER",
    }


def _config_id(threshold: float, k: int) -> str:
    return f"threshold_{threshold:.3f}_k_{k}"


def evaluate_grid(
    cases: list[dict[str, Any]], score_rows: list[dict[str, Any]]
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    grid_rows = []
    materialized: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]] = {}
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
            gate = gate_v3(metrics)
            config_id = _config_id(threshold, k)
            row = {
                "grid_schema_version": GRID_SCHEMA_VERSION,
                "config_id": config_id,
                "threshold": threshold,
                "k": k,
                "gate": gate,
                "metrics": metrics,
            }
            grid_rows.append(row)
            materialized[config_id] = (assembled, diagnostics, metrics)

    passing = [row for row in grid_rows if row["gate"]["pass"]]

    def mean_or_inf(row: dict[str, Any]) -> float:
        value = row["metrics"]["combined"][
            "mean_spans_per_supported_requirement"
        ]
        return float(value) if value is not None else float("inf")

    if passing:
        chosen = min(
            passing,
            key=lambda row: (
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
        choice_reason = "full_gate_pass_per_prefrozen_lexicographic_objective"
    else:
        chosen = min(
            grid_rows,
            key=lambda row: (
                row["metrics"]["combined"]["comparison"][
                    "evidence_group_regression_count"
                ],
                row["metrics"]["combined"]["comparison"][
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
        choice_reason = "no_gate_pass_no_go_fallback_per_prefrozen_objective"
    assembled, diagnostics, metrics = materialized[chosen["config_id"]]
    selection = {
        "config_id": chosen["config_id"],
        "threshold": chosen["threshold"],
        "k": chosen["k"],
        "choice_reason": choice_reason,
        "passing_configuration_count": len(passing),
        "grid_configuration_count": len(grid_rows),
    }
    return (
        sorted(grid_rows, key=lambda row: row["config_id"]),
        selection,
        assembled,
        diagnostics,
        metrics,
    )


def _markdown(report: dict[str, Any]) -> bytes:
    dev = report["metrics"]["adaptive_dev_63"]
    combined = report["metrics"]["combined"]
    selection = report["selected_configuration"]
    lines = [
        "# Extractive Assembler v3 mechanical segment reranker",
        "",
        f"- Decision: **{report['decision']}**",
        f"- Selected configuration: threshold={selection['threshold']}, K={selection['k']}",
        f"- Passing grid configurations: {selection['passing_configuration_count']}/{selection['grid_configuration_count']}",
        f"- Dev evidence groups: 47/59 -> {dev['all_human_gold_evidence_group_citation']['assembler_successes']}/59",
        f"- Fully cited eligible questions: {combined['all_groups_cited_questions']['baseline_successes']}/{combined['all_groups_cited_questions']['total']} -> {combined['all_groups_cited_questions']['assembler_successes']}/{combined['all_groups_cited_questions']['total']}",
        f"- Mean selected segments: {combined['mean_spans_per_supported_requirement']}",
        f"- Exact slices: {combined['span_validity']['exact_slices']}; invalid: {combined['span_validity']['invalid']}",
        f"- Group improvements/regressions: {combined['comparison']['evidence_group_improvement_count']}/{combined['comparison']['evidence_group_regression_count']}",
        f"- Inference total ms: {report['latency']['total_inference_ms']}",
        "",
        "No LLM or answer-text generation was used. Gold IDs were scoring-only.",
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
        "v2_report": root / DEFAULT_V2_REPORT,
        "v2_manifest": root / DEFAULT_V2_MANIFEST,
        "contract": root / DEFAULT_CONTRACT,
        "model_contract_source": root / "src/v3/score_evidence_reranker.py",
        "stage2_evaluator_source": root / "src/v3/evaluate_requirement_reranker.py",
        "case_builder_source": root / "src/v3/evaluate_extractive_assembler.py",
        "scoring_source": root / "src/v3/evaluate_extractive_assembler_v2.py",
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
    segment_rows = build_segment_rows(cases)
    score_rows, latency, model_meta = run_segment_reranker(
        cases, segment_rows, device=device
    )
    grid_rows, selection, assembled, diagnostics, metrics = evaluate_grid(
        cases, score_rows
    )
    gate_result = gate_v3(metrics)
    v2_report = json.loads(input_paths["v2_report"].read_text(encoding="utf-8"))

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"

    def freeze_jsonl(
        prefix: str, rows: list[dict[str, Any]], key: Any
    ) -> tuple[Path, str]:
        payload = _serialize_jsonl(rows, key)
        digest = _sha256_bytes(payload)
        path = evidence_dir / f"{prefix}_{digest}.jsonl"
        write_immutable(path, payload)
        return path, digest

    segments_path, segments_sha = freeze_jsonl(
        "extractive_assembler_v3_segments", segment_rows, lambda row: row["case_id"]
    )
    scores_path, scores_sha = freeze_jsonl(
        "extractive_assembler_v3_scores", score_rows, lambda row: row["case_id"]
    )
    grid_path, grid_sha = freeze_jsonl(
        "extractive_assembler_v3_grid", grid_rows, lambda row: row["config_id"]
    )
    assembled_path, assembled_sha = freeze_jsonl(
        "extractive_assembler_v3_cases", assembled, lambda row: row["case_id"]
    )
    diagnostics_path, diagnostics_sha = freeze_jsonl(
        "extractive_assembler_v3_diagnostics",
        diagnostics,
        lambda row: row["case_id"],
    )

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_aggregate_32_plus_63",
        "decision": gate_result["decision"],
        "gate": gate_result,
        "selected_configuration": selection,
        "metrics": metrics,
        "latency": latency,
        "v2_reference": {
            "mean_selected_segments": v2_report["metrics"]["combined"][
                "mean_spans_per_supported_requirement"
            ],
            "total_inference_ms": v2_report["latency"]["per_requirement"][
                "total_ms"
            ],
        },
        "segmentation": {
            "version": SEGMENT_SCHEMA_VERSION,
            "spec_sha256": _segmentation_sha256(),
            "kiwipiepy_version": kiwipiepy_version,
            "candidate_count": sum(len(row["segments"]) for row in segment_rows),
            "overlap_count": 0,
            "paragraph_candidates": 0,
        },
        "model": model_meta,
        "tuning_contract": {
            "thresholds": list(THRESHOLDS),
            "k_values": list(K_VALUES),
            "aggregate_only": True,
            "individual_question_tuning": False,
            "grid_fixed_before_segment_scores": True,
            "selection_objective": selection["choice_reason"],
        },
        "scope": {
            "assembler_llm_calls": 0,
            "freeform_generation": False,
            "training": False,
            "new_keyword_rules": False,
            "retrieval_changed": False,
            "stage2_reranker_changed": False,
            "planner_changed": False,
            "entailment_judge": "parked",
            "answerability": "parked",
            "new_canary": False,
            "frozen_blind_accessed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"extractive_assembler_v3_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"extractive_assembler_v3_pilot_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    artifacts = {
        "segments": (segments_path, segments_sha, len(segment_rows)),
        "scores": (scores_path, scores_sha, len(score_rows)),
        "grid": (grid_path, grid_sha, len(grid_rows)),
        "assembled_cases": (assembled_path, assembled_sha, len(assembled)),
        "diagnostics": (diagnostics_path, diagnostics_sha, len(diagnostics)),
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
        "segmentation": report["segmentation"],
        "selected_configuration": selection,
        "artifacts": {
            name: {
                "path": _relative(root, value[0]),
                "sha256": value[1],
                **({"row_count": value[2]} if value[2] is not None else {}),
            }
            for name, value in artifacts.items()
        },
        "decision": gate_result["decision"],
        "gold_available_to_reranker": False,
        "assembler_llm_calls": 0,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"extractive_assembler_v3_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during assembler v3 pilot: {name}")
    return {
        "decision": gate_result["decision"],
        "gate": gate_result,
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
        description="Run the LLM-free mechanical segment reranker assembler pilot"
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
