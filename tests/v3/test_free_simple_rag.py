import time

import pytest

import src.v3.free_simple_rag as free_simple_rag
from src.v3.free_simple_rag import (
    answer_simple_rag_from_candidates,
    cap_response_mode_to_model,
    render_simple_natural_answer,
)


def test_simple_renderer_uses_short_evidence_numbers() -> None:
    rendered = render_simple_natural_answer(
        [
            {
                "status": "supported_exact",
                "answer": "108,921",
                "citations": [
                    {"chunk_id": "chunk_sha256_a"},
                    {"chunk_id": "chunk_sha256_a"},
                ],
            },
            {
                "status": "supported_exact",
                "answer": "계정귀속",
                "citations": [{"chunk_id": "chunk_sha256_b"}],
            },
        ]
    )

    assert rendered == (
        "- 108,921 [근거 1]\n"
        "- 계정귀속 [근거 2]"
    )
    assert "chunk_sha256" not in rendered


def test_response_mode_can_be_downgraded_but_not_upgraded() -> None:
    assert (
        cap_response_mode_to_model(
            "full_answer",
            model_mode="partial_answer",
        )
        == "partial_answer"
    )
    assert (
        cap_response_mode_to_model(
            "abstain",
            model_mode="partial_answer",
        )
        == "abstain"
    )
    assert (
        cap_response_mode_to_model(
            "full_answer",
            model_mode=None,
        )
        == "full_answer"
    )


