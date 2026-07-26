from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.diagnose_typed_evidence_ref_generalization_64_precision_fix import (
    DEFAULT_SEALED,
    DEFAULT_SOURCE,
)
from src.v3.simple_domain_rag import SimpleDomainRAG


DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "product_router_generalization_64_candidate_pools_20260726.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "product_router_generalization_64_candidate_pools_20260726.json"
)


def _requirement_is_covered(
    requirement: dict[str, Any],
    candidate_ids: list[str],
) -> bool:
    if requirement["expected_status"] == "unsupported":
        return True
    acceptable_ids = {
        unit["chunk_id"]
        for unit in requirement["acceptable_evidence_units"]
    }
    return bool(acceptable_ids & set(candidate_ids))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build adaptive product-router candidate pools for the reviewed "
            "generalization-64 set without running generation."
        )
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("diagnostic output or summary already exists")

    sealed_rows = read_jsonl(resolved(args.sealed))
    source_rows = read_jsonl(resolved(args.source))
    source_by_id = {row["candidate_id"]: row for row in source_rows}
    if len(sealed_rows) != 64:
        raise RuntimeError("expected 64 reviewed rows")
    if {row["candidate_id"] for row in sealed_rows} != set(source_by_id):
        raise RuntimeError("sealed and source candidate IDs differ")

    rag = SimpleDomainRAG(
        root=root,
        device=args.device,
        retrieval_depth=20,
        rerank_depth=5,
    )
    rag._initialize()

    output_rows = []
    covered_slots = []
    for index, sealed in enumerate(sealed_rows, 1):
        routed, hits = rag._retrieve_and_rerank(sealed["question_text"])
        candidate_ids = [row["chunk_id"] for row in hits]
        covered = all(
            _requirement_is_covered(requirement, candidate_ids)
            for requirement in sealed["requirements"]
        )
        if covered:
            covered_slots.append(sealed["slot_ordinal"])
        source = source_by_id[sealed["candidate_id"]]
        output_rows.append(
            {
                **source,
                "candidate_chunk_ids": candidate_ids,
                "requirement_candidate_chunk_ids": [
                    list(candidate_ids) for _ in sealed["requirements"]
                ],
                "retrieval": {
                    "candidate_id": sealed["candidate_id"],
                    "slot_ordinal": sealed["slot_ordinal"],
                    "product_route": routed["route"],
                    "product_candidate_ids": candidate_ids,
                    "strict_gold_covered": covered,
                },
            }
        )
        print(
            json.dumps(
                {
                    "stage": "retrieval",
                    "progress": f"{index}/{len(sealed_rows)}",
                    "covered": covered,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    write_jsonl(output_path, output_rows)
    summary = {
        "evaluation_role": (
            "adaptive_product_router_retrieval_diagnostic_not_generalization"
        ),
        "retrieval_only": True,
        "generation_calls": 0,
        "strict_candidate_covered": {
            "successes": len(covered_slots),
            "total": len(sealed_rows),
        },
        "covered_slots": covered_slots,
        "uncovered_slots": [
            row["slot_ordinal"]
            for row in sealed_rows
            if row["slot_ordinal"] not in covered_slots
        ],
        "inputs": {
            "sealed_sha256": file_sha256(resolved(args.sealed)),
            "source_sha256": file_sha256(resolved(args.source)),
        },
        "output": args.output.as_posix(),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
