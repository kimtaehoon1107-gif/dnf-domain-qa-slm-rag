from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.generate_grounded_llm_answer import (
    build_batched_requirement_prompt,
    build_grounded_prompt,
    build_requirement_prompt,
    generate_batched_non_table_requirement_output,
    generate_batched_requirement_output,
    generate_grounded_output,
    generate_non_table_requirement_output,
    generate_requirement_output,
    safe_abstention,
    select_table_rows_for_requirement,
    verify_and_sanitize_output,
    verify_non_table_requirement_selection,
    verify_requirement_selection,
)
from src.v3.typed_evidence_ref import (
    TYPED_EVIDENCE_CONTRACT_VERSION,
    assess_requirement_evidence_sufficiency_shadow,
    build_typed_evidence_prompt_with_candidate_units,
    generate_typed_evidence_output,
    resolve_requirement_claim_contracts,
    verify_typed_requirement_selection,
)


DEFAULT_REVIEWED = Path(
    "data/v3/evaluation/requirement_surface_query_canary_reviewed_"
    "533a4b031369cdd63872cd4f52a33d9128fbcf6cf42a344e2693b4959a76c561.jsonl"
)
DEFAULT_BASELINE_CASES = Path(
    "data/v3/evidence/requirement_surface_query_canary_ab_cases_"
    "deaaef651ea4110bf9883a32123742564cb0022ed7745a1cfdadc5d3ec463003.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_TEMPORAL = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DEFAULT_TABLE_FACTS = Path(
    "data/v3/structured/table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_OUTPUT = Path("outputs/v3/grounded_llm_replay_cases.jsonl")
DEFAULT_SUMMARY = Path("reports/v3/grounded_llm_replay_summary.json")
Generator = Callable[..., dict[str, Any]]


class TypedEvidenceNamespaceMismatchError(RuntimeError):
    """Stored E-reference coordinates do not match the rebuilt prompt."""


def _typed_evidence_namespace_metadata(
    units_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": unit["chunk_id"],
            "start_char": unit["start_char"],
            "end_char": unit["end_char"],
        }
        for evidence_ref, unit in sorted(
            units_by_ref.items(),
            key=lambda item: int(item[0][1:]),
        )
    ]
    payload = json.dumps(
        units,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "claim_contract_version": TYPED_EVIDENCE_CONTRACT_VERSION,
        "units": units,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _attach_typed_evidence_namespace(
    call: dict[str, Any],
    units_by_ref: dict[str, dict[str, Any]],
) -> None:
    current_namespace = _typed_evidence_namespace_metadata(units_by_ref)
    replay_requires_match = bool(
        call.pop("_recorded_replay_requires_namespace_match", False)
    )
    recorded_namespace = call.get("typed_evidence_namespace")
    if replay_requires_match and recorded_namespace != current_namespace:
        raise TypedEvidenceNamespaceMismatchError(
            "recorded typed evidence namespace does not match rebuilt prompt"
        )
    if (
        recorded_namespace is not None
        and recorded_namespace != current_namespace
    ):
        raise TypedEvidenceNamespaceMismatchError(
            "generator typed evidence namespace does not match rebuilt prompt"
        )
    call["typed_evidence_namespace"] = current_namespace


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 6) if total else 0.0,
    }


