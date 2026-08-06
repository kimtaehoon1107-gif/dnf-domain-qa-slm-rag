from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import src.v3.free_minimal_claim_v2 as free_minimal_claim_v2
from src.v3.free_minimal_claim_v2 import (
    FreeMinimalClaimV2,
    LiveClaimDraft,
    LiveClaimPlan,
    _fixed_requirements,
    _resolved_live_requirements,
    _resolved_live_requirements_strict_shadow,
    render_natural_answer,
)
from src.v3.free_minimal_table import (
    _matching_attributes,
    choose_structured_table_answer,
    operation_identity_matches,
    operation_identity_state,
    prefer_exact_title_parent_ids,
)
from src.v3.typed_evidence_ref import _relation_supported


def test_fixed_requirements_assign_server_owned_ids() -> None:
    plan = LiveClaimPlan(
        requirements=[
            LiveClaimDraft(
                subject="상품 A",
                relation="price",
                value_type="currency",
            ),
            LiveClaimDraft(
                subject="상품 A 구성품",
                relation="included_items",
                value_type="entity_list",
                cardinality="all",
                expected_count=2,
            ),
        ]
    )

    assert _fixed_requirements(plan) == [
        {
            "requirement_id": "requirement_1",
            "subject": "상품 A",
            "relation": "price",
            "value_type": "currency",
        },
        {
            "requirement_id": "requirement_2",
            "subject": "상품 A 구성품",
            "relation": "included_items",
            "value_type": "entity_list",
            "cardinality": "all",
            "expected_count": 2,
        },
    ]


def test_live_claim_relation_requires_canonical_snake_case() -> None:
    with pytest.raises(ValidationError):
        LiveClaimDraft(
            subject="상품 A",
            relation="거래_타입",
            value_type="enum",
        )


def test_live_claim_relation_registry_normalizes_generator_and_verifier_type() -> None:
    requirements = [
        {
            "requirement_id": "requirement_1",
            "subject": "상품 A",
            "relation": "trade_type",
            "value_type": "number",
        }
    ]

    resolved = _resolved_live_requirements(
        requirements,
        question="상품 A의 거래 타입은 뭐야?",
    )

    assert resolved[0]["value_type"] == "enum"


def test_live_claim_unknown_relation_fails_closed() -> None:
    with pytest.raises(
        RuntimeError,
        match="unregistered_live_relation",
    ):
        _resolved_live_requirements(
            [
                {
                    "requirement_id": "requirement_1",
                    "subject": "115Lv 무기 에픽 장비",
                    "relation": "exceeding_equipment_requirement",
                    "value_type": "number",
                }
            ],
            question=(
                "115Lv 무기 에픽 장비를 초월할 때 "
                "순례의 인장이 몇 개 필요해?"
            ),
        )


def test_live_claim_known_entry_relation_remains_available() -> None:
    resolved = _resolved_live_requirements(
        [
            {
                "requirement_id": "requirement_1",
                "subject": "최후의 과업 채널",
                "relation": "entry_reputation",
                "value_type": "number",
            }
        ],
        question="최후의 과업 채널 입장 명성은 얼마야?",
    )

    assert resolved[0]["relation"] == "entry_reputation"


def test_live_claim_normalizes_generic_enhancement_probability() -> None:
    resolved = _resolved_live_requirements(
        [
            {
                "requirement_id": "requirement_1",
                "subject": "강화 확률",
                "relation": "probability",
                "value_type": "number",
            }
        ],
        question="강화 확률 알려줘",
    )

    assert resolved[0]["relation"] == "enhancement_probability"
    assert resolved[0]["value_type"] == "percentage"


def test_strict_shadow_admits_unique_family_without_question_hardcode() -> None:
    resolved = _resolved_live_requirements_strict_shadow(
        [
            {
                "requirement_id": "requirement_1",
                "subject": "강화",
                "relation": "probability",
                "value_type": "percentage",
            }
        ],
        question="강화 확률 알려줘",
    )

    assert resolved[0]["relation"] == "probability"
    assert resolved[0]["value_type"] == "percentage"
    assert resolved[0]["relation_validation_mode"] == "strict"
    assert (
        resolved[0]["_inferred_relation_family_candidate"]
        == "percentage_effect"
    )
    assert resolved[0]["_relation_family_candidates"] == [
        "percentage_effect"
    ]


def test_strict_shadow_keeps_ambiguous_family_unknown_and_strict() -> None:
    resolved = _resolved_live_requirements_strict_shadow(
        [
            {
                "requirement_id": "requirement_1",
                "subject": "최후의 과업",
                "relation": "entry_requirement",
                "value_type": "number",
            }
        ],
        question="최후의 과업 입장 명성은?",
    )

    assert resolved[0]["relation_validation_mode"] == "strict"
    assert resolved[0]["_inferred_relation_family_candidate"] is None
    assert resolved[0]["_relation_family_candidates"] == [
        "price_currency",
        "quantity_limit",
        "temporal",
    ]
    assert not _relation_supported(
        resolved[0],
        "최후의 과업 입장 명성은 108,921입니다.",
    )


