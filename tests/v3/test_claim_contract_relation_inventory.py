from __future__ import annotations

from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.diagnose_typed_evidence_ref_generalization_64_precision_fix import (
    apply_reviewed_claim_target_corrections,
)
from src.v3.extract_claim_contract_relation_inventory import (
    build_relation_inventory,
)


ROOT = Path(__file__).resolve().parents[2]
SEALED = ROOT / (
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_sealed_"
    "e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf32b85a597.jsonl"
)
CORRECTIONS = ROOT / (
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_"
    "claim_target_corrections_20260727.jsonl"
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


def _inventory() -> list[dict[str, object]]:
    sealed = read_jsonl(SEALED)
    chunks = read_jsonl(CHUNKS)
    documents = read_jsonl(DOCUMENTS)
    corrected, _ = apply_reviewed_claim_target_corrections(
        sealed,
        read_jsonl(CORRECTIONS),
        chunks_by_id={row["chunk_id"]: row for row in chunks},
        documents_by_id={
            row["document_id"]: row for row in documents
        },
        sealed_sha256=file_sha256(SEALED),
        corpus_chunks_sha256=file_sha256(CHUNKS),
    )
    return build_relation_inventory(sealed, corrected)


def test_relation_inventory_contains_all_96_requirements() -> None:
    inventory = _inventory()

    assert len(inventory) == 96
    assert len(
        {
            (row["slot_ordinal"], row["requirement_id"])
            for row in inventory
        }
    ) == 96


def test_relation_inventory_uses_reviewed_slot_30_target() -> None:
    inventory = _inventory()
    row = next(
        row
        for row in inventory
        if row["slot_ordinal"] == 30
        and row["requirement_id"] == "supported_levels"
    )

    assert row["sealed_relation"] == "supported_equipment_levels"
    assert row["relation"] == (
        "searchable_and_equippable_equipment_level"
    )
    assert row["claim_target_corrected"] is True
    assert row["relation_contract_state"] == "unvalidated"
    assert row["relation_family"] == "quantity_limit"
    assert row["parent_relation"] == "eligibility"
    assert row["family_validation_mode"] == "typed_family"


def test_relation_inventory_uses_reviewed_slot_47_duration_range() -> None:
    inventory = _inventory()
    row = next(
        row
        for row in inventory
        if row["slot_ordinal"] == 47
        and row["requirement_id"] == "processing_days"
    )

    assert row["expected_status"] == "supported"
    assert row["value_type"] == "duration_range"
    assert row["claim_target_corrected"] is True
    assert row["relation_family"] == "temporal"
    assert row["parent_relation"] == "duration"
    assert row["family_validation_mode"] == "typed_family"


def test_relation_inventory_uses_reviewed_slot_31_preset_limit() -> None:
    inventory = _inventory()
    row = next(
        row
        for row in inventory
        if row["slot_ordinal"] == 31
        and row["requirement_id"] == "preset_limit"
    )

    assert row["expected_status"] == "supported"
    assert row["value_type"] == "number"
    assert row["claim_target_corrected"] is True
    assert row["relation_family"] == "quantity_limit"
    assert row["parent_relation"] == "count"
    assert row["family_validation_mode"] == "typed_family"


def test_all_inventory_relations_have_reviewed_family_contracts() -> None:
    inventory = _inventory()

    assert {
        row["family_type_validation_state"] for row in inventory
    } <= {"typed_family_valid", "audit_only"}
    assert all(row["parent_relation"] for row in inventory)
    assert all(row["relation_family"] != "unregistered" for row in inventory)


def test_inventory_keeps_evidence_document_parent_and_source() -> None:
    inventory = _inventory()
    supported = [
        row for row in inventory if row["expected_status"] == "supported"
    ]

    assert all(row["primary_document_id"] for row in inventory)
    assert all(row["acceptable_parent_document_ids"] for row in supported)
    assert all(row["acceptable_source_ids"] for row in supported)


def test_reviewed_family_registry_replaces_heuristic_misclassifications() -> None:
    inventory = _inventory()
    by_relation = {
        row["relation"]: row
        for row in inventory
    }

    assert by_relation["base_fee"]["relation_family"] == (
        "percentage_effect"
    )
    assert by_relation["credited_after"]["relation_family"] == "temporal"
    assert by_relation["drawing_goods_quantity"]["relation_family"] == (
        "quantity_limit"
    )
