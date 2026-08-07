from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.diagnose_product_candidate_waterfall_missing32 import (
    _requirement_best_ranks,
)
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
)
from src.v3.product_candidate_identity import (
    candidate_row_from_chunk,
    reserve_then_fill,
    shortlist_document_chunks,
    shortlist_identity_documents,
)


DEFAULT_OUTPUT = Path(
    "reports/v3/product_candidate_assembly_ab_20260731.jsonl"
)


def _compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).casefold()


def duplicate_aware_requirement_visibility(
    sealed: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score repeated evidence in overlapping chunks of the sealed parent."""

    selected_ids = {str(row["chunk_id"]) for row in candidates}
    by_parent: dict[str, list[str]] = defaultdict(list)
    for row in candidates:
        by_parent[str(row["parent_document_id"])].append(
            str(row.get("display_text") or "")
        )
    requirements = []
    for requirement in sealed["requirements"]:
        if requirement["expected_status"] != "supported":
            continue
        units = requirement.get("acceptable_evidence_units") or []
        exact = any(
            str(unit["chunk_id"]) in selected_ids for unit in units
        )
        equivalent = False
        for document_id in {
            str(unit["document_id"]) for unit in units
        }:
            parent_text = _compact("\n".join(by_parent.get(document_id, [])))
            if not parent_text:
                continue
            evidence_texts = [
                _compact(str(unit.get("text") or ""))
                for unit in units
                if str(unit["document_id"]) == document_id
                and str(unit.get("text") or "").strip()
            ]
            required_values = [
                _compact(str(value))
                for value in requirement.get("required_values") or []
                if str(value).strip()
            ]
            if any(text and text in parent_text for text in evidence_texts):
                equivalent = True
                break
            if required_values and all(
                value in parent_text for value in required_values
            ):
                equivalent = True
                break
        requirements.append(
            {
                "requirement_id": requirement["requirement_id"],
                "visible": exact or equivalent,
                "exact_chunk": exact,
                "overlap_equivalent": equivalent and not exact,
            }
        )
    return {
        "all_supported_visible": all(
            row["visible"] for row in requirements
        ),
        "visible_requirement_count": sum(
            row["visible"] for row in requirements
        ),
        "supported_requirement_count": len(requirements),
        "requirements": requirements,
    }


def _rerank(
    rag: ProductFreeRAG,
    query: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scores = rag._score_pairs(
        [
            (
                query,
                rag._artifacts.chunks_by_id[row["chunk_id"]][
                    "retrieval_text"
                ],
            )
            for row in rows
        ]
    )
    return sorted(
        (
            {**row, "reranker_score": round(float(score), 8)}
            for row, score in zip(rows, scores, strict=True)
        ),
        key=lambda row: (
            -float(row["reranker_score"]),
            int(row.get("rank") or 0),
            str(row["chunk_id"]),
        ),
    )


def _arm_result(
    sealed: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **candidate_requirement_visibility(sealed, candidates),
        "duplicate_aware": duplicate_aware_requirement_visibility(
            sealed,
            candidates,
        ),
        "chunk_ids": [str(row["chunk_id"]) for row in candidates],
        "requirement_ranks": _requirement_best_ranks(
            sealed,
            [str(row["chunk_id"]) for row in candidates],
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare per-query reservation and temporal identity shortlist "
            "candidate assembly without generation."
        )
    )
    parser.add_argument("--sealed-set", type=Path, default=DEFAULT_SEALED_SET)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--slots", nargs="+", type=int)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path.cwd()
    sealed_rows = read_jsonl(root / args.sealed_set)
    if args.slots:
        requested_slots = set(args.slots)
        sealed_rows = [
            row
            for row in sealed_rows
            if int(row["slot_ordinal"]) in requested_slots
        ]
    run_rows = [
        row for row in read_jsonl(root / args.run) if row.get("type") == "case"
    ]
    run_by_id = {row["candidate_id"]: row for row in run_rows}
    rag = ProductFreeRAG(root=root, device=args.device)
    rag._initialize()

    from src.v3.question_router import DEFAULT_AS_OF
    from src.v3.retrieve_v3 import retrieve_with_embedding

    chunks_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in rag._artifacts.chunks_by_id.values():
        chunks_by_parent[str(chunk["parent_document_id"])].append(chunk)

    rows = []
    for sealed in sealed_rows:
        question = sealed["question_text"]
        baseline_candidates = (
            run_by_id[sealed["candidate_id"]]["result"].get("candidates") or []
        )
        queries = surface_requirement_queries(question)
        policy = search_policy_for_product_question(
            question,
            default_as_of=DEFAULT_AS_OF,
        )
        embeddings = rag._encode_queries(queries)
        per_query_hits = []
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
            locally_ranked = _rerank(rag, query, hits)
            per_query_hits.append(locally_ranked)
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
        global_ranked = _rerank(rag, question, list(union_by_chunk.values()))
        query_reservation = reserve_then_fill(
            [[row] for ranked in per_query_hits[1:] for row in ranked[:1]],
            global_ranked,
        )

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
        identity_rows = [
            candidate_row_from_chunk(
                chunk,
                rag._artifacts.documents_by_id[chunk["parent_document_id"]],
                fallback_rank=DEFAULT_RETRIEVAL_DEPTH + 1,
            )
            for chunk in shortlisted_chunks
        ]
        identity_union = dict(union_by_chunk)
        for row in identity_rows:
            identity_union.setdefault(str(row["chunk_id"]), row)
        identity_global = _rerank(rag, question, list(identity_union.values()))
        identity_reserved = []
        for document in shortlisted_documents:
            parent_id = str(document["document_id"])
            ranked_for_parent = [
                row
                for row in identity_global
                if str(row["parent_document_id"]) == parent_id
            ]
            if ranked_for_parent:
                identity_reserved.append([ranked_for_parent[0]])
        identity_shortlist = reserve_then_fill(
            identity_reserved,
            identity_global,
        )

        baseline = _arm_result(sealed, baseline_candidates)
        reservation = _arm_result(sealed, query_reservation)
        identity = _arm_result(sealed, identity_shortlist)
        row = {
            "type": "case",
            "slot_ordinal": sealed["slot_ordinal"],
            "candidate_id": sealed["candidate_id"],
            "question": question,
            "surface_queries": queries,
            "baseline": baseline,
            "query_reservation": reservation,
            "identity_shortlist": {
                **identity,
                "documents": shortlisted_documents,
                "injected_chunk_ids": [
                    str(chunk["chunk_id"]) for chunk in shortlisted_chunks
                ],
            },
            "query_reservation_win": (
                not baseline["all_supported_visible"]
                and reservation["all_supported_visible"]
            ),
            "query_reservation_loss": (
                baseline["all_supported_visible"]
                and not reservation["all_supported_visible"]
            ),
            "identity_shortlist_win": (
                not baseline["all_supported_visible"]
                and identity["all_supported_visible"]
            ),
            "identity_shortlist_loss": (
                baseline["all_supported_visible"]
                and not identity["all_supported_visible"]
            ),
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    "slot": row["slot_ordinal"],
                    "baseline": baseline["all_supported_visible"],
                    "query_reservation": reservation[
                        "all_supported_visible"
                    ],
                    "identity_shortlist": identity[
                        "all_supported_visible"
                    ],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    def count(arm: str) -> int:
        return sum(row[arm]["all_supported_visible"] for row in rows)

    def duplicate_aware_count(arm: str) -> int:
        return sum(
            row[arm]["duplicate_aware"]["all_supported_visible"]
            for row in rows
        )

    summary = {
        "type": "summary",
        "evaluation_role": "generation_free_candidate_assembly_adaptive_ab",
        "case_count": len(rows),
        "qwen_calls": 0,
        "baseline_all_supported_visible": count("baseline"),
        "baseline_duplicate_aware_visible": duplicate_aware_count(
            "baseline"
        ),
        "query_reservation_all_supported_visible": count(
            "query_reservation"
        ),
        "query_reservation_duplicate_aware_visible": (
            duplicate_aware_count("query_reservation")
        ),
        "query_reservation_wins": sum(
            row["query_reservation_win"] for row in rows
        ),
        "query_reservation_losses": sum(
            row["query_reservation_loss"] for row in rows
        ),
        "identity_shortlist_all_supported_visible": count(
            "identity_shortlist"
        ),
        "identity_shortlist_duplicate_aware_visible": (
            duplicate_aware_count("identity_shortlist")
        ),
        "identity_shortlist_wins": sum(
            row["identity_shortlist_win"] for row in rows
        ),
        "identity_shortlist_losses": sum(
            row["identity_shortlist_loss"] for row in rows
        ),
    }
    write_jsonl(root / args.output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