def test_strict_shadow_rejects_value_type_outside_planner_schema() -> None:
    with pytest.raises(
        RuntimeError,
        match="invalid_live_value_type",
    ):
        _resolved_live_requirements_strict_shadow(
            [
                {
                    "requirement_id": "requirement_1",
                    "subject": "디레지에",
                    "relation": "difficulty_types",
                    "value_type": "object",
                }
            ],
            question="디레지에 난이도는?",
        )


def test_simple_rag_branch_passes_configured_evidence_mode(
    monkeypatch,
) -> None:
    captured = {}
    artifacts = SimpleNamespace(
        chunks_by_id={
            "c1": {
                "chunk_id": "c1",
                "parent_document_id": "d1",
                "display_text": "evidence",
            }
        },
        documents_by_id={
            "d1": {
                "document_id": "d1",
                "source_id": "guide",
                "title": "guide",
            }
        },
    )
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.base = SimpleNamespace(
        _artifacts=artifacts,
        temporal_by_document={},
        _retrieve_and_rerank=lambda question: (
            {"route": {}},
            [{"chunk_id": "c1"}],
        ),
    )
    runtime.model = "test"
    runtime.timeout = 1.0
    runtime.fallback_mode = "simple_rag"
    runtime.simple_rag_evidence_mode = "server_ref"
    runtime._structured_table_answer = lambda *args, **kwargs: None
    runtime._apply_operation_guard = lambda result, **kwargs: result

    monkeypatch.setattr(
        free_minimal_claim_v2,
        "choose_direct_entry_fame",
        lambda *args, **kwargs: None,
    )

    def fake_answer(**kwargs):
        captured.update(kwargs)
        return {
            "response_mode": "full_answer",
            "requirements": [
                {
                    "status": "supported_exact",
                    "answer": "answer",
                    "citations": [{"chunk_id": "c1"}],
                }
            ],
        }

    monkeypatch.setattr(
        free_minimal_claim_v2,
        "answer_simple_rag_from_candidates",
        fake_answer,
    )

    runtime.answer("question")

    assert captured["evidence_mode"] == "server_ref"


def test_runtime_reports_retrieval_failure_stage() -> None:
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.enable_metadata_queries = False
    runtime.base = SimpleNamespace(
        _retrieve_and_rerank=lambda question: (_ for _ in ()).throw(
            TimeoutError("retrieval timed out")
        )
    )

    result = runtime.answer("질문")

    assert result["response_mode"] == "abstain"
    assert result["failure_stage"] == "retrieval"
    assert result["verification"]["failure_stage"] == "retrieval"
    assert result["latency"]["retrieval_ms"] >= 0
    assert result["latency"]["failure_stage_ms"] >= 0


def test_runtime_reports_simple_rag_generation_failure_stage(
    monkeypatch,
) -> None:
    artifacts = SimpleNamespace(
        chunks_by_id={
            "c1": {
                "chunk_id": "c1",
                "parent_document_id": "d1",
                "display_text": "evidence",
            }
        },
        documents_by_id={
            "d1": {
                "document_id": "d1",
                "source_id": "guide",
                "title": "guide",
            }
        },
    )
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.enable_metadata_queries = False
    runtime.base = SimpleNamespace(
        _artifacts=artifacts,
        temporal_by_document={},
        _retrieve_and_rerank=lambda question: (
            {"route": {}},
            [{"chunk_id": "c1"}],
        ),
    )
    runtime.model = "test"
    runtime.timeout = 1.0
    runtime.generation_timeout = 0.25
    runtime.fallback_mode = "simple_rag"
    runtime.simple_rag_evidence_mode = "exact_quote"
    runtime._structured_table_answer = lambda *args, **kwargs: None

    monkeypatch.setattr(
        free_minimal_claim_v2,
        "choose_direct_entry_fame",
        lambda *args, **kwargs: None,
    )
    captured = {}

    def fail_generation(**kwargs):
        captured.update(kwargs)
        exc = TimeoutError("generation timed out")
        exc.generation_diagnostics = {
            "timeout_seconds": kwargs["timeout"],
            "prompt_chars": 1234,
            "candidate_count": 1,
            "max_output_tokens": 1200,
        }
        raise exc

    monkeypatch.setattr(
        free_minimal_claim_v2,
        "answer_simple_rag_from_candidates",
        fail_generation,
    )
    monkeypatch.setattr(
        free_minimal_claim_v2,
        "_ollama_runtime_status",
        lambda: {
            "reachable": True,
            "loaded_models": [{"name": "test"}],
            "probe_ms": 1.0,
        },
    )

    result = runtime.answer("질문")

    assert result["response_mode"] == "abstain"
    assert result["failure_stage"] == "simple_rag_generation"
    assert (
        result["verification"]["failure_stage"]
        == "simple_rag_generation"
    )
    assert result["latency"]["failure_stage_ms"] >= 0
    assert result["latency"]["generation_ms"] >= 0
    assert captured["timeout"] == 0.25
    assert result["generation"]["request"]["prompt_chars"] == 1234
    assert result["generation"]["usage"]["input_tokens"] is None
    assert result["generation"]["ollama_status"]["reachable"] is True


