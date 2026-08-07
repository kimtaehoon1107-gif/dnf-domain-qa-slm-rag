from __future__ import annotations

from src.v3.requirement_value_shape import (
    apply_value_shape_veto,
    detect_value_shapes,
    normalize_expected_value_shape,
)


def _decision(text: str) -> dict:
    return {
        "requirement_id": "requirement_1",
        "status": "supported_exact",
        "spans": [{"chunk_id": "chunk_1", "text": text}],
        "unsupported_message": None,
    }


def test_percentage_does_not_accept_timestamp_digits() -> None:
    requirement = {
        "requirement_id": "requirement_1",
        "subject": "스트라이커(남)",
        "relation": "공격력_증가율",
        "value_type": "amount",
    }
    transformed, audit = apply_value_shape_veto(
        requirement, _decision("(16:30 패치 내용) 2026년 7월 16일")
    )
    assert audit["expected_kind"] == "percentage"
    assert audit["vetoed"]
    assert transformed["status"] == "unsupported"
    assert transformed["spans"] == []


def test_percentage_presence_is_not_positive_entailment() -> None:
    requirement = {
        "requirement_id": "requirement_1",
        "relation": "공격력_증가율",
        "value_type": "amount",
    }
    transformed, audit = apply_value_shape_veto(
        requirement, _decision("기본 공격력이 11.7% 증가합니다.")
    )
    assert not audit["vetoed"]
    assert audit["support_semantics"] == "absence_only_veto_never_positive_entailment"
    assert transformed["status"] == "supported_exact"


def test_calendar_dates_are_masked_before_duration_and_count_detection() -> None:
    shapes = detect_value_shapes("2026년 7월 16일 16:30 점검")
    assert "calendar_date" in shapes
    assert "clock_or_datetime" in shapes
    assert "duration" not in shapes
    assert "count_value" not in shapes


def test_duration_and_cost_resource_quantity_are_supported_shapes() -> None:
    assert "duration" in detect_value_shapes("마지막 사용 후 15일 동안 보관")
    shapes = detect_value_shapes("광휘의 소울 25개와 125,000골드")
    assert "cost_value" in shapes
    assert "currency" in shapes
    assert "quantity" in shapes


def test_dated_range_counts_as_a_duration() -> None:
    assert "duration" in detect_value_shapes("판매기간: 06.25 ~ 07.30")
    assert "duration" in detect_value_shapes("2026.06.25 ~ 2026.07.30")
    requirement = {
        "requirement_id": "requirement_1",
        "subject": "7월 이달의 아이템",
        "relation": "판매 기간",
        "value_type": "duration",
    }
    _, audit = apply_value_shape_veto(
        requirement, _decision("판매기간: 06.25 ~ 07.30")
    )
    assert not audit["vetoed"]


def test_unbounded_term_counts_as_a_duration() -> None:
    requirement = {
        "requirement_id": "requirement_1",
        "subject": "타인_결제수단_도용",
        "relation": "첫_이용제한",
        "value_type": "duration",
    }
    _, audit = apply_value_shape_veto(
        requirement,
        _decision("| 결제도용 가해 (타인의 결제 수단 무단도용) | 영구 게임 이용제한 |"),
    )
    assert not audit["vetoed"]


def test_a_single_date_is_still_not_a_duration() -> None:
    assert "duration" not in detect_value_shapes("2026년 7월 30일 06시에 삭제됩니다")


def test_ambiguous_text_or_amount_has_no_veto_contract() -> None:
    text_requirement = {"relation": "주의사항", "value_type": "text"}
    amount_requirement = {"relation": "unknown_amount", "value_type": "amount"}
    assert not normalize_expected_value_shape(text_requirement)["veto_enabled"]
    assert not normalize_expected_value_shape(amount_requirement)["veto_enabled"]
    transformed, audit = apply_value_shape_veto(text_requirement, _decision("제목만"))
    assert not audit["vetoed"]
    assert transformed["status"] == "supported_exact"
