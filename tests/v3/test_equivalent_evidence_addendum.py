from __future__ import annotations

from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256


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


def test_equivalent_evidence_addendum_preserves_the_sealed_artifact() -> None:
    rows = read_jsonl(ADDENDUM)

    assert {row["slot_ordinal"] for row in rows} == {8, 41}
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
