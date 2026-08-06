from src.v3.minimal_claim_v2_replay import _render_batch


def test_render_batch_preserves_claim_labels_and_deduplicates_chunks() -> None:
    verified = {
        "requirements": [
            {
                "requirement_id": "requirement_1",
                "status": "supported_exact",
                "value_type": "number",
                "value": 10,
                "answer": "10",
                "citations": [
                    {"chunk_id": "chunk_1", "evidence_ref": "E1"},
                    {"chunk_id": "chunk_1", "evidence_ref": "E2"},
                ],
                "verification": {"failure_reasons": []},
            }
        ],
        "verification": {},
    }
    requirements = [
        {
            "requirement_id": "requirement_1",
            "subject": "아바타 프리셋",
            "relation": "maximum_saved_presets",
            "value_type": "number",
        }
    ]

    result = _render_batch(verified, requirements)

    assert result["response_mode"] == "full_answer"
    assert result["requirements"][0]["subject"] == "아바타 프리셋"
    assert result["rendered_answer"].count("[chunk_1]") == 1
