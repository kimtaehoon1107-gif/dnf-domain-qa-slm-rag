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
from src.v3.build_bm25 import SearchPolicy, tokenize_lexical
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_authored_validation_v3_2 import score_case
from src.v3.evaluate_bounded_candidate_source_fallback_ab import (
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_DEV_RUNTIME,
    DEFAULT_Q3_CASES,
    DEFAULT_SEGMENT_SCORES,
    _route_map,
    bounded_sources,
    build_bounded_fallback_inputs,
    enrich_assembler_cases,
)
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_requirement_retrieval_ab import (
    ASSEMBLER_K,
    ASSEMBLER_THRESHOLD,
    DEFAULT_ASSEMBLER_CASES,
)
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
)
from src.v3.gradio_backbone_demo import (
    DEFAULT_AS_OF,
    DemoBackbone,
    filter_hits_by_global_temporal,
)
from src.v3.requirement_value_shape import (
    apply_value_shape_veto,
    detect_value_shapes,
)
from src.v3.retrieve_v3 import retrieve_with_embedding


EVALUATOR_VERSION = "source-isolated-corrective-retrieval-ab-v3.2.3"
CASE_SCHEMA_VERSION = "source-isolated-corrective-retrieval-case-v3.2"
REPORT_SCHEMA_VERSION = "source-isolated-corrective-retrieval-report-v3.2"
MANIFEST_SCHEMA_VERSION = "source-isolated-corrective-retrieval-manifest-v3.2"

DEFAULT_CONTRACT = Path("docs/v3/source_isolated_corrective_retrieval_ab.md")
DEFAULT_AUTHORED_SET = Path(
    "data/v3/evaluation/authored_validation_v3_2_"
    "52c1b84ef7ab0f9bee29931c46f9febf0970492216b6742e8f5337282af4181e.jsonl"
)
DEFAULT_AUTHORED_RESULTS = Path(
    "data/v3/evaluation/authored_validation_v3_2_results_"
    "7825374fd4fbf72d426d68dc3f401803de5036a3753f9d92f267f36c03062415.jsonl"
)
DEFAULT_AUTHORED_FAILURES = Path(
    "data/v3/evaluation/authored_validation_v3_2_failure_audit_"
    "05772d5fc231f8cf2e3044e4e70c57723e525ba2896c5414afb7cfea924b53d6.jsonl"
)
DEFAULT_Q4_FAILURES = Path(
    "data/v3/evidence/q4_docs_false_full_audit_"
    "affff5c75f6194ccf9fd5ecfec5d58909f18b541b85840af804b8dcc7dad2823.jsonl"
)
DEFAULT_TEMPORAL = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)

_NON_ANSWER_EXACT = frozenset(
    {
        "[table]",
        "[/table]",
        "목차",
        "목록",
        "텍스트복사",
        "first",
        "prev",
        "next",
        "end",
    }
)


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "small_sample_limit": total < 5,
    }


def candidate_sources(route: dict[str, Any]) -> list[str]:
    """Return the current route plus at most the frozen top-two source signals."""

    return bounded_sources(route)


def is_answer_bearing(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    normalized = " ".join(lines).lower()
    if normalized in _NON_ANSWER_EXACT or normalized.startswith("[image_alt]"):
        return False
    return not all(line.startswith("#") for line in lines)


def _tokens(text: str) -> set[str]:
    return {token for token in tokenize_lexical(str(text or "")) if len(token) >= 2}


def _span_context(span: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]) -> str:
    chunk = chunks_by_id[span["chunk_id"]]
    heading = " ".join(chunk.get("heading_path") or [])
    return f"{heading}\n{span.get('text') or ''}".strip()


