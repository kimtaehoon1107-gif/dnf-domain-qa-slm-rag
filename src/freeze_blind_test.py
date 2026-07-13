from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from make_blind_test_candidate import expected_chunk_ids, expected_parent_ids


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def training_context_exposure(
    final_rows: list[dict[str, Any]], training_rows: list[dict[str, Any]]
) -> dict[str, int]:
    final_parents = {parent for row in final_rows for parent in expected_parent_ids(row)}
    final_chunks = {chunk for row in final_rows for chunk in expected_chunk_ids(row)}
    hit_parents: set[str] = set()
    hit_chunks: set[str] = set()
    occurrences = 0
    gold_occurrences = 0
    distractor_occurrences = 0
    for row in training_rows:
        for document in row.get("documents") or []:
            doc_id = str(document.get("doc_id", ""))
            parent = doc_id.split("__chunk_", 1)[0]
            if parent not in final_parents:
                continue
            hit_parents.add(parent)
            occurrences += 1
            if document.get("role") == "gold":
                gold_occurrences += 1
            else:
                distractor_occurrences += 1
            if doc_id in final_chunks:
                hit_chunks.add(doc_id)
    return {
        "unique_parent_overlap": len(hit_parents),
        "unique_exact_chunk_overlap": len(hit_chunks),
        "context_occurrences": occurrences,
        "gold_occurrences": gold_occurrences,
        "distractor_occurrences": distractor_occurrences,
    }


