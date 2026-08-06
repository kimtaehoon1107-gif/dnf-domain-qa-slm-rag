from __future__ import annotations

from tests.v3.test_typed_evidence_ref import _ref_containing, _units

from src.v3.typed_evidence_ref import verify_typed_requirement_selection


def test_explicit_question_count_repairs_supported_delimited_entity_list() -> None:
    first = "[7월]클론 레어 아바타(교환불가) 풀세트 상자"
    second = "[7월]찬란한 엠블렘(계정귀속) 풀세트 선택상자"
    text = f"사용 시 {first}, {second}를 획득합니다."
    chunks_by_id, units, _, _ = _units(
        text,
        title="보상 상자 묶음",
    )
    evidence_ref = next(iter(units))

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "obtained_items",
            "status": "supported",
            "value_type": "entity_list",
            "value": f"{first}, {second}",
            "evidence_refs": [evidence_ref],
        },
        requirement={
            "requirement_id": "obtained_items",
            "subject": "보상 상자 묶음",
            "relation": "obtained_items",
            "value_type": "entity_list",
        },
        question_time_scope="current",
        question_text="보상 묶음을 사용하면 얻는 두 상자 이름을 알려줘.",
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )

    assert decision["status"] == "supported_exact", audit["failure_reasons"]
    assert decision["answer"] == f"{first}, {second}"
    assert audit["normalized_value"] == [first, second]
    assert (
        audit["value_shape_repair"]
        == "explicit_count_delimited_string"
    )
    assert audit["cardinality_validation_state"] == "count_match"


def test_delimited_entity_list_without_explicit_count_stays_blocked() -> None:
    text = "무한 올빼미는 마을, 던전에서 사용할 수 있습니다."
    chunks_by_id, units, _, _ = _units(text, title="무한 올빼미")
    evidence_ref = next(iter(units))

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "usable_locations",
            "status": "supported",
            "value_type": "entity_list",
            "value": "마을, 던전",
            "evidence_refs": [evidence_ref],
        },
        requirement={
            "requirement_id": "usable_locations",
            "subject": "무한 올빼미",
            "relation": "usable_locations",
            "value_type": "entity_list",
        },
        question_time_scope="current",
        question_text="무한 올빼미는 어디에서 사용할 수 있어?",
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )

    assert decision["status"] == "unsupported"
    assert "entity_list_value_shape_mismatch" in audit["failure_reasons"]


def test_document_title_binds_dated_maintenance_time_row() -> None:
    row = "| 시간 | 04:30 ~ 10:00 |"
    chunks_by_id, units, _, _ = _units(
        f"### 공지사항\n{row}",
        title="4/2(목) 정기점검 안내",
        published_at="2026-03-31",
    )
    evidence_ref = _ref_containing(units, row)

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "maintenance_time",
            "status": "supported",
            "value_type": "time_range",
            "value": "04:30/10:00",
            "evidence_refs": [evidence_ref],
        },
        requirement={
            "requirement_id": "maintenance_time",
            "subject": "2026년 4월 2일 정기점검",
            "relation": "maintenance_time",
            "value_type": "date_range",
        },
        question_time_scope="historical",
        question_text="2026년 4월 2일 정기점검은 몇 시부터 몇 시까지였어?",
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )

    assert decision["status"] == "supported_exact", audit["failure_reasons"]
    assert decision["answer"] == "4시 30분 ~ 10시"
    assert audit["failure_reasons"] == []


