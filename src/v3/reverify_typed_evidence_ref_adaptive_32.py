from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_grounded_llm_replay import (
    DEFAULT_BASELINE_CASES,
    DEFAULT_CHUNKS,
    DEFAULT_DOCUMENTS,
    DEFAULT_TABLE_FACTS,
    DEFAULT_TEMPORAL,
    run_fixed_requirement_replay,
    summarize_replay,
)


DEFAULT_REVIEWED = Path("outputs/v3/subject_arm_full_reviewed_32.jsonl")
DEFAULT_POOLS = Path("outputs/v3/subject_arm_full_requirement_pools_32.jsonl")
DEFAULT_SOURCE = Path("outputs/v3/typed_evidence_ref_subject_arm_32.jsonl")
DEFAULT_OUTPUT = Path(
    "outputs/v3/typed_evidence_ref_subject_arm_32_precision_fix_reverified.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/typed_evidence_ref_subject_arm_32_precision_fix_reverified_summary.json"
)


def _recorded_generator(calls: list[dict[str, Any]]):
    call_index = 0

    def generate(**_: Any) -> dict[str, Any]:
        nonlocal call_index
        if call_index >= len(calls):
            raise RuntimeError("recorded generation calls exhausted")
        call = copy.deepcopy(calls[call_index])
        call_index += 1
        if "output" not in call:
            raise RuntimeError(
                f"recorded generation call has no output: {call.get('error')}"
            )
        return call

    def assert_consumed() -> None:
        if call_index != len(calls):
            raise RuntimeError(
                f"unused recorded generation calls: {len(calls) - call_index}"
            )

    return generate, assert_consumed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--candidate-pools", type=Path, default=DEFAULT_POOLS)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline-cases", type=Path, default=DEFAULT_BASELINE_CASES)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--table-facts", type=Path, default=DEFAULT_TABLE_FACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("output or summary already exists")

    reviewed = read_jsonl(resolved(args.reviewed))
    source_rows = read_jsonl(resolved(args.source))
    source_by_id = {row["candidate_id"]: row for row in source_rows}
    if {row["candidate_id"] for row in reviewed} != set(source_by_id):
        raise RuntimeError("reviewed and recorded generation candidate IDs differ")
    recorded_calls = [
        call
        for reviewed_row in reviewed
        for call in source_by_id[reviewed_row["candidate_id"]]["model_call"]["calls"]
    ]
    generator, assert_consumed = _recorded_generator(recorded_calls)
    selected_ids = {row["candidate_id"] for row in reviewed}
    baseline = [
        row
        for row in read_jsonl(resolved(args.baseline_cases))
        if row["candidate_id"] in selected_ids
    ]
    pools = [
        row
        for row in read_jsonl(resolved(args.candidate_pools))
        if row["candidate_id"] in selected_ids
    ]

    rows = run_fixed_requirement_replay(
        reviewed_rows=reviewed,
        baseline_rows=baseline,
        chunks=read_jsonl(resolved(args.chunks)),
        documents=read_jsonl(resolved(args.documents)),
        temporal_rows=read_jsonl(resolved(args.temporal)),
        table_facts=read_jsonl(resolved(args.table_facts)),
        model="qwen3-8b:ctx8192",
        as_of="2026-07-22",
        reasoning_effort="high",
        timeout_seconds=180,
        batch_generator=generator,
        typed_batch_generator=generator,
        split_evidence_schema=True,
        batch_requirements=True,
        typed_evidence_refs=True,
        candidate_pool_rows=pools,
        candidate_pool_arm="subject_arm_full",
    )
    assert_consumed()
    summary = {
        **summarize_replay(rows),
        "evaluation_role": "adaptive_32_verifier_only_replay",
        "model": "qwen3-8b:ctx8192",
        "candidate_pool_arm": "subject_arm_full",
        "split_evidence_schema": True,
        "batch_requirements": True,
        "typed_evidence_refs": True,
        "new_model_calls": 0,
        "generation_replayed_from": args.source.as_posix(),
        "generation_source_sha256": file_sha256(resolved(args.source)),
    }
    write_jsonl(output_path, rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
