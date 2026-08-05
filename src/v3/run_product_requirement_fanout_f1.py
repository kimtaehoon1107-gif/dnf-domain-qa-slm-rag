from __future__ import annotations

import argparse
import json
import statistics
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


RUNNER_VERSION = "product-requirement-fanout-f1-v1"
DEFAULT_BASELINE = Path(
    "reports/v3/product_free_rag_a6_pending_adaptive_replay_20260806.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_requirement_fanout_f1_20260806.jsonl"
)
TARGET_SLOTS = (7, 32)


def _contains_values(claim: dict[str, Any], values: tuple[str, ...]) -> bool:
    text = " ".join(str(claim.get("text") or "").split())
    return all(value in text for value in values)


def _gate_a6_7(result: dict[str, Any]) -> bool:
    requirements = result.get("fanout_requirements") or []
    if len(requirements) != 2:
        return False
    first = requirements[0].get("claims") or []
    second = requirements[1].get("claims") or []
    first_text = " ".join(str(claim.get("text") or "") for claim in first)
    second_text = " ".join(str(claim.get("text") or "") for claim in second)
    return (
        any(_contains_values(claim, ("20", "18")) for claim in first)
        and not ("12" in first_text and "9" in first_text)
        and any(_contains_values(claim, ("12", "9")) for claim in second)
        and not ("20" in second_text and "18" in second_text)
    )


def _gate_a6_32(result: dict[str, Any]) -> bool:
    requirements = result.get("fanout_requirements") or []
    if len(requirements) != 2:
        return False
    first = requirements[0].get("claims") or []
    second = requirements[1]
    exposed = " ".join(
        str(claim.get("text") or "") for claim in result.get("claims") or []
    )
    return (
        any("221" in str(claim.get("text") or "") for claim in first)
        and second.get("mode") == "unsupported"
        and not second.get("claims")
        and "제한 없음" not in exposed
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the two-case Product requirement fan-out F1 gate"
    )
    parser.add_argument("--frozen-set", type=Path, default=DEFAULT_FROZEN_SET)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    frozen_path = (root / args.frozen_set).resolve()
    baseline_path = (root / args.baseline).resolve()
    output_path = (root / args.output).resolve()
    if output_path.exists():
        raise RuntimeError(f"F1 output already exists: {output_path}")
    if sha256_path(frozen_path) != FROZEN_SHA256:
        raise RuntimeError("opened Product A6 frozen-set SHA mismatch")

    frozen_by_slot = {
        int(row["slot_ordinal"]): row for row in read_jsonl(frozen_path)
    }
    baseline_by_slot = {
        int(row["slot_ordinal"]): row
        for row in read_jsonl(baseline_path)
        if row.get("type") == "case"
    }
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
        use_requirement_fanout=True,
    )
    records = []
    for slot in TARGET_SLOTS:
        frozen = frozen_by_slot[slot]
        print(json.dumps({"stage": "slot_started", "slot": slot}), flush=True)
        result = rag.answer(
            frozen["question_text"],
            metadata_as_of=frozen["as_of"],
        )
        scored = score_case(
            frozen,
            result,
            chunks_by_id=rag._artifacts.chunks_by_id,
        )
        baseline = baseline_by_slot[slot]["result"]
        core_gate = _gate_a6_7(result) if slot == 7 else _gate_a6_32(result)
        record = {
            "type": "case",
            "runner_version": RUNNER_VERSION,
            "evaluation_role": "adaptive_f1_not_blind_not_official",
            "slot_ordinal": slot,
            "question": frozen["question_text"],
            "baseline": {
                "mode": baseline["mode"],
                "rendered_answer": baseline["rendered_answer"],
                "claims": baseline["claims"],
            },
            "fanout": scored,
            "core_gate_passed": core_gate,
            "citation_gate_passed": bool(
                scored.get("all_exposed_citations_exact")
            ),
            "latency_gate_passed": float(result["latency_ms"]) <= 30000.0,
        }
        records.append(record)
        write_jsonl(output_path, records)
        print(
            json.dumps(
                {
                    "slot": slot,
                    "mode": result["mode"],
                    "core_gate": core_gate,
                    "qwen_calls": result["generation"]["fanout_call_count"],
                    "latency_ms": result["latency_ms"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    latencies = [
        float(record["fanout"]["result"]["latency_ms"])
        for record in records
    ]
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "adaptive_f1_not_blind_not_official",
        "qwen_call_count": sum(
            int(record["fanout"]["result"]["generation"]["fanout_call_count"])
            for record in records
        ),
        "a6_7_gate": records[0]["core_gate_passed"],
        "a6_32_gate": records[1]["core_gate_passed"],
        "citation_gate": all(record["citation_gate_passed"] for record in records),
        "latency_gate": all(record["latency_gate_passed"] for record in records),
        "latencies_ms": latencies,
        "median_ms": round(statistics.median(latencies), 3),
        "proceed_to_f2": (
            any(record["core_gate_passed"] for record in records)
            and all(record["citation_gate_passed"] for record in records)
            and all(record["latency_gate_passed"] for record in records)
        ),
        "runtime_default_changed": False,
    }
    write_jsonl(output_path, [*records, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