def test_processing_duration_requires_the_complete_range() -> None:
    duration_line = (
        "유형에 따라 3~5일 정도 소요될 수 있는 점 참고 부탁드립니다."
    )
    evidence = (
        "이용제한 재조사를 위해 1:1문의를 접수한 경우\n"
        f"{duration_line}"
    )
    chunks_by_id, units, _, _ = _units(
        evidence,
        title="[게임이용제한] 이용 제한 해제를 어떻게 하나요?",
    )
    evidence_ref = _ref_containing(units, duration_line)
    requirement = {
        "requirement_id": "processing_days",
        "subject": "게임 이용제한 재조사",
        "relation": "processing_days",
        "value_type": "number",
    }

    correct, correct_audit = verify_typed_requirement_selection(
        {
            "requirement_id": "processing_days",
            "status": "supported",
            "value_type": "duration_range",
            "value": "3일/5일",
            "evidence_refs": [evidence_ref],
        },
        requirement=requirement,
        question_time_scope="current",
        question_text="게임 이용제한 재조사 처리에는 며칠이 걸려?",
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )
    stale_endpoint, stale_audit = verify_typed_requirement_selection(
        {
            "requirement_id": "processing_days",
            "status": "supported",
            "value_type": "number",
            "value": 5,
            "evidence_refs": [evidence_ref],
        },
        requirement=requirement,
        question_time_scope="current",
        question_text="게임 이용제한 재조사 처리에는 며칠이 걸려?",
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )

    assert correct["status"] == "supported_exact", correct_audit[
        "failure_reasons"
    ]
    assert correct["answer"] == "3~5일"
    assert stale_endpoint["status"] == "unsupported"
    assert "value_type_mismatch" in stale_audit["failure_reasons"]
    assert "typed_value_not_supported_by_evidence" in stale_audit[
        "failure_reasons"
    ]


def test_mobile_otp_subject_matches_official_neople_otp_name() -> None:
    evidence = "정지된 이후에도 OTP 이용이 가능합니다."
    chunks_by_id, units, _, _ = _units(
        evidence,
        title="[네오플OTP] 휴대폰이 정지되면 OTP를 사용할 수 없나요?",
    )
    evidence_ref = _ref_containing(units, evidence)

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "otp_after_suspension",
            "status": "supported",
            "value_type": "boolean",
            "value": "true",
            "evidence_refs": [evidence_ref],
        },
        requirement={
            "requirement_id": "otp_after_suspension",
            "subject": "모바일 OTP",
            "relation": "usable_after_phone_suspension",
            "value_type": "boolean",
        },
        question_time_scope="current",
        question_text=(
            "휴대폰이 정지된 후에도 모바일 OTP를 사용할 수 있어?"
        ),
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )

    assert decision["status"] == "supported_exact", audit["failure_reasons"]
    assert decision["answer"] == "예"
    assert audit["value_shape_repair"] == "legacy_boolean_string"


def test_conditional_evidence_expands_to_adjacent_conclusion() -> None:
    condition = (
        "다만, 다른 계정으로의 이동(트레이드, 경매장, "
        "아바타마켓 등)이 발생하면"
    )
    conclusion = (
        "교환불가 타입으로 변경되니 아바타 이동/거래 시 "
        "유의 부탁 드립니다."
    )
    chunks_by_id, units, _, _ = _units(
        f"{condition}\n{conclusion}",
        title=(
            "[게임 이용] 히든 레어 아바타를 이동시킬 경우 "
            "교환이 불가능한가요?"
        ),
    )
    condition_ref = _ref_containing(units, condition)
    conclusion_ref = _ref_containing(units, conclusion)

    decision, audit = verify_typed_requirement_selection(
        {
            "requirement_id": "other_account_trade_type",
            "status": "supported",
            "value_type": "boolean",
            "value": True,
            "evidence_refs": [condition_ref],
        },
        requirement={
            "requirement_id": "other_account_trade_type",
            "subject": "히든 레어 아바타 다른 계정 이동",
            "relation": "changes_to_untradeable",
            "value_type": "boolean",
        },
        question_time_scope="current",
        question_text=(
            "히든 레어 아바타를 다른 계정으로 넘기면 "
            "교환불가로 바뀌어?"
        ),
        evidence_units_by_ref=units,
        chunks_by_id=chunks_by_id,
        as_of="2026-07-22",
    )

    assert decision["status"] == "supported_exact", audit["failure_reasons"]
    assert {
        citation["evidence_ref"] for citation in decision["citations"]
    } == {condition_ref, conclusion_ref}
