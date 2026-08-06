from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.diagnose_typed_evidence_ref_generalization_64_precision_fix import (
    apply_reviewed_claim_target_corrections,
    apply_reviewed_equivalent_evidence_overlay,
)
from src.v3.score_typed_evidence_ref_generalization import (
    score_generalization_cases,
)


ROOT = Path(__file__).resolve().parents[2]
ADDENDUM = ROOT / (
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_"
    "equivalent_evidence_addendum_20260727.jsonl"
)
CORRECTIONS = ROOT / (
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_"
    "claim_target_corrections_20260727.jsonl"
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
ADAPTIVE_SOURCE = ROOT / (
    "outputs/v3/diagnostics/"
    "typed_evidence_ref_policy_month_binding_qwen3_8b_"
    "adaptive_full64_20260727.jsonl"
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
    assert audit["applied_count"] == 7
    assert audit["claim_target_correction_required_count"] == 2
    assert {
        row["slot_ordinal"]
        for row in audit["claim_target_correction_required"]
    } == {31, 47}

    before_by_slot = {row["slot_ordinal"]: row for row in before}
    after_by_slot = {row["slot_ordinal"]: row for row in after}
    assert after_by_slot[31] == before_by_slot[31]
    before_processing = next(
        requirement
        for requirement in before_by_slot[47]["requirements"]
        if requirement["requirement_id"] == "processing_days"
    )
    after_processing = next(
        requirement
        for requirement in after_by_slot[47]["requirements"]
        if requirement["requirement_id"] == "processing_days"
    )
    assert after_processing == before_processing
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
    assert first_audit["applied_count"] == 7
    assert second_audit["applied_count"] == 0
    assert second_audit["duplicate_count"] == 7


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


def _apply_target_corrections(
    correction_rows: list[dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    chunks = read_jsonl(CHUNKS)
    documents = read_jsonl(DOCUMENTS)
    return apply_reviewed_claim_target_corrections(
        read_jsonl(SEALED),
        correction_rows or read_jsonl(CORRECTIONS),
        chunks_by_id={row["chunk_id"]: row for row in chunks},
        documents_by_id={
            row["document_id"]: row for row in documents
        },
        sealed_sha256=file_sha256(SEALED),
        corpus_chunks_sha256=file_sha256(CHUNKS),
    )


def test_claim_target_correction_preserves_sealed_and_corrects_reviewed_slots() -> None:
    before = read_jsonl(SEALED)
    after, audit = _apply_target_corrections()

    assert file_sha256(SEALED) == (
        "e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf32b85a597"
    )
    assert audit["sealed_artifact_changed"] is False
    assert audit["applied_count"] == 3
    before_by_slot = {row["slot_ordinal"]: row for row in before}
    after_by_slot = {row["slot_ordinal"]: row for row in after}
    for slot in range(1, 65):
        if slot not in {30, 31, 47}:
            assert after_by_slot[slot] == before_by_slot[slot]

    requirement = after_by_slot[30]["requirements"][0]
    assert requirement["relation"] == (
        "searchable_and_equippable_equipment_level"
    )
    assert requirement["required_values"] == [115]
    assert requirement["value_type"] == "entity_list"
    assert requirement["acceptable_evidence_units"] == [
        {
            "canonical_url": "https://df.nexon.com/guide?no=1494",
            "chunk_id": (
                "chunk_sha256_8e72d8b4e29bd2b22548e8611776e2f5371d4b2"
                "dfb4b27bf0409e866273160e0"
            ),
            "document_id": (
                "document_sha256_13859d266b067df0fd3bd0d1306d3f05eb676603"
                "aea78af25add514935864db0"
            ),
            "document_status": "current",
            "end_char": 191,
            "source_id": "dnf_game_guide",
            "start_char": 158,
            "text": (
                "115레벨 이상 장비, 융합석을 검색 및 착용이 가능합니다."
            ),
            "title": "[시스템] 장비 시뮬레이터",
        }
    ]

    duration = next(
        requirement
        for requirement in after_by_slot[47]["requirements"]
        if requirement["requirement_id"] == "processing_days"
    )
    assert duration["expected_status"] == "supported"
    assert duration["relation"] == "processing_days"
    assert duration["required_values"] == ["3일/5일"]
    assert duration["subject"] == "게임 이용제한 재조사"
    assert duration["value_type"] == "duration_range"
    assert duration["acceptable_evidence_units"][0]["text"].endswith(
        "유형에 따라 3~5일 정도 소요될 수 있는 점 참고 부탁드립니다."
    )

    preset = next(
        requirement
        for requirement in after_by_slot[31]["requirements"]
        if requirement["requirement_id"] == "preset_limit"
    )
    assert preset["expected_status"] == "supported"
    assert preset["relation"] == "maximum_saved_presets"
    assert preset["required_values"] == [10]
    assert preset["value_type"] == "number"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sealed_artifact_sha256", "stale", "sealed SHA mismatch"),
        ("corpus_chunks_sha256", "stale", "corpus SHA mismatch"),
        ("slot_ordinal", 64, "slot mismatch"),
        ("requirement_id", "missing", "requirement ID missing"),
    ],
)
def test_claim_target_correction_rejects_stale_or_misidentified_rows(
    field: str,
    value: object,
    message: str,
) -> None:
    rows = read_jsonl(CORRECTIONS)
    rows[0][field] = value

    with pytest.raises(RuntimeError, match=message):
        _apply_target_corrections(rows)


def test_claim_target_correction_rejects_bad_evidence_coordinates() -> None:
    rows = copy.deepcopy(read_jsonl(CORRECTIONS))
    unit = rows[0]["replacement_claim_target"][
        "acceptable_evidence_units"
    ][0]
    unit["end_char"] -= 1

    with pytest.raises(RuntimeError, match="coordinates mismatch"):
        _apply_target_corrections(rows)


def test_slot_30_historical_115_answer_is_correct_after_target_review() -> None:
    corrected, _ = _apply_target_corrections()
    corrected_slot = next(
        row for row in corrected if row["slot_ordinal"] == 30
    )
    source_slot = next(
        row for row in read_jsonl(ADAPTIVE_SOURCE)
        if row["slot_ordinal"] == 30
    )
    chunks_by_id = {
        row["chunk_id"]: row for row in read_jsonl(CHUNKS)
    }

    scored, summary = score_generalization_cases(
        [corrected_slot],
        [source_slot],
        chunks_by_id=chunks_by_id,
    )

    holdout = scored[0]["holdout_score"]
    assert holdout["gold_value_complete"] is True
    assert holdout["typed_answer_value_complete"] is True
    assert holdout["typed_claim_complete"] is True
    assert holdout["automatic_semantic_false_full"] is False
    assert summary["gold_value_complete"] == {
        "successes": 1,
        "total": 1,
    }
