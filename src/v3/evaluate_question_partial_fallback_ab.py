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
from src.v3.run_unified_runtime import PARTIAL_DISCLAIMER
from src.v3.select_evidence import classify_answerability

EVALUATOR_VERSION = "question-partial-fallback-ab-v3.2.0"
CASE_SCHEMA_VERSION = "question-partial-fallback-ab-case-v3.2"
REPORT_SCHEMA_VERSION = "question-partial-fallback-ab-report-v3.2"
MANIFEST_SCHEMA_VERSION = "question-partial-fallback-ab-manifest-v3.2"
SPAN_COMPLETENESS_THRESHOLD = 0.50

DEFAULT_GROUND_TRUTH = Path(
    "data/v3/evaluation/semantic_answerability_ground_truth_"
    "53cd8ae72ad4ee2f7c9b1d4370991ad74b5044d154e3657fd2008f45f71fe609.jsonl"
)
DEFAULT_ARM0_CASES = Path(
    "data/v3/evidence/router_backbone_mixed_metrics_cases_"
    "72fdfde24b8001ea7ab9864b431d606eb40217f581a37bcaba1274b57e15170a.jsonl"
)
DEFAULT_UNIFIED_RUNTIME = Path(
    "data/v3/runtime/unified_runtime_cases_"
    "f28e2fbfb768c901dc4f1079f262252d645a74c7e4ee494180c2879e528f7789.jsonl"
)
DEFAULT_CANARY_RUNTIME = Path(
    "data/v3/evaluation/authored_canary_first_run_cases_"
    "a326d9fd96a4cfcaf9b2d38d74f27fffe26b62dfc1364063c8258891546beecd.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/question_partial_fallback_ab.md")


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "small_sample_limit": total < 5,
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


def _claims_exact(
    claims: list[dict[str, Any]], chunks_by_id: dict[str, dict[str, Any]]
) -> bool:
    return bool(claims) and all(
        claim["citation_chunk_id"] in chunks_by_id
        and claim["claim_text"]
        in chunks_by_id[claim["citation_chunk_id"]]["display_text"]
        for claim in claims
    )