def build_table_rows_by_chunk(
    table_facts: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in table_facts:
        chunk_id = fact["source_chunk_id"]
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            raise RuntimeError(f"Table fact references an unknown chunk: {chunk_id}")
        start = int(fact["start_offset"])
        end = int(fact["end_offset"])
        row_text = fact["row_text"]
        if chunk["display_text"][start:end] != row_text:
            raise RuntimeError(f"Table row is not an exact chunk slice: {fact['row_id']}")
        key = (chunk_id, fact["row_id"])
        row = rows.setdefault(
            key,
            {
                "row_id": fact["row_id"],
                "start_char": start,
                "end_char": end,
                "row_text": row_text,
                "facts": [],
            },
        )
        row["facts"].append(
            {
                "attribute": fact["attribute"],
                "subject": fact.get("subject"),
                "value": fact["value"],
                "unit": fact.get("unit"),
            }
        )
    output: dict[str, list[dict[str, Any]]] = {}
    for (chunk_id, _), row in rows.items():
        row["facts"].sort(key=lambda value: (value["attribute"], value["value"]))
        output.setdefault(chunk_id, []).append(row)
    for chunk_rows in output.values():
        chunk_rows.sort(key=lambda row: (row["start_char"], row["row_id"]))
    return output


def score_verified_output(
    reviewed: dict[str, Any],
    *,
    candidate_chunk_ids: list[str],
    candidate_chunk_ids_by_requirement: list[list[str]] | None = None,
    verified: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    decisions = verified["requirements"]
    groups = reviewed["evidence_groups"]
    candidate_ids = set(candidate_chunk_ids)
    group_scores = []
    relevant_count = 0
    citation_count = 0
    surplus_citation_count = 0
    exact_slices = True
    for group, decision in zip(groups, decisions[: len(groups)]):
        citations = decision.get("citations") or []
        acceptable = set(group["acceptable_chunk_ids"])
        span = group["evidence_span"]
        group_hit = any(citation["chunk_id"] in acceptable for citation in citations)
        literal_hit = any(
            citation["chunk_id"] in acceptable and span in citation["text"]
            for citation in citations
        )
        for citation in citations:
            citation_count += 1
            chunk = chunks_by_id.get(citation["chunk_id"])
            exact = bool(
                chunk is not None
                and chunk["display_text"][citation["start_char"] : citation["end_char"]]
                == citation["text"]
            )
            exact_slices = exact_slices and exact
            relevant_count += bool(
                citation["chunk_id"] in acceptable and span in citation["text"]
            )
        group_scores.append(
            {
                "group_id": group["group_id"],
                "group_hit": group_hit,
                "literal_span_hit": literal_hit,
                "supported": decision.get("status") == "supported_exact",
            }
        )
    for decision in decisions[len(groups) :]:
        for citation in decision.get("citations") or []:
            citation_count += 1
            surplus_citation_count += 1
            chunk = chunks_by_id.get(citation["chunk_id"])
            exact_slices = exact_slices and bool(
                chunk is not None
                and chunk["display_text"][citation["start_char"] : citation["end_char"]]
                == citation["text"]
            )
    while len(group_scores) < len(groups):
        group = groups[len(group_scores)]
        group_scores.append(
            {
                "group_id": group["group_id"],
                "group_hit": False,
                "literal_span_hit": False,
                "supported": False,
            }
        )
    if candidate_chunk_ids_by_requirement is None:
        candidate_covered = all(
            bool(candidate_ids & set(group["acceptable_chunk_ids"])) for group in groups
        )
    else:
        if len(candidate_chunk_ids_by_requirement) != len(groups):
            raise RuntimeError("Requirement candidate pool count differs from evidence groups")
        candidate_covered = all(
            bool(set(pool) & set(group["acceptable_chunk_ids"]))
            for pool, group in zip(candidate_chunk_ids_by_requirement, groups, strict=True)
        )
    all_groups = all(row["group_hit"] for row in group_scores)
    all_spans = all(row["literal_span_hit"] for row in group_scores)
    full_answer = verified["response_mode"] == "full_answer"
    time_scope_match = verified.get("question_time_scope") == reviewed["time_scope"]
    return {
        "groups": group_scores,
        "candidate_all_groups_covered": candidate_covered,
        "all_groups_hit": all_groups,
        "all_evidence_spans_hit": all_spans,
        "full_answer": full_answer,
        "false_full": full_answer and not all_spans,
        "exact_citation_slices": exact_slices,
        "citation_count": citation_count,
        "relevant_citation_count": relevant_count,
        "surplus_citation_count": surplus_citation_count,
        "citation_precision": round(relevant_count / citation_count, 6)
        if citation_count
        else 1.0,
        "requirement_count_match": len(decisions) == len(reviewed["requirements"]),
        "question_time_scope_match": time_scope_match,
        "safe_to_expose": verified["verification"]["all_exposed_citations_verified"],
        "generation_error": verified["verification"].get("generation_error"),
    }


def summarize_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    covered = [row for row in rows if row["llm_score"]["candidate_all_groups_covered"]]
    baseline_literal = {
        row["candidate_id"]
        for row in rows
        if row["baseline_score"]["all_evidence_spans_hit"]
    }
    llm_literal = {
        row["candidate_id"]
        for row in rows
        if row["llm_score"]["all_evidence_spans_hit"]
    }
    llm_strict = sum(row["llm_score"]["all_groups_hit"] for row in rows)
    llm_literal_covered = sum(
        row["llm_score"]["all_evidence_spans_hit"] for row in covered
    )
    baseline_relevant = sum(
        row["baseline_score"]["relevant_citation_count"] for row in rows
    )
    baseline_citations = sum(row["baseline_score"]["citation_count"] for row in rows)
    llm_relevant = sum(row["llm_score"]["relevant_citation_count"] for row in rows)
    llm_citations = sum(row["llm_score"]["citation_count"] for row in rows)
    metrics = {
        "evaluated_questions": total,
        "candidate_all_required_coverage": _ratio(len(covered), total),
        "baseline_all_required_evidence": _ratio(
            sum(row["baseline_score"]["all_groups_hit"] for row in rows), total
        ),
        "baseline_all_literal_spans": _ratio(len(baseline_literal), total),
        "llm_all_required_evidence": _ratio(llm_strict, total),
        "llm_all_literal_spans": _ratio(len(llm_literal), total),
        "llm_literal_given_candidate_coverage": _ratio(
            llm_literal_covered, len(covered)
        ),
        "literal_regression_case_ids": sorted(baseline_literal - llm_literal),
        "literal_improvement_case_ids": sorted(llm_literal - baseline_literal),
        "false_full_case_ids": sorted(
            row["candidate_id"] for row in rows if row["llm_score"]["false_full"]
        ),
        "requirement_count_mismatch_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if not row["llm_score"]["requirement_count_match"]
        ),
        "time_scope_mismatch_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if not row["llm_score"]["question_time_scope_match"]
        ),
        "generation_error_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if row["llm_score"]["generation_error"]
        ),
        "surplus_citation_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if row["llm_score"]["surplus_citation_count"]
        ),
        "all_exact_citation_slices": all(
            row["llm_score"]["exact_citation_slices"] for row in rows
        ),
        "all_outputs_safe_to_expose": all(
            row["llm_score"]["safe_to_expose"] for row in rows
        ),
        "baseline_citation_precision": round(
            baseline_relevant / baseline_citations, 6
        )
        if baseline_citations
        else 1.0,
        "llm_citation_precision": round(llm_relevant / llm_citations, 6)
        if llm_citations
        else 1.0,
        "total_latency_ms": round(
            sum(row.get("model_call", {}).get("latency_ms", 0) for row in rows), 3
        ),
        "total_tokens": sum(
            row.get("model_call", {}).get("usage", {}).get("total_tokens", 0)
            for row in rows
        ),
    }
    full_run = total == 32
    gates = {
        "full_32_question_run": full_run,
        "candidate_coverage_22_of_32": len(covered) == 22 if full_run else False,
        "llm_literal_at_least_18_of_22_covered": (
            llm_literal_covered >= 18 if full_run else False
        ),
        "literal_regression_zero": not metrics["literal_regression_case_ids"],
        "false_full_zero": not metrics["false_full_case_ids"],
        "requirement_count_mismatch_zero": not metrics[
            "requirement_count_mismatch_case_ids"
        ],
        "time_scope_mismatch_zero": not metrics["time_scope_mismatch_case_ids"],
        "generation_error_zero": not metrics["generation_error_case_ids"],
        "surplus_citation_zero": not metrics["surplus_citation_case_ids"],
        "exact_citation_slices_100_percent": metrics["all_exact_citation_slices"],
        "all_outputs_safe_to_expose": metrics["all_outputs_safe_to_expose"],
        "citation_precision_non_decreasing": metrics["llm_citation_precision"]
        >= metrics["baseline_citation_precision"],
    }
    return {
        "evaluation_role": "adaptive_32_replay_not_independent_holdout",
        "metrics": metrics,
        "gates": gates,
        "decision": "PRODUCT_GENERATOR_GO" if all(gates.values()) else "NO_GO",
        "automatic_runtime_or_canonical_promotion": False,
    }


