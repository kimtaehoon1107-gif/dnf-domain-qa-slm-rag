from __future__ import annotations

import pytest

from src.v3.simple_domain_rag import (
    append_one_baseline_fallback,
    enforce_factual_token_support,
    refine_simple_domain_route,
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


def test_routed_candidates_append_only_one_missing_baseline_fallback() -> None:
    routed = [{"chunk_id": "route-a"}, {"chunk_id": "route-b"}]
    baseline = [
        {"chunk_id": "route-a"},
        {"chunk_id": "baseline-gold"},
        {"chunk_id": "baseline-extra"},
    ]

    merged = append_one_baseline_fallback(
        routed,
        baseline,
        maximum=3,
    )

    assert [row["chunk_id"] for row in merged] == [
        "route-a",
        "route-b",
        "baseline-gold",
    ]


def test_routed_candidate_fallback_never_exceeds_bound() -> None:
    routed = [{"chunk_id": "route-a"}, {"chunk_id": "route-b"}]

    assert append_one_baseline_fallback(
        routed,
        [{"chunk_id": "baseline"}],
        maximum=2,
    ) == routed


@pytest.mark.parametrize(
    ("question", "expected_source", "expected_scope"),
    [
        ("Npay 포인트 쿠폰은 어디에서 입력해?", "dnf_faq", "current"),
        ("던파ON 출석체크 보상은 어디서 받아?", "dnf_game_guide", "current"),
        (
            "운영정책 변경 공지는 언제 시행됐어?",
            "dnf_notice",
            "historical",
        ),
        ("Chrome 권한 알림 공지 내용을 알려줘", "dnf_notice", "current"),
        (
            "6월 이달의 아이템은 언제 삭제됐어?",
            "dnf_monthly_item",
            "historical",
        ),
        ("이 패키지에 포함된 구성품은 뭐야?", "dnf_event", "current"),
        ("5월 28일 업데이트에서 바뀐 내용은?", "dnf_update", "current"),
    ],
)
def test_simple_domain_route_refines_high_confidence_source_patterns(
    question: str,
    expected_source: str,
    expected_scope: str,
) -> None:
    route = refine_simple_domain_route(
        question,
        {
            "routing_signals": {"explicit": []},
            "route_action": "retrieve",
        },
    )

    assert route["source_ids"] == [expected_source]
    assert route["time_scope"] == expected_scope
    assert route["route_action"] == "retrieve"
    assert route["routing_signals"]["explicit"][0].startswith("simple:")


def test_simple_domain_route_leaves_unmatched_route_unchanged() -> None:
    original = {
        "source_ids": ["dnf_faq"],
        "time_scope": "current",
        "routing_signals": {"explicit": []},
        "route_action": "retrieve",
    }

    assert refine_simple_domain_route("장비 성장 방법을 알려줘", original) is original


def test_simple_domain_route_does_not_treat_every_lottery_as_notice() -> None:
    original = {
        "source_ids": ["dnf_event"],
        "time_scope": "current",
        "routing_signals": {"explicit": ["event:이벤트"]},
        "route_action": "retrieve",
    }

    assert refine_simple_domain_route("이벤트 추첨 보상을 알려줘", original) is original


def test_simple_search_policy_restricts_current_search_to_routed_sources() -> None:
    policy = search_policy_for_simple_route(
        {
            "time_scope": "current",
            "temporal_as_of": None,
            "source_ids": ["dnf_update"],
            "routing_signals": {"explicit": ["patch:업데이트"]},
        }
    )

    assert policy.source_ids == ("dnf_update",)
    assert policy.default_exposure_only is True
    assert policy.allowed_statuses == ("current", "upcoming")


def test_simple_search_policy_exposes_only_the_requested_historical_date() -> None:
    policy = search_policy_for_simple_route(
        {
            "time_scope": "historical",
            "temporal_as_of": "2026-06-10",
            "source_ids": ["dnf_monthly_item"],
            "routing_signals": {"explicit": ["monthly:이달의 아이템"]},
        }
    )

    assert policy.source_ids == ("dnf_monthly_item",)
    assert policy.default_exposure_only is False
    assert policy.allowed_statuses is None
    assert policy.as_of == "2026-06-10"


def test_simple_search_policy_allows_expired_month_identity_without_exact_day() -> None:
    policy = search_policy_for_simple_route(
        {
            "time_scope": "historical",
            "temporal_as_of": None,
            "source_ids": ["dnf_monthly_item"],
            "routing_signals": {"explicit": ["monthly:이달의 아이템"]},
        }
    )

    assert policy.source_ids == ("dnf_monthly_item",)
    assert policy.default_exposure_only is False
    assert policy.allowed_statuses is None
    assert policy.as_of is None


def test_simple_search_policy_keeps_all_sources_for_inferred_route() -> None:
    policy = search_policy_for_simple_route(
        {
            "time_scope": "current",
            "temporal_as_of": None,
            "source_ids": ["dnf_faq"],
            "routing_signals": {"explicit": []},
        }
    )

    assert policy.source_ids is None
