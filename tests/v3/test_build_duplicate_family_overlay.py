from __future__ import annotations

from src.v3.build_duplicate_family_overlay import build_duplicate_families


def _relation() -> dict:
    return {
        "normalized_title_key": "sameproduct",
        "parent_documents": [
            {
                "parent_document_id": "document_shop",
                "source_id": "dnf_seria_shop",
                "canonical_url": "https://example.test/shop",
                "title": "Same Product",
                "content_hash": "shop_hash",
            },
            {
                "parent_document_id": "document_event",
                "source_id": "dnf_event",
                "canonical_url": "https://example.test/event",
                "title": "Same Product",
                "content_hash": "event_hash",
            },
        ],
    }


def test_family_keeps_members_and_assigns_distinct_source_roles() -> None:
    family = build_duplicate_families([_relation()])[0]

    assert len(family["members"]) == 2
    assert {member["source_role"] for member in family["members"]} == {
        "commerce_price_components_trade_deletion",
        "event_terms_eligibility_rewards",
    }
    assert family["used_for_document_merge"] is False
    assert family["used_for_retrieval_deduplication"] is False


def test_family_prefers_source_by_attribute_without_runtime_application() -> None:
    family = build_duplicate_families([_relation()])[0]

    assert family["preferred_source_by_attribute"]["price"] == "dnf_seria_shop"
    assert family["preferred_source_by_attribute"]["reward"] == "dnf_event"
    assert family["review_status"] == "requires_semantic_confirmation"
    assert family["used_for_runtime_ranking"] is False


def test_family_id_and_output_are_deterministic() -> None:
    first = build_duplicate_families([_relation()])
    reversed_members = _relation()
    reversed_members["parent_documents"].reverse()
    second = build_duplicate_families([reversed_members])

    assert first == second


def test_missing_role_is_explicit_null_not_invented_source() -> None:
    monthly_shop = _relation()
    monthly_shop["parent_documents"][1]["source_id"] = "dnf_monthly_item"
    family = build_duplicate_families([monthly_shop])[0]

    assert family["preferred_source_by_attribute"]["reward"] is None
    assert family["preferred_source_by_attribute"]["price"] == "dnf_monthly_item"
