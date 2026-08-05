from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.freeze_product_free_rag_a6 import MODEL_TAG, verify_model
from src.v3.product_free_rag import ProductFreeRAG
from src.v3.run_product_free_rag_a6_adaptive_replay import (
    DEFAULT_FROZEN_SET,
    FROZEN_SHA256,
)
from src.v3.run_product_free_rag_a6_one_shot import sha256_path
from src.v3.score_product_free_rag_a6 import score_case


RUNNER_VERSION = "product-free-rag-a6-slot25-repeat3-v1"
SLOT_ORDINAL = 25
REPEAT_COUNT = 3
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_a6_slot25_repeat3_adaptive_20260806.jsonl"
)


def _record(
    frozen: dict[str, Any],
    result: dict[str, Any],
    *,
    run_index: int,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "case",
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "adaptive_variability_diagnostic_not_official",
        "adaptive_replay": True,
        "blind": False,
        "official_a6_eligible": False,
        "run_index": run_index,
        **score_case(frozen, result, chunks_by_id=chunks_by_id),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path.cwd().resolve()
    frozen_path = root / DEFAULT_FROZEN_SET
    output_path = root / DEFAULT_OUTPUT
    if output_path.exists():
        raise RuntimeError(f"repeat output already exists: {output_path}")
    if sha256_path(frozen_path) != FROZEN_SHA256:
        raise RuntimeError("opened Product A6 frozen-set SHA mismatch")
    frozen = next(
        row
        for row in read_jsonl(frozen_path)
        if int(row["slot_ordinal"]) == SLOT_ORDINAL
    )
    verify_model()
    rag = ProductFreeRAG(
        root=root,
        model=MODEL_TAG,
        device="cuda",
        timeout=120.0,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
        handoff_cuda_to_generation=True,
    )

    records: list[dict[str, Any]] = []
    for run_index in range(1, REPEAT_COUNT + 1):
        print(
            json.dumps(
                {"stage": "run_started", "run_index": run_index},
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            result = rag.answer(
                frozen["question_text"],
                metadata_as_of=frozen["as_of"],
            )
            record = _record(
                frozen,
                result,
                run_index=run_index,
                chunks_by_id=rag._artifacts.chunks_by_id,
            )
        except Exception as exc:
            record = {
                "type": "error",
                "runner_version": RUNNER_VERSION,
                "evaluation_role": (
                    "adaptive_variability_diagnostic_not_official"
                ),
                "adaptive_replay": True,
                "blind": False,
                "official_a6_eligible": False,
                "slot_ordinal": SLOT_ORDINAL,
                "run_index": run_index,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        records.append(record)
        write_jsonl(output_path, records)
        print(
            json.dumps(
                {
                    "run_index": run_index,
                    "type": record["type"],
                    "mode": record.get("actual_mode"),
                    "automatic_meaning_complete": record.get(
                        "meaning_complete"
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    cases = [row for row in records if row["type"] == "case"]
    errors = [row for row in records if row["type"] == "error"]
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "status": "adaptive_variability_diagnostic_complete_not_official",
        "slot_ordinal": SLOT_ORDINAL,
        "attempted_calls": REPEAT_COUNT,
        "generation_calls_recorded": sum(
            row["result"].get("generation") is not None for row in cases
        ),
        "generation_errors": len(errors),
        "automatic_meaning_complete_runs": [
            row["run_index"] for row in cases if row["meaning_complete"]
        ],
        "latency_ms": [
            row["result"].get("latency", {}).get("total_ms") for row in cases
        ],
        "official_score_unchanged": True,
    }
    write_jsonl(output_path, [*records, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
