from __future__ import annotations

from src.v3.grounded_answer_generator import (
    UNCONFIRMABLE_MESSAGE,
    apply_table_value_shape_gate,
    build_generation_request,
    compose_backbone_answer,
    compose_answer,
    extract_factual_tokens,
    partition_requirements,
    table_value_spans,
    verify_generated_answer,
)


def _requirement(relation: str, value_type: str = "amount") -> dict:
    return {
        "requirement_id": f"req_{relation}",
        "subject": "염색제거약",
        "relation": relation,
        "value_type": value_type,
    }


def _decision(status: str, *texts: str) -> dict:
    return {
        "status": status,
        "spans": [{"span_id": f"s{i}", "text": text} for i, text in enumerate(texts)],
    }


def test_requirement_without_the_requested_value_is_never_generated() -> None:
    # "가격" asks for a cost value; the cited span is a heading with no amount.
    requirements = [_requirement("가격")]
    decisions = [_decision("supported_exact", "상점 판매가가 존재하며 교환가능 아이템입니다.")]
    partition = partition_requirements(requirements, decisions)
    assert partition["generatable"] == []
    assert len(partition["unconfirmable"]) == 1
    assert partition["unconfirmable"][0]["reason"] == "value_shape_absent_in_cited_spans"
    assert partition["unconfirmable"][0]["message"] == UNCONFIRMABLE_MESSAGE


def test_requirement_with_the_value_is_generatable() -> None:
    requirements = [_requirement("가격")]
    decisions = [_decision("supported_exact", "| 염색제거약 | 100,000 골드 | 계정귀속 |")]
    partition = partition_requirements(requirements, decisions)
    assert len(partition["generatable"]) == 1
    assert partition["unconfirmable"] == []


def test_price_relation_rejects_unrelated_item_quantities() -> None:
    requirement = {
        "requirement_id": "req_price",
        "subject": "\uc11c\uc57d \uacb0\uc815",
        "relation": "price",
        "value_type": "amount",
    }
    checked, audit = apply_table_value_shape_gate(
        requirement,
        _decision(
            "supported_exact",
            "\uc131\ucde8 \ubcf4\uc0c1 \uc0c1\uc790 1\uac1c\uc640 10\uac1c\ub97c "
            "\uc9c0\uae09\ud569\ub2c8\ub2e4.",
        ),
        [],
    )

    assert checked["status"] == "unsupported"
    assert audit["cost_relation_vetoed"] is True


def test_price_relation_accepts_explicit_cost_context_or_currency() -> None:
    requirement = {
        "requirement_id": "req_price",
        "subject": "\uc11c\uc57d \uacb0\uc815",
        "relation": "price",
        "value_type": "amount",
    }

    contextual, contextual_audit = apply_table_value_shape_gate(
        requirement,
        _decision(
            "supported_exact",
            "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \ube44\uc6a9\uc740 "
            "\uad11\ud718\uc758 \uc18c\uc6b8 25\uac1c\uc785\ub2c8\ub2e4.",
        ),
        [],
    )
    currency, currency_audit = apply_table_value_shape_gate(
        requirement,
        _decision(
            "supported_exact",
            "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4\uc5d0 "
            "125,000\uace8\ub4dc\uac00 "
            "\ud544\uc694\ud569\ub2c8\ub2e4.",
        ),
        [],
    )

    assert contextual["status"] == "supported_exact"
    assert contextual_audit["cost_relation_vetoed"] is False
    assert currency["status"] == "supported_exact"
    assert currency_audit["cost_relation_vetoed"] is False


def test_price_relation_requires_subject_in_the_table_entity_cell() -> None:
    requirement = {
        "requirement_id": "req_price",
        "subject": "\uace8\ub4dc \ucf54\uc778",
        "relation": "price",
        "value_type": "amount",
    }
    wrong, wrong_audit = apply_table_value_shape_gate(
        requirement,
        _decision(
            "supported_exact",
            "| \ud648\uc1fc\ud551 \uacf5\uad6c\uc138\ud2b8 | "
            "18 \uace8\ub4dc \ucf54\uc778 | \uad50\ud658\ubd88\uac00 |",
        ),
        [],
    )
    correct, correct_audit = apply_table_value_shape_gate(
        requirement,
        _decision(
            "supported_exact",
            "| \uace8\ub4dc \ucf54\uc778 10\uac1c | "
            "1,500\uc138\ub77c | \uad50\ud658\uac00\ub2a5 |",
        ),
        [],
    )

    assert wrong["status"] == "unsupported"
    assert wrong_audit["cost_subject_alignment_vetoed"] is True
    assert correct["status"] == "supported_exact"
    assert correct_audit["cost_subject_alignment_vetoed"] is False


