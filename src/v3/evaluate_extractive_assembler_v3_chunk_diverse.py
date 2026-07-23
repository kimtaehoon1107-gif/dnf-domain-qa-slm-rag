from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.diagnose_extractive_assembler_v3_regressions import adjusted_gate
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
from src.v3.evaluate_extractive_assembler_v3 import THRESHOLDS
from src.v3.requirement_value_shape import (
    detect_value_shapes,
    normalize_expected_value_shape,
)


EVALUATOR_VERSION = "mechanical-chunk-diverse-assembler-v3.5"
GRID_SCHEMA_VERSION = "mechanical-chunk-diverse-grid-v3.5"
CASE_SCHEMA_VERSION = "mechanical-chunk-diverse-case-v3.5"
REPORT_SCHEMA_VERSION = "mechanical-chunk-diverse-report-v3.5"
MANIFEST_SCHEMA_VERSION = "mechanical-chunk-diverse-manifest-v3.5"
K_VALUES = (1, 2, 3)

DEFAULT_V3_SCORES = Path(
    "data/v3/evidence/extractive_assembler_v3_scores_"
    "1d0199ee1754c84d91342c960e8eb37b54740ecb8ce832f7391f81bcad5fb5f6.jsonl"
)
DEFAULT_V3_REPORT = Path(
    "reports/v3/extractive_assembler_v3_pilot_"
    "1a5b26488fb8df5141c1586290119239208e2c2bf655fccdbdaa4222f80615f1.json"
)
DEFAULT_V3_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_manifest_"
    "d2a11898764bbedeb6d6aeb61af30f6f98cdfbbd33c57f7a080ce9ee5a800374.json"
)
DEFAULT_ATTRIBUTION = Path(
    "data/v3/evidence/extractive_assembler_v3_regression_attribution_"
    "92f761213eaeaff436b5c3659bdefe6d5ad3e5fa6fc662caeba6d466a2e212ce.jsonl"
)
DEFAULT_FAILED_REPAIR_REPORT = Path(
    "reports/v3/extractive_assembler_v3_regression_repair_"
    "2e31c534d3d84ec2f83afb481df4bd1502662a45607e96161a0e69551d95b89e.json"
)
DEFAULT_FAILED_REPAIR_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_regression_manifest_"
    "80378257ef66bfd16103cbff410f64fa1bac794ff6d2c6a85e09f237b51f11b9.json"
)
DEFAULT_CONTRACT = Path(
    "docs/v3/extractive_assembler_v3_chunk_diverse_repair.md"
)


def _ranked(
    score: dict[str, Any], *, expected_kind: str | None = None
) -> list[dict[str, Any]]:
    """Rank candidates by reranker score, optionally floating value-bearing spans first.

    ``expected_kind`` of None reproduces the score-only order exactly. When set, a
    candidate whose text carries the requirement's value shape outranks one that does
    not, so the shape contract selects evidence instead of only rejecting it later.

    Adding a subject-similarity tie-break was measured twice and reverted both times
    (regex matcher 50.0% -> 44.2%, Kiwi particle-stripped 50.0% -> 42.9% gold-value
    accuracy). The cause is structural, not matcher quality: the correct span often
    never names the subject at all -- "| 상점판매가격 | 4,000만 골드 |" carries the value
    while the product name sits in another cell -- so ranking by subject presence
    systematically demotes correct evidence. Binding by table structure, not by text
    similarity, is the open path.
    """

    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        missing_value = (
            0
            if expected_kind is None
            or expected_kind in detect_value_shapes(str(row.get("text") or ""))
            else 1
        )
        return (
            missing_value,
            -float(row["reranker_score"]),
            row["chunk_id"],
            int(row["start_char"]),
            int(row["end_char"]),
            row["span_id"],
        )

    return sorted(score["candidates"], key=sort_key)


