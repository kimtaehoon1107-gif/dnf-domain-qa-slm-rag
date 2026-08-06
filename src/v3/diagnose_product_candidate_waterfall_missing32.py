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
from src.v3.diagnose_product_surface_retrieval_ab import (
    candidate_requirement_visibility,
)
from src.v3.product_free_rag import (
    DEFAULT_RETRIEVAL_DEPTH,
    ProductFreeRAG,
    search_policy_for_product_question,
    select_parent_diverse_candidates,
)


DEFAULT_OUTPUT = Path(
    "reports/v3/product_candidate_waterfall_missing32_20260731.jsonl"
)


def classify_drop_stage(
    *,
    union_visible: bool,
    reranker_top8_visible: bool,
    parent_top8_visible: bool,
) -> str:
    if not union_visible:
        return "initial_union_missing"
    if parent_top8_visible:
        return "visible"
    if reranker_top8_visible:
        return "parent_cap_or_final_assembly"
    return "reranker_below_final_cut"


def _requirement_best_ranks(
    sealed: dict[str, Any],
    ranked_ids: list[str],
) -> list[dict[str, Any]]:
    ranks = {chunk_id: index for index, chunk_id in enumerate(ranked_ids, 1)}
    output = []
    for requirement in sealed["requirements"]:
        if requirement["expected_status"] != "supported":
            continue
        gold_ids = {
            str(unit["chunk_id"])
            for unit in requirement.get("acceptable_evidence_units") or []
        }
        visible_ranks = [
            ranks[chunk_id] for chunk_id in gold_ids if chunk_id in ranks
        ]
        output.append(
            {
                "requirement_id": requirement["requirement_id"],
                "best_rank": min(visible_ranks) if visible_ranks else None,
                "gold_chunk_ids": sorted(gold_ids),
            }
        )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Trace reviewed evidence through per-query top20, union, "
            "reranker top8, and parent-diverse top8 for baseline misses."
        )
    )
    parser.add_argument("--sealed-set", type=Path, default=DEFAULT_SEALED_SET)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cpu")
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
    missing_rows = [
        sealed
        for sealed in sealed_rows
        if not candidate_requirement_visibility(
            sealed,
            baseline_by_id[sealed["candidate_id"]]["result"].get(
                "candidates"
            )
            or [],
        )["all_supported_visible"]
    ]
    rag = ProductFreeRAG(root=root, device=args.device)
    rag._initialize()

    from src.v3.question_router import DEFAULT_AS_OF
    from src.v3.retrieve_v3 import retrieve_with_embedding

    rows = []
    for sealed in missing_rows:
        queries = surface_requirement_queries(sealed["question_text"])
        embeddings = rag._encode_queries(queries)
        policy = search_policy_for_product_question(
            sealed["question_text"],
            default_as_of=DEFAULT_AS_OF,
        )
        per_query = []
        union_by_chunk: dict[str, dict[str, Any]] = {}
        for query_index, (query, embedding) in enumerate(
            zip(queries, embeddings, strict=True)
        ):
            hits = retrieve_with_embedding(
                query,
                embedding,
                rag._artifacts,
                top_k=DEFAULT_RETRIEVAL_DEPTH,
                policy=policy,
            )
            per_query.append(
                {
                    "query": query,
                    "requirement_ranks": _requirement_best_ranks(
                        sealed,
                        [str(hit["chunk_id"]) for hit in hits],
                    ),
                }
            )
            for hit in hits:
                chunk_id = str(hit["chunk_id"])
                if chunk_id not in union_by_chunk:
                    union_by_chunk[chunk_id] = {
                        **hit,
                        "query_indexes": [query_index],
                    }
                else:
                    union_by_chunk[chunk_id]["query_indexes"].append(
                        query_index
                    )
        union = list(union_by_chunk.values())
        pairs = [
            (
                sealed["question_text"],
                rag._artifacts.chunks_by_id[row["chunk_id"]][
                    "retrieval_text"
                ],
            )
            for row in union
        ]
        scores = rag._score_pairs(pairs)
        reranked = sorted(
            (
                {
                    **row,
                    "reranker_score": round(float(score), 8),
                }
                for row, score in zip(union, scores, strict=True)
            ),
            key=lambda row: (
                -float(row["reranker_score"]),
                int(row.get("rank") or 0),
                str(row["chunk_id"]),
            ),
        )
        plain_top8 = reranked[:8]
        parent_top8 = select_parent_diverse_candidates(reranked)
        union_visibility = candidate_requirement_visibility(sealed, union)
        plain_visibility = candidate_requirement_visibility(
            sealed,
            plain_top8,
        )
        parent_visibility = candidate_requirement_visibility(
            sealed,
            parent_top8,
        )
        row = {
            "type": "case",
            "slot_ordinal": sealed["slot_ordinal"],
            "candidate_id": sealed["candidate_id"],
            "question": sealed["question_text"],
            "queries": queries,
            "per_query_top20": per_query,
            "union": {
                **union_visibility,
                "candidate_count": len(union),
                "requirement_ranks": _requirement_best_ranks(
                    sealed,
                    [str(item["chunk_id"]) for item in union],
                ),
            },
            "reranker": {
                "requirement_ranks": _requirement_best_ranks(
                    sealed,
                    [str(item["chunk_id"]) for item in reranked],
                ),
                "plain_top8_visible": plain_visibility[
                    "all_supported_visible"
                ],
                "plain_top8_chunk_ids": [
                    item["chunk_id"] for item in plain_top8
                ],
            },
            "parent_top8": {
                **parent_visibility,
                "chunk_ids": [item["chunk_id"] for item in parent_top8],
            },
            "drop_stage": classify_drop_stage(
                union_visible=union_visibility["all_supported_visible"],
                reranker_top8_visible=plain_visibility[
                    "all_supported_visible"
                ],
                parent_top8_visible=parent_visibility[
                    "all_supported_visible"
                ],
            ),
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    "slot": row["slot_ordinal"],
                    "union": union_visibility["all_supported_visible"],
                    "plain_top8": plain_visibility[
                        "all_supported_visible"
                    ],
                    "parent_top8": parent_visibility[
                        "all_supported_visible"
                    ],
                    "drop_stage": row["drop_stage"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    summary = {
        "type": "summary",
        "evaluation_role": (
            "candidate_waterfall_on_existing32_baseline_misses"
        ),
        "case_count": len(rows),
        "retrieval_query_count": sum(len(row["queries"]) for row in rows),
        "qwen_calls": 0,
        "union_visible": sum(
            row["union"]["all_supported_visible"] for row in rows
        ),
        "plain_top8_visible": sum(
            row["reranker"]["plain_top8_visible"] for row in rows
        ),
        "parent_top8_visible": sum(
            row["parent_top8"]["all_supported_visible"] for row in rows
        ),
        "drop_stage_counts": {
            stage: sum(row["drop_stage"] == stage for row in rows)
            for stage in (
                "initial_union_missing",
                "reranker_below_final_cut",
                "parent_cap_or_final_assembly",
                "visible",
            )
        },
    }
    write_jsonl(root / args.output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
