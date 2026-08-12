from __future__ import annotations

from src.v3.product_minimal_verifier import verify_product_claim_output


QUESTION = "미카엘라 레이드 하드와 일반의 보상 차이 알려줘."


def _verify_claims(claims: list[str], evidence: str) -> dict:
    unit = {
        "evidence_ref": "E1",
        "chunk_id": "c1",
        "parent_document_id": "d1",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "title": "무너진 성자 미카엘라 레이드 보상",
        "context_text": "레이드 클리어 보상",
        "unit_kind": "table_row",
        "question_relevance_score": 1.0,
    }
    return verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {"text": claim, "evidence_refs": ["E1"]}
                for claim in claims
            ],
            "clarification": "",
        },
        question=QUESTION,
        evidence_units=[unit],
        chunks_by_id={"c1": {"display_text": evidence}},
    )


def _verify(claim: str, evidence: str) -> dict:
    return _verify_claims([claim], evidence)


def test_comparison_verifier_rejects_derived_delta_not_present_in_evidence() -> None:
    verified = _verify(
        "광휘의 잔재는 하드가 일반보다 50개 더 많습니다.",
        "| 광휘의 잔재 | 일반: 40개 | 하드: 90개 |",
    )

    assert verified["claims"] == []
    assert verified["rejected_claims"][0]["reasons"] == [
        "comparison_values_incomplete"
    ]


def test_comparison_verifier_rejects_absolute_value_used_as_delta() -> None:
    verified = _verify(
        "광휘의 잔재는 하드가 일반보다 90개 더 많습니다.",
        "| 광휘의 잔재 | 일반: 40개 | 하드: 90개 |",
    )

    assert verified["claims"] == []
    assert verified["rejected_claims"][0]["reasons"] == [
        "comparison_values_incomplete"
    ]


def test_comparison_verifier_rejects_orphaned_unlabeled_quantity_row() -> None:
    verified = _verify(
        "하드 모드는 일반보다 90개의 아이템을 추가로 제공합니다.",
        "| 싱글 | 매칭 | 일반 | 하드 | - | - | 40개 | 90개 |",
    )

    assert verified["claims"] == []
    assert verified["rejected_claims"][0]["reasons"] == [
        "comparison_values_incomplete"
    ]


def test_comparison_verifier_requires_both_unequal_values_or_verified_delta() -> None:
    incomplete = _verify(
        "광휘의 잔재는 하드에서 90개 획득할 수 있습니다.",
        "| 광휘의 잔재 | 일반: 40개 | 하드: 90개 |",
    )
    complete = _verify(
        "광휘의 잔재는 일반에서 40개, 하드에서 90개 획득합니다.",
        "| 광휘의 잔재 | 일반: 40개 | 하드: 90개 |",
    )

    assert incomplete["claims"] == []
    assert incomplete["rejected_claims"][0]["reasons"] == [
        "comparison_values_incomplete"
    ]
    assert len(complete["claims"]) == 1


def test_comparison_verifier_accepts_complementary_claims_on_same_row() -> None:
    verified = _verify_claims(
        [
            "광휘의 잔재는 하드에서 90개 획득합니다.",
            "광휘의 잔재는 일반에서 40개 획득합니다.",
        ],
        "| 광휘의 잔재 | 일반: 40개 | 하드: 90개 |",
    )

    assert len(verified["claims"]) == 2
    assert verified["rejected_claims"] == []


def _verify_availability(
    claim: str,
    *,
    enable_availability_comparison: bool,
    subject: str = "임의의 원석",
) -> dict:
    evidence = f"| {subject} | - | O |"
    unit = {
        "evidence_ref": "E1",
        "chunk_id": "availability",
        "parent_document_id": "d1",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "title": "임의의 레이드 보상",
        "context_text": (
            "표 열: | 항목 | 일반 | 하드 | > "
            f"열 해석: {subject}: 일반 획득 불가, 하드 획득 가능"
        ),
        "unit_kind": "table_row",
        "question_relevance_score": 1.0,
        "availability_subject": subject,
        "availability_values": {"일반": False, "하드": True},
    }
    return verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [{"text": claim, "evidence_refs": ["E1"]}],
            "clarification": "",
        },
        question="임의의 레이드 일반과 하드 보상 차이 알려줘.",
        evidence_units=[unit],
        chunks_by_id={"availability": {"display_text": evidence}},
        enable_availability_comparison=enable_availability_comparison,
    )


