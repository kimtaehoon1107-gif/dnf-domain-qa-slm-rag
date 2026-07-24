from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_authored_validation_v3_2 import score_case
from src.v3.evaluate_bounded_candidate_source_fallback_ab import (
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_DEV_RUNTIME,
    DEFAULT_Q3_CASES,
    DEFAULT_SEGMENT_SCORES,
    _route_map,
    build_bounded_fallback_inputs,
    enrich_assembler_cases,
)
from src.v3.evaluate_extractive_assembler_v3 import segment_chunk_nonoverlap
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_requirement_retrieval_ab import (
    ASSEMBLER_K,
    ASSEMBLER_THRESHOLD,
    DEFAULT_ASSEMBLER_CASES,
)
from src.v3.evaluate_requirement_reranker import requirement_text
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
)
from src.v3.evaluate_source_isolated_corrective_retrieval_ab import (
    DEFAULT_AUTHORED_RESULTS,
    DEFAULT_AUTHORED_SET,
    DEFAULT_TEMPORAL,
    _build_isolated_frozen_bundles,
    _decision_view,
    _decisions_exact,
    _live_source_decisions,
    _q4_baseline_decisions,
    _ratio,
    _runtime_decisions,
    _runtime_from_decisions,
    _score_groups,
    _tokens,
    baseline_allows_corrective_retrieval,
    candidate_sources,
    choose_isolated_decisions,
    is_answer_bearing,
)
from src.v3.gradio_backbone_demo import (
    DEFAULT_AS_OF,
    DemoBackbone,
    filter_hits_by_global_temporal,
)
from src.v3.requirement_value_shape import (
    detect_value_shapes,
    normalize_expected_value_shape,
)
from src.v3.retrieve_v3 import retrieve_with_embedding


EVALUATOR_VERSION = "contextual-answer-unit-ab-v3.2.5"
CASE_SCHEMA_VERSION = "contextual-answer-unit-ab-case-v3.2"
REPORT_SCHEMA_VERSION = "contextual-answer-unit-ab-report-v3.2"
MANIFEST_SCHEMA_VERSION = "contextual-answer-unit-ab-manifest-v3.2"

DEFAULT_CONTRACT = Path("docs/v3/contextual_answer_unit_ab.md")
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)

