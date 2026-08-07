from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.diagnose_product_evidence_pack_top8_ab import (
    DEFAULT_RUN,
    DEFAULT_SEALED_SET,
    score_pack,
)
from src.v3.product_evidence_pack import (
    build_compact_product_evidence_pack,
    build_product_evidence_pack,
    surface_requirement_queries,
)
from src.v3.product_free_rag import (
    GLOBAL_TEMPORAL_OVERLAY,
)


DEFAULT_OUTPUT = Path(
    "reports/v3/product_surface_coverage_pack_ab_20260731.jsonl"
)
DEFAULT_SURFACE_UNITS = 7


def build_surface_coverage_pack(*args, **kwargs):
    kwargs.setdefault("max_units", DEFAULT_SURFACE_UNITS)
    return build_compact_product_evidence_pack(*args, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the current question-only pack with a generic surface-"
            "clause and token-coverage pack. No model calls are made."
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
    run_by_id = {row["candidate_id"]: row for row in run_rows}

    from src.v3.retrieve_v3 import load_runtime_artifacts

    artifacts = load_runtime_artifacts(root)
    temporal_by_document = {
        row["document_id"]: row
        for row in read_jsonl(root / GLOBAL_TEMPORAL_OVERLAY)
    }
    rows = []
    for sealed in sealed_rows:
        run = run_by_id[sealed["candidate_id"]]
        candidate_chunk_ids = [
            row["chunk_id"]
            for row in run["result"].get("candidates") or []
        ]
        current_units = build_product_evidence_pack(
            candidate_chunk_ids,
            question=sealed["question_text"],
            requirement_queries=None,
            requested_subjects=None,
            chunks_by_id=artifacts.chunks_by_id,
            documents_by_id=artifacts.documents_by_id,
            temporal_by_document=temporal_by_document,
            max_units=8,
        )
        surface_units = build_surface_coverage_pack(
            candidate_chunk_ids,
            question=sealed["question_text"],
            chunks_by_id=artifacts.chunks_by_id,
            documents_by_id=artifacts.documents_by_id,
            temporal_by_document=temporal_by_document,
        )
        current = score_pack(sealed, current_units)
        surface = score_pack(sealed, surface_units)
        rows.append(
            {
                "type": "case",
                "slot_ordinal": sealed["slot_ordinal"],
                "candidate_id": sealed["candidate_id"],
                "question": sealed["question_text"],
                "surface_queries": surface_requirement_queries(
                    sealed["question_text"]
                ),
                "current": current,
                "surface_coverage": surface,
                "visibility_win": (
                    not current["all_supported_visible"]
                    and surface["all_supported_visible"]
                ),
                "visibility_loss": (
                    current["all_supported_visible"]
                    and not surface["all_supported_visible"]
                ),
            }
        )
    summary = {
        "type": "summary",
        "evaluation_role": (
            "generation_free_surface_clause_coverage_pack_adaptive_ab"
        ),
        "retrieval_calls": 0,
        "reranker_calls": 0,
        "qwen_calls": 0,
        "case_count": len(rows),
        "current_all_supported_visible": sum(
            row["current"]["all_supported_visible"] for row in rows
        ),
        "surface_all_supported_visible": sum(
            row["surface_coverage"]["all_supported_visible"]
            for row in rows
        ),
        "current_visible_requirements": sum(
            row["current"]["visible_requirement_count"] for row in rows
        ),
        "surface_visible_requirements": sum(
            row["surface_coverage"]["visible_requirement_count"]
            for row in rows
        ),
        "supported_requirement_count": sum(
            row["current"]["supported_requirement_count"] for row in rows
        ),
        "visibility_win_slots": [
            row["slot_ordinal"] for row in rows if row["visibility_win"]
        ],
        "visibility_loss_slots": [
            row["slot_ordinal"] for row in rows if row["visibility_loss"]
        ],
        "current_prompt_chars": sum(
            row["current"]["prompt_chars"] for row in rows
        ),
        "surface_prompt_chars": sum(
            row["surface_coverage"]["prompt_chars"]
            for row in rows
        ),
        "go": bool(
            sum(
                row["surface_coverage"]["all_supported_visible"]
                for row in rows
            )
            > sum(row["current"]["all_supported_visible"] for row in rows)
            and not any(row["visibility_loss"] for row in rows)
        ),
    }
    write_jsonl(root / args.output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