def test_unsupported_requirement_is_not_generated() -> None:
    requirements = [_requirement("가격")]
    decisions = [_decision("unsupported")]
    partition = partition_requirements(requirements, decisions)
    assert partition["generatable"] == []
    assert partition["unconfirmable"][0]["reason"] == "unsupported"


def test_generation_request_contains_no_gold_or_chunk_payload() -> None:
    requirements = [_requirement("가격")]
    decisions = [_decision("supported_exact", "| 염색제거약 | 100,000 골드 | 계정귀속 |")]
    partition = partition_requirements(requirements, decisions)
    request = build_generation_request("염색제거약 가격 알려줘", partition["generatable"])
    assert "100,000 골드" in request["user"]
    for forbidden in ("evidence_groups", "acceptable_chunk_ids", "gold_answer", "chunk_sha256"):
        assert forbidden not in request["user"]


def test_extract_factual_tokens_finds_numbers_dates_and_times() -> None:
    tokens = extract_factual_tokens("가격은 100,000 골드이고 2026년 8월 27일 06시에 삭제되며 20% 증가합니다.")
    joined = " ".join(tokens)
    assert "100,000 골드" in joined
    assert "20%" in joined
    assert any("2026" in token for token in tokens)


def test_hallucinated_number_fails_verification() -> None:
    generatable = [
        {"requirement_index": 1, "spans": [{"text": "| 염색제거약 | 100,000 골드 | 계정귀속 |"}]}
    ]
    result = verify_generated_answer("염색제거약은 150,000 골드입니다.", generatable)
    assert result["verified"] is False
    assert any("150,000" in token for token in result["unsupported_tokens"])


def test_selected_table_value_tokens_must_all_appear_in_the_answer() -> None:
    generatable = [
        {
            "requirement_index": 1,
            "spans": [
                {
                    "text": "\uc720\ub2c8\ud06c \u00b7 \uad11\ud718\uc758 \uc18c\uc6b8 = 25\uac1c",
                    "value": "25\uac1c",
                    "evidence_kind": "table_attribute_value",
                },
                {
                    "text": "\uc720\ub2c8\ud06c \u00b7 \uace8\ub4dc = 125,000\uace8\ub4dc",
                    "value": "125,000\uace8\ub4dc",
                    "evidence_kind": "table_attribute_value",
                },
            ],
        }
    ]

    result = verify_generated_answer(
        "\uad11\ud718\uc758 \uc18c\uc6b8 25\uac1c\uac00 \ud544\uc694\ud569\ub2c8\ub2e4.",
        generatable,
    )

    assert result["verified"] is False
    assert result["missing_required_tokens"] == ["125,000\uace8\ub4dc"]


def test_answer_using_only_cited_numbers_passes_verification() -> None:
    generatable = [
        {"requirement_index": 1, "spans": [{"text": "| 염색제거약 | 100,000 골드 | 계정귀속 |"}]}
    ]
    result = verify_generated_answer("염색제거약의 가격은 100,000 골드입니다.", generatable)
    assert result["verified"] is True
    assert result["unsupported_tokens"] == []


def test_verification_ignores_whitespace_differences() -> None:
    generatable = [{"requirement_index": 1, "spans": [{"text": "100,000 골드"}]}]
    assert verify_generated_answer("가격은 100,000골드입니다.", generatable)["verified"] is True


def test_compose_falls_back_when_model_invents_a_number() -> None:
    requirements = [_requirement("가격")]
    decisions = [_decision("supported_exact", "| 염색제거약 | 100,000 골드 | 계정귀속 |")]
    result = compose_answer(
        question="염색제거약 가격 알려줘",
        requirements=requirements,
        decisions=decisions,
        generate=lambda request: "염색제거약은 9,999 골드입니다.",
    )
    assert result["mode"] == "extractive_fallback"
    assert result["used_generated_text"] is False
    assert result["answer_text"] == ""


def test_compose_uses_generated_text_when_grounded() -> None:
    requirements = [_requirement("가격")]
    decisions = [_decision("supported_exact", "| 염색제거약 | 100,000 골드 | 계정귀속 |")]
    result = compose_answer(
        question="염색제거약 가격 알려줘",
        requirements=requirements,
        decisions=decisions,
        generate=lambda request: "염색제거약의 가격은 100,000 골드입니다.",
    )
    assert result["mode"] == "generated"
    assert result["used_generated_text"] is True
    assert result["verification"]["verified"] is True


