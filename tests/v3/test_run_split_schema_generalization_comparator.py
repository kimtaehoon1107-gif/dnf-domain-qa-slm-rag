from __future__ import annotations

import pytest

from src.v3.run_split_schema_generalization_comparator import build_replay_inputs


def _sealed() -> dict:
    return {
        "candidate_id": "case-1",
        "slot_ordinal": 1,
        "question_text": "질문",
        "time_scope": "current",
        "requirements": [
            {
                "requirement_id": "r1",
                "relation": "price",
                "acceptable_evidence_units": [
                    {
                        "chunk_id": "gold",
                        "document_id": "doc",
                        "text": "가격은 100골드입니다.",
                    }
                ],
            },
            {
                "requirement_id": "r2",
                "relation": "trade_type",
                "acceptable_evidence_units": [],
            },
        ],
    }


def _typed() -> dict:
    return {
        "candidate_id": "case-1",
        "baseline_score": {"all_groups_hit": False},
        "requirement_candidate_chunk_ids": [
            ["arm-1", "arm-2"],
            ["arm-1", "arm-2"],
        ],
        "retrieval": {
            "baseline_candidate_ids": ["base-1"],
            "subject_arm_full_candidate_ids": ["arm-1", "arm-2"],
        },
    }


def test_build_replay_inputs_reuses_exact_typed_candidate_snapshot() -> None:
    reviewed, baseline, pools = build_replay_inputs([_sealed()], [_typed()])

    assert reviewed[0]["expected_requirement_count"] == 2
    assert reviewed[0]["evidence_groups"][0]["evidence_span"] == "가격은 100골드입니다."
    assert reviewed[0]["evidence_groups"][1]["evidence_span"] == "__UNSUPPORTED__"
    assert baseline[0]["arm0"]["candidate_chunk_ids"] == ["base-1"]
    assert [
        row["subject_arm_full"]["candidate_chunk_ids"]
        for row in pools[0]["requirement_candidate_pools"]
    ] == [["arm-1", "arm-2"], ["arm-1", "arm-2"]]


def test_build_replay_inputs_rejects_candidate_drift() -> None:
    typed = _typed()
    typed["requirement_candidate_chunk_ids"][1] = ["different"]

    with pytest.raises(RuntimeError, match="differs across requirements"):
        build_replay_inputs([_sealed()], [typed])
