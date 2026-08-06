from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.free_minimal_claim_v2 import FreeMinimalClaimV2
from src.v3.free_simple_rag import (
    answer_simple_rag_from_candidates,
    render_simple_natural_answer,
)
from src.v3.retrieve_v3 import load_runtime_artifacts
from src.v3.score_typed_evidence_ref_generalization import (
    score_generalization_cases,
)
from src.v3.simple_domain_rag import GLOBAL_TEMPORAL_OVERLAY


RUNNER_VERSION = "free-simple-rag-evidence-ref-untouched32-ab-v1"
DEFAULT_SEALED = Path(
    "data/v3/evaluation/"
    "simple_rag_untouched32_sealed_"
    "6b2bc67087d255af1b4cfdc9076b8dfd8d0cce2b2194e2e2210af08eb8a95198.jsonl"
)
DEFAULT_CANDIDATES = Path(
    "outputs/v3/untouched/"
    "simple_rag_original_vs_b134_untouched32_one_shot_20260728.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "free_simple_rag_evidence_ref_ab_untouched32_20260729.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "free_simple_rag_evidence_ref_ab_untouched32_20260729.json"
)
EVIDENCE_MODES = ("exact_quote", "server_ref")
AVAILABLE_EVIDENCE_MODES = (*EVIDENCE_MODES, "atomic_ref")


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round((len(ordered) - 1) * fraction))),
    )
    return round(ordered[index], 3)


