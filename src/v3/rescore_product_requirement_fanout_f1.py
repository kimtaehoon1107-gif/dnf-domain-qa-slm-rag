from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.run_product_requirement_fanout_f1 import (
    RUNNER_VERSION,
    _gate_a6_7,
    _gate_a6_32,
)


DEFAULT_INPUT = Path(
    "reports/v3/product_free_rag_requirement_fanout_f1_20260806.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_requirement_fanout_f1_strict_rescore_20260806.jsonl"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strictly rescore the saved Product requirement fan-out F1"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    input_path = args.input if args.input.is_absolute() else root / args.input
    output_path = args.output if args.output.is_absolute() else root / args.output
    if output_path.exists():
        raise RuntimeError(f"strict rescore output already exists: {output_path}")

    records = []
    for row in read_jsonl(input_path):
        if row.get("type") != "case":
            continue
        slot = int(row["slot_ordinal"])
        result = row["fanout"]["result"]
        rescored = dict(row)
        rescored["core_gate_passed"] = (
            _gate_a6_7(result) if slot == 7 else _gate_a6_32(result)
        )
        rescored["strict_rescore"] = True
        records.append(rescored)
    records.sort(key=lambda row: int(row["slot_ordinal"]))
    summary = {
        "type": "summary",
        "runner_version": f"{RUNNER_VERSION}-strict-rescore-v1",
        "source": input_path.relative_to(root).as_posix(),
        "qwen_call_count": 0,
        "source_qwen_call_count": sum(
            int(row["fanout"]["result"]["generation"]["fanout_call_count"])
            for row in records
        ),
        "a6_7_gate": records[0]["core_gate_passed"],
        "a6_32_gate": records[1]["core_gate_passed"],
        "citation_gate": all(row["citation_gate_passed"] for row in records),
        "latency_gate": all(row["latency_gate_passed"] for row in records),
        "proceed_to_f2": False,
        "stop_reason": "both_core_cases_failed_strict_requirement_isolation",
        "f2_executed": False,
        "f3_executed": False,
    }
    write_jsonl(output_path, [*records, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
