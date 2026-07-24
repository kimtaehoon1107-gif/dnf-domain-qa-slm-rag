from __future__ import annotations

from src.v3.build_subject_anchored_requirement_pools import (
    build_requirement_pools,
)


def test_builds_one_bounded_pool_per_fixed_requirement() -> None:
    reviewed = [
        {
            "candidate_id": "case-1",
            "slot_ordinal": 21,
            "question_text": "질문",
            "requirements": [
                {"requirement_id": "requirement_1"},
                {"requirement_id": "requirement_2"},
            ],
        }
    ]
    retrieval = [
        {
            "candidate_id": "case-1",
            "slot_ordinal": 21,
            "plan": {
                "subject": "길드",
                "queries": ["길드 재가입", "길드 권한 위임"],
            },
            "anchored_group_candidate_ids": [
                ["chunk-a", "chunk-b", "chunk-c"],
                ["chunk-d"],
            ],
        }
    ]

    selected, pools, arm_name = build_requirement_pools(
        reviewed,
        retrieval,
        top_k=2,
    )

    assert selected == reviewed
    assert arm_name == "subject_top_2"
    assert pools[0]["requirement_candidate_pools"] == [
        {
            "requirement_id": "requirement_1",
            "query": "길드 재가입",
            "subject_top_2": {
                "candidate_chunk_ids": ["chunk-a", "chunk-b"]
            },
        },
        {
            "requirement_id": "requirement_2",
            "query": "길드 권한 위임",
            "subject_top_2": {"candidate_chunk_ids": ["chunk-d"]},
        },
    ]


def test_builds_full_arm_pool_for_every_case_and_requirement() -> None:
    reviewed = [
        {
            "candidate_id": "case-1",
            "slot_ordinal": 1,
            "question_text": "질문",
            "requirements": [
                {
                    "requirement_id": "requirement_1",
                    "subject": "대상",
                    "surface": "가격",
                },
                {
                    "requirement_id": "requirement_2",
                    "subject": "대상",
                    "surface": "거래 타입",
                },
            ],
        }
    ]
    retrieval = [
        {
            "candidate_id": "case-1",
            "slot_ordinal": 1,
            "plan": None,
            "arm_candidate_ids": ["chunk-a", "chunk-b", "chunk-a"],
            "anchored_group_candidate_ids": [],
        }
    ]

    selected, pools, arm_name = build_requirement_pools(
        reviewed,
        retrieval,
        top_k=3,
        use_full_arm=True,
    )

    assert selected == reviewed
    assert arm_name == "subject_arm_full"
    assert pools[0]["subject"] == "대상"
    assert pools[0]["requirement_candidate_pools"] == [
        {
            "requirement_id": "requirement_1",
            "query": "가격",
            "subject_arm_full": {
                "candidate_chunk_ids": ["chunk-a", "chunk-b"]
            },
        },
        {
            "requirement_id": "requirement_2",
            "query": "거래 타입",
            "subject_arm_full": {
                "candidate_chunk_ids": ["chunk-a", "chunk-b"]
            },
        },
    ]