def run_replay(
    *,
    reviewed_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]],
    table_facts: list[dict[str, Any]],
    model: str,
    as_of: str,
    reasoning_effort: str,
    timeout_seconds: float,
    generator: Generator = generate_grounded_output,
) -> list[dict[str, Any]]:
    reviewed_by_id = {row["candidate_id"]: row for row in reviewed_rows}
    baseline_by_id = {row["candidate_id"]: row for row in baseline_rows}
    if set(reviewed_by_id) != set(baseline_by_id):
        raise RuntimeError("Reviewed and baseline candidate IDs differ")
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    temporal_by_document = {row["document_id"]: row for row in temporal_rows}
    table_rows_by_chunk = build_table_rows_by_chunk(
        table_facts, chunks_by_id=chunks_by_id
    )
    results = []
    for reviewed in reviewed_rows:
        baseline = baseline_by_id[reviewed["candidate_id"]]
        candidate_ids = list(baseline["arm0"]["candidate_chunk_ids"])
        prompt = build_grounded_prompt(
            question=reviewed["question_text"],
            as_of=as_of,
            candidate_chunk_ids=candidate_ids,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
            table_rows_by_chunk=table_rows_by_chunk,
        )
        try:
            model_call = generator(
                prompt=prompt,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
            )
            verified = verify_and_sanitize_output(
                model_call["output"],
                candidate_chunk_ids=candidate_ids,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                temporal_by_document=temporal_by_document,
            )
        except Exception as exc:
            model_call = {"requested_model": model, "error": f"{type(exc).__name__}: {exc}"}
            verified = safe_abstention(exc)
        score = score_verified_output(
            reviewed,
            candidate_chunk_ids=candidate_ids,
            verified=verified,
            chunks_by_id=chunks_by_id,
        )
        results.append(
            {
                "candidate_id": reviewed["candidate_id"],
                "question_text": reviewed["question_text"],
                "candidate_chunk_ids": candidate_ids,
                "decision_input_fields": [
                    "question_text",
                    "as_of",
                    "candidate_chunk_ids",
                    "candidate_metadata_and_text",
                    "candidate_table_atomic_rows",
                ],
                "gold_available_to_generator": False,
                "model_call": model_call,
                "verified_output": verified,
                "baseline_score": baseline["arm0_score"],
                "llm_score": score,
            }
        )
    return results