STRUCTURAL_PREFIX = ("#", "■", "▒")
MARKER_LINES = frozenset({"[table]", "[/table]", "목록", "텍스트복사"})
MAX_LOCAL_LABELS = 2
MAX_LABEL_CHARS = 30


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        normalized = " ".join(str(value or "").split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def _prior_lines(text: str, start_char: int) -> list[str]:
    return [line.strip() for line in text[:start_char].splitlines() if line.strip()]


def _table_row_retrieval_text(text: str) -> str:
    """Normalize compact Korean duration labels only in retrieval context."""

    return re.sub(r"(?<!\d)(\d+)\s*월(?=\s*\(\s*만원\s*\))", r"\1개월", text)


def contextual_retrieval_text(
    chunk: dict[str, Any],
    segment: dict[str, Any],
    *,
    document_title: str,
) -> str:
    """Add value-free identity context while keeping the cited segment unchanged."""

    prior = _prior_lines(chunk["display_text"], int(segment["start_char"]))
    headings = [line.lstrip("# ").strip() for line in prior if line.startswith(STRUCTURAL_PREFIX)]
    inline_heading = headings[-1] if headings else ""

    table_header = ""
    if segment.get("kind") == "table_row":
        for line in reversed(prior):
            if (
                line.count("|") >= 2
                and not re.search(r"\d", line)
                and not detect_value_shapes(line)
            ):
                table_header = line
                break

    labels = []
    for line in reversed(prior):
        normalized = " ".join(line.split())
        if normalized.lower() in MARKER_LINES:
            continue
        if line.startswith(STRUCTURAL_PREFIX) or line.count("|") >= 2:
            continue
        if line.startswith(("-", "*", "※")) or re.search(r"[.!?。！？]$", normalized):
            continue
        if (
            len(normalized) > MAX_LABEL_CHARS
            or re.search(r"\d", normalized)
            or detect_value_shapes(normalized)
        ):
            continue
        if not is_answer_bearing(normalized):
            continue
        labels.append(normalized)
        if len(labels) == MAX_LOCAL_LABELS:
            break
    labels.reverse()

    context = _dedupe(
        [
            document_title,
            *(chunk.get("heading_path") or []),
            inline_heading,
            table_header,
            *labels,
        ]
    )
    segment_text = segment["text"]
    if segment.get("kind") == "table_row":
        segment_text = _table_row_retrieval_text(segment_text)
    return "\n".join([*context, segment_text])


def _enrich_decisions(
    decisions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_span = {row["span_id"]: row for row in candidates}
    output = []
    for decision in decisions:
        spans = []
        for span in decision.get("spans", []):
            candidate = by_span[span["span_id"]]
            chunk = chunks_by_id[span["chunk_id"]]
            spans.append(
                {
                    **span,
                    "parent_document_id": chunk["parent_document_id"],
                    "source_id": chunk["source_id"],
                    "answer_unit_context": candidate["answer_unit_context"],
                    "kind": candidate.get("kind"),
                }
            )
        output.append({**decision, "spans": spans})
    return output


def assemble_contextual_answer_units(
    demo: DemoBackbone,
    requirements: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    *,
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    assert demo._artifacts is not None
    assert demo._assembler_config is not None
    selected_ids = [row["chunk_id"] for row in selected]
    selected_chunks = {
        chunk_id: demo._artifacts.chunks_by_id[chunk_id]["display_text"]
        for chunk_id in selected_ids
    }
    segments = []
    for chunk_id in selected_ids:
        chunk = demo._artifacts.chunks_by_id[chunk_id]
        document = documents_by_id[chunk["parent_document_id"]]
        for segment in segment_chunk_nonoverlap(chunk_id, chunk["display_text"]):
            segments.append(
                {
                    **segment,
                    "answer_unit_context": contextual_retrieval_text(
                        chunk,
                        segment,
                        document_title=document.get("title") or "",
                    ),
                }
            )
    score_requirements = []
    for index, requirement in enumerate(requirements, 1):
        query = requirement_text(requirement)
        scores = demo._score_pairs(
            [(query, row["answer_unit_context"]) for row in segments]
        )
        score_requirements.append(
            {
                "requirement_index": index,
                "requirement_id": requirement["requirement_id"],
                "query": query,
                "candidates": [
                    {**segment, "reranker_score": round(float(score), 8)}
                    for segment, score in zip(segments, scores, strict=True)
                ],
            }
        )
    case = {
        "case_id": "contextual_case",
        "dataset": "development_contextual_answer_unit",
        "requirements": requirements,
        "selected_chunk_ids": selected_ids,
        "selected_chunks": selected_chunks,
    }
    score_row = {"case_id": "contextual_case", "requirements": score_requirements}
    assembled = assemble_chunk_diverse_configuration(
        [case],
        [score_row],
        threshold=float(demo._assembler_config["threshold"]),
        k=int(demo._assembler_config["k"]),
    )[0]["decisions"]
    return _enrich_decisions(
        assembled,
        [row for requirement in score_requirements for row in requirement["candidates"]],
        demo._artifacts.chunks_by_id,
    )


def contextual_certificate(
    requirement: dict[str, Any],
    decision: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    subject_tokens = _tokens(requirement.get("subject") or "")
    expected = normalize_expected_value_shape(requirement)["expected_kind"]
    units = []
    for span in decision.get("spans", []):
        if not is_answer_bearing(span.get("text", "")):
            continue
        context = span.get("answer_unit_context") or "\n".join(
            [
                " ".join(chunks_by_id[span["chunk_id"]].get("heading_path") or []),
                span.get("text") or "",
            ]
        )
        context_tokens = _tokens(context)
        coverage = (
            len(subject_tokens & context_tokens) / len(subject_tokens)
            if subject_tokens
            else 1.0
        )
        exact_text = span.get("text", "")
        detected = detect_value_shapes(exact_text)
        numeric_table_value = bool(
            span.get("kind") == "table_row"
            and re.search(r"\d", exact_text)
            and expected in {"cost_value", "count_value"}
        )
        shape_safe = expected is None or expected in detected or numeric_table_value
        units.append(
            {
                "span_id": span.get("span_id"),
                "chunk_id": span["chunk_id"],
                "parent_document_id": chunks_by_id[span["chunk_id"]][
                    "parent_document_id"
                ],
                "text": span.get("text"),
                "answer_unit_context": context,
                "kind": span.get("kind"),
                "subject_coverage": round(coverage, 8),
                "shape_safe": shape_safe,
                "bound": bool(coverage > 0 and shape_safe),
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
        "answer_bearing": bool(units),
        "shape_vetoed": bool(
            decision.get("status") == "supported_exact"
            and expected is not None
            and not any(row["shape_safe"] for row in units)
        ),
        "best": best,
    }


def contextual_certificate_dominates(
    alternative: dict[str, Any], baseline: dict[str, Any]
) -> bool:
    best = alternative.get("best") or {}
    if not (
        alternative["supported_exact"]
        and alternative["answer_bearing"]
        and not alternative["shape_vetoed"]
        and best.get("bound", False)
    ):
        return False

    def vector(certificate: dict[str, Any]) -> tuple[float, ...]:
        unit = certificate.get("best") or {}
        return (
            float(certificate["supported_exact"]),
            float(certificate["answer_bearing"]),
            float(not certificate["shape_vetoed"]),
            float(unit.get("bound", False)),
            float(unit.get("shape_safe", False)),
            float(unit.get("subject_coverage", 0.0)),
        )

    alt = vector(alternative)
    base = vector(baseline)
    if any(left < right for left, right in zip(alt, base, strict=True)):
        return False
    return any(left > right for left, right in zip(alt, base, strict=True))


def choose_contextual_decisions(
    requirements: list[dict[str, Any]],
    baseline_decisions: list[dict[str, Any]],
    source_decisions: dict[str, list[dict[str, Any]]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chosen = list(baseline_decisions)
    audit = []
    for position, requirement in enumerate(requirements):
        current = chosen[position]
        current_certificate = contextual_certificate(requirement, current, chunks_by_id)
        replacement = None
        candidates = []
        for source_id in source_decisions:
            alternative = source_decisions[source_id][position]
            certificate = contextual_certificate(requirement, alternative, chunks_by_id)
            dominates = contextual_certificate_dominates(certificate, current_certificate)
            current_best = current_certificate.get("best") or {}
            candidate_best = certificate.get("best") or {}
            parent_safe = bool(
                candidate_best.get("kind") == "table_row"
                or candidate_best.get("parent_document_id")
                == current_best.get("parent_document_id")
            )
            dominates = dominates and parent_safe
            candidates.append(
                {
                    "source_id": source_id,
                    "certificate": certificate,
                    "parent_boundary_safe": parent_safe,
                    "dominates_current": dominates,
                }
            )
            if dominates:
                current = alternative
                current_certificate = certificate
                replacement = source_id
        chosen[position] = current
        audit.append(
            {
                "requirement_id": requirement["requirement_id"],
                "replacement_source_id": replacement,
                "final_certificate": current_certificate,
                "candidate_certificates": candidates,
            }
        )
    return chosen, audit


def _contextual_live_sources(
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
            as_of=DEFAULT_AS_OF,
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
        output[source_id] = assemble_contextual_answer_units(
            demo,
            requirements,
            selected,
            documents_by_id=demo._artifacts.documents_by_id,
        )
    return output


def _contextual_frozen_bundles(
    *,
    demo: DemoBackbone,
    assembler_cases: list[dict[str, Any]],
    segment_score_rows: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    global_scores = {
        row["case_id"]: row
        for row in segment_score_rows
        if row["retrieval_arm"] == "federated_global"
    }
    cases = []
    scores = []
    lookup = {}
    candidate_contexts: dict[str, dict[str, dict[str, Any]]] = {}
    for case in assembler_cases:
        case_id = case["case_id"]
        for source_id in candidate_sources(routes[case_id]):
            isolated_id = f"{case_id}::{source_id}"
            lookup[isolated_id] = (case_id, source_id)
            requirements = []
            selected_ids = []
            seen = set()
            candidate_contexts[isolated_id] = {}
            for score_requirement in global_scores[case_id]["requirements"]:
                raw_candidates = [
                    row
                    for row in score_requirement["candidates"]
                    if chunks_by_id[row["chunk_id"]]["source_id"] == source_id
                ]
                contextual = []
                for candidate in raw_candidates:
                    chunk = chunks_by_id[candidate["chunk_id"]]
                    document = documents_by_id[chunk["parent_document_id"]]
                    answer_context = contextual_retrieval_text(
                        chunk,
                        candidate,
                        document_title=document.get("title") or "",
                    )
                    enriched = {**candidate, "answer_unit_context": answer_context}
                    contextual.append(enriched)
                    candidate_contexts[isolated_id][candidate["span_id"]] = enriched
                    if candidate["chunk_id"] not in seen:
                        seen.add(candidate["chunk_id"])
                        selected_ids.append(candidate["chunk_id"])
                query = score_requirement["query"]
                reranker_scores = demo._score_pairs(
                    [(query, row["answer_unit_context"]) for row in contextual]
                )
                requirements.append(
                    {
                        **score_requirement,
                        "candidates": [
                            {**row, "reranker_score": round(float(value), 8)}
                            for row, value in zip(contextual, reranker_scores, strict=True)
                        ],
                    }
                )
            cases.append(
                {
                    **case,
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
                    "requirements": requirements,
                }
            )
    assembled = assemble_chunk_diverse_configuration(
        cases, scores, threshold=ASSEMBLER_THRESHOLD, k=ASSEMBLER_K
    )
    output: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in assembled:
        case_id, source_id = lookup[row["case_id"]]
        all_candidates = [
            candidate
            for requirement in next(
                score for score in scores if score["case_id"] == row["case_id"]
            )["requirements"]
            for candidate in requirement["candidates"]
        ]
        output.setdefault(case_id, {})[source_id] = _enrich_decisions(
            row["decisions"], all_candidates, chunks_by_id
        )
    return output


def _temporal_violations(
    decisions: list[dict[str, Any]],
    route: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    return sorted(
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


def _context_decision_view(
    requirements: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = _decision_view(requirements, decisions)
    for row, decision in zip(rows, decisions, strict=True):
        for citation, span in zip(row["citations"], decision.get("spans", []), strict=True):
            citation["answer_unit_context"] = span.get("answer_unit_context")
    return rows


def evaluate_frozen(
    *,
    demo: DemoBackbone,
    ground_truth: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    assembler: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    segment_scores: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    truth = {row["case_id"]: row for row in ground_truth}
    eval_by_id = {row["dev_id"]: row for row in evaluations}
    assembler_by_id = {row["case_id"]: row for row in assembler}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    raw_baseline = _q4_baseline_decisions(assembler, fallback_rows)
    source_bundles = _build_isolated_frozen_bundles(
        assembler_cases=assembler,
        segment_score_rows=segment_scores,
        routes=routes,
        chunks=chunks,
        baseline_decisions=raw_baseline,
    )
    contextual_bundles = _contextual_frozen_bundles(
        demo=demo,
        assembler_cases=assembler,
        segment_score_rows=segment_scores,
        routes=routes,
        chunks=chunks,
        documents=documents,
    )
    rows = []
    for case_id in sorted(truth):
        if truth[case_id]["answerability_profile"] != "docs_only":
            continue
        requirements = assembler_by_id[case_id]["requirements"]
        route = routes[case_id]
        eligible = (
            baseline_allows_corrective_retrieval(raw_baseline[case_id])
            and route["time_scope"] == "current"
            and "dnf_account_policy" not in route["source_ids"]
        )
        source_alternatives = (
            {
                source_id: decisions
                for source_id, decisions in source_bundles[case_id].items()
                if source_id not in set(route["source_ids"])
            }
            if eligible
            else {}
        )
        arm0, _ = choose_isolated_decisions(
            requirements, raw_baseline[case_id], source_alternatives, chunks_by_id
        )
        arm1, audit = choose_contextual_decisions(
            requirements,
            arm0,
            contextual_bundles[case_id] if eligible else {},
            chunks_by_id,
        )
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": truth[case_id]["dataset"],
                "evaluation_block": "frozen_docs_69",
                "question": eval_by_id[case_id]["question"],
                "source_id": None,
                "arm0_decisions": _context_decision_view(requirements, arm0),
                "arm1_decisions": _context_decision_view(requirements, arm1),
                "replacement_audit": audit,
                "arm0_score": _score_groups(eval_by_id[case_id], arm0),
                "arm1_score": _score_groups(eval_by_id[case_id], arm1),
                "exact_slices": _decisions_exact(arm1, chunks_by_id),
                "temporal_violation_chunk_ids": _temporal_violations(
                    arm1, route, chunks_by_id
                ),
                "gold_available_to_decision": False,
            }
        )
    return rows


def evaluate_authored(
    *,
    demo: DemoBackbone,
    evaluations: list[dict[str, Any]],
    results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    eval_by_id = {row["dev_id"]: row for row in evaluations}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    temporal = {row["document_id"]: row for row in temporal_rows}
    rows = []
    for index, source in enumerate(sorted(results, key=lambda row: row["case_id"]), 1):
        case_id = source["case_id"]
        evaluation = eval_by_id[case_id]
        requirements, raw_baseline = _runtime_decisions(source)
        route = source["runtime"]["route"]
        eligible = (
            baseline_allows_corrective_retrieval(raw_baseline)
            and route["time_scope"] == "current"
            and "dnf_account_policy" not in route["source_ids"]
        )
        sources = candidate_sources(route)
        print(f"[context authored {index}/{len(results)}] {evaluation['question']}", flush=True)
        source_bundles = (
            _live_source_decisions(
                demo,
                question=evaluation["question"],
                requirements=requirements,
                route=route,
                source_ids=[
                    source_id
                    for source_id in sources
                    if source_id not in set(route["source_ids"])
                ],
            )
            if eligible
            else {}
        )
        arm0, _ = choose_isolated_decisions(
            requirements, raw_baseline, source_bundles, chunks_by_id
        )
        contextual = (
            _contextual_live_sources(
                demo,
                question=evaluation["question"],
                requirements=requirements,
                route=route,
                source_ids=sources,
            )
            if eligible
            else {}
        )
        arm1, audit = choose_contextual_decisions(
            requirements, arm0, contextual, chunks_by_id
        )
        arm0_score = {
            **score_case(
                evaluation,
                _runtime_from_decisions(source, arm0),
                chunks_by_id,
                temporal,
            ),
            **_score_groups(evaluation, arm0),
        }
        arm1_score = {
            **score_case(
                evaluation,
                _runtime_from_decisions(source, arm1),
                chunks_by_id,
                temporal,
            ),
            **_score_groups(evaluation, arm1),
        }
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": "authored_validation_v3_2_adaptive",
                "evaluation_block": "authored_adaptive_24",
                "question": evaluation["question"],
                "source_id": evaluation["source_ids"][0],
                "arm0_decisions": _context_decision_view(requirements, arm0),
                "arm1_decisions": _context_decision_view(requirements, arm1),
                "replacement_audit": audit,
                "arm0_score": arm0_score,
                "arm1_score": arm1_score,
                "exact_slices": _decisions_exact(arm1, chunks_by_id),
                "temporal_violation_chunk_ids": arm1_score[
                    "temporal_violation_chunk_ids"
                ],
                "gold_available_to_decision": False,
            }
        )
    return rows


def summarize(frozen_rows: list[dict[str, Any]], authored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        arm0_hit = {row["case_id"] for row in rows if row["arm0_score"]["all_groups_hit"]}
        arm1_hit = {row["case_id"] for row in rows if row["arm1_score"]["all_groups_hit"]}
        arm0_span = {
            row["case_id"]
            for row in rows
            if row["arm0_score"]["all_evidence_spans_hit"]
        }
        arm1_span = {
            row["case_id"]
            for row in rows
            if row["arm1_score"]["all_evidence_spans_hit"]
        }
        new_false = sorted(
            row["case_id"]
            for row in rows
            if row["arm1_score"]["false_full"]
            and not row["arm0_score"]["false_full"]
        )
        return {
            "arm0_all_groups": _ratio(len(arm0_hit), total),
            "arm1_all_groups": _ratio(len(arm1_hit), total),
            "arm0_all_evidence_spans": _ratio(len(arm0_span), total),
            "arm1_all_evidence_spans": _ratio(len(arm1_span), total),
            "arm0_false_full": _ratio(
                sum(row["arm0_score"]["false_full"] for row in rows), total
            ),
            "arm1_false_full": _ratio(
                sum(row["arm1_score"]["false_full"] for row in rows), total
            ),
            "regression_case_ids": sorted(arm0_hit - arm1_hit),
            "improvement_case_ids": sorted(arm1_hit - arm0_hit),
            "evidence_span_regression_case_ids": sorted(arm0_span - arm1_span),
            "evidence_span_improvement_case_ids": sorted(arm1_span - arm0_span),
            "new_false_full_case_ids": new_false,
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
    source_arm0 = Counter()
    source_arm1 = Counter()
    for row in authored_rows:
        source_arm0[row["source_id"]] += row["arm0_score"]["all_groups_hit"]
        source_arm1[row["source_id"]] += row["arm1_score"]["all_groups_hit"]
    source_non_decreasing = all(
        source_arm1[source_id] >= source_arm0[source_id]
        for source_id in source_arm0
    )
    checks = {
        "frozen_all_groups_at_least_63_of_69": frozen["arm1_all_groups"]["successes"] >= 63,
        "frozen_regression_zero": not frozen["regression_case_ids"],
        "frozen_evidence_span_regression_zero": not frozen[
            "evidence_span_regression_case_ids"
        ],
        "frozen_new_false_full_zero": not frozen["new_false_full_case_ids"],
        "authored_all_groups_at_least_20_of_24": authored["arm1_all_groups"]["successes"] >= 20,
        "authored_evidence_span_improves_beyond_7_of_24": authored[
            "arm1_all_evidence_spans"
        ]["successes"]
        > 7,
        "authored_regression_zero": not authored["regression_case_ids"],
        "authored_new_false_full_zero": not authored["new_false_full_case_ids"],
        "authored_false_full_at_most_2_of_24": authored["arm1_false_full"]["successes"] <= 2,
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
                "arm0": source_arm0[source_id],
                "arm1": source_arm1[source_id],
                "total": 3,
            }
            for source_id in sorted(source_arm0)
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
        "# Contextual answer-unit selection A/B",
        "",
        "Development-only. No runtime/canonical promotion.",
        "",
        f"Decision: **{result['decision']}**",
        "",
        "| Block | Arm 0 groups | Arm 1 groups | Arm 0 literal spans | Arm 1 literal spans | Arm 0 false-full | Arm 1 false-full |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Frozen docs | {frozen['arm0_all_groups']['successes']}/69 | {frozen['arm1_all_groups']['successes']}/69 | {frozen['arm0_all_evidence_spans']['successes']}/69 | {frozen['arm1_all_evidence_spans']['successes']}/69 | {frozen['arm0_false_full']['successes']}/69 | {frozen['arm1_false_full']['successes']}/69 |",
        f"| Authored adaptive | {authored['arm0_all_groups']['successes']}/24 | {authored['arm1_all_groups']['successes']}/24 | {authored['arm0_all_evidence_spans']['successes']}/24 | {authored['arm1_all_evidence_spans']['successes']}/24 | {authored['arm0_false_full']['successes']}/24 | {authored['arm1_false_full']['successes']}/24 |",
        "",
        f"- frozen regressions: `{frozen['regression_case_ids']}`",
        f"- authored regressions: `{authored['regression_case_ids']}`",
        f"- authored span improvements: `{authored['evidence_span_improvement_case_ids']}`",
        f"- new false-full: `{frozen['new_false_full_case_ids'] + authored['new_false_full_case_ids']}`",
        f"- exact citations: **{result['strict_gate_checks']['exact_all']}**",
        f"- temporal violations zero: **{result['strict_gate_checks']['temporal_violation_zero']}**",
        "",
        "Literal evidence-span containment is a conservative mechanical lower bound, not semantic entailment.",
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
        "documents": root / DEFAULT_DOCUMENTS,
        "temporal": root / DEFAULT_TEMPORAL,
        "authored_set": root / DEFAULT_AUTHORED_SET,
        "authored_results": root / DEFAULT_AUTHORED_RESULTS,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    chunks = read_jsonl(inputs["chunks"])
    documents = read_jsonl(inputs["documents"])
    assembler = enrich_assembler_cases(
        read_jsonl(inputs["assembler_cases"]), read_jsonl(inputs["enumeration"])
    )
    segment_scores = read_jsonl(inputs["segment_scores"])
    routes = _route_map(
        read_jsonl(inputs["dev_runtime"]), read_jsonl(inputs["canary_runtime"])
    )
    fallback_cases, fallback_scores = build_bounded_fallback_inputs(
        assembler_cases=assembler,
        segment_score_rows=segment_scores,
        routes=routes,
        chunks=chunks,
    )
    fallback_rows = assemble_chunk_diverse_configuration(
        fallback_cases,
        fallback_scores,
        threshold=ASSEMBLER_THRESHOLD,
        k=ASSEMBLER_K,
    )
    demo = DemoBackbone(
        root=root,
        planner_model="qwen3:8b",
        enable_v3_2_candidates=True,
    )
    demo._initialize()
    frozen_rows = evaluate_frozen(
        demo=demo,
        ground_truth=read_jsonl(inputs["ground_truth"]),
        evaluations=read_jsonl(inputs["adaptive_dev"])
        + read_jsonl(inputs["downgraded_canary"]),
        assembler=assembler,
        fallback_rows=fallback_rows,
        segment_scores=segment_scores,
        routes=routes,
        chunks=chunks,
        documents=documents,
    )
    authored_rows = evaluate_authored(
        demo=demo,
        evaluations=read_jsonl(inputs["authored_set"]),
        results=read_jsonl(inputs["authored_results"]),
        chunks=chunks,
        temporal_rows=read_jsonl(inputs["temporal"]),
    )
    result = summarize(frozen_rows, authored_rows)
    rows = frozen_rows + authored_rows
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_contextual_answer_unit_ab",
        "result": result,
        "constraints": {
            "gold_or_labels_changed": False,
            "gold_available_to_decision": False,
            "new_domain_keyword_rules": 0,
            "neighbor_answer_values_in_context": False,
            "training_or_reindex": False,
            "runtime_or_canonical_promoted": False,
            "frozen_blind_accessed": False,
            "authored_set_is_adaptive_not_sealed": True,
        },
        "inputs": {
            name: {"path": path.relative_to(root).as_posix(), "sha256": before[name]}
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
    cases_path = evidence_dir / f"contextual_answer_unit_ab_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"contextual_answer_unit_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"contextual_answer_unit_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("Frozen input changed during contextual answer-unit A/B")
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
    manifest_path = evidence_dir / f"contextual_answer_unit_ab_manifest_{manifest_sha}.json"
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