def assemble_chunk_diverse_configuration(
    cases: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    *,
    threshold: float,
    k: int,
    value_first: bool = False,
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
            expected_kind = (
                normalize_expected_value_shape(requirement)["expected_kind"]
                if value_first
                else None
            )
            selected = []
            seen_chunks: set[str] = set()
            for candidate in (
                _ranked(score, expected_kind=expected_kind)
                if score is not None
                else []
            ):
                if float(candidate["reranker_score"]) < threshold:
                    continue
                if candidate["chunk_id"] in seen_chunks:
                    continue
                seen_chunks.add(candidate["chunk_id"])
                selected.append(candidate)
                if len(selected) == k:
                    break
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
            for candidate in selected:
                source = case["selected_chunks"][candidate["chunk_id"]]
                exact = source[candidate["start_char"] : candidate["end_char"]]
                if exact != candidate["text"]:
                    raise RuntimeError(
                        f"Segment offset mismatch: {candidate['span_id']}"
                    )
                spans.append(
                    {
                        "span_id": candidate["span_id"],
                        "chunk_id": candidate["chunk_id"],
                        "start_char": candidate["start_char"],
                        "end_char": candidate["end_char"],
                        "text": exact,
                        "reranker_score": candidate["reranker_score"],
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
                "selection_strategy": "value_first_top_k_distinct_chunks_per_requirement"
                if value_first
                else "top_k_distinct_chunks_per_requirement",
                "decisions": decisions,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def _metrics(
    cases: list[dict[str, Any]], assembled: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics = score_cases_v2(cases, assembled)
    return diagnostics, {
        "combined": aggregate_v2(diagnostics),
        "downgraded_canary_32": aggregate_v2(
            [
                row
                for row in diagnostics
                if row["dataset"] == "downgraded_canary_32"
            ]
        ),
        "adaptive_dev_63": aggregate_v2(
            [row for row in diagnostics if row["dataset"] == "adaptive_dev_63"]
        ),
    }


def evaluate_chunk_diverse_grid(
    cases: list[dict[str, Any]], score_rows: list[dict[str, Any]]
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    grid = []
    materialized = {}
    for threshold in THRESHOLDS:
        for k in K_VALUES:
            assembled = assemble_chunk_diverse_configuration(
                cases, score_rows, threshold=threshold, k=k
            )
            diagnostics, metrics = _metrics(cases, assembled)
            gate = adjusted_gate(metrics)
            config_id = f"threshold_{threshold:.3f}_k_{k}_distinct_chunks"
            grid.append(
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
    passing = [row for row in grid if row["gate"]["pass"]]

    def mean_selected(row: dict[str, Any]) -> float:
        value = row["metrics"]["combined"][
            "mean_spans_per_supported_requirement"
        ]
        return float(value) if value is not None else float("inf")

    pool = passing or grid
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
            mean_selected(row),
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
        "grid_configuration_count": len(grid),
        "choice_reason": "full_adjusted_gate_pass"
        if passing
        else "no_go_fallback_prefrozen_objective",
    }
    return (
        sorted(grid, key=lambda row: row["config_id"]),
        selection,
        assembled,
        diagnostics,
        metrics,
    )


def _markdown(report: dict[str, Any]) -> bytes:
    combined = report["metrics"]["combined"]
    dev = report["metrics"]["adaptive_dev_63"]
    canary = report["metrics"]["downgraded_canary_32"]
    lines = [
        "# Assembler v3 chunk-diverse aggregate repair",
        "",
        f"- Decision: **{report['decision']}**",
        f"- Attribution: {report['attribution_histogram']}",
        f"- Configuration: threshold={report['selected_configuration']['threshold']}, K={report['selected_configuration']['k']}",
        f"- Adaptive-dev evidence groups: {dev['all_human_gold_evidence_group_citation']['assembler_successes']}/59",
        f"- Fully cited eligible questions: {combined['all_groups_cited_questions']['assembler_successes']}/73",
        f"- Group/question regressions: {combined['comparison']['evidence_group_regression_count']}/{combined['comparison']['all_groups_question_regression_count']}",
        f"- Downgraded-canary regressions: {canary['comparison']['evidence_group_regression_count']}/{canary['comparison']['all_groups_question_regression_count']}",
        f"- Mean selected segments: {combined['mean_spans_per_supported_requirement']}",
        f"- Exact validity: {combined['span_validity']['rate']}",
        "",
        "This is a development-only GO to a new sealed canary, not runtime or",
        "canonical promotion. No LLM or individual-question rule was used.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path, *, evaluated_at: str | None = None
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
        "v3_scores": root / DEFAULT_V3_SCORES,
        "v3_report": root / DEFAULT_V3_REPORT,
        "v3_manifest": root / DEFAULT_V3_MANIFEST,
        "regression_attribution": root / DEFAULT_ATTRIBUTION,
        "failed_repair_report": root / DEFAULT_FAILED_REPAIR_REPORT,
        "failed_repair_manifest": root / DEFAULT_FAILED_REPAIR_MANIFEST,
        "contract": root / DEFAULT_CONTRACT,
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
    scores = read_jsonl(input_paths["v3_scores"])
    grid, selection, assembled, diagnostics, metrics = evaluate_chunk_diverse_grid(
        cases, scores
    )
    gate = adjusted_gate(metrics)
    attribution = read_jsonl(input_paths["regression_attribution"])
    histogram: dict[str, int] = {}
    for row in attribution:
        stage = row["primary_stage"]
        histogram[stage] = histogram.get(stage, 0) + 1
    original_report = json.loads(input_paths["v3_report"].read_text(encoding="utf-8"))
    failed_report = json.loads(
        input_paths["failed_repair_report"].read_text(encoding="utf-8")
    )

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

    grid_path, grid_sha = freeze_jsonl(
        "extractive_assembler_v3_chunk_diverse_grid",
        grid,
        lambda row: row["config_id"],
    )
    cases_path, cases_sha = freeze_jsonl(
        "extractive_assembler_v3_chunk_diverse_cases",
        assembled,
        lambda row: row["case_id"],
    )
    diagnostics_path, diagnostics_sha = freeze_jsonl(
        "extractive_assembler_v3_chunk_diverse_diagnostics",
        diagnostics,
        lambda row: row["case_id"],
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_chunk_diverse_aggregate_repair",
        "decision": gate["decision"],
        "gate": gate,
        "gate_recommendation": "PROCEED_TO_NEW_SEALED_CANARY"
        if gate["pass"]
        else "USER_DECISION_STRICT_ZERO_VS_DOCUMENTED_EXCEPTION",
        "attribution_histogram": dict(sorted(histogram.items())),
        "selected_configuration": selection,
        "metrics": metrics,
        "selection_strategy": {
            "name": "top_k_distinct_chunks_per_requirement",
            "max_segments_per_chunk_per_requirement": 1,
            "uses_original_v3_scores": True,
            "uses_gold_at_runtime": False,
        },
        "prior_attempts": {
            "original_v3_decision": original_report["decision"],
            "k_only_gate_pass": failed_report["k_only_diagnostic"]["gate_pass"],
            "uniform_merge_decision": failed_report["decision"],
            "uniform_merge_selected_configuration": failed_report[
                "selected_configuration"
            ],
            "uniform_merge_metrics": failed_report["metrics"],
        },
        "model": original_report["model"],
        "latency": {
            "new_model_inference_calls": 0,
            "selection_only": True,
            "source_score_latency": original_report["latency"],
        },
        "tuning_contract": {
            "thresholds": list(THRESHOLDS),
            "k_values": list(K_VALUES),
            "aggregate_only": True,
            "individual_question_rules": 0,
            "adaptive_development_adjustment": True,
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
    report_path = reports_dir / f"extractive_assembler_v3_chunk_diverse_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"extractive_assembler_v3_chunk_diverse_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    artifacts = {
        "grid": (grid_path, grid_sha, len(grid)),
        "cases": (cases_path, cases_sha, len(assembled)),
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
        "model": original_report["model"],
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
        "gold_available_to_selector": False,
        "assembler_llm_calls": 0,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"extractive_assembler_v3_chunk_diverse_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during chunk-diverse repair: {name}")
    return {
        "decision": gate["decision"],
        "gate": gate,
        "gate_recommendation": report["gate_recommendation"],
        "attribution_histogram": report["attribution_histogram"],
        "selected_configuration": selection,
        "metrics": metrics,
        "artifacts": {
            name: {"path": str(value[0]), "sha256": value[1]}
            for name, value in artifacts.items()
        },
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the aggregate chunk-diverse assembler-v3 repair"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(args.root, evaluated_at=args.evaluated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