def test_availability_comparison_shadow_accepts_matching_values() -> None:
    verified = _verify_availability(
        "임의의 원석은 일반에서 획득 불가, 하드에서 획득 가능하다.",
        enable_availability_comparison=True,
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []


def test_availability_comparison_accepts_marker_with_explanation() -> None:
    verified = _verify_availability(
        "임의의 원석은 일반에서 X(불가), 하드에서 O(가능)입니다.",
        enable_availability_comparison=True,
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []


def test_availability_comparison_allows_omitted_leading_document_qualifier() -> None:
    accepted = _verify_availability(
        "경매 주화는 일반 획득 불가, 하드 획득 가능입니다.",
        enable_availability_comparison=True,
        subject="[임의 레이드] 경매 주화",
    )
    conflicting = _verify_availability(
        "[다른 레이드] 경매 주화는 일반 획득 불가, 하드 획득 가능입니다.",
        enable_availability_comparison=True,
        subject="[임의 레이드] 경매 주화",
    )

    assert len(accepted["claims"]) == 1
    assert accepted["rejected_claims"] == []
    assert conflicting["claims"] == []
    assert "availability_subject_mismatch" in conflicting[
        "rejected_claims"
    ][0]["reasons"]


def test_availability_comparison_uses_value_occurrences_after_intro() -> None:
    verified = _verify_availability(
        "일반과 하드의 차이는 임의의 원석이 일반에서 획득 불가이고, "
        "하드에서 획득 가능하다는 점이다.",
        enable_availability_comparison=True,
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []


def test_availability_comparison_shadow_rejects_reversed_values() -> None:
    verified = _verify_availability(
        "임의의 원석은 일반에서 획득 가능, 하드에서 획득 불가다.",
        enable_availability_comparison=True,
    )

    assert verified["claims"] == []
    assert "availability_value_mismatch" in verified["rejected_claims"][0][
        "reasons"
    ]


def test_availability_comparison_shadow_rejects_missing_side() -> None:
    verified = _verify_availability(
        "임의의 원석은 일반에서 획득 불가다.",
        enable_availability_comparison=True,
    )

    assert verified["claims"] == []
    assert "availability_comparison_incomplete" in verified[
        "rejected_claims"
    ][0]["reasons"]


def test_availability_comparison_accepts_complementary_claims_on_same_row() -> None:
    evidence = (
        "| 임의의 주화(1회 교환 가능) 교환권 | - | O | "
        "사용 시 3개 획득, 개봉 비용 15개 |"
    )
    unit = {
        "evidence_ref": "E1",
        "chunk_id": "availability-pair",
        "parent_document_id": "d1",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "title": "임의의 레이드 보상",
        "context_text": (
            "표 열: | 항목 | 일반 | 하드 | > "
            "열 해석: 임의의 주화(1회 교환 가능) 교환권: "
            "일반 획득 불가, 하드 획득 가능"
        ),
        "unit_kind": "table_row",
        "question_relevance_score": 1.0,
        "availability_subject": "임의의 주화(1회 교환 가능) 교환권",
        "availability_values": {"일반": False, "하드": True},
    }
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "임의의 주화(1회 교환 가능) 교환권은 "
                        "일반에서 획득 불가다."
                    ),
                    "evidence_refs": ["E1"],
                },
                {
                    "text": (
                        "임의의 주화(1회 교환 가능) 교환권은 "
                        "하드에서 획득 가능하다."
                    ),
                    "evidence_refs": ["E1"],
                },
            ],
            "clarification": "",
        },
        question="임의의 레이드 일반과 하드 보상 차이 알려줘.",
        evidence_units=[unit],
        chunks_by_id={
            "availability-pair": {"display_text": evidence}
        },
        enable_availability_comparison=True,
    )

    assert len(verified["claims"]) == 2
    assert verified["rejected_claims"] == []


def test_availability_comparison_binds_each_subject_in_merged_claim() -> None:
    evidence_a = "| 항아리 A | - | O |"
    evidence_b = "| 항아리 B | O | X |"
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": "d1",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "title": "임의의 레이드 보상",
            "context_text": context,
            "unit_kind": "table_row",
            "question_relevance_score": 1.0,
            "availability_subject": subject,
            "availability_values": values,
        }
        for evidence_ref, chunk_id, evidence, context, subject, values in (
            (
                "E1",
                "merged-a",
                evidence_a,
                "항아리 A: 일반 획득 불가, 하드 획득 가능",
                "항아리 A",
                {"일반": False, "하드": True},
            ),
            (
                "E2",
                "merged-b",
                evidence_b,
                "항아리 B: 일반 획득 가능, 하드 획득 불가",
                "항아리 B",
                {"일반": True, "하드": False},
            ),
        )
    ]

    def verify(text: str) -> dict:
        return verify_product_claim_output(
            {
                "mode": "answer",
                "claims": [
                    {"text": text, "evidence_refs": ["E1", "E2"]}
                ],
                "clarification": "",
            },
            question="임의의 레이드 일반과 하드 보상 차이 알려줘.",
            evidence_units=units,
            chunks_by_id={
                "merged-a": {"display_text": evidence_a},
                "merged-b": {"display_text": evidence_b},
            },
            enable_availability_comparison=True,
        )

    correct = verify(
        "항아리 A는 일반 획득 불가, 하드 획득 가능하고, "
        "항아리 B는 일반 획득 가능, 하드 획득 불가다."
    )
    swapped = verify(
        "항아리 A는 일반 획득 불가, 하드 획득 가능하고, "
        "항아리 B도 일반 획득 불가, 하드 획득 가능하다."
    )

    assert len(correct["claims"]) == 1
    assert correct["rejected_claims"] == []
    assert swapped["claims"] == []
    assert "availability_value_mismatch" in swapped["rejected_claims"][0][
        "reasons"
    ]


