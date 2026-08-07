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
from src.v3.evaluate_question_partial_fallback_ab import (
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_CHUNKS,
    DEFAULT_GROUND_TRUTH,
    _fallback_metrics,
    _ratio,
)
from src.v3.evaluate_question_partial_hybrid_ab import (
    DEFAULT_CLAIM_RERANKER,
    _group_observation,
    _response_claims,
)
from src.v3.evaluate_router_backbone_mixed_metrics import DEFAULT_CANARY, DEFAULT_DEV

EVALUATOR_VERSION = "question-partial-context-ab-v3.2.1"
CASE_SCHEMA_VERSION = "question-partial-context-ab-case-v3.2"
AUDIT_SCHEMA_VERSION = "question-partial-context-error-audit-v3.2"
REPORT_SCHEMA_VERSION = "question-partial-context-ab-report-v3.2"
MANIFEST_SCHEMA_VERSION = "question-partial-context-ab-manifest-v3.2"

DEFAULT_Q2_CASES = Path(
    "data/v3/evidence/question_partial_hybrid_ab_cases_"
    "01f88a41218238a5e9474cd3901ff88a1a11ce7bc0a267dfac7986dcebc7af37.jsonl"
)
DEFAULT_FEDERATED_CASES = Path(
    "data/v3/evidence/federated_retrieval_ab_cases_"
    "c9921d0e7570ba77a40e7be94d85951f9419a2fe8847fc81c49891780f51f28f.jsonl"
)
DEFAULT_FEDERATED_CANDIDATES = Path(
    "data/v3/retrieval/federated_retrieval_ab_candidates_"
    "fc5d64c1c201ccbc37711dc9aba5268c276e6aedc05c57537cea7f227af689bd.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/question_partial_context_ab.md")


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


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


def build_context_rows(
    *,
    q2_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    if set(evaluations) != {row["case_id"] for row in q2_rows}:
        raise RuntimeError("Q2 and evaluation case IDs differ")

    output = []
    for q2 in sorted(q2_rows, key=lambda row: row["case_id"]):
        observation = q2["arm_q2_observation"]
        # The runtime trigger is the frozen question-level partial decision,
        # never gold span completeness. Applying context only to observed
        # failures would leak the evaluation answer into the decision.
        applied = bool(q2["arm_q2_applied"] and observation is not None)
        q3_observation = observation
        q3_metrics = q2["arm_q2_mixed_metrics"]
        context_chars = 0
        if applied:
            claims = []
            for chunk_id in observation["cited_chunk_ids"]:
                chunk = chunks_by_id[chunk_id]
                text = chunk["display_text"]
                context_chars += len(text)
                claims.append({"citation_chunk_id": chunk_id, "claim_text": text})
            q3_observation = _group_observation(
                claims=claims,
                evidence_groups=evaluations[q2["case_id"]]["evidence_groups"],
                chunks_by_id=chunks_by_id,
                source="q2_same_cited_chunk_context",
                partial_safety_contract=True,
                verified=True,
            )
            q3_observation["context_answer_unit"] = "full_cited_chunk_diagnostic"
            q3_observation["context_character_count"] = context_chars
            q3_metrics = _fallback_metrics(q3_observation)
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": q2["case_id"],
                "dataset": q2["dataset"],
                "answerability_profile": q2["answerability_profile"],
                "q3_context_applied": applied,
                "q3_context_character_count": context_chars,
                "arm0_mixed_metrics": q2["arm0_mixed_metrics"],
                "arm_q2_mixed_metrics": q2["arm_q2_mixed_metrics"],
                "arm_q3_mixed_metrics": q3_metrics,
                "arm_q2_observation": observation,
                "arm_q3_observation": q3_observation,
                "arm0_score": q2["arm0_score"],
                "docs_value_complete": q2["docs_value_complete"],
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_runtime_decision": False,
                "question_or_gold_text_included": False,
            }
        )
    return output


