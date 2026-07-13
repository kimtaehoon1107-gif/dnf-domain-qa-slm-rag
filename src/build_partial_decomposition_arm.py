from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from make_partial_decomposition_train import (
    DEFAULT_BLOCKED_EVAL_SETS,
    GENERIC_REFUSAL,
    blocked_ids,
    expected_chunk_ids,
    expected_parent_ids,
    normalize_space,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_arm(
    base_rows: list[dict[str, Any]],
    reviewed_rows: list[dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_ids = {str(row.get("qa_id") or "") for row in base_rows}
    if "" in base_ids or len(base_ids) != len(base_rows):
        raise ValueError("Base train QA has missing or duplicate qa_id values.")
    base_questions = {
        normalize_space(row.get("question")).lower()
        for row in base_rows
        if normalize_space(row.get("question"))
    }
    if len(base_questions) != len(base_rows):
        raise ValueError("Base train QA has missing or duplicate questions.")

    blocked_parents, blocked_chunks, blocked_questions = blocked_ids(blocked_rows)
    reviewed_ids: set[str] = set()
    reviewed_questions: set[str] = set()
    for row in reviewed_rows:
        qa_id = str(row.get("qa_id") or "").strip()
        question = normalize_space(row.get("question")).lower()
        if not qa_id or qa_id in reviewed_ids or qa_id in base_ids:
            raise ValueError(f"Reviewed row has missing or duplicate qa_id: {qa_id!r}")
        if not question or question in reviewed_questions or question in base_questions:
            raise ValueError(f"Reviewed row has missing or duplicate train question: {qa_id}")
        if str(row.get("review_status")) != "approved":
            raise ValueError(f"Reviewed row is not approved: {qa_id}")
        if str(row.get("source_split") or row.get("split")) != "train":
            raise ValueError(f"Reviewed row is not train-only: {qa_id}")
        if str(row.get("answerability")) != "partial":
            raise ValueError(f"Reviewed row is not Partial: {qa_id}")
        requirement_types = {str(item.get("type")) for item in row.get("requirements", [])}
        if requirement_types != {"grounded", "unsupported"}:
            raise ValueError(f"Reviewed row lacks grounded/unsupported requirements: {qa_id}")
        if GENERIC_REFUSAL in normalize_space(row.get("gold_answer")):
            raise ValueError(f"Reviewed row contains the generic refusal: {qa_id}")
        if expected_parent_ids(row) & blocked_parents:
            raise ValueError(f"Reviewed row overlaps a held-out parent: {qa_id}")
        if expected_chunk_ids(row) & blocked_chunks:
            raise ValueError(f"Reviewed row overlaps a held-out chunk: {qa_id}")
        if question in blocked_questions:
            raise ValueError(f"Reviewed row overlaps a held-out question: {qa_id}")
        reviewed_ids.add(qa_id)
        reviewed_questions.add(question)

    combined = [*base_rows, *reviewed_rows]
    return combined, {
        "base_rows": len(base_rows),
        "reviewed_decomposition_rows": len(reviewed_rows),
        "rows": len(combined),
        "unique_ids": len(base_ids | reviewed_ids),
        "unique_questions": len(base_questions | reviewed_questions),
        "answerability_counts": dict(
            Counter(str(row.get("answerability", "")) for row in combined)
        ),
        "reviewed_blocked_parent_overlap": 0,
        "reviewed_blocked_chunk_overlap": 0,
        "reviewed_blocked_question_overlap": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the reviewed Partial decomposition train arm.")
    parser.add_argument(
        "--base-train-qa",
        type=Path,
        default=Path("data/processed/domain_train_qa_measurement_fixed_blind_safe_v2.jsonl"),
    )
    parser.add_argument(
        "--reviewed",
        type=Path,
        default=Path("data/processed/domain_partial_decomposition_train_reviewed.jsonl"),
    )
    parser.add_argument(
        "--reviewed-manifest",
        type=Path,
        default=Path("reports/partial_decomposition_train_reviewed_manifest.json"),
    )
    parser.add_argument(
        "--blocked-eval-set",
        type=Path,
        nargs="*",
        default=list(DEFAULT_BLOCKED_EVAL_SETS),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/domain_train_qa_partial_decomposition_arm.jsonl"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("reports/domain_train_qa_partial_decomposition_arm_manifest.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reviewed_manifest = json.loads(args.reviewed_manifest.read_text(encoding="utf-8"))
    if reviewed_manifest.get("status") != "frozen_reviewed_training_only":
        raise ValueError("Reviewed decomposition manifest is not frozen for training.")
    if reviewed_manifest.get("may_be_used_for_training") is not True:
        raise ValueError("Reviewed decomposition manifest does not allow training use.")
    if reviewed_manifest.get("output_sha256") != sha256(args.reviewed):
        raise ValueError("Reviewed decomposition rows no longer match their manifest.")

    base_rows = read_jsonl(args.base_train_qa)
    reviewed_rows = read_jsonl(args.reviewed)
    blocked_rows = [row for path in args.blocked_eval_set for row in read_jsonl(path)]
    combined, summary = build_arm(base_rows, reviewed_rows, blocked_rows)
    write_jsonl(args.output, combined)
    manifest = {
        "status": "ready_for_hard_negative_mining",
        "may_be_used_for_raft_build": True,
        "may_be_used_for_training": False,
        "base_train_qa": str(args.base_train_qa),
        "base_train_qa_sha256": sha256(args.base_train_qa),
        "reviewed_decomposition": str(args.reviewed),
        "reviewed_decomposition_sha256": sha256(args.reviewed),
        "blocked_eval_sets": [str(path) for path in args.blocked_eval_set],
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        **summary,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
