from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.product_free_rag import ProductFreeRAG
from src.v3.score_typed_evidence_ref_generalization import (
    _STRICT_VALUE_TYPES,
    _approved_evidence_groups,
    _citation_exact,
    _citation_supports_unit,
    value_present,
)


EVALUATION_ROLE = (
    "adaptive_replay_of_previously_executed_untouched32_not_a5"
)
DEFAULT_SEALED_SET = Path(
    "data/v3/evaluation/"
    "simple_rag_untouched32_sealed_"
    "6b2bc67087d255af1b4cfdc9076b8dfd8d0cce2b2194e2e2210af08eb8a95198"
    ".jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_existing32_adaptive_replay_20260731.jsonl"
)
_SYSTEM_DIAGNOSTIC_STAGES = {
    "before_retrieval",
    "after_handoff",
    "after_question",
    "after_error",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _gpu_process_snapshot() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if completed.returncode != 0:
        return {
            "error": completed.stderr.strip()
            or f"nvidia-smi exited {completed.returncode}"
        }
    processes = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) != 3:
            continue
        process_name = parts[1]
        if not any(
            marker in process_name.casefold()
            for marker in ("python", "ollama", "llama")
        ):
            continue
        processes.append(
            {
                "process_id": parts[0],
                "process_name": process_name,
                "used_gpu_memory_mb": parts[2],
            }
        )
    return {"processes": processes}


def _ollama_process_snapshot() -> dict[str, Any]:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    try:
        with urlopen(f"{base_url}/api/ps", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "models": [
            {
                "name": model.get("name") or model.get("model"),
                "size": model.get("size"),
                "size_vram": model.get("size_vram"),
                "context_length": model.get("context_length"),
                "expires_at": model.get("expires_at"),
            }
            for model in payload.get("models") or []
        ]
    }


def _cuda_diagnostic_hook(
    trace: list[dict[str, Any]],
    *,
    slot_ordinal: int,
    persistent_trace: list[dict[str, Any]],
    trace_path: Path,
):
    def record(snapshot: dict[str, Any]) -> None:
        row = dict(snapshot)
        row["slot_ordinal"] = slot_ordinal
        if row.get("stage") in _SYSTEM_DIAGNOSTIC_STAGES:
            row["gpu_processes"] = _gpu_process_snapshot()
            row["ollama"] = _ollama_process_snapshot()
        trace.append(row)
        persistent_trace.append(row)
        write_jsonl(trace_path, persistent_trace)

    return record


def _citations(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        citation
        for claim in result.get("claims") or []
        for citation in claim.get("citations") or []
    ]


def _requirement_score(
    requirement: dict[str, Any],
    *,
    rendered_answer: str,
    citations: list[dict[str, Any]],
    as_of: str,
) -> dict[str, Any]:
    expected_supported = requirement["expected_status"] == "supported"
    values = requirement.get("required_values") or []
    normalized_value_complete = bool(
        expected_supported
        and values
        and all(
            value_present(
                value,
                requirement["value_type"],
                rendered_answer,
                as_of=as_of,
                relation=requirement.get("relation"),
            )
            for value in values
        )
    )
    evidence_groups = _approved_evidence_groups(
        requirement,
        as_of=as_of,
    )
    evidence_value_hits = (
        [
            any(
                _citation_supports_unit(
                    citation,
                    unit,
                    expected=value,
                    value_type=requirement["value_type"],
                    as_of=as_of,
                )
                for citation in citations
                for unit in matching_units
            )
            for value, matching_units in zip(
                values,
                evidence_groups,
                strict=True,
            )
        ]
        if values
        else []
    )
    evidence_complete = bool(
        expected_supported
        and values
        and all(evidence_value_hits)
    )
    value_complete = normalized_value_complete or bool(
        expected_supported
        and requirement["value_type"] not in _STRICT_VALUE_TYPES
        and evidence_complete
    )
    return {
        "requirement_id": requirement["requirement_id"],
        "expected_status": requirement["expected_status"],
        "value_type": requirement["value_type"],
        "normalized_value_complete": normalized_value_complete,
        "evidence_complete": evidence_complete,
        "value_complete": value_complete,
    }