def test_runtime_accepts_explicit_table_index_manifest() -> None:
    runtime = FreeMinimalClaimV2(
        root=Path.cwd(),
        base=SimpleNamespace(),
        table_index_manifest=Path("data/test-table-index.json"),
    )

    assert runtime.table_index_manifest == Path(
        "data/test-table-index.json"
    )


def test_runtime_accepts_separate_generation_timeout() -> None:
    runtime = FreeMinimalClaimV2(
        root=Path.cwd(),
        base=SimpleNamespace(),
        timeout=90.0,
        generation_timeout=30.0,
    )

    assert runtime.timeout == 90.0
    assert runtime.generation_timeout == 30.0


def test_metadata_query_bypasses_retrieval_and_qwen() -> None:
    runtime = FreeMinimalClaimV2(
        root=Path.cwd(),
        base=SimpleNamespace(
            _retrieve_and_rerank=lambda question: (_ for _ in ()).throw(
                AssertionError("metadata query must bypass retrieval")
            )
        ),
        enable_metadata_queries=True,
        metadata_as_of="2026-07-30",
    )
    runtime._metadata_documents = [
        {
            "document_id": "event_1",
            "source_id": "dnf_event",
            "title": "진행 이벤트",
            "published_at": "2026-07-16",
            "valid_from": "2026-07-16",
            "valid_to": "2026-08-06",
            "status": "current",
            "default_exposure": True,
            "review_required": False,
            "canonical_url": "https://example.test/event",
        }
    ]

    result = runtime.answer("지금 진행 중 이벤트 알려줘")

    assert result["response_mode"] == "partial"
    assert result["verification"]["qwen_called"] is False
    assert result["verification"]["requested_as_of"] == "2026-07-30"
    assert result["verification"]["coverage_as_of"] == "2026-07-17"
    assert result["verification"]["effective_as_of"] == "2026-07-17"
    assert result["latency"]["retrieval_ms"] == 0.0


def test_operation_identity_rejects_tuning_for_transcendence() -> None:
    assert not operation_identity_matches(
        "115Lv 장비를 초월할 때 비용은?",
        title="조율 / 승급",
        heading_path=["장비 조율", "비용"],
    )
    assert operation_identity_matches(
        "115Lv 장비를 초월할 때 비용은?",
        title="초월",
        heading_path=["NPC 장비 초월", "비용"],
    )


def test_operation_identity_accepts_requested_operation_in_quote() -> None:
    assert operation_identity_matches(
        "초월은 무슨 종류가 있어?",
        title="서약 / 결정",
        heading_path=[],
        evidence_text="서약 결정 초월 비용은 아래와 같습니다.",
    )
    assert (
        operation_identity_state(
            "초월 비용은?",
            title="조율 / 승급",
            heading_path=["장비 조율"],
            evidence_text="조율 비용은 300개입니다.",
        )
        == "conflict"
    )


def test_table_sidecar_prefers_exact_named_document_title() -> None:
    selected = prefer_exact_title_parent_ids(
        "강화 확률 알려줘",
        parent_ids=("guide", "ticket"),
        documents_by_id={
            "guide": {"title": "강화"},
            "ticket": {"title": "무기 강화권[리노]"},
        },
    )

    assert selected == ("guide",)


def test_table_sidecar_keeps_parents_without_exact_title() -> None:
    selected = prefer_exact_title_parent_ids(
        "115Lv 장비 초월 비용 알려줘",
        parent_ids=("guide", "update"),
        documents_by_id={
            "guide": {"title": "[장비] 초월"},
            "update": {"title": "초월 비용 변경"},
        },
    )

    assert selected == ("guide", "update")


def test_operation_guard_hides_wrong_equipment_operation() -> None:
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.base = SimpleNamespace(
        _artifacts=SimpleNamespace(
            chunks_by_id={
                "chunk_tuning": {
                    "chunk_id": "chunk_tuning",
                    "parent_document_id": "document_tuning",
                    "heading_path": ["장비 조율", "비용"],
                }
            },
            documents_by_id={
                "document_tuning": {
                    "document_id": "document_tuning",
                    "title": "조율 / 승급",
                }
            },
        )
    )
    guarded = runtime._apply_operation_guard(
        {
            "response_mode": "full_answer",
            "requirements": [
                {
                    "requirement_id": "requirement_1",
                    "status": "supported_exact",
                    "value": 300,
                    "answer": "300",
                    "citations": [
                        {"chunk_id": "chunk_tuning"}
                    ],
                    "verification": {"failure_reasons": []},
                }
            ],
        },
        question=(
            "115Lv 무기 에픽 장비를 초월할 때 "
            "순례의 인장이 몇 개 필요해?"
        ),
    )

    assert guarded["response_mode"] == "abstain"
    assert guarded["requirements"][0]["status"] == "unsupported"
    assert guarded["requirements"][0]["citations"] == []
    assert (
        "operation_identity_conflict"
        in guarded["requirements"][0]["verification"][
            "failure_reasons"
        ]
    )