def test_compose_abstains_and_never_calls_the_model() -> None:
    calls: list[dict] = []

    def _generate(request: dict) -> str:
        calls.append(request)
        return "무엇이든"

    requirements = [_requirement("가격")]
    decisions = [_decision("supported_exact", "상점 판매가가 존재하며 교환가능 아이템입니다.")]
    result = compose_answer(
        question="염색제거약 가격 알려줘",
        requirements=requirements,
        decisions=decisions,
        generate=_generate,
    )
    assert result["mode"] == "abstain"
    assert result["answer_text"] == UNCONFIRMABLE_MESSAGE
    assert calls == []


def _oath_table_view() -> dict:
    return {
        "table_id": "table_oath",
        "table_subject": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4",
        "caption": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \ube44\uc6a9\uc740 "
        "\uc544\ub798\uc640 \uac19\uc2b5\ub2c8\ub2e4.",
        "attributes": [
            "\uad11\ud718\uc758 \uc18c\uc6b8",
            "\uc0c1\uae09 \uc6d0\uc18c \uacb0\uc815",
            "\uc21c\ub840\uc758 \uc778\uc7a5 / \uace8\ub4dc",
            "\uc194\ub9ac\ub4dc \uc18c\uc6b8",
        ],
        "rows": [
            {
                "row_id": "row_unique",
                "subject": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \uc720\ub2c8\ud06c",
                "source_chunk_id": "chunk_oath",
                "start_offset": 10,
                "end_offset": 60,
                "exact_row_text": "| unique | 25 | 36 | 25 or 125000 | 1 |",
                "values": {
                    "\uad11\ud718\uc758 \uc18c\uc6b8": "25\uac1c",
                    "\uc0c1\uae09 \uc6d0\uc18c \uacb0\uc815": "36\uac1c",
                    "\uc21c\ub840\uc758 \uc778\uc7a5 / \uace8\ub4dc": "\uc21c\ub840\uc758 \uc778\uc7a5 25\uac1c or 125,000\uace8\ub4dc",
                    "\uc194\ub9ac\ub4dc \uc18c\uc6b8": "1\uac1c",
                },
            },
            {
                "row_id": "row_legendary",
                "subject": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \ub808\uc804\ub354\ub9ac",
                "source_chunk_id": "chunk_oath",
                "start_offset": 61,
                "end_offset": 120,
                "exact_row_text": "| legendary | 60 | 180 | 250 or 1250000 | 65 |",
                "values": {
                    "\uad11\ud718\uc758 \uc18c\uc6b8": "60\uac1c",
                    "\uc0c1\uae09 \uc6d0\uc18c \uacb0\uc815": "180\uac1c",
                    "\uc21c\ub840\uc758 \uc778\uc7a5 / \uace8\ub4dc": "\uc21c\ub840\uc758 \uc778\uc7a5 250\uac1c or 1,250,000\uace8\ub4dc",
                    "\uc194\ub9ac\ub4dc \uc18c\uc6b8": "65\uac1c",
                },
            },
        ],
    }


def _oath_requirement() -> dict:
    return {
        "requirement_id": "req_oath_unique_cost",
        "subject": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \uc720\ub2c8\ud06c",
        "relation": "\uac00\uaca9",
        "value_type": "amount",
    }


def test_table_values_are_bound_to_attributes_for_the_matching_row() -> None:
    spans = table_value_spans(_oath_requirement(), [_oath_table_view()])

    assert len(spans) == 4
    text = "\n".join(span["text"] for span in spans)
    assert "\uad11\ud718\uc758 \uc18c\uc6b8 = 25\uac1c" in text
    assert "\uc0c1\uae09 \uc6d0\uc18c \uacb0\uc815 = 36\uac1c" in text
    assert "\uc21c\ub840\uc758 \uc778\uc7a5 / \uace8\ub4dc = \uc21c\ub840\uc758 \uc778\uc7a5 25\uac1c or 125,000\uace8\ub4dc" in text
    assert "\uc194\ub9ac\ub4dc \uc18c\uc6b8 = 1\uac1c" in text
    assert "60\uac1c" not in text
    assert all(span["exact_row_text"] for span in spans)


def test_table_row_matching_uses_subject_and_relation_from_the_planner() -> None:
    requirement = {
        "requirement_id": "req_oath_unique_cost",
        "subject": "\uc11c\uc57d_\uacb0\uc815",
        "relation": "\uc720\ub2c8\ud06c_\uac00\uaca9",
        "value_type": "amount",
    }

    spans = table_value_spans(requirement, [_oath_table_view()])

    assert len(spans) == 4
    text = "\n".join(span["text"] for span in spans)
    assert "25\uac1c" in text
    assert "60\uac1c" not in text


