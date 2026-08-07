from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3 import product_evidence_pack
from src.v3.diagnose_product_value_presence_parenthetical_binding import (
    score_requirement_value_presence,
)
from src.v3.product_free_rag import DEFAULT_EVIDENCE_UNITS, ProductFreeRAG


RUNNER_VERSION = "product-ranking-context-reeval-v1"
FROZEN = Path(
    "data/v3/evaluation/product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc"
    ".jsonl"
)
SAVED_A6_PACKS = Path(
    "reports/v3/product_table_subject_binding_a6_post_decoupled_20260805.jsonl"
)
SCALE_INVENTORY = Path(
    "reports/v3/product_table_subject_binding_s2_r1_baseline_20260805.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_ranking_context_reeval_20260805.jsonl"
)
TARGET_CHUNK_ID = (
    "chunk_sha256_b85cf9c381f143cf45072d4a3738bdb2bebdba4634eb37cd962defa2798fc3f6"
)
TARGET_START = 189
TARGET_END = 224
DESCRIPTIVE_DIAGNOSTIC_KEYS = {
    "A6-17:mold_trade_types",
    "A6-29:august_special_box_prices",
}
VALUE_ORDER = {
    "value_present_none": 0,
    "value_present_partial": 1,
    "value_present_full": 2,
}


def _coordinate(unit: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(unit.get("chunk_id") or ""),
        int(unit.get("start_char", -1)),
        int(unit.get("end_char", -1)),
        str(unit.get("unit_kind") or ""),
    )


def _pack_signature(pack: list[dict[str, Any]]) -> list[tuple[str, int, int, str]]:
    return [_coordinate(unit) for unit in pack]


def _full_ranking_context_text(unit: dict[str, Any]) -> str:
    return str(unit.get("context_text") or "")


@contextmanager
def ranking_context_arm(*, include_table_introducer: bool) -> Iterator[None]:
    original = product_evidence_pack._ranking_context_text
    if include_table_introducer:
        product_evidence_pack._ranking_context_text = _full_ranking_context_text
    try:
        yield
    finally:
        product_evidence_pack._ranking_context_text = original


def _build_pack(
    rag: ProductFreeRAG,
    *,
    question: str,
    candidate_chunk_ids: list[str],
    include_table_introducer: bool,
    score_pairs=None,
) -> tuple[list[dict[str, Any]], float]:
    requirement_queries = product_evidence_pack.kiwi_independent_requirement_queries(
        question
    )
    started = time.perf_counter()
    with ranking_context_arm(
        include_table_introducer=include_table_introducer
    ):
        pack = product_evidence_pack.build_atomic_reranked_product_evidence_pack(
            candidate_chunk_ids,
            question=question,
            requirement_queries=requirement_queries or None,
            chunks_by_id=rag._artifacts.chunks_by_id,
            documents_by_id=rag._artifacts.documents_by_id,
            temporal_by_document=rag.temporal_by_document,
            score_pairs=score_pairs or rag._score_pairs,
            max_units=DEFAULT_EVIDENCE_UNITS,
            prefilter_per_query=32,
            reserve_per_query=3 if len(requirement_queries) > 1 else 1,
        )
    return pack, (time.perf_counter() - started) * 1000


def _all_atomic_units(
    rag: ProductFreeRAG,
    *,
    question: str,
    candidate_chunk_ids: list[str],
) -> list[dict[str, Any]]:
    previous_by_chunk_id = product_evidence_pack._previous_parent_chunks(
        rag._artifacts.chunks_by_id
    )
    units = []
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = rag._artifacts.chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        document = rag._artifacts.documents_by_id[parent_document_id]
        temporal = rag.temporal_by_document.get(parent_document_id, {})
        units.extend(
            product_evidence_pack._without_product_header_metadata_units(
                product_evidence_pack._chunk_atomic_units(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                ),
                chunk=chunk,
                question=question,
            )
        )
        units.extend(
            product_evidence_pack._without_product_header_metadata_units(
                product_evidence_pack._short_numbered_list_units(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                    previous_chunk=previous_by_chunk_id.get(chunk_id),
                ),
                chunk=chunk,
                question=question,
            )
        )
    return units


