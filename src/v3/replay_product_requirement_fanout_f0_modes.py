from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3 import answer_target_router, product_evidence_pack
from src.v3.product_free_rag import answer_product_rag_from_candidates


DEFAULT_INPUT = Path(
    "reports/v3/product_free_rag_a6_pending_adaptive_replay_20260806.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_requirement_fanout_f0_mode_replay_20260806.jsonl"
)


def _replay_result(
    case: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    saved = case["result"]
    raw_output = copy.deepcopy(saved["raw_model_output"])

    def saved_generator(**_: Any) -> dict[str, Any]:
        return {
            "output": copy.deepcopy(raw_output),
            "model": "saved-output-replay",
            "provider": "none",
            "latency_ms": 0.0,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        }

    return answer_product_rag_from_candidates(
        question=str(case["question"]),
        requirement_queries=None,
        requested_subjects=list(
            (saved.get("verification") or {}).get("requested_subjects") or []
        ),
        selected=list(saved.get("candidates") or []),
        chunks_by_id=chunks_by_id,
        documents_by_id={},
        temporal_by_document={},
        model="saved-output-replay",
        timeout_seconds=0.0,
        generator=saved_generator,
        evidence_units_override=list(saved.get("evidence_pack") or []),
    )


def _legacy_boundary_filter(
    tokens: list[Any],
    allowed_forms: set[str] | None = None,
) -> list[int]:
    boundaries = answer_target_router._clause_boundaries(tokens)
    if not allowed_forms:
        return boundaries
    return [
        index
        for index in boundaries
        if str(tokens[index].form) in allowed_forms
    ]


def _with_boundary_function(
    boundary_function: Callable[..., list[int]],
    replay: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    original = product_evidence_pack._clause_boundaries
    product_evidence_pack._clause_boundaries = boundary_function
    try:
        return replay()
    finally:
        product_evidence_pack._clause_boundaries = original


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay saved A6 outputs across the F0 clause-boundary change"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    input_path = args.input if args.input.is_absolute() else root / args.input
    chunks_path = args.chunks if args.chunks.is_absolute() else root / args.chunks
    output_path = args.output if args.output.is_absolute() else root / args.output
    if output_path.exists():
        raise RuntimeError(f"replay output already exists: {output_path}")

    cases = [
        row for row in read_jsonl(input_path) if row.get("type") == "case"
    ]
    chunks_by_id = {
        row["chunk_id"]: row for row in read_jsonl(chunks_path)
    }
    replayed = []
    for case in cases:
        baseline = _with_boundary_function(
            _legacy_boundary_filter,
            lambda: _replay_result(case, chunks_by_id=chunks_by_id),
        )
        f0 = _replay_result(case, chunks_by_id=chunks_by_id)
        replayed.append(
            {
                "type": "case",
                "slot_ordinal": case["slot_ordinal"],
                "question": case["question"],
                "saved_mode": case["result"]["mode"],
                "baseline_mode": baseline["mode"],
                "f0_mode": f0["mode"],
                "mode_changed": baseline["mode"] != f0["mode"],
                "baseline_claim_count": len(baseline["claims"]),
                "f0_claim_count": len(f0["claims"]),
                "baseline_reason": baseline["verification"].get("reason"),
                "f0_reason": f0["verification"].get("reason"),
            }
        )
    summary = {
        "type": "summary",
        "runner_version": "product-requirement-fanout-f0-mode-replay-v1",
        "qwen_calls": 0,
        "case_count": len(replayed),
        "mode_changed_slots": [
            row["slot_ordinal"] for row in replayed if row["mode_changed"]
        ],
        "saved_baseline_mode_drift_slots": [
            row["slot_ordinal"]
            for row in replayed
            if row["saved_mode"] != row["baseline_mode"]
        ],
    }
    write_jsonl(output_path, [*replayed, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
