from __future__ import annotations

from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.score_product_free_rag_a6 import (
    requirement_value_complete,
    score_case,
    summarize,
)


ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = (
    ROOT / "data/v3/evaluation/product_free_rag_a6_candidate_v3_20260805.jsonl"
)
ONE_SHOT = ROOT / (
    "reports/v3/product_free_rag_a6_one_shot_"
    "4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl"
)
CHUNKS = ROOT / (
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)


def test_structured_and_range_values_are_scored_without_gold_text_copy() -> None:
    assert requirement_value_complete(
        {
            "expected_status": "supported",
            "value_type": "object",
            "relation": "price_and_purchase_limit",
            "required_values": [
                {
                    "price": 360,
                    "unit": "광휘의 잔영",
                    "purchase_limit": "계정당 월 4회",
                }
            ],
        },
        rendered_answer="가격은 광휘의 잔영 360개이며 계정당 월 4회 살 수 있습니다.",
        as_of="2026-07-31",
    )
    assert requirement_value_complete(
        {
            "expected_status": "supported",
            "value_type": "currency",
            "relation": "price",
            "required_values": [{"amount": 350, "unit": "M"}],
        },
        rendered_answer="가격은 350M입니다.",
        as_of="2026-07-31",
    )
    assert requirement_value_complete(
        {
            "expected_status": "supported",
            "value_type": "time_range",
            "relation": "maintenance_time",
            "required_values": ["05:30", "10:00"],
        },
        rendered_answer="점검은 05:30부터 10:00까지입니다.",
        as_of="2026-07-31",
    )


def test_metadata_case_requires_exact_documents_values_and_field_refs() -> None:
    frozen = {
        "slot_ordinal": 2,
        "candidate_id": "candidate-2",
        "question_text": "최근 공지를 알려줘",
        "as_of": "2026-07-31",
        "expected_query_mode": "metadata",
        "expected_response_mode": "partial_answer",
        "expected_qwen_called": False,
        "expected_effective_as_of": "2026-07-17",
        "expected_document_ids": ["doc-a", "doc-b"],
        "requirements": [
            {
                "requirement_id": "latest",
                "required_values": ["공지 A", "공지 B"],
            }
        ],
    }
    citations = [
        {"document_id": "doc-a", "field_refs": ["title", "published_at"]},
        {"document_id": "doc-b", "field_refs": ["title", "published_at"]},
    ]
    result = {
        "mode": "partial",
        "rendered_answer": "공지 A\n공지 B",
        "candidates": [{"document_id": "doc-a"}, {"document_id": "doc-b"}],
        "claims": [{"citations": citations}],
        "generation": None,
        "verification": {"effective_as_of": "2026-07-17"},
    }

    scored = score_case(frozen, result, chunks_by_id={})

    assert scored["meaning_complete"] is True
    assert scored["citation_policy_restored"] is True
    assert scored["qwen_call_match"] is True


def test_complete_table_requires_server_text_and_exact_runtime_coordinate() -> None:
    table = "| 칭호명 | 행운아 |\n| 옵션 | 명성 +315 |"
    chunk_text = f"[TABLE]\n{table}\n[/TABLE]"
    start = chunk_text.index(table)
    end = start + len(table)
    unit = {
        "chunk_id": "chunk-table",
        "start_char": start,
        "end_char": end,
        "text": table,
    }
    frozen = {
        "slot_ordinal": 31,
        "candidate_id": "candidate-31",
        "question_text": "칭호 전체 표를 보여줘",
        "as_of": "2026-07-31",
        "expected_query_mode": "rag",
        "expected_response_mode": "full_answer",
        "expected_qwen_called": True,
        "requirements": [
            {
                "requirement_id": "table",
                "expected_status": "supported",
                "value_type": "table",
                "relation": "complete_table",
                "required_values": [{"title": "행운아", "fame": 315}],
                "acceptable_evidence_units": [unit],
            }
        ],
    }
    citation = {**unit}
    result = {
        "mode": "answer",
        "rendered_answer": f"칭호 표입니다.\n\n{table}",
        "claims": [{"citations": [citation]}],
        "generation": {"usage": {"input_tokens": 100}},
        "verification": {"all_exposed_citations_verified": True},
    }

    scored = score_case(
        frozen,
        result,
        chunks_by_id={"chunk-table": {"display_text": chunk_text}},
    )

    assert scored["meaning_complete"] is True
    assert scored["citation_policy_restored"] is True


