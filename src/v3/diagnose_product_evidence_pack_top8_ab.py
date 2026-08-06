from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.product_evidence_pack import (
    _dedupe_key,
    _query_score,
    build_product_evidence_pack,
)
from src.v3.product_free_rag import (
    DEFAULT_EVIDENCE_UNITS,
    GLOBAL_TEMPORAL_OVERLAY,
    build_product_prompt,
)
from src.v3.score_typed_evidence_ref_generalization import (
    _STRICT_VALUE_TYPES,
    value_present,
)
from src.v3.simple_evidence_refs import _chunk_atomic_units


DEFAULT_SEALED_SET = Path(
    "data/v3/evaluation/"
    "simple_rag_untouched32_sealed_"
    "6b2bc67087d255af1b4cfdc9076b8dfd8d0cce2b2194e2e2210af08eb8a95198"
    ".jsonl"
)
DEFAULT_RUN = Path(
    "reports/v3/product_free_rag_existing32_adaptive_replay_20260731.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_evidence_pack_top2_vs_top8_ab_20260731.jsonl"
)


def _assign_refs(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    atomic_index = 0
    table_index = 0
    output = []
    for unit in units:
        if unit.get("complete"):
            table_index += 1
            evidence_ref = f"T{table_index}"
        else:
            atomic_index += 1
            evidence_ref = f"E{atomic_index}"
        output.append({**unit, "evidence_ref": evidence_ref})
    return output


def fill_question_only_pack(
    base_units: list[dict[str, Any]],
    *,
    candidate_chunk_ids: list[str],
    question: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    max_units: int = DEFAULT_EVIDENCE_UNITS,
) -> list[dict[str, Any]]:
    """Keep the current selection and fill its unchanged ranking to max_units."""

    selected = list(base_units)
    selected_keys = {
        key for unit in selected if (key := _dedupe_key(unit))
    }
    complete_ranges = [
        (
            str(unit["chunk_id"]),
            int(unit["start_char"]),
            int(unit["end_char"]),
        )
        for unit in selected
        if unit.get("complete")
    ]
    all_units = []
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        all_units.extend(
            _chunk_atomic_units(
                candidate_index=candidate_index,
                chunk_id=chunk_id,
                chunk=chunk,
                document=documents_by_id[parent_document_id],
                temporal=temporal_by_document.get(
                    parent_document_id,
                    {},
                ),
            )
        )
    ranked = sorted(
        all_units,
        key=lambda unit: _query_score(unit, question),
        reverse=True,
    )
    for unit in ranked:
        if len(selected) >= max_units:
            break
        if any(
            str(unit["chunk_id"]) == chunk_id
            and int(unit["start_char"]) >= start
            and int(unit["end_char"]) <= end
            for chunk_id, start, end in complete_ranges
        ):
            continue
        key = _dedupe_key(unit)
        if not key or key in selected_keys:
            continue
        selected.append(unit)
        selected_keys.add(key)
    return _assign_refs(selected)


def _value_visible(
    value: Any,
    *,
    value_index: int,
    requirement: dict[str, Any],
    units: list[dict[str, Any]],
    as_of: str,
) -> bool:
    visible_text = "\n".join(
        " ".join(
            (
                str(unit.get("title") or ""),
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
        )
        for unit in units
    )
    if value_present(
        value,
        requirement["value_type"],
        visible_text,
        as_of=as_of,
        relation=requirement.get("relation"),
    ):
        return True
    gold_units = requirement.get("acceptable_evidence_units") or []
    values = requirement.get("required_values") or []
    matching_gold = [
        gold
        for gold in gold_units
        if value_present(
            value,
            requirement["value_type"],
            gold.get("text") or "",
            as_of=as_of,
            relation=requirement.get("relation"),
        )
    ]
    if not matching_gold:
        if len(gold_units) == len(values):
            matching_gold = gold_units[value_index : value_index + 1]
        elif len(values) == 1:
            matching_gold = gold_units
    return any(
        str(unit["chunk_id"]) == str(gold["chunk_id"])
        and max(int(unit["start_char"]), int(gold["start_char"]))
        < min(int(unit["end_char"]), int(gold["end_char"]))
        for unit in units
        for gold in matching_gold
    )


def score_pack(
    sealed: dict[str, Any],
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    requirement_scores = []
    for requirement in sealed["requirements"]:
        if requirement["expected_status"] != "supported":
            continue
        values = requirement.get("required_values") or []
        value_hits = [
            _value_visible(
                value,
                value_index=value_index,
                requirement=requirement,
                units=units,
                as_of=sealed["as_of"],
            )
            for value_index, value in enumerate(values)
        ]
        requirement_scores.append(
            {
                "requirement_id": requirement["requirement_id"],
                "value_type": requirement["value_type"],
                "value_hits": value_hits,
                "visible": bool(values) and all(value_hits),
            }
        )
    return {
        "all_supported_visible": all(
            row["visible"] for row in requirement_scores
        ),
        "visible_requirement_count": sum(
            row["visible"] for row in requirement_scores
        ),
        "supported_requirement_count": len(requirement_scores),
        "requirements": requirement_scores,
        "unit_count": len(units),
        "prompt_chars": len(
            build_product_prompt(
                question=sealed["question_text"],
                evidence_units=units,
            )
        ),
        "units": [
            {
                "evidence_ref": unit["evidence_ref"],
                "candidate_ref": unit["candidate_ref"],
                "chunk_id": unit["chunk_id"],
                "start_char": unit["start_char"],
                "end_char": unit["end_char"],
                "text": unit["text"],
                "complete": bool(unit.get("complete")),
            }
            for unit in units
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the current two-unit question-only evidence pack with "
            "an eight-unit fill over stored candidates. No retrieval or "
            "generation calls are made."
        )
    )
    parser.add_argument("--sealed-set", type=Path, default=DEFAULT_SEALED_SET)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path.cwd()
    sealed_rows = read_jsonl(root / args.sealed_set)
    run_rows = [
        row
        for row in read_jsonl(root / args.run)
        if row.get("type") == "case"
    ]
    if len(sealed_rows) != 32 or len(run_rows) != 32:
        raise RuntimeError("the sealed and stored run inputs must have 32 cases")

    from src.v3.retrieve_v3 import load_runtime_artifacts

    artifacts = load_runtime_artifacts(root)
    temporal_by_document = {
        row["document_id"]: row
        for row in read_jsonl(root / GLOBAL_TEMPORAL_OVERLAY)
    }
    run_by_id = {row["candidate_id"]: row for row in run_rows}
    rows = []
    for sealed in sealed_rows:
        run = run_by_id[sealed["candidate_id"]]
        candidate_chunk_ids = [
            row["chunk_id"]
            for row in run["result"].get("candidates") or []
        ]
        arm_a_units = build_product_evidence_pack(
            candidate_chunk_ids,
            question=sealed["question_text"],
            requirement_queries=None,
            requested_subjects=None,
            chunks_by_id=artifacts.chunks_by_id,
            documents_by_id=artifacts.documents_by_id,
            temporal_by_document=temporal_by_document,
            max_units=DEFAULT_EVIDENCE_UNITS,
        )
        arm_b_units = fill_question_only_pack(
            arm_a_units,
            candidate_chunk_ids=candidate_chunk_ids,
            question=sealed["question_text"],
            chunks_by_id=artifacts.chunks_by_id,
            documents_by_id=artifacts.documents_by_id,
            temporal_by_document=temporal_by_document,
        )
        arm_a = score_pack(sealed, arm_a_units)
        arm_b = score_pack(sealed, arm_b_units)
        rows.append(
            {
                "type": "case",
                "slot_ordinal": sealed["slot_ordinal"],
                "candidate_id": sealed["candidate_id"],
                "question": sealed["question_text"],
                "arm_a_current_top2": arm_a,
                "arm_b_question_top8": arm_b,
                "visibility_win": (
                    not arm_a["all_supported_visible"]
                    and arm_b["all_supported_visible"]
                ),
                "visibility_loss": (
                    arm_a["all_supported_visible"]
                    and not arm_b["all_supported_visible"]
                ),
            }
        )

    arm_a_visible = sum(
        row["arm_a_current_top2"]["all_supported_visible"]
        for row in rows
    )
    arm_b_visible = sum(
        row["arm_b_question_top8"]["all_supported_visible"]
        for row in rows
    )
    summary = {
        "type": "summary",
        "evaluation_role": (
            "generation_free_adaptive_evidence_pack_ab_on_stored_candidates"
        ),
        "retrieval_calls": 0,
        "reranker_calls": 0,
        "qwen_calls": 0,
        "case_count": len(rows),
        "arm_a_all_supported_visible": arm_a_visible,
        "arm_b_all_supported_visible": arm_b_visible,
        "visibility_win_slots": [
            row["slot_ordinal"] for row in rows if row["visibility_win"]
        ],
        "visibility_loss_slots": [
            row["slot_ordinal"] for row in rows if row["visibility_loss"]
        ],
        "arm_a_visible_requirements": sum(
            row["arm_a_current_top2"]["visible_requirement_count"]
            for row in rows
        ),
        "arm_b_visible_requirements": sum(
            row["arm_b_question_top8"]["visible_requirement_count"]
            for row in rows
        ),
        "supported_requirement_count": sum(
            row["arm_a_current_top2"]["supported_requirement_count"]
            for row in rows
        ),
        "arm_a_units": sum(
            row["arm_a_current_top2"]["unit_count"] for row in rows
        ),
        "arm_b_units": sum(
            row["arm_b_question_top8"]["unit_count"] for row in rows
        ),
        "arm_a_prompt_chars": sum(
            row["arm_a_current_top2"]["prompt_chars"] for row in rows
        ),
        "arm_b_prompt_chars": sum(
            row["arm_b_question_top8"]["prompt_chars"] for row in rows
        ),
        "go": bool(
            arm_b_visible > arm_a_visible
            and not any(row["visibility_loss"] for row in rows)
        ),
    }
    write_jsonl(root / args.output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