def test_operation_guard_keeps_valid_quote_and_prunes_conflict() -> None:
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.base = SimpleNamespace(
        _artifacts=SimpleNamespace(
            chunks_by_id={
                "chunk_valid": {
                    "chunk_id": "chunk_valid",
                    "parent_document_id": "document_valid",
                    "heading_path": [],
                },
                "chunk_wrong": {
                    "chunk_id": "chunk_wrong",
                    "parent_document_id": "document_wrong",
                    "heading_path": ["장비 조율"],
                },
            },
            documents_by_id={
                "document_valid": {
                    "document_id": "document_valid",
                    "title": "서약 / 결정",
                },
                "document_wrong": {
                    "document_id": "document_wrong",
                    "title": "조율 / 승급",
                },
            },
        )
    )
    guarded = runtime._apply_operation_guard(
        {
            "response_mode": "full_answer",
            "requirements": [
                {
                    "requirement_index": 1,
                    "status": "supported_exact",
                    "answer": "장비 초월과 서약 결정 초월",
                    "citations": [
                        {
                            "chunk_id": "chunk_valid",
                            "text": "서약 결정 초월 비용은 아래와 같습니다.",
                        },
                        {
                            "chunk_id": "chunk_wrong",
                            "text": "장비 조율 비용은 아래와 같습니다.",
                        },
                    ],
                    "verification": {"failure_reasons": []},
                }
            ],
            "verification": {
                "requirements": [
                    {
                        "requirement_index": 1,
                        "model_status": "supported",
                        "exposed_status": "supported_exact",
                        "failure_reasons": [],
                    }
                ]
            },
        },
        question="초월은 무슨 종류가 있어?",
    )

    assert guarded["response_mode"] == "full_answer"
    assert [
        row["chunk_id"]
        for row in guarded["requirements"][0]["citations"]
    ] == ["chunk_valid"]
    assert (
        guarded["verification"]["requirements"][0]["exposed_status"]
        == "supported_exact"
    )


def test_operation_guard_preserves_model_partial_ceiling() -> None:
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.base = SimpleNamespace(
        _artifacts=SimpleNamespace(
            chunks_by_id={
                "chunk_valid": {
                    "chunk_id": "chunk_valid",
                    "parent_document_id": "document_valid",
                    "heading_path": [],
                }
            },
            documents_by_id={
                "document_valid": {
                    "document_id": "document_valid",
                    "title": "칭호 문의",
                }
            },
        )
    )

    guarded = runtime._apply_operation_guard(
        {
            "model_response_mode": "partial_answer",
            "response_mode": "partial_answer",
            "requirements": [
                {
                    "requirement_index": 1,
                    "status": "supported_exact",
                    "answer": "서버/캐릭터명",
                    "citations": [
                        {
                            "chunk_id": "chunk_valid",
                            "text": "서버/캐릭터명",
                        }
                    ],
                }
            ],
            "verification": {
                "requirements": [
                    {
                        "requirement_index": 1,
                        "model_status": "partial",
                        "exposed_status": "supported_exact",
                        "failure_reasons": [],
                    }
                ]
            },
        },
        question="문의 정보와 처리 기간을 알려줘",
    )

    assert guarded["response_mode"] == "partial_answer"


def test_operation_guard_rechecks_numbers_after_pruning() -> None:
    runtime = object.__new__(FreeMinimalClaimV2)
    runtime.base = SimpleNamespace(
        _artifacts=SimpleNamespace(
            chunks_by_id={
                "chunk_valid": {
                    "chunk_id": "chunk_valid",
                    "parent_document_id": "document_valid",
                    "heading_path": ["장비 초월"],
                },
                "chunk_wrong": {
                    "chunk_id": "chunk_wrong",
                    "parent_document_id": "document_wrong",
                    "heading_path": ["장비 조율"],
                },
            },
            documents_by_id={
                "document_valid": {
                    "document_id": "document_valid",
                    "title": "초월",
                },
                "document_wrong": {
                    "document_id": "document_wrong",
                    "title": "조율 / 승급",
                },
            },
        )
    )
    guarded = runtime._apply_operation_guard(
        {
            "response_mode": "full_answer",
            "requirements": [
                {
                    "requirement_index": 1,
                    "status": "supported_exact",
                    "answer": "300개",
                    "citations": [
                        {
                            "chunk_id": "chunk_valid",
                            "text": "초월에는 순례의 인장이 필요합니다.",
                        },
                        {
                            "chunk_id": "chunk_wrong",
                            "text": "조율 비용은 300개입니다.",
                        },
                    ],
                    "verification": {"failure_reasons": []},
                }
            ],
            "verification": {
                "requirements": [
                    {
                        "requirement_index": 1,
                        "model_status": "supported",
                        "exposed_status": "supported_exact",
                        "failure_reasons": [],
                    }
                ]
            },
        },
        question="초월 비용은 몇 개야?",
    )

    assert guarded["response_mode"] == "abstain"
    assert (
        "operation_value_not_supported_after_pruning"
        in guarded["requirements"][0]["verification"][
            "failure_reasons"
        ]
    )
    assert (
        guarded["verification"]["requirements"][0]["exposed_status"]
        == "unsupported"
    )


