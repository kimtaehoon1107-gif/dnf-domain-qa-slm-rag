from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def question_set(rows: list[dict[str, Any]]) -> set[str]:
    return {normalize_space(row.get("question")).lower() for row in rows if row.get("question")}


def freeze_rows(
    review_rows: list[dict[str, str]],
    chunks_by_id: dict[str, dict[str, Any]],
    blocked_questions: set[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for row in review_rows:
        candidate_id = str(row.get("candidate_id") or "").strip()
        if row.get("human_decision", "").strip().lower() != "approve":
            raise ValueError(f"All partial-dev rows must be approved before freeze: {candidate_id}")
        question = normalize_space(row.get("human_question"))
        answer = normalize_space(row.get("human_gold_answer"))
        evidence_span = normalize_space(row.get("evidence_span"))
        chunk_ids = [item for item in str(row.get("expected_chunk_ids") or "").split("|") if item]
        if not candidate_id or candidate_id in seen_ids:
            raise ValueError(f"Missing or duplicate candidate_id: {candidate_id}")
        if not question or question.lower() in seen_questions:
            raise ValueError(f"Missing or duplicate human question: {candidate_id}")
        if question.lower() in blocked_questions:
            raise ValueError(f"Question overlaps train/RAFT: {candidate_id}")
        if not answer or len(answer) > 200:
            raise ValueError(f"Gold answer must be 1..200 characters: {candidate_id}")
        if not chunk_ids or any(chunk_id not in chunks_by_id for chunk_id in chunk_ids):
            raise ValueError(f"Missing expected chunk: {candidate_id}")
        if not evidence_span or not any(
            evidence_span in normalize_space(chunks_by_id[chunk_id].get("text")) for chunk_id in chunk_ids
        ):
            raise ValueError(f"Evidence span mismatch: {candidate_id}")
        seen_ids.add(candidate_id)
        seen_questions.add(question.lower())
        output.append(
            {
                "eval_id": candidate_id,
                "question": question,
                "intent": "human_partial_personal_decision",
                "answerability": "partial",
                "expected_answer": answer,
                "gold_answer": answer,
                "evidence_span": evidence_span,
                "expected_doc_id": row.get("expected_doc_id", ""),
                "expected_chunk_id": chunk_ids[0],
                "expected_evidence_doc_ids": [row.get("expected_doc_id", "")],
                "expected_chunk_ids": chunk_ids,
                "difficulty": "hard",
                "failure_focus": "partial_personal_decision",
                "source_eval_type": "human_partial_dev",
                "source_split": "dev",
                "source_set": row.get("source_set", ""),
                "source_row_id": row.get("source_row_id", ""),
                "review_notes": row.get("review_notes", ""),
            }
        )
    return output


def read_review(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze approved human-authored partial development rows.")
    parser.add_argument("--review", type=Path, default=Path("data/review/partial_dev_human_review_20.csv"))
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument(
        "--train-qa",
        type=Path,
        default=Path("data/processed/domain_train_qa_measurement_fixed_blind_safe_v2.jsonl"),
    )
    parser.add_argument(
        "--raft",
        type=Path,
        default=Path("data/processed/domain_raft_hard_negative_answer_filtered_blind_safe_v2_gate_balanced.jsonl"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/processed/partial_dev_human_v1.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("reports/partial_dev_human_v1_manifest.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    review_rows = read_review(args.review)
    chunks = read_jsonl(args.chunks)
    train_rows = read_jsonl(args.train_qa)
    raft_rows = read_jsonl(args.raft)
    blocked_questions = question_set(train_rows) | question_set(raft_rows)
    frozen = freeze_rows(review_rows, {str(row["doc_id"]): row for row in chunks}, blocked_questions)
    write_jsonl(args.output, frozen)
    manifest = {
        "status": "frozen_dev_only",
        "evaluation_role": "human_authored_partial_development",
        "may_guide_model_changes": True,
        "may_be_used_for_training": False,
        "review": str(args.review),
        "review_sha256": sha256(args.review),
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        "rows": len(frozen),
        "answerability_counts": {"partial": len(frozen)},
        "unique_questions": len(question_set(frozen)),
        "train_raft_question_overlap": len(question_set(frozen) & blocked_questions),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
