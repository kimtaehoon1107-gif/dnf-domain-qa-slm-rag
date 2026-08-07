from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.requirement_entity_anchor import build_official_entity_index
from src.v3.simple_domain_rag import SimpleDomainRAG
from src.v3.subject_anchored_retrieval import (
    build_planner_relation_queries,
    candidate_supports_subject,
    extract_subject_anchored_queries,
    merge_subject_anchored_candidates,
    reciprocal_rank_fuse,
    subject_supported_hits,
)


EVALUATOR_VERSION = "simple-subject-anchored-retrieval-ab-v1"
DEFAULT_EVAL_SET = Path(
    "data/v3/evaluation/requirement_surface_query_canary_reviewed_"
    "533a4b031369cdd63872cd4f52a33d9128fbcf6cf42a344e2693b4959a76c561.jsonl"
)
DEFAULT_BASELINE = Path("outputs/v3/simple_domain_rag_eval32_ctx8192_cases.jsonl")
DEFAULT_OUTPUT = Path("outputs/v3/simple_subject_anchored_retrieval_ab_cases.jsonl")
DEFAULT_REPORT = Path("reports/v3/simple_subject_anchored_retrieval_ab_summary.json")


def _covered(reviewed: dict[str, Any], candidate_ids: list[str]) -> bool:
    selected = set(candidate_ids)
    return all(
        bool(selected & set(group["acceptable_chunk_ids"]))
        for group in reviewed["evidence_groups"]
    )


