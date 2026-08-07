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
from src.v3.free_minimal_claim_v2 import FreeMinimalClaimV2
from src.v3.run_free_simple_rag_top3_visibility import (
    _value_variants,
)
from src.v3.simple_domain_rag import SimpleDomainRAG


DEFAULT_CASES = Path(
    "data/v3/evaluation/"
    "free_simple_rag_cpu_smoke10_adaptive_20260731.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "free_simple_rag_top5_top3_generation_ab_"
    "adaptive_20260731.jsonl"
)
TABLE_INDEX = Path(
    "data/v3/structured/"
    "table_atomic_facts_arm1_index_manifest_"
    "888974fe242b695e8dd2dbdd0ab30c859223390a9b69e15da7d2937a6b4a23cf.json"
)
DEFAULT_CASE_IDS = (
    "cpu_smoke_01",
    "cpu_smoke_08",
    "cpu_smoke_09",
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result_text(result: dict[str, Any]) -> str:
    values = [str(result.get("rendered_answer") or "")]
    for requirement in result.get("requirements", []):
        values.extend(
            (
                str(requirement.get("answer") or ""),
                str(requirement.get("value") or ""),
            )
        )
    return "\n".join(values)


def _score_result(
    case: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    text = _result_text(result)
    required_hits = {
        value: any(
            variant in text
            for variant in _value_variants(str(value))
        )
        for value in case.get("required_values", [])
    }
    forbidden_hits = {
        value: any(
            variant in text
            for variant in _value_variants(str(value))
        )
        for value in case.get("forbidden_values", [])
    }
    response_mode = str(result.get("response_mode") or "")
    all_required = all(required_hits.values())
    any_forbidden = any(forbidden_hits.values())
    correct_full = (
        response_mode == "full_answer"
        and all_required
        and not any_forbidden
    )
    return {
        "required_hits": required_hits,
        "forbidden_hits": forbidden_hits,
        "correct_full": correct_full,
        "false_full": (
            response_mode == "full_answer"
            and (not all_required or any_forbidden)
        ),
        "timeout": (
            result.get("failure_stage")
            == "simple_rag_generation"
            and "timed out" in str(result.get("error") or "")
        ),
    }


def run_ab(
    *,
    root: Path,
    cases_path: Path,
    output_path: Path,
    case_ids: tuple[str, ...],
    repeats: int,
) -> list[dict[str, Any]]:
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing output: {output_path}"
        )
    cases_by_id = {
        row["case_id"]: row for row in read_jsonl(cases_path)
    }
    missing = [case_id for case_id in case_ids if case_id not in cases_by_id]
    if missing:
        raise RuntimeError(f"Unknown case ids: {missing}")
    base = SimpleDomainRAG(
        root=root,
        device="cpu",
        retrieval_depth=20,
        rerank_depth=5,
        timeout=90.0,
    )
    runtime = FreeMinimalClaimV2(
        root=root,
        base=base,
        timeout=90.0,
        generation_timeout=30.0,
        fallback_mode="simple_rag",
        table_index_manifest=root / TABLE_INDEX,
        enable_metadata_queries=True,
    )
    rows: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        depths = (5, 3) if repeat % 2 else (3, 5)
        for case_id in case_ids:
            case = cases_by_id[case_id]
            for depth in depths:
                base.rerank_depth = depth
                started = time.perf_counter()
                result = runtime.answer(str(case["question"]))
                rows.append(
                    {
                        "run_id": (
                            "free-simple-rag-top5-top3-generation-ab-"
                            "adaptive-20260731"
                        ),
                        "cases_sha256": _file_sha256(cases_path),
                        "repeat": repeat,
                        "arm": f"top{depth}",
                        "case": case,
                        "wall_ms": round(
                            (time.perf_counter() - started) * 1000,
                            3,
                        ),
                        "score": _score_result(case, result),
                        "result": result,
                    }
                )
                write_jsonl(output_path, rows)
                print(
                    f"repeat={repeat} {case_id} top{depth} "
                    f"{result.get('response_mode')} "
                    f"correct={rows[-1]['score']['correct_full']} "
                    f"timeout={rows[-1]['score']['timeout']} "
                    f"{rows[-1]['wall_ms'] / 1000:.2f}s",
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
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        raise RuntimeError("repeats must be positive")
    root = args.root.resolve()
    cases_path = (
        args.cases if args.cases.is_absolute() else root / args.cases
    )
    output_path = (
        args.output if args.output.is_absolute() else root / args.output
    )
    run_ab(
        root=root,
        cases_path=cases_path,
        output_path=output_path,
        case_ids=tuple(args.case_ids or DEFAULT_CASE_IDS),
        repeats=args.repeats,
    )


if __name__ == "__main__":
    main()
