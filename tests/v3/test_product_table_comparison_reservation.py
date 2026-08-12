from src.v3.product_table_comparison import (
    build_server_availability_output,
    build_server_content_kind_output,
    build_table_comparison_reservation,
    comparison_labels,
    merge_table_comparison_reservation,
)


def _chunk(index: int, text: str, *, start: int) -> dict:
    return {
        "chunk_id": f"c{index}",
        "chunk_index": index,
        "parent_document_id": "p1",
        "start_offset": start,
        "display_text": text,
        "default_exposure": True,
        "status": "current",
    }


def test_comparison_labels_follow_question_surface() -> None:
    assert set(
        comparison_labels("임의 레이드 하드와 일반의 보상 차이 알려줘")
    ) == {"일반", "하드"}
    assert comparison_labels("임의 레이드 보상 알려줘") == []


def test_comparison_labels_keep_numeric_compounds() -> None:
    assert comparison_labels(
        "아포칼립스 안티엔바이 매칭과 2단계의 보상 차이 알려줘"
    ) == ["매칭", "2단계"]
    assert comparison_labels(
        "피 흘리는 철광 제 1철광과 제 3철광의 보상 차이 알려줘"
    ) == ["제1철광", "제3철광"]
    assert comparison_labels(
        "어둑섬 1단계와 해방의 보상 차이 알려줘"
    ) == ["1단계", "해방"]


def test_reservation_resolves_multiword_and_qualified_headers() -> None:
    chunks = [
        _chunk(
            1,
            """[TABLE]
| 보상 | 일반 몬스터 | 보스 몬스터 |
| 재료 A | - | O |
[/TABLE]
[TABLE]
| 장비 | 레전더리 | 태초 |
| 무기 | O | X |
[/TABLE]
[TABLE]
| 보상 | 1단계 | 극 |
| 열쇠 | O | - |
[/TABLE]""",
            start=0,
        )
    ]
    documents = {
        "p1": {
            "source_id": "guide",
            "title": "임의 가이드",
            "status": "current",
        }
    }
    common = {
        "parent_ids": ["p1"],
        "chunks_by_parent": {"p1": chunks},
        "documents_by_id": documents,
        "temporal_by_document": {},
        "score_pairs": lambda pairs: [1.0] * len(pairs),
    }

    monster = build_table_comparison_reservation(
        "광휘의 순례 일반 몬스터와 보스 몬스터의 드랍 차이 알려줘",
        **common,
    )
    rarity = build_table_comparison_reservation(
        "보이드 소울 추출 레전더리와 태초 장비의 차이 알려줘",
        **common,
    )
    extreme = build_table_comparison_reservation(
        "깨어난 숲 1단계와 극 난이도의 보상 차이 알려줘",
        **common,
    )

    assert monster[0]["availability_values"] == {
        "일반 몬스터": False,
        "보스 몬스터": True,
    }
    assert rarity[0]["availability_values"] == {
        "레전더리": True,
        "태초": False,
    }
    assert extreme[0]["availability_values"] == {
        "1단계": True,
        "극": False,
    }

    topic_question = build_table_comparison_reservation(
        "임의 가이드 재료 A 획득 여부는 일반 몬스터와 보스 몬스터에서 "
        "어떤 차이가 있어?",
        **common,
    )

    assert topic_question[0]["availability_values"] == {
        "일반 몬스터": False,
        "보스 몬스터": True,
    }


def test_labeled_dash_values_become_availability_metadata() -> None:
    chunks = [
        _chunk(
            1,
            """[TABLE]
| 보상 | 싱글 | 매칭 | 일반 | 하드 |
| 광휘 | 싱글: - | 매칭: - | 일반: 40개 | 하드: 90개 |
[/TABLE]""",
            start=0,
        )
    ]
    units = build_table_comparison_reservation(
        "임의 레이드 싱글과 매칭의 보상 차이 알려줘",
        parent_ids=["p1"],
        chunks_by_parent={"p1": chunks},
        documents_by_id={
            "p1": {
                "source_id": "guide",
                "title": "임의 레이드",
                "status": "current",
            }
        },
        temporal_by_document={},
        score_pairs=lambda pairs: [1.0] * len(pairs),
    )

    assert units[0]["availability_subject"] == "광휘"
    assert units[0]["availability_values"] == {
        "싱글": False,
        "매칭": False,
    }
    assert units[0]["model_text"] == "| 광휘 | 싱글: - | 매칭: - |"


