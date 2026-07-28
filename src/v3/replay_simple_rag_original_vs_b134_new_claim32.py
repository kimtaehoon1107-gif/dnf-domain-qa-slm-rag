from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


RUNNER_VERSION = "simple-rag-original-vs-b134-new-claim32-replay-v1"
DEFAULT_SEALED = Path(
    "data/v3/evaluation/"
    "typed_evidence_ref_new_claim32_sealed_"
    "b8e9f67bc3cb927168f312d3cb5dfaca154c2dffd14c7fabd8c6efb5a98ee83a.jsonl"
)
DEFAULT_SOURCE = Path(
    "outputs/v3/diagnostics/"
    "simple_rag_minimal_verifier_b134_new_claim32_paired_20260728.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "simple_rag_original_vs_b134_new_claim32_paired_20260728.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "simple_rag_original_vs_b134_new_claim32_paired_20260728.json"
)


def _compatible_reviewed(row: dict[str, Any]) -> dict[str, Any]:
    groups = []
    for index, requirement in enumerate(row["requirements"], 1):
        units = requirement["acceptable_evidence_units"]
        groups.append(
            {
                "group_id": f"evidence_{index}",
                "requirement_id": requirement["requirement_id"],
                "acceptable_chunk_ids": list(
                    dict.fromkeys(unit["chunk_id"] for unit in units)
                ),
                "document_ids": list(
                    dict.fromkeys(unit["document_id"] for unit in units)
                ),
                "evidence_span": (
                    units[0]["text"] if units else "__UNSUPPORTED__"
                ),
                "expected_evidence": units,
            }
        )
    return {
        **row,
        "evidence_groups": groups,
        "expected_requirement_count": len(row["requirements"]),
    }


