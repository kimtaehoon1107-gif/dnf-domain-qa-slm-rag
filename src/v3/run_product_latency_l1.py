from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.product_free_rag import ProductFreeRAG
from src.v3.score_product_free_rag_a6 import _percentile


RUNNER_VERSION = "product-latency-l1-v1"
MODEL_TAG = "qwen3-8b:ctx8192"
DEFAULT_QUESTIONS = Path(
    "data/v3/evaluation/product_pipeline_user10_v2_adaptive_20260805.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_latency_l1_user10x5_20260805.jsonl"
)
TIMEZONE = ZoneInfo("Asia/Seoul")
OUTLIER_MS = 30_000.0
LATENCY_KEYS = (
    "initialization_ms",
    "model_reload_ms",
    "question_normalize_ms",
    "query_embedding_ms",
    "lexical_dense_search_ms",
    "candidate_rerank_ms",
    "evidence_atomic_rerank_ms",
    "model_handoff_ms",
    "generation_ms",
    "verification_render_ms",
    "observability_ms",
    "unattributed_ms",
    "total_ms",
)


def _stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else None,
        "over_30s_count": sum(value > OUTLIER_MS for value in values),
    }


def select_questions(
    questions: list[dict[str, Any]], slots: list[int] | None
) -> list[dict[str, Any]]:
    if len(questions) != 10:
        raise RuntimeError("L1 source must contain exactly 10 USER10 v2 questions")
    if slots is None:
        return questions
    requested = list(dict.fromkeys(slots))
    by_slot = {int(item["slot"]): item for item in questions}
    missing = [slot for slot in requested if slot not in by_slot]
    if missing:
        raise RuntimeError(f"unknown USER10 v2 slots: {missing}")
    return [by_slot[slot] for slot in requested]


def summarize_cases(cases: list[dict[str, Any]], *, repeats: int) -> dict[str, Any]:
    successful = [row for row in cases if row.get("error") is None]
    round_stats = []
    for repeat in range(1, repeats + 1):
        rows = [row for row in successful if int(row["repeat"]) == repeat]
        round_stats.append(
            {
                "repeat": repeat,
                **_stats([float(row["wall_ms"]) for row in rows]),
                "error_count": sum(
                    row.get("error") is not None
                    for row in cases
                    if int(row["repeat"]) == repeat
                ),
            }
        )
    outliers = [row for row in successful if float(row["wall_ms"]) > OUTLIER_MS]
    outliers_by_slot = Counter(int(row["slot"]) for row in outliers)
    slot_stats = []
    for slot in sorted({int(row["slot"]) for row in cases}):
        rows = [row for row in successful if int(row["slot"]) == slot]
        values = [float(row["wall_ms"]) for row in rows]
        slot_stats.append(
            {
                "slot": slot,
                "wall_ms_by_repeat": {
                    str(row["repeat"]): row["wall_ms"] for row in rows
                },
                "min_ms": round(min(values), 3) if values else None,
                "max_ms": round(max(values), 3) if values else None,
                "range_ms": round(max(values) - min(values), 3) if values else None,
                "over_30s_count": sum(value > OUTLIER_MS for value in values),
            }
        )
    return {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "status": "complete",
        "repeat_count": repeats,
        "question_count": len({int(row["slot"]) for row in cases}),
        "case_count": len(cases),
        "successful_case_count": len(successful),
        "error_count": len(cases) - len(successful),
        "qwen_call_count": sum(bool(row.get("qwen_called")) for row in cases),
        "diagnostics_hook_enabled": False,
        "runtime_modified": False,
        "overall": _stats([float(row["wall_ms"]) for row in successful]),
        "rounds": round_stats,
        "slots": slot_stats,
        "outlier_count": len(outliers),
        "outliers_by_slot": dict(sorted(outliers_by_slot.items())),
        "outliers": [
            {
                "sequence": row["sequence"],
                "repeat": row["repeat"],
                "slot": row["slot"],
                "question": row["question"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "wall_ms": row["wall_ms"],
                "latency": row["latency"],
            }
            for row in outliers
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run USER10 v2 five times in one process without diagnostics hooks"
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--slots", type=int, nargs="+")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    if args.repeats < 1:
        raise RuntimeError("repeats must be positive")
    root = Path(__file__).resolve().parents[2]
    questions_path = args.questions if args.questions.is_absolute() else root / args.questions
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"L1 output already exists: {output}")
    questions = select_questions(read_jsonl(questions_path), args.slots)

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    runtime = ProductFreeRAG(
        root=root,
        model=MODEL_TAG,
        device=args.device,
        timeout=args.timeout,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
        handoff_cuda_to_generation=True,
    )
    cases: list[dict[str, Any]] = []
    run_started = time.perf_counter()
    sequence = 0
    for repeat in range(1, args.repeats + 1):
        for item in questions:
            sequence += 1
            started_at = datetime.now(TIMEZONE).isoformat()
            started = time.perf_counter()
            result = None
            error = None
            try:
                result = runtime.answer(str(item["question"]))
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
            finished_at = datetime.now(TIMEZONE).isoformat()
            wall_ms = round((time.perf_counter() - started) * 1000, 3)
            latency = {
                key: (result or {}).get("latency", {}).get(key)
                for key in LATENCY_KEYS
            }
            row = {
                "type": "case",
                "runner_version": RUNNER_VERSION,
                "sequence": sequence,
                "repeat": repeat,
                "slot": int(item["slot"]),
                "question": str(item["question"]),
                "started_at": started_at,
                "finished_at": finished_at,
                "wall_ms": wall_ms,
                "over_30s": wall_ms > OUTLIER_MS,
                "latency": latency,
                "qwen_called": bool((result or {}).get("generation")),
                "result": result,
                "error": error,
            }
            cases.append(row)
            write_jsonl(output, cases)
            print(
                json.dumps(
                    {
                        "repeat": repeat,
                        "slot": row["slot"],
                        "wall_seconds": round(wall_ms / 1000, 2),
                        "over_30s": row["over_30s"],
                        "qwen_called": row["qwen_called"],
                        "error": error,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    summary = summarize_cases(cases, repeats=args.repeats)
    summary["model"] = MODEL_TAG
    summary["total_elapsed_ms"] = round(
        (time.perf_counter() - run_started) * 1000, 3
    )
    summary["completed_at"] = datetime.now(TIMEZONE).isoformat()
    write_jsonl(output, [*cases, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