def test_table_binding_selects_one_row_and_the_requested_attribute() -> None:
    view = {
        "table_id": "table_shop",
        "table_subject": "\uace8\ub4dc \ucf54\uc778 \uc0c1\ud488",
        "attributes": ["\uc544\uc774\ud15c \uac00\uaca9", "\uac70\ub798\ud0c0\uc785"],
        "rows": [
            {
                "row_id": "row_100",
                "subject": "\uace8\ub4dc \ucf54\uc778 100\uac1c",
                "source_chunk_id": "chunk_shop",
                "exact_row_text": "| 100 | 15,000 | \uad50\ud658\uac00\ub2a5 |",
                "values": {
                    "\uc544\uc774\ud15c \uac00\uaca9": "15,000\uc138\ub77c",
                    "\uac70\ub798\ud0c0\uc785": "\uad50\ud658\uac00\ub2a5",
                },
            },
            {
                "row_id": "row_10",
                "subject": "\uace8\ub4dc \ucf54\uc778 10\uac1c",
                "source_chunk_id": "chunk_shop",
                "exact_row_text": "| 10 | 1,500 | \uacc4\uc815\uadc0\uc18d |",
                "values": {
                    "\uc544\uc774\ud15c \uac00\uaca9": "1,500\uc138\ub77c",
                    "\uac70\ub798\ud0c0\uc785": "\uacc4\uc815\uadc0\uc18d",
                },
            },
        ],
    }
    requirement = {
        "subject": "\uace8\ub4dc \ucf54\uc778",
        "relation": "price_ten_units",
        "value_type": "amount",
    }

    spans = table_value_spans(requirement, [view])

    assert [span["text"] for span in spans] == [
        "\uace8\ub4dc \ucf54\uc778 10\uac1c \u00b7 "
        "\uc544\uc774\ud15c \uac00\uaca9 = 1,500\uc138\ub77c"
    ]


def test_table_binding_rejects_unmatched_relation_instead_of_all_columns() -> None:
    requirement = {
        "subject": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \uc720\ub2c8\ud06c",
        "relation": "\uc0ac\uc6a9\ubc29\ubc95",
        "value_type": "text",
    }

    assert table_value_spans(requirement, [_oath_table_view()]) == []


def test_table_values_rescue_a_supported_heading_without_promoting_support() -> None:
    requirements = [_oath_requirement()]
    decisions = [
        _decision(
            "supported_exact",
            "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \ube44\uc6a9\uc740 \uc544\ub798\uc640 \uac19\uc2b5\ub2c8\ub2e4.",
        )
    ]

    without_table = partition_requirements(requirements, decisions)
    with_table = partition_requirements(
        requirements,
        decisions,
        table_views_by_requirement=[[_oath_table_view()]],
    )

    assert without_table["generatable"] == []
    assert len(with_table["generatable"]) == 1
    assert with_table["generatable"][0]["table_value_span_count"] == 4

    unsupported = partition_requirements(
        requirements,
        [_decision("unsupported")],
        table_views_by_requirement=[[_oath_table_view()]],
    )
    assert unsupported["generatable"] == []


def test_compose_backbone_answer_uses_public_table_views() -> None:
    requests = []
    backbone_result = {
        "question": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \uc720\ub2c8\ud06c \uac00\uaca9",
        "requirements": [
            {
                "requirement": _oath_requirement(),
                "status": "supported",
                "citations": [
                    {
                        "span_id": "heading",
                        "chunk_id": "chunk_oath",
                        "text": "\uc11c\uc57d \uacb0\uc815 \ucd08\uc6d4 \ube44\uc6a9\uc740 \uc544\ub798\uc640 \uac19\uc2b5\ub2c8\ub2e4.",
                    }
                ],
                "table_views": [_oath_table_view()],
            }
        ],
    }

    def _generate(request: dict) -> str:
        requests.append(request)
        return (
            "\uad11\ud718\uc758 \uc18c\uc6b8 25\uac1c, \uc0c1\uae09 \uc6d0\uc18c \uacb0\uc815 36\uac1c, "
            "\uc21c\ub840\uc758 \uc778\uc7a5 25\uac1c \ub610\ub294 125,000\uace8\ub4dc, "
            "\uc194\ub9ac\ub4dc \uc18c\uc6b8 1\uac1c\uc785\ub2c8\ub2e4."
        )

    result = compose_backbone_answer(backbone_result, generate=_generate)

    assert result["mode"] == "generated"
    assert result["verification"]["verified"] is True
    assert len(requests) == 1
    assert "\uad11\ud718\uc758 \uc18c\uc6b8 = 25\uac1c" in requests[0]["user"]
    assert "60\uac1c" not in requests[0]["user"]
    assert "\uc544\ub798\uc640 \uac19\uc2b5\ub2c8\ub2e4" not in requests[0]["user"]
