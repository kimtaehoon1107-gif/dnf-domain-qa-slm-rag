from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.evaluate_grounded_llm_replay import (
    DEFAULT_BASELINE_CASES,
    DEFAULT_CHUNKS,
    DEFAULT_DOCUMENTS,
    DEFAULT_TABLE_FACTS,
    DEFAULT_TEMPORAL,
    run_fixed_requirement_replay,
    summarize_replay,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--candidate-pools", type=Path, nargs="+", required=True)
    parser.add_argument("--candidate-pool-arm", required=True)
    parser.add_argument("--baseline-cases", type=Path, default=DEFAULT_BASELINE_CASES)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--table-facts", type=Path, default=DEFAULT_TABLE_FACTS)
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--as-of", default="2026-07-22")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--split-evidence-schema", action="store_true")
    parser.add_argument("--batch-requirements", action="store_true")
    parser.add_argument("--typed-evidence-refs", action="store_true")
    parser.add_argument("--allow-partial-candidate-pools", action="store_true")
    parser.add_argument("--slots", type=int, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("output or summary already exists")

    reviewed = read_jsonl(resolved(args.reviewed))
    if args.slots:
        selected_slots = set(args.slots)
        reviewed = [
            row for row in reviewed
            if row["slot_ordinal"] in selected_slots
        ]
        found_slots = {row["slot_ordinal"] for row in reviewed}
        if found_slots != selected_slots:
            raise RuntimeError(
                f"unknown slots: {sorted(selected_slots - found_slots)}"
            )
    selected_ids = {row["candidate_id"] for row in reviewed}
    baseline = [
        row
        for row in read_jsonl(resolved(args.baseline_cases))
        if row["candidate_id"] in selected_ids
    ]
    candidate_pools = [
        row
        for path in args.candidate_pools
        for row in read_jsonl(resolved(path))
        if row["candidate_id"] in selected_ids
    ]
    if len({row["candidate_id"] for row in candidate_pools}) != len(candidate_pools):
        raise RuntimeError("duplicate candidate_id across candidate-pool files")

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    checkpoint_rows = []

    def record_result(row: dict, current: int, total: int) -> None:
        checkpoint_rows.append(row)
        write_jsonl(output_path, checkpoint_rows)
        print(f"subject requirement generation {current}/{total}", flush=True)

    rows = run_fixed_requirement_replay(
        reviewed_rows=reviewed,
        baseline_rows=baseline,
        chunks=read_jsonl(resolved(args.chunks)),
        documents=read_jsonl(resolved(args.documents)),
        temporal_rows=read_jsonl(resolved(args.temporal)),
        table_facts=read_jsonl(resolved(args.table_facts)),
        model=args.model,
        as_of=args.as_of,
        reasoning_effort="high",
        timeout_seconds=args.timeout_seconds,
        split_evidence_schema=args.split_evidence_schema,
        batch_requirements=args.batch_requirements,
        typed_evidence_refs=args.typed_evidence_refs,
        result_callback=record_result,
        candidate_pool_rows=candidate_pools,
        candidate_pool_arm=args.candidate_pool_arm,
        allow_partial_candidate_pools=args.allow_partial_candidate_pools,
    )
    summary = {
        **summarize_replay(rows),
        "model": args.model,
        "candidate_pool_arm": args.candidate_pool_arm,
        "split_evidence_schema": args.split_evidence_schema,
        "batch_requirements": args.batch_requirements,
        "typed_evidence_refs": args.typed_evidence_refs,
        "allow_partial_candidate_pools": args.allow_partial_candidate_pools,
    }
    write_jsonl(output_path, rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
