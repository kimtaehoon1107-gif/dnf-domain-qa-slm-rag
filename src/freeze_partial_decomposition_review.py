from __future__ import annotations

import argparse
import csv
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


DECISIONS = {"approve", "rewrite", "reject"}
QUALITY_FIELDS = (
    "grounded_fact_correct",
    "unsupported_request_natural",
    "targeted_abstention_correct",
)
INVARIANT_FIELDS = (
    "source_qa_id",
    "expected_doc_id",
    "source_question",
    "grounded_answer",
    "evidence_span",
    "unsupported_request",
    "targeted_abstention",
    "proposed_question",
    "proposed_answer",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_review(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def question_set(rows: list[dict[str, Any]]) -> set[str]:
    return {
        normalize_space(row.get("question")).lower()
        for row in rows
        if normalize_space(row.get("question"))
    }


def review_invariant(candidate: dict[str, Any], review: dict[str, str], field: str) -> str:
    if field == "proposed_question":
        return normalize_space(candidate.get("question"))
    if field == "proposed_answer":
        return normalize_space(candidate.get("gold_answer"))
    return normalize_space(candidate.get(field))


def freeze_reviewed_rows(
    candidates: list[dict[str, Any]],
    reviews: list[dict[str, str]],
    chunks_by_id: dict[str, dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
    train_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidate_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("qa_id") or "").strip()
        if not candidate_id or candidate_id in candidate_by_id:
            raise ValueError(f"Missing or duplicate candidate qa_id: {candidate_id!r}")
        candidate_by_id[candidate_id] = candidate

    review_by_id: dict[str, dict[str, str]] = {}
    for review in reviews:
        candidate_id = str(review.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in review_by_id:
            raise ValueError(f"Missing or duplicate review candidate_id: {candidate_id!r}")
        review_by_id[candidate_id] = review

    missing_reviews = sorted(set(candidate_by_id) - set(review_by_id))
    unknown_reviews = sorted(set(review_by_id) - set(candidate_by_id))
    if missing_reviews or unknown_reviews:
        raise ValueError(
            f"Review coverage mismatch: missing={missing_reviews}, unknown={unknown_reviews}"
        )

    blocked_parents, blocked_chunks, blocked_questions = blocked_ids(blocked_rows)
    existing_train_questions = question_set(train_rows)
    output: list[dict[str, Any]] = []
    decisions: Counter[str] = Counter()
    seen_questions: set[str] = set()

    for candidate in candidates:
        candidate_id = str(candidate["qa_id"])
        review = review_by_id[candidate_id]
        decision = str(review.get("human_decision") or "").strip().lower()
        if decision not in DECISIONS:
            raise ValueError(f"Invalid human_decision for {candidate_id}: {decision!r}")

        for field in INVARIANT_FIELDS:
            expected = review_invariant(candidate, review, field)
            actual = normalize_space(review.get(field))
            if actual != expected:
                raise ValueError(f"Review changed immutable field {field}: {candidate_id}")
        review_chunk_ids = [
            item.strip()
            for item in str(review.get("expected_chunk_ids") or "").split("|")
            if item.strip()
        ]
        if review_chunk_ids != list(candidate.get("expected_chunk_ids") or []):
            raise ValueError(f"Review changed expected_chunk_ids: {candidate_id}")

        quality = {
            field: str(review.get(field) or "").strip().lower() for field in QUALITY_FIELDS
        }
        if any(value not in {"yes", "no"} for value in quality.values()):
            raise ValueError(f"All quality fields need yes/no: {candidate_id}")

        human_question = normalize_space(review.get("human_question"))
        human_answer = normalize_space(review.get("human_answer"))
        if decision == "rewrite":
            if not human_question or not human_answer:
                raise ValueError(f"Rewrite requires human_question and human_answer: {candidate_id}")
            if human_question == normalize_space(candidate.get("question")) and human_answer == normalize_space(
                candidate.get("gold_answer")
            ):
                raise ValueError(f"Rewrite must change the question or answer: {candidate_id}")
        elif human_question or human_answer:
            raise ValueError(f"Only rewrite may set human_question/human_answer: {candidate_id}")

        decisions[decision] += 1
        if decision == "reject":
            continue
        if any(value != "yes" for value in quality.values()):
            raise ValueError(f"Accepted row requires yes for all quality fields: {candidate_id}")

        row = dict(candidate)
        if decision == "rewrite":
            row["pre_review_question"] = row["question"]
            row["pre_review_answer"] = row["gold_answer"]
            row["question"] = human_question
            row["expected_answer"] = human_answer
            row["gold_answer"] = human_answer
        row["review_status"] = "approved"
        row["review_decision"] = decision
        row["review_notes"] = normalize_space(review.get("review_notes"))

        question = normalize_space(row.get("question")).lower()
        if not question or question in seen_questions:
            raise ValueError(f"Missing or duplicate accepted question: {candidate_id}")
        if question in existing_train_questions:
            raise ValueError(f"Accepted question already exists in train QA: {candidate_id}")
        if question in blocked_questions:
            raise ValueError(f"Accepted question overlaps held-out evaluation: {candidate_id}")
        if GENERIC_REFUSAL in normalize_space(row.get("gold_answer")):
            raise ValueError(f"Generic refusal is not allowed: {candidate_id}")

        parents = expected_parent_ids(row)
        chunk_ids = expected_chunk_ids(row)
        if parents & blocked_parents or chunk_ids & blocked_chunks:
            raise ValueError(f"Accepted row overlaps held-out parent/chunk: {candidate_id}")
        if not chunk_ids or any(chunk_id not in chunks_by_id for chunk_id in chunk_ids):
            raise ValueError(f"Accepted row has a missing expected chunk: {candidate_id}")
        evidence = normalize_space(row.get("evidence_span"))
        if not evidence or not any(
            evidence in normalize_space(chunks_by_id[chunk_id].get("text"))
            for chunk_id in chunk_ids
        ):
            raise ValueError(f"Accepted row evidence is not visible in its chunk: {candidate_id}")

        seen_questions.add(question)
        output.append(row)

    return output, {
        "candidate_rows": len(candidates),
        "review_rows": len(reviews),
        "decision_counts": dict(decisions),
        "accepted_rows": len(output),
        "unique_accepted_questions": len(seen_questions),
        "train_question_overlap": 0,
        "blocked_parent_overlap": 0,
        "blocked_chunk_overlap": 0,
        "blocked_question_overlap": 0,
        "missing_chunks": 0,
        "span_mismatches": 0,
        "generic_refusal_rows": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze reviewed Partial decomposition training rows.")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/processed/domain_partial_decomposition_train_candidates.jsonl"),
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=Path("data/review/partial_decomposition_train_review_24.csv"),
    )
    parser.add_argument(
        "--candidate-manifest",
        type=Path,
        default=Path("reports/partial_decomposition_train_candidates_manifest.json"),
    )
    parser.add_argument(
        "--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl")
    )
    parser.add_argument(
        "--train-qa",
        type=Path,
        default=Path("data/processed/domain_train_qa_measurement_fixed_blind_safe_v2.jsonl"),
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
        default=Path("data/processed/domain_partial_decomposition_train_reviewed.jsonl"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("reports/partial_decomposition_train_reviewed_manifest.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_manifest = json.loads(args.candidate_manifest.read_text(encoding="utf-8"))
    if source_manifest.get("status") != "pending_human_review":
        raise ValueError("Candidate manifest is not pending human review.")
    if source_manifest.get("output_sha256") != sha256(args.candidates):
        raise ValueError("Candidate file hash no longer matches its manifest.")

    candidates = read_jsonl(args.candidates)
    reviews = read_review(args.review)
    chunks = read_jsonl(args.chunks)
    train_rows = read_jsonl(args.train_qa)
    blocked_rows = [row for path in args.blocked_eval_set for row in read_jsonl(path)]
    output, summary = freeze_reviewed_rows(
        candidates,
        reviews,
        {str(row["doc_id"]): row for row in chunks},
        blocked_rows,
        train_rows,
    )
    if not output:
        raise ValueError("Human review accepted no training rows.")

    write_jsonl(args.output, output)
    manifest = {
        "status": "frozen_reviewed_training_only",
        "may_be_used_for_training": True,
        "source_candidate_manifest": str(args.candidate_manifest),
        "candidate_sha256": sha256(args.candidates),
        "review": str(args.review),
        "review_template_sha256": source_manifest.get("review_sha256"),
        "review_sha256": sha256(args.review),
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        **summary,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
