from __future__ import annotations

from src.v3.evaluate_gradio_v3_2_candidates import evaluate_wiring


def test_candidate_wiring_adds_exact_table_and_safe_metadata() -> None:
    text = "| 구분 | 비용 |\n| 유니크 | 25개 |\n| 레전더리 | 60개 |\n| 에픽 | 200개 |\n| 태초 | 500개 |"
    chunk = {
        "chunk_id": "chunk_table",
        "display_text": text,
    }
    facts = []
    for index, (label, value) in enumerate(
        [("유니크", "25개"), ("레전더리", "60개"), ("에픽", "200개"), ("태초", "500개")],
        start=1,
    ):
        row_text = f"| {label} | {value} |"
        start = text.index(row_text)
        facts.append(
            {
                "fact_id": f"fact_{index}",
                "table_id": "table_1",
                "row_id": f"row_{index}",
                "parent_document_id": "doc_table",
                "parent_start_offset": start,
                "table_caption": "서약 결정 초월 비용은 아래와 같습니다.",
                "title": "초월",
                "canonical_url": "https://example.test/guide",
                "subject": f"서약 결정 초월 {label}",
                "attribute": "비용",
                "value": value,
                "value_start_offset": start + row_text.index(value),
                "source_chunk_id": "chunk_table",
                "start_offset": start,
                "end_offset": start + len(row_text),
                "row_text": row_text,
            }
        )
    temporal = [
        {
            "document_id": "doc_notice",
            "source_id": "dnf_notice",
            "validity_state": "current_unverified",
            "validity_reason": "no explicit end",
            "retrieval_action_current": "allow_with_warning",
            "last_verified_at": None,
        },
        {
            "document_id": "doc_expired",
            "source_id": "dnf_event",
            "validity_state": "expired",
            "validity_reason": "ended",
            "retrieval_action_current": "deny",
            "last_verified_at": "2026-07-18",
        },
        {
            "document_id": "doc_shop",
            "source_id": "dnf_seria_shop",
            "validity_state": "active_window",
            "validity_reason": "window",
            "retrieval_action_current": "allow",
            "last_verified_at": "2026-07-18",
        },
        {
            "document_id": "doc_event",
            "source_id": "dnf_event",
            "validity_state": "active_window",
            "validity_reason": "window",
            "retrieval_action_current": "allow",
            "last_verified_at": "2026-07-18",
        },
    ]
    families = [
        {
            "duplicate_family_id": "family_1",
            "relation_kind": "same_official_entity_candidate",
            "review_status": "requires_semantic_confirmation",
            "preferred_source_by_attribute": {"price": "dnf_seria_shop"},
            "members": [
                {"parent_document_id": "doc_shop", "source_role": "commerce_price_components_trade_deletion"},
                {"parent_document_id": "doc_event", "source_role": "event_terms_eligibility_rewards"},
            ],
        }
    ]

    result = evaluate_wiring(
        chunks=[chunk],
        facts=facts,
        selected_fact_ids=["fact_1"],
        temporal_rows=temporal,
        families=families,
    )

    assert result["pass"] is True
    assert result["off"]["complete_table_views"] == 0
    assert result["on"]["complete_table_views"] == 1
    assert result["on"]["exact_offset_mismatch_count"] == 0
