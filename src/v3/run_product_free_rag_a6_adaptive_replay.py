from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.freeze_product_free_rag_a6 import MODEL_TAG, verify_model
from src.v3.product_free_rag import ProductFreeRAG
from src.v3.run_product_free_rag_a6_one_shot import (
    run_regression_preflight,
    sha256_path,
)
from src.v3.score_product_free_rag_a6 import score_case, summarize


RUNNER_VERSION = "product-free-rag-a6-adaptive-replay-v1"
EVALUATION_ROLE = "adaptive_diagnosis_not_blind_not_official"
FROZEN_SHA256 = (
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc"
)
DEFAULT_FROZEN_SET = Path(
    "data/v3/evaluation/"
    f"product_free_rag_a6_frozen_{FROZEN_SHA256}.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_a6_pending_adaptive_replay_20260806.jsonl"
)
ORIGINAL_ONE_SHOT = Path(
    "reports/v3/product_free_rag_a6_one_shot_"
    "4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499"
    ".jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the already-opened Product A6 set with the current "
            "Product Free RAG. This is adaptive diagnosis, never an "
            "official or blind A6 score."
        )
    )
    parser.add_argument("--frozen-set", type=Path, default=DEFAULT_FROZEN_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def _case_record(
    frozen: dict[str, Any],
    result: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "case",
        "runner_version": RUNNER_VERSION,
        "evaluation_role": EVALUATION_ROLE,
        "adaptive_replay": True,
        "blind": False,
        "official_a6_eligible": False,
        **score_case(frozen, result, chunks_by_id=chunks_by_id),
    }


def _load_records(output_path: Path, *, resume: bool) -> list[dict[str, Any]]:
    if not output_path.exists():
        return []
    if not resume:
        raise RuntimeError(
            f"adaptive output already exists; pass --resume: {output_path}"
        )
    rows = list(read_jsonl(output_path))
    if any(row.get("type") == "summary" for row in rows):
        raise RuntimeError("completed adaptive replay cannot be rerun")
    return [row for row in rows if row.get("type") in {"case", "error"}]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path.cwd().resolve()
    frozen_path = (root / args.frozen_set).resolve()
    output_path = (root / args.output).resolve()

    if sha256_path(frozen_path) != FROZEN_SHA256:
        raise RuntimeError("opened Product A6 frozen-set SHA mismatch")
    frozen_rows = list(read_jsonl(frozen_path))
    if len(frozen_rows) != 32:
        raise RuntimeError(f"expected 32 opened A6 rows, got {len(frozen_rows)}")
    if any(row.get("training_allowed") is not False for row in frozen_rows):
        raise RuntimeError("opened Product A6 rows are not training-prohibited")

    records = _load_records(output_path, resume=args.resume)
    completed_ids = {str(row["candidate_id"]) for row in records}
    if len(completed_ids) != len(records):
        raise RuntimeError("adaptive output contains duplicate candidate IDs")

    print('{"stage":"regression_preflight_started"}', flush=True)
    regression = run_regression_preflight(root)
    print('{"stage":"regression_preflight_passed"}', flush=True)
    print('{"stage":"model_seal_check_started"}', flush=True)
    verify_model()
    print('{"stage":"model_seal_check_passed"}', flush=True)
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

    for frozen in frozen_rows:
        candidate_id = str(frozen["candidate_id"])
        if candidate_id in completed_ids:
            continue
        print(
            json.dumps(
                {"stage": "slot_started", "slot": frozen["slot_ordinal"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            result = rag.answer(
                frozen["question_text"],
                metadata_as_of=frozen["as_of"],
            )
            record = _case_record(
                frozen,
                result,
                chunks_by_id=(
                    rag._artifacts.chunks_by_id
                    if rag._artifacts is not None
                    else {}
                ),
            )
        except Exception as exc:
            record = {
                "type": "error",
                "runner_version": RUNNER_VERSION,
                "evaluation_role": EVALUATION_ROLE,
                "adaptive_replay": True,
                "blind": False,
                "official_a6_eligible": False,
                "slot_ordinal": frozen["slot_ordinal"],
                "candidate_id": candidate_id,
                "question": frozen["question_text"],
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        records.append(record)
        completed_ids.add(candidate_id)
        write_jsonl(output_path, records)
        print(
            json.dumps(
                {
                    "slot": frozen["slot_ordinal"],
                    "type": record["type"],
                    "mode": record.get("actual_mode"),
                    "meaning_complete": record.get("meaning_complete"),
                    "latency_ms": (
                        record.get("result", {})
                        .get("latency", {})
                        .get("total_ms")
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    case_records = [row for row in records if row.get("type") == "case"]
    error_records = [row for row in records if row.get("type") == "error"]
    if len(case_records) + len(error_records) != 32:
        raise RuntimeError("adaptive replay ended without 32 terminal records")

    summary = summarize(
        case_records,
        expected_count=32,
        error_count=len(error_records),
        regression_passed=regression["passed"],
    )
    automated_gate = summary.pop("automated_go_candidate")
    latencies = [
        float(row["result"].get("latency", {}).get("total_ms") or 0.0)
        for row in case_records
    ]
    summary.update(
        {
            "status": "adaptive_replay_not_blind_not_official",
            "runner_version": RUNNER_VERSION,
            "evaluation_role": EVALUATION_ROLE,
            "adaptive_replay": True,
            "blind": False,
            "official_a6_eligible": False,
            "official_a6_rerun": False,
            "adaptive_automated_gate_candidate": automated_gate,
            "go": None,
            "max_ms": round(max(latencies), 3) if latencies else None,
            "over_30_seconds_slots": [
                row["slot_ordinal"]
                for row in case_records
                if float(
                    row["result"].get("latency", {}).get("total_ms") or 0.0
                )
                > 30000
            ],
            "frozen_set": {
                "path": frozen_path.as_posix(),
                "sha256": FROZEN_SHA256,
            },
            "original_official_one_shot": ORIGINAL_ONE_SHOT.as_posix(),
            "query_inputs": "question_only_no_gold_queries_or_subjects",
            "experimental_profile": {
                "model": MODEL_TAG,
                "identity_shortlist": True,
                "compact_evidence_pack": True,
                "atomic_evidence_reranker": True,
                "question_coverage_contract": False,
                "device": rag.device,
            },
            "regression_preflight": regression,
            "errors": error_records,
        }
    )
    write_jsonl(output_path, [*records, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
