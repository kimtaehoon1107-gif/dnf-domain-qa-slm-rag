from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.diagnose_typed_evidence_ref_generalization_64_precision_fix import (
    apply_reviewed_equivalent_evidence_overlay,
)


ROOT = Path(__file__).resolve().parents[2]
ADDENDUM = ROOT / (
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_"
    "equivalent_evidence_addendum_20260727.jsonl"
)
SEALED = ROOT / (
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_sealed_"
    "e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf32b85a597.jsonl"
)
CHUNKS = ROOT / (
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DOCUMENTS = ROOT / (
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)


def test_equivalent_evidence_addendum_preserves_the_sealed_artifact() -> None:
    rows = read_jsonl(ADDENDUM)

    assert {row["slot_ordinal"] for row in rows} == {
        8,
        24,
        31,
        36,
        40,
        41,
        47,
    }
    assert {
        row["evaluation_role"] for row in rows
    } == {"reviewed_equivalent_evidence_addendum_not_sealed_rewrite"}
    assert {
        row["sealed_artifact_sha256"] for row in rows
    } == {file_sha256(SEALED)}


def test_equivalent_evidence_slices_exist_at_the_recorded_coordinates() -> None:
    chunks_by_id = {row["chunk_id"]: row for row in read_jsonl(CHUNKS)}

    for row in read_jsonl(ADDENDUM):
        unit = row["acceptable_evidence_unit"]
        source_text = chunks_by_id[unit["chunk_id"]]["display_text"]
        assert (
            source_text[unit["start_char"] : unit["end_char"]]
            == unit["text"]
        )
        assert row["corpus_chunks_sha256"] == file_sha256(CHUNKS)


def _apply_overlay(
    addendum_rows: list[dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    chunks = read_jsonl(CHUNKS)
    documents = read_jsonl(DOCUMENTS)
    return apply_reviewed_equivalent_evidence_overlay(
        read_jsonl(SEALED),
        addendum_rows or read_jsonl(ADDENDUM),
        chunks_by_id={row["chunk_id"]: row for row in chunks},
        documents_by_id={
            row["document_id"]: row for row in documents
        },
        sealed_sha256=file_sha256(SEALED),
        corpus_chunks_sha256=file_sha256(CHUNKS),
    )


def test_overlay_adds_evidence_only_to_supported_claims() -> None:
    before = read_jsonl(SEALED)
    after, audit = _apply_overlay()

    assert file_sha256(SEALED) == (
        "e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf32b85a597"
    )
    assert audit["applied_count"] == 6
    assert audit["claim_target_correction_required_count"] == 2
    assert {
        row["slot_ordinal"]
        for row in audit["claim_target_correction_required"]
    } == {31, 47}

    before_by_slot = {row["slot_ordinal"]: row for row in before}
    after_by_slot = {row["slot_ordinal"]: row for row in after}
    for slot in (31, 47):
        assert after_by_slot[slot] == before_by_slot[slot]
    for slot in range(1, 65):
        before_row = before_by_slot[slot]
        after_row = after_by_slot[slot]
        assert before_row["question_text"] == after_row["question_text"]
        for before_requirement, after_requirement in zip(
            before_row["requirements"],
            after_row["requirements"],
            strict=True,
        ):
            for key in (
                "expected_status",
                "required_values",
                "value_type",
            ):
                assert (
                    after_requirement[key]
                    == before_requirement[key]
                )


def test_overlay_is_idempotent() -> None:
    once, first_audit = _apply_overlay()
    chunks = read_jsonl(CHUNKS)
    documents = read_jsonl(DOCUMENTS)
    twice, second_audit = apply_reviewed_equivalent_evidence_overlay(
        once,
        read_jsonl(ADDENDUM),
        chunks_by_id={row["chunk_id"]: row for row in chunks},
        documents_by_id={
            row["document_id"]: row for row in documents
        },
        sealed_sha256=file_sha256(SEALED),
        corpus_chunks_sha256=file_sha256(CHUNKS),
    )

    assert twice == once
    assert first_audit["applied_count"] == 6
    assert second_audit["applied_count"] == 0
    assert second_audit["duplicate_count"] == 6


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sealed_artifact_sha256", "stale", "sealed SHA mismatch"),
        ("corpus_chunks_sha256", "stale", "corpus SHA mismatch"),
        ("slot_ordinal", 64, "slot mismatch"),
        ("requirement_id", "missing", "requirement ID missing"),
    ],
)
def test_overlay_rejects_stale_or_misidentified_rows(
    field: str,
    value: object,
    message: str,
) -> None:
    rows = read_jsonl(ADDENDUM)
    rows[0][field] = value

    with pytest.raises(RuntimeError, match=message):
        _apply_overlay(rows)


def test_overlay_rejects_coordinate_or_metadata_mismatch() -> None:
    for mutation, message in (
        (
            lambda row: row["acceptable_evidence_unit"].__setitem__(
                "end_char",
                row["acceptable_evidence_unit"]["end_char"] - 1,
            ),
            "coordinates mismatch",
        ),
        (
            lambda row: row["acceptable_evidence_unit"].__setitem__(
                "source_id",
                "wrong",
            ),
            "chunk metadata mismatch",
        ),
    ):
        rows = copy.deepcopy(read_jsonl(ADDENDUM))
        mutation(rows[0])
        with pytest.raises(RuntimeError, match=message):
            _apply_overlay(rows)