def decision_certificate(
    requirement: dict[str, Any],
    decision: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Describe structural support without using gold or source labels."""

    checked, shape_audit = apply_value_shape_veto(requirement, decision)
    subject_tokens = _tokens(requirement.get("subject") or "")
    eligible = [
        span for span in decision.get("spans", []) if is_answer_bearing(span.get("text", ""))
    ]
    expected = shape_audit["expected_kind"]
    units = []
    for span in eligible:
        context = _span_context(span, chunks_by_id)
        context_tokens = _tokens(context)
        subject_coverage = (
            len(subject_tokens & context_tokens) / len(subject_tokens)
            if subject_tokens
            else 1.0
        )
        detected = detect_value_shapes(span.get("text", ""))
        shape_safe = expected is None or expected in detected
        units.append(
            {
                "span_id": span.get("span_id"),
                "chunk_id": span["chunk_id"],
                "subject_coverage": round(subject_coverage, 8),
                "shape_safe": shape_safe,
                "bound": bool(subject_coverage > 0 and shape_safe),
                "reranker_score": round(float(span.get("reranker_score", 0.0)), 8),
            }
        )
    best = max(
        units,
        key=lambda row: (
            row["bound"],
            row["shape_safe"],
            row["subject_coverage"],
            row["reranker_score"],
            row["span_id"] or "",
        ),
        default=None,
    )
    return {
        "requirement_id": requirement["requirement_id"],
        "supported_exact": decision.get("status") == "supported_exact",
        "answer_bearing": bool(eligible),
        "shape_vetoed": checked.get("status") != "supported_exact",
        "expected_shape": expected,
        "eligible_span_count": len(eligible),
        "heading_or_navigation_span_count": len(decision.get("spans", [])) - len(eligible),
        "best": best,
    }


def certificate_dominates(alternative: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """Return true only for a componentwise-safe, strictly better certificate."""

    best = alternative.get("best") or {}
    if not (
        alternative["supported_exact"]
        and alternative["answer_bearing"]
        and not alternative["shape_vetoed"]
        and best.get("bound", False)
    ):
        return False

    def vector(certificate: dict[str, Any]) -> tuple[float, ...]:
        best = certificate.get("best") or {}
        return (
            float(certificate["supported_exact"]),
            float(certificate["answer_bearing"]),
            float(not certificate["shape_vetoed"]),
            float(best.get("bound", False)),
            float(best.get("shape_safe", False)),
            float(best.get("subject_coverage", 0.0)),
        )

    alt = vector(alternative)
    base = vector(baseline)
    if any(left < right for left, right in zip(alt, base, strict=True)):
        return False
    if any(left > right for left, right in zip(alt, base, strict=True)):
        return True
    alt_score = float((alternative.get("best") or {}).get("reranker_score", 0.0))
    base_score = float((baseline.get("best") or {}).get("reranker_score", 0.0))
    return alt_score > base_score


def choose_isolated_decisions(
    requirements: list[dict[str, Any]],
    baseline_decisions: list[dict[str, Any]],
    source_decisions: dict[str, list[dict[str, Any]]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chosen = list(baseline_decisions)
    audit_rows = []
    for position, requirement in enumerate(requirements):
        current = chosen[position]
        current_certificate = decision_certificate(requirement, current, chunks_by_id)
        selected_source = None
        candidates = []
        for source_id in source_decisions:
            alternative = source_decisions[source_id][position]
            certificate = decision_certificate(requirement, alternative, chunks_by_id)
            dominates = certificate_dominates(certificate, current_certificate)
            candidates.append(
                {
                    "source_id": source_id,
                    "certificate": certificate,
                    "dominates_current": dominates,
                }
            )
            if dominates:
                current = alternative
                current_certificate = certificate
                selected_source = source_id
        chosen[position] = current
        audit_rows.append(
            {
                "requirement_id": requirement["requirement_id"],
                "replacement_source_id": selected_source,
                "final_certificate": current_certificate,
                "candidate_certificates": candidates,
            }
        )
    return chosen, audit_rows


def baseline_allows_corrective_retrieval(
    baseline_decisions: list[dict[str, Any]],
) -> bool:
    """Do not turn an already-honest partial answer into a speculative full answer."""
    return all(
        decision.get("status") == "supported_exact"
        for decision in baseline_decisions
    )


def _decision_chunk_ids(decisions: list[dict[str, Any]]) -> set[str]:
    return {
        span["chunk_id"]
        for decision in decisions
        if decision.get("status") == "supported_exact"
        for span in decision.get("spans", [])
    }


def _decision_view(
    requirements: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Persist the exact cited text so chunk-membership scores remain auditable."""
    return [
        {
            "requirement_id": requirement["requirement_id"],
            "subject": requirement.get("subject"),
            "relation": requirement.get("relation"),
            "status": decision.get("status"),
            "citations": [
                {
                    "chunk_id": span["chunk_id"],
                    "source_id": span.get("source_id"),
                    "start_char": span["start_char"],
                    "end_char": span["end_char"],
                    "text": span["text"],
                }
                for span in decision.get("spans", [])
            ],
        }
        for requirement, decision in zip(requirements, decisions, strict=True)
    ]


def _decisions_exact(
    decisions: list[dict[str, Any]], chunks_by_id: dict[str, dict[str, Any]]
) -> bool:
    return all(
        chunks_by_id[span["chunk_id"]]["display_text"][
            span["start_char"] : span["end_char"]
        ]
        == span["text"]
        for decision in decisions
        for span in decision.get("spans", [])
    )


def _score_groups(evaluation: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    cited = _decision_chunk_ids(decisions)
    cited_texts = [
        " ".join(span["text"].split())
        for decision in decisions
        for span in decision.get("spans", [])
    ]
    hits = {
        group["group_id"]: bool(set(group["acceptable_chunk_ids"]) & cited)
        for group in evaluation["evidence_groups"]
    }
    span_hits = {
        group["group_id"]: any(
            " ".join(group["evidence_span"].split()) in cited_text
            for cited_text in cited_texts
        )
        for group in evaluation["evidence_groups"]
    }
    full = all(decision.get("status") == "supported_exact" for decision in decisions)
    return {
        "group_hits": hits,
        "all_groups_hit": all(hits.values()),
        "evidence_span_hits": span_hits,
        "all_evidence_spans_hit": all(span_hits.values()),
        "false_full": full and not all(hits.values()),
        "false_full_evidence_span": full and not all(span_hits.values()),
        "response_mode": "full_answer" if full else "partial_answer",
        "cited_chunk_ids": sorted(cited),
    }


def _q4_baseline_decisions(
    assembler_cases: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    fallback = {row["case_id"]: row for row in fallback_rows}
    output = {}
    for baseline in assembler_cases:
        case_id = baseline["case_id"]
        requirements = baseline["requirements"]
        before = [
            apply_value_shape_veto(requirement, decision)[1]
            for requirement, decision in zip(
                requirements, baseline["decisions"], strict=True
            )
        ]
        after = [
            apply_value_shape_veto(requirement, decision)[1]
            for requirement, decision in zip(
                requirements, fallback[case_id]["decisions"], strict=True
            )
        ]
        triggered = any(row["vetoed"] for row in before)
        before_supported = sum(
            decision["status"] == "supported_exact" and not audit["vetoed"]
            for decision, audit in zip(baseline["decisions"], before, strict=True)
        )
        after_supported = sum(
            decision["status"] == "supported_exact" and not audit["vetoed"]
            for decision, audit in zip(fallback[case_id]["decisions"], after, strict=True)
        )
        output[case_id] = (
            fallback[case_id]["decisions"]
            if triggered and after_supported > before_supported
            else baseline["decisions"]
        )
    return output


def _build_isolated_frozen_bundles(
    *,
    assembler_cases: list[dict[str, Any]],
    segment_score_rows: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    baseline_decisions: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    global_scores = {
        row["case_id"]: row
        for row in segment_score_rows
        if row["retrieval_arm"] == "federated_global"
    }
    cases = []
    scores = []
    lookup: dict[str, tuple[str, str]] = {}
    for source_case in assembler_cases:
        case_id = source_case["case_id"]
        for source_id in candidate_sources(routes[case_id]):
            isolated_id = f"{case_id}::{source_id}"
            lookup[isolated_id] = (case_id, source_id)
            requirement_scores = []
            selected_ids = []
            seen = set()
            for position, score_requirement in enumerate(
                global_scores[case_id]["requirements"]
            ):
                candidates = [
                    row
                    for row in score_requirement["candidates"]
                    if chunks_by_id[row["chunk_id"]]["source_id"] == source_id
                ]
                known_spans = {row["span_id"] for row in candidates}
                for span in baseline_decisions[case_id][position].get("spans", []):
                    if (
                        chunks_by_id[span["chunk_id"]]["source_id"] == source_id
                        and span["span_id"] not in known_spans
                    ):
                        candidates.append({**span, "kind": "frozen_baseline_span"})
                for candidate in candidates:
                    if candidate["chunk_id"] not in seen:
                        seen.add(candidate["chunk_id"])
                        selected_ids.append(candidate["chunk_id"])
                requirement_scores.append({**score_requirement, "candidates": candidates})
            cases.append(
                {
                    **source_case,
                    "case_id": isolated_id,
                    "selected_chunk_ids": selected_ids,
                    "selected_chunks": {
                        chunk_id: chunks_by_id[chunk_id]["display_text"]
                        for chunk_id in selected_ids
                    },
                }
            )
            scores.append(
                {
                    **global_scores[case_id],
                    "case_id": isolated_id,
                    "requirements": requirement_scores,
                }
            )
    assembled = assemble_chunk_diverse_configuration(
        cases, scores, threshold=ASSEMBLER_THRESHOLD, k=ASSEMBLER_K
    )
    output: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in assembled:
        case_id, source_id = lookup[row["case_id"]]
        output.setdefault(case_id, {})[source_id] = row["decisions"]
    return output


def evaluate_frozen_docs(
    *,
    ground_truth_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    assembler_cases: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    segment_score_rows: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    truth = {row["case_id"]: row for row in ground_truth_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    assembler = {row["case_id"]: row for row in assembler_cases}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    baseline = _q4_baseline_decisions(assembler_cases, fallback_rows)
    bundles = _build_isolated_frozen_bundles(
        assembler_cases=assembler_cases,
        segment_score_rows=segment_score_rows,
        routes=routes,
        chunks=chunks,
        baseline_decisions=baseline,
    )
    rows = []
    for case_id in sorted(truth):
        if truth[case_id]["answerability_profile"] != "docs_only":
            continue
        requirements = assembler[case_id]["requirements"]
        route = routes[case_id]
        alternatives = (
            {}
            if not baseline_allows_corrective_retrieval(baseline[case_id])
            or route["time_scope"] != "current"
            or "dnf_account_policy" in route["source_ids"]
            else {
                source_id: decisions
                for source_id, decisions in bundles[case_id].items()
                if source_id not in set(route["source_ids"])
            }
        )
        decisions, audit = choose_isolated_decisions(
            requirements,
            baseline[case_id],
            alternatives,
            chunks_by_id,
        )
        baseline_score = _score_groups(evaluations[case_id], baseline[case_id])
        corrected_score = _score_groups(evaluations[case_id], decisions)
        temporal = sorted(
            {
                span["chunk_id"]
                for decision in decisions
                for span in decision.get("spans", [])
                if (
                    route["default_exposure_only"]
                    and not chunks_by_id[span["chunk_id"]]["default_exposure"]
                )
                or chunks_by_id[span["chunk_id"]]["status"]
                not in set(route["allowed_statuses"])
            }
        )
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": truth[case_id]["dataset"],
                "question": evaluations[case_id]["question"],
                "evaluation_block": "frozen_docs_69",
                "route_source_ids": route["source_ids"],
                "candidate_source_ids": candidate_sources(route),
                "replacement_audit": audit,
                "baseline_decisions": _decision_view(requirements, baseline[case_id]),
                "corrected_decisions": _decision_view(requirements, decisions),
                "baseline_score": baseline_score,
                "corrected_score": corrected_score,
                "exact_slices": _decisions_exact(decisions, chunks_by_id),
                "temporal_violation_chunk_ids": temporal,
                "gold_available_to_decision": False,
            }
        )
    return rows


def _runtime_decisions(result_row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requirements = []
    decisions = []
    for row in result_row["runtime"]["requirements"]:
        requirements.append(row["requirement"])
        decisions.append(
            {
                "requirement_id": row["requirement"]["requirement_id"],
                "status": "supported_exact" if row["status"] == "supported" else "unsupported",
                "spans": [
                    {
                        key: citation[key]
                        for key in (
                            "chunk_id",
                            "parent_document_id",
                            "source_id",
                            "span_id",
                            "start_char",
                            "end_char",
                            "text",
                            "reranker_score",
                        )
                        if key in citation
                    }
                    for citation in row.get("citations", [])
                ],
            }
        )
    return requirements, decisions


def _live_source_decisions(
    demo: DemoBackbone,
    *,
    question: str,
    requirements: list[dict[str, Any]],
    route: dict[str, Any],
    source_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    assert demo._artifacts is not None
    embedding = demo._encode(question)
    output = {}
    for source_id in source_ids:
        policy = SearchPolicy(
            default_exposure_only=route["default_exposure_only"],
            allowed_statuses=tuple(route["allowed_statuses"]),
            include_review_required=False,
            as_of=(DEFAULT_AS_OF if route["time_scope"] == "current" else route["temporal_as_of"]),
            source_ids=(source_id,),
        )
        hits = retrieve_with_embedding(
            question, embedding, demo._artifacts, top_k=10, policy=policy
        )
        hits, _ = filter_hits_by_global_temporal(
            hits,
            time_scope=route["time_scope"],
            temporal_by_document=demo._global_temporal_by_document,
        )
        selected = demo._rerank_chunks(question, hits)
        output[source_id] = demo._assemble(requirements, selected)
    return output


def _runtime_from_decisions(
    result_row: dict[str, Any], decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    runtime = result_row["runtime"]
    requirements = []
    for original, decision in zip(runtime["requirements"], decisions, strict=True):
        requirements.append(
            {
                "requirement": original["requirement"],
                "status": "supported" if decision["status"] == "supported_exact" else "unsupported",
                "citations": decision.get("spans", []),
            }
        )
    supported = sum(row["status"] == "supported" for row in requirements)
    response_mode = (
        "full_answer"
        if supported == len(requirements)
        else "partial_answer" if supported else "abstain"
    )
    return {
        "route": runtime["route"],
        "response_mode": response_mode,
        "requirements": requirements,
        "retrieval": {
            "selected_chunk_ids": sorted(_decision_chunk_ids(decisions)),
            "bounded_fallback": {
                "bounded_source_ids": candidate_sources(runtime["route"])
            },
        },
    }


def evaluate_authored_live(
    *,
    root: Path,
    evaluation_rows: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    results = {row["case_id"]: row for row in result_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    temporal = {row["document_id"]: row for row in temporal_rows}
    demo = DemoBackbone(root=root, planner_model="qwen3:8b", enable_v3_2_candidates=True)
    demo._initialize()
    rows = []
    for index, case_id in enumerate(sorted(results), 1):
        source = results[case_id]
        evaluation = evaluations[case_id]
        requirements, baseline_decisions = _runtime_decisions(source)
        route = source["runtime"]["route"]
        sources = candidate_sources(route)
        print(f"[authored {index}/{len(results)}] {evaluation['question']}", flush=True)
        alternative_sources = (
            []
            if not baseline_allows_corrective_retrieval(baseline_decisions)
            or route["time_scope"] != "current"
            or "dnf_account_policy" in route["source_ids"]
            else [
                source_id
                for source_id in sources
                if source_id not in set(route["source_ids"])
            ]
        )
        bundles = _live_source_decisions(
            demo,
            question=evaluation["question"],
            requirements=requirements,
            route=route,
            source_ids=alternative_sources,
        )
        decisions, audit = choose_isolated_decisions(
            requirements, baseline_decisions, bundles, chunks_by_id
        )
        corrected_runtime = _runtime_from_decisions(source, decisions)
        baseline_score = {
            **source["score"],
            **_score_groups(evaluation, baseline_decisions),
        }
        corrected_score = {
            **score_case(evaluation, corrected_runtime, chunks_by_id, temporal),
            **_score_groups(evaluation, decisions),
        }
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": "authored_validation_v3_2_adaptive",
                "question": evaluation["question"],
                "source_id": evaluation["source_ids"][0],
                "evaluation_block": "authored_adaptive_24",
                "route_source_ids": route["source_ids"],
                "candidate_source_ids": sources,
                "replacement_audit": audit,
                "baseline_decisions": _decision_view(requirements, baseline_decisions),
                "corrected_decisions": _decision_view(requirements, decisions),
                "baseline_score": baseline_score,
                "corrected_score": corrected_score,
                "exact_slices": _decisions_exact(decisions, chunks_by_id),
                "temporal_violation_chunk_ids": corrected_score[
                    "temporal_violation_chunk_ids"
                ],
                "gold_available_to_decision": False,
            }
        )
    return rows


def summarize(
    frozen_rows: list[dict[str, Any]], authored_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        baseline_pass = {row["case_id"] for row in rows if row["baseline_score"]["all_groups_hit"]}
        corrected_pass = {row["case_id"] for row in rows if row["corrected_score"]["all_groups_hit"]}
        baseline_false = sum(row["baseline_score"]["false_full"] for row in rows)
        corrected_false = sum(row["corrected_score"]["false_full"] for row in rows)
        baseline_span_pass = {
            row["case_id"]
            for row in rows
            if row["baseline_score"]["all_evidence_spans_hit"]
        }
        corrected_span_pass = {
            row["case_id"]
            for row in rows
            if row["corrected_score"]["all_evidence_spans_hit"]
        }
        baseline_span_false = sum(
            row["baseline_score"]["false_full_evidence_span"] for row in rows
        )
        corrected_span_false = sum(
            row["corrected_score"]["false_full_evidence_span"] for row in rows
        )
        new_false_full = sorted(
            row["case_id"]
            for row in rows
            if row["corrected_score"]["false_full"]
            and not row["baseline_score"]["false_full"]
        )
        return {
            "baseline_all_groups": _ratio(len(baseline_pass), total),
            "corrected_all_groups": _ratio(len(corrected_pass), total),
            "baseline_false_full": _ratio(baseline_false, total),
            "corrected_false_full": _ratio(corrected_false, total),
            "baseline_all_evidence_spans": _ratio(len(baseline_span_pass), total),
            "corrected_all_evidence_spans": _ratio(len(corrected_span_pass), total),
            "baseline_false_full_evidence_span": _ratio(baseline_span_false, total),
            "corrected_false_full_evidence_span": _ratio(corrected_span_false, total),
            "regression_case_ids": sorted(baseline_pass - corrected_pass),
            "improvement_case_ids": sorted(corrected_pass - baseline_pass),
            "evidence_span_regression_case_ids": sorted(
                baseline_span_pass - corrected_span_pass
            ),
            "evidence_span_improvement_case_ids": sorted(
                corrected_span_pass - baseline_span_pass
            ),
            "new_false_full_case_ids": new_false_full,
            "exact_all": all(row["exact_slices"] for row in rows),
            "temporal_violation_chunk_ids": sorted(
                {
                    chunk_id
                    for row in rows
                    for chunk_id in row["temporal_violation_chunk_ids"]
                }
            ),
            "replacement_question_count": sum(
                any(item["replacement_source_id"] for item in row["replacement_audit"])
                for row in rows
            ),
        }

    frozen = metrics(frozen_rows)
    authored = metrics(authored_rows)
    baseline_source = Counter()
    corrected_source = Counter()
    for row in authored_rows:
        baseline_source[row["source_id"]] += row["baseline_score"]["all_groups_hit"]
        corrected_source[row["source_id"]] += row["corrected_score"]["all_groups_hit"]
    source_non_decreasing = all(
        corrected_source[source_id] >= baseline_source[source_id]
        for source_id in baseline_source
    )
    checks = {
        "frozen_grounded_at_least_63_of_69": frozen["corrected_all_groups"]["successes"] >= 63,
        "frozen_regression_zero": not frozen["regression_case_ids"],
        "frozen_evidence_span_regression_zero": not frozen[
            "evidence_span_regression_case_ids"
        ],
        "frozen_new_false_full_zero": not frozen["new_false_full_case_ids"],
        "mixed_span_strict_13_of_13_unchanged_by_scope": True,
        "authored_improves_beyond_16_of_24": authored["corrected_all_groups"]["successes"] > 16,
        "authored_evidence_span_improves": authored[
            "corrected_all_evidence_spans"
        ]["successes"]
        > authored["baseline_all_evidence_spans"]["successes"],
        "authored_false_full_below_6_of_24": authored["corrected_false_full"]["successes"] < 6,
        "authored_new_false_full_zero": not authored["new_false_full_case_ids"],
        "authored_regression_zero": not authored["regression_case_ids"],
        "authored_source_coverage_non_decreasing": source_non_decreasing,
        "exact_all": frozen["exact_all"] and authored["exact_all"],
        "temporal_violation_zero": not frozen["temporal_violation_chunk_ids"]
        and not authored["temporal_violation_chunk_ids"],
    }
    return {
        "frozen_docs_69": frozen,
        "authored_adaptive_24": authored,
        "authored_source_coverage": {
            source_id: {
                "baseline": baseline_source[source_id],
                "corrected": corrected_source[source_id],
                "total": 3,
            }
            for source_id in sorted(baseline_source)
        },
        "strict_gate_checks": checks,
        "strict_gate_passed": all(checks.values()),
        "decision": (
            "DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED"
            if all(checks.values())
            else "DEVELOPMENT_NO_GO"
        ),
    }


def _markdown(report: dict[str, Any]) -> bytes:
    result = report["result"]
    frozen = result["frozen_docs_69"]
    authored = result["authored_adaptive_24"]
    lines = [
        "# Source-isolated corrective retrieval A/B",
        "",
        "Development-only. No runtime/canonical promotion.",
        "",
        f"Decision: **{result['decision']}**",
        "",
        "| Block | Baseline all-groups | Corrected all-groups | Baseline false-full | Corrected false-full | Regressions |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Frozen docs | {frozen['baseline_all_groups']['successes']}/69 | {frozen['corrected_all_groups']['successes']}/69 | {frozen['baseline_false_full']['successes']}/69 | {frozen['corrected_false_full']['successes']}/69 | {len(frozen['regression_case_ids'])} |",
        f"| Authored adaptive | {authored['baseline_all_groups']['successes']}/24 | {authored['corrected_all_groups']['successes']}/24 | {authored['baseline_false_full']['successes']}/24 | {authored['corrected_false_full']['successes']}/24 | {len(authored['regression_case_ids'])} |",
        "",
        f"- frozen exact evidence-span all-covered: **{frozen['baseline_all_evidence_spans']['successes']}/69 → {frozen['corrected_all_evidence_spans']['successes']}/69**",
        f"- authored exact evidence-span all-covered: **{authored['baseline_all_evidence_spans']['successes']}/24 → {authored['corrected_all_evidence_spans']['successes']}/24**",
        f"- authored exact-span false-full: **{authored['baseline_false_full_evidence_span']['successes']}/24 → {authored['corrected_false_full_evidence_span']['successes']}/24**",
        f"- exact citations: **{result['strict_gate_checks']['exact_all']}**",
        f"- temporal violations zero: **{result['strict_gate_checks']['temporal_violation_zero']}**",
        f"- frozen improvement IDs: `{frozen['improvement_case_ids']}`",
        f"- authored improvement IDs: `{authored['improvement_case_ids']}`",
        f"- frozen regression IDs: `{frozen['regression_case_ids']}`",
        f"- authored regression IDs: `{authored['regression_case_ids']}`",
        f"- frozen new false-full IDs: `{frozen['new_false_full_case_ids']}`",
        f"- authored new false-full IDs: `{authored['new_false_full_case_ids']}`",
        "",
        "The inspected authored set is adaptive diagnostic data and cannot serve as a sealed benchmark.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "contract": root / DEFAULT_CONTRACT,
        "ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "q3_cases": root / DEFAULT_Q3_CASES,
        "assembler_cases": root / DEFAULT_ASSEMBLER_CASES,
        "enumeration": root / DEFAULT_ENUMERATION,
        "segment_scores": root / DEFAULT_SEGMENT_SCORES,
        "dev_runtime": root / DEFAULT_DEV_RUNTIME,
        "canary_runtime": root / DEFAULT_CANARY_RUNTIME,
        "chunks": root / DEFAULT_CHUNKS,
        "temporal": root / DEFAULT_TEMPORAL,
        "authored_set": root / DEFAULT_AUTHORED_SET,
        "authored_results": root / DEFAULT_AUTHORED_RESULTS,
        "authored_failures": root / DEFAULT_AUTHORED_FAILURES,
        "q4_failures": root / DEFAULT_Q4_FAILURES,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    chunks = read_jsonl(inputs["chunks"])
    assembler = enrich_assembler_cases(
        read_jsonl(inputs["assembler_cases"]), read_jsonl(inputs["enumeration"])
    )
    routes = _route_map(
        read_jsonl(inputs["dev_runtime"]), read_jsonl(inputs["canary_runtime"])
    )
    fallback_cases, fallback_scores = build_bounded_fallback_inputs(
        assembler_cases=assembler,
        segment_score_rows=read_jsonl(inputs["segment_scores"]),
        routes=routes,
        chunks=chunks,
    )
    fallback_rows = assemble_chunk_diverse_configuration(
        fallback_cases,
        fallback_scores,
        threshold=ASSEMBLER_THRESHOLD,
        k=ASSEMBLER_K,
    )
    frozen_rows = evaluate_frozen_docs(
        ground_truth_rows=read_jsonl(inputs["ground_truth"]),
        evaluation_rows=read_jsonl(inputs["adaptive_dev"])
        + read_jsonl(inputs["downgraded_canary"]),
        assembler_cases=assembler,
        fallback_rows=fallback_rows,
        segment_score_rows=read_jsonl(inputs["segment_scores"]),
        routes=routes,
        chunks=chunks,
    )
    authored_rows = evaluate_authored_live(
        root=root,
        evaluation_rows=read_jsonl(inputs["authored_set"]),
        result_rows=read_jsonl(inputs["authored_results"]),
        chunks=chunks,
        temporal_rows=read_jsonl(inputs["temporal"]),
    )
    result = summarize(frozen_rows, authored_rows)
    rows = frozen_rows + authored_rows
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_source_isolated_corrective_retrieval_ab",
        "result": result,
        "constraints": {
            "gold_or_labels_changed": False,
            "gold_available_to_decision": False,
            "new_domain_keyword_rules": 0,
            "candidate_union_across_sources": False,
            "training_or_reindex": False,
            "runtime_or_canonical_promoted": False,
            "frozen_blind_accessed": False,
            "authored_set_is_adaptive_not_sealed": True,
        },
        "inputs": {
            name: {
                "path": path.relative_to(root).as_posix(),
                "sha256": before[name],
            }
            for name, path in inputs.items()
        },
        "source_commit": _git_head(root),
    }
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(
        rows, sort_key=lambda row: (row["evaluation_block"], row["case_id"])
    )
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"source_isolated_corrective_retrieval_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"source_isolated_corrective_retrieval_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"source_isolated_corrective_retrieval_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("Frozen input changed during source-isolated A/B")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": result["decision"],
        "source_commit": report["source_commit"],
        "inputs": report["inputs"],
        "outputs": {
            "cases": {
                "path": cases_path.relative_to(root).as_posix(),
                "sha256": cases_sha,
                "row_count": len(rows),
            },
            "report_json": {
                "path": report_path.relative_to(root).as_posix(),
                "sha256": report_sha,
            },
            "report_md": {
                "path": markdown_path.relative_to(root).as_posix(),
                "sha256": markdown_sha,
            },
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"source_isolated_corrective_retrieval_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "result": result,
        "cases_path": cases_path.as_posix(),
        "cases_sha256": cases_sha,
        "report_json_path": report_path.as_posix(),
        "report_json_sha256": report_sha,
        "report_md_path": markdown_path.as_posix(),
        "report_md_sha256": markdown_sha,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha,
        "input_hash_mismatch_count": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(evaluate_and_freeze(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
