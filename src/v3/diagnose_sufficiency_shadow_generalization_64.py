from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.diagnose_typed_evidence_ref_generalization_64_precision_fix import (
    DEFAULT_CHUNKS,
    DEFAULT_DOCUMENTS,
    DEFAULT_SEALED,
    DEFAULT_TABLE_FACTS,
    DEFAULT_TEMPORAL,
)
from src.v3.evaluate_grounded_llm_replay import build_table_rows_by_chunk
from src.v3.generate_grounded_llm_answer import (
    select_table_rows_for_requirement,
)
from src.v3.typed_evidence_ref import (
    assess_requirement_evidence_sufficiency_shadow,
    build_typed_evidence_prompt,
)


DEFAULT_CANDIDATES = Path(
    "outputs/v3/diagnostics/"
    "product_router_generalization_64_candidate_pools_20260726.jsonl"
)
DEFAULT_RESULTS = Path(
    "outputs/v3/diagnostics/"
    "typed_evidence_ref_product_router_full64_20260726.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "typed_evidence_ref_sufficiency_shadow_full64_20260727.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "typed_evidence_ref_sufficiency_shadow_full64_20260727.json"
)


def summarize_shadow(rows: list[dict[str, Any]]) -> dict[str, Any]:
    requirements = [
        requirement
        for row in rows
        for requirement in row["requirements"]
    ]
    assessable = [
        requirement
        for requirement in requirements
        if requirement["assessable"]
    ]
    triggered = [
        requirement
        for requirement in assessable
        if requirement["would_trigger"]
    ]
    return {
        "question_count": len(rows),
        "requirement_count": len(requirements),
        "assessable_requirement_count": len(assessable),
        "would_trigger_requirement_count": len(triggered),
        "would_trigger_slots": sorted(
            {
                row["slot_ordinal"]
                for row in rows
                if any(
                    requirement["would_trigger"]
                    for requirement in row["requirements"]
                )
            }
        ),
        "excluded_table_requirement_count": sum(
            requirement["reason"] == "table_branch_excluded"
            for requirement in requirements
        ),
        "excluded_unregistered_requirement_count": sum(
            requirement["reason"] == "unregistered_relation_excluded"
            for requirement in requirements
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a same-evidence-group sufficiency gate in shadow mode. "
            "No fallback retrieval or generation is executed."
        )
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--table-facts", type=Path, default=DEFAULT_TABLE_FACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--as-of", default="2026-07-22")
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("shadow output or summary already exists")

    sealed_rows = read_jsonl(resolved(args.sealed))
    candidate_rows = read_jsonl(resolved(args.candidates))
    result_rows = read_jsonl(resolved(args.results))
    if not (
        len(sealed_rows) == len(candidate_rows) == len(result_rows) == 64
    ):
        raise RuntimeError("shadow diagnostic requires exactly 64 aligned rows")
    candidates_by_id = {
        row["candidate_id"]: row for row in candidate_rows
    }
    results_by_id = {row["candidate_id"]: row for row in result_rows}
    candidate_ids = {row["candidate_id"] for row in sealed_rows}
    if candidate_ids != set(candidates_by_id) or candidate_ids != set(
        results_by_id
    ):
        raise RuntimeError("sealed, candidate, and result IDs differ")

    chunks = read_jsonl(resolved(args.chunks))
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {
        row["document_id"]: row
        for row in read_jsonl(resolved(args.documents))
    }
    temporal_by_document = {
        row["document_id"]: row
        for row in read_jsonl(resolved(args.temporal))
    }
    table_rows_by_chunk = build_table_rows_by_chunk(
        read_jsonl(resolved(args.table_facts)),
        chunks_by_id=chunks_by_id,
    )

    output_rows = []
    for sealed in sealed_rows:
        candidate = candidates_by_id[sealed["candidate_id"]]
        result = results_by_id[sealed["candidate_id"]]
        requirement_candidates = candidate[
            "requirement_candidate_chunk_ids"
        ]
        if len(requirement_candidates) != len(sealed["requirements"]):
            raise RuntimeError("requirement candidate count differs")
        assessments: list[dict[str, Any] | None] = [
            None for _ in sealed["requirements"]
        ]
        grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for index, (requirement, chunk_ids) in enumerate(
            zip(
                sealed["requirements"],
                requirement_candidates,
                strict=True,
            )
        ):
            matching_rows = select_table_rows_for_requirement(
                table_rows_by_chunk,
                requirement,
            )
            if any(matching_rows.get(chunk_id) for chunk_id in chunk_ids):
                assessments[index] = {
                    "requirement_id": requirement["requirement_id"],
                    "scope": "model_visible_evidence",
                    "assessable": False,
                    "would_trigger": False,
                    "reason": "table_branch_excluded",
                    "supporting_group_refs": [],
                }
                continue
            grouped[tuple(chunk_ids)].append(index)

        for chunk_id_tuple, indices in grouped.items():
            requirements = [
                sealed["requirements"][index] for index in indices
            ]
            _, units_by_ref = build_typed_evidence_prompt(
                question=sealed["question_text"],
                requirements=requirements,
                question_time_scope=sealed["time_scope"],
                as_of=args.as_of,
                candidate_chunk_ids=list(chunk_id_tuple),
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                temporal_by_document=temporal_by_document,
            )
            for index in indices:
                assessments[index] = (
                    assess_requirement_evidence_sufficiency_shadow(
                        sealed["requirements"][index],
                        evidence_units_by_ref=units_by_ref,
                        as_of=args.as_of,
                    )
                )
        if any(assessment is None for assessment in assessments):
            raise RuntimeError("shadow assessment is incomplete")
        output_rows.append(
            {
                "candidate_id": sealed["candidate_id"],
                "slot_ordinal": sealed["slot_ordinal"],
                "question_text": sealed["question_text"],
                "requirements": assessments,
                "observed_outcome": result["holdout_score"]["outcome"],
                "diagnostic_role": (
                    "adaptive_shadow_only_no_retrieval_or_generation"
                ),
            }
        )

    write_jsonl(output_path, output_rows)
    summary = {
        "evaluation_role": (
            "adaptive_sufficiency_shadow_not_generalization_or_promotion"
        ),
        "fallback_retrieval_calls": 0,
        "generation_calls": 0,
        **summarize_shadow(output_rows),
        "inputs": {
            "sealed_sha256": file_sha256(resolved(args.sealed)),
            "candidates_sha256": file_sha256(resolved(args.candidates)),
            "results_sha256": file_sha256(resolved(args.results)),
        },
        "output": args.output.as_posix(),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