def _unified_observation(
    row: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    response = row["response"]
    plan = response.get("answer_plan")
    claims = [] if plan is None else plan["claims"]
    expected = set(row["expected_evidence_group_ids"])
    cited = set(row["cited_evidence_group_ids"])
    recalls = {group_id: 0.0 for group_id in expected}
    for claim in row["claim_audit"]:
        for group_id in claim["matched_evidence_group_ids"]:
            if group_id in recalls:
                recalls[group_id] = max(
                    recalls[group_id], float(claim["gold_span_token_recall"])
                )
    disclaimer = (
        response["response_type"] == "partial_official_fact"
        and response["rendered_answer"].startswith(PARTIAL_DISCLAIMER)
    )
    return {
        "fallback_source": "frozen_unified_runtime",
        "global_partial_disclaimer": disclaimer,
        "exact_extractive": (
            response["runtime_status"] == "success"
            and response["verification"] is not None
            and response["verification"]["verified"]
            and _claims_exact(claims, chunks_by_id)
        ),
        "official_group_count": len(expected),
        "official_group_cited_count": len(expected & cited),
        "all_official_groups_cited": expected <= cited,
        "official_group_span_recalls": {
            key: round(value, 8) for key, value in sorted(recalls.items())
        },
        "all_official_spans_complete": all(
            value >= SPAN_COMPLETENESS_THRESHOLD for value in recalls.values()
        ),
        "cited_chunk_ids": sorted(response["citation_chunk_ids"]),
    }


def _canary_observation(
    row: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    canonical = row["canonical"]
    claims = canonical["claims"]
    group_rows = row["group_results"]
    recalls = {
        group["group_id"]: float(group["canonical_claim_token_recall"])
        for group in group_rows
    }
    return {
        "fallback_source": "frozen_authored_canary_first_run",
        "global_partial_disclaimer": bool(row["partial_disclaimer"]),
        "exact_extractive": (
            canonical["runtime_status"] == "success"
            and _claims_exact(claims, chunks_by_id)
        ),
        "official_group_count": len(group_rows),
        "official_group_cited_count": sum(
            bool(group["canonical_cited_hit"]) for group in group_rows
        ),
        "all_official_groups_cited": all(
            bool(group["canonical_cited_hit"]) for group in group_rows
        ),
        "official_group_span_recalls": {
            key: round(value, 8) for key, value in sorted(recalls.items())
        },
        "all_official_spans_complete": all(
            value >= SPAN_COMPLETENESS_THRESHOLD for value in recalls.values()
        ),
        "cited_chunk_ids": sorted(canonical["citation_chunk_ids"]),
    }


def _fallback_metrics(observation: dict[str, Any]) -> dict[str, Any]:
    disclaimer = observation["global_partial_disclaimer"]
    chunk_complete = observation["all_official_groups_cited"]
    correct = disclaimer and chunk_complete
    if not disclaimer:
        primary = "mixed_overclaim"
    elif chunk_complete:
        primary = "correct_mixed_partial"
    else:
        primary = "mixed_missing_evidence"
    return {
        "correct_mixed_partial": correct,
        "correct_mixed_partial_span_strict": (
            correct and observation["all_official_spans_complete"]
        ),
        "mixed_overclaim": not disclaimer,
        "mixed_missing_evidence": disclaimer and not chunk_complete,
        "primary_mixed_label": primary,
    }


def build_ab_rows(
    *,
    ground_truth_rows: list[dict[str, Any]],
    arm0_rows: list[dict[str, Any]],
    unified_rows: list[dict[str, Any]],
    canary_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ground_truth = {row["case_id"]: row for row in ground_truth_rows}
    arm0 = {row["case_id"]: row for row in arm0_rows}
    unified = {row["case_id"]: row for row in unified_rows}
    canary = {row["case_id"]: row for row in canary_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    if set(ground_truth) != set(arm0):
        raise RuntimeError("Ground truth and Arm0 case IDs differ")
    if set(unified) & set(canary):
        raise RuntimeError("Frozen fallback sources overlap")
    if set(unified) | set(canary) != set(ground_truth):
        raise RuntimeError("Frozen fallback sources do not cover all 95 cases")

    output = []
    for case_id in sorted(ground_truth):
        gt = ground_truth[case_id]
        baseline = arm0[case_id]
        signal = classify_answerability(gt["question"])
        applied = signal["label"] == "partial"
        observation = None
        metrics = baseline["mixed_metrics"]
        if applied:
            source = unified.get(case_id)
            observation = (
                _unified_observation(source, chunks_by_id)
                if source is not None
                else _canary_observation(canary[case_id], chunks_by_id)
            )
            metrics = _fallback_metrics(observation)
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": baseline["dataset"],
                "answerability_profile": gt["answerability_profile"],
                "question_signal": signal,
                "arm_q_applied": applied,
                "arm_q_observation": observation,
                "arm0_mixed_metrics": baseline["mixed_metrics"],
                "arm_q_mixed_metrics": metrics,
                "arm0_score": baseline["arm0_score"],
                "docs_value_complete": baseline["docs_value_complete"],
                "question_or_gold_text_included": False,
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_runtime_decision": False,
            }
        )
    return output


def summarize_ab(rows: list[dict[str, Any]]) -> dict[str, Any]:
    docs = [row for row in rows if row["answerability_profile"] == "docs_only"]
    mixed = [row for row in rows if row["answerability_profile"] == "mixed"]
    reject = [row for row in rows if row["arm0_score"]["reject_correct"]]
    realtime = [row for row in rows if row["arm0_score"]["realtime_safe_abstain"]]

    def count(items: list[dict[str, Any]], predicate) -> int:
        return sum(1 for row in items if predicate(row))

    classifier = {
        profile: dict(
            sorted(
                Counter(
                    row["question_signal"]["label"]
                    for row in rows
                    if row["answerability_profile"] == profile
                ).items()
            )
        )
        for profile in sorted({row["answerability_profile"] for row in rows})
    }
    docs_chunk = count(docs, lambda row: row["arm0_score"]["grounded_answer"])
    docs_span = count(
        docs,
        lambda row: row["arm0_score"]["grounded_answer"]
        and row["docs_value_complete"],
    )

    def mixed_summary(key: str) -> dict[str, Any]:
        return {
            "correct_mixed_partial": _ratio(
                count(mixed, lambda row: row[key]["correct_mixed_partial"]),
                len(mixed),
            ),
            "correct_mixed_partial_span_strict": _ratio(
                count(
                    mixed,
                    lambda row: row[key]["correct_mixed_partial_span_strict"],
                ),
                len(mixed),
            ),
            "mixed_overclaim": _ratio(
                count(mixed, lambda row: row[key]["mixed_overclaim"]), len(mixed)
            ),
            "mixed_missing_evidence": _ratio(
                count(
                    mixed,
                    lambda row: row[key]["mixed_missing_evidence"],
                ),
                len(mixed),
            ),
            "primary_label_counts": dict(
                sorted(Counter(row[key]["primary_mixed_label"] for row in mixed).items())
            ),
        }

    regressions = [
        row["case_id"]
        for row in mixed
        if row["arm0_mixed_metrics"]["correct_mixed_partial"]
        and not row["arm_q_mixed_metrics"]["correct_mixed_partial"]
    ]
    overclaim_rows = [
        row for row in mixed if row["arm0_mixed_metrics"]["mixed_overclaim"]
    ]
    converted = count(
        overclaim_rows,
        lambda row: row["arm_q_mixed_metrics"]["correct_mixed_partial"],
    )
    unresolved = count(
        overclaim_rows, lambda row: row["arm_q_mixed_metrics"]["mixed_overclaim"]
    )
    applied = [row for row in rows if row["arm_q_applied"]]
    exact = count(
        applied, lambda row: row["arm_q_observation"]["exact_extractive"]
    )
    disclaimer = count(
        applied,
        lambda row: row["arm_q_observation"]["global_partial_disclaimer"],
    )
    arm0_mixed = mixed_summary("arm0_mixed_metrics")
    arm_q_mixed = mixed_summary("arm_q_mixed_metrics")
    checks = {
        "docs_chunk_nonregression": docs_chunk >= 61,
        "docs_span_value_nonregression": docs_span >= 45,
        "mixed_overclaim_zero": arm_q_mixed["mixed_overclaim"]["successes"] == 0,
        "existing_correct_mixed_question_regression_zero": not regressions,
        "fallback_exact_extractive_all": exact == len(applied),
        "fallback_partial_disclaimer_all": disclaimer == len(applied),
        "reject_unchanged_11_of_11": len(reject) == 11,
        "realtime_unchanged_2_of_2": len(realtime) == 2,
    }
    return {
        "question_signal_counts_by_profile": classifier,
        "arm_q_applied": _ratio(len(applied), len(rows)),
        "docs_only_unchanged": {
            "question_count": len(docs),
            "chunk_grounded": _ratio(docs_chunk, len(docs)),
            "span_value_grounded": _ratio(docs_span, len(docs)),
        },
        "arm0_mixed": arm0_mixed,
        "arm_q_mixed": arm_q_mixed,
        "overclaim_conversion": {
            "baseline_overclaim_count": len(overclaim_rows),
            "converted_to_correct_partial": converted,
            "converted_to_missing_evidence": len(overclaim_rows) - converted - unresolved,
            "unresolved_overclaim": unresolved,
        },
        "existing_correct_mixed_regression_count": len(regressions),
        "existing_correct_mixed_regression_case_ids": sorted(regressions),
        "fallback_contract": {
            "exact_extractive": _ratio(exact, len(applied)),
            "partial_disclaimer": _ratio(disclaimer, len(applied)),
        },
        "strict_gate_checks": checks,
        "strict_gate_passed": all(checks.values()),
        "decision": "DEVELOPMENT_GO" if all(checks.values()) else "DEVELOPMENT_NO_GO",
    }


def _render_markdown(report: dict[str, Any]) -> bytes:
    result = report["result"]
    arm0 = result["arm0_mixed"]
    arm_q = result["arm_q_mixed"]
    docs = result["docs_only_unchanged"]
    conversion = result["overclaim_conversion"]
    lines = [
        "# Question-level partial fallback A/B (development only)",
        "",
        "Arm Q composes already-frozen partial outputs only when the existing question-level",
        "classifier returns `partial`. No model call, runtime change, or promotion occurred.",
        "",
        "## Result",
        "",
        f"Decision: **{result['decision']}** (strict gate passed: `{result['strict_gate_passed']}`).",
        "",
        "| Metric | Arm 0 | Arm Q |",
        "|---|---:|---:|",
        f"| docs_only chunk grounded | {docs['chunk_grounded']['successes']}/69 | {docs['chunk_grounded']['successes']}/69 |",
        f"| docs_only span-value grounded | {docs['span_value_grounded']['successes']}/69 | {docs['span_value_grounded']['successes']}/69 |",
        f"| mixed correct partial (chunk) | {arm0['correct_mixed_partial']['successes']}/13 | {arm_q['correct_mixed_partial']['successes']}/13 |",
        f"| mixed correct partial (span) | {arm0['correct_mixed_partial_span_strict']['successes']}/13 | {arm_q['correct_mixed_partial_span_strict']['successes']}/13 |",
        f"| mixed overclaim | {arm0['mixed_overclaim']['successes']}/13 | {arm_q['mixed_overclaim']['successes']}/13 |",
        f"| mixed missing evidence | {arm0['mixed_missing_evidence']['successes']}/13 | {arm_q['mixed_missing_evidence']['successes']}/13 |",
        "",
        "## Conversion and regression",
        "",
        f"- baseline overclaims: {conversion['baseline_overclaim_count']}",
        f"- converted to correct partial: {conversion['converted_to_correct_partial']}",
        f"- converted to honest partial with missing evidence: {conversion['converted_to_missing_evidence']}",
        f"- unresolved overclaims: {conversion['unresolved_overclaim']}",
        f"- previously correct mixed-question regressions: {result['existing_correct_mixed_regression_count']}",
        f"- regression case IDs: `{result['existing_correct_mixed_regression_case_ids']}`",
        "",
        "## Question-level signal",
        "",
        f"`{result['question_signal_counts_by_profile']}`",
        "",
        "## Strict gate",
        "",
    ]
    lines.extend(
        f"- {name}: `{passed}`"
        for name, passed in result["strict_gate_checks"].items()
    )
    lines.extend(
        [
            "",
            "The fallback is not promoted. Aggregate safety improves, but any strict",
            "question regression keeps this arm development-only NO-GO.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "arm0_two_axis_cases": root / DEFAULT_ARM0_CASES,
        "unified_runtime_cases": root / DEFAULT_UNIFIED_RUNTIME,
        "authored_canary_first_run_cases": root / DEFAULT_CANARY_RUNTIME,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "question_classifier_source": root / "src/v3/select_evidence.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    rows = build_ab_rows(
        ground_truth_rows=read_jsonl(inputs["answerability_ground_truth"]),
        arm0_rows=read_jsonl(inputs["arm0_two_axis_cases"]),
        unified_rows=read_jsonl(inputs["unified_runtime_cases"]),
        canary_rows=read_jsonl(inputs["authored_canary_first_run_cases"]),
        chunks=read_jsonl(inputs["chunks"]),
    )
    result = summarize_ab(rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_question_partial_fallback_no_promotion",
        "span_completeness_threshold": SPAN_COMPLETENESS_THRESHOLD,
        "result": result,
        "constraints": {
            "model_inference_calls": 0,
            "new_keyword_rules": 0,
            "search_changed": False,
            "planner_changed": False,
            "reranker_changed": False,
            "assembler_changed": False,
            "gold_or_labels_changed": False,
            "runtime_or_canonical_promoted": False,
        },
        "inputs": {
            name: {
                "path": path.resolve().relative_to(root).as_posix(),
                "sha256": before[name],
            }
            for name, path in inputs.items()
        },
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"question_partial_fallback_ab_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)

    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"question_partial_fallback_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _render_markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"question_partial_fallback_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("A frozen input changed during evaluation")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "git_head": _git_head(root),
        "inputs": report["inputs"],
        "outputs": {
            "cases": {"path": cases_path.relative_to(root).as_posix(), "sha256": cases_sha},
            "report_json": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_md": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "decision": result["decision"],
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"question_partial_fallback_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "result": result,
        "cases_path": cases_path,
        "cases_sha256": cases_sha,
        "report_json_path": report_path,
        "report_json_sha256": report_sha,
        "report_md_path": markdown_path,
        "report_md_sha256": markdown_sha,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = evaluate_and_freeze(args.root)
    print(
        json.dumps(
            {
                **{key: value for key, value in result.items() if not isinstance(value, Path)},
                **{key: value.as_posix() for key, value in result.items() if isinstance(value, Path)},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