def _first_requirement_ranking(
    rag: ProductFreeRAG,
    *,
    question: str,
    candidate_chunk_ids: list[str],
    include_table_introducer: bool,
) -> dict[str, Any]:
    queries = product_evidence_pack.kiwi_independent_requirement_queries(question)
    if not queries:
        surface_queries = product_evidence_pack.surface_requirement_queries(
            question
        )
        queries = (
            surface_queries[1:]
            if len(surface_queries) > 1
            else surface_queries
        )
    if not queries:
        raise RuntimeError("A6-7 did not produce a requirement query")
    query = queries[0]
    units = _all_atomic_units(
        rag,
        question=question,
        candidate_chunk_ids=candidate_chunk_ids,
    )
    with ranking_context_arm(
        include_table_introducer=include_table_introducer
    ):
        prefiltered = sorted(
            range(len(units)),
            key=lambda index: product_evidence_pack._query_score(
                units[index], query
            ),
            reverse=True,
        )[:32]
        texts = [
            product_evidence_pack._atomic_reranker_text(units[index])
            for index in prefiltered
        ]
        scores = list(rag._score_pairs(list(zip([query] * len(texts), texts))))
    if len(scores) != len(prefiltered):
        raise RuntimeError("A6-7 ranking score count mismatch")
    score_by_index = dict(zip(prefiltered, scores))
    ranked = sorted(
        prefiltered,
        key=lambda index: (
            -float(score_by_index[index]),
            int(units[index]["candidate_ref"]),
            int(units[index]["start_char"]),
        ),
    )

    def ranking_row(position: int, index: int) -> dict[str, Any]:
        unit = units[index]
        return {
            "rank": position,
            "score": round(float(score_by_index[index]), 8),
            "coordinate": _coordinate(unit),
            "text": str(unit.get("text") or ""),
            "context_text": str(unit.get("context_text") or ""),
        }

    ranking = [ranking_row(position, index) for position, index in enumerate(ranked, 1)]
    target = next(
        (
            row
            for row in ranking
            if row["coordinate"][0] == TARGET_CHUNK_ID
            and row["coordinate"][1] == TARGET_START
            and row["coordinate"][2] == TARGET_END
        ),
        None,
    )
    return {
        "query": query,
        "prefilter_count": len(prefiltered),
        "top3": ranking[:3],
        "target_rank": target["rank"] if target else None,
        "target_score": target["score"] if target else None,
    }


def _gate_kind(case_ref: str, requirement_id: str) -> str:
    if f"{case_ref}:{requirement_id}" in DESCRIPTIVE_DIAGNOSTIC_KEYS:
        return "descriptive_diagnostic"
    return "numeric_date_time_currency"


def _score_requirements(
    frozen: dict[str, Any],
    pack: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        score_requirement_value_presence(
            requirement,
            evidence_pack=pack,
            as_of=str(frozen["as_of"]),
        )
        for requirement in frozen.get("requirements") or []
    ]


def _target_pack_position(pack: list[dict[str, Any]]) -> int | None:
    for position, unit in enumerate(pack, 1):
        coordinate = _coordinate(unit)
        if (
            coordinate[0] == TARGET_CHUNK_ID
            and coordinate[1] == TARGET_START
            and coordinate[2] == TARGET_END
        ):
            return position
    return None


