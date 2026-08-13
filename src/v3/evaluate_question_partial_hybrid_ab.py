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
from src.v3.evaluate_claim_reranker import _gold_span_token_recall
from src.v3.evaluate_question_partial_fallback_ab import (
    DEFAULT_ARM0_CASES,
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_CHUNKS,
    DEFAULT_GROUND_TRUTH,
    SPAN_COMPLETENESS_THRESHOLD,
    _canary_observation,
    _claims_exact,
    _fallback_metrics,
    _ratio,
)
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_ASSEMBLER,
    DEFAULT_CANARY,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    docs_requirement_split,
)
from src.v3.run_unified_runtime import PARTIAL_DISCLAIMER
from src.v3.select_evidence import classify_answerability

EVALUATOR_VERSION = "question-partial-hybrid-ab-v3.2.0"
CASE_SCHEMA_VERSION = "question-partial-hybrid-ab-case-v3.2"
AUDIT_SCHEMA_VERSION = "mixed-answerability-error-audit-v3.2"
REPORT_SCHEMA_VERSION = "question-partial-hybrid-ab-report-v3.2"
MANIFEST_SCHEMA_VERSION = "question-partial-hybrid-ab-manifest-v3.2"

DEFAULT_ARM_Q_CASES = Path(
    "data/v3/evidence/question_partial_fallback_ab_cases_"
    "18c3c54f0bc6411af03a6e9aca00737c7c42da1fbee077a829f49f248d4f83fd.jsonl"
)
DEFAULT_CLAIM_RERANKER = Path(
    "data/v3/evidence/claim_reranker_cases_"
    "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/question_partial_hybrid_ab.md")


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _response_claims(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("claims") is not None:
        return response["claims"]
    plan = response.get("answer_plan")
    return [] if plan is None else plan["claims"]


def _group_observation(
    *,
    claims: list[dict[str, Any]],
    evidence_groups: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    source: str,
    partial_safety_contract: bool,
    verified: bool,
) -> dict[str, Any]:
    cited_ids = {claim["citation_chunk_id"] for claim in claims}
    recalls: dict[str, float] = {}
    cited_count = 0
    for group in evidence_groups:
        acceptable = set(group["acceptable_chunk_ids"])
        matching = [
            claim for claim in claims if claim["citation_chunk_id"] in acceptable
        ]
        if matching:
            cited_count += 1
        recalls[group["group_id"]] = max(
            (
                _gold_span_token_recall(claim["claim_text"], group["evidence_span"])
                for claim in matching
            ),
            default=0.0,
        )
    return {
        "fallback_source": source,
        "global_partial_disclaimer": partial_safety_contract,
        "partial_safety_contract": partial_safety_contract,
        "exact_extractive": verified and _claims_exact(claims, chunks_by_id),
        "official_group_count": len(evidence_groups),
        "official_group_cited_count": cited_count,
        "all_official_groups_cited": cited_count == len(evidence_groups),
        "official_group_span_recalls": {
            key: round(value, 8) for key, value in sorted(recalls.items())
        },
        "all_official_spans_complete": all(
            value >= SPAN_COMPLETENESS_THRESHOLD for value in recalls.values()
        ),
        "cited_chunk_ids": sorted(cited_ids),
    }


def _claim_reranker_observation(
    row: dict[str, Any],
    evaluation: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    response = row["response"]
    claims = _response_claims(response)
    verification = response.get("verification")
    verified = bool(verification and verification.get("verified"))
    partial = (
        response["response_type"] == "partial_official_fact"
        and response["rendered_answer"].startswith(PARTIAL_DISCLAIMER)
    )
    return _group_observation(
        claims=claims,
        evidence_groups=evaluation["evidence_groups"],
        chunks_by_id=chunks_by_id,
        source="frozen_canonical_claim_reranker_v3_1",
        partial_safety_contract=partial,
        verified=verified,
    )


def _preserved_partial_observation(
    baseline: dict[str, Any],
    assembler: dict[str, Any],
    evaluation: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    exact = True
    for decision in assembler["decisions"]:
        if decision["status"] != "supported_exact":
            continue
        for span in decision["spans"]:
            chunk = chunks_by_id.get(span["chunk_id"])
            if chunk is None:
                exact = False
                continue
            sliced = chunk["display_text"][span["start_char"] : span["end_char"]]
            exact = exact and sliced == span["text"]
            claims.append(
                {
                    "citation_chunk_id": span["chunk_id"],
                    "claim_text": span["text"],
                }
            )
    observation = _group_observation(
        claims=claims,
        evidence_groups=evaluation["evidence_groups"],
        chunks_by_id=chunks_by_id,
        source="frozen_arm0_already_partial",
        partial_safety_contract=baseline["arm0"]["response_mode"] == "partial_answer",
        verified=exact,
    )
    observation["exact_extractive"] = exact and observation["exact_extractive"]
    return observation


def build_hybrid_rows(
    *,
    ground_truth_rows: list[dict[str, Any]],
    arm0_rows: list[dict[str, Any]],
    arm_q_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    claim_reranker_rows: list[dict[str, Any]],
    canary_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ground_truth = {row["case_id"]: row for row in ground_truth_rows}
    arm0 = {row["case_id"]: row for row in arm0_rows}
    arm_q = {row["case_id"]: row for row in arm_q_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    claim_reranker = {row["case_id"]: row for row in claim_reranker_rows}
    canary = {row["case_id"]: row for row in canary_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    expected = set(ground_truth)
    if not (expected == set(arm0) == set(arm_q) == set(assemblers) == set(evaluations)):
        raise RuntimeError("Frozen 95-case joins do not have identical case IDs")

    output = []
    for case_id in sorted(expected):
        gt = ground_truth[case_id]
        baseline = arm0[case_id]
        previous = arm_q[case_id]
        signal = classify_answerability(gt["question"])
        observation = None
        metrics = baseline["mixed_metrics"]
        source = "arm0_unchanged"
        if signal["label"] == "partial":
            if baseline["arm0"]["response_mode"] == "partial_answer":
                observation = _preserved_partial_observation(
                    baseline,
                    assemblers[case_id],
                    evaluations[case_id],
                    chunks_by_id,
                )
            elif case_id in claim_reranker:
                observation = _claim_reranker_observation(
                    claim_reranker[case_id], evaluations[case_id], chunks_by_id
                )
            elif case_id in canary:
                observation = _canary_observation(canary[case_id], chunks_by_id)
                observation["partial_safety_contract"] = observation[
                    "global_partial_disclaimer"
                ]
            else:
                raise RuntimeError(f"No frozen Q2 source for partial case: {case_id}")
            metrics = _fallback_metrics(observation)
            source = observation["fallback_source"]
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": baseline["dataset"],
                "answerability_profile": gt["answerability_profile"],
                "question_signal": signal,
                "arm_q2_applied": observation is not None,
                "arm_q2_source": source,
                "arm_q2_observation": observation,
                "arm0_mixed_metrics": baseline["mixed_metrics"],
                "arm_q_mixed_metrics": previous["arm_q_mixed_metrics"],
                "arm_q2_mixed_metrics": metrics,
                "arm0_score": baseline["arm0_score"],
                "docs_value_complete": baseline["docs_value_complete"],
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_runtime_decision": False,
                "question_or_gold_text_included": False,
            }
        )
    return output


def _mixed_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    def count(field: str) -> int:
        return sum(bool(row[key][field]) for row in rows)

    return {
        "correct_mixed_partial": _ratio(count("correct_mixed_partial"), len(rows)),
        "correct_mixed_partial_span_strict": _ratio(
            count("correct_mixed_partial_span_strict"), len(rows)
        ),
        "mixed_overclaim": _ratio(count("mixed_overclaim"), len(rows)),
        "mixed_missing_evidence": _ratio(count("mixed_missing_evidence"), len(rows)),
        "primary_label_counts": dict(
            sorted(Counter(row[key]["primary_mixed_label"] for row in rows).items())
        ),
    }


def summarize_hybrid(rows: list[dict[str, Any]]) -> dict[str, Any]:
    docs = [row for row in rows if row["answerability_profile"] == "docs_only"]
    mixed = [row for row in rows if row["answerability_profile"] == "mixed"]
    applied = [row for row in rows if row["arm_q2_applied"]]
    arm0 = _mixed_summary(mixed, "arm0_mixed_metrics")
    arm_q = _mixed_summary(mixed, "arm_q_mixed_metrics")
    arm_q2 = _mixed_summary(mixed, "arm_q2_mixed_metrics")
    regressions = [
        row["case_id"]
        for row in mixed
        if row["arm0_mixed_metrics"]["correct_mixed_partial"]
        and not row["arm_q2_mixed_metrics"]["correct_mixed_partial"]
    ]
    exact_count = sum(row["arm_q2_observation"]["exact_extractive"] for row in applied)
    safety_count = sum(
        row["arm_q2_observation"].get(
            "partial_safety_contract",
            row["arm_q2_observation"]["global_partial_disclaimer"],
        )
        for row in applied
    )
    docs_chunk = sum(row["arm0_score"]["grounded_answer"] for row in docs)
    docs_span = sum(
        row["arm0_score"]["grounded_answer"] and row["docs_value_complete"]
        for row in docs
    )
    source_counts = dict(sorted(Counter(row["arm_q2_source"] for row in applied).items()))
    checks = {
        "docs_chunk_nonregression": docs_chunk >= 61,
        "docs_span_value_nonregression": docs_span >= 45,
        "mixed_overclaim_zero": arm_q2["mixed_overclaim"]["successes"] == 0,
        "existing_correct_mixed_question_regression_zero": not regressions,
        "q2_exact_extractive_all": exact_count == len(applied),
        "q2_partial_safety_contract_all": safety_count == len(applied),
        "reject_unchanged_11_of_11": sum(
            row["arm0_score"]["reject_correct"] for row in rows
        )
        == 11,
        "realtime_unchanged_2_of_2": sum(
            row["arm0_score"]["realtime_safe_abstain"] for row in rows
        )
        == 2,
    }
    return {
        "docs_only_unchanged": {
            "question_count": len(docs),
            "chunk_grounded": _ratio(docs_chunk, len(docs)),
            "span_value_grounded": _ratio(docs_span, len(docs)),
        },
        "arm0_mixed": arm0,
        "arm_q_mixed": arm_q,
        "arm_q2_mixed": arm_q2,
        "arm_q2_source_counts": source_counts,
        "existing_correct_mixed_regression_count": len(regressions),
        "existing_correct_mixed_regression_case_ids": regressions,
        "arm_q2_contract": {
            "exact_extractive": _ratio(exact_count, len(applied)),
            "partial_safety_contract": _ratio(safety_count, len(applied)),
        },
        "strict_gate_checks": checks,
        "strict_gate_passed": all(checks.values()),
        "decision": "DEVELOPMENT_GO_CANDIDATE"
        if all(checks.values())
        else "DEVELOPMENT_NO_GO",
    }


def build_error_audit_rows(
    *,
    hybrid_rows: list[dict[str, Any]],
    ground_truth_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    arm0_rows: list[dict[str, Any]],
    arm_q_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hybrid = {row["case_id"]: row for row in hybrid_rows}
    ground_truth = {row["case_id"]: row for row in ground_truth_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    arm0 = {row["case_id"]: row for row in arm0_rows}
    arm_q = {row["case_id"]: row for row in arm_q_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}

    output = []
    for case_id in sorted(hybrid):
        baseline = arm0[case_id]
        previous = arm_q[case_id]
        is_regression = (
            baseline["mixed_metrics"]["correct_mixed_partial"]
            and not previous["arm_q_mixed_metrics"]["correct_mixed_partial"]
        )
        if not (
            baseline["mixed_metrics"]["mixed_overclaim"]
            or previous["arm_q_mixed_metrics"]["mixed_missing_evidence"]
            or is_regression
        ):
            continue
        gt = ground_truth[case_id]
        if gt["answerability_profile"] != "mixed":
            continue
        enumeration = enumerations[case_id]
        assembler = assemblers[case_id]
        evaluation = evaluations[case_id]
        requirements = enumeration["requirements"]
        docs_required, non_docs_required = docs_requirement_split(gt, len(requirements))
        summaries = {
            int(item["requirement_index"]): item
            for item in gt.get("partial_requirements_in_question_order") or []
        }
        requirement_rows = []
        for index, (requirement, decision) in enumerate(
            zip(requirements, assembler["decisions"], strict=True), start=1
        ):
            summary = summaries.get(index, {})
            requirement_rows.append(
                {
                    "requirement_index": index,
                    "human_summary": summary.get("requirement_summary"),
                    "answerable_from_docs": index in docs_required,
                    "planner_requirement": {
                        key: requirement.get(key)
                        for key in ("subject", "relation", "value_type", "subject_group")
                    },
                    "arm0_status": decision["status"],
                    "arm0_exact_spans": [
                        {
                            key: span[key]
                            for key in ("chunk_id", "start_char", "end_char", "text")
                        }
                        for span in decision["spans"]
                    ],
                }
            )
        tags = []
        if baseline["mixed_metrics"]["mixed_overclaim"]:
            tags.append("ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT")
        if previous["arm_q_mixed_metrics"]["mixed_missing_evidence"]:
            tags.append("ARM_Q_OFFICIAL_EVIDENCE_MISS")
        if is_regression:
            tags.append("ARM_Q_EXISTING_CORRECT_MIXED_REGRESSION")
        if previous["question_signal"]["label"] != "partial":
            tags.append("QUESTION_PARTIAL_SIGNAL_MISS")
        if baseline["mixed_metrics"]["mixed_overclaim"]:
            first_stage = "SEMANTIC_SUPPORT_BOUNDARY"
            rationale = (
                "사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 "
                "질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다."
            )
        elif previous["question_signal"]["label"] != "partial":
            first_stage = "QUESTION_PARTIAL_SIGNAL"
            rationale = "혼합형 질문을 question-level partial 신호가 포착하지 못했다."
        else:
            first_stage = "FALLBACK_EVIDENCE_SELECTION"
            rationale = "안전 partial은 적용됐지만 공식 gold evidence group 인용이 누락됐다."
        output.append(
            {
                "audit_schema_version": AUDIT_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": baseline["dataset"],
                "question": evaluation["question"],
                "requirements": requirement_rows,
                "gold_evidence_groups": evaluation["evidence_groups"],
                "arm0": {
                    "response_mode": baseline["arm0"]["response_mode"],
                    "supported_requirement_indices": baseline["arm0"][
                        "supported_requirement_indices"
                    ],
                    "label": baseline["mixed_metrics"]["primary_mixed_label"],
                },
                "arm_q": {
                    "question_signal": previous["question_signal"],
                    "label": previous["arm_q_mixed_metrics"]["primary_mixed_label"],
                    "observation": previous["arm_q_observation"],
                },
                "arm_q2": {
                    "source": hybrid[case_id]["arm_q2_source"],
                    "label": hybrid[case_id]["arm_q2_mixed_metrics"][
                        "primary_mixed_label"
                    ],
                    "observation": hybrid[case_id]["arm_q2_observation"],
                },
                "analysis": {
                    "first_failure_stage": first_stage,
                    "tags": tags,
                    "rationale": rationale,
                },
                "gold_used_for_scoring_and_audit_only": True,
            }
        )
    return output


def _code_block(lines: list[str], text: str) -> None:
    lines.append("```text")
    lines.extend(text.splitlines() or [""])
    lines.append("```")


def _render_markdown(report: dict[str, Any], audit_rows: list[dict[str, Any]]) -> bytes:
    result = report["result"]
    lines = [
        "# Mixed-answerability errors and question-partial hybrid A/B",
        "",
        "Development-only direct-data audit. Gold appears only in this audit and scoring;",
        "Arm Q2 decisions use no gold, new keyword, model call, or per-question rule.",
        "",
        "## A/B result",
        "",
        "| Metric | Arm 0 | Arm Q | Arm Q2 |",
        "|---|---:|---:|---:|",
        f"| Correct mixed partial | {result['arm0_mixed']['correct_mixed_partial']['successes']}/13 | {result['arm_q_mixed']['correct_mixed_partial']['successes']}/13 | {result['arm_q2_mixed']['correct_mixed_partial']['successes']}/13 |",
        f"| Span-strict mixed partial | {result['arm0_mixed']['correct_mixed_partial_span_strict']['successes']}/13 | {result['arm_q_mixed']['correct_mixed_partial_span_strict']['successes']}/13 | {result['arm_q2_mixed']['correct_mixed_partial_span_strict']['successes']}/13 |",
        f"| Mixed over-claim | {result['arm0_mixed']['mixed_overclaim']['successes']}/13 | {result['arm_q_mixed']['mixed_overclaim']['successes']}/13 | {result['arm_q2_mixed']['mixed_overclaim']['successes']}/13 |",
        f"| Mixed missing evidence | {result['arm0_mixed']['mixed_missing_evidence']['successes']}/13 | {result['arm_q_mixed']['mixed_missing_evidence']['successes']}/13 | {result['arm_q2_mixed']['mixed_missing_evidence']['successes']}/13 |",
        "",
        f"Decision: **{result['decision']}**. Source counts: `{result['arm_q2_source_counts']}`.",
        "",
        "## Direct error cases",
        "",
    ]
    for ordinal, row in enumerate(audit_rows, start=1):
        lines.extend(
            [
                f"### {ordinal}. {row['question']}",
                "",
                f"- case: `{row['case_id']}`",
                f"- first failure: `{row['analysis']['first_failure_stage']}`",
                f"- tags: `{row['analysis']['tags']}`",
                f"- labels: Arm0 `{row['arm0']['label']}` → Arm Q `{row['arm_q']['label']}` → Arm Q2 `{row['arm_q2']['label']}`",
                f"- analysis: {row['analysis']['rationale']}",
                "",
                "#### Requirements and Arm0 exact spans",
                "",
            ]
        )
        for requirement in row["requirements"]:
            lines.append(
                f"**R{requirement['requirement_index']} · docs={str(requirement['answerable_from_docs']).lower()} · {requirement['human_summary'] or requirement['planner_requirement']}**"
            )
            lines.append("")
            if requirement["arm0_exact_spans"]:
                for span in requirement["arm0_exact_spans"]:
                    lines.append(f"`{span['chunk_id']}`")
                    lines.append("")
                    _code_block(lines, span["text"])
                    lines.append("")
            else:
                lines.extend(["No cited span.", ""])
        lines.extend(["#### Human gold evidence", ""])
        for group in row["gold_evidence_groups"]:
            lines.append(
                f"`{group['group_id']}` acceptable chunks: `{group['acceptable_chunk_ids']}`"
            )
            lines.append("")
            _code_block(lines, group["evidence_span"])
            lines.append("")
        lines.append(f"Arm Q2 source: `{row['arm_q2']['source']}`.")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path, *, artifact_root: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    inputs = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": root / DEFAULT_ASSEMBLER,
        "arm0_cases": root / DEFAULT_ARM0_CASES,
        "arm_q_cases": root / DEFAULT_ARM_Q_CASES,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "canonical_claim_reranker": root / DEFAULT_CLAIM_RERANKER,
        "authored_canary_runtime": root / DEFAULT_CANARY_RUNTIME,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    ground_truth_rows = read_jsonl(inputs["answerability_ground_truth"])
    arm0_rows = read_jsonl(inputs["arm0_cases"])
    arm_q_rows = read_jsonl(inputs["arm_q_cases"])
    enumeration_rows = read_jsonl(inputs["enumeration"])
    assembler_rows = read_jsonl(inputs["assembler_cases"])
    evaluation_rows = read_jsonl(inputs["adaptive_dev"]) + read_jsonl(
        inputs["downgraded_canary"]
    )
    chunks = read_jsonl(inputs["chunks"])
    hybrid_rows = build_hybrid_rows(
        ground_truth_rows=ground_truth_rows,
        arm0_rows=arm0_rows,
        arm_q_rows=arm_q_rows,
        assembler_rows=assembler_rows,
        evaluation_rows=evaluation_rows,
        claim_reranker_rows=read_jsonl(inputs["canonical_claim_reranker"]),
        canary_rows=read_jsonl(inputs["authored_canary_runtime"]),
        chunks=chunks,
    )
    audit_rows = build_error_audit_rows(
        hybrid_rows=hybrid_rows,
        ground_truth_rows=ground_truth_rows,
        enumeration_rows=enumeration_rows,
        assembler_rows=assembler_rows,
        arm0_rows=arm0_rows,
        arm_q_rows=arm_q_rows,
        evaluation_rows=evaluation_rows,
    )
    result = summarize_hybrid(hybrid_rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_direct_error_audit_and_hybrid_ab",
        "result": result,
        "audit": {
            "row_count": len(audit_rows),
            "arm0_overclaim_count": sum(
                row["arm0_mixed_metrics"]["mixed_overclaim"] for row in hybrid_rows
            ),
            "arm_q_missing_evidence_count": sum(
                row["arm_q_mixed_metrics"]["mixed_missing_evidence"]
                for row in hybrid_rows
                if row["answerability_profile"] == "mixed"
            ),
            "first_failure_stage_counts": dict(
                sorted(
                    Counter(
                        row["analysis"]["first_failure_stage"] for row in audit_rows
                    ).items()
                )
            ),
        },
        "constraints": {
            "new_keyword_rules": 0,
            "model_inference_calls": 0,
            "training_run": False,
            "gold_or_labels_changed": False,
            "runtime_or_canonical_promoted": False,
            "sealed_or_frozen_blind_accessed": False,
        },
        "inputs": {
            name: {
                "path": path.relative_to(root).as_posix(),
                "sha256": before[name],
            }
            for name, path in inputs.items()
        },
    }

    evidence_dir = artifact_root / "data/v3/evidence"
    reports_dir = artifact_root / "reports/v3"
    cases_bytes = _serialize_jsonl(hybrid_rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"question_partial_hybrid_ab_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    audit_bytes = _serialize_jsonl(audit_rows, sort_key=lambda row: row["case_id"])
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    audit_path = evidence_dir / f"mixed_answerability_error_audit_{audit_sha}.jsonl"
    write_immutable(audit_path, audit_bytes)
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"question_partial_hybrid_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _render_markdown(report, audit_rows)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"question_partial_hybrid_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("A frozen input changed during evaluation")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "decision": result["decision"],
        "inputs": report["inputs"],
        "outputs": {
            "cases": {
                "path": cases_path.relative_to(artifact_root).as_posix(),
                "sha256": cases_sha,
                "row_count": len(hybrid_rows),
            },
            "error_audit": {
                "path": audit_path.relative_to(artifact_root).as_posix(),
                "sha256": audit_sha,
                "row_count": len(audit_rows),
            },
            "report_json": {
                "path": report_path.relative_to(artifact_root).as_posix(),
                "sha256": report_sha,
            },
            "report_md": {
                "path": markdown_path.relative_to(artifact_root).as_posix(),
                "sha256": markdown_sha,
            },
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"question_partial_hybrid_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "result": result,
        "audit": report["audit"],
        "cases_sha256": cases_sha,
        "audit_sha256": audit_sha,
        "report_json_sha256": report_sha,
        "report_md_sha256": markdown_sha,
        "manifest_sha256": manifest_sha,
        "cases_path": cases_path.as_posix(),
        "audit_path": audit_path.as_posix(),
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