def test_server_ref_mode_restores_citation_without_model_quote(
    monkeypatch,
) -> None:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": "# Transcendence\nEquipment transcendence is available.",
            "status": "current",
            "default_exposure": True,
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_game_guide",
            "source_kind": "game_guide",
            "title": "Transcendence",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }

    def fake_generate(**kwargs):
        assert '"evidence_ref": "E1"' in kwargs["prompt"]
        assert '"chunk_id"' not in kwargs["prompt"]
        return {
            "output": {
                "question_time_scope": "current",
                "result": {
                    "status": "supported",
                    "answer": "Equipment transcendence",
                    "evidence_refs": ["E1"],
                },
            },
            "model": "test",
            "provider": "test",
            "thinking_enabled": False,
            "latency_ms": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(
        free_simple_rag,
        "generate_evidence_ref_output_native",
        fake_generate,
    )
    result = answer_simple_rag_from_candidates(
        question="What type is available?",
        model="test",
        timeout=1.0,
        selected=[{"chunk_id": "c1"}],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={"d1": {"validity_state": "current"}},
        route={"temporal_as_of": "2026-07-29"},
        candidates=[{"chunk_id": "c1"}],
        retrieval_ms=1.0,
        started=time.perf_counter(),
        evidence_mode="server_ref",
    )

    assert result["evidence_mode"] == "server_ref"
    assert result["evidence_unit_count"] >= 1
    assert result["response_mode"] == "full_answer"
    citation = result["requirements"][0]["citations"][0]
    assert citation["chunk_id"] == "c1"
    assert chunks["c1"]["display_text"][
        citation["start_char"] : citation["end_char"]
    ] == citation["text"]


def test_atomic_ref_mode_sends_sentence_units_and_restores_slice(
    monkeypatch,
) -> None:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": (
                "# Transcendence\n"
                "Equipment transcendence is available. "
                "Its cost depends on rarity."
            ),
            "heading_path": ["Guide"],
            "status": "current",
            "default_exposure": True,
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_game_guide",
            "source_kind": "game_guide",
            "title": "Transcendence",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }

    def fake_generate(**kwargs):
        assert "Equipment transcendence is available." in kwargs["prompt"]
        assert "Its cost depends on rarity." in kwargs["prompt"]
        return {
            "output": {
                "question_time_scope": "current",
                "result": {
                    "status": "supported",
                    "answer": "Equipment transcendence",
                    "evidence_refs": ["E1"],
                },
            },
            "model": "test",
            "provider": "test",
            "thinking_enabled": False,
            "latency_ms": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(
        free_simple_rag,
        "generate_evidence_ref_output_native",
        fake_generate,
    )
    result = answer_simple_rag_from_candidates(
        question="What transcendence is available?",
        model="test",
        timeout=1.0,
        selected=[{"chunk_id": "c1"}],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={"d1": {"validity_state": "current"}},
        route={"temporal_as_of": "2026-07-29"},
        candidates=[{"chunk_id": "c1"}],
        retrieval_ms=1.0,
        started=time.perf_counter(),
        evidence_mode="atomic_ref",
    )

    assert result["evidence_mode"] == "atomic_ref"
    assert result["evidence_unit_count"] == 2
    citation = result["requirements"][0]["citations"][0]
    assert citation["text"] == "Equipment transcendence is available."


def test_exact_quote_mode_passes_retry_generation_options(
    monkeypatch,
) -> None:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": "The supported value is 1.",
            "status": "current",
            "default_exposure": True,
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_game_guide",
            "source_kind": "game_guide",
            "title": "Value",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "output": {
                "question_time_scope": "current",
                "response_mode": "full_answer",
                "requirements": [
                    {
                        "question_part": "value",
                        "status": "supported",
                        "answer": "1",
                        "evidence": [
                            {
                                "candidate_ref": "1",
                                "quote": "The supported value is 1.",
                            }
                        ],
                    }
                ],
            },
            "model": "test",
            "provider": "test",
            "thinking_enabled": False,
            "latency_ms": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(
        free_simple_rag,
        "generate_grounded_output_native",
        fake_generate,
    )
    result = answer_simple_rag_from_candidates(
        question="What is the value?",
        model="test",
        timeout=1.0,
        selected=[{"chunk_id": "c1"}],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={
            "d1": {
                "validity_state": "current",
                "retrieval_action_current": "allow",
                "revision_id": "r1",
            }
        },
        route={"temporal_as_of": "2026-07-29"},
        candidates=[{"chunk_id": "c1"}],
        retrieval_ms=1.0,
        started=time.perf_counter(),
        evidence_mode="exact_quote",
        exact_quote_generation_options={
            "num_ctx": 12288,
            "num_predict": 1800,
            "seed": 42,
        },
    )

    assert captured["num_ctx"] == 12288
    assert captured["num_predict"] == 1800
    assert captured["seed"] == 42
    request = result["generation"]["request"]
    assert request["timeout_seconds"] == 1.0
    assert request["candidate_count"] == 1
    assert request["max_output_tokens"] == 1800


def test_exact_quote_temporal_annotations_are_opt_in(
    monkeypatch,
) -> None:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": (
                "2026.06.02 15:00\n"
                "6/4(목) 점검 중 업데이트 되는 내용 안내 드립니다."
            ),
            "status": "current",
            "default_exposure": True,
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_update",
            "source_kind": "patch_note",
            "title": "시즌 업데이트",
            "published_at": "2026-06-02",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }

    def fake_generate(**kwargs):
        assert '"role": "published_at"' in kwargs["prompt"]
        assert '"role": "effective_at"' in kwargs["prompt"]
        return {
            "output": {
                "question_time_scope": "current",
                "response_mode": "full_answer",
                "requirements": [
                    {
                        "question_part": "업데이트 적용일",
                        "status": "supported",
                        "answer": "6/4(목)",
                        "evidence": [
                            {
                                "candidate_ref": "1",
                                "quote": (
                                    "6/4(목) 점검 중 업데이트 되는 "
                                    "내용 안내 드립니다."
                                ),
                            }
                        ],
                    }
                ],
            },
            "model": "test",
            "provider": "test",
            "thinking_enabled": False,
            "latency_ms": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(
        free_simple_rag,
        "generate_grounded_output_native",
        fake_generate,
    )
    result = answer_simple_rag_from_candidates(
        question="업데이트는 언제 적용됐어?",
        model="test",
        timeout=1.0,
        selected=[{"chunk_id": "c1"}],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={
            "d1": {
                "validity_state": "current",
                "retrieval_action_current": "allow",
                "revision_id": "r1",
            }
        },
        route={"temporal_as_of": "2026-07-29"},
        candidates=[{"chunk_id": "c1"}],
        retrieval_ms=1.0,
        started=time.perf_counter(),
        evidence_mode="exact_quote",
        include_temporal_role_annotations=True,
    )

    assert result["response_mode"] == "full_answer"
    assert result["generation"]["request"][
        "temporal_role_annotations"
    ] is True


def test_exact_quote_timeout_carries_safe_request_diagnostics(
    monkeypatch,
) -> None:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": "The supported value is 1.",
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_game_guide",
            "title": "Value",
        }
    }

    monkeypatch.setattr(
        free_simple_rag,
        "generate_grounded_output_native",
        lambda **kwargs: (_ for _ in ()).throw(
            TimeoutError("generation timed out")
        ),
    )

    with pytest.raises(TimeoutError) as caught:
        answer_simple_rag_from_candidates(
            question="What is the value?",
            model="test",
            timeout=0.25,
            selected=[{"chunk_id": "c1"}],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document={},
            route={},
            candidates=[{"chunk_id": "c1"}],
            retrieval_ms=1.0,
            started=time.perf_counter(),
        )

    diagnostics = caught.value.generation_diagnostics
    assert diagnostics["timeout_seconds"] == 0.25
    assert diagnostics["prompt_chars"] > 0
    assert diagnostics["candidate_count"] == 1
    assert "prompt" not in diagnostics


def test_exact_quote_openai_backend_passes_only_output_limit(
    monkeypatch,
) -> None:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": "The supported value is 1.",
            "status": "current",
            "default_exposure": True,
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_game_guide",
            "source_kind": "game_guide",
            "title": "Value",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "output": {
                "question_time_scope": "current",
                "response_mode": "full_answer",
                "requirements": [
                    {
                        "question_part": "value",
                        "status": "supported",
                        "answer": "1",
                        "evidence": [
                            {
                                "candidate_ref": "1",
                                "quote": "The supported value is 1.",
                            }
                        ],
                    }
                ],
            },
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(
        free_simple_rag,
        "generate_grounded_output",
        fake_generate,
    )
    result = answer_simple_rag_from_candidates(
        question="What is the value?",
        model="test",
        timeout=1.0,
        selected=[{"chunk_id": "c1"}],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={"d1": {"validity_state": "current"}},
        route={"temporal_as_of": "2026-07-29"},
        candidates=[{"chunk_id": "c1"}],
        retrieval_ms=1.0,
        started=time.perf_counter(),
        evidence_mode="exact_quote",
        exact_quote_backend="openai_compatible",
        exact_quote_generation_options={"num_predict": 1200},
    )

    assert captured["max_output_tokens"] == 1200
    assert result["exact_quote_backend"] == "openai_compatible"
