from __future__ import annotations

from pathlib import Path

from src.v3.product_free_rag import ProductFreeRAG
from src.v3.run_product_requirement_fanout_f1 import (
    _gate_a6_7,
    _gate_a6_32,
)


def _child_result(
    *,
    question: str,
    mode: str,
    value: str = "",
    clarification: str = "",
) -> dict:
    claims = []
    evidence_pack = []
    if value:
        citation = {
            "evidence_ref": "E1",
            "chunk_id": f"chunk-{value}",
            "start_char": 10,
            "end_char": 20,
            "text": value,
        }
        claims = [
            {
                "text": value,
                "evidence_refs": ["E1"],
                "citations": [citation],
            }
        ]
        evidence_pack = [
            {
                "ref": "E1",
                "evidence_ref": "E1",
                "candidate_ref": "1",
                **citation,
            }
        ]
    return {
        "product_free_rag_version": "test",
        "question": question,
        "mode": mode,
        "model_mode": mode,
        "claims": claims,
        "rejected_claims": [],
        "clarification": clarification,
        "clarification_options": [],
        "rendered_answer": value or clarification,
        "candidates": [],
        "evidence_unit_count": len(evidence_pack),
        "evidence_pack": evidence_pack,
        "raw_model_output": {"mode": mode},
        "generation": {
            "latency_ms": 5.0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
            },
        },
        "verification": {"all_exposed_citations_verified": True},
        "latency": {"generation_ms": 5.0, "total_ms": 8.0},
        "latency_ms": 8.0,
        "experimental_profile": {},
        "runtime_fingerprint": "test",
    }


def _rag_with_fake_single_answer(*, fanout: bool, calls: list[str]):
    rag = object.__new__(ProductFreeRAG)
    rag.root = Path.cwd()
    rag.use_requirement_fanout = fanout

    def fake_single(question: str, **_: object) -> dict:
        calls.append(question)
        if "구매 제한" in question:
            return _child_result(question=question, mode="unsupported")
        if "명성" in question:
            return _child_result(
                question=question,
                mode="answer",
                value="모험가 명성은 +221입니다.",
            )
        return _child_result(question=question, mode="unsupported")

    rag._answer_single = fake_single
    return rag


def test_fanout_disabled_keeps_the_single_call_path() -> None:
    calls: list[str] = []
    rag = _rag_with_fake_single_answer(fanout=False, calls=calls)
    question = "가격과 기간을 알려줘."

    result = rag.answer(question)

    assert calls == [question]
    assert result["mode"] == "unsupported"


def test_fanout_splits_two_requirements_and_remaps_evidence_refs() -> None:
    calls: list[str] = []
    rag = _rag_with_fake_single_answer(fanout=True, calls=calls)
    question = (
        "2025년 10월 시브의 보조장비 보주는 모험가 명성이 얼마 붙었고, "
        "계정당 구매 제한은 몇 개였어?"
    )

    result = rag.answer(question)

    assert len(calls) == 2
    assert result["mode"] == "partial"
    assert [row["mode"] for row in result["fanout_requirements"]] == [
        "answer",
        "unsupported",
    ]
    assert result["claims"][0]["evidence_refs"] == ["F1E1"]
    assert result["claims"][0]["citations"][0]["evidence_ref"] == "F1E1"
    assert result["evidence_pack"][0]["evidence_ref"] == "F1E1"
    assert result["generation"]["fanout_call_count"] == 2


def test_fanout_clarification_takes_precedence() -> None:
    rag = object.__new__(ProductFreeRAG)
    rag.root = Path.cwd()
    rag.use_requirement_fanout = True
    child_index = 0

    def fake_single(question: str, **_: object) -> dict:
        nonlocal child_index
        child_index += 1
        if child_index == 1:
            return _child_result(
                question=question,
                mode="answer",
                value="첫 번째 값입니다.",
            )
        return _child_result(
            question=question,
            mode="clarification",
            clarification="두 번째 요구의 대상을 알려주세요.",
        )

    rag._answer_single = fake_single

    result = rag.answer("첫 번째 값은 얼마고, 두 번째 값은 얼마야?")

    assert result["mode"] == "clarification"
    assert result["claims"] == []
    assert result["clarification"] == "두 번째 요구의 대상을 알려주세요."


def test_f1_gate_rejects_an_extra_wrong_value_in_the_first_requirement() -> None:
    result = {
        "fanout_requirements": [
            {
                "claims": [
                    {"text": "타이드 바운드 쿨타임은 12초에서 9초입니다."},
                    {"text": "타이드 바운드 쿨타임은 20초에서 18초입니다."},
                ]
            },
            {"claims": [{"text": "질풍 개화는 12초에서 9초입니다."}]},
        ]
    }

    assert not _gate_a6_7(result)


def test_f1_gate_requires_unsupported_for_the_missing_purchase_limit() -> None:
    result = {
        "claims": [{"text": "모험가 명성은 +221입니다."}],
        "fanout_requirements": [
            {"claims": [{"text": "모험가 명성은 +221입니다."}]},
            {
                "mode": "partial",
                "claims": [{"text": "모험가 명성은 +221입니다."}],
            },
        ],
    }

    assert not _gate_a6_32(result)