def test_structured_table_selects_exact_row_and_attribute() -> None:
    chunk_id = "chunk_table"
    display_text = (
        "115Lv 장비 초월 비용은 아래와 같습니다.\n"
        "| 장비 종류 | 구분 | 순례의 인장 |\n"
        "| 무기 | 에픽 | 1,125 |"
    )
    row_text = "| 무기 | 에픽 | 1,125 |"
    start = display_text.index(row_text)
    facts = [
        {
            "fact_id": "fact_1",
            "table_id": "table_1",
            "row_id": "row_1",
            "parent_document_id": "document_1",
            "source_chunk_id": chunk_id,
            "source_id": "dnf_game_guide",
            "title": "초월",
            "canonical_url": "https://example.invalid",
            "table_caption": "115Lv 장비 초월 비용은 아래와 같습니다.",
            "subject": "115Lv 장비 초월 무기 에픽",
            "attribute": "순례의 인장",
            "value": "1,125",
            "value_start_offset": start + row_text.index("1,125"),
            "start_offset": start,
            "end_offset": start + len(row_text),
            "parent_start_offset": start,
            "row_text": row_text,
        }
    ]

    selected = choose_structured_table_answer(
        question=(
            "115Lv 무기 에픽 장비를 초월할 때 "
            "순례의 인장이 몇 개 필요해?"
        ),
        ranked_seed_facts=facts,
        all_facts=facts,
        chunks_by_id={
            chunk_id: {"display_text": display_text}
        },
    )

    assert selected is not None
    assert selected["kind"] == "table_cells"
    assert selected["values"] == {"순례의 인장": "1,125"}


def test_table_attribute_matches_shorter_question_alias() -> None:
    assert _matching_attributes(
        "계약 3일 가격과 거래 타입은?",
        ["판매가격", "거래타입", "설명"],
    ) == ["판매가격", "거래타입"]


def test_structured_table_uses_row_label_for_generic_value_column() -> None:
    chunk_id = "chunk_entry_fame"
    first_row = "| 입장 명성 | 63,257 |"
    second_row = "| 권장 명성 | 76,599 |"
    display_text = f"{first_row}\n{second_row}"
    facts = []
    for index, (label, value, row_text) in enumerate(
        (
            ("입장 명성", "63,257", first_row),
            ("권장 명성", "76,599", second_row),
        ),
        1,
    ):
        start = display_text.index(row_text)
        facts.append(
            {
                "fact_id": f"fact_{index}",
                "table_id": "table_content_info",
                "row_id": f"row_{index}",
                "parent_document_id": "document_diregie",
                "source_chunk_id": chunk_id,
                "source_id": "dnf_game_guide",
                "title": "검은 질병의 디레지에 레이드",
                "heading_path": ["콘텐츠 정보"],
                "canonical_url": "https://example.invalid",
                "table_caption": "콘텐츠 정보",
                "subject": f"콘텐츠 정보 {label}",
                "attribute": "내용",
                "value": value,
                "value_start_offset": start + row_text.index(value),
                "start_offset": start,
                "end_offset": start + len(row_text),
                "parent_start_offset": start,
                "row_text": row_text,
            }
        )

    selected = choose_structured_table_answer(
        question="디레지에 입장명성 알려줘",
        ranked_seed_facts=[facts[0]],
        all_facts=facts,
        chunks_by_id={chunk_id: {"display_text": display_text}},
    )

    assert selected is not None
    assert selected["kind"] == "table_cells"
    assert selected["row"]["label"] == "입장 명성"
    assert selected["values"] == {"입장 명성": "63,257"}


def test_structured_table_returns_complete_view_for_broad_cost_question() -> None:
    chunk_id = "chunk_table"
    row_text = "| 무기 | 에픽 | 1,125 |"
    display_text = row_text
    facts = [
        {
            "fact_id": "fact_1",
            "table_id": "table_1",
            "row_id": "row_1",
            "parent_document_id": "document_1",
            "source_chunk_id": chunk_id,
            "source_id": "dnf_game_guide",
            "title": "초월",
            "canonical_url": "https://example.invalid",
            "table_caption": "115Lv 장비 초월 비용은 아래와 같습니다.",
            "subject": "115Lv 장비 초월 무기 에픽",
            "attribute": "순례의 인장",
            "value": "1,125",
            "value_start_offset": row_text.index("1,125"),
            "start_offset": 0,
            "end_offset": len(row_text),
            "parent_start_offset": 0,
            "row_text": row_text,
        }
    ]

    selected = choose_structured_table_answer(
        question="115Lv 장비 초월 비용 알려줘",
        ranked_seed_facts=facts,
        all_facts=facts,
        chunks_by_id={
            chunk_id: {"display_text": display_text}
        },
    )

    assert selected is not None
    assert selected["kind"] == "complete_table"


