from __future__ import annotations

import pytest

from src.v3.simple_domain_rag import (
    enforce_factual_token_support,
    search_policy_for_simple_route,
    select_top_reranked,
)


def _verified_result(*answers: tuple[str, str]) -> dict:
    requirements = []
    audits = []
    for index, (answer, evidence) in enumerate(answers, 1):
        requirements.append(
            {
                "requirement_index": index,
                "question_part": f"part {index}",
                "status": "supported_exact",
                "answer": answer,
                "citations": [
                    {
                        "chunk_id": f"chunk_{index}",
                        "text": evidence,
                    }
                ],
            }
        )
        audits.append(
            {
                "requirement_index": index,
                "model_status": "supported",
                "exposed_status": "supported_exact",
                "failure_reasons": [],
            }
        )
    return {
        "response_mode": "full_answer",
        "requirements": requirements,
        "rendered_answer": "before",
        "verification": {
            "requirements": audits,
            "raw_output_passed_without_sanitization": True,
            "all_exposed_citations_verified": True,
        },
    }


def test_factual_token_verifier_keeps_grounded_numbers() -> None:
    result = enforce_factual_token_support(
        _verified_result(
            ("가격은 3,100 세라입니다.", "가격: 3,100세라"),
            ("삭제 시점은 2026년 8월 27일입니다.", "2026년 8월 27일 삭제"),
        )
    )

    assert result["response_mode"] == "full_answer"
    assert all(row["status"] == "supported_exact" for row in result["requirements"])
    assert result["verification"]["raw_output_passed_without_sanitization"] is True


def test_factual_token_verifier_downgrades_only_invented_claim() -> None:
    result = enforce_factual_token_support(
        _verified_result(
            ("가격은 9,999 골드입니다.", "가격은 3,100 골드입니다."),
            ("거래 타입은 계정귀속입니다.", "거래 타입: 계정귀속"),
        )
    )

    assert result["response_mode"] == "partial_answer"
    assert result["requirements"][0]["status"] == "unsupported"
    assert result["requirements"][0]["answer"] == ""
    assert result["requirements"][1]["status"] == "supported_exact"
    assert "9,999 골드" in result["verification"]["requirements"][0][
        "missing_factual_tokens"
    ]


def test_factual_token_verifier_abstains_when_every_claim_is_invalid() -> None:
    result = enforce_factual_token_support(
        _verified_result(("한도는 100회입니다.", "한도는 10회입니다."))
    )

    assert result["response_mode"] == "abstain"
    assert result["rendered_answer"] == ""


def test_select_top_reranked_uses_score_then_retrieval_rank() -> None:
    hits = [
        {"chunk_id": "a", "rank": 1},
        {"chunk_id": "b", "rank": 2},
        {"chunk_id": "c", "rank": 3},
    ]

    selected = select_top_reranked(hits, [0.1, 0.9, 0.8], depth=2)

    assert [row["chunk_id"] for row in selected] == ["b", "c"]


def test_select_top_reranked_rejects_invalid_contract() -> None:
    with pytest.raises(RuntimeError, match="score count"):
        select_top_reranked([{"chunk_id": "a", "rank": 1}], [], depth=1)
    with pytest.raises(RuntimeError, match="at least 1"):
        select_top_reranked([], [], depth=0)


def test_simple_search_policy_uses_all_sources_but_keeps_current_filter() -> None:
    policy = search_policy_for_simple_route(
        {"time_scope": "current", "temporal_as_of": None}
    )

    assert policy.source_ids is None
    assert policy.default_exposure_only is True
    assert policy.allowed_statuses == ("current", "upcoming")


def test_simple_search_policy_exposes_only_the_requested_historical_date() -> None:
    policy = search_policy_for_simple_route(
        {"time_scope": "historical", "temporal_as_of": "2026-06-10"}
    )

    assert policy.source_ids is None
    assert policy.default_exposure_only is False
    assert policy.allowed_statuses is None
    assert policy.as_of == "2026-06-10"