def freeze_rows(
    reviewed_rows: list[dict[str, Any]],
    replacement_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
    expected_counts: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unresolved = [
        str(row.get("eval_id", "<missing>"))
        for row in reviewed_rows + replacement_rows
        if row.get("review_status") not in {"approved", "rejected"}
    ]
    if unresolved:
        raise ValueError(f"unresolved review_status rows: {unresolved}")

    selected = [
        dict(row)
        for row in reviewed_rows + replacement_rows
        if row.get("review_status") == "approved"
    ]
    ids = [str(row.get("eval_id", "")) for row in selected]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("final blind rows require unique non-empty eval_id values")

    questions = [normalize_space(row.get("question", "")).lower() for row in selected]
    if not all(questions) or len(questions) != len(set(questions)):
        raise ValueError("final blind rows contain empty or duplicate normalized questions")

    counts = Counter(str(row.get("answerability", "")) for row in selected)
    if dict(counts) != expected_counts:
        raise ValueError(f"answerability distribution mismatch: {dict(counts)} != {expected_counts}")

    chunks_by_id = {str(chunk["doc_id"]): chunk for chunk in chunks}
    missing_chunks: list[str] = []
    span_mismatches: list[str] = []
    false_with_evidence: list[str] = []
    for row in selected:
        eval_id = str(row["eval_id"])
        if row.get("answerability") == "false":
            if (
                row.get("evidence_span")
                or expected_chunk_ids(row)
                or row.get("citations")
                or row.get("expected_doc_id")
            ):
                false_with_evidence.append(eval_id)
            continue

        chunk_ids = expected_chunk_ids(row)
        if not chunk_ids:
            missing_chunks.append(eval_id)
            continue
        span = str(row.get("evidence_span", ""))
        available = [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]
        if not available:
            missing_chunks.append(eval_id)
        elif not span or not any(span in str(chunk.get("text", "")) for chunk in available):
            span_mismatches.append(eval_id)

    if missing_chunks or span_mismatches or false_with_evidence:
        raise ValueError(
            "blind evidence validation failed: "
            f"missing_chunks={missing_chunks}, span_mismatches={span_mismatches}, "
            f"false_with_evidence={false_with_evidence}"
        )

    blocked_parents = {parent for row in blocked_rows for parent in expected_parent_ids(row)}
    blocked_chunks = {chunk for row in blocked_rows for chunk in expected_chunk_ids(row)}
    blocked_questions = {
        normalize_space(row.get("question", "")).lower()
        for row in blocked_rows
        if row.get("question")
    }
    final_parents = {parent for row in selected for parent in expected_parent_ids(row)}
    final_chunks = {chunk for row in selected for chunk in expected_chunk_ids(row)}
    parent_overlap = sorted(final_parents & blocked_parents)
    chunk_overlap = sorted(final_chunks & blocked_chunks)
    question_overlap = sorted(set(questions) & blocked_questions)
    if parent_overlap or chunk_overlap or question_overlap:
        raise ValueError(
            "blind leakage validation failed: "
            f"parents={parent_overlap}, chunks={chunk_overlap}, questions={question_overlap}"
        )

    final_rows = []
    for row in selected:
        frozen = dict(row)
        frozen["evaluation_role"] = "final_blind_test_v1"
        frozen["source_split"] = "blind_v1_frozen"
        frozen["blind_test_version"] = "v1"
        final_rows.append(frozen)

    report = {
        "rows": len(final_rows),
        "answerability_counts": dict(counts),
        "unique_ids": len(set(ids)),
        "unique_questions": len(set(questions)),
        "missing_chunks": len(missing_chunks),
        "evidence_span_mismatches": len(span_mismatches),
        "false_with_evidence": len(false_with_evidence),
        "blocked_parent_overlap": len(parent_overlap),
        "blocked_chunk_overlap": len(chunk_overlap),
        "blocked_question_overlap": len(question_overlap),
    }
    return final_rows, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and freeze a one-shot blind-test release.")
    parser.add_argument("--reviewed-candidate", type=Path, required=True)
    parser.add_argument("--replacements", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument(
        "--train-qa", type=Path, default=Path("data/processed/domain_train_qa_measurement_fixed.jsonl")
    )
    parser.add_argument(
        "--existing-eval-set",
        type=Path,
        nargs="+",
        default=[
            Path("data/processed/domain_eval_set_expanded.jsonl"),
            Path("data/processed/official_eval_set.jsonl"),
            Path("data/processed/fresh_paraphrase_eval_set.jsonl"),
        ],
    )
    parser.add_argument("--output", type=Path, default=Path("data/eval/blind_test_v1.jsonl"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("reports/blind_test_v1_frozen_manifest.json")
    )
    parser.add_argument(
        "--historical-raft",
        type=Path,
        nargs="*",
        default=[
            Path("data/processed/domain_raft_sample_expanded_gate_balanced.jsonl"),
            Path("data/processed/domain_raft_measurement_fixed_gate_balanced.jsonl"),
            Path("data/processed/domain_raft_instruction_only_gate_balanced.jsonl"),
            Path("data/processed/domain_raft_hard_negative_only_gate_balanced.jsonl"),
        ],
        help="RAFT files used by historical adapters; exposure makes them incompatible with this blind release.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    reviewed_rows = read_jsonl(args.reviewed_candidate)
    replacement_rows = read_jsonl(args.replacements)
    chunks = read_jsonl(args.chunks)
    blocked_paths = [args.train_qa, *args.existing_eval_set]
    blocked_rows = [row for path in blocked_paths for row in read_jsonl(path)]
    final_rows, report = freeze_rows(
        reviewed_rows,
        replacement_rows,
        chunks,
        blocked_rows,
        expected_counts={"true": 60, "partial": 20, "false": 20},
    )
    write_jsonl(args.output, final_rows)

    historical_audit = []
    for path in args.historical_raft:
        if not path.exists():
            continue
        exposure = training_context_exposure(final_rows, read_jsonl(path))
        historical_audit.append({"path": str(path), **exposure})
    historical_adapter_compatible = not any(
        item["unique_parent_overlap"] for item in historical_audit
    )

    manifest = {
        "status": (
            "frozen_unevaluated"
            if historical_adapter_compatible
            else "frozen_unevaluated_requires_clean_retrain"
        ),
        "evaluation_role": "final_blind_test_v1",
        "model_evaluation_allowed": "one_shot_only",
        "evaluated": False,
        "historical_adapter_compatible": historical_adapter_compatible,
        "required_before_evaluation": (
            []
            if historical_adapter_compatible
            else [
                "Regenerate RAFT with zero blind parent/chunk context overlap.",
                "Train a new adapter from the base model, not from any historical adapter.",
                "Do not include historical adapter scores in the final blind comparison.",
            ]
        ),
        "historical_training_context_audit": historical_audit,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "review_method": (
            "30-row full human review, assistant pre-review of 70 rows, "
            "risk-stratified 25-row human confirmation, and full human review of 4 replacements"
        ),
        "source_files": {
            str(args.reviewed_candidate): file_sha256(args.reviewed_candidate),
            str(args.replacements): file_sha256(args.replacements),
            str(args.chunks): file_sha256(args.chunks),
            **{str(path): file_sha256(path) for path in blocked_paths},
            **{str(path): file_sha256(path) for path in args.historical_raft if path.exists()},
        },
        "output": str(args.output),
        "output_sha256": file_sha256(args.output),
        **report,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