def test_availability_context_keeps_each_table_introduction() -> None:
    chunks = [
        _chunk(
            1,
            """확정적으로 다음 아이템을 획득할 수 있습니다.
[TABLE]
| 보상 | 기억의 숲 탐사 | 핀더의 정원 탐사 |
| 에픽 소울 | - | O |
[/TABLE]
정해진 확률로 다음 아이템을 획득할 수 있습니다.
[TABLE]
| 보상 | 기억의 숲 탐사 | 핀더의 정원 탐사 |
| 에픽 소울 | O | O |
[/TABLE]""",
            start=0,
        )
    ]
    units = build_table_comparison_reservation(
        "임의 가이드 확정 보상 에픽 소울은 기억의 숲 탐사와 "
        "핀더의 정원 탐사에서 어떤 차이가 있어?",
        parent_ids=["p1"],
        chunks_by_parent={"p1": chunks},
        documents_by_id={
            "p1": {
                "source_id": "guide",
                "title": "임의 가이드",
                "status": "current",
            }
        },
        temporal_by_document={},
        score_pairs=lambda pairs: [1.0] * len(pairs),
    )

    assert [unit["table_intro"] for unit in units] == [
        "확정적으로 다음 아이템을 획득할 수 있습니다."
    ]
    assert all(
        unit["table_intro"] in unit["context_text"] for unit in units
    )

    ambiguous = build_table_comparison_reservation(
        "임의 가이드 에픽 소울은 기억의 숲 탐사와 "
        "핀더의 정원 탐사에서 어떤 차이가 있어?",
        parent_ids=["p1"],
        chunks_by_parent={"p1": chunks},
        documents_by_id={
            "p1": {
                "source_id": "guide",
                "title": "임의 가이드",
                "status": "current",
            }
        },
        temporal_by_document={},
        score_pairs=lambda pairs: [1.0] * len(pairs),
    )

    assert {unit["table_intro"] for unit in ambiguous} == {
        "확정적으로 다음 아이템을 획득할 수 있습니다.",
        "정해진 확률로 다음 아이템을 획득할 수 있습니다.",
    }


def test_reservation_combines_quantity_and_cross_chunk_availability() -> None:
    chunks = [
        _chunk(
            1,
            """[TABLE]
| 아이템 명 | 획득 가능 난이도 | 교환 타입 |
| 아이템 명 | 싱글 | 매칭 | 일반 | 하드 | 교환 타입 |
| 원석 | - | - | - | O | 교환불가 |
| 재료 A | 싱글: - | 매칭: - | 일반: 40개 | 하드: 90개 |
| 재료 B | 싱글: 100개 | 매칭: 100개 | 일반: 200개 | 하드: 200개 |""",
            start=0,
        ),
        _chunk(
            2,
            """| 교환 주화 | - | - | - | O | 1회 교환가능 |
| 공통 보상 | O | O | O | O | 교환불가 |
[/TABLE]""",
            start=200,
        ),
    ]
    documents = {
        "p1": {
            "source_id": "guide",
            "title": "임의 레이드",
            "status": "current",
        }
    }

    units = build_table_comparison_reservation(
        "임의 레이드 하드와 일반의 보상 차이 알려줘",
        parent_ids=["p1"],
        chunks_by_parent={"p1": chunks},
        documents_by_id=documents,
        temporal_by_document={},
        score_pairs=lambda pairs: [1.0] * len(pairs),
    )

    assert {unit.get("availability_subject") for unit in units} >= {
        "원석",
        "교환 주화",
    }
    assert any("일반: 40개" in unit["text"] for unit in units)
    assert any("일반: 200개" in unit["text"] for unit in units)
    assert not any("공통 보상" in unit["text"] for unit in units)
    assert len(units) == 4
    assert {unit["question_focus"] for unit in units} == {
        "임의 레이드 하드와 일반의 보상 차이 알려줘"
    }

    same_item = build_table_comparison_reservation(
        "임의 레이드 공통 보상 하드와 일반의 획득 가능 여부 차이 알려줘",
        parent_ids=["p1"],
        chunks_by_parent={"p1": chunks},
        documents_by_id=documents,
        temporal_by_document={},
        score_pairs=lambda pairs: [1.0] * len(pairs),
    )

    assert any("공통 보상" in unit["text"] for unit in same_item)
    assert next(
        unit["availability_values"]
        for unit in same_item
        if "공통 보상" in unit["text"]
    ) == {"하드": True, "일반": True}


