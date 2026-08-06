from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.io_utils import read_jsonl
from src.v3.freeze_product_free_rag_a5 import (
    APPROVAL_COLUMNS,
    DEFAULT_RUNTIME_SNAPSHOT,
    apply_human_reviews,
    audit_frozen_rows,
    collect_runtime_artifact_paths,
    load_review_decisions,
)


ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / "data/v3/evaluation/product_free_rag_a5_unexecuted32_draft.jsonl"
CHUNKS = ROOT / (
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)


def _write_review_csv(
    path: Path,
    candidates: list[dict],
    *,
    incomplete_slot: int | None = None,
) -> None:
    columns = [
        "slot_ordinal",
        "source_id",
        "question_text",
        *APPROVAL_COLUMNS,
        "review_decision",
        "reviewer_id",
        "reviewed_at",
        "review_rationale",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for candidate in candidates:
            slot = candidate["slot_ordinal"]
            writer.writerow(
                {
                    "slot_ordinal": slot,
                    "source_id": candidate["source_id"],
                    "question_text": candidate["question_text"],
                    **{
                        column: "" if slot == incomplete_slot else "yes"
                        for column in APPROVAL_COLUMNS
                    },
                    "review_decision": "approve",
                    "reviewer_id": "human-reviewer",
                    "reviewed_at": "2026-07-31T15:00:00+09:00",
                    "review_rationale": "질문·정답·근거·응답 모드를 확인함",
                }
            )


def test_review_csv_rejects_any_unapproved_check(tmp_path: Path) -> None:
    candidates = list(read_jsonl(CANDIDATES))
    review_csv = tmp_path / "review.csv"
    _write_review_csv(review_csv, candidates, incomplete_slot=17)

    with pytest.raises(RuntimeError, match="slot 17: question_approved"):
        load_review_decisions(review_csv, candidates=candidates)


def test_approved_review_freezes_all_rows_and_passes_coordinate_audit(
    tmp_path: Path,
) -> None:
    candidates = list(read_jsonl(CANDIDATES))
    review_csv = tmp_path / "review.csv"
    _write_review_csv(review_csv, candidates)

    reviews = load_review_decisions(review_csv, candidates=candidates)
    frozen = apply_human_reviews(candidates, reviews)
    chunks = {row["chunk_id"]: row for row in read_jsonl(CHUNKS)}
    audit = audit_frozen_rows(frozen, chunks_by_id=chunks)

    assert audit["gate_pass"] is True
    assert all(row["execution_allowed"] is True for row in frozen)
    assert all(row["training_allowed"] is False for row in frozen)


def test_runtime_seal_includes_actual_bm25_and_dense_files() -> None:
    paths = {
        path.name
        for path in collect_runtime_artifact_paths(
            ROOT,
            ROOT / DEFAULT_RUNTIME_SNAPSHOT,
        )
    }

    assert any(name.startswith("bm25_index_") for name in paths)
    assert any(name.startswith("dense_full_embeddings_") for name in paths)
    assert any(name.startswith("dense_full_metadata_") for name in paths)