def _blocked_citations(
    baseline: dict[str, Any],
    *,
    subject: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked = []
    for requirement in baseline["result"]["requirements"]:
        if requirement["status"] != "supported_exact":
            continue
        for citation in requirement["citations"]:
            chunk = chunks_by_id[citation["chunk_id"]]
            document = documents_by_id[chunk["parent_document_id"]]
            if not candidate_supports_subject(
                subject,
                chunk=chunk,
                document=document,
            ):
                blocked.append(
                    {
                        "question_part": requirement["question_part"],
                        "chunk_id": citation["chunk_id"],
                        "source_id": citation["source_id"],
                    }
                )
    return blocked


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_covered = {
        row["candidate_id"] for row in rows if row["baseline_candidate_covered"]
    }
    arm_covered = {
        row["candidate_id"] for row in rows if row["arm_candidate_covered"]
    }
    blocked = [row for row in rows if row["blocked_citations"]]
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "case_count": len(rows),
        "applied_case_count": sum(row["plan"] is not None for row in rows),
        "baseline_candidate_covered": len(baseline_covered),
        "arm_candidate_covered": len(arm_covered),
        "newly_covered_slots": sorted(
            row["slot_ordinal"]
            for row in rows
            if row["arm_candidate_covered"]
            and not row["baseline_candidate_covered"]
        ),
        "candidate_regression_slots": sorted(
            row["slot_ordinal"]
            for row in rows
            if row["baseline_candidate_covered"]
            and not row["arm_candidate_covered"]
        ),
        "maximum_candidate_count": max(
            (len(row["arm_candidate_ids"]) for row in rows),
            default=0,
        ),
        "blocked_citation_count": sum(
            len(row["blocked_citations"]) for row in rows
        ),
        "blocked_slots": sorted(row["slot_ordinal"] for row in blocked),
        "strict_success_blocked_slots": sorted(
            row["slot_ordinal"]
            for row in blocked
            if row["baseline_all_evidence_spans_hit"]
        ),
        "false_full_blocked_slots": sorted(
            row["slot_ordinal"]
            for row in blocked
            if row["baseline_false_full"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--slots", type=int, nargs="+")
    parser.add_argument(
        "--query-source",
        choices=("surface", "planner-relation", "surface-planner-fusion"),
        default="surface",
    )
    args = parser.parse_args()

    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    reviewed_rows = read_jsonl(resolved(args.eval_set))
    baseline_rows = read_jsonl(resolved(args.baseline))
    baseline_by_id = {row["candidate_id"]: row for row in baseline_rows}
    if args.slots:
        selected_slots = set(args.slots)
        reviewed_rows = [
            row for row in reviewed_rows
            if row["slot_ordinal"] in selected_slots
        ]
        found_slots = {row["slot_ordinal"] for row in reviewed_rows}
        if found_slots != selected_slots:
            raise RuntimeError(
                f"unknown slots: {sorted(selected_slots - found_slots)}"
            )
    missing_baselines = [
        row["candidate_id"]
        for row in reviewed_rows
        if row["candidate_id"] not in baseline_by_id
    ]
    if missing_baselines:
        raise RuntimeError(
            f"missing baseline cases: {missing_baselines}"
        )

    rag = SimpleDomainRAG(root=root, device=args.device, rerank_depth=20)
    rag._initialize()
    assert rag._artifacts is not None
    chunks = rag._artifacts.chunks_by_id
    documents = rag._artifacts.documents_by_id
    entity_index = build_official_entity_index(
        list(documents.values()),
        list(chunks.values()),
    )

    started = time.perf_counter()
    output_rows = []
    for index, reviewed in enumerate(reviewed_rows, 1):
        baseline = baseline_by_id[reviewed["candidate_id"]]
        baseline_candidates = list(baseline["result"]["candidates"])
        baseline_ids = [row["chunk_id"] for row in baseline_candidates]
        plan = extract_subject_anchored_queries(
            reviewed["question_text"],
            entity_index,
        )
        anchored_groups = []
        if plan is not None:
            planner_queries = build_planner_relation_queries(
                plan["subject"],
                reviewed["requirements"],
            )
            queries_used = (
                planner_queries
                if args.query_source == "planner-relation"
                else plan["queries"]
            )
            if len(queries_used) != len(plan["queries"]):
                raise RuntimeError("planner and extracted requirement counts differ")
            if args.query_source == "surface-planner-fusion":
                queries_used = [
                    f"{surface} || {planner}"
                    for surface, planner in zip(
                        plan["queries"],
                        planner_queries,
                        strict=True,
                    )
                ]
                query_pairs = zip(
                    plan["queries"],
                    planner_queries,
                    strict=True,
                )
                for surface_query, planner_query in query_pairs:
                    variants = []
                    for query in dict.fromkeys(
                        (surface_query, planner_query)
                    ):
                        _, hits = rag._retrieve_and_rerank(query)
                        variants.append(
                            subject_supported_hits(
                                plan["subject"],
                                hits,
                                chunks_by_id=chunks,
                                documents_by_id=documents,
                            )
                        )
                    anchored_groups.append(reciprocal_rank_fuse(variants))
            else:
                for query in queries_used:
                    _, hits = rag._retrieve_and_rerank(query)
                    anchored_groups.append(
                        subject_supported_hits(
                        plan["subject"],
                        hits,
                        chunks_by_id=chunks,
                        documents_by_id=documents,
                    )
                )
            arm_candidates = merge_subject_anchored_candidates(
                baseline_candidates,
                anchored_groups,
                subject=plan["subject"],
                chunks_by_id=chunks,
                documents_by_id=documents,
            )
            blocked = _blocked_citations(
                baseline,
                subject=plan["subject"],
                chunks_by_id=chunks,
                documents_by_id=documents,
            )
        else:
            arm_candidates = baseline_candidates
            blocked = []
            queries_used = []
        arm_ids = [row["chunk_id"] for row in arm_candidates]
        output_rows.append(
            {
                "evaluator_version": EVALUATOR_VERSION,
                "candidate_id": reviewed["candidate_id"],
                "slot_ordinal": reviewed["slot_ordinal"],
                "question_text": reviewed["question_text"],
                "plan": plan,
                "query_source": args.query_source,
                "queries_used": queries_used,
                "baseline_candidate_ids": baseline_ids,
                "arm_candidate_ids": arm_ids,
                "anchored_group_candidate_ids": [
                    [row["chunk_id"] for row in group[:3]]
                    for group in anchored_groups
                ],
                "baseline_candidate_covered": _covered(
                    reviewed,
                    baseline_ids,
                ),
                "arm_candidate_covered": _covered(reviewed, arm_ids),
                "blocked_citations": blocked,
                "baseline_all_evidence_spans_hit": baseline["score"][
                    "all_evidence_spans_hit"
                ],
                "baseline_false_full": baseline["score"]["false_full"],
            }
        )
        write_jsonl(resolved(args.output), output_rows)
        print(
            json.dumps(
                {
                    "progress": f"{index}/{len(reviewed_rows)}",
                    "slot": reviewed["slot_ordinal"],
                    "applied": plan is not None,
                    "baseline_covered": output_rows[-1][
                        "baseline_candidate_covered"
                    ],
                    "arm_covered": output_rows[-1]["arm_candidate_covered"],
                    "blocked": len(blocked),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    report = {
        **summarize(output_rows),
        "query_source": args.query_source,
        "wall_clock_ms": round((time.perf_counter() - started) * 1000, 3),
        "output": resolved(args.output).relative_to(root).as_posix(),
    }
    report_path = resolved(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