def test_merge_keeps_reservations_and_eight_unit_cap() -> None:
    reserved = [
        {
            "chunk_id": "r1",
            "start_char": 0,
            "end_char": 4,
            "text": "예약 1",
        },
        {
            "chunk_id": "r2",
            "start_char": 0,
            "end_char": 4,
            "text": "예약 2",
        },
    ]
    semantic = [
        {
            "chunk_id": f"s{index}",
            "start_char": 0,
            "end_char": 4,
            "text": f"의미 {index}",
        }
        for index in range(10)
    ]

    merged = merge_table_comparison_reservation(reserved, semantic)

    assert len(merged) == 8
    assert [row["text"] for row in merged[:2]] == ["예약 1", "예약 2"]
    assert [row["evidence_ref"] for row in merged] == [
        f"E{index}" for index in range(1, 9)
    ]


def test_server_availability_output_renders_pure_two_axis_rows() -> None:
    output = build_server_availability_output(
        [
            {
                "evidence_ref": "E1",
                "unit_kind": "table_row",
                "parent_document_id": "p1",
                "availability_subject": "어둠에 물든 침광의 원석",
                "availability_values": {"하드": True, "일반": False},
            },
            {
                "evidence_ref": "E2",
                "unit_kind": "table_row",
                "parent_document_id": "p1",
                "availability_subject": "경매 주화",
                "availability_values": {"하드": True, "일반": False},
            },
        ]
    )

    assert output == {
        "mode": "answer",
        "claims": [
            {
                "text": (
                    "어둠에 물든 침광의 원석: "
                    "하드 획득 가능, 일반 획득 불가."
                ),
                "evidence_refs": ["E1"],
            },
            {
                "text": "경매 주화: 하드 획득 가능, 일반 획득 불가.",
                "evidence_refs": ["E2"],
            },
        ],
        "clarification": "",
    }


def test_server_availability_output_rejects_quantity_or_mixed_pack() -> None:
    assert build_server_availability_output(
        [
            {
                "evidence_ref": "E1",
                "unit_kind": "table_row",
                "parent_document_id": "p1",
                "availability_subject": "원석",
                "availability_values": {"하드": True, "일반": False},
            },
            {
                "evidence_ref": "E2",
                "unit_kind": "table_row",
                "parent_document_id": "p1",
                "text": "| 광휘의 잔재 | 하드: 90개 | 일반: 40개 |",
            },
        ]
    ) is None


def test_server_availability_output_rejects_duplicate_subject_context() -> None:
    assert build_server_availability_output(
        [
            {
                "evidence_ref": "E1",
                "unit_kind": "table_row",
                "parent_document_id": "p1",
                "availability_subject": "에픽 소울",
                "availability_values": {"탐사 A": True, "탐사 B": False},
            },
            {
                "evidence_ref": "E2",
                "unit_kind": "table_row",
                "parent_document_id": "p1",
                "availability_subject": "에픽 소울",
                "availability_values": {"탐사 A": False, "탐사 B": True},
            },
        ]
    ) is None


def test_server_content_kind_output_renders_one_complete_category_row() -> None:
    output = build_server_content_kind_output(
        "미카엘라 레이드 종류 뭐뭐가 있어?",
        [
            {
                "evidence_ref": "E1",
                "unit_kind": "table_row",
                "title": "무너진 성자 미카엘라",
                "text": "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |",
                "complete_category": True,
            }
        ],
    )

    assert output == {
        "mode": "answer",
        "claims": [
            {
                "text": (
                    "무너진 성자 미카엘라의 난이도는 "
                    "싱글, 매칭, 일반, 하드로 구분됩니다."
                ),
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }


def test_server_content_kind_output_rejects_multiple_matching_rows() -> None:
    unit = {
        "unit_kind": "table_row",
        "title": "문서",
        "text": "| 난이도 | 싱글 | 일반 |",
        "complete_category": True,
    }
    assert build_server_content_kind_output(
        "레이드 종류 알려줘",
        [
            {**unit, "evidence_ref": "E1"},
            {**unit, "evidence_ref": "E2"},
        ],
    ) is None
