from __future__ import annotations

from src.v3.summarize_v3_2_feature_arms import build_summary


def test_summary_keeps_go_no_go_and_skip_distinct() -> None:
    loaded = {
        "table_atomic_facts": {"gate": {"decision": "GO"}},
        "evidence_clean_view": {"decision": "NO_GO"},
        "global_temporal_overlay": {"decision": "GO_TEMPORAL"},
        "duplicate_family_overlay": {"decision": "GO_DUPLICATE"},
        "policy_clause_children": {"decision": "NO_GO_POLICY"},
        "faq_title_dedup": {"decision": "NO_GO_FAQ"},
        "ocr_structure_readiness": {"audit": {"decision": "SKIP_NO_GO"}},
        "table_sidecar_depths": {"decision": "NO_GAIN"},
        "gradio_candidate_integration": {"gate": {"decision": "GO_DEMO"}},
    }

    summary = build_summary(loaded)
    statuses = {row["improvement"]: row["implementation_status"] for row in summary["rows"]}

    assert statuses["표 row-level atomic fact"] == "implemented_go_candidate"
    assert statuses["FAQ 제목 중복 제거"] == "implemented_ab_no_go"
    assert statuses["OCR 구조 복구"] == "skipped_no_go_precondition"
    assert summary["development_demo"]["decision"] == "GO_DEMO"
    assert summary["development_demo"]["off_on_ab_verified"] is True
    assert summary["promotion"]["development_demo_changed"] is True
    assert summary["promotion"]["promoted"] is False