def _aggregate_model_calls(calls: list[dict[str, Any]], model: str) -> dict[str, Any]:
    return {
        "requested_model": model,
        "calls": calls,
        "call_count": len(calls),
        "latency_ms": round(sum(call.get("latency_ms", 0) for call in calls), 3),
        "usage": {
            key: sum(call.get("usage", {}).get(key, 0) for call in calls)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        },
    }


def run_fixed_requirement_replay(
    *,
    reviewed_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]],
    table_facts: list[dict[str, Any]],
    model: str,
    as_of: str,
    reasoning_effort: str,
    timeout_seconds: float,
    generator: Generator = generate_requirement_output,
    non_table_generator: Generator | None = None,
    batch_generator: Generator = generate_batched_requirement_output,
    non_table_batch_generator: Generator | None = None,
    typed_batch_generator: Generator = generate_typed_evidence_output,
    split_evidence_schema: bool = False,
    batch_requirements: bool = False,
    typed_evidence_refs: bool = False,
    progress: Callable[[int, int], None] | None = None,
    result_callback: Callable[[dict[str, Any], int, int], None] | None = None,
    candidate_pool_rows: list[dict[str, Any]] | None = None,
    candidate_pool_arm: str | None = None,
    allow_partial_candidate_pools: bool = False,
) -> list[dict[str, Any]]:
    if batch_requirements and not split_evidence_schema:
        raise RuntimeError("batch_requirements requires split_evidence_schema")
    if typed_evidence_refs and not batch_requirements:
        raise RuntimeError("typed_evidence_refs requires batch_requirements")
    reviewed_by_id = {row["candidate_id"]: row for row in reviewed_rows}
    baseline_by_id = {row["candidate_id"]: row for row in baseline_rows}
    if set(reviewed_by_id) != set(baseline_by_id):
        raise RuntimeError("Reviewed and baseline candidate IDs differ")
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    temporal_by_document = {row["document_id"]: row for row in temporal_rows}
    table_rows_by_chunk = build_table_rows_by_chunk(
        table_facts, chunks_by_id=chunks_by_id
    )
    candidate_pools_by_id = {
        row["candidate_id"]: row for row in (candidate_pool_rows or [])
    }
    if candidate_pool_rows is not None:
        if not candidate_pool_arm:
            raise RuntimeError("candidate_pool_arm is required with candidate_pool_rows")
        unknown_pool_ids = set(candidate_pools_by_id) - set(reviewed_by_id)
        if unknown_pool_ids:
            raise RuntimeError("Candidate pools include unknown candidate IDs")
        if (
            not allow_partial_candidate_pools
            and set(candidate_pools_by_id) != set(reviewed_by_id)
        ):
            raise RuntimeError("Reviewed and candidate-pool candidate IDs differ")
    results = []
    for row_index, reviewed in enumerate(reviewed_rows, 1):
        baseline = baseline_by_id[reviewed["candidate_id"]]
        resolved_requirements = resolve_requirement_claim_contracts(
            reviewed["requirements"],
            question_text=reviewed["question_text"],
        )
        baseline_candidate_ids = list(baseline["arm0"]["candidate_chunk_ids"])
        if (
            candidate_pool_rows is None
            or reviewed["candidate_id"] not in candidate_pools_by_id
        ):
            requirement_candidate_ids = [
                list(baseline_candidate_ids) for _ in resolved_requirements
            ]
        else:
            pools = candidate_pools_by_id[reviewed["candidate_id"]][
                "requirement_candidate_pools"
            ]
            if len(pools) != len(resolved_requirements):
                raise RuntimeError("Requirement candidate pool count differs from requirements")
            requirement_candidate_ids = [
                list(pool[candidate_pool_arm]["candidate_chunk_ids"])
                for pool in pools
            ]
        decisions: list[dict[str, Any] | None] = [
            None for _ in resolved_requirements
        ]
        audits: list[dict[str, Any] | None] = [
            None for _ in resolved_requirements
        ]
        calls = []
        evidence_modes = []
        for requirement, candidate_ids in zip(
            resolved_requirements, requirement_candidate_ids, strict=True
        ):
            matching_table_rows = select_table_rows_for_requirement(
                table_rows_by_chunk, requirement
            )
            has_candidate_table_rows = any(
                matching_table_rows.get(chunk_id) for chunk_id in candidate_ids
            )
            evidence_mode = (
                "table"
                if split_evidence_schema and has_candidate_table_rows
                else "non_table"
                if split_evidence_schema
                else "shared"
            )
            evidence_modes.append(evidence_mode)
        if batch_requirements:
            grouped_indices: dict[tuple[str, tuple[str, ...]], list[int]] = {}
            for requirement_index, (evidence_mode, candidate_ids) in enumerate(
                zip(evidence_modes, requirement_candidate_ids, strict=True)
            ):
                grouped_indices.setdefault(
                    (evidence_mode, tuple(candidate_ids)), []
                ).append(requirement_index)
            for (evidence_mode, candidate_id_tuple), indices in grouped_indices.items():
                candidate_ids = list(candidate_id_tuple)
                grouped_requirements = [
                    resolved_requirements[index] for index in indices
                ]
                typed_units_by_ref = None
                typed_candidate_units_by_ref = None
                if typed_evidence_refs and evidence_mode == "non_table":
                    (
                        prompt,
                        typed_units_by_ref,
                        typed_candidate_units_by_ref,
                    ) = build_typed_evidence_prompt_with_candidate_units(
                        question=reviewed["question_text"],
                        requirements=grouped_requirements,
                        question_time_scope=reviewed["time_scope"],
                        as_of=as_of,
                        candidate_chunk_ids=candidate_ids,
                        chunks_by_id=chunks_by_id,
                        documents_by_id=documents_by_id,
                        temporal_by_document=temporal_by_document,
                    )
                    sufficiency_shadow = [
                        assess_requirement_evidence_sufficiency_shadow(
                            requirement,
                            evidence_units_by_ref=typed_units_by_ref,
                            as_of=as_of,
                        )
                        for requirement in grouped_requirements
                    ]
                else:
                    sufficiency_shadow = []
                    prompt = build_batched_requirement_prompt(
                        question=reviewed["question_text"],
                        requirements=grouped_requirements,
                        question_time_scope=reviewed["time_scope"],
                        as_of=as_of,
                        candidate_chunk_ids=candidate_ids,
                        chunks_by_id=chunks_by_id,
                        documents_by_id=documents_by_id,
                        temporal_by_document=temporal_by_document,
                        table_rows_by_chunk=table_rows_by_chunk,
                        include_table_rows=evidence_mode == "table",
                    )
                call: dict[str, Any] | None = None
                try:
                    if typed_evidence_refs and evidence_mode == "non_table":
                        active_generator = typed_batch_generator
                    else:
                        active_generator = (
                            non_table_batch_generator
                            or generate_batched_non_table_requirement_output
                            if evidence_mode == "non_table"
                            else batch_generator
                        )
                    call = active_generator(
                        prompt=prompt,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        timeout_seconds=timeout_seconds,
                    )
                    if (
                        typed_evidence_refs
                        and evidence_mode == "non_table"
                        and typed_units_by_ref is not None
                    ):
                        _attach_typed_evidence_namespace(
                            call,
                            typed_units_by_ref,
                        )
                    if sufficiency_shadow:
                        call["sufficiency_shadow"] = sufficiency_shadow
                    selections = call["output"]["requirements"]
                    selection_ids = [
                        selection["requirement_id"] for selection in selections
                    ]
                    expected_ids = [
                        requirement["requirement_id"]
                        for requirement in grouped_requirements
                    ]
                    ordinal_ids = {
                        str(index) for index in range(1, len(expected_ids) + 1)
                    }
                    if (
                        len(selection_ids) == len(expected_ids)
                        and set(selection_ids) == ordinal_ids
                    ):
                        for selection in selections:
                            selection["requirement_id"] = expected_ids[
                                int(selection["requirement_id"]) - 1
                            ]
                        selection_ids = [
                            selection["requirement_id"] for selection in selections
                        ]
                        call["requirement_id_normalization"] = "ordinal_to_fixed"
                    if (
                        len(selection_ids) != len(set(selection_ids))
                        or set(selection_ids) != set(expected_ids)
                    ):
                        raise RuntimeError(
                            "batched requirement IDs differ from fixed requirements"
                        )
                    selections_by_id = {
                        selection["requirement_id"]: {
                            key: value
                            for key, value in selection.items()
                            if key != "requirement_id"
                        }
                        for selection in selections
                    }
                    for requirement_index in indices:
                        requirement = resolved_requirements[requirement_index]
                        selection = selections_by_id[requirement["requirement_id"]]
                        if typed_evidence_refs and evidence_mode == "non_table":
                            if typed_units_by_ref is None:
                                raise RuntimeError(
                                    "typed evidence units were not built"
                                )
                            decision, audit = verify_typed_requirement_selection(
                                {
                                    "requirement_id": requirement[
                                        "requirement_id"
                                    ],
                                    **selection,
                                },
                                requirement=requirement,
                                question_time_scope=reviewed["time_scope"],
                                question_text=reviewed["question_text"],
                                evidence_units_by_ref=typed_units_by_ref,
                                chunks_by_id=chunks_by_id,
                                as_of=as_of,
                                candidate_evidence_units_by_ref=(
                                    typed_candidate_units_by_ref
                                ),
                            )
                        elif evidence_mode == "non_table":
                            decision, audit = verify_non_table_requirement_selection(
                                selection,
                                requirement=requirement,
                                question_time_scope=reviewed["time_scope"],
                                question_text=reviewed["question_text"],
                                candidate_chunk_ids=candidate_ids,
                                chunks_by_id=chunks_by_id,
                                documents_by_id=documents_by_id,
                                temporal_by_document=temporal_by_document,
                            )
                        else:
                            decision, audit = verify_requirement_selection(
                                selection,
                                requirement=requirement,
                                question_time_scope=reviewed["time_scope"],
                                question_text=reviewed["question_text"],
                                candidate_chunk_ids=candidate_ids,
                                chunks_by_id=chunks_by_id,
                                documents_by_id=documents_by_id,
                                temporal_by_document=temporal_by_document,
                                table_rows_by_chunk=table_rows_by_chunk,
                            )
                        decisions[requirement_index] = decision
                        audits[requirement_index] = audit
                except TypedEvidenceNamespaceMismatchError:
                    raise
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    call = {
                        **(call or {"requested_model": model}),
                        "batch_protocol_error": error,
                        "error": error,
                    }
                    if (
                        typed_evidence_refs
                        and evidence_mode == "non_table"
                        and typed_units_by_ref is not None
                    ):
                        call["typed_evidence_namespace"] = (
                            _typed_evidence_namespace_metadata(
                                typed_units_by_ref
                            )
                        )
                    if sufficiency_shadow:
                        call["sufficiency_shadow"] = sufficiency_shadow
                    for requirement_index in indices:
                        requirement = resolved_requirements[requirement_index]
                        decisions[requirement_index] = {
                            "requirement_id": requirement["requirement_id"],
                            "question_part": requirement.get("surface")
                            or requirement.get("relation"),
                            "status": "unsupported",
                            "answer": "",
                            "citations": [],
                        }
                        audits[requirement_index] = {
                            "requirement_id": requirement["requirement_id"],
                            "model_status": None,
                            "exposed_status": "unsupported",
                            "failure_reasons": [
                                f"generation_error:{type(exc).__name__}"
                            ],
                            "generation_error": error,
                        }
                calls.append(call)
        else:
            for requirement_index, (
                requirement,
                candidate_ids,
                evidence_mode,
            ) in enumerate(
                zip(
                    resolved_requirements,
                    requirement_candidate_ids,
                    evidence_modes,
                    strict=True,
                )
            ):
                prompt = build_requirement_prompt(
                    question=reviewed["question_text"],
                    requirement=requirement,
                    question_time_scope=reviewed["time_scope"],
                    as_of=as_of,
                    candidate_chunk_ids=candidate_ids,
                    chunks_by_id=chunks_by_id,
                    documents_by_id=documents_by_id,
                    temporal_by_document=temporal_by_document,
                    table_rows_by_chunk=table_rows_by_chunk,
                )
                try:
                    active_generator = (
                        non_table_generator or generate_non_table_requirement_output
                        if evidence_mode == "non_table"
                        else generator
                    )
                    call = active_generator(
                        prompt=prompt,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        timeout_seconds=timeout_seconds,
                    )
                    if evidence_mode == "non_table":
                        decision, audit = verify_non_table_requirement_selection(
                            call["output"],
                            requirement=requirement,
                            question_time_scope=reviewed["time_scope"],
                            question_text=reviewed["question_text"],
                            candidate_chunk_ids=candidate_ids,
                            chunks_by_id=chunks_by_id,
                            documents_by_id=documents_by_id,
                            temporal_by_document=temporal_by_document,
                        )
                    else:
                        decision, audit = verify_requirement_selection(
                            call["output"],
                            requirement=requirement,
                            question_time_scope=reviewed["time_scope"],
                            question_text=reviewed["question_text"],
                            candidate_chunk_ids=candidate_ids,
                            chunks_by_id=chunks_by_id,
                            documents_by_id=documents_by_id,
                            temporal_by_document=temporal_by_document,
                            table_rows_by_chunk=table_rows_by_chunk,
                        )
                except Exception as exc:
                    call = {
                        "requested_model": model,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    decision = {
                        "requirement_id": requirement["requirement_id"],
                        "question_part": requirement.get("surface")
                        or requirement.get("relation"),
                        "status": "unsupported",
                        "answer": "",
                        "citations": [],
                    }
                    audit = {
                        "requirement_id": requirement["requirement_id"],
                        "model_status": None,
                        "exposed_status": "unsupported",
                        "failure_reasons": [
                            f"generation_error:{type(exc).__name__}"
                        ],
                        "generation_error": f"{type(exc).__name__}: {exc}",
                    }
                calls.append(call)
                decisions[requirement_index] = decision
                audits[requirement_index] = audit
        if any(decision is None for decision in decisions) or any(
            audit is None for audit in audits
        ):
            raise RuntimeError("requirement decisions were not fully populated")
        decisions = [decision for decision in decisions if decision is not None]
        audits = [audit for audit in audits if audit is not None]
        supported_count = sum(
            decision["status"] == "supported_exact" for decision in decisions
        )
        if supported_count == 0:
            response_mode = "abstain"
        elif supported_count == len(decisions):
            response_mode = "full_answer"
        else:
            response_mode = "partial_answer"
        rendered = "\n".join(
            f"- {decision['answer']} "
            + " ".join(
                f"[{citation['chunk_id']}]" for citation in decision["citations"]
            )
            for decision in decisions
            if decision["status"] == "supported_exact"
        )
        generation_errors = [
            audit["generation_error"] for audit in audits if audit.get("generation_error")
        ]
        verified = {
            "question_time_scope": reviewed["time_scope"],
            "model_response_mode": None,
            "response_mode": response_mode,
            "requirements": decisions,
            "rendered_answer": rendered,
            "verification": {
                "requirements": audits,
                "raw_output_passed_without_sanitization": all(
                    not audit["failure_reasons"] for audit in audits
                ),
                "all_exposed_citations_verified": True,
                **(
                    {"generation_error": "; ".join(generation_errors)}
                    if generation_errors
                    else {}
                ),
            },
        }
        score = score_verified_output(
            reviewed,
            candidate_chunk_ids=list(
                dict.fromkeys(
                    chunk_id
                    for pool in requirement_candidate_ids
                    for chunk_id in pool
                )
            ),
            candidate_chunk_ids_by_requirement=requirement_candidate_ids,
            verified=verified,
            chunks_by_id=chunks_by_id,
        )
        all_candidate_ids = list(
            dict.fromkeys(
                chunk_id for pool in requirement_candidate_ids for chunk_id in pool
            )
        )
        result = {
            "candidate_id": reviewed["candidate_id"],
            "question_text": reviewed["question_text"],
            "candidate_chunk_ids": all_candidate_ids,
            "requirement_candidate_chunk_ids": requirement_candidate_ids,
            "requirement_evidence_modes": evidence_modes,
            "candidate_pool_arm": (
                candidate_pool_arm
                if reviewed["candidate_id"] in candidate_pools_by_id
                else "baseline_fallback"
            ),
            "decision_input_fields": [
                "question_text",
                "fixed_public_requirements",
                "fixed_question_time_scope",
                "as_of",
                "candidate_chunk_ids",
                "candidate_metadata_and_text",
                "requirement_filtered_table_atomic_rows",
                "server_selected_evidence_schema",
            ],
            "gold_answer_or_evidence_available_to_generator": False,
            "frozen_requirement_semantics_available_to_generator": True,
            "batch_requirements": batch_requirements,
            "typed_evidence_refs": typed_evidence_refs,
            "model_call": _aggregate_model_calls(calls, model),
            "verified_output": verified,
            "baseline_score": baseline["arm0_score"],
            "llm_score": score,
        }
        results.append(result)
        if result_callback is not None:
            result_callback(result, row_index, len(reviewed_rows))
        if progress is not None:
            progress(row_index, len(reviewed_rows))
    return results


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Replay fixed retrieval candidates through a grounded LLM")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--baseline-cases", type=Path, default=DEFAULT_BASELINE_CASES)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--table-facts", type=Path, default=DEFAULT_TABLE_FACTS)
    configured_model = os.environ.get("MODEL")
    parser.add_argument(
        "--model", default=configured_model, required=configured_model is None
    )
    parser.add_argument("--as-of", default="2026-07-22")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--fixed-requirements-per-call", action="store_true")
    parser.add_argument("--candidate-pools", type=Path)
    parser.add_argument("--candidate-pool-arm")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def _rooted(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    output_path = _rooted(root, args.output)
    summary_path = _rooted(root, args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("Output path already exists; choose new --output and --summary paths")
    reviewed = read_jsonl(_rooted(root, args.reviewed))
    if args.limit is not None:
        if args.limit <= 0:
            raise RuntimeError("--limit must be positive")
        reviewed = reviewed[: args.limit]
    baseline_all = read_jsonl(_rooted(root, args.baseline_cases))
    selected_ids = {row["candidate_id"] for row in reviewed}
    baseline = [row for row in baseline_all if row["candidate_id"] in selected_ids]
    replay = run_fixed_requirement_replay if args.fixed_requirements_per_call else run_replay
    candidate_pool_rows = (
        read_jsonl(_rooted(root, args.candidate_pools)) if args.candidate_pools else None
    )
    if candidate_pool_rows is not None:
        candidate_pool_rows = [
            row for row in candidate_pool_rows if row["candidate_id"] in selected_ids
        ]
        if replay is not run_fixed_requirement_replay:
            raise RuntimeError("Candidate pools require --fixed-requirements-per-call")
    replay_kwargs = {
        "reviewed_rows": reviewed,
        "baseline_rows": baseline,
        "chunks": read_jsonl(_rooted(root, args.chunks)),
        "documents": read_jsonl(_rooted(root, args.documents)),
        "temporal_rows": read_jsonl(_rooted(root, args.temporal)),
        "table_facts": read_jsonl(_rooted(root, args.table_facts)),
        "model": args.model,
        "as_of": args.as_of,
        "reasoning_effort": args.reasoning_effort,
        "timeout_seconds": args.timeout_seconds,
    }
    if args.fixed_requirements_per_call:
        replay_kwargs["progress"] = lambda current, total: print(
            f"fixed-requirement replay {current}/{total}", flush=True
        )
        replay_kwargs["candidate_pool_rows"] = candidate_pool_rows
        replay_kwargs["candidate_pool_arm"] = args.candidate_pool_arm
    rows = replay(**replay_kwargs)
    summary = summarize_replay(rows)
    summary["run_config"] = {
        "model": args.model,
        "as_of": args.as_of,
        "reasoning_effort": args.reasoning_effort,
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "fixed_requirements_per_call": args.fixed_requirements_per_call,
        "candidate_pools": str(args.candidate_pools) if args.candidate_pools else None,
        "candidate_pool_arm": args.candidate_pool_arm,
    }
    write_jsonl(output_path, rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output_path), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