def test_fully_unsupported_case_is_complete_only_when_model_abstains() -> None:
    frozen = {
        "slot_ordinal": 20,
        "candidate_id": "candidate-20",
        "question_text": "정확한 원인 프로그램은 뭐야?",
        "as_of": "2026-07-31",
        "expected_query_mode": "rag",
        "expected_response_mode": "abstain",
        "expected_qwen_called": True,
        "requirements": [
            {
                "requirement_id": "offending_program",
                "expected_status": "unsupported",
                "value_type": "entity",
                "relation": "offending_program_name",
                "required_values": [],
                "acceptable_evidence_units": [],
            }
        ],
    }
    unsupported_result = {
        "mode": "unsupported",
        "rendered_answer": "공식 문서에서 확인할 수 없습니다.",
        "claims": [],
        "generation": {"usage": {"input_tokens": 10}},
        "verification": {"all_exposed_citations_verified": True},
    }
    answer_result = {
        **unsupported_result,
        "mode": "answer",
        "rendered_answer": "백신 프로그램 때문입니다.",
    }

    accepted = score_case(frozen, unsupported_result, chunks_by_id={})
    overclaim = score_case(frozen, answer_result, chunks_by_id={})

    assert accepted["meaning_complete"] is True
    assert accepted["unsupported_overclaim_candidate"] is False
    assert overclaim["meaning_complete"] is False
    assert overclaim["false_full_candidate"] is True
    assert overclaim["unsupported_overclaim_candidate"] is True


def test_requirement_level_overclaim_gate_matches_a6_review_cases() -> None:
    frozen_by_slot = {
        row["slot_ordinal"]: row
        for row in read_jsonl(CANDIDATES)
    }
    result_by_slot = {
        row["slot_ordinal"]: row["result"]
        for row in read_jsonl(ONE_SHOT)
        if row.get("type") == "case"
    }
    chunks_by_id = {
        row["chunk_id"]: row
        for row in read_jsonl(CHUNKS)
    }
    scored = {
        slot: score_case(
            frozen_by_slot[slot],
            result_by_slot[slot],
            chunks_by_id=chunks_by_id,
        )
        for slot in (6, 22, 29, 32)
    }

    assert scored[6]["false_full_candidate"] is True
    assert scored[6]["unsupported_overclaim_candidate"] is False
    assert scored[22]["unsupported_overclaim_candidate"] is True
    assert scored[29]["unsupported_overclaim_candidate"] is False
    assert scored[32]["unsupported_overclaim_candidate"] is False


def test_summary_encodes_all_preregistered_go_gates() -> None:
    rows = []
    for slot in range(1, 33):
        clarification = slot == 10
        rows.append(
            {
                "slot_ordinal": slot,
                "expected_mode": "clarification" if clarification else "answer",
                "meaning_complete": True,
                "false_full_candidate": False,
                "citation_policy_restored": True,
                "qwen_call_match": True,
                "result": {
                    "latency": {"total_ms": 1000},
                    "generation": (
                        None
                        if slot in {2, 5, 9, 10}
                        else {"usage": {"input_tokens": 500}}
                    ),
                },
            }
        )

    summary = summarize(
        rows,
        expected_count=32,
        error_count=0,
        regression_passed=True,
    )

    assert summary["automated_go_candidate"] is True
    assert summary["human_semantic_review_required"] is True
    assert summary["go"] is None
    assert summary["clear_case_count"] == 31
    assert summary["generation_calls"] == 28


def test_every_supported_rag_gold_value_is_scorable_from_its_canonical_values() -> None:
    failures = []
    for row in read_jsonl(CANDIDATES):
        if row["expected_query_mode"] != "rag":
            continue
        for requirement in row["requirements"]:
            if requirement["expected_status"] != "supported":
                continue
            assert requirement["acceptable_evidence_units"]
            gold_text = " ".join(
                str(value) for value in requirement["required_values"]
            )
            direct_complete = requirement_value_complete(
                requirement,
                rendered_answer=gold_text,
                as_of=row["as_of"],
            )
            if (
                not direct_complete
                and requirement["value_type"]
                not in {"text", "enum", "entity", "entity_list", "boolean"}
            ):
                failures.append(
                    (row["slot_ordinal"], requirement["requirement_id"])
                )

    assert failures == []
