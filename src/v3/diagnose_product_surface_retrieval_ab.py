from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.diagnose_product_evidence_pack_top8_ab import (
    DEFAULT_RUN,
    DEFAULT_SEALED_SET,
)
from src.v3.diagnose_product_surface_coverage_pack import (
    surface_requirement_queries,
)
from src.v3.product_free_rag import ProductFreeRAG


DEFAULT_OUTPUT = Path(
    "reports/v3/product_surface_requirement_retrieval_ab_20260731.jsonl"
)


def candidate_requirement_visibility(
    sealed: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = {
        str(candidate["chunk_id"]) for candidate in candidates
    }
    requirement_hits = [
        {
            "requirement_id": requirement["requirement_id"],
            "visible": bool(
                candidate_ids
                & {
                    str(unit["chunk_id"])
                    for unit in (
                        requirement.get("acceptable_evidence_units") or []
                    )
                }
            ),
        }
        for requirement in sealed["requirements"]
        if requirement["expected_status"] == "supported"
    ]
    return {
        "all_supported_visible": all(
            row["visible"] for row in requirement_hits
        ),
        "visible_requirement_count": sum(
            row["visible"] for row in requirement_hits
        ),
        "supported_requirement_count": len(requirement_hits),
        "requirements": requirement_hits,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare stored full-question candidates with full-question plus "
            "generic surface-clause queries. Qwen is not called."
        )
    )
    parser.add_argument("--sealed-set", type=Path, default=DEFAULT_SEALED_SET)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path.cwd()
    sealed_rows = read_jsonl(root / args.sealed_set)
    baseline_rows = [
        row
        for row in read_jsonl(root / args.run)
        if row.get("type") == "case"
    ]
    baseline_by_id = {row["candidate_id"]: row for row in baseline_rows}
    output_path = root / args.output
    rows: list[dict[str, Any]] = []
    if output_path.exists():
        if not args.resume:
            raise RuntimeError(
                f"output already exists; pass --resume: {output_path}"
            )
        rows = [
            row
            for row in read_jsonl(output_path)
            if row.get("type") == "case"
        ]
    completed_ids = {row["candidate_id"] for row in rows}
    rag = ProductFreeRAG(root=root, device=args.device)
    retrieval_calls = 0
    errors = []
    for sealed in sealed_rows:
        if sealed["candidate_id"] in completed_ids:
            continue
        baseline = baseline_by_id[sealed["candidate_id"]]
        baseline_candidates = baseline["result"].get("candidates") or []
        queries = surface_requirement_queries(sealed["question_text"])
        requirement_queries = queries[1:]
        try:
            if requirement_queries:
                retrieval_calls += 1
                expanded_candidates = rag.retrieve(
                    sealed["question_text"],
                    requirement_queries=requirement_queries,
                )
            else:
                expanded_candidates = baseline_candidates
            arm_a = candidate_requirement_visibility(
                sealed,
                baseline_candidates,
            )
            arm_b = candidate_requirement_visibility(
                sealed,
                expanded_candidates,
            )
            row = {
                "type": "case",
                "evaluation_role": (
                    "surface_requirement_query_retrieval_adaptive_ab"
                ),
                "slot_ordinal": sealed["slot_ordinal"],
                "candidate_id": sealed["candidate_id"],
                "question": sealed["question_text"],
                "requirement_queries": requirement_queries,
                "retrieval_reused": not requirement_queries,
                "arm_a_full_question": {
                    **arm_a,
                    "candidates": baseline_candidates,
                },
                "arm_b_surface_queries": {
                    **arm_b,
                    "candidates": expanded_candidates,
                },
                "visibility_win": (
                    not arm_a["all_supported_visible"]
                    and arm_b["all_supported_visible"]
                ),
                "visibility_loss": (
                    arm_a["all_supported_visible"]
                    and not arm_b["all_supported_visible"]
                ),
            }
            rows.append(row)
            write_jsonl(output_path, rows)
            print(
                json.dumps(
                    {
                        "slot": sealed["slot_ordinal"],
                        "queries": len(requirement_queries),
                        "baseline": arm_a["all_supported_visible"],
                        "expanded": arm_b["all_supported_visible"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:
            error = {
                "candidate_id": sealed["candidate_id"],
                "slot_ordinal": sealed["slot_ordinal"],
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            errors.append(error)
            print(
                json.dumps({"type": "error", **error}, ensure_ascii=False),
                flush=True,
            )
    summary = {
        "type": "summary",
        "evaluation_role": (
            "surface_requirement_query_retrieval_adaptive_ab"
        ),
        "case_count": len(sealed_rows),
        "completed": len(rows),
        "errors": errors,
        "retrieval_calls_this_invocation": retrieval_calls,
        "qwen_calls": 0,
        "arm_a_all_supported_visible": sum(
            row["arm_a_full_question"]["all_supported_visible"]
            for row in rows
        ),
        "arm_b_all_supported_visible": sum(
            row["arm_b_surface_queries"]["all_supported_visible"]
            for row in rows
        ),
        "arm_a_visible_requirements": sum(
            row["arm_a_full_question"]["visible_requirement_count"]
            for row in rows
        ),
        "arm_b_visible_requirements": sum(
            row["arm_b_surface_queries"]["visible_requirement_count"]
            for row in rows
        ),
        "supported_requirement_count": sum(
            row["arm_a_full_question"]["supported_requirement_count"]
            for row in rows
        ),
        "visibility_win_slots": [
            row["slot_ordinal"] for row in rows if row["visibility_win"]
        ],
        "visibility_loss_slots": [
            row["slot_ordinal"] for row in rows if row["visibility_loss"]
        ],
    }
    summary["go"] = bool(
        summary["arm_b_all_supported_visible"]
        > summary["arm_a_all_supported_visible"]
        and not summary["visibility_loss_slots"]
        and not errors
    )
    write_jsonl(output_path, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