def score_case(
    sealed: dict[str, Any],
    result: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rendered_answer = str(result.get("rendered_answer") or "")
    citations = _citations(result)
    requirement_scores = [
        _requirement_score(
            requirement,
            rendered_answer=rendered_answer,
            citations=citations,
            as_of=sealed["as_of"],
        )
        for requirement in sealed["requirements"]
    ]
    supported_scores = [
        row
        for row in requirement_scores
        if row["expected_status"] == "supported"
    ]
    expected_mode = {
        "full_answer": "answer",
        "partial_answer": "partial",
    }[sealed["expected_response_mode"]]
    actual_mode = result.get("mode")
    all_supported_complete = all(
        row["value_complete"] for row in supported_scores
    )
    candidate_ids = {
        str(row.get("chunk_id"))
        for row in result.get("candidates") or []
    }
    retrieval_requirement_hits = [
        bool(
            candidate_ids
            & {
                str(unit["chunk_id"])
                for unit in requirement.get("acceptable_evidence_units") or []
            }
        )
        for requirement in sealed["requirements"]
        if requirement["expected_status"] == "supported"
    ]
    citations_exact = all(
        _citation_exact(citation, chunks_by_id)
        for citation in citations
    )
    expected_partial = sealed["expected_response_mode"] == "partial_answer"
    return {
        "slot_ordinal": sealed["slot_ordinal"],
        "candidate_id": sealed["candidate_id"],
        "question": sealed["question_text"],
        "expected_mode": expected_mode,
        "actual_mode": actual_mode,
        "mode_match": actual_mode == expected_mode,
        "all_supported_complete": all_supported_complete,
        "meaning_complete": (
            actual_mode == expected_mode and all_supported_complete
        ),
        "false_full_candidate": bool(
            expected_partial and actual_mode == "answer"
        ),
        "retrieval_all_supported_visible": all(
            retrieval_requirement_hits
        ),
        "retrieval_requirement_hits": retrieval_requirement_hits,
        "all_exposed_citations_exact": citations_exact,
        "runtime_citations_verified": bool(
            result.get("verification", {}).get(
                "all_exposed_citations_verified"
            )
        ),
        "requirement_scores": requirement_scores,
        "result": result,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            int(fraction * len(ordered) + 0.999999) - 1,
        ),
    )
    return round(ordered[index], 3)


