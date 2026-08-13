from __future__ import annotations

import argparse
import hashlib
import json
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
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_question_partial_fallback_ab import _fallback_metrics, _ratio
from src.v3.evaluate_question_partial_hybrid_ab import _group_observation
from src.v3.evaluate_question_partial_context_ab import DEFAULT_Q2_CASES
from src.v3.evaluate_requirement_retrieval_ab import (
    ASSEMBLER_K,
    ASSEMBLER_THRESHOLD,
    DEFAULT_ASSEMBLER_CASES,
)
from src.v3.evaluate_router_backbone_ab import _score_arm, simulate_arm
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
)
from src.v3.mixed_answerability_structure import classify_answerability_v3_2
from src.v3.requirement_value_shape import apply_value_shape_veto

EVALUATOR_VERSION = "bounded-candidate-source-fallback-ab-v3.2.0"
CASE_SCHEMA_VERSION = "bounded-candidate-source-fallback-ab-case-v3.2"
REPORT_SCHEMA_VERSION = "bounded-candidate-source-fallback-ab-report-v3.2"
MANIFEST_SCHEMA_VERSION = "bounded-candidate-source-fallback-ab-manifest-v3.2"

DEFAULT_Q3_CASES = Path(
    "data/v3/evidence/question_partial_context_ab_cases_"
    "7ad2c3b70d7cba22d8e04ddc6ac0ea5f20bfa8072fc55dcde1d3d17c188a6c79.jsonl"
)
DEFAULT_SEGMENT_SCORES = Path(
    "data/v3/evidence/federated_retrieval_ab_segment_scores_"
    "d06152692e3fafa04f72de4e3a87b4fffbc18b324154f4486a6c4db11f853f41.jsonl"
)
DEFAULT_DEV_RUNTIME = Path(
    "data/v3/runtime/unified_runtime_cases_"
    "f28e2fbfb768c901dc4f1079f262252d645a74c7e4ee494180c2879e528f7789.jsonl"
)
DEFAULT_CANARY_RUNTIME = Path(
    "data/v3/evaluation/authored_canary_first_run_cases_"
    "a326d9fd96a4cfcaf9b2d38d74f27fffe26b62dfc1364063c8258891546beecd.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/bounded_candidate_source_fallback_ab.md")