def test_structured_table_projects_stage_and_probability_for_broad_query() -> None:
    chunk_id = "chunk_table"
    row_text = "| +4 → 5 시도 | 80% |"
    display_text = row_text
    facts = []
    for attribute, value in (
        ("강화 시도 구간", "+4 → 5 시도"),
        ("성공 확률", "80%"),
    ):
        facts.append(
            {
                "fact_id": f"fact_{len(facts) + 1}",
                "table_id": "table_1",
                "row_id": "row_1",
                "parent_document_id": "document_1",
                "source_chunk_id": chunk_id,
                "source_id": "dnf_game_guide",
                "title": "강화",
                "canonical_url": "https://example.invalid",
                "table_caption": "안전 강화",
                "subject": "안전 강화",
                "attribute": attribute,
                "value": value,
                "value_start_offset": row_text.index(value),
                "start_offset": 0,
                "end_offset": len(row_text),
                "parent_start_offset": 0,
                "row_text": row_text,
            }
        )

    selected = choose_structured_table_answer(
        question="강화 확률 알려줘",
        ranked_seed_facts=facts,
        all_facts=facts,
        chunks_by_id={
            chunk_id: {"display_text": display_text}
        },
    )

    assert selected is not None
    assert selected["kind"] == "complete_table"
    assert selected["display_attributes"] == [
        "강화 시도 구간",
        "성공 확률",
    ]


def _multi_table_facts() -> tuple[
    list[dict[str, object]],
    dict[str, dict[str, str]],
]:
    rows = [
        (
            "equipment",
            "table_equipment",
            "document_transcendence",
            "chunk_transcendence",
            "115Lv 장비 초월 비용은 아래와 같습니다.",
            "115Lv 장비 초월 레어",
            "| 레어 | 10개 |",
            "10개",
        ),
        (
            "equipment",
            "table_equipment",
            "document_transcendence",
            "chunk_transcendence",
            "115Lv 장비 초월 비용은 아래와 같습니다.",
            "115Lv 장비 초월 에픽",
            "| 에픽 | 20개 |",
            "20개",
        ),
        (
            "oath",
            "table_oath",
            "document_transcendence",
            "chunk_transcendence",
            "서약 결정 초월 비용은 아래와 같습니다.",
            "서약 결정 초월 레어",
            "| 레어 | 30개 |",
            "30개",
        ),
        (
            "oath",
            "table_oath",
            "document_transcendence",
            "chunk_transcendence",
            "서약 결정 초월 비용은 아래와 같습니다.",
            "서약 결정 초월 에픽",
            "| 에픽 | 40개 |",
            "40개",
        ),
        (
            "reinforcement",
            "table_reinforcement",
            "document_reinforcement",
            "chunk_reinforcement",
            "안전 강화",
            "안전 강화 +0 → 1",
            "| +0 → 1 | 100% |",
            "100%",
        ),
        (
            "reinforcement",
            "table_reinforcement",
            "document_reinforcement",
            "chunk_reinforcement",
            "안전 강화",
            "안전 강화 +1 → 2",
            "| +1 → 2 | 90% |",
            "90%",
        ),
    ]
    chunk_rows: dict[str, list[str]] = {}
    for row in rows:
        chunk_rows.setdefault(row[3], []).append(row[6])
    chunks = {
        chunk_id: {"display_text": "\n".join(text_rows)}
        for chunk_id, text_rows in chunk_rows.items()
    }
    facts: list[dict[str, object]] = []
    for index, (
        kind,
        table_id,
        parent_id,
        chunk_id,
        caption,
        subject,
        row_text,
        value,
    ) in enumerate(rows, 1):
        display_text = chunks[chunk_id]["display_text"]
        start = display_text.index(row_text)
        facts.append(
            {
                "fact_id": f"fact_multi_{index}",
                "table_id": table_id,
                "row_id": f"row_multi_{index}",
                "parent_document_id": parent_id,
                "source_chunk_id": chunk_id,
                "source_id": "dnf_game_guide",
                "title": "강화" if kind == "reinforcement" else "초월",
                "canonical_url": "https://example.invalid",
                "table_caption": caption,
                "subject": subject,
                "attribute": (
                    "성공 확률"
                    if kind == "reinforcement"
                    else "비용"
                ),
                "value": value,
                "value_start_offset": start + row_text.index(value),
                "start_offset": start,
                "end_offset": start + len(row_text),
                "parent_start_offset": start,
                "row_text": row_text,
            }
        )
    return facts, chunks


