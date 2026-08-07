from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.free_simple_rag import answer_simple_rag_from_candidates
from src.v3.run_free_simple_rag_top3_generation_ab import _score_result
from src.v3.simple_domain_rag import SimpleDomainRAG


DEFAULT_SOURCE = Path(
    "outputs/v3/diagnostics/"
    "free_simple_rag_top5_top3_generation_ab_adaptive_20260731.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "free_simple_rag_temporal_label_generation_ab_adaptive_20260731.jsonl"
)
CASE_ID = "cpu_smoke_09"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixed_candidate_seed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if (
            row.get("arm") == "top5"
            and row.get("case", {}).get("case_id") == CASE_ID
        ):
            return row
    raise RuntimeError(f"missing top5 seed for {CASE_ID}")


def run_ab(
    *,
    root: Path,
    source_path: Path,
    output_path: Path,
    repeats: int,
) -> list[dict[str, Any]]:
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing output: {output_path}"
        )
    if repeats < 1:
        raise RuntimeError("repeats must be positive")
    seed = _fixed_candidate_seed(read_jsonl(source_path))
    case = seed["case"]
    seed_result = seed["result"]
    candidates = seed_result["candidates"]
    selected = [
        {"chunk_id": row["chunk_id"]}
        for row in candidates
    ]
    base = SimpleDomainRAG(
        root=root,
        device="cpu",
        retrieval_depth=20,
        rerank_depth=5,
        timeout=90.0,
    )
    base._initialize()
    assert base._artifacts is not None
    rows: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        arms = (
            (False, True) if repeat % 2 else (True, False)
        )
        for annotations in arms:
            started = time.perf_counter()
            result = answer_simple_rag_from_candidates(
                question=str(case["question"]),
                model="qwen3-8b:ctx8192",
                timeout=30.0,
                selected=selected,
                chunks_by_id=base._artifacts.chunks_by_id,
                documents_by_id=base._artifacts.documents_by_id,
                temporal_by_document=base.temporal_by_document,
                route=seed_result["route"],
                candidates=candidates,
                retrieval_ms=0.0,
                started=started,
                evidence_mode="exact_quote",
                include_temporal_role_annotations=annotations,
            )
            row = {
                "run_id": (
                    "free-simple-rag-temporal-label-generation-ab-"
                    "adaptive-20260731"
                ),
                "source_sha256": _file_sha256(source_path),
                "repeat": repeat,
                "arm": (
                    "temporal_labeled"
                    if annotations
                    else "baseline_prompt"
                ),
                "fixed_candidate_ids": [
                    item["chunk_id"] for item in candidates
                ],
                "retrieval_calls": 0,
                "case": case,
                "wall_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "score": _score_result(case, result),
                "result": result,
            }
            rows.append(row)
            write_jsonl(output_path, rows)
            print(
                f"repeat={repeat} {row['arm']} "
                f"{result.get('response_mode')} "
                f"correct={row['score']['correct_full']} "
                f"false_full={row['score']['false_full']} "
                f"{row['wall_ms'] / 1000:.2f}s",
                flush=True,
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    root = args.root.resolve()
    source_path = (
        args.source if args.source.is_absolute() else root / args.source
    )
    output_path = (
        args.output if args.output.is_absolute() else root / args.output
    )
    run_ab(
        root=root,
        source_path=source_path,
        output_path=output_path,
        repeats=args.repeats,
    )


if __name__ == "__main__":
    main()
