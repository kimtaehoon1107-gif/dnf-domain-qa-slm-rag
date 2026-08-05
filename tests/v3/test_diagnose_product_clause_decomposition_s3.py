from src.v3.diagnose_product_clause_decomposition_s3 import (
    _arm_requirement_queries,
    _overlaps,
    _reservation_assignments,
    _value_decreases_from_m3,
)


def test_explicit_fallback_changes_only_when_kiwi_is_empty() -> None:
    failed = _arm_requirement_queries(
        "버그를 발견하면 어디에 제보해야 하고, 답변 기한은 며칠이야?"
    )
    assert failed["A_current"] is None
    assert len(failed["B_explicit_fallback"] or []) == 2

    control = _arm_requirement_queries(
        "점검은 몇 시에 시작하고 서버는 어느 날 다시 열릴 예정이었어?"
    )
    assert control["A_current"] == control["B_explicit_fallback"]


def test_overlaps_requires_same_chunk_and_character_overlap() -> None:
    pack = [
        {
            "chunk_id": "chunk-1",
            "start_char": 20,
            "end_char": 40,
        }
    ]
    assert _overlaps(
        pack,
        [{"chunk_id": "chunk-1", "start_char": 30, "end_char": 50}],
    )
    assert not _overlaps(
        pack,
        [{"chunk_id": "chunk-2", "start_char": 30, "end_char": 50}],
    )
    assert not _overlaps(
        pack,
        [{"chunk_id": "chunk-1", "start_char": 40, "end_char": 50}],
    )


def test_a6_7_reservation_shadow_uses_two_explicit_clauses() -> None:
    arms = _arm_requirement_queries(
        "6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 "
        "줄었고, 질풍 개화 옵션의 기본 쿨타임은 몇 초에서 몇 초로 "
        "바뀌었어?"
    )
    assert arms["A_current"] is None
    assert arms["B_explicit_fallback"] == [
        "6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 줄었고",
        "질풍 개화 옵션의 기본 쿨타임은 몇 초에서 몇 초로 바뀌었어",
    ]


def test_value_decrease_gate_separates_descriptive_diagnostics() -> None:
    requirements = [
        {
            "requirement_id": "mold_trade_types",
            "value_presence": "value_present_none",
            "required_values": ["교환 가능"],
            "assigned_units": [],
        },
        {
            "requirement_id": "numeric_value",
            "value_presence": "value_present_partial",
            "required_values": ["10", "20"],
            "assigned_units": [],
        },
    ]
    m3 = {
        "mold_trade_types": {"value_presence": "value_present_partial"},
        "numeric_value": {"value_presence": "value_present_full"},
    }
    decreases = _value_decreases_from_m3("A6-17", requirements, m3)
    assert [row["gate_kind"] for row in decreases] == [
        "descriptive_diagnostic",
        "numeric_date_time_currency",
    ]


def test_reservation_assignments_require_explicit_question_focus() -> None:
    assignments = _reservation_assignments(
        [
            {
                "evidence_ref": "E1",
                "chunk_id": "chunk-1",
                "start_char": 10,
                "end_char": 20,
                "text": "첫 근거",
                "question_focus": "첫 절",
            },
            {
                "evidence_ref": "E2",
                "chunk_id": "chunk-2",
                "start_char": 30,
                "end_char": 40,
                "text": "미예약 근거",
                "question_focus": "",
            },
        ]
    )
    assert list(assignments) == ["첫 절"]
    assert assignments["첫 절"][0]["evidence_ref"] == "E1"