def _clone_oath_table(
    facts: list[dict[str, object]],
    chunks: dict[str, dict[str, str]],
    *,
    suffix: str,
    first_value: str = "30개",
) -> list[dict[str, object]]:
    source = [
        fact for fact in facts if fact["table_id"] == "table_oath"
    ]
    row_texts = [
        str(fact["row_text"]).replace("30개", first_value)
        for fact in source
    ]
    chunk_id = f"chunk_oath_{suffix}"
    chunks[chunk_id] = {"display_text": "\n".join(row_texts)}
    cloned = []
    for index, (fact, row_text) in enumerate(
        zip(source, row_texts, strict=True),
        1,
    ):
        value = str(fact["value"]).replace("30개", first_value)
        start = chunks[chunk_id]["display_text"].index(row_text)
        cloned.append(
            {
                **fact,
                "fact_id": f"fact_oath_{suffix}_{index}",
                "table_id": f"table_oath_{suffix}",
                "row_id": f"row_oath_{suffix}_{index}",
                "parent_document_id": f"document_oath_{suffix}",
                "source_chunk_id": chunk_id,
                "row_text": row_text,
                "value": value,
                "value_start_offset": start + row_text.index(value),
                "start_offset": start,
                "end_offset": start + len(row_text),
                "parent_start_offset": start,
            }
        )
    return cloned