def _requirement_comparison(
    case_ref: str,
    baseline: list[dict[str, Any]],
    shadow: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    before_by_id = {
        str(requirement["requirement_id"]): requirement for requirement in baseline
    }
    return [
        {
            "requirement_id": requirement["requirement_id"],
            "value_type": requirement["value_type"],
            "gate_kind": _gate_kind(
                case_ref, str(requirement["requirement_id"])
            ),
            "before": before_by_id[str(requirement["requirement_id"])][
                "value_presence"
            ],
            "after": requirement["value_presence"],
        }
        for requirement in shadow
    ]


def _value_counts(rows: list[dict[str, Any]], arm: str) -> dict[str, int]:
    return dict(
        Counter(
            requirement["value_presence"]
            for row in rows
            for requirement in row[f"{arm}_requirements"]
            if str(requirement["value_presence"]).startswith("value_present_")
        )
    )


def _measure_saved_scale(
    rag: ProductFreeRAG,
    inventory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    cases = [row for row in inventory_rows if row.get("type") == "case"]
    prior_summary = next(
        row for row in inventory_rows if row.get("type") == "summary"
    )
    score_cache: dict[tuple[str, str], float] = {}
    scorer_calls = 0

    def cached_score_pairs(pairs: list[tuple[str, str]]) -> list[float]:
        nonlocal scorer_calls
        missing = list(dict.fromkeys(pair for pair in pairs if pair not in score_cache))
        if missing:
            scores = list(rag._score_pairs(missing))
            if len(scores) != len(missing):
                raise RuntimeError("saved-scale score count mismatch")
            score_cache.update(zip(missing, scores))
            scorer_calls += 1
        return [score_cache[pair] for pair in pairs]

    changed_sets = []
    changed_orders = []
    changed_set_records = 0
    changed_order_records = 0
    introducer_cases = [row for row in cases if row["has_introducer_candidate"]]
    for position, row in enumerate(introducer_cases, 1):
        question = str(row["question"])
        candidate_ids = [str(value) for value in row["candidate_chunk_ids"]]
        baseline, _ = _build_pack(
            rag,
            question=question,
            candidate_chunk_ids=candidate_ids,
            include_table_introducer=False,
            score_pairs=cached_score_pairs,
        )
        shadow, _ = _build_pack(
            rag,
            question=question,
            candidate_chunk_ids=candidate_ids,
            include_table_introducer=True,
            score_pairs=cached_score_pairs,
        )
        baseline_signature = _pack_signature(baseline)
        shadow_signature = _pack_signature(shadow)
        source_record_count = len(row["source_records"])
        if set(baseline_signature) != set(shadow_signature):
            changed_sets.append(int(row["case_key"]))
            changed_set_records += source_record_count
        elif baseline_signature != shadow_signature:
            changed_orders.append(int(row["case_key"]))
            changed_order_records += source_record_count
        if position % 20 == 0 or position == len(introducer_cases):
            print(
                json.dumps(
                    {
                        "stage": "saved_scale",
                        "completed": position,
                        "total": len(introducer_cases),
                        "pack_set_changed_unique": len(changed_sets),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return {
        "inventory_unique_case_count": len(cases),
        "inventory_saved_record_count": prior_summary["saved_record_count"],
        "introducer_candidate_unique_cases": len(introducer_cases),
        "pack_set_changed_unique_cases": len(changed_sets),
        "pack_set_changed_records": changed_set_records,
        "pack_order_only_changed_unique_cases": len(changed_orders),
        "pack_order_only_changed_records": changed_order_records,
        "pack_set_changed_case_keys": changed_sets,
        "pack_order_only_changed_case_keys": changed_orders,
        "unique_scored_pairs": len(score_cache),
        "scorer_calls": scorer_calls,
        "r2_historical_reference": {
            "saved_record_count": 1300,
            "pack_set_changed_records": 246,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-evaluate full table-introducer context in atomic ranking"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")

    frozen_by_ref = {
        f"A6-{row['slot_ordinal']}": row for row in read_jsonl(root / FROZEN)
    }
    saved_by_ref = {
        str(row["case_ref"]): row
        for row in read_jsonl(root / SAVED_A6_PACKS)
        if row.get("type") == "case"
    }
    if len(frozen_by_ref) != 32 or len(saved_by_ref) != 32:
        raise RuntimeError("ranking-context re-evaluation requires 32 A6 rows")

    rag = ProductFreeRAG(
        root=root,
        device=args.device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    rows = []
    for slot in range(1, 33):
        case_ref = f"A6-{slot}"
        frozen = frozen_by_ref[case_ref]
        saved = saved_by_ref[case_ref]
        question = str(frozen["question_text"])
        candidate_ids = [str(value) for value in saved["candidate_chunk_ids"]]
        baseline_pack, baseline_ms = _build_pack(
            rag,
            question=question,
            candidate_chunk_ids=candidate_ids,
            include_table_introducer=False,
        )
        shadow_pack, shadow_ms = _build_pack(
            rag,
            question=question,
            candidate_chunk_ids=candidate_ids,
            include_table_introducer=True,
        )
        baseline_requirements = _score_requirements(frozen, baseline_pack)
        shadow_requirements = _score_requirements(frozen, shadow_pack)
        comparison = _requirement_comparison(
            case_ref, baseline_requirements, shadow_requirements
        )
        baseline_signature = _pack_signature(baseline_pack)
        shadow_signature = _pack_signature(shadow_pack)
        rows.append(
            {
                "type": "case",
                "case_ref": case_ref,
                "slot_ordinal": slot,
                "question": question,
                "candidate_chunk_ids": candidate_ids,
                "baseline_pack": baseline_pack,
                "shadow_pack": shadow_pack,
                "baseline_requirements": baseline_requirements,
                "shadow_requirements": shadow_requirements,
                "requirements_before_after": comparison,
                "pack_set_changed": (
                    set(baseline_signature) != set(shadow_signature)
                ),
                "pack_order_only_changed": (
                    set(baseline_signature) == set(shadow_signature)
                    and baseline_signature != shadow_signature
                ),
                "baseline_candidate_rerank_ms": round(baseline_ms, 3),
                "shadow_candidate_rerank_ms": round(shadow_ms, 3),
                "candidate_rerank_delta_ms": round(shadow_ms - baseline_ms, 3),
            }
        )
        print(
            json.dumps(
                {
                    "stage": "a6",
                    "case_ref": case_ref,
                    "pack_set_changed": rows[-1]["pack_set_changed"],
                    "pack_order_only_changed": rows[-1][
                        "pack_order_only_changed"
                    ],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    a67 = next(row for row in rows if row["case_ref"] == "A6-7")
    a67_ranking = {
        "A_current": _first_requirement_ranking(
            rag,
            question=a67["question"],
            candidate_chunk_ids=a67["candidate_chunk_ids"],
            include_table_introducer=False,
        ),
        "B_full_context": _first_requirement_ranking(
            rag,
            question=a67["question"],
            candidate_chunk_ids=a67["candidate_chunk_ids"],
            include_table_introducer=True,
        ),
        "target_pack_position": {
            "A_current": _target_pack_position(a67["baseline_pack"]),
            "B_full_context": _target_pack_position(a67["shadow_pack"]),
        },
    }
    all_comparisons = [
        {"case_ref": row["case_ref"], **comparison}
        for row in rows
        for comparison in row["requirements_before_after"]
        if comparison["before"].startswith("value_present_")
        and comparison["after"].startswith("value_present_")
    ]
    gate_decreases = [
        comparison
        for comparison in all_comparisons
        if comparison["gate_kind"] == "numeric_date_time_currency"
        and VALUE_ORDER[comparison["after"]] < VALUE_ORDER[comparison["before"]]
    ]
    descriptive_decreases = [
        comparison
        for comparison in all_comparisons
        if comparison["gate_kind"] == "descriptive_diagnostic"
        and VALUE_ORDER[comparison["after"]] < VALUE_ORDER[comparison["before"]]
    ]
    changed_rows = [
        row
        for row in rows
        if row["pack_set_changed"] or row["pack_order_only_changed"]
    ]
    scale = _measure_saved_scale(
        rag, read_jsonl(root / SCALE_INVENTORY)
    )
    baseline_times = [row["baseline_candidate_rerank_ms"] for row in rows]
    shadow_times = [row["shadow_candidate_rerank_ms"] for row in rows]
    gate_1 = bool(
        a67_ranking["B_full_context"]["top3"]
        and tuple(a67_ranking["B_full_context"]["top3"][0]["coordinate"])[0:3]
        == (TARGET_CHUNK_ID, TARGET_START, TARGET_END)
    )
    gates = {
        "a6_7_first_requirement_target_rank_1": gate_1,
        "numeric_date_time_currency_decrease_zero": not gate_decreases,
    }
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "status": "shadow_complete_no_runtime_change",
        "qwen_calls": 0,
        "runtime_modified": False,
        "case_count": len(rows),
        "measurable_requirement_count": len(all_comparisons),
        "value_presence_counts": {
            "A_current": _value_counts(rows, "baseline"),
            "B_full_context": _value_counts(rows, "shadow"),
            "expected_A_current": {
                "value_present_full": 40,
                "value_present_partial": 4,
                "value_present_none": 5,
            },
        },
        "numeric_date_time_currency_decreases": gate_decreases,
        "descriptive_diagnostic_decreases": descriptive_decreases,
        "value_presence_changes": [
            comparison
            for comparison in all_comparisons
            if comparison["before"] != comparison["after"]
        ],
        "pack_set_changed_case_refs": [
            row["case_ref"] for row in rows if row["pack_set_changed"]
        ],
        "pack_order_only_changed_case_refs": [
            row["case_ref"]
            for row in rows
            if row["pack_order_only_changed"]
        ],
        "changed_cases_requirements_before_after": {
            row["case_ref"]: row["requirements_before_after"]
            for row in changed_rows
        },
        "candidate_rerank_ms": {
            "A_total": round(sum(baseline_times), 3),
            "B_total": round(sum(shadow_times), 3),
            "delta_total": round(sum(shadow_times) - sum(baseline_times), 3),
            "A_mean": round(sum(baseline_times) / len(baseline_times), 3),
            "B_mean": round(sum(shadow_times) / len(shadow_times), 3),
            "delta_mean": round(
                (sum(shadow_times) - sum(baseline_times)) / len(rows), 3
            ),
        },
        "a6_7": a67_ranking,
        "saved_scale": scale,
        "gates": gates,
        "stage_2_allowed": all(gates.values()),
        "a6_7_stop_condition_applies": not all(gates.values()),
    }
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