def test_availability_comparison_accepts_shared_equal_value_predicate() -> None:
    evidence = "| 광휘 | 싱글: - | 매칭: - | 일반: 40개 | 하드: 90개 |"
    unit = {
        "evidence_ref": "E1",
        "chunk_id": "shared-value",
        "parent_document_id": "d1",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "title": "임의 레이드",
        "context_text": "광휘: 싱글 획득 불가, 매칭 획득 불가",
        "unit_kind": "table_row",
        "question_relevance_score": 1.0,
        "availability_subject": "광휘",
        "availability_values": {"싱글": False, "매칭": False},
    }

    def verify(text: str) -> dict:
        return verify_product_claim_output(
            {
                "mode": "answer",
                "claims": [{"text": text, "evidence_refs": ["E1"]}],
                "clarification": "",
            },
            question="임의 레이드 싱글과 매칭 보상 차이 알려줘.",
            evidence_units=[unit],
            chunks_by_id={"shared-value": {"display_text": evidence}},
            enable_availability_comparison=True,
        )

    unavailable = verify(
        "광휘는 싱글과 매칭 모두 획득 가능 난이도가 없습니다."
    )
    wrong_available = verify(
        "광휘는 싱글과 매칭 모두 획득 가능합니다."
    )

    assert len(unavailable["claims"]) == 1
    assert unavailable["rejected_claims"] == []
    assert wrong_available["claims"] == []
    assert "availability_value_mismatch" in wrong_available[
        "rejected_claims"
    ][0]["reasons"]


def test_availability_comparison_allows_omitted_trailing_qualifier() -> None:
    verified = _verify_availability(
        "임의의 주화는 일반에서 획득 불가, 하드에서 획득 가능하다.",
        enable_availability_comparison=True,
        subject="임의의 주화(1회 교환가능)",
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []


def test_availability_comparison_rejects_conflicting_qualifier() -> None:
    verified = _verify_availability(
        "임의의 주화(계정귀속)는 일반에서 획득 불가, 하드에서 획득 가능하다.",
        enable_availability_comparison=True,
        subject="임의의 주화(1회 교환가능)",
    )

    assert verified["claims"] == []
    assert "availability_subject_mismatch" in verified[
        "rejected_claims"
    ][0]["reasons"]


def test_availability_comparison_ignores_later_non_subject_parenthetical() -> None:
    verified = _verify_availability(
        "임의의 주화는 일반에서 획득 불가, 하드에서 획득 가능하며 "
        "1회 교환 가능(거래 후 계정귀속)이다.",
        enable_availability_comparison=True,
        subject="임의의 주화(1회 교환가능)",
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []


def test_availability_comparison_uses_first_predicate_before_trade_type() -> None:
    verified = _verify_availability(
        "임의의 원석은 일반 획득 불가, 하드 획득 가능하며 교환불가다.",
        enable_availability_comparison=True,
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []


def test_availability_comparison_allows_spaces_inside_numeric_labels() -> None:
    evidence = "| 임의의 항아리 | X | O |"
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "임의의 항아리는 제 1철광에서 획득할 수 없고, "
                        "제 3철광에서 획득할 수 있다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="임의 던전 제1철광과 제3철광의 보상 차이 알려줘.",
        evidence_units=[
            {
                "evidence_ref": "E1",
                "chunk_id": "numeric-label",
                "parent_document_id": "d1",
                "start_char": 0,
                "end_char": len(evidence),
                "text": evidence,
                "title": "임의 던전",
                "context_text": (
                    "표 열: | 항목 | 제1철광 | 제3철광 | > "
                    "열 해석: 임의의 항아리: 제1철광 획득 불가, "
                    "제3철광 획득 가능"
                ),
                "unit_kind": "table_row",
                "question_relevance_score": 1.0,
                "availability_subject": "임의의 항아리",
                "availability_values": {
                    "제1철광": False,
                    "제3철광": True,
                },
            }
        ],
        chunks_by_id={
            "numeric-label": {"display_text": evidence}
        },
        enable_availability_comparison=True,
    )

    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"] == []