def test_structured_table_group_matches_two_explicit_subjects() -> None:
    facts, chunks = _multi_table_facts()
    transcendence = [
        fact
        for fact in facts
        if fact["parent_document_id"] == "document_transcendence"
    ]

    selected = choose_structured_table_answer(
        question="장비 초월 비용, 서약 초월 비용 알려줘",
        ranked_seed_facts=[
            transcendence[0],
            transcendence[2],
        ],
        all_facts=transcendence,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "complete_table_group"
    assert [
        view["table_subject"] for view in selected["views"]
    ] == ["115Lv 장비 초월", "서약 결정 초월"]


def test_structured_table_group_collapses_equivalent_official_tables() -> None:
    facts, chunks = _multi_table_facts()
    duplicate = _clone_oath_table(
        facts,
        chunks,
        suffix="duplicate",
    )
    combined = [*facts, *duplicate]
    seeds = [
        next(
            fact
            for fact in facts
            if fact["table_id"] == "table_equipment"
        ),
        next(
            fact
            for fact in facts
            if fact["table_id"] == "table_oath"
        ),
        duplicate[0],
    ]

    selected = choose_structured_table_answer(
        question="장비 초월 비용, 서약 초월 비용 알려줘",
        ranked_seed_facts=seeds,
        all_facts=combined,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "complete_table_group"
    assert len(selected["views"]) == 2


def test_structured_table_group_excludes_non_numeric_sibling_cost_table() -> None:
    facts, chunks = _multi_table_facts()
    chunk_id = "chunk_oath_non_cost"
    noise_rows = [
        "| 광휘의 소울 | 계정 귀속 |",
        "| 미광의 소울 | 교환 불가 |",
    ]
    chunks[chunk_id] = {"display_text": "\n".join(noise_rows)}
    noisy = []
    for index, row_text in enumerate(noise_rows, 1):
        value = row_text.split("|")[2].strip()
        start = chunks[chunk_id]["display_text"].index(row_text)
        noisy.append(
            {
                "fact_id": f"fact_oath_noise_{index}",
                "table_id": "table_oath_noise",
                "row_id": f"row_oath_noise_{index}",
                "parent_document_id": "document_oath_noise",
                "source_chunk_id": chunk_id,
                "source_id": "dnf_game_guide",
                "title": "서약 / 결정",
                "canonical_url": "https://example.invalid",
                "table_caption": (
                    "서약 결정 초월 비용은 아래와 같습니다."
                ),
                "subject": f"서약 결정 초월 소울 {index}",
                "attribute": "거래 타입",
                "value": value,
                "value_start_offset": start + row_text.index(value),
                "start_offset": start,
                "end_offset": start + len(row_text),
                "parent_start_offset": start,
                "row_text": row_text,
            }
        )
    combined = [*facts, *noisy]

    selected = choose_structured_table_answer(
        question="장비 초월 비용, 서약 초월 비용 알려줘",
        ranked_seed_facts=[
            next(
                fact
                for fact in facts
                if fact["table_id"] == "table_equipment"
            ),
            next(
                fact
                for fact in facts
                if fact["table_id"] == "table_oath"
            ),
            noisy[0],
        ],
        all_facts=combined,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "complete_table_group"
    assert {
        view["table_id"] for view in selected["views"]
    } == {"table_equipment", "table_oath"}


def test_structured_table_group_clarifies_conflicting_table_values() -> None:
    facts, chunks = _multi_table_facts()
    conflicting = _clone_oath_table(
        facts,
        chunks,
        suffix="conflict",
        first_value="31개",
    )
    combined = [*facts, *conflicting]

    selected = choose_structured_table_answer(
        question="장비 초월 비용, 서약 초월 비용 알려줘",
        ranked_seed_facts=[
            next(
                fact
                for fact in facts
                if fact["table_id"] == "table_equipment"
            ),
            next(
                fact
                for fact in facts
                if fact["table_id"] == "table_oath"
            ),
            conflicting[0],
        ],
        all_facts=combined,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "table_group_clarification"
    assert selected["ambiguous_targets"] == [
        "서약 초월 비용 알려줘"
    ]


@pytest.mark.parametrize(
    ("question", "expected_subject"),
    [
        ("장비 초월 비용 알려줘", "115Lv 장비 초월"),
        ("서약 초월 비용 알려줘", "서약 결정 초월"),
    ],
)
def test_structured_table_group_preserves_single_subject_questions(
    question: str,
    expected_subject: str,
) -> None:
    facts, chunks = _multi_table_facts()
    transcendence = [
        fact
        for fact in facts
        if fact["parent_document_id"] == "document_transcendence"
    ]

    selected = choose_structured_table_answer(
        question=question,
        ranked_seed_facts=[
            transcendence[0],
            transcendence[2],
        ],
        all_facts=transcendence,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "complete_table"
    assert selected["view"]["table_subject"] == expected_subject


def test_structured_table_group_clarifies_generic_subject() -> None:
    facts, chunks = _multi_table_facts()
    transcendence = [
        fact
        for fact in facts
        if fact["parent_document_id"] == "document_transcendence"
    ]

    selected = choose_structured_table_answer(
        question="초월 비용 알려줘",
        ranked_seed_facts=[
            transcendence[0],
            transcendence[2],
        ],
        all_facts=transcendence,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "table_group_clarification"
    assert selected["ambiguous_targets"] == ["초월 비용 알려줘"]


def test_structured_table_group_returns_partial_for_missing_subject() -> None:
    facts, chunks = _multi_table_facts()
    equipment = [
        fact
        for fact in facts
        if fact["table_id"] == "table_equipment"
    ]

    selected = choose_structured_table_answer(
        question="장비 초월 비용, 서약 초월 비용 알려줘",
        ranked_seed_facts=[equipment[0]],
        all_facts=equipment,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "partial_table_group"
    assert selected["unresolved_targets"] == [
        "서약 초월 비용 알려줘"
    ]
    assert selected["views"][0]["table_subject"] == "115Lv 장비 초월"


def test_structured_table_group_can_join_two_seed_parents() -> None:
    facts, chunks = _multi_table_facts()
    equipment = next(
        fact
        for fact in facts
        if fact["table_id"] == "table_equipment"
    )
    reinforcement = next(
        fact
        for fact in facts
        if fact["table_id"] == "table_reinforcement"
    )

    selected = choose_structured_table_answer(
        question="장비 초월 비용과 강화 확률 알려줘",
        ranked_seed_facts=[equipment, reinforcement],
        all_facts=facts,
        chunks_by_id=chunks,
    )

    assert selected is not None
    assert selected["kind"] == "complete_table_group"
    assert {
        view["table_subject"] for view in selected["views"]
    } == {"115Lv 장비 초월", "안전 강화"}


def test_structured_table_group_renderer_bypasses_qwen() -> None:
    facts, chunks = _multi_table_facts()
    transcendence = [
        fact
        for fact in facts
        if fact["parent_document_id"] == "document_transcendence"
    ]
    selected = choose_structured_table_answer(
        question="장비 초월 비용, 서약 초월 비용 알려줘",
        ranked_seed_facts=[
            transcendence[0],
            transcendence[2],
        ],
        all_facts=transcendence,
        chunks_by_id=chunks,
    )
    assert selected is not None

    runtime = FreeMinimalClaimV2.__new__(FreeMinimalClaimV2)
    runtime._table_facts = transcendence
    runtime._candidate_rows = lambda selected_rows: []
    result = runtime._render_structured_table_result(
        "장비 초월 비용, 서약 초월 비용 알려줘",
        selected_answer=selected,
        selected=[],
        route={},
        retrieval_ms=1.0,
        table_ms=2.0,
        started=free_minimal_claim_v2.time.perf_counter(),
    )

    assert result["response_mode"] == "full_answer"
    assert result["generation"]["mode"] == (
        "bypassed_for_structured_table"
    )
    assert len(result["requirements"]) == 2
    assert len(result["table_views"]) == 2
    assert all(
        requirement["status"] == "supported_exact"
        and requirement["citations"]
        for requirement in result["requirements"]
    )
    assert "115Lv 장비 초월" in result["rendered_answer"]
    assert "서약 결정 초월" in result["rendered_answer"]


def test_natural_renderer_hides_chunk_sha_and_uses_korean_labels() -> None:
    rendered = render_natural_answer(
        [
            {
                "status": "supported_exact",
                "subject": "상품 A",
                "relation": "price",
                "answer": "3,100 세라",
                "citations": [
                    {"chunk_id": "chunk_sha256_price"},
                    {"chunk_id": "chunk_sha256_price"},
                ],
            },
            {
                "status": "supported_exact",
                "subject": "상품 A",
                "relation": "trade_type",
                "answer": "계정귀속",
                "citations": [{"chunk_id": "chunk_sha256_price"}],
            },
        ]
    )

    assert rendered == (
        "- 가격은 3,100 세라입니다. [근거 1]\n"
        "- 거래 타입은 계정귀속입니다. [근거 1]"
    )
    assert "chunk_sha256" not in rendered
