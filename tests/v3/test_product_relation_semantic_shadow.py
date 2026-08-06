from src.v3.product_relation_semantic_shadow import (
    build_relation_semantic_shadow,
    citation_semantic_text,
    relation_clause_for_claim,
    relation_clauses_for_claims,
    relation_focused_question_clauses,
)


def test_relation_clauses_keep_compound_requirements_separate():
    clauses = relation_focused_question_clauses(
        "데일리샷 상품의 출시 시각과 특별 할인 쿠폰 금액을 알려줘"
    )

    assert "출시 시각" in clauses
    assert "특별 할인 쿠폰 금액" in clauses


def test_relation_clause_mapping_does_not_use_evidence_scores():
    question = "상점 판매 가격과 계정당 구매 제한을 알려줘"

    assert relation_clause_for_claim(
        question,
        "상점 판매 가격은 1,000 골드입니다.",
    ) == "상점 판매 가격"
    assert relation_clause_for_claim(
        question,
        "계정당 구매 제한은 1회입니다.",
    ) == "계정당 구매 제한"


def test_relation_clause_mapping_prefers_relation_over_subject_identity():
    question = (
        "영롱한 조율의 추 상자와 광휘의 잔영 상자의 "
        "가격·구매 제한을 각각 알려줘"
    )

    assert relation_clause_for_claim(
        question,
        "영롱한 조율의 추 상자의 가격은 360개이며 구매 제한은 월 4회입니다.",
    ) == "가격·구매 제한"


def test_relation_clause_mapping_separates_numbered_relations():
    question = "서비스 담당자 인권 침해의 1차 조치와 2차 조치는 각각 뭐야?"

    assert relation_clause_for_claim(
        question,
        "서비스 담당자 인권 침해의 2차 조치는 3일 이용제한입니다.",
    ) == "2차 조치"


def test_relation_clause_mapping_keeps_subject_specific_shared_relation():
    question = (
        "큐브의 계약에서 흑색 큐브 조각과 흰색 큐브 조각은 "
        "무기에 각각 어떤 속성을 부여해?"
    )

    assert "흰색 큐브 조각" in relation_clause_for_claim(
        question,
        "흰색 큐브 조각은 무기에 명속성을 부여합니다.",
    )


def test_relation_clause_mapping_separates_value_and_deletion_requirements():
    question = "해방의 열쇠 100개 상자는 무엇을 주고 언제 삭제됐어?"

    queries = relation_clauses_for_claims(
        question,
        [
            "해방의 열쇠 100개 상자는 열쇠 100개를 줍니다.",
            "해방의 열쇠 100개 상자는 7월 23일 06시에 삭제됩니다.",
        ],
    )

    assert "삭제" in queries[1]


def test_shared_multi_relation_is_not_forced_to_subject_fragments():
    question = (
        "영롱한 조율의 추 상자와 광휘의 잔영 상자의 "
        "가격·구매 제한을 각각 알려줘"
    )
    queries = relation_clauses_for_claims(
        question,
        [
            "영롱한 조율의 추 상자의 가격은 360개이며 구매 제한은 월 4회입니다.",
            "광휘의 잔영 상자의 가격은 2개이며 구매 제한은 주 40회입니다.",
        ],
    )

    assert all("가격·구매 제한" in query for query in queries)


def test_relation_clauses_strip_subject_and_generic_request_wording():
    assert relation_focused_question_clauses(
        "최후의 과업은 입장 명성 제한이 어떻게 돼?"
    ) == ["입장 명성 제한"]


def test_long_single_question_is_reduced_to_relation_tail():
    question = (
        "아이템 잠금 해제 때 등록된 OTP로 인증하면 "
        "72시간을 기다리지 않고 바로 풀 수 있어?"
    )

    clauses = relation_focused_question_clauses(question)

    assert clauses == ["72시간을 기다리지 않고 바로 풀 수 있어"]
    assert clauses[0] != question.rstrip("?")


def test_semantic_shadow_is_non_blocking_and_uses_best_citation_score():
    claims = [
        {
            "text": "계정당 구매 제한은 1회입니다.",
            "evidence_refs": ["E1", "E2"],
            "citations": [
                {"evidence_ref": "E1", "chunk_id": "wrong", "text": "거래 가능"},
                {
                    "evidence_ref": "E2",
                    "chunk_id": "right",
                    "text": "구매 제한은 계정당 1회입니다.",
                },
            ],
        }
    ]
    seen_pairs = []

    def score_pairs(pairs):
        seen_pairs.extend(pairs)
        return [0.0002, 0.9652]

    records = build_relation_semantic_shadow(
        question="계정당 구매 제한을 알려줘",
        claims=claims,
        score_pairs=score_pairs,
    )

    assert seen_pairs == [
        ("계정당 구매 제한", "근거: 거래 가능"),
        ("계정당 구매 제한", "근거: 구매 제한은 계정당 1회입니다."),
    ]
    assert records[0]["claim_score"] == 0.9652
    assert records[0]["diagnostic_only"] is True
    assert records[0]["affects_answer"] is False
    assert records[0]["threshold"] is None
    assert claims[0]["evidence_refs"] == ["E1", "E2"]


def test_semantic_shadow_rejects_claim_without_restored_citation():
    try:
        build_relation_semantic_shadow(
            question="입장 명성 알려줘",
            claims=[{"text": "입장 명성은 1입니다.", "citations": []}],
            score_pairs=lambda pairs: [],
        )
    except RuntimeError as exc:
        assert "no restored citations" in str(exc)
    else:
        raise AssertionError("missing citations must fail the shadow audit")


def test_metadata_citation_uses_only_declared_restored_fields():
    text, kind = citation_semantic_text(
        {
            "title": "7/16 정기점검 업데이트 안내",
            "published_at": "2026-07-15",
            "canonical_url": "https://example.invalid/not-scored",
            "field_refs": ["title", "published_at"],
        }
    )

    assert text == "제목: 7/16 정기점검 업데이트 안내\n게시일: 2026-07-15"
    assert kind == "metadata_fields"
    assert "canonical_url" not in text
