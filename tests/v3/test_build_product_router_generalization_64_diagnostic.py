from __future__ import annotations

from src.v3.build_product_router_generalization_64_diagnostic import (
    _requirement_is_covered,
)


def test_supported_requirement_needs_an_acceptable_candidate() -> None:
    requirement = {
        "expected_status": "supported",
        "acceptable_evidence_units": [
            {"chunk_id": "gold"},
        ],
    }

    assert _requirement_is_covered(requirement, ["other", "gold"])
    assert not _requirement_is_covered(requirement, ["other"])


def test_unsupported_requirement_needs_no_candidate() -> None:
    requirement = {
        "expected_status": "unsupported",
        "acceptable_evidence_units": [],
    }

    assert _requirement_is_covered(requirement, [])
