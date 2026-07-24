from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl


DEFAULT_REVIEWED = Path(
    "data/v3/evaluation/requirement_surface_query_canary_reviewed_"
    "533a4b031369cdd63872cd4f52a33d9128fbcf6cf42a344e2693b4959a76c561.jsonl"
)
DEFAULT_RETRIEVAL_AB = Path(
    "outputs/v3/simple_subject_anchored_retrieval_ab_cases.jsonl"
)


def build_requirement_pools(
    reviewed_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    *,
    top_k: int,
    use_full_arm: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if top_k < 1:
        raise RuntimeError("top_k must be positive")
    reviewed_by_id = {row["candidate_id"]: row for row in reviewed_rows}
    arm_name = "subject_arm_full" if use_full_arm else f"subject_top_{top_k}"
    selected_reviewed = []
    pools = []
    for retrieval in retrieval_rows:
        plan = retrieval.get("plan")
        if plan is None and not use_full_arm:
            continue
        candidate_id = retrieval["candidate_id"]
        reviewed = reviewed_by_id.get(candidate_id)
        if reviewed is None:
            raise RuntimeError(f"missing reviewed case: {candidate_id}")
        requirements = reviewed["requirements"]
        if use_full_arm:
            full_arm_ids = list(
                dict.fromkeys(retrieval["arm_candidate_ids"])
            )
            if not full_arm_ids:
                raise RuntimeError(
                    f"empty full arm for slot {reviewed['slot_ordinal']}"
                )
            groups = [full_arm_ids for _ in requirements]
            queries = [
                requirement.get("surface") or requirement.get("relation")
                for requirement in requirements
            ]
        else:
            groups = retrieval["anchored_group_candidate_ids"]
            queries = retrieval.get("queries_used") or plan["queries"]
        if len(groups) != len(requirements):
            raise RuntimeError(
                f"requirement/group count differs for slot "
                f"{reviewed['slot_ordinal']}"
            )
        requirement_pools = []
        for requirement, query, group in zip(
            requirements,
            queries,
            groups,
            strict=True,
        ):
            candidate_ids = list(dict.fromkeys(group))
            if not use_full_arm:
                candidate_ids = candidate_ids[:top_k]
            if not candidate_ids:
                raise RuntimeError(
                    f"empty subject candidate group for slot "
                    f"{reviewed['slot_ordinal']}"
                )
            requirement_pools.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "query": query,
                    arm_name: {"candidate_chunk_ids": candidate_ids},
                }
            )
        selected_reviewed.append(reviewed)
        pools.append(
            {
                "candidate_id": candidate_id,
                "slot_ordinal": reviewed["slot_ordinal"],
                "question_text": reviewed["question_text"],
                "subject": (
                    plan["subject"]
                    if plan is not None
                    else requirements[0].get("subject")
                ),
                "requirement_candidate_pools": requirement_pools,
            }
        )
    return selected_reviewed, pools, arm_name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--retrieval-ab", type=Path, default=DEFAULT_RETRIEVAL_AB)
    parser.add_argument("--slots", type=int, nargs="+")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--use-full-arm", action="store_true")
    parser.add_argument("--output-reviewed", type=Path, required=True)
    parser.add_argument("--output-pools", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    reviewed_rows = read_jsonl(resolved(args.reviewed))
    retrieval_rows = read_jsonl(resolved(args.retrieval_ab))
    if args.slots:
        selected_slots = set(args.slots)
        retrieval_rows = [
            row
            for row in retrieval_rows
            if row["slot_ordinal"] in selected_slots
        ]
        found = {row["slot_ordinal"] for row in retrieval_rows}
        if found != selected_slots:
            raise RuntimeError(
                f"unknown slots: {sorted(selected_slots - found)}"
            )
    selected_reviewed, pools, arm_name = build_requirement_pools(
        reviewed_rows,
        retrieval_rows,
        top_k=args.top_k,
        use_full_arm=args.use_full_arm,
    )
    write_jsonl(resolved(args.output_reviewed), selected_reviewed)
    write_jsonl(resolved(args.output_pools), pools)
    print(
        json.dumps(
            {
                "case_count": len(pools),
                "requirement_count": sum(
                    len(row["requirement_candidate_pools"]) for row in pools
                ),
                "candidate_pool_arm": arm_name,
                "slots": [row["slot_ordinal"] for row in pools],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
