from __future__ import annotations

from src.v3.evaluate_table_atomic_facts_arm1 import (
    augment_decisions,
    fuse_rankings,
    is_table_fact_retrievable,
    is_temporally_eligible,
    select_reranked_children,
)


def _fact(**overrides):
    row = {
        "fact_id": "fact_1",
        "source_chunk_id": "chunk_1",
        "parent_document_id": "document_1",
        "row_text": "| 유니크 | 25개 |",
        "start_offset": 3,
        "end_offset": 17,
        "default_exposure": True,
        "review_required": False,
        "status": "current",
        "valid_from": None,
        "valid_to": None,
    }
    row.update(overrides)
    return row


def test_temporal_eligibility_blocks_noncurrent_or_out_of_window() -> None:
    assert is_temporally_eligible(_fact(), as_of="2026-07-18")
    assert not is_temporally_eligible(_fact(status="expired"), as_of="2026-07-18")
    assert not is_temporally_eligible(_fact(default_exposure=False), as_of="2026-07-18")
    assert not is_temporally_eligible(_fact(valid_from="2026-08-01"), as_of="2026-07-18")
    assert not is_temporally_eligible(_fact(valid_to="2026-07-01"), as_of="2026-07-18")


def test_table_fact_requires_cited_parent_and_current_temporal_allow() -> None:
    overlay = {
        "document_1": {"retrieval_action_current": "allow_with_warning"},
        "document_2": {"retrieval_action_current": "deny"},
    }
    allowed = frozenset({"document_1"})

    assert is_table_fact_retrievable(
        _fact(),
        as_of="2026-07-18",
        allowed_parent_document_ids=allowed,
        temporal_by_document=overlay,
    )
    assert not is_table_fact_retrievable(
        _fact(parent_document_id="document_2"),
        as_of="2026-07-18",
        allowed_parent_document_ids=allowed,
        temporal_by_document=overlay,
    )
    assert not is_table_fact_retrievable(
        _fact(),
        as_of="2026-07-18",
        allowed_parent_document_ids=frozenset({"document_other"}),
        temporal_by_document=overlay,
    )
    assert not is_table_fact_retrievable(
        _fact(),
        as_of="2026-07-18",
        allowed_parent_document_ids=allowed,
        temporal_by_document={},
    )


def test_rrf_is_deterministic_and_rewards_both_channels() -> None:
    assert fuse_rankings(["a", "b"], ["b", "c"]) == ["b", "a", "c"]


def test_selection_is_thresholded_and_chunk_diverse() -> None:
    facts = [
        _fact(fact_id="a", source_chunk_id="chunk_1"),
        _fact(fact_id="b", source_chunk_id="chunk_1"),
        _fact(fact_id="c", source_chunk_id="chunk_2"),
        _fact(fact_id="d", source_chunk_id="chunk_3"),
    ]
    selected = select_reranked_children(
        facts, [0.9, 0.8, 0.7, -0.1], threshold=0.001, k=3
    )
    assert [row["fact_id"] for row in selected] == ["a", "c"]


def test_augmentation_is_additive_and_does_not_turn_unsupported_into_answer() -> None:
    text = "xxx| 유니크 | 25개 |zzz"
    chunks = {"chunk_1": {"display_text": text}}
    supported = {
        "requirement_id": "requirement_1",
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "old",
                "chunk_id": "chunk_old",
                "start_char": 0,
                "end_char": 1,
                "text": "x",
            }
        ],
    }
    unsupported = {
        "requirement_id": "requirement_2",
        "status": "unsupported",
        "spans": [],
    }
    fact = _fact(
        end_offset=3 + len("| 유니크 | 25개 |"),
        reranker_score=0.9,
    )
    output = augment_decisions(
        [supported, unsupported], {1: [fact], 2: [fact]}, chunks
    )

    assert [span["span_id"] for span in output[0]["spans"]] == ["old", "fact_1"]
    assert output[1]["status"] == "unsupported"
    assert output[1]["spans"] == []
    assert supported["spans"][0]["span_id"] == "old"
