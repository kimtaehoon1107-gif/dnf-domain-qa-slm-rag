from __future__ import annotations

from src.v3.claim_contract_relation_registry import (
    RELATION_CONTRACTS,
    canonical_value_type,
    family_type_validation_state,
    relation_contract,
    relation_families_for_value_type,
    semantic_anchor_groups,
)
from src.v3.typed_evidence_ref import resolve_requirement_claim_contract


def test_reviewed_registry_fixes_the_three_heuristic_misclassifications() -> None:
    assert relation_contract("base_fee").family == "percentage_effect"
    assert relation_contract("additional_fee").family == "percentage_effect"
    assert relation_contract("credited_after").family == "temporal"
    assert (
        relation_contract("drawing_goods_quantity").family
        == "quantity_limit"
    )


def test_registry_exposes_parent_relations() -> None:
    assert relation_contract("effective_at").parent_relation == "point_in_time"
    assert relation_contract("price").parent_relation == "price"
    assert relation_contract("trade_type").parent_relation == "trade_status"
    assert relation_contract(
        "searchable_and_equippable_equipment_level"
    ).parent_relation == "eligibility"


def test_relation_families_for_value_type_distinguishes_unique_and_ambiguous() -> None:
    assert relation_families_for_value_type("percentage") == (
        "percentage_effect",
    )
    assert relation_families_for_value_type("number") == (
        "price_currency",
        "quantity_limit",
        "temporal",
    )
    assert relation_families_for_value_type("unknown") == ()


def test_structured_family_type_contract_is_fail_closed() -> None:
    valid = {
        "relation": "price",
        "value_type": "currency",
    }
    invalid = {
        "relation": "price",
        "value_type": "boolean",
    }

    assert family_type_validation_state(valid) == "typed_family_valid"
    assert family_type_validation_state(invalid) == "type_mismatch"


def test_natural_language_family_stays_audit_only() -> None:
    requirement = {
        "relation": "company_intervention_rule",
        "value_type": "text",
    }

    assert family_type_validation_state(requirement) == "audit_only"
    assert relation_contract(requirement).validation_mode == "audit_only"


def test_registry_canonical_type_repairs_are_centralized() -> None:
    assert canonical_value_type("daily_reset_time") == "time"
    assert canonical_value_type("maintenance_time") == "time_range"
    assert canonical_value_type("processing_days") == "duration_range"

    resolved, _, _ = resolve_requirement_claim_contract(
        {
            "requirement_id": "daily_reset",
            "relation": "daily_reset_time",
            "value_type": "enum",
        },
        question_text="",
    )

    assert resolved["value_type"] == "time"
    assert resolved["_relation_family"] == "temporal"
    assert resolved["_parent_relation"] == "recurring_reset_at"


def test_processing_duration_accepts_official_sowyo_wording() -> None:
    groups = semantic_anchor_groups("processing_days")

    assert "소요" in groups[0]


def test_registry_relations_are_unique_and_nonempty() -> None:
    assert len(RELATION_CONTRACTS) == len(set(RELATION_CONTRACTS))
    assert all(
        contract.family
        and contract.parent_relation
        and contract.allowed_value_types
        for contract in RELATION_CONTRACTS.values()
    )