SOURCE_EXPANSION_LIMIT = 2


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _route_map(
    dev_runtime_rows: list[dict[str, Any]], canary_runtime_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    output = {row["case_id"]: row["route"] for row in dev_runtime_rows}
    output.update({row["case_id"]: row["actual_route"] for row in canary_runtime_rows})
    return output


def enrich_assembler_cases(
    assembler_rows: list[dict[str, Any]], enumeration_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    enumerations = {row["case_id"]: row["requirements"] for row in enumeration_rows}
    if set(enumerations) != {row["case_id"] for row in assembler_rows}:
        raise RuntimeError("Assembler and enumeration case IDs differ")
    return [{**row, "requirements": enumerations[row["case_id"]]} for row in assembler_rows]


def bounded_sources(route: dict[str, Any]) -> list[str]:
    output = list(route["source_ids"])
    for source_id in route["routing_signals"]["candidate_sources"][:SOURCE_EXPANSION_LIMIT]:
        if source_id not in output:
            output.append(source_id)
    return output


def _shape_audit(
    requirements: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    audits = []
    supported_after_veto = 0
    for requirement, decision in zip(requirements, decisions, strict=True):
        checked, audit = apply_value_shape_veto(requirement, decision)
        supported_after_veto += checked["status"] == "supported_exact"
        audits.append(audit)
    return {
        "supported_after_veto": supported_after_veto,
        "veto_count": sum(row["vetoed"] for row in audits),
        "requirements": audits,
    }


def build_bounded_fallback_inputs(
    *,
    assembler_cases: list[dict[str, Any]],
    segment_score_rows: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    global_scores = {
        row["case_id"]: row
        for row in segment_score_rows
        if row["retrieval_arm"] == "federated_global"
    }
    cases = []
    scores = []
    for source in assembler_cases:
        case_id = source["case_id"]
        route = routes[case_id]
        allowed = set(bounded_sources(route)) if route["route_action"] == "retrieve" else set()
        score_source = global_scores[case_id]
        requirement_scores = []
        selected_ids: list[str] = []
        seen: set[str] = set()
        for requirement_position, requirement in enumerate(
            score_source["requirements"]
        ):
            candidates = [
                row
                for row in requirement["candidates"]
                if chunks_by_id[row["chunk_id"]]["source_id"] in allowed
            ]
            seen_spans = {row["span_id"] for row in candidates}
            baseline_decision = source["decisions"][requirement_position]
            for span in baseline_decision.get("spans", []):
                if span["span_id"] in seen_spans:
                    continue
                candidates.append({**span, "kind": "frozen_baseline_span"})
                seen_spans.add(span["span_id"])
            for candidate in candidates:
                chunk_id = candidate["chunk_id"]
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    selected_ids.append(chunk_id)
            requirement_scores.append({**requirement, "candidates": candidates})
        cases.append(
            {
                **source,
                "selected_chunk_ids": selected_ids,
                "selected_chunks": {
                    chunk_id: chunks_by_id[chunk_id]["display_text"]
                    for chunk_id in selected_ids
                },
                "bounded_source_ids": sorted(allowed),
            }
        )
        scores.append({**score_source, "requirements": requirement_scores})
    return cases, scores


def _decisions_exact(
    decisions: list[dict[str, Any]], chunks_by_id: dict[str, dict[str, Any]]
) -> bool:
    for decision in decisions:
        for span in decision.get("spans", []):
            text = chunks_by_id[span["chunk_id"]]["display_text"]
            if text[span["start_char"] : span["end_char"]] != span["text"]:
                return False
    return True


def build_q4_rows(
    *,
    ground_truth_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    q3_rows: list[dict[str, Any]],
    assembler_cases: list[dict[str, Any]],
    fallback_assembler_rows: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    truth = {row["case_id"]: row for row in ground_truth_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    q3 = {row["case_id"]: row for row in q3_rows}
    baseline = {row["case_id"]: row for row in assembler_cases}
    fallback = {row["case_id"]: row for row in fallback_assembler_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    chunk_to_parent = {
        row["chunk_id"]: row["parent_document_id"] for row in chunks
    }
    expected = set(truth)
    if not (expected == set(evaluations) == set(q3) == set(baseline) == set(fallback)):
        raise RuntimeError("Q4 joins do not cover identical 95 case IDs")

    output = []
    for case_id in sorted(expected):
        requirements = baseline[case_id]["requirements"]
        baseline_decisions = baseline[case_id]["decisions"]
        fallback_decisions = fallback[case_id]["decisions"]
        before = _shape_audit(requirements, baseline_decisions)
        after = _shape_audit(requirements, fallback_decisions)
        route = routes[case_id]
        triggered = route["route_action"] == "retrieve" and before["veto_count"] > 0
        committed = bool(
            triggered
            and after["supported_after_veto"] > before["supported_after_veto"]
        )
        decisions = fallback_decisions if committed else baseline_decisions
        simulated = simulate_arm(
            placement="arm0",
            question=evaluations[case_id]["question"],
            assembler_decisions=decisions,
            classifier_predictions=[],
            chunk_to_parent=chunk_to_parent,
        )
        answerability = classify_answerability_v3_2(evaluations[case_id]["question"])
        profile = truth[case_id]["answerability_profile"]
        mixed_metrics = q3[case_id]["arm_q3_mixed_metrics"]
        observation = q3[case_id]["arm_q3_observation"]
        if profile == "mixed" and committed:
            cited_ids = sorted(
                {
                    span["chunk_id"]
                    for decision in decisions
                    if decision["status"] == "supported_exact"
                    for span in decision["spans"]
                }
            )
            claims = [
                {
                    "citation_chunk_id": chunk_id,
                    "claim_text": chunks_by_id[chunk_id]["display_text"],
                }
                for chunk_id in cited_ids
            ]
            observation = _group_observation(
                claims=claims,
                evidence_groups=evaluations[case_id]["evidence_groups"],
                chunks_by_id=chunks_by_id,
                source="bounded_candidate_source_fallback_context",
                partial_safety_contract=answerability["label"] == "partial",
                verified=_decisions_exact(decisions, chunks_by_id),
            )
            mixed_metrics = _fallback_metrics(observation)
        docs_score = None
        if profile == "docs_only":
            docs_score = _score_arm(
                simulated,
                target="answerable_docs",
                evidence_groups=evaluations[case_id]["evidence_groups"],
                expected_docs_flags=[True] * len(decisions),
                baseline_supported_indices=set(),
            )
        temporal_violations = []
        baseline_chunk_ids = {
            span["chunk_id"]
            for decision in baseline_decisions
            for span in decision.get("spans", [])
        }
        if committed:
            for decision in decisions:
                for span in decision.get("spans", []):
                    if span["chunk_id"] in baseline_chunk_ids:
                        continue
                    chunk = chunks_by_id[span["chunk_id"]]
                    default_denied = bool(
                        route["default_exposure_only"]
                        and not chunk["default_exposure"]
                    )
                    status_denied = chunk["status"] not in set(route["allowed_statuses"])
                    if default_denied or status_denied:
                        temporal_violations.append(span["chunk_id"])
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": truth[case_id]["dataset"],
                "answerability_profile": profile,
                "answerability_signal": answerability,
                "route_source_ids": route["source_ids"],
                "bounded_source_ids": bounded_sources(route),
                "fallback_triggered": triggered,
                "fallback_committed": committed,
                "baseline_shape_audit": before,
                "fallback_shape_audit": after,
                "selected_chunk_ids": simulated["cited_chunk_ids"],
                "q3_mixed_metrics": q3[case_id]["arm_q3_mixed_metrics"],
                "q4_mixed_metrics": mixed_metrics,
                "q4_mixed_observation": observation,
                "arm0_score": q3[case_id]["arm0_score"],
                "q4_docs_score": docs_score,
                "exact_slices": _decisions_exact(decisions, chunks_by_id),
                "temporal_violation_chunk_ids": sorted(set(temporal_violations)),
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_trigger_or_commit": False,
                "new_domain_keyword_rules": 0,
            }
        )
    return output


def _mixed_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return {
        field: _ratio(sum(row[key][field] for row in rows), len(rows))
        for field in (
            "correct_mixed_partial",
            "correct_mixed_partial_span_strict",
            "mixed_overclaim",
            "mixed_missing_evidence",
        )
    }


def summarize_q4(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mixed = [row for row in rows if row["answerability_profile"] == "mixed"]
    docs = [row for row in rows if row["answerability_profile"] == "docs_only"]
    q3 = _mixed_summary(mixed, "q3_mixed_metrics")
    q4 = _mixed_summary(mixed, "q4_mixed_metrics")
    docs_grounded = sum(row["q4_docs_score"]["grounded_answer"] for row in docs)
    baseline_grounded_ids = {
        row["case_id"] for row in docs if row["arm0_score"]["grounded_answer"]
    }
    q4_grounded_ids = {
        row["case_id"] for row in docs if row["q4_docs_score"]["grounded_answer"]
    }
    baseline_false = {
        row["case_id"] for row in docs if row["arm0_score"]["false_full_answer"]
    }
    q4_false = {
        row["case_id"] for row in docs if row["q4_docs_score"]["false_full_answer"]
    }
    committed = [row for row in rows if row["fallback_committed"]]
    violations = sorted(
        {
            chunk_id
            for row in rows
            for chunk_id in row["temporal_violation_chunk_ids"]
        }
    )
    checks = {
        "mixed_span_strict_improved_over_12_of_13": (
            q4["correct_mixed_partial_span_strict"]["successes"] > 12
        ),
        "mixed_overclaim_zero": q4["mixed_overclaim"]["successes"] == 0,
        "docs_grounded_at_least_61_of_69": docs_grounded >= 61,
        "docs_grounded_regression_zero": not (baseline_grounded_ids - q4_grounded_ids),
        "new_false_full_zero": not (q4_false - baseline_false),
        "exact_slices_all": all(row["exact_slices"] for row in rows),
        "temporal_violation_zero": not violations,
        "reject_11_of_11_unchanged": sum(row["arm0_score"]["reject_correct"] for row in rows) == 11,
        "realtime_2_of_2_unchanged": sum(row["arm0_score"]["realtime_safe_abstain"] for row in rows) == 2,
    }
    return {
        "arm_q3_mixed": q3,
        "arm_q4_mixed": q4,
        "docs_only": {
            "grounded": _ratio(docs_grounded, len(docs)),
            "grounded_regression_case_ids": sorted(baseline_grounded_ids - q4_grounded_ids),
            "grounded_improvement_case_ids": sorted(q4_grounded_ids - baseline_grounded_ids),
            "false_full": _ratio(len(q4_false), len(docs)),
            "new_false_full_case_ids": sorted(q4_false - baseline_false),
        },
        "fallback": {
            "triggered_count": sum(row["fallback_triggered"] for row in rows),
            "committed_count": len(committed),
            "committed_case_ids": [row["case_id"] for row in committed],
            "source_expansion_limit": SOURCE_EXPANSION_LIMIT,
        },
        "temporal_violation_chunk_ids": violations,
        "strict_gate_checks": checks,
        "strict_gate_passed": all(checks.values()),
        "decision": "DEVELOPMENT_GO_NEW_AUTHORED_VALIDATION"
        if all(checks.values())
        else "DEVELOPMENT_NO_GO",
    }


def _render_markdown(report: dict[str, Any], rows: list[dict[str, Any]]) -> bytes:
    result = report["result"]
    q3 = result["arm_q3_mixed"]
    q4 = result["arm_q4_mixed"]
    lines = [
        "# Bounded candidate-source fallback A/B",
        "",
        "Development-only; no runtime/canonical promotion.",
        "",
        "| Metric | Q3 | Q4 |",
        "|---|---:|---:|",
        f"| Mixed correct partial | {q3['correct_mixed_partial']['successes']}/13 | {q4['correct_mixed_partial']['successes']}/13 |",
        f"| Mixed span-strict | {q3['correct_mixed_partial_span_strict']['successes']}/13 | {q4['correct_mixed_partial_span_strict']['successes']}/13 |",
        f"| Mixed overclaim | {q3['mixed_overclaim']['successes']}/13 | {q4['mixed_overclaim']['successes']}/13 |",
        f"| Docs grounded | 61/69 | {result['docs_only']['grounded']['successes']}/69 |",
        f"| Docs false-full | baseline | {result['docs_only']['false_full']['successes']}/69 |",
        "",
        f"Triggered {result['fallback']['triggered_count']} cases; committed "
        f"{result['fallback']['committed_count']}. Decision: **{result['decision']}**.",
        "",
        "## Committed cases",
        "",
    ]
    for row in rows:
        if not row["fallback_committed"]:
            continue
        lines.append(
            f"- `{row['case_id']}`: `{row['route_source_ids']}` → `{row['bounded_source_ids']}`, "
            f"shape {row['baseline_shape_audit']['supported_after_veto']}→"
            f"{row['fallback_shape_audit']['supported_after_veto']}"
        )
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path, *, artifact_root: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    inputs = {
        "ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "q3_cases": root / DEFAULT_Q3_CASES,
        "frozen_assembler_cases": root / DEFAULT_ASSEMBLER_CASES,
        "enumeration": root / DEFAULT_ENUMERATION,
        "federated_segment_scores": root / DEFAULT_SEGMENT_SCORES,
        "dev_runtime": root / DEFAULT_DEV_RUNTIME,
        "canary_runtime": root / DEFAULT_CANARY_RUNTIME,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    ground_truth = read_jsonl(inputs["ground_truth"])
    evaluation = read_jsonl(inputs["adaptive_dev"]) + read_jsonl(inputs["downgraded_canary"])
    q3 = read_jsonl(inputs["q3_cases"])
    assembler = enrich_assembler_cases(
        read_jsonl(inputs["frozen_assembler_cases"]),
        read_jsonl(inputs["enumeration"]),
    )
    chunks = read_jsonl(inputs["chunks"])
    routes = _route_map(read_jsonl(inputs["dev_runtime"]), read_jsonl(inputs["canary_runtime"]))
    fallback_cases, fallback_scores = build_bounded_fallback_inputs(
        assembler_cases=assembler,
        segment_score_rows=read_jsonl(inputs["federated_segment_scores"]),
        routes=routes,
        chunks=chunks,
    )
    fallback_assembler = assemble_chunk_diverse_configuration(
        fallback_cases,
        fallback_scores,
        threshold=ASSEMBLER_THRESHOLD,
        k=ASSEMBLER_K,
    )
    rows = build_q4_rows(
        ground_truth_rows=ground_truth,
        evaluation_rows=evaluation,
        q3_rows=q3,
        assembler_cases=assembler,
        fallback_assembler_rows=fallback_assembler,
        routes=routes,
        chunks=chunks,
    )
    result = summarize_q4(rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_bounded_source_fallback_ab",
        "result": result,
        "constraints": {
            "gold_or_labels_changed": False,
            "gold_available_to_trigger_or_commit": False,
            "domain_keyword_rules_added": 0,
            "model_calls": 0,
            "training_or_reindex": False,
            "runtime_or_canonical_promoted": False,
            "frozen_blind_accessed": False,
        },
        "inputs": {
            name: {"path": path.relative_to(root).as_posix(), "sha256": before[name]}
            for name, path in inputs.items()
        },
    }
    evidence_dir = artifact_root / "data/v3/evidence"
    reports_dir = artifact_root / "reports/v3"
    cases_bytes = _serialize_jsonl(rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"bounded_candidate_source_fallback_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"bounded_candidate_source_fallback_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _render_markdown(report, rows)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"bounded_candidate_source_fallback_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("A frozen input changed during Q4 evaluation")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "decision": result["decision"],
        "inputs": report["inputs"],
        "outputs": {
            "cases": {"path": cases_path.relative_to(artifact_root).as_posix(), "sha256": cases_sha, "row_count": len(rows)},
            "report_json": {"path": report_path.relative_to(artifact_root).as_posix(), "sha256": report_sha},
            "report_md": {"path": markdown_path.relative_to(artifact_root).as_posix(), "sha256": markdown_sha},
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"bounded_candidate_source_fallback_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "result": result,
        "cases_sha256": cases_sha,
        "report_json_sha256": report_sha,
        "report_md_sha256": markdown_sha,
        "manifest_sha256": manifest_sha,
        "cases_path": cases_path.as_posix(),
        "report_json_path": report_path.as_posix(),
        "report_md_path": markdown_path.as_posix(),
        "manifest_path": manifest_path.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(evaluate_and_freeze(args.root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
