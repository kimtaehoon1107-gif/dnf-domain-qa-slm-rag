from src.v3.evaluate_requirement_entity_anchor_ab import (
    GUIDE_CHUNK_ID,
    GUIDE_DOCUMENT_ID,
    propose_equivalent_guide_sibling,
)


def test_guide_sibling_is_proposed_without_mutating_original_gold():
    evaluation = {
        "evidence_groups": [
            {
                "group_id": "g1",
                "acceptable_chunk_ids": ["update"],
                "document_ids": ["update-doc"],
                "evidence_span": "정답 1",
            },
            {
                "group_id": "g2",
                "acceptable_chunk_ids": ["update"],
                "document_ids": ["update-doc"],
                "evidence_span": "정답 2",
            },
        ]
    }
    chunks = {GUIDE_CHUNK_ID: {"display_text": "정답 1\n정답 2"}}

    proposed, audit = propose_equivalent_guide_sibling(evaluation, chunks)

    assert evaluation["evidence_groups"][0]["acceptable_chunk_ids"] == ["update"]
    assert GUIDE_CHUNK_ID in proposed["evidence_groups"][0]["acceptable_chunk_ids"]
    assert GUIDE_DOCUMENT_ID in proposed["evidence_groups"][1]["document_ids"]
    assert audit["gold_changed"] is False
    assert audit["human_review_required"] is True
