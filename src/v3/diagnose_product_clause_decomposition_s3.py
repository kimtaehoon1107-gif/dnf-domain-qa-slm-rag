from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.diagnose_product_value_presence_parenthetical_binding import (
    score_requirement_value_presence,
)
from src.v3.product_candidate_identity import (
    candidate_row_from_chunk,
    reserve_then_fill,
    shortlist_document_chunks,
    shortlist_identity_documents,
)
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    explicit_question_clauses,
    kiwi_independent_requirement_queries,
)
from src.v3.product_free_rag import (
    DEFAULT_EVIDENCE_UNITS,
    DEFAULT_RETRIEVAL_DEPTH,
    ProductFreeRAG,
    expand_evidence_candidate_chunk_ids,
    search_policy_for_product_question,
)


A6_INPUT = Path(
    "data/v3/evaluation/product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc"
    "689b65dc.jsonl"
)
USER10_INPUT = Path(
    "data/v3/evaluation/product_pipeline_user10_v2_adaptive_20260805.jsonl"
)
USER10_SAVED = Path(
    "reports/v3/product_pipeline_user10_v2_after_improvements_20260805.jsonl"
)
S1_INPUT = Path(
    "reports/v3/product_free_rag_clause_decomposition_s1_20260805.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_clause_decomposition_s3_20260805.jsonl"
)
REQUIREMENT_RESERVATION_OUTPUT = Path(
    "reports/v3/product_free_rag_requirement_reservation_reeval_20260805.jsonl"
)
M3_INPUT = Path("reports/v3/product_value_presence_m3_20260805.jsonl")
TARGET_CASES = {"A6-1", "A6-2", "A6-4", "A6-7", "A6-22"}
PRIMARY_GATE_CASES = {"A6-1", "A6-4", "A6-22"}
CONTROL_CASE = "A6-2"
RUNNER_VERSION = "product-free-rag-clause-decomposition-s3-v1"
REQUIREMENT_RESERVATION_RUNNER_VERSION = (
    "product-free-rag-requirement-reservation-reeval-v1"
)
DESCRIPTIVE_DIAGNOSTIC_KEYS = {
    "A6-17:mold_trade_types",
    "A6-29:august_special_box_prices",
}
_VALUE_ORDER = {
    "value_present_none": 0,
    "value_present_partial": 1,
    "value_present_full": 2,
}


def _arm_requirement_queries(question: str) -> dict[str, list[str] | None]:
    kiwi = kiwi_independent_requirement_queries(question)
    explicit = explicit_question_clauses(question)
    return {
        "A_current": kiwi or None,
        "B_explicit_fallback": kiwi or explicit,
    }


def _overlaps(
    evidence_pack: list[dict[str, Any]],
    gold_units: list[dict[str, Any]],
) -> bool:
    return any(
        str(unit.get("chunk_id")) == str(gold.get("chunk_id"))
        and int(unit.get("start_char", unit.get("start_offset", -1)))
        < int(gold.get("end_char", gold.get("end_offset", -1)))
        and int(unit.get("end_char", unit.get("end_offset", -1)))
        > int(gold.get("start_char", gold.get("start_offset", -1)))
        for unit in evidence_pack
        for gold in gold_units
    )


def _pack_signature(evidence_pack: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            unit.get("chunk_id"),
            unit.get("start_char", unit.get("start_offset")),
            unit.get("end_char", unit.get("end_offset")),
            unit.get("text"),
        )
        for unit in evidence_pack
    ]


def _pack_coordinate_set(
    evidence_pack: list[dict[str, Any]],
) -> set[tuple[str, int, int, str]]:
    return {
        (
            str(unit.get("chunk_id") or ""),
            int(unit.get("start_char", -1)),
            int(unit.get("end_char", -1)),
            str(unit.get("unit_kind") or ""),
        )
        for unit in evidence_pack
    }


def _value_gate_kind(case_ref: str, requirement_id: str) -> str:
    return (
        "descriptive_diagnostic"
        if f"{case_ref}:{requirement_id}" in DESCRIPTIVE_DIAGNOSTIC_KEYS
        else "numeric_date_time_currency"
    )


