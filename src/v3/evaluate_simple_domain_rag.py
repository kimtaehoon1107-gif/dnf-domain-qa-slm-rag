from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.evaluate_grounded_llm_replay import score_verified_output
from src.v3.simple_domain_rag import SimpleDomainRAG


EVALUATOR_VERSION = "simple-domain-rag-evaluator-v1"
DEFAULT_EVAL_SET = Path(
    "data/v3/evaluation/requirement_surface_query_canary_reviewed_"
    "533a4b031369cdd63872cd4f52a33d9128fbcf6cf42a344e2693b4959a76c561.jsonl"
)
DEFAULT_OUTPUT = Path("outputs/v3/simple_domain_rag_eval32_ctx8192_cases.jsonl")
DEFAULT_SUMMARY = Path("reports/v3/simple_domain_rag_eval32_ctx8192_summary.json")
TABLE_SOURCES = {"dnf_monthly_item", "dnf_seria_shop"}


def _ratio(successes: int, total: int) -> dict[str, int | float]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 6) if total else 0.0,
    }


def summarize_cases(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    covered = [row for row in rows if row["score"]["candidate_all_groups_covered"]]
    response_modes = Counter(row["result"]["response_mode"] for row in rows)
    relevant = sum(row["score"]["relevant_citation_count"] for row in rows)
    citations = sum(row["score"]["citation_count"] for row in rows)

    def segment(selected: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "cases": len(selected),
            "candidate_all_groups_covered": _ratio(
                sum(row["score"]["candidate_all_groups_covered"] for row in selected),
                len(selected),
            ),
            "all_evidence_spans_hit": _ratio(
                sum(row["score"]["all_evidence_spans_hit"] for row in selected),
                len(selected),
            ),
            "false_full": _ratio(
                sum(row["score"]["false_full"] for row in selected),
                len(selected),
            ),
        }

    return {
        "evaluator_version": EVALUATOR_VERSION,
        "case_count": total,
        "candidate_all_groups_covered": _ratio(len(covered), total),
        "all_groups_hit": _ratio(
            sum(row["score"]["all_groups_hit"] for row in rows), total
        ),
        "all_evidence_spans_hit": _ratio(
            sum(row["score"]["all_evidence_spans_hit"] for row in rows), total
        ),
        "literal_when_candidate_covered": _ratio(
            sum(row["score"]["all_evidence_spans_hit"] for row in covered),
            len(covered),
        ),
        "false_full": _ratio(
            sum(row["score"]["false_full"] for row in rows), total
        ),
        "requirement_count_match": _ratio(
            sum(row["score"]["requirement_count_match"] for row in rows), total
        ),
        "question_time_scope_match": _ratio(
            sum(row["score"]["question_time_scope_match"] for row in rows), total
        ),
        "exact_citation_slices": _ratio(
            sum(row["score"]["exact_citation_slices"] for row in rows), total
        ),
        "citation_precision": round(relevant / citations, 6) if citations else 1.0,
        "response_modes": dict(sorted(response_modes.items())),
        "generation_error_count": sum(
            bool(row["score"]["generation_error"]) for row in rows
        ),
        "input_tokens": sum(
            int(row["result"].get("generation", {}).get("usage", {}).get("input_tokens", 0))
            for row in rows
        ),
        "output_tokens": sum(
            int(row["result"].get("generation", {}).get("usage", {}).get("output_tokens", 0))
            for row in rows
        ),
        "latency_ms": round(
            sum(float(row["result"].get("latency_ms") or 0.0) for row in rows), 3
        ),
        "segments": {
            "table_sources": segment(
                [row for row in rows if row["is_table_source"]]
            ),
            "non_table_sources": segment(
                [row for row in rows if not row["is_table_source"]]
            ),
            "one_requirement": segment(
                [row for row in rows if row["gold_requirement_count"] == 1]
            ),
            "multiple_requirements": segment(
                [row for row in rows if row["gold_requirement_count"] > 1]
            ),
        },
        "candidate_miss_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if not row["score"]["candidate_all_groups_covered"]
        ),
        "literal_failure_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if not row["score"]["all_evidence_spans_hit"]
        ),
        "false_full_case_ids": sorted(
            row["candidate_id"] for row in rows if row["score"]["false_full"]
        ),
    }


def evaluate_case(
    reviewed: dict[str, Any],
    *,
    rag: SimpleDomainRAG,
) -> dict[str, Any]:
    result = rag.answer(reviewed["question_text"])
    candidate_ids = [row["chunk_id"] for row in result.get("candidates", [])]
    assert rag._artifacts is not None
    score = score_verified_output(
        reviewed,
        candidate_chunk_ids=candidate_ids,
        verified=result,
        chunks_by_id=rag._artifacts.chunks_by_id,
    )
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "candidate_id": reviewed["candidate_id"],
        "slot_ordinal": reviewed["slot_ordinal"],
        "question_text": reviewed["question_text"],
        "source_id": reviewed["source_id"],
        "is_table_source": reviewed["source_id"] in TABLE_SOURCES,
        "gold_requirement_count": len(reviewed["requirements"]),
        "gold_answer": reviewed["gold_answer"],
        "score": score,
        "result": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    root = args.root.resolve()
    eval_path = args.eval_set if args.eval_set.is_absolute() else root / args.eval_set
    output_path = args.output if args.output.is_absolute() else root / args.output
    summary_path = args.summary if args.summary.is_absolute() else root / args.summary
    reviewed_rows = read_jsonl(eval_path)
    if args.limit is not None:
        reviewed_rows = reviewed_rows[: args.limit]

    completed = read_jsonl(output_path) if output_path.exists() else []
    completed_by_id = {row["candidate_id"]: row for row in completed}
    if len(completed_by_id) != len(completed):
        raise RuntimeError("duplicate candidate_id in evaluation checkpoint")

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    rag = SimpleDomainRAG(
        root=root,
        model=args.model,
        device=args.device,
        timeout=args.timeout,
    )
    started = time.perf_counter()
    output_rows = []
    for index, reviewed in enumerate(reviewed_rows, 1):
        candidate_id = reviewed["candidate_id"]
        if candidate_id in completed_by_id:
            case = completed_by_id[candidate_id]
            status = "resumed"
        else:
            case = evaluate_case(reviewed, rag=rag)
            completed_by_id[candidate_id] = case
            status = "evaluated"
        output_rows.append(case)
        write_jsonl(output_path, output_rows)
        print(
            json.dumps(
                {
                    "progress": f"{index}/{len(reviewed_rows)}",
                    "status": status,
                    "slot_ordinal": case["slot_ordinal"],
                    "response_mode": case["result"]["response_mode"],
                    "candidate_covered": case["score"][
                        "candidate_all_groups_covered"
                    ],
                    "literal": case["score"]["all_evidence_spans_hit"],
                    "false_full": case["score"]["false_full"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = {
        **summarize_cases(output_rows),
        "model": args.model,
        "device": args.device,
        "eval_set": eval_path.relative_to(root).as_posix(),
        "output": output_path.relative_to(root).as_posix(),
        "wall_clock_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
