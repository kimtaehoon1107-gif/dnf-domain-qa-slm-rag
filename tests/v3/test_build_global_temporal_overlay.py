from __future__ import annotations

from datetime import date

from src.v3.build_global_temporal_overlay import classify_document_temporally


def _document(**overrides):
    row = {
        "document_id": "document_1",
        "source_kind": "general_notice",
        "status": "current",
        "default_exposure": True,
        "valid_from": None,
        "valid_to": None,
        "fetched_at": "2026-07-18T00:00:00+09:00",
    }
    row.update(overrides)
    return row


def test_old_notice_is_unverified_not_expired_by_publication_age() -> None:
    result = classify_document_temporally(
        _document(published_at="2024-01-31"),
        policy_by_document={},
        review_required_chunk_count=0,
        as_of=date(2026, 7, 18),
    )

    assert result["validity_state"] == "current_unverified"
    assert result["retrieval_action_current"] == "allow_with_warning"
    assert result["last_verified_at"] is None
    assert result["verified_by"] is None


def test_explicit_expired_window_is_denied_and_verified_from_metadata() -> None:
    result = classify_document_temporally(
        _document(valid_from="2026-01-01", valid_to="2026-06-30"),
        policy_by_document={},
        review_required_chunk_count=0,
        as_of=date(2026, 7, 18),
    )

    assert result["validity_state"] == "expired"
    assert result["retrieval_action_current"] == "deny"
    assert result["last_verified_at"] == "2026-07-18T00:00:00+09:00"


def test_preview_is_denied_even_without_dates() -> None:
    result = classify_document_temporally(
        _document(source_kind="preview_patch", status="unknown", default_exposure=False),
        policy_by_document={},
        review_required_chunk_count=0,
        as_of=date(2026, 7, 18),
    )

    assert result["validity_state"] == "preview"
    assert result["retrieval_action_current"] == "deny"


def test_policy_uses_verified_revision_lineage() -> None:
    result = classify_document_temporally(
        _document(source_kind="account_policy"),
        policy_by_document={
            "document_1": {
                "is_current_revision": True,
                "superseded_by": None,
                "last_verified_at": "2026-07-17T00:00:00+09:00",
            }
        },
        review_required_chunk_count=0,
        as_of=date(2026, 7, 18),
    )

    assert result["validity_state"] == "current_revision"
    assert result["retrieval_action_current"] == "allow"
    assert result["last_verified_at"] == "2026-07-17T00:00:00+09:00"
