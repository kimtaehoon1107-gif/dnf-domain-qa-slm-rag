from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.simple_domain_rag import SimpleDomainRAG


DEFAULT_CASES = Path(
    "data/v3/evaluation/"
    "free_simple_rag_cpu_smoke10_adaptive_20260731.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "free_simple_rag_top3_visibility_v2_adaptive_20260731.jsonl"
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value_variants(value: str) -> tuple[str, ...]:
    variants = [value]
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        year, month, day = (int(part) for part in match.groups())
        variants.extend(
            (
                f"{year}.{month:02d}.{day:02d}",
                f"{year}년 {month}월 {day}일",
                f"{month}월 {day}일",
                f"{month}/{day}",
            )
        )
    return tuple(variants)


def _candidate_rows(
    rag: SimpleDomainRAG,
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assert rag._artifacts is not None
    rows = []
    for rank, hit in enumerate(selected, 1):
        chunk = rag._artifacts.chunks_by_id[hit["chunk_id"]]
        document = rag._artifacts.documents_by_id[
            chunk["parent_document_id"]
        ]
        rows.append(
            {
                "rank": rank,
                "chunk_id": hit["chunk_id"],
                "parent_document_id": chunk["parent_document_id"],
                "source_id": document["source_id"],
                "title": document.get("title"),
                "reranker_score": hit.get("reranker_score"),
                "display_text": chunk["display_text"],
            }
        )
    return rows


def run_visibility(
    *,
    root: Path,
    cases_path: Path,
    output_path: Path,
) -> list[dict[str, Any]]:
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing output: {output_path}"
        )
    cases = read_jsonl(cases_path)
    rag = SimpleDomainRAG(
        root=root,
        device="cpu",
        retrieval_depth=20,
        rerank_depth=5,
        timeout=90.0,
    )
    rows: list[dict[str, Any]] = []
    for case in cases:
        if str(case.get("category") or "").startswith("metadata_"):
            continue
        arm_rows: dict[str, Any] = {}
        for depth in (5, 3):
            rag.rerank_depth = depth
            started = time.perf_counter()
            routed, selected = rag._retrieve_and_rerank(
                str(case["question"])
            )
            candidates = _candidate_rows(rag, selected)
            combined = "\n".join(
                str(row["display_text"]) for row in candidates
            )
            required_hits = {
                value: any(
                    variant in combined
                    for variant in _value_variants(str(value))
                )
                for value in case.get("required_values", [])
            }
            arm_rows[f"top{depth}"] = {
                "retrieval_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "route": routed.get("route"),
                "candidates": candidates,
                "required_value_hits": required_hits,
                "all_required_values_visible": all(
                    required_hits.values()
                ),
            }
        top5_ids = [
            row["chunk_id"]
            for row in arm_rows["top5"]["candidates"]
        ]
        top3_ids = [
            row["chunk_id"]
            for row in arm_rows["top3"]["candidates"]
        ]
        rows.append(
            {
                "run_id": (
                    "free-simple-rag-top3-visibility-"
                    "adaptive-20260731"
                ),
                "cases_sha256": _file_sha256(cases_path),
                "case": case,
                "arms": arm_rows,
                "top3_candidate_ids_subset_of_top5": set(
                    top3_ids
                ).issubset(top5_ids),
                "required_visibility_regression": (
                    arm_rows["top5"]["all_required_values_visible"]
                    and not arm_rows["top3"][
                        "all_required_values_visible"
                    ]
                ),
            }
        )
        write_jsonl(output_path, rows)
        print(
            f"{case['case_id']} "
            f"top5={len(top5_ids)} top3={len(top3_ids)} "
            f"regression={rows[-1]['required_visibility_regression']}",
            flush=True,
        )
    return rows


def rescore_visibility(
    *,
    input_path: Path,
    output_path: Path,
) -> list[dict[str, Any]]:
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing output: {output_path}"
        )
    rows = read_jsonl(input_path)
    for row in rows:
        required_values = row["case"].get("required_values", [])
        for arm in ("top5", "top3"):
            combined = "\n".join(
                str(candidate["display_text"])
                for candidate in row["arms"][arm]["candidates"]
            )
            required_hits = {
                value: any(
                    variant in combined
                    for variant in _value_variants(str(value))
                )
                for value in required_values
            }
            row["arms"][arm]["required_value_hits"] = required_hits
            row["arms"][arm]["all_required_values_visible"] = all(
                required_hits.values()
            )
        row["required_visibility_regression"] = (
            row["arms"]["top5"]["all_required_values_visible"]
            and not row["arms"]["top3"][
                "all_required_values_visible"
            ]
        )
        row["rescore"] = {
            "mode": "visibility_only",
            "retrieval_calls": 0,
            "source_output": input_path.as_posix(),
        }
    write_jsonl(output_path, rows)
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
    parser.add_argument("--rescore-input", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    cases_path = (
        args.cases if args.cases.is_absolute() else root / args.cases
    )
    output_path = (
        args.output if args.output.is_absolute() else root / args.output
    )
    if args.rescore_input is not None:
        input_path = (
            args.rescore_input
            if args.rescore_input.is_absolute()
            else root / args.rescore_input
        )
        rescore_visibility(
            input_path=input_path,
            output_path=output_path,
        )
        return
    run_visibility(
        root=root,
        cases_path=cases_path,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
