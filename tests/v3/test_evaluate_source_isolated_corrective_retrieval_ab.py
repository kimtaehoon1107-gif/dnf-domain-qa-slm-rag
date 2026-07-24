from src.v3.evaluate_source_isolated_corrective_retrieval_ab import (
    baseline_allows_corrective_retrieval,
    _decision_view,
    _score_groups,
    candidate_sources,
    certificate_dominates,
    choose_isolated_decisions,
    decision_certificate,
    is_answer_bearing,
)


def _chunk(chunk_id: str, text: str, heading: str = "상품") -> dict:
    return {
        "chunk_id": chunk_id,
        "display_text": text,
        "heading_path": [heading],
    }


def _span(chunk_id: str, text: str, score: float = 0.5) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": f"parent-{chunk_id}",
        "source_id": "source",
        "span_id": f"span-{chunk_id}-{score}",
        "start_char": 0,
        "end_char": len(text),
        "text": text,
        "reranker_score": score,
    }


def test_candidate_sources_keep_route_and_only_frozen_top_two():
    route = {
        "source_ids": ["dnf_faq"],
        "routing_signals": {
            "candidate_sources": ["dnf_notice", "dnf_seria_shop", "dnf_event"]
        },
    }

    assert candidate_sources(route) == ["dnf_faq", "dnf_notice", "dnf_seria_shop"]


def test_heading_navigation_and_image_are_not_answer_bearing():
    assert is_answer_bearing("## 전문직업 포기하기") is False
    assert is_answer_bearing("목록") is False
    assert is_answer_bearing("[IMAGE_ALT] 상품 이미지") is False
    assert is_answer_bearing("전문직업 포기 비용은 10,000 골드입니다.") is True


def test_certificate_requires_subject_and_expected_value_in_one_answer_unit():
    requirement = {
        "requirement_id": "r1",
        "subject": "충전한 세라",
        "relation": "삭제 기간",
        "value_type": "duration",
    }
    chunks = {
        "wrong-subject": _chunk("wrong-subject", "충전한 세라는 현금 화폐입니다."),
        "wrong-value": _chunk("wrong-value", "아이템은 3일 뒤 삭제됩니다.", "아이템"),
        "right": _chunk(
            "right", "충전한 세라는 마지막 사용일로부터 60개월 뒤 삭제됩니다.", "세라"
        ),
    }
    wrong = {
        "status": "supported_exact",
        "spans": [
            _span("wrong-subject", chunks["wrong-subject"]["display_text"], 0.8),
            _span("wrong-value", chunks["wrong-value"]["display_text"], 0.7),
        ],
    }
    right = {
        "status": "supported_exact",
        "spans": [_span("right", chunks["right"]["display_text"], 0.6)],
    }

    wrong_certificate = decision_certificate(requirement, wrong, chunks)
    right_certificate = decision_certificate(requirement, right, chunks)

    assert wrong_certificate["best"]["bound"] is False
    assert right_certificate["best"]["bound"] is True
    assert certificate_dominates(right_certificate, wrong_certificate) is True


def test_isolated_choice_replaces_only_when_certificate_dominates():
    requirement = {
        "requirement_id": "r1",
        "subject": "아라드 로얄 패스",
        "relation": "price",
        "value_type": "amount",
    }
    baseline_text = "아라드 로얄 패스로 업그레이드할 수 있습니다."
    better_text = "아라드 로얄 패스 29,800 세라"
    chunks = {
        "baseline": _chunk("baseline", baseline_text, "아라드 로얄 패스"),
        "better": _chunk("better", better_text, "아라드 로얄 패스"),
    }
    baseline = {
        "status": "supported_exact",
        "spans": [_span("baseline", baseline_text, 0.9)],
    }
    better = {
        "status": "supported_exact",
        "spans": [_span("better", better_text, 0.7)],
    }

    chosen, audit = choose_isolated_decisions(
        [requirement], [baseline], {"dnf_event": [better]}, chunks
    )

    assert chosen == [better]
    assert audit[0]["replacement_source_id"] == "dnf_event"
    assert "gold" not in str(audit).lower()


def test_vetoed_alternative_never_wins_on_reranker_score_alone():
    baseline = {
        "supported_exact": True,
        "answer_bearing": True,
        "shape_vetoed": True,
        "best": {
            "bound": False,
            "shape_safe": False,
            "subject_coverage": 1.0,
            "reranker_score": 0.1,
        },
    }
    alternative = {
        **baseline,
        "best": {**baseline["best"], "reranker_score": 0.99},
    }

    assert certificate_dominates(alternative, baseline) is False


def test_honest_partial_is_not_upgraded_by_corrective_retrieval():
    full = [{"status": "supported_exact"}, {"status": "supported_exact"}]
    partial = [{"status": "supported_exact"}, {"status": "unsupported"}]

    assert baseline_allows_corrective_retrieval(full) is True
    assert baseline_allows_corrective_retrieval(partial) is False


def test_decision_view_keeps_exact_cited_text_for_human_audit():
    requirement = {"requirement_id": "r1", "subject": "상품", "relation": "가격"}
    decision = {
        "status": "supported_exact",
        "spans": [
            {
                "chunk_id": "chunk-1",
                "source_id": "dnf_event",
                "start_char": 3,
                "end_char": 12,
                "text": "29,800 세라",
            }
        ],
    }

    assert _decision_view([requirement], [decision])[0]["citations"][0]["text"] == "29,800 세라"


def test_group_score_distinguishes_chunk_membership_from_exact_gold_span():
    evaluation = {
        "evidence_groups": [
            {
                "group_id": "g1",
                "acceptable_chunk_ids": ["chunk-1"],
                "evidence_span": "9,800 세라",
            }
        ]
    }
    decisions = [
        {
            "status": "supported_exact",
            "spans": [
                {
                    "chunk_id": "chunk-1",
                    "text": "캐릭터 추가 지정권",
                }
            ],
        }
    ]

    score = _score_groups(evaluation, decisions)

    assert score["all_groups_hit"] is True
    assert score["all_evidence_spans_hit"] is False
    assert score["false_full_evidence_span"] is True