def _value_decreases_from_m3(
    case_ref: str,
    requirements: list[dict[str, Any]],
    m3_requirements: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    decreases = []
    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        before = str(m3_requirements[requirement_id]["value_presence"])
        after = str(requirement["value_presence"])
        if before not in _VALUE_ORDER or after not in _VALUE_ORDER:
            continue
        if _VALUE_ORDER[after] >= _VALUE_ORDER[before]:
            continue
        decreases.append(
            {
                "case_ref": case_ref,
                "requirement_id": requirement_id,
                "before": before,
                "after": after,
                "gate_kind": _value_gate_kind(case_ref, requirement_id),
                "required_values": requirement["required_values"],
                "assigned_units": requirement["assigned_units"],
            }
        )
    return decreases


def _reservation_assignments(
    evidence_pack: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    assignments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in evidence_pack:
        focus = str(unit.get("question_focus") or "")
        if not focus:
            continue
        assignments[focus].append(
            {
                "evidence_ref": unit.get("evidence_ref"),
                "chunk_id": unit.get("chunk_id"),
                "start_char": unit.get("start_char"),
                "end_char": unit.get("end_char"),
                "text": unit.get("text"),
            }
        )
    return dict(assignments)


def _a6_gold_requirements(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": requirement["requirement_id"],
            "gold_source": "acceptable_evidence_units",
            "gold_units": requirement["acceptable_evidence_units"],
        }
        for requirement in row["requirements"]
        if requirement.get("expected_status") == "supported"
        and requirement.get("acceptable_evidence_units")
    ]


def _user10_saved_gold(
    saved_row: dict[str, Any],
) -> list[dict[str, Any]]:
    citations = [
        citation
        for claim in saved_row["result"].get("claims") or []
        for citation in claim.get("citations") or []
    ]
    units = list(
        {
            (
                str(citation["chunk_id"]),
                int(citation["start_char"]),
                int(citation["end_char"]),
            ): {
                "chunk_id": citation["chunk_id"],
                "start_char": citation["start_char"],
                "end_char": citation["end_char"],
                "text": citation.get("text") or "",
            }
            for citation in citations
        }.values()
    )
    if not units:
        raise RuntimeError("USER10 correct case has no saved cited evidence")
    return [
        {
            "requirement_id": "saved_human_correct_citations",
            "gold_source": "saved_human_correct_citations_proxy",
            "gold_units": units,
        }
    ]


def _run_arm(
    *,
    rag: ProductFreeRAG,
    question: str,
    as_of: str,
    requirement_queries: list[str] | None,
    chunks_by_parent: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from src.v3.retrieve_v3 import retrieve_with_embedding

    queries = list(dict.fromkeys([question, *(requirement_queries or [])]))
    embedded = time.perf_counter()
    embeddings = rag._encode_queries(queries)
    query_embedding_ms = (time.perf_counter() - embedded) * 1000
    searched = time.perf_counter()
    policy = search_policy_for_product_question(
        question,
        default_as_of=as_of,
    )
    union_by_chunk: dict[str, dict[str, Any]] = {}
    for query_index, (query, embedding) in enumerate(
        zip(queries, embeddings, strict=True)
    ):
        for hit in retrieve_with_embedding(
            query,
            embedding,
            rag._artifacts,
            top_k=DEFAULT_RETRIEVAL_DEPTH,
            policy=policy,
        ):
            chunk_id = str(hit["chunk_id"])
            if chunk_id not in union_by_chunk:
                union_by_chunk[chunk_id] = {
                    **hit,
                    "query_indexes": [query_index],
                }
            else:
                union_by_chunk[chunk_id]["query_indexes"].append(query_index)
    hybrid_union_count = len(union_by_chunk)
    lexical_dense_search_ms = (time.perf_counter() - searched) * 1000

    shortlisted_documents = shortlist_identity_documents(
        question,
        documents_by_id=rag._artifacts.documents_by_id,
        chunks_by_parent=chunks_by_parent,
    )
    shortlisted_chunks = shortlist_document_chunks(
        question,
        shortlisted_documents,
        chunks_by_parent=chunks_by_parent,
    )
    for chunk in shortlisted_chunks:
        union_by_chunk.setdefault(
            str(chunk["chunk_id"]),
            candidate_row_from_chunk(
                chunk,
                rag._artifacts.documents_by_id[chunk["parent_document_id"]],
                fallback_rank=DEFAULT_RETRIEVAL_DEPTH + 1,
            ),
        )
    union = list(union_by_chunk.values())
    reranked_at = time.perf_counter()
    scores = rag._score_pairs(
        [
            (
                question,
                rag._artifacts.chunks_by_id[row["chunk_id"]][
                    "retrieval_text"
                ],
            )
            for row in union
        ]
    )
    reranked = sorted(
        (
            {**row, "reranker_score": round(float(score), 8)}
            for row, score in zip(union, scores, strict=True)
        ),
        key=lambda row: (
            -float(row["reranker_score"]),
            int(row.get("rank") or 0),
            str(row["chunk_id"]),
        ),
    )
    candidate_rerank_ms = (time.perf_counter() - reranked_at) * 1000
    reserved = []
    for document in shortlisted_documents:
        parent_id = str(document["document_id"])
        parent_rows = [
            row
            for row in reranked
            if str(row["parent_document_id"]) == parent_id
        ]
        if parent_rows:
            reserved.append([parent_rows[0]])
    final_candidates = reserve_then_fill(reserved, reranked)
    evidence_candidate_ids = expand_evidence_candidate_chunk_ids(
        question,
        final_candidates,
        chunks_by_parent=chunks_by_parent,
    )
    evidence_started = time.perf_counter()
    evidence_pack = build_atomic_reranked_product_evidence_pack(
        evidence_candidate_ids,
        question=question,
        requirement_queries=requirement_queries,
        chunks_by_id=rag._artifacts.chunks_by_id,
        documents_by_id=rag._artifacts.documents_by_id,
        temporal_by_document=rag.temporal_by_document,
        score_pairs=rag._score_pairs,
        max_units=DEFAULT_EVIDENCE_UNITS,
        prefilter_per_query=32,
        reserve_per_query=3 if len(requirement_queries or []) > 1 else 1,
    )
    evidence_atomic_rerank_ms = (time.perf_counter() - evidence_started) * 1000
    return {
        "requirement_queries": requirement_queries or [],
        "query_count": len(queries),
        "hybrid_union_count": hybrid_union_count,
        "reranker_candidate_count": len(union),
        "final_candidate_chunk_ids": [
            str(row["chunk_id"]) for row in final_candidates
        ],
        "evidence_pack": evidence_pack,
        "query_embedding_ms": round(query_embedding_ms, 3),
        "lexical_dense_search_ms": round(lexical_dense_search_ms, 3),
        "candidate_rerank_ms": round(candidate_rerank_ms, 3),
        "evidence_atomic_rerank_ms": round(
            evidence_atomic_rerank_ms,
            3,
        ),
    }


def run_requirement_reservation_reeval(
    *,
    root: Path,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frozen_rows = sorted(
        read_jsonl(root / A6_INPUT),
        key=lambda row: int(row["slot_ordinal"]),
    )
    m3_by_ref = {
        str(row["case_ref"]): row
        for row in read_jsonl(root / M3_INPUT)
        if row.get("type") == "case"
    }
    if len(frozen_rows) != 32 or len(m3_by_ref) != 32:
        raise RuntimeError("requirement reservation re-eval requires 32 A6 rows")

    rag = ProductFreeRAG(
        root=root,
        device=device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    chunks_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in rag._artifacts.chunks_by_id.values():
        chunks_by_parent[str(chunk["parent_document_id"])].append(chunk)

    rows = []
    for source in frozen_rows:
        case_ref = f"A6-{source['slot_ordinal']}"
        question = str(source["question_text"])
        arms = {}
        for arm_name, requirement_queries in _arm_requirement_queries(
            question
        ).items():
            arm = _run_arm(
                rag=rag,
                question=question,
                as_of=str(source["as_of"]),
                requirement_queries=requirement_queries,
                chunks_by_parent=chunks_by_parent,
            )
            arm["requirements"] = [
                score_requirement_value_presence(
                    requirement,
                    evidence_pack=arm["evidence_pack"],
                    as_of=str(source["as_of"]),
                )
                for requirement in source.get("requirements") or []
            ]
            arm["reservation_assignments"] = _reservation_assignments(
                arm["evidence_pack"]
            )
            arms[arm_name] = arm

        current = arms["A_current"]
        fallback = arms["B_explicit_fallback"]
        m3_requirements = {
            str(requirement["requirement_id"]): requirement
            for requirement in m3_by_ref[case_ref]["requirements"]
        }
        current_coordinates = _pack_coordinate_set(current["evidence_pack"])
        fallback_coordinates = _pack_coordinate_set(fallback["evidence_pack"])
        rows.append(
            {
                "type": "case",
                "case_ref": case_ref,
                "slot_ordinal": int(source["slot_ordinal"]),
                "question": question,
                "explicit_question_clauses": explicit_question_clauses(
                    question
                ),
                "kiwi_requirement_queries": (
                    kiwi_independent_requirement_queries(question)
                ),
                "arms": arms,
                "pack_set_changed": (
                    current_coordinates != fallback_coordinates
                ),
                "pack_added_coordinates": sorted(
                    fallback_coordinates - current_coordinates
                ),
                "pack_removed_coordinates": sorted(
                    current_coordinates - fallback_coordinates
                ),
                "pack_order_changed": (
                    current_coordinates == fallback_coordinates
                    and _pack_signature(current["evidence_pack"])
                    != _pack_signature(fallback["evidence_pack"])
                ),
                "candidate_rerank_ms_delta": round(
                    fallback["candidate_rerank_ms"]
                    - current["candidate_rerank_ms"],
                    3,
                ),
                "value_decreases_from_m3": {
                    "A_current": _value_decreases_from_m3(
                        case_ref,
                        current["requirements"],
                        m3_requirements,
                    ),
                    "B_explicit_fallback": _value_decreases_from_m3(
                        case_ref,
                        fallback["requirements"],
                        m3_requirements,
                    ),
                },
            }
        )
        print(
            json.dumps(
                {
                    "case_ref": case_ref,
                    "pack_set_changed": rows[-1]["pack_set_changed"],
                    "A_rerank_ms": current["candidate_rerank_ms"],
                    "B_rerank_ms": fallback["candidate_rerank_ms"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    a67 = next(row for row in rows if row["case_ref"] == "A6-7")
    a67_requirements = {
        arm_name: {
            str(requirement["requirement_id"]): requirement
            for requirement in arm["requirements"]
        }
        for arm_name, arm in a67["arms"].items()
    }
    target_units = a67_requirements["B_explicit_fallback"][
        "base_cooldown_change"
    ]["assigned_units"]
    first_clause = str(a67["explicit_question_clauses"][0])
    first_clause_assignments = a67["arms"]["B_explicit_fallback"][
        "reservation_assignments"
    ].get(first_clause, [])
    gate_1 = any(
        str(unit["chunk_id"])
        == "chunk_sha256_b85cf9c381f143cf45072d4a3738bdb2bebdba4634eb37cd962defa2798fc3f6"
        and int(unit["start_char"]) == 189
        and int(unit["end_char"]) == 224
        for unit in first_clause_assignments
    )
    all_decreases = [
        decrease
        for row in rows
        for decrease in row["value_decreases_from_m3"][
            "B_explicit_fallback"
        ]
    ]
    gate_decreases = [
        decrease
        for decrease in all_decreases
        if decrease["gate_kind"] == "numeric_date_time_currency"
    ]

    def value_counts(arm_name: str) -> dict[str, int]:
        return dict(
            Counter(
                requirement["value_presence"]
                for row in rows
                for requirement in row["arms"][arm_name]["requirements"]
                if str(requirement["value_presence"]).startswith(
                    "value_present_"
                )
            )
        )

    rerank_a = [
        row["arms"]["A_current"]["candidate_rerank_ms"] for row in rows
    ]
    rerank_b = [
        row["arms"]["B_explicit_fallback"]["candidate_rerank_ms"]
        for row in rows
    ]
    summary = {
        "type": "summary",
        "runner_version": REQUIREMENT_RESERVATION_RUNNER_VERSION,
        "status": "diagnostic_complete_no_runtime_change",
        "diagnostic_question": (
            "Does explicit-clause requirement reservation bind A6-7 E3 to "
            "base_cooldown_change after R1 and R2?"
        ),
        "prior_s3_decision_remains_valid": True,
        "qwen_calls": 0,
        "runtime_modified": False,
        "case_count": len(rows),
        "measurable_requirement_count": sum(
            str(requirement["value_presence"]).startswith("value_present_")
            for row in rows
            for requirement in row["arms"]["B_explicit_fallback"][
                "requirements"
            ]
        ),
        "value_presence_counts": {
            "M3": {
                "value_present_full": 39,
                "value_present_partial": 4,
                "value_present_none": 6,
            },
            "A_current": value_counts("A_current"),
            "B_explicit_fallback": value_counts(
                "B_explicit_fallback"
            ),
        },
        "value_decreases_from_m3": all_decreases,
        "numeric_date_time_currency_decreases": gate_decreases,
        "descriptive_diagnostic_decreases": [
            decrease
            for decrease in all_decreases
            if decrease["gate_kind"] == "descriptive_diagnostic"
        ],
        "pack_set_changed_case_refs": [
            row["case_ref"] for row in rows if row["pack_set_changed"]
        ],
        "pack_order_only_changed_case_refs": [
            row["case_ref"] for row in rows if row["pack_order_changed"]
        ],
        "candidate_rerank_ms": {
            "A_total": round(sum(rerank_a), 3),
            "B_total": round(sum(rerank_b), 3),
            "delta_total": round(sum(rerank_b) - sum(rerank_a), 3),
            "A_mean": round(sum(rerank_a) / len(rerank_a), 3),
            "B_mean": round(sum(rerank_b) / len(rerank_b), 3),
            "delta_mean": round(
                (sum(rerank_b) - sum(rerank_a)) / len(rerank_a),
                3,
            ),
        },
        "a6_7": {
            "explicit_question_clauses": a67[
                "explicit_question_clauses"
            ],
            "A_current_requirements": a67_requirements["A_current"],
            "B_explicit_fallback_requirements": a67_requirements[
                "B_explicit_fallback"
            ],
            "A_current_reservation_assignments": a67["arms"][
                "A_current"
            ]["reservation_assignments"],
            "B_explicit_fallback_reservation_assignments": a67["arms"][
                "B_explicit_fallback"
            ]["reservation_assignments"],
            "B_base_cooldown_gold_assigned_units": target_units,
            "gate_1_e3_189_224_assigned": gate_1,
        },
        "reference_cases": {
            case_ref: next(row for row in rows if row["case_ref"] == case_ref)
            for case_ref in ("A6-1", "A6-4", "A6-22")
        },
        "gates": {
            "a6_7_requirement_1_has_e3_189_224": gate_1,
            "numeric_date_time_currency_decrease_zero": not gate_decreases,
        },
        "go": gate_1 and not gate_decreases,
        "next_stage": (
            "SEPARATE_REQUIREMENT_RESERVATION_RUNTIME_ROUND"
            if gate_1 and not gate_decreases
            else "CLAIM_PER_REQUIREMENT_SPLIT_ROUND"
            if not gate_1
            else "REDUCE_RESERVATION_AND_REMEASURE"
        ),
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Shadow explicit clause fallback without calling Qwen"
    )
    parser.add_argument(
        "--mode",
        choices=("original-s3", "requirement-reservation-reeval"),
        default="original-s3",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    requested_output = args.output or (
        REQUIREMENT_RESERVATION_OUTPUT
        if args.mode == "requirement-reservation-reeval"
        else DEFAULT_OUTPUT
    )
    output = (
        requested_output
        if requested_output.is_absolute()
        else root / requested_output
    )
    if output.exists():
        raise RuntimeError(f"S3 output already exists: {output}")

    if args.mode == "requirement-reservation-reeval":
        rows, summary = run_requirement_reservation_reeval(
            root=root,
            device=args.device,
        )
        write_jsonl(output, [*rows, summary])
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    s1_rows = read_jsonl(root / S1_INPUT)
    s1_summary = next(
        row for row in s1_rows if row.get("type") == "summary"
    )
    if not s1_summary["decision"]["proceed_to_s2"]:
        raise RuntimeError("S1 did not authorize S3")
    gap_correct_refs = {
        row["case_ref"]
        for row in s1_rows
        if row.get("type") == "case"
        and row.get("decomposition_gap")
        and row.get("human_judgement") == "correct"
    }
    case_refs = TARGET_CASES | gap_correct_refs
    a6_by_ref = {
        f"A6-{row['slot_ordinal']}": row for row in read_jsonl(root / A6_INPUT)
    }
    user10_by_ref = {
        f"USER10-{row['slot']}": row for row in read_jsonl(root / USER10_INPUT)
    }
    saved_user10_by_ref = {
        f"USER10-{row['slot']}": row
        for row in read_jsonl(root / USER10_SAVED)
        if row.get("type") == "case"
    }

    rag = ProductFreeRAG(
        root=root,
        device=args.device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    chunks_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in rag._artifacts.chunks_by_id.values():
        chunks_by_parent[str(chunk["parent_document_id"])].append(chunk)

    rows = []
    for case_ref in sorted(
        case_refs,
        key=lambda value: (value.split("-")[0], int(value.split("-")[1])),
    ):
        if case_ref.startswith("A6-"):
            source = a6_by_ref[case_ref]
            question = source["question_text"]
            as_of = source["as_of"]
            gold_requirements = _a6_gold_requirements(source)
        else:
            source = user10_by_ref[case_ref]
            question = source["question"]
            as_of = "2026-08-05"
            gold_requirements = _user10_saved_gold(
                saved_user10_by_ref[case_ref]
            )
        arm_queries = _arm_requirement_queries(question)
        arms = {}
        for arm_name, requirement_queries in arm_queries.items():
            arm = _run_arm(
                rag=rag,
                question=question,
                as_of=as_of,
                requirement_queries=requirement_queries,
                chunks_by_parent=chunks_by_parent,
            )
            arm["gold_visibility"] = {
                requirement["requirement_id"]: _overlaps(
                    arm["evidence_pack"],
                    requirement["gold_units"],
                )
                for requirement in gold_requirements
            }
            arm["all_gold_visible"] = all(arm["gold_visibility"].values())
            arms[arm_name] = arm
        current = arms["A_current"]
        fallback = arms["B_explicit_fallback"]
        regressed_requirements = [
            requirement_id
            for requirement_id, visible in current["gold_visibility"].items()
            if visible and not fallback["gold_visibility"][requirement_id]
        ]
        row = {
            "type": "case",
            "case_ref": case_ref,
            "question": question,
            "is_primary_gate_case": case_ref in PRIMARY_GATE_CASES,
            "is_control": case_ref == CONTROL_CASE,
            "is_gap_correct_regression_case": case_ref in gap_correct_refs,
            "gold_requirements": gold_requirements,
            "arms": arms,
            "newly_all_gold_visible": (
                not current["all_gold_visible"]
                and fallback["all_gold_visible"]
            ),
            "regressed_requirements": regressed_requirements,
            "pack_changed": (
                _pack_signature(current["evidence_pack"])
                != _pack_signature(fallback["evidence_pack"])
            ),
            "candidate_rerank_ms_delta": round(
                fallback["candidate_rerank_ms"]
                - current["candidate_rerank_ms"],
                3,
            ),
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    "case_ref": case_ref,
                    "A_all_gold": current["all_gold_visible"],
                    "B_all_gold": fallback["all_gold_visible"],
                    "regressed": regressed_requirements,
                    "rerank_delta_ms": row["candidate_rerank_ms_delta"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    primary_recovered = [
        row["case_ref"]
        for row in rows
        if row["case_ref"] in PRIMARY_GATE_CASES
        and row["newly_all_gold_visible"]
    ]
    control = next(row for row in rows if row["case_ref"] == CONTROL_CASE)
    gap_correct_regressions = [
        {
            "case_ref": row["case_ref"],
            "requirements": row["regressed_requirements"],
        }
        for row in rows
        if row["is_gap_correct_regression_case"]
        and row["regressed_requirements"]
    ]
    rerank_a = [
        row["arms"]["A_current"]["candidate_rerank_ms"] for row in rows
    ]
    rerank_b = [
        row["arms"]["B_explicit_fallback"]["candidate_rerank_ms"]
        for row in rows
    ]
    gates = {
        "primary_recovered_at_least_2": len(primary_recovered) >= 2,
        "control_pack_unchanged": not control["pack_changed"],
        "gap_correct_gold_regressions_zero": not gap_correct_regressions,
    }
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "status": "diagnostic_complete_no_runtime_change",
        "case_count": len(rows),
        "qwen_calls": 0,
        "runtime_modified": False,
        "target_cases": sorted(TARGET_CASES),
        "gap_correct_cases": sorted(gap_correct_refs),
        "primary_recovered_cases": primary_recovered,
        "gap_correct_regressions": gap_correct_regressions,
        "control_pack_changed": control["pack_changed"],
        "candidate_rerank_ms": {
            "A_total": round(sum(rerank_a), 3),
            "B_total": round(sum(rerank_b), 3),
            "delta_total": round(sum(rerank_b) - sum(rerank_a), 3),
            "A_mean": round(sum(rerank_a) / len(rerank_a), 3),
            "B_mean": round(sum(rerank_b) / len(rerank_b), 3),
            "delta_mean": round(
                (sum(rerank_b) - sum(rerank_a)) / len(rerank_a),
                3,
            ),
        },
        "gates": gates,
        "go": all(gates.values()),
        "next_stage": (
            "SEPARATE_FALLBACK_IMPLEMENTATION_ROUND"
            if all(gates.values())
            else "RETURN_TO_W6_THREE_WAY_SPLIT"
        ),
    }
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
