from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.freeze_product_free_rag_a5 import MODEL_TAG, verify_model
from src.v3.product_free_rag import ProductFreeRAG
from src.v3.score_product_free_rag_a5 import score_case


RUNNER_VERSION = "product-runtime-application-targeted-live-v2"
DEFAULT_FROZEN_SET = Path(
    "data/v3/evaluation/"
    "product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc"
    ".jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run explicitly selected, already-opened Product evaluation slots "
            "through the current Product Free RAG runtime."
        )
    )
    parser.add_argument("--frozen-set", type=Path, default=DEFAULT_FROZEN_SET)
    parser.add_argument("--slots", type=int, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--question-coverage-contract", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path.cwd().resolve()
    frozen_path = (root / args.frozen_set).resolve()
    output_path = (root / args.output).resolve()
    if output_path.exists():
        raise RuntimeError(f"targeted live output already exists: {output_path}")

    selected_slots = set(args.slots)
    frozen_rows = [
        row
        for row in read_jsonl(frozen_path)
        if int(row["slot_ordinal"]) in selected_slots
    ]
    found_slots = {int(row["slot_ordinal"]) for row in frozen_rows}
    if found_slots != selected_slots:
        missing = sorted(selected_slots - found_slots)
        raise RuntimeError(f"requested slots not found: {missing}")
    if any(row.get("execution_allowed") is not True for row in frozen_rows):
        raise RuntimeError("selected row is not approved for execution")
    if any(row.get("training_allowed") is not False for row in frozen_rows):
        raise RuntimeError("selected row is not training-prohibited")

    verify_model()
    rag = ProductFreeRAG(
        root=root,
        model=MODEL_TAG,
        device=args.device,
        timeout=args.timeout,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
        handoff_cuda_to_generation=True,
    )
    records = []
    for frozen in sorted(frozen_rows, key=lambda row: int(row["slot_ordinal"])):
        slot = int(frozen["slot_ordinal"])
        print(json.dumps({"stage": "slot_started", "slot": slot}), flush=True)
        result = rag.answer(
            str(frozen["question_text"]),
            metadata_as_of=str(frozen["as_of"]),
            use_question_coverage_contract=args.question_coverage_contract,
        )
        scored = score_case(
            frozen,
            result,
            chunks_by_id=rag._artifacts.chunks_by_id,
        )
        record = {
            "type": "case",
            "runner_version": RUNNER_VERSION,
            "evaluation_role": "targeted_adaptive_runtime_application",
            "adaptive": True,
            "blind": False,
            "official_a6_eligible": False,
            "question_coverage_contract": args.question_coverage_contract,
            **scored,
        }
        records.append(record)
        write_jsonl(output_path, records)
        print(
            json.dumps(
                {
                    "stage": "slot_finished",
                    "slot": slot,
                    "mode": record.get("actual_mode"),
                    "meaning_complete": record.get("meaning_complete"),
                    "all_exposed_citations_exact": record.get(
                        "all_exposed_citations_exact"
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