def _adapt(
    sealed: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    source_decisions = result.get("requirements") or []
    source_audits = (
        result.get("verification", {}).get("requirements") or []
    )
    decisions = []
    audits = []
    for index, requirement in enumerate(sealed["requirements"]):
        source = source_decisions[index] if index < len(source_decisions) else {}
        decisions.append(
            {
                "requirement_id": requirement["requirement_id"],
                "question_part": source.get("question_part"),
                "status": source.get("status", "unsupported"),
                "answer": source.get("answer", ""),
                "citations": source.get("citations") or [],
            }
        )
        audit = source_audits[index] if index < len(source_audits) else {}
        audits.append(
            {
                "requirement_id": requirement["requirement_id"],
                "model_status": audit.get("model_status"),
                "exposed_status": decisions[-1]["status"],
                "failure_reasons": audit.get(
                    "failure_reasons",
                    (
                        ["model_requirement_missing"]
                        if index >= len(source_decisions)
                        else []
                    ),
                ),
            }
        )
    return {
        "question_time_scope": result.get("question_time_scope"),
        "model_response_mode": result.get("model_response_mode"),
        "response_mode": result.get("response_mode", "abstain"),
        "requirements": decisions,
        "rendered_answer": result.get("rendered_answer", ""),
        "verification": {
            **result.get("verification", {}),
            "requirements": audits,
        },
    }


def _exposure_signature(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "response_mode": result.get("response_mode"),
        "requirements": [
            {
                "question_part": row.get("question_part"),
                "status": row.get("status"),
                "answer": row.get("answer"),
                "citations": [
                    {
                        "chunk_id": citation.get("chunk_id"),
                        "start_char": citation.get("start_char"),
                        "end_char": citation.get("end_char"),
                        "text": citation.get("text"),
                    }
                    for citation in row.get("citations") or []
                ],
            }
            for row in result.get("requirements") or []
        ],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    source_root = args.legacy_source_root.resolve()
    root_text = os.path.normcase(str(root))
    sys.path = [
        str(source_root),
        *[
            entry
            for entry in sys.path
            if os.path.normcase(str(Path(entry or ".").resolve()))
            != root_text
        ],
    ]

    from src.io_utils import read_jsonl, write_jsonl
    from src.v3.evaluate_grounded_llm_replay import score_verified_output
    from src.v3.evaluate_simple_domain_rag import summarize_cases
    from src.v3.generate_grounded_llm_answer import (
        safe_abstention,
        verify_and_sanitize_output,
    )
    from src.v3.retrieve_v3 import load_runtime_artifacts
    from src.v3.score_typed_evidence_ref_generalization import (
        score_generalization_cases,
    )
    from src.v3.simple_domain_rag import (
        GLOBAL_TEMPORAL_OVERLAY,
        enforce_factual_token_support,
    )

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    sealed_rows = read_jsonl(resolve(args.sealed))
    source_rows = read_jsonl(resolve(args.source))
    if len(sealed_rows) != 32 or len(source_rows) != 32:
        raise RuntimeError("original comparison requires 32 paired rows")
    output_path = resolve(args.output)
    summary_path = resolve(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("original comparison output already exists")

    artifacts = load_runtime_artifacts(root)
    temporal_by_document = {
        row["document_id"]: row
        for row in read_jsonl(root / GLOBAL_TEMPORAL_OVERLAY)
    }
    rows = []
    for sealed, source in zip(sealed_rows, source_rows):
        if sealed["candidate_id"] != source["candidate_id"]:
            raise RuntimeError("sealed and paired source order mismatch")
        raw_output = source.get("raw_model_output")
        if raw_output is None:
            original_basic = safe_abstention(
                RuntimeError("stored raw output unavailable")
            )
        else:
            verified = verify_and_sanitize_output(
                raw_output,
                candidate_chunk_ids=source["candidate_chunk_ids"],
                chunks_by_id=artifacts.chunks_by_id,
                documents_by_id=artifacts.documents_by_id,
                temporal_by_document=temporal_by_document,
            )
            original_basic = enforce_factual_token_support(verified)
        stages = {
            "original_basic": original_basic,
            "guarded_a1_a3": source["original_result"],
            "frozen_b134": source["frozen_b134_result"],
        }
        reviewed = _compatible_reviewed(sealed)
        rows.append(
            {
                "runner_version": RUNNER_VERSION,
                "evaluation_role": (
                    "paired_adaptive_new_claim32_verifier_replay"
                ),
                "candidate_id": source["candidate_id"],
                "slot_ordinal": source["slot_ordinal"],
                "question_text": source["question_text"],
                "source_id": source["source_id"],
                "candidate_chunk_ids": source["candidate_chunk_ids"],
                "original_basic_result": original_basic,
                "guarded_a1_a3_result": source["original_result"],
                "frozen_b134_result": source["frozen_b134_result"],
                "strict_scores": {
                    stage: score_verified_output(
                        reviewed,
                        candidate_chunk_ids=source["candidate_chunk_ids"],
                        verified=result,
                        chunks_by_id=artifacts.chunks_by_id,
                    )
                    for stage, result in stages.items()
                },
                "generation_error": source["generation_error"],
                "observability": source["observability"],
            }
        )
    write_jsonl(output_path, rows)

    summaries = {}
    for stage in ("original_basic", "guarded_a1_a3", "frozen_b134"):
        field = f"{stage}_result"
        cases = []
        strict_cases = []
        for sealed, row in zip(sealed_rows, rows):
            result = row[field]
            cases.append(
                {
                    "candidate_id": row["candidate_id"],
                    "slot_ordinal": row["slot_ordinal"],
                    "question_text": row["question_text"],
                    "verified_output": _adapt(sealed, result),
                    "requirement_candidate_chunk_ids": [
                        list(row["candidate_chunk_ids"])
                        for _ in sealed["requirements"]
                    ],
                    "model_call": {
                        "call_count": int(not row["generation_error"]),
                        "latency_ms": float(
                            row["observability"].get("latency_ms") or 0.0
                        ),
                        "usage": row["observability"].get("usage") or {},
                    },
                }
            )
            strict_cases.append(
                {
                    "candidate_id": row["candidate_id"],
                    "slot_ordinal": row["slot_ordinal"],
                    "is_table_source": row["source_id"]
                    in {"dnf_monthly_item", "dnf_seria_shop"},
                    "gold_requirement_count": len(sealed["requirements"]),
                    "score": row["strict_scores"][stage],
                    "result": result,
                }
            )
        _, fixed_summary = score_generalization_cases(
            sealed_rows,
            copy.deepcopy(cases),
            chunks_by_id=artifacts.chunks_by_id,
        )
        summaries[stage] = {
            "conventional_strict": summarize_cases(strict_cases),
            "fixed_gold_value_scoring": fixed_summary,
            "response_modes": dict(
                sorted(
                    Counter(row[field]["response_mode"] for row in rows).items()
                )
            ),
        }

    summary = {
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "paired_adaptive_new_claim32_verifier_replay",
        "model_calls": 0,
        "retrieval_calls": 0,
        "candidate_sha256": source_rows[0]["candidate_sha256"],
        "generation_error_slots": [
            row["slot_ordinal"] for row in rows if row["generation_error"]
        ],
        "exposure_changed_original_to_guarded": [
            row["slot_ordinal"]
            for row in rows
            if _exposure_signature(row["original_basic_result"])
            != _exposure_signature(row["guarded_a1_a3_result"])
        ],
        "exposure_changed_guarded_to_frozen": [
            row["slot_ordinal"]
            for row in rows
            if _exposure_signature(row["guarded_a1_a3_result"])
            != _exposure_signature(row["frozen_b134_result"])
        ],
        "exposure_changed_original_to_frozen": [
            row["slot_ordinal"]
            for row in rows
            if _exposure_signature(row["original_basic_result"])
            != _exposure_signature(row["frozen_b134_result"])
        ],
        "stages": summaries,
        "manual_review_required": True,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--legacy-source-root", type=Path, required=True)
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            run(build_parser().parse_args()),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
