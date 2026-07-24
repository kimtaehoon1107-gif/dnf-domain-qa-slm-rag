from __future__ import annotations

import argparse
import json
import os
import sys
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
    DEFAULT_SOURCE,
    DEFAULT_TABLE_FACTS,
    DEFAULT_TEMPORAL,
    _baseline_row,
    _candidate_pool_row,
    _compatible_reviewed,
)
from src.v3.evaluate_grounded_llm_replay import run_fixed_requirement_replay
from src.v3.score_typed_evidence_ref_generalization import (
    score_generalization_cases,
)


DEFAULT_SLOTS = [1, 9, 14, 17, 22, 49, 57]
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "typed_evidence_ref_temporal_role_qwen3_8b_smoke_20260725.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "typed_evidence_ref_temporal_role_qwen3_8b_smoke_20260725.json"
)


def _transition(previous_correct: bool, current_correct: bool) -> str:
    if previous_correct and current_correct:
        return "preserved_correct"
    if previous_correct and not current_correct:
        return "new_regression"
    if not previous_correct and current_correct:
        return "recovered"
    return "persistent_error"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a targeted Qwen3 8B temporal-role generation smoke with "
            "stored candidate pools."
        )
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--slots", type=int, nargs="+", default=DEFAULT_SLOTS)
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--table-facts", type=Path, default=DEFAULT_TABLE_FACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("smoke output or summary already exists")

    requested_slots = list(dict.fromkeys(args.slots))
    sealed_all = read_jsonl(resolved(args.sealed))
    source_all = read_jsonl(resolved(args.source))
    sealed_by_slot = {row["slot_ordinal"]: row for row in sealed_all}
    source_by_id = {row["candidate_id"]: row for row in source_all}
    missing_slots = [
        slot for slot in requested_slots if slot not in sealed_by_slot
    ]
    if missing_slots:
        raise RuntimeError(f"unknown slots: {missing_slots}")

    sealed_rows = [sealed_by_slot[slot] for slot in requested_slots]
    source_rows = [
        source_by_id[sealed["candidate_id"]] for sealed in sealed_rows
    ]
    reviewed_rows = [_compatible_reviewed(row) for row in sealed_rows]
    baseline_rows = [
        _baseline_row(sealed, source)
        for sealed, source in zip(sealed_rows, source_rows, strict=True)
    ]
    pool_rows = [
        _candidate_pool_row(sealed, source)
        for sealed, source in zip(sealed_rows, source_rows, strict=True)
    ]

    chunks = read_jsonl(resolved(args.chunks))
    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")

    def report_progress(
        _: dict[str, Any],
        current: int,
        total: int,
    ) -> None:
        print(
            json.dumps(
                {
                    "stage": "generation",
                    "progress": f"{current}/{total}",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    generated_rows = run_fixed_requirement_replay(
        reviewed_rows=reviewed_rows,
        baseline_rows=baseline_rows,
        chunks=chunks,
        documents=read_jsonl(resolved(args.documents)),
        temporal_rows=read_jsonl(resolved(args.temporal)),
        table_facts=read_jsonl(resolved(args.table_facts)),
        model=args.model,
        as_of="2026-07-22",
        reasoning_effort="high",
        timeout_seconds=180,
        split_evidence_schema=True,
        batch_requirements=True,
        typed_evidence_refs=True,
        result_callback=report_progress,
        candidate_pool_rows=pool_rows,
        candidate_pool_arm="subject_arm_full",
    )
    enriched_rows = [
        {
            **generated,
            "slot_ordinal": sealed["slot_ordinal"],
            "source_id": sealed["source_id"],
            "primary_dimension": sealed["primary_dimension"],
            "retrieval": source["retrieval"],
        }
        for generated, sealed, source in zip(
            generated_rows,
            sealed_rows,
            source_rows,
            strict=True,
        )
    ]
    scored_rows, score_summary = score_generalization_cases(
        sealed_rows,
        enriched_rows,
        chunks_by_id={row["chunk_id"]: row for row in chunks},
    )

    cases = []
    for sealed, previous, current in zip(
        sealed_rows,
        source_rows,
        scored_rows,
        strict=True,
    ):
        previous_correct = bool(
            previous["holdout_score"]["gold_value_complete"]
        )
        current_correct = bool(
            current["holdout_score"]["gold_value_complete"]
        )
        cases.append(
            {
                "slot_ordinal": sealed["slot_ordinal"],
                "question_text": sealed["question_text"],
                "previous_category": (
                    "previous_correct"
                    if previous_correct
                    else "previous_error"
                ),
                "previous": {
                    "outcome": previous["holdout_score"]["outcome"],
                    "failure_stage": previous["holdout_score"][
                        "failure_stage"
                    ],
                    "model_output": [
                        call.get("output")
                        for call in previous["model_call"]["calls"]
                    ],
                },
                "current": {
                    "outcome": current["holdout_score"]["outcome"],
                    "failure_stage": current["holdout_score"][
                        "failure_stage"
                    ],
                    "verified_output": current["verified_output"],
                    "model_call": current["model_call"],
                },
                "transition": _transition(
                    previous_correct,
                    current_correct,
                ),
            }
        )

    summary = {
        "evaluation_role": (
            "targeted_adaptive_generation_smoke_not_generalization"
        ),
        "model": args.model,
        "slots": requested_slots,
        "retrieval_reexecuted": False,
        "stored_candidate_pools_reused": True,
        "new_model_calls": sum(
            row["model_call"]["call_count"] for row in scored_rows
        ),
        "previous_error_slots": [
            row["slot_ordinal"]
            for row in cases
            if row["previous_category"] == "previous_error"
        ],
        "previous_correct_slots": [
            row["slot_ordinal"]
            for row in cases
            if row["previous_category"] == "previous_correct"
        ],
        "transitions": {
            transition: [
                row["slot_ordinal"]
                for row in cases
                if row["transition"] == transition
            ]
            for transition in (
                "recovered",
                "persistent_error",
                "preserved_correct",
                "new_regression",
            )
        },
        "score_summary": score_summary,
        "cases": cases,
        "inputs": {
            "sealed_sha256": file_sha256(resolved(args.sealed)),
            "source_sha256": file_sha256(resolved(args.source)),
            "chunks_sha256": file_sha256(resolved(args.chunks)),
            "documents_sha256": file_sha256(resolved(args.documents)),
            "temporal_sha256": file_sha256(resolved(args.temporal)),
            "table_facts_sha256": file_sha256(resolved(args.table_facts)),
        },
        "output": args.output.as_posix(),
    }
    write_jsonl(output_path, scored_rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "model": args.model,
                "slots": requested_slots,
                "new_model_calls": summary["new_model_calls"],
                "transitions": summary["transitions"],
                "correct": score_summary["gold_value_complete"],
                "generation_errors": score_summary[
                    "generation_error_count"
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