def _candidate_metadata(
    candidate_ids: list[str],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for index, chunk_id in enumerate(candidate_ids, 1):
        chunk = chunks_by_id[chunk_id]
        document = documents_by_id[chunk["parent_document_id"]]
        rows.append(
            {
                "candidate_ref": str(index),
                "chunk_id": chunk_id,
                "title": document.get("title"),
                "source_id": document.get("source_id"),
            }
        )
    return rows


def build_question_level_verified_output(
    sealed: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Adapt one free-form answer for value/evidence scoring only.

    The same combined answer and citations are checked against each supported
    gold requirement. Unsupported requirements remain excluded from automatic
    scoring and require human review for overclaim.
    """

    supported_rows = [
        row
        for row in result.get("requirements", [])
        if row.get("status") == "supported_exact"
    ]
    answer = "\n".join(
        str(row.get("answer") or "").strip()
        for row in supported_rows
        if str(row.get("answer") or "").strip()
    )
    citations = []
    seen = set()
    for row in supported_rows:
        for citation in row.get("citations", []):
            key = (
                citation.get("chunk_id"),
                citation.get("start_char"),
                citation.get("end_char"),
            )
            if key in seen:
                continue
            seen.add(key)
            citations.append(dict(citation))

    decisions = []
    audits = []
    exposed = bool(answer and citations)
    for requirement in sealed["requirements"]:
        expected_supported = requirement["expected_status"] == "supported"
        status = (
            "supported_exact"
            if expected_supported and exposed
            else "unsupported"
        )
        decisions.append(
            {
                "requirement_id": requirement["requirement_id"],
                "question_part": requirement["relation"],
                "status": status,
                "answer": answer if status == "supported_exact" else "",
                "citations": citations if status == "supported_exact" else [],
            }
        )
        audits.append(
            {
                "requirement_id": requirement["requirement_id"],
                "model_status": result.get("model_response_mode"),
                "exposed_status": status,
                "failure_reasons": [],
            }
        )
    return {
        "question_time_scope": result.get("question_time_scope"),
        "model_response_mode": result.get("model_response_mode"),
        "response_mode": result.get("response_mode", "abstain"),
        "requirements": decisions,
        "rendered_answer": result.get("rendered_answer", ""),
        "verification": {
            "requirements": audits,
            "generation_error": result.get("generation_error"),
            "question_level_adapter": True,
            "unsupported_overclaim_requires_human_review": True,
        },
    }


def _run_arm(
    *,
    mode: str,
    sealed: dict[str, Any],
    source: dict[str, Any],
    model: str,
    timeout: float,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    guard_runtime: FreeMinimalClaimV2,
    exact_quote_generation_options: dict[str, Any] | None = None,
    exact_quote_backend: str = "native",
    apply_operation_guard: bool = True,
) -> dict[str, Any]:
    candidate_ids = list(source["candidate_chunk_ids"])
    selected = [{"chunk_id": chunk_id} for chunk_id in candidate_ids]
    candidates = _candidate_metadata(
        candidate_ids,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
    )
    started = time.perf_counter()
    try:
        result = answer_simple_rag_from_candidates(
            question=sealed["question_text"],
            model=model,
            timeout=timeout,
            selected=selected,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
            route=source.get("route") or {},
            candidates=candidates,
            retrieval_ms=0.0,
            started=started,
            evidence_mode=mode,
            exact_quote_generation_options=exact_quote_generation_options,
            exact_quote_backend=exact_quote_backend,
        )
        if apply_operation_guard:
            result = guard_runtime._apply_operation_guard(
                result,
                question=sealed["question_text"],
            )
        result["rendered_answer"] = render_simple_natural_answer(
            result["requirements"]
        )
        return {
            "result": result,
            "generation_error": None,
            "wall_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        }
    except Exception as exc:
        return {
            "result": {
                "question_time_scope": None,
                "model_response_mode": None,
                "response_mode": "abstain",
                "requirements": [],
                "rendered_answer": "",
                "verification": {
                    "requirements": [],
                    "generation_error": f"{type(exc).__name__}: {exc}",
                },
            },
            "generation_error": f"{type(exc).__name__}: {exc}",
            "wall_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        }


def _arm_metrics(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    arm_rows = [row["arms"][mode] for row in rows]
    generation_latencies = [
        float(
            arm["result"].get("generation", {}).get("latency_ms") or 0.0
        )
        for arm in arm_rows
        if arm["generation_error"] is None
    ]
    wall_latencies = [
        float(arm.get("wall_ms") or 0.0)
        for arm in arm_rows
        if arm["generation_error"] is None
    ]
    usages = [
        arm["result"].get("generation", {}).get("usage") or {}
        for arm in arm_rows
        if arm["generation_error"] is None
    ]
    response_modes = Counter(
        arm["result"].get("response_mode", "abstain")
        for arm in arm_rows
    )
    return {
        "generation_errors": sum(
            arm["generation_error"] is not None for arm in arm_rows
        ),
        "response_modes": dict(sorted(response_modes.items())),
        "generation_latency_ms": {
            "mean": round(statistics.mean(generation_latencies), 3)
            if generation_latencies
            else 0.0,
            "p50": round(statistics.median(generation_latencies), 3)
            if generation_latencies
            else 0.0,
            "p95": _percentile(generation_latencies, 0.95),
        },
        "wall_latency_ms": {
            "mean": round(statistics.mean(wall_latencies), 3)
            if wall_latencies
            else 0.0,
            "p50": round(statistics.median(wall_latencies), 3)
            if wall_latencies
            else 0.0,
            "p95": _percentile(wall_latencies, 0.95),
        },
        "tokens": {
            "input_total": sum(
                int(usage.get("input_tokens") or 0) for usage in usages
            ),
            "output_total": sum(
                int(usage.get("output_tokens") or 0) for usage in usages
            ),
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    sealed_path = resolve(args.sealed)
    candidate_path = resolve(args.candidates)
    output_path = resolve(args.output)
    summary_path = resolve(args.summary)
    sealed_rows = read_jsonl(sealed_path)
    candidate_rows = read_jsonl(candidate_path)
    if len(sealed_rows) != 32 or len(candidate_rows) != 32:
        raise RuntimeError("evaluation needs exactly 32 sealed and candidate rows")
    candidates_by_id = {
        row["candidate_id"]: row for row in candidate_rows
    }
    if len(candidates_by_id) != 32:
        raise RuntimeError("candidate source contains duplicate IDs")
    if {
        row["candidate_id"] for row in sealed_rows
    } != set(candidates_by_id):
        raise RuntimeError("sealed and candidate IDs differ")
    evaluation_rows = sealed_rows
    if args.slots:
        requested_slots = set(args.slots)
        evaluation_rows = [
            row
            for row in sealed_rows
            if int(row["slot_ordinal"]) in requested_slots
        ]
        found_slots = {
            int(row["slot_ordinal"]) for row in evaluation_rows
        }
        if found_slots != requested_slots:
            raise RuntimeError(
                f"unknown slots: {sorted(requested_slots - found_slots)}"
            )

    completed = read_jsonl(output_path) if output_path.exists() else []
    completed_by_id = {row["candidate_id"]: row for row in completed}
    if completed and not args.resume:
        raise RuntimeError("output exists; use --resume")

    artifacts = load_runtime_artifacts(root)
    temporal_by_document = {
        row["document_id"]: row
        for row in read_jsonl(root / GLOBAL_TEMPORAL_OVERLAY)
    }
    base = SimpleNamespace(_artifacts=artifacts)
    guard_runtime = object.__new__(FreeMinimalClaimV2)
    guard_runtime.base = base

    started = time.perf_counter()
    rows = []
    modes = tuple(args.modes)
    exact_quote_generation_options = {
        key: value
        for key, value in {
            "num_ctx": args.exact_num_ctx,
            "num_predict": args.exact_num_predict,
            "seed": args.exact_seed,
            "think": args.exact_think,
        }.items()
        if value is not None
    }
    total = len(evaluation_rows)
    for current, sealed in enumerate(evaluation_rows, 1):
        candidate_id = sealed["candidate_id"]
        source = candidates_by_id[candidate_id]
        row = completed_by_id.get(
            candidate_id,
            {
                "runner_version": RUNNER_VERSION,
                "evaluation_role": (
                    "adaptive_untouched32_paired_ab_not_generalization"
                ),
                "candidate_id": candidate_id,
                "slot_ordinal": sealed["slot_ordinal"],
                "question_text": sealed["question_text"],
                "candidate_chunk_ids": source["candidate_chunk_ids"],
                "route": source.get("route") or {},
                "arms": {},
            },
        )
        for mode in modes:
            if mode in row["arms"]:
                continue
            row["arms"][mode] = _run_arm(
                mode=mode,
                sealed=sealed,
                source=source,
                model=args.model,
                timeout=args.timeout_seconds,
                chunks_by_id=artifacts.chunks_by_id,
                documents_by_id=artifacts.documents_by_id,
                temporal_by_document=temporal_by_document,
                guard_runtime=guard_runtime,
                exact_quote_generation_options=(
                    exact_quote_generation_options or None
                ),
                exact_quote_backend=args.exact_backend,
                apply_operation_guard=not args.skip_operation_guard,
            )
            completed_by_id[candidate_id] = row
            ordered = [
                completed_by_id[item["candidate_id"]]
                for item in evaluation_rows
                if item["candidate_id"] in completed_by_id
            ]
            write_jsonl(output_path, ordered)
            print(
                json.dumps(
                    {
                        "progress": f"{current}/{total}",
                        "slot": sealed["slot_ordinal"],
                        "mode": mode,
                        "response_mode": row["arms"][mode]["result"].get(
                            "response_mode"
                        ),
                        "error": row["arms"][mode]["generation_error"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        rows.append(row)

    automatic = {}
    for mode in modes:
        adapted_rows = []
        for sealed, row in zip(evaluation_rows, rows, strict=True):
            arm = row["arms"][mode]
            adapted_rows.append(
                {
                    "candidate_id": sealed["candidate_id"],
                    "verified_output": build_question_level_verified_output(
                        sealed,
                        {
                            **arm["result"],
                            "generation_error": arm["generation_error"],
                        },
                    ),
                    "requirement_candidate_chunk_ids": [
                        list(row["candidate_chunk_ids"])
                        for _ in sealed["requirements"]
                    ],
                }
            )
        scored, score_summary = score_generalization_cases(
            evaluation_rows,
            adapted_rows,
            chunks_by_id=artifacts.chunks_by_id,
        )
        automatic[mode] = {
            "summary": score_summary,
            "slots": [
                {
                    "slot_ordinal": sealed["slot_ordinal"],
                    "holdout_score": scored_row["holdout_score"],
                }
                for sealed, scored_row in zip(
                    evaluation_rows,
                    scored,
                    strict=True,
                )
            ],
        }

    summary = {
        "runner_version": RUNNER_VERSION,
        "evaluation_role": (
            "adaptive_untouched32_paired_ab_not_generalization"
        ),
        "model": args.model,
        "sealed": {
            "path": args.sealed.as_posix(),
            "sha256": file_sha256(sealed_path),
        },
        "candidate_source": {
            "path": args.candidates.as_posix(),
            "sha256": file_sha256(candidate_path),
            "retrieval_rerun": False,
        },
        "selected_slots": [
            int(row["slot_ordinal"]) for row in evaluation_rows
        ],
        "exact_quote_generation_options": (
            exact_quote_generation_options or None
        ),
        "exact_quote_backend": args.exact_backend,
        "operation_guard_applied": not args.skip_operation_guard,
        "arms": {
            mode: {
                **_arm_metrics(rows, mode),
                "automatic_scoring": automatic[mode],
            }
            for mode in modes
        },
        "human_review": {
            "performed": False,
            "warning": (
                "Question-level answers need human review for semantic "
                "completeness, ambiguity, extra claims, and unsupported "
                "overclaim."
            ),
        },
        "wall_clock_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
        "output": args.output.as_posix(),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run exact-quote versus server-ref on the already-open untouched32 "
            "candidate pools."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=AVAILABLE_EVIDENCE_MODES,
        default=list(EVIDENCE_MODES),
    )
    parser.add_argument("--slots", nargs="+", type=int)
    parser.add_argument("--exact-num-ctx", type=int)
    parser.add_argument("--exact-num-predict", type=int)
    parser.add_argument("--exact-seed", type=int)
    parser.add_argument(
        "--exact-backend",
        choices=("native", "openai_compatible"),
        default="native",
    )
    parser.add_argument(
        "--exact-think",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--skip-operation-guard", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(run(parse_args()), ensure_ascii=False, indent=2),
        flush=True,
    )


if __name__ == "__main__":
    main()