def summarize_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mixed = [row for row in rows if row["answerability_profile"] == "mixed"]
    docs = [row for row in rows if row["answerability_profile"] == "docs_only"]
    applied = [row for row in rows if row["q3_context_applied"]]
    q2 = _mixed_summary(mixed, "arm_q2_mixed_metrics")
    q3 = _mixed_summary(mixed, "arm_q3_mixed_metrics")
    regressions = [
        row["case_id"]
        for row in mixed
        if row["arm_q2_mixed_metrics"]["correct_mixed_partial"]
        and not row["arm_q3_mixed_metrics"]["correct_mixed_partial"]
    ]
    docs_chunk = sum(row["arm0_score"]["grounded_answer"] for row in docs)
    docs_span = sum(
        row["arm0_score"]["grounded_answer"] and row["docs_value_complete"]
        for row in docs
    )
    exact = sum(row["arm_q3_observation"]["exact_extractive"] for row in applied)
    safe = sum(
        row["arm_q3_observation"]["partial_safety_contract"] for row in applied
    )
    context_lengths = sorted(row["q3_context_character_count"] for row in applied)
    checks = {
        "strict_span_improved_over_9_of_13": (
            q3["correct_mixed_partial_span_strict"]["successes"] > 9
        ),
        "chunk_correct_partial_12_of_13_maintained": (
            q3["correct_mixed_partial"]["successes"] == 12
        ),
        "mixed_overclaim_zero": q3["mixed_overclaim"]["successes"] == 0,
        "existing_correct_regression_zero": not regressions,
        "context_exact_all": exact == len(applied),
        "context_partial_safety_all": safe == len(applied),
        "docs_chunk_61_of_69_unchanged": docs_chunk == 61,
        "docs_span_value_45_of_69_unchanged": docs_span == 45,
        "reject_11_of_11_unchanged": sum(
            row["arm0_score"]["reject_correct"] for row in rows
        )
        == 11,
        "realtime_2_of_2_unchanged": sum(
            row["arm0_score"]["realtime_safe_abstain"] for row in rows
        )
        == 2,
    }
    return {
        "arm_q2_mixed": q2,
        "arm_q3_mixed": q3,
        "context_applied_count": len(applied),
        "context_character_count": {
            "values": context_lengths,
            "median": context_lengths[len(context_lengths) // 2] if context_lengths else 0,
            "max": max(context_lengths, default=0),
        },
        "existing_correct_regression_case_ids": regressions,
        "docs_only_unchanged": {
            "chunk_grounded": _ratio(docs_chunk, len(docs)),
            "span_value_grounded": _ratio(docs_span, len(docs)),
        },
        "strict_gate_checks": checks,
        "strict_gate_passed": all(checks.values()),
        "decision": (
            "DEVELOPMENT_GO_CONTEXT_ARM_RUNTIME_NOT_PROMOTED"
            if all(checks.values())
            else "DEVELOPMENT_NO_GO"
        ),
        "remaining_error_count": sum(
            not row["arm_q3_mixed_metrics"]["correct_mixed_partial_span_strict"]
            for row in mixed
        ),
    }


def _actual_claims(
    case_id: str,
    q2_source: str,
    claim_rows: dict[str, dict[str, Any]],
    canary_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if q2_source == "frozen_canonical_claim_reranker_v3_1":
        return _response_claims(claim_rows[case_id]["response"])
    if case_id in canary_rows:
        return canary_rows[case_id]["canonical"]["claims"]
    return []


def build_failure_audit(
    *,
    q2_rows: list[dict[str, Any]],
    q3_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    claim_reranker_rows: list[dict[str, Any]],
    canary_rows: list[dict[str, Any]],
    federated_cases: list[dict[str, Any]],
    federated_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    q3 = {row["case_id"]: row for row in q3_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    claims = {row["case_id"]: row for row in claim_reranker_rows}
    canary = {row["case_id"]: row for row in canary_rows}
    federated = {row["case_id"]: row for row in federated_cases}
    candidate_rows: dict[str, list[dict[str, Any]]] = {}
    for row in federated_candidates:
        candidate_rows.setdefault(row["case_id"], []).append(row)

    output = []
    for row in q2_rows:
        if row["answerability_profile"] != "mixed":
            continue
        q2_metrics = row["arm_q2_mixed_metrics"]
        if q2_metrics["correct_mixed_partial_span_strict"]:
            continue
        evaluation = evaluations[row["case_id"]]
        observation = row["arm_q2_observation"]
        current_claims = _actual_claims(
            row["case_id"], row["arm_q2_source"], claims, canary
        )
        cited_ids = set(observation["cited_chunk_ids"]) if observation else set()
        all_gold_chunks_already_cited = all(
            bool(cited_ids & set(group["acceptable_chunk_ids"]))
            for group in evaluation["evidence_groups"]
        )
        if observation is not None and all_gold_chunks_already_cited:
            failure_type = "SAME_CHUNK_CONTEXT_TRUNCATION"
            rationale = (
                "모든 gold chunk는 이미 인용했지만 선택 span이 청크 안의 후속 값·목록을 "
                "포함하지 않았다. 동일 청크 context answer-unit으로 복구된다."
            )
        else:
            failure_type = "SOURCE_SCOPE_PLUS_PARTIAL_SIGNAL_MISS"
            rationale = (
                "hard source route가 gold source를 후보에서 제외했고 question-level partial "
                "signal도 개인 계산 요구를 놓쳤다. 기존 federated 진단은 근거만 회수한다."
            )
        fed = federated.get(row["case_id"])
        rank_audit = []
        for request in candidate_rows.get(row["case_id"], []):
            item = {
                "requirement_index": request["requirement_index"],
                "query": request["query"],
                "variant_gold_ranks": {},
            }
            acceptable = {
                chunk_id
                for group in evaluation["evidence_groups"]
                for chunk_id in group["acceptable_chunk_ids"]
            }
            for variant, value in request["variants"].items():
                ranks = [
                    hit["rank"] for hit in value["hits"] if hit["chunk_id"] in acceptable
                ]
                item["variant_gold_ranks"][variant] = min(ranks) if ranks else None
            rank_audit.append(item)
        route = canary.get(row["case_id"], {}).get("actual_route")
        output.append(
            {
                "audit_schema_version": AUDIT_SCHEMA_VERSION,
                "case_id": row["case_id"],
                "dataset": row["dataset"],
                "question": evaluation["question"],
                "q2_source": row["arm_q2_source"],
                "q2_claims": current_claims,
                "q2_observation": observation,
                "gold_evidence_groups": evaluation["evidence_groups"],
                "cited_chunk_contexts": [
                    {
                        "chunk_id": chunk_id,
                        "display_text": chunks_by_id[chunk_id]["display_text"],
                    }
                    for chunk_id in sorted(cited_ids)
                ],
                "first_failure_type": failure_type,
                "rationale": rationale,
                "q3_context_applied": q3[row["case_id"]]["q3_context_applied"],
                "q3_span_strict_fixed": q3[row["case_id"]]["arm_q3_mixed_metrics"][
                    "correct_mixed_partial_span_strict"
                ],
                "route_audit": (
                    None
                    if route is None
                    else {
                        "chosen_source_ids": route["source_ids"],
                        "candidate_sources": route["routing_signals"]["candidate_sources"],
                        "answerability": route["answerability"],
                        "answerability_reason": route["answerability_reason"],
                    }
                ),
                "federated_existing_ab": (
                    None
                    if fed is None
                    else {
                        arm: {
                            "all_groups_cited": fed[arm]["score"]["all_groups_cited"],
                            "grounded_answer": fed[arm]["score"]["grounded_answer"],
                            "cited_chunk_ids": fed[arm]["cited_chunk_ids"],
                        }
                        for arm in ("federated_global", "federated_quota")
                    }
                ),
                "federated_gold_rank_audit": rank_audit,
                "gold_used_for_scoring_and_audit_only": True,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def _render_markdown(report: dict[str, Any], audit: list[dict[str, Any]]) -> bytes:
    result = report["result"]
    q2 = result["arm_q2_mixed"]
    q3 = result["arm_q3_mixed"]
    lines = [
        "# Question-partial context answer-unit A/B",
        "",
        "Development-only. Gold is used only for scoring and the direct-data audit.",
        "No runtime or canonical promotion was performed.",
        "",
        "## Result",
        "",
        "| Metric | Arm Q2 | Arm Q3 |",
        "|---|---:|---:|",
        f"| Correct mixed partial | {q2['correct_mixed_partial']['successes']}/13 | {q3['correct_mixed_partial']['successes']}/13 |",
        f"| Span-strict mixed partial | {q2['correct_mixed_partial_span_strict']['successes']}/13 | {q3['correct_mixed_partial_span_strict']['successes']}/13 |",
        f"| Overclaim | {q2['mixed_overclaim']['successes']}/13 | {q3['mixed_overclaim']['successes']}/13 |",
        f"| Missing official evidence | {q2['mixed_missing_evidence']['successes']}/13 | {q3['mixed_missing_evidence']['successes']}/13 |",
        "",
        f"Decision: **{result['decision']}**. Context was applied to "
        f"{result['context_applied_count']} cases; one retrieval/partial-signal case remains.",
        "",
        "## Direct failure audit",
        "",
    ]
    for item in audit:
        lines.extend(
            [
                f"### {item['case_id']}",
                "",
                f"Question: {item['question']}",
                "",
                f"Type: `{item['first_failure_type']}`; Q3 fixed: `{item['q3_span_strict_fixed']}`.",
                "",
                item["rationale"],
                "",
                "Q2 claims:",
                "",
            ]
        )
        for claim in item["q2_claims"]:
            lines.append(
                f"- `{claim['citation_chunk_id']}` — {claim['claim_text']}"
            )
        lines.extend(["", "Gold evidence spans:", ""])
        for group in item["gold_evidence_groups"]:
            lines.append(f"- `{group['group_id']}` — {group['evidence_span']}")
        if item["route_audit"] is not None:
            lines.extend(
                [
                    "",
                    f"Chosen sources: `{item['route_audit']['chosen_source_ids']}`; candidate sources: `{item['route_audit']['candidate_sources']}`.",
                    f"Answerability signal: `{item['route_audit']['answerability']}` ({item['route_audit']['answerability_reason']}).",
                ]
            )
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "q2_cases": root / DEFAULT_Q2_CASES,
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "canonical_claim_reranker": root / DEFAULT_CLAIM_RERANKER,
        "authored_canary_runtime": root / DEFAULT_CANARY_RUNTIME,
        "federated_cases": root / DEFAULT_FEDERATED_CASES,
        "federated_candidates": root / DEFAULT_FEDERATED_CANDIDATES,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    q2_rows = read_jsonl(inputs["q2_cases"])
    evaluation_rows = read_jsonl(inputs["adaptive_dev"]) + read_jsonl(
        inputs["downgraded_canary"]
    )
    chunks = read_jsonl(inputs["chunks"])
    q3_rows = build_context_rows(
        q2_rows=q2_rows, evaluation_rows=evaluation_rows, chunks=chunks
    )
    audit = build_failure_audit(
        q2_rows=q2_rows,
        q3_rows=q3_rows,
        evaluation_rows=evaluation_rows,
        chunks=chunks,
        claim_reranker_rows=read_jsonl(inputs["canonical_claim_reranker"]),
        canary_rows=read_jsonl(inputs["authored_canary_runtime"]),
        federated_cases=read_jsonl(inputs["federated_cases"]),
        federated_candidates=read_jsonl(inputs["federated_candidates"]),
    )
    result = summarize_context(q3_rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_same_chunk_context_ab",
        "result": result,
        "audit": {
            "row_count": len(audit),
            "failure_type_counts": dict(
                sorted(Counter(row["first_failure_type"] for row in audit).items())
            ),
            "fixed_count": sum(row["q3_span_strict_fixed"] for row in audit),
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
            name: {"path": path.relative_to(root).as_posix(), "sha256": before[name]}
            for name, path in inputs.items()
        },
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(q3_rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"question_partial_context_ab_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    audit_bytes = _serialize_jsonl(audit, sort_key=lambda row: row["case_id"])
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    audit_path = evidence_dir / f"question_partial_context_error_audit_{audit_sha}.jsonl"
    write_immutable(audit_path, audit_bytes)
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"question_partial_context_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _render_markdown(report, audit)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"question_partial_context_ab_{markdown_sha}.md"
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
            "cases": {"path": cases_path.relative_to(root).as_posix(), "sha256": cases_sha, "row_count": len(q3_rows)},
            "error_audit": {"path": audit_path.relative_to(root).as_posix(), "sha256": audit_sha, "row_count": len(audit)},
            "report_json": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_md": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"question_partial_context_ab_manifest_{manifest_sha}.json"
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
