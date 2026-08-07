from __future__ import annotations

from src.v3.grounded_answer_generator import compose_answer, expand_spans_to_parent_chunks

CHUNKS = {
    "chunk_1": "* 스페셜 클론 레어 아바타 풀세트 상자는 상점 판매가가 존재합니다.\n"
    "| 스페셜 클론 레어 아바타 풀세트 상자 | 4,000만 골드 |",
    # Same price, but the item name sits in a value cell rather than the entity cell,
    # which is how a transposed table is stored.
    "chunk_2": "* 상품 안내입니다.\n| 상품명 | 스페셜 클론 레어 아바타 풀세트 상자 |\n"
    "| 상점판매가격 | 4,000만 골드 |",
}


def _requirement() -> dict:
    return {
        "requirement_id": "requirement_1",
        "subject": "스페셜_클론_레어_아바타_풀세트_상자",
        "relation": "상점판매가",
        "value_type": "amount",
    }


def _decision() -> dict:
    return {
        "requirement_id": "requirement_1",
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "s1",
                "chunk_id": "chunk_1",
                "text": "* 스페셜 클론 레어 아바타 풀세트 상자는 상점 판매가가 존재합니다.",
            }
        ],
    }


def test_expansion_replaces_the_span_with_its_parent_chunk() -> None:
    expanded = expand_spans_to_parent_chunks([_decision()], CHUNKS)
    assert [span["text"] for span in expanded[0]["spans"]] == [CHUNKS["chunk_1"]]
    assert expanded[0]["spans"][0]["evidence_kind"] == "parent_chunk"


def test_table_value_units_survive_expansion() -> None:
    decisions = [
        {
            "status": "supported_exact",
            "spans": [
                {"chunk_id": "chunk_1", "text": "머리말"},
                {
                    "chunk_id": "chunk_1",
                    "text": "상자 · 상점판매가격 = 4,000만 골드",
                    "evidence_kind": "table_attribute_value",
                },
            ],
        }
    ]
    expanded = expand_spans_to_parent_chunks(decisions, CHUNKS)
    kinds = [span.get("evidence_kind") for span in expanded[0]["spans"]]
    assert "table_attribute_value" in kinds
    assert "parent_chunk" in kinds


def test_chunk_scope_lets_a_value_outside_the_span_be_verified() -> None:
    seen: list[str] = []

    def generate(request: dict) -> str:
        seen.append(request["user"])
        return "상점판매가격은 4,000만 골드입니다."

    span_scope = compose_answer(
        question="상점판매가는?",
        requirements=[_requirement()],
        decisions=[_decision()],
        generate=generate,
    )
    chunk_scope = compose_answer(
        question="상점판매가는?",
        requirements=[_requirement()],
        decisions=[_decision()],
        chunk_text_by_id=CHUNKS,
        generate=generate,
    )
    # The price is in the chunk but not in the selected span. Span scope never even
    # reaches the model: the value-shape gate abstains on the narrow span. Chunk scope
    # widens the evidence before that gate, so the same answer becomes verifiable.
    assert span_scope["mode"] == "abstain"
    assert chunk_scope["mode"] == "generated"
    # Only the chunk-scope run ever reached the model, and it saw the price.
    assert len(seen) == 1
    assert "4,000만 골드" in seen[0]


def test_chunk_scope_does_not_disable_the_cost_subject_veto() -> None:
    # chunk_2 holds the same price, but the item name is a value cell, so the entity
    # cell never names the subject. Widening the evidence must not smuggle that past
    # the cost-alignment veto.
    calls: list[str] = []

    def generate(request: dict) -> str:
        calls.append(request["user"])
        return "상점판매가격은 4,000만 골드입니다."

    decision = _decision()
    decision["spans"][0]["chunk_id"] = "chunk_2"
    result = compose_answer(
        question="상점판매가는?",
        requirements=[_requirement()],
        decisions=[decision],
        chunk_text_by_id=CHUNKS,
        generate=generate,
    )
    assert result["mode"] == "abstain"
    assert calls == []


def test_omitting_chunk_texts_changes_nothing() -> None:
    def generate(request: dict) -> str:
        return "상점 판매가가 존재합니다."

    default = compose_answer(
        question="상점판매가는?",
        requirements=[_requirement()],
        decisions=[_decision()],
        generate=generate,
    )
    explicit_none = compose_answer(
        question="상점판매가는?",
        requirements=[_requirement()],
        decisions=[_decision()],
        chunk_text_by_id=None,
        generate=generate,
    )
    assert default == explicit_none