def summarize(
    rows: list[dict[str, Any]],
    *,
    sealed_count: int,
    sealed_path: Path,
) -> dict[str, Any]:
    latencies = [
        float(row["result"].get("latency", {}).get("total_ms") or 0)
        for row in rows
    ]
    generation_rows = [
        row["result"]["generation"]
        for row in rows
        if row["result"].get("generation") is not None
    ]
    return {
        "type": "summary",
        "evaluation_role": EVALUATION_ROLE,
        "a5_eligible": False,
        "sealed_set": {
            "path": sealed_path.as_posix(),
            "sha256": _sha256(sealed_path),
        },
        "query_inputs": "question_only_no_gold_retrieval_hints",
        "case_count": sealed_count,
        "completed": len(rows),
        "meaning_complete": sum(row["meaning_complete"] for row in rows),
        "semantic_accuracy": (
            sum(row["meaning_complete"] for row in rows) / sealed_count
            if sealed_count
            else 0.0
        ),
        "all_supported_complete": sum(
            row["all_supported_complete"] for row in rows
        ),
        "false_full_candidate_slots": [
            row["slot_ordinal"]
            for row in rows
            if row["false_full_candidate"]
        ],
        "retrieval_all_supported_visible": sum(
            row["retrieval_all_supported_visible"] for row in rows
        ),
        "citation_coordinate_rate": (
            sum(row["all_exposed_citations_exact"] for row in rows)
            / len(rows)
            if rows
            else 0.0
        ),
        "runtime_citation_verification_rate": (
            sum(row["runtime_citations_verified"] for row in rows)
            / len(rows)
            if rows
            else 0.0
        ),
        "generation_calls": len(generation_rows),
        "p50_ms": (
            round(statistics.median(latencies), 3)
            if latencies
            else None
        ),
        "p95_ms": _percentile(latencies, 0.95),
        "input_tokens": sum(
            int(row.get("usage", {}).get("input_tokens") or 0)
            for row in generation_rows
        ),
        "output_tokens": sum(
            int(row.get("usage", {}).get("output_tokens") or 0)
            for row in generation_rows
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the already-consumed 32-case set with Product Free RAG. "
            "This is adaptive diagnosis, not an A5 untouched evaluation."
        )
    )
    parser.add_argument("--sealed-set", type=Path, default=DEFAULT_SEALED_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--identity-shortlist", action="store_true")
    parser.add_argument("--compact-evidence-pack", action="store_true")
    parser.add_argument("--atomic-evidence-reranker", action="store_true")
    parser.add_argument("--cuda-model-handoff", action="store_true")
    parser.add_argument("--question-coverage-contract", action="store_true")
    parser.add_argument("--cuda-memory-diagnostics", action="store_true")
    parser.add_argument("--slots", type=int, nargs="+")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path.cwd()
    sealed_path = (root / args.sealed_set).resolve()
    output_path = (root / args.output).resolve()
    sealed_rows = read_jsonl(sealed_path)
    if len(sealed_rows) != 32:
        raise RuntimeError(f"expected 32 sealed rows, got {len(sealed_rows)}")
    if args.slots:
        requested_slots = set(args.slots)
        sealed_rows = [
            row
            for row in sealed_rows
            if int(row["slot_ordinal"]) in requested_slots
        ]
        observed_slots = {
            int(row["slot_ordinal"]) for row in sealed_rows
        }
        if observed_slots != requested_slots:
            raise RuntimeError(
                f"unknown requested slots: {sorted(requested_slots - observed_slots)}"
            )

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
    trace_path = output_path.with_name(
        f"{output_path.stem}_memory_trace.jsonl"
    )
    persistent_trace = (
        read_jsonl(trace_path)
        if args.cuda_memory_diagnostics
        and args.resume
        and trace_path.exists()
        else []
    )
    rag = ProductFreeRAG(
        root=root,
        model=args.model,
        device=args.device,
        timeout=args.timeout,
        use_identity_shortlist=args.identity_shortlist,
        use_compact_evidence_pack=args.compact_evidence_pack,
        use_atomic_evidence_reranker=args.atomic_evidence_reranker,
        handoff_cuda_to_generation=args.cuda_model_handoff,
    )
    errors = []
    for sealed in sealed_rows:
        if sealed["candidate_id"] in completed_ids:
            continue
        memory_trace: list[dict[str, Any]] = []
        diagnostic_hook = (
            _cuda_diagnostic_hook(
                memory_trace,
                slot_ordinal=int(sealed["slot_ordinal"]),
                persistent_trace=persistent_trace,
                trace_path=trace_path,
            )
            if args.cuda_memory_diagnostics
            else None
        )
        try:
            result = rag.answer(
                sealed["question_text"],
                diagnostics_hook=diagnostic_hook,
                use_question_coverage_contract=(
                    args.question_coverage_contract
                ),
            )
            row = {
                "type": "case",
                "evaluation_role": EVALUATION_ROLE,
                **score_case(
                    sealed,
                    result,
                    chunks_by_id=rag._artifacts.chunks_by_id,
                ),
            }
            if args.cuda_memory_diagnostics:
                row["cuda_memory_trace"] = memory_trace
            rows.append(row)
            write_jsonl(output_path, rows)
            print(
                json.dumps(
                    {
                        "slot": row["slot_ordinal"],
                        "mode": row["actual_mode"],
                        "complete": row["meaning_complete"],
                        "retrieval_visible": row[
                            "retrieval_all_supported_visible"
                        ],
                        "latency_ms": result.get("latency", {}).get(
                            "total_ms"
                        ),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:
            rag.record_cuda_memory_diagnostic(
                "after_error",
                diagnostic_hook,
            )
            error = {
                "slot_ordinal": sealed["slot_ordinal"],
                "candidate_id": sealed["candidate_id"],
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if args.cuda_memory_diagnostics:
                error["cuda_memory_trace"] = memory_trace
            errors.append(error)
            print(
                json.dumps({"type": "error", **error}, ensure_ascii=False),
                flush=True,
            )
    summary = summarize(
        rows,
        sealed_count=len(sealed_rows),
        sealed_path=sealed_path,
    )
    summary["errors"] = errors
    write_jsonl(output_path, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
