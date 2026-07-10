import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from io_utils import read_jsonl, write_jsonl


# Hand-written diverse rows stay at 1x: they target phrasing coverage, not
# volume. Oversampling them 3x re-induces the over-refusal seesaw (v2 lesson).
DEFAULT_NO_OVERSAMPLE_TYPES = ("casual_false_train", "partial_diverse_train")


def gate_balance(
    rows: list[dict],
    oversample: int,
    no_oversample_types: set[str],
) -> list[dict]:
    out = []
    for row in rows:
        out.append(row)
        if str(row.get("answerability", "")) not in ("partial", "false"):
            continue
        if str(row.get("source_eval_type", "")) in no_oversample_types:
            continue
        for _ in range(oversample - 1):
            out.append(dict(row))
    for index, row in enumerate(out, start=1):
        copied = dict(row)
        copied["raft_id"] = f"raft_{index:04d}"
        out[index - 1] = copied
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Oversample partial/false RAFT rows (gate balancing), keeping hand-written diverse rows at 1x."
    )
    parser.add_argument("--raft", type=Path, default=Path("data/processed/domain_raft_sample_expanded.jsonl"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/domain_raft_sample_expanded_gate_balanced.jsonl")
    )
    parser.add_argument("--oversample", type=int, default=3)
    parser.add_argument("--no-oversample-types", nargs="*", default=list(DEFAULT_NO_OVERSAMPLE_TYPES))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.raft)
    balanced = gate_balance(rows, args.oversample, set(args.no_oversample_types))
    write_jsonl(args.output, balanced)
    print(
        json.dumps(
            {
                "input": str(args.raft),
                "output": str(args.output),
                "input_rows": len(rows),
                "output_rows": len(balanced),
                "answerability_counts": dict(Counter(str(r.get("answerability")) for r in balanced)),
                "kept_1x_rows": sum(
                    1
                    for r in rows
                    if str(r.get("answerability")) in ("partial", "false")
                    and str(r.get("source_eval_type", "")) in set(args.no_oversample_types)
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
