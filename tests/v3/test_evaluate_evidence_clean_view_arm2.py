from __future__ import annotations

from src.v3.evaluate_evidence_clean_view_arm2 import apply_evidence_mask


def test_mask_removes_only_excluded_spans_and_downgrades_empty_requirement() -> None:
    rows = [
        {
            "case_id": "case_1",
            "dataset": "dev",
            "decisions": [
                {
                    "requirement_id": "requirement_1",
                    "status": "supported_exact",
                    "unsupported_message": None,
                    "spans": [
                        {"span_id": "body", "chunk_id": "chunk_1", "start_char": 0, "end_char": 4, "text": "본문"},
                        {"span_id": "nav", "chunk_id": "chunk_1", "start_char": 10, "end_char": 12, "text": "목록"},
                    ],
                },
                {
                    "requirement_id": "requirement_2",
                    "status": "supported_exact",
                    "unsupported_message": None,
                    "spans": [
                        {"span_id": "nav_only", "chunk_id": "chunk_1", "start_char": 10, "end_char": 12, "text": "목록"},
                    ],
                },
            ],
        }
    ]
    view = {
        "chunk_id": "chunk_1",
        "evidence_to_original_offset_map": [
            {"original_start_offset": 0, "original_end_offset": 5}
        ],
        "excluded_ranges": [
            {"start_offset": 5, "end_offset": 20, "reasons": ["navigation"]}
        ],
    }

    masked, removals = apply_evidence_mask(
        rows, views_by_chunk={"chunk_1": view}, evaluation_arm="test"
    )

    assert [span["span_id"] for span in masked[0]["decisions"][0]["spans"]] == ["body"]
    assert masked[0]["decisions"][0]["status"] == "supported_exact"
    assert masked[0]["decisions"][1]["status"] == "unsupported"
    assert len(removals) == 2
    assert {row["evaluation_arm"] for row in removals} == {"test"}
    assert rows[0]["decisions"][1]["status"] == "supported_exact"
