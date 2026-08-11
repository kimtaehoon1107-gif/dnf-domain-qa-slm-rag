from __future__ import annotations

import json
from unittest.mock import Mock

import app.product_free_rag_demo as demo
from src.v3.product_free_rag import (
    DEFAULT_PRODUCT_BM25_MANIFEST,
    DEFAULT_PRODUCT_CHUNKS,
    DEFAULT_PRODUCT_DENSE_MANIFEST,
    DEFAULT_PRODUCT_RUNTIME_SNAPSHOT,
)


def test_corrupted_question_is_rejected_before_runtime(monkeypatch):
    runtime_factory = Mock(side_effect=AssertionError("RAG must not run"))
    monkeypatch.setattr(demo, "_runtime", runtime_factory)

    answer, citations, candidates, raw, pending = demo.answer_question(
        "????????????",
        "product_free_rag_v1",
    )

    payload = json.loads(raw)
    assert "실행 실패" in answer
    assert payload["error_type"] == "ValueError"
    assert "received_utf8_bytes=" in payload["error"]
    assert citations == []
    assert candidates == []
    assert pending is None
    runtime_factory.assert_not_called()


def test_normal_korean_question_passes_input_validation():
    demo.validate_demo_question("미카엘라 레이드 보상 차이 알려줘")


def test_demo_cli_defaults_match_canonical_runtime_paths():
    args = demo.build_argument_parser().parse_args([])

    assert args.preinitialize_retrieval is False
    assert args.chunks == DEFAULT_PRODUCT_CHUNKS
    assert args.bm25_manifest == DEFAULT_PRODUCT_BM25_MANIFEST
    assert args.dense_manifest == DEFAULT_PRODUCT_DENSE_MANIFEST
    assert args.metadata_snapshot == DEFAULT_PRODUCT_RUNTIME_SNAPSHOT

    preinitialized = demo.build_argument_parser().parse_args(
        ["--preinitialize-retrieval"]
    )
    assert preinitialized.preinitialize_retrieval is True


def test_product_runtime_receives_configured_paths(monkeypatch, tmp_path):
    chunks = tmp_path / "chunks.jsonl"
    bm25 = tmp_path / "bm25.json"
    dense = tmp_path / "dense.json"
    metadata_snapshot = tmp_path / "metadata.json"
    runtime = object()
    constructor = Mock(return_value=runtime)
    monkeypatch.setattr(demo, "ProductFreeRAG", constructor)
    monkeypatch.setattr(demo, "_RUNTIMES", {})
    monkeypatch.setattr(
        demo,
        "_RUNTIME_PATHS",
        {
            "chunks_path": chunks,
            "bm25_manifest_path": bm25,
            "dense_manifest_path": dense,
            "metadata_snapshot_path": metadata_snapshot,
        },
    )

    assert demo._runtime("product_free_rag_v1") is runtime
    constructor.assert_called_once()
    kwargs = constructor.call_args.kwargs
    assert kwargs["chunks_path"] == chunks
    assert kwargs["bm25_manifest_path"] == bm25
    assert kwargs["dense_manifest_path"] == dense
    assert kwargs["metadata_snapshot_path"] == metadata_snapshot
    assert kwargs["use_table_comparison_reservation"] is True
    assert kwargs["use_server_availability_rendering"] is True
    assert kwargs["use_server_content_kind_rendering"] is True
