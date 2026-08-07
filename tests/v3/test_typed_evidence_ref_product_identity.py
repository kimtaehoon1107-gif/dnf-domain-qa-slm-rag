from __future__ import annotations

from src.v3.typed_evidence_ref import (
    build_evidence_units,
    verify_typed_requirement_selection,
)


def _product_units(text: str) -> tuple[dict, dict[str, dict]]:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": text,
            "default_exposure": True,
            "status": "current",
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_seria_shop",
            "source_kind": "shop_product",
            "title": "트로피컬 바캉스 패키지",
            "published_at": "2026-06-04",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }
    temporal = {
        "d1": {
            "document_id": "d1",
            "source_kind": "shop_product",
            "revision_id": "r1",
            "validity_state": "current",
            "retrieval_action_current": "allow",
        }
    }
    units = build_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    return chunks, {unit["evidence_ref"]: unit for unit in units}


def test_sibling_product_type_cannot_satisfy_requested_product_identity() -> None:
    evidence = (
        "트로피컬 바캉스 오라 아바타 상자는 "
        "2026년 8월 27일 06시에 삭제됩니다."
    )
    chunks, units = _product_units(evidence)
    evidence_ref = next(iter(units))

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "deletion_at",
            "status": "supported",
            "value_type": "datetime",
            "value": "2026-08-27T06:00",
            "evidence_refs": [evidence_ref],
        },
        requirement={
            "requirement_id": "deletion_at",
            "subject": "트로피컬 바캉스 무기 아바타 상자",
            "relation": "deletion_at",
            "value_type": "datetime",
            "temporal_role": "deletion_at",
        },
        question_time_scope="current",
        evidence_units_by_ref=units,
        chunks_by_id=chunks,
        as_of="2026-07-27",
    )

    assert decision["status"] == "unsupported"
    assert "subject_identity_conflict" in audit["failure_reasons"]


def test_exact_product_identity_remains_supported() -> None:
    evidence = (
        "트로피컬 바캉스 무기 아바타 상자는 "
        "2026년 8월 27일 06시에 삭제됩니다."
    )
    chunks, units = _product_units(evidence)
    evidence_ref = next(iter(units))

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "deletion_at",
            "status": "supported",
            "value_type": "datetime",
            "value": "2026-08-27T06:00",
            "evidence_refs": [evidence_ref],
        },
        requirement={
            "requirement_id": "deletion_at",
            "subject": "트로피컬 바캉스 무기 아바타 상자",
            "relation": "deletion_at",
            "value_type": "datetime",
            "temporal_role": "deletion_at",
        },
        question_time_scope="current",
        evidence_units_by_ref=units,
        chunks_by_id=chunks,
        as_of="2026-07-27",
    )

    assert decision["status"] == "supported_exact"
    assert "subject_identity_conflict" not in audit["failure_reasons"]


def test_direct_sibling_type_overrides_requested_heading_context() -> None:
    evidence = (
        "# 트로피컬 바캉스 무기 아바타 상자\n"
        "트로피컬 바캉스 오라 아바타 상자는 "
        "2026년 8월 27일 06시에 삭제됩니다."
    )
    chunks, units = _product_units(evidence)
    sibling_ref = next(
        evidence_ref
        for evidence_ref, unit in units.items()
        if "오라 아바타 상자는" in unit["text"]
    )

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "deletion_at",
            "status": "supported",
            "value_type": "datetime",
            "value": "2026-08-27T06:00",
            "evidence_refs": [sibling_ref],
        },
        requirement={
            "requirement_id": "deletion_at",
            "subject": "트로피컬 바캉스 무기 아바타 상자",
            "relation": "deletion_at",
            "value_type": "datetime",
            "temporal_role": "deletion_at",
        },
        question_time_scope="current",
        evidence_units_by_ref=units,
        chunks_by_id=chunks,
        as_of="2026-07-27",
    )

    assert decision["status"] == "unsupported"
    assert "subject_identity_conflict" in audit["failure_reasons"]
