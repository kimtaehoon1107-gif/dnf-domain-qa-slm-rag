from __future__ import annotations

import argparse
import html
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import sentence_transformers
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import gradio as gr

from src.io_utils import read_jsonl
from src.v3.assemble_table_group_answers import assemble_table_group_answers
from src.v3.build_bm25 import SearchPolicy
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_extractive_assembler_v3 import segment_chunk_nonoverlap
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_requirement_reranker import requirement_text
from src.v3.evaluate_table_atomic_facts_arm1 import (
    RERANKER_K as TABLE_RERANKER_K,
    RERANKER_THRESHOLD as TABLE_RERANKER_THRESHOLD,
    search_sidecar,
    select_reranked_children,
)
from src.v3.evaluate_semantic_requirement_planner import (
    PLANNER_SYSTEM_PROMPT,
    _configured_base_url,
    _fixed_prompt_hash,
    _json_request,
    _ollama_api_url,
    run_planner,
    runtime_metadata,
)
from src.v3.grounded_answer_generator import (
    apply_table_value_shape_gate,
    compose_backbone_answer,
)
from src.v3.question_router import (
    DEFAULT_AS_OF,
    DEFAULT_OVERLAY,
    build_source_entity_index,
    route_and_retrieve_with_embedding,
    route_question,
)
from src.v3.rerank_evidence import select_reranked_evidence
from src.v3.requirement_value_shape import apply_value_shape_veto
from src.v3.retrieve_v3 import load_runtime_artifacts, retrieve_with_embedding
from src.v3.score_evidence_reranker import (
    BATCH_SIZE,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
)
from src.v3.select_evidence import classify_answerability


DEMO_VERSION = "dnf-v3-backbone-gradio-demo-v1.2-v3.2-promoted-default"
RUNTIME_PROMOTION_STATUS = "v3.2_development_canonical_promoted_by_user_authorization"
DEFAULT_PLANNER_MODEL = "qwen3:8b"
DEFAULT_GENERATOR_MODEL = "qwen3:8b"
DEFAULT_PORT = 7862
TOP_K = 10
BOUNDED_SOURCE_EXPANSION_LIMIT = 2
ASSEMBLER_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_"
    "9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json"
)
GLOBAL_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DUPLICATE_FAMILY_OVERLAY = Path(
    "data/v3/structured/duplicate_family_overlay_v3.2_"
    "d71e7184b95a4bbdf8a4748b24daf5ce6b2d67834507660f905ffc869faaa336.jsonl"
)
TABLE_INDEX_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_index_manifest_"
    "423dfd6ae35bbfa5db1cef0ea1caa61df547ed99c508c998fd134f44f1c4f79d.json"
)
CANONICAL_RUNTIME_POINTER = Path("data/v3/runtime/canonical_runtime_v3_2.json")
EXPECTED_DIRTY_CHUNKS_SHA256 = (
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885"
)
EXPECTED_PLANNER_PROMPT_SHA256 = (
    "01ddcf34498276b4896f5c628f53fa874047e8a989b3a5df3e405bd43c87d948"
)

HONEST_BANNER = (
    "⚠️ **개발 데모/runtime** · 기존 **미승격** v3.2 후보를 사용자 승인으로 "
    "**기본 canonical view에 승격** · 현재 개발 천장 약 **9/82 false-full** 존재 · "
    "production-ready 또는 최종 benchmark 통과를 뜻하지 않습니다. "
    "답변은 자유 생성 없이 원문 추출 인용만 표시합니다. "
    "exact 인용은 원문 복사를 뜻할 뿐 의미 정답 보장이 아니므로, 사실과 속성 귀속을 직접 확인하세요. "
    "새 sealed canary는 실행하지 않았고 기존 95문항 무회귀 근거로 승격했습니다."
)

EXAMPLE_QUESTIONS = [
    "초월 가격 알려줘.",
    "아라드 낚시왕에서 낚시는 하루 몇 번 가능하고 언제 초기화돼?",
    "기본 피로도는 캐릭터당 얼마고 PC방에서는 추가로 얼마나 받아?",
    "내 계정 제재 상태 지금 확인해봐.",
    "지금 경매장에서 웨딩 아바타 시세 얼마야?",
    "내일 서울 비 와? 던파 문서로 알려줄 수 있어?",
]


def _require_nonempty_question(question: str) -> str:
    normalized = " ".join((question or "").split())
    if not normalized:
        raise RuntimeError("질문을 입력해 주세요.")
    return normalized


def _requirement_label(requirement: dict[str, Any]) -> str:
    subject = str(requirement.get("subject", "")).strip()
    relation = str(requirement.get("relation", "")).strip()
    return " — ".join(part for part in (subject, relation) if part) or "요구사항"


def _citation_metadata(
    chunk_id: str,
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chunk = chunks_by_id[chunk_id]
    document = documents_by_id[chunk["parent_document_id"]]
    return {
        "chunk_id": chunk_id,
        "parent_document_id": chunk["parent_document_id"],
        "source_id": document["source_id"],
        "title": document["title"],
        "canonical_url": document["canonical_url"],
        "published_at": document.get("published_at"),
        "updated_at": document.get("updated_at"),
        "revision_id": document.get("revision_id"),
        "status": document.get("status"),
        "is_current_revision": document.get("is_current_revision"),
    }


def build_duplicate_family_member_index(
    families: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for family in families:
        for member in family["members"]:
            document_id = member["parent_document_id"]
            if document_id in output:
                raise RuntimeError(f"Document belongs to multiple duplicate families: {document_id}")
            output[document_id] = {
                "duplicate_family_id": family["duplicate_family_id"],
                "duplicate_family_relation_kind": family["relation_kind"],
                "duplicate_family_review_status": family["review_status"],
                "source_role": member["source_role"],
                "preferred_source_by_attribute": family["preferred_source_by_attribute"],
            }
    return output


def enrich_citation_metadata(
    metadata: dict[str, Any],
    *,
    temporal_by_document: dict[str, dict[str, Any]],
    family_by_document: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(metadata)
    document_id = metadata["parent_document_id"]
    temporal = temporal_by_document.get(document_id)
    if temporal is not None:
        enriched["validity_state"] = temporal["validity_state"]
        enriched["validity_reason"] = temporal["validity_reason"]
        enriched["retrieval_action_current"] = temporal["retrieval_action_current"]
        enriched["last_verified_at"] = temporal.get("last_verified_at")
        enriched["temporal_warning"] = (
            "현재 공식 사이트에서 노출되지만 명시적 유효기간 또는 최신 revision 검증이 없습니다."
            if temporal["validity_state"] == "current_unverified"
            else None
        )
    family = family_by_document.get(document_id)
    if family is not None:
        enriched.update(family)
    return enriched


def filter_hits_by_global_temporal(
    hits: list[dict[str, Any]],
    *,
    time_scope: str,
    temporal_by_document: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if time_scope != "current":
        return list(hits), []
    allowed = []
    denied = []
    for hit in hits:
        temporal = temporal_by_document.get(hit["parent_document_id"])
        if temporal is not None and temporal["retrieval_action_current"] == "deny":
            denied.append(hit)
        else:
            allowed.append(hit)
    return allowed, denied


def validate_exact_citation(span: dict[str, Any], source_text: str) -> None:
    start = int(span["start_char"])
    end = int(span["end_char"])
    if start < 0 or end < start or end > len(source_text):
        raise RuntimeError(f"Invalid citation offset: {span['span_id']}")
    if source_text[start:end] != span["text"]:
        raise RuntimeError(f"Citation is not an exact source slice: {span['span_id']}")


def summarize_grounded_decisions(
    decisions: list[dict[str, Any]],
    chunk_to_parent: dict[str, str],
) -> dict[str, Any]:
    supported = [
        decision for decision in decisions if decision["status"] == "supported_exact"
    ]
    if not supported:
        return {"route_action": "abstain", "response_mode": "abstain"}

    response_mode = (
        "full_answer" if len(supported) == len(decisions) else "partial_answer"
    )
    parent_sets = [
        {chunk_to_parent[span["chunk_id"]] for span in decision["spans"]}
        for decision in supported
    ]
    cross_parent = (
        len(supported) >= 2
        and len(supported) == len(decisions)
        and all(parent_sets)
        and not set.intersection(*parent_sets)
    )
    return {
        "route_action": "decompose_candidate" if cross_parent else "retrieve",
        "response_mode": response_mode,
    }


def bounded_candidate_sources(route: dict[str, Any]) -> tuple[str, ...]:
    output = list(route["source_ids"])
    candidates = route.get("routing_signals", {}).get("candidate_sources", [])
    for source_id in candidates[:BOUNDED_SOURCE_EXPANSION_LIMIT]:
        if source_id not in output:
            output.append(source_id)
    return tuple(output)


def shape_audit(
    requirements: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    audits = []
    supported_after_veto = 0
    for requirement, decision in zip(requirements, decisions, strict=True):
        checked, audit = apply_value_shape_veto(requirement, decision)
        supported_after_veto += checked["status"] == "supported_exact"
        audits.append(audit)
    return {
        "supported_after_veto": supported_after_veto,
        "veto_count": sum(row["vetoed"] for row in audits),
        "requirements": audits,
    }


def _route_only_result(
    *,
    question: str,
    requirements: list[dict[str, Any]],
    route: dict[str, Any],
    planner_log: dict[str, Any],
    planner_runtime: dict[str, Any],
) -> dict[str, Any]:
    action = route["route_action"]
    if action == "realtime_api":
        status = "abstain"
        message = "개인 계정 또는 실시간 상태는 정적 공식 문서에서 확인할 수 없습니다."
    elif action == "reject":
        status = "reject"
        message = "던파 공식 문서 코퍼스로 근거 있는 답변을 제공할 수 없는 질문입니다."
    else:
        status = "abstain"
        message = "이 개발 데모에서 검증된 단일 검색 경로로는 답을 확인할 수 없습니다."
    return {
        "demo_version": DEMO_VERSION,
        "question": question,
        "route": route,
        "response_mode": status,
        "message": message,
        "requirements": [
            {
                "requirement": requirement,
                "status": status,
                "message": message,
                "citations": [],
            }
            for requirement in requirements
        ],
        "planner": {"runtime": planner_runtime, "call": planner_log},
        "provenance": {
            "dirty_canonical_chunks_sha256": EXPECTED_DIRTY_CHUNKS_SHA256,
            "planner_prompt_sha256": EXPECTED_PLANNER_PROMPT_SHA256,
            "as_of": DEFAULT_AS_OF,
        },
    }


class DemoBackbone:
    def __init__(
        self,
        *,
        root: Path,
        planner_model: str = DEFAULT_PLANNER_MODEL,
        device: str | None = None,
        timeout: float = 180.0,
        enable_v3_2_candidates: bool = True,
        enable_bounded_fallback: bool = False,
        enable_generation: bool = False,
        generator_model: str = DEFAULT_GENERATOR_MODEL,
        generation_evidence_scope: str = "chunk",
        answer_generator: Any | None = None,
    ) -> None:
        self.root = root.resolve()
        self.planner_model = planner_model
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.timeout = timeout
        self.enable_v3_2_candidates = enable_v3_2_candidates
        self.enable_bounded_fallback = enable_bounded_fallback
        self.enable_generation = enable_generation
        self.generator_model = generator_model
        self.generation_evidence_scope = generation_evidence_scope
        self._answer_generator = answer_generator
        self._lock = threading.Lock()
        self._artifacts: Any | None = None
        self._overlay_rows: list[dict[str, Any]] | None = None
        self._source_entity_index: dict[str, list[frozenset[str]]] | None = None
        self._embedder: SentenceTransformer | None = None
        self._reranker: CrossEncoder | None = None
        self._planner_runtime: dict[str, Any] | None = None
        self._assembler_config: dict[str, Any] | None = None
        self._global_temporal_by_document: dict[str, dict[str, Any]] = {}
        self._family_by_document: dict[str, dict[str, Any]] = {}
        self._table_bm25: dict[str, Any] | None = None
        self._table_facts: list[dict[str, Any]] = []
        self._table_embeddings: np.ndarray | None = None
        self._canonical_runtime_manifest_ref: dict[str, Any] | None = None
        self._table_facts_path: str | None = None

    def _generate_answer_text(self, request: dict[str, Any]) -> str:
        if self._answer_generator is not None:
            return str(self._answer_generator(request) or "")
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required (use the Ollama dummy key)")
        if self.generator_model.startswith("qwen3"):
            response = _json_request(
                _ollama_api_url(_configured_base_url(), "/api/chat"),
                {
                    "model": self.generator_model,
                    "messages": [
                        {"role": "system", "content": request["system"]},
                        {"role": "user", "content": request["user"]},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "num_predict": 600},
                },
                self.timeout,
            )
            content = response.get("message", {}).get("content")
            if not content:
                raise RuntimeError("Ollama native generator returned no answer text")
            return str(content)
        from openai import OpenAI

        response = OpenAI(max_retries=1, timeout=self.timeout).chat.completions.create(
            model=self.generator_model,
            messages=[
                {"role": "system", "content": request["system"]},
                {"role": "user", "content": request["user"]},
            ],
            temperature=0,
            max_tokens=600,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Generator returned no answer text")
        return content

    def _generation_chunk_texts(
        self, result: dict[str, Any]
    ) -> dict[str, str] | None:
        """Parent-chunk text for the cited chunks, when the model may see whole passages.

        On by default. Measured on the frozen 95 against the same backbone: handing the
        model the parent chunk instead of the selected spans took correct gold values
        from 16 to 26 and wrong answers from 22 to 12, with generation errors staying at
        zero. Set the scope to "span" to restore span-only evidence.
        """

        if not getattr(self, "generation_evidence_scope", "span") == "chunk":
            return None
        if self._artifacts is None:
            return None
        texts: dict[str, str] = {}
        for item in result.get("requirements", []):
            for citation in item.get("citations", []):
                chunk_id = citation.get("chunk_id")
                chunk = self._artifacts.chunks_by_id.get(chunk_id)
                if chunk_id and chunk:
                    texts[chunk_id] = str(
                        chunk.get("display_text") or chunk.get("text") or ""
                    )
        return texts or None

    def _finalize_result(
        self,
        result: dict[str, Any],
        *,
        started: float,
    ) -> dict[str, Any]:
        generation_enabled = bool(getattr(self, "enable_generation", False))
        generator_model = str(
            getattr(self, "generator_model", DEFAULT_GENERATOR_MODEL)
        )
        if not generation_enabled:
            result["generation"] = {
                "enabled": False,
                "model": generator_model,
                "mode": "disabled",
                "used_generated_text": False,
            }
        else:
            generation_started = time.perf_counter()
            try:
                composed = compose_backbone_answer(
                    result,
                    generate=self._generate_answer_text,
                    chunk_text_by_id=self._generation_chunk_texts(result),
                )
                result["generation"] = {
                    "enabled": True,
                    "model": generator_model,
                    **composed,
                    "latency_ms": round(
                        (time.perf_counter() - generation_started) * 1000,
                        3,
                    ),
                }
            except Exception as exc:
                result["generation"] = {
                    "enabled": True,
                    "model": generator_model,
                    "mode": "generation_error",
                    "answer_text": "",
                    "used_generated_text": False,
                    "verification": None,
                    "error": str(exc),
                    "latency_ms": round(
                        (time.perf_counter() - generation_started) * 1000,
                        3,
                    ),
                }
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def _initialize(self) -> None:
        if self._artifacts is not None:
            return
        pointer_path = self.root / CANONICAL_RUNTIME_POINTER
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("status") != "canonical_v3_2_development_default_promoted":
            raise RuntimeError("v3.2 canonical runtime pointer is not promoted")
        manifest_ref = pointer["manifest"]
        manifest_path = self.root / manifest_ref["path"]
        if file_sha256(manifest_path) != manifest_ref["sha256"]:
            raise RuntimeError("v3.2 canonical runtime manifest hash mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["canonical_runtime"]["table_index_manifest"] != TABLE_INDEX_MANIFEST.as_posix():
            raise RuntimeError("v3.2 canonical runtime table index manifest mismatch")
        self._canonical_runtime_manifest_ref = dict(manifest_ref)
        if _fixed_prompt_hash(PLANNER_SYSTEM_PROMPT) != EXPECTED_PLANNER_PROMPT_SHA256:
            raise RuntimeError("Frozen planner prompt SHA-256 differs from the demo contract")
        self._artifacts = load_runtime_artifacts(self.root)
        chunks_path = self._artifacts.provenance["chunks_path"]
        if EXPECTED_DIRTY_CHUNKS_SHA256 not in chunks_path:
            raise RuntimeError("The demo must use the frozen dirty canonical chunks")
        self._overlay_rows = read_jsonl(self.root / DEFAULT_OVERLAY)
        self._source_entity_index = build_source_entity_index(
            list(self._artifacts.documents_by_id.values()),
            list(self._artifacts.chunks_by_id.values()),
        )
        self._planner_runtime = runtime_metadata(self.planner_model, self.timeout)
        manifest = json.loads(
            (self.root / ASSEMBLER_MANIFEST).read_text(encoding="utf-8")
        )
        self._assembler_config = dict(manifest["selected_configuration"])
        if manifest["model"]["name"] != MODEL_NAME:
            raise RuntimeError("Frozen assembler reranker model differs from runtime")

        model_info = self._artifacts.dense_model
        self._embedder = SentenceTransformer(
            model_info["model_name"],
            device=self.device,
            local_files_only=True,
        )
        self._embedder.max_seq_length = model_info["max_sequence_length"]
        self._reranker = CrossEncoder(
            MODEL_NAME,
            revision=MODEL_REVISION,
            max_length=MAX_LENGTH,
            device=self.device,
            local_files_only=True,
        )
        if self.enable_v3_2_candidates:
            temporal_rows = read_jsonl(self.root / GLOBAL_TEMPORAL_OVERLAY)
            self._global_temporal_by_document = {
                row["document_id"]: row for row in temporal_rows
            }
            if len(self._global_temporal_by_document) != len(temporal_rows):
                raise RuntimeError("Duplicate document_id in global temporal overlay")
            self._family_by_document = build_duplicate_family_member_index(
                read_jsonl(self.root / DUPLICATE_FAMILY_OVERLAY)
            )
            index_manifest = json.loads(
                (self.root / TABLE_INDEX_MANIFEST).read_text(encoding="utf-8")
            )
            bm25_path = self.root / index_manifest["bm25"]["path"]
            metadata_path = self.root / index_manifest["dense"]["metadata_path"]
            embedding_path = self.root / index_manifest["dense"]["path"]
            self._table_facts_path = index_manifest["dense"]["metadata_path"]
            for path, expected in (
                (bm25_path, index_manifest["bm25"]["sha256"]),
                (metadata_path, index_manifest["dense"]["metadata_sha256"]),
                (embedding_path, index_manifest["dense"]["sha256"]),
            ):
                if file_sha256(path) != expected:
                    raise RuntimeError(f"Frozen table sidecar hash mismatch: {path}")
            self._table_bm25 = json.loads(bm25_path.read_text(encoding="utf-8"))
            self._table_facts = read_jsonl(metadata_path)
            self._table_embeddings = np.fromfile(embedding_path, dtype="<f4").reshape(
                len(self._table_facts), index_manifest["dense"]["dimension"]
            )

    def _plan(self, question: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows, logs = run_planner(
            [{"case_id": "demo_case", "question": question}],
            model=self.planner_model,
            batch_size=1,
            timeout=self.timeout,
        )
        return rows[0]["requirements"], logs[0]

    def _encode(self, question: str) -> np.ndarray:
        assert self._embedder is not None
        encoded = self._embedder.encode(
            [question],
            batch_size=1,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(encoded[0], dtype="<f4")

    def _score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        assert self._reranker is not None
        if not pairs:
            return []
        scores = self._reranker.predict(
            pairs,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if self.device == "cuda":
            torch.cuda.synchronize()
        values = np.asarray(scores, dtype=np.float64).reshape(-1)
        if len(values) != len(pairs) or not np.isfinite(values).all():
            raise RuntimeError("Reranker scores are missing or non-finite")
        return values.tolist()

    def _rerank_chunks(
        self, question: str, hits: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        assert self._artifacts is not None
        pairs = [
            (question, self._artifacts.chunks_by_id[hit["chunk_id"]]["retrieval_text"])
            for hit in hits
        ]
        candidates = []
        for fallback_rank, (hit, score) in enumerate(
            zip(hits, self._score_pairs(pairs), strict=True), 1
        ):
            candidates.append(
                {
                    "retrieval_rank": int(hit.get("rank", fallback_rank)),
                    "chunk_id": hit["chunk_id"],
                    "parent_document_id": hit["parent_document_id"],
                    "source_id": hit["source_id"],
                    "status": hit["status"],
                    "default_exposure": hit["default_exposure"],
                    "review_required": hit["review_required"],
                    "guardrail_injected": bool(hit.get("guardrail_injected")),
                    "reranker_score": round(float(score), 8),
                }
            )
        return select_reranked_evidence(
            question, candidates, self._artifacts.chunks_by_id
        )

    def _assemble(
        self,
        requirements: list[dict[str, Any]],
        selected: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        assert self._artifacts is not None
        assert self._assembler_config is not None
        selected_ids = [row["chunk_id"] for row in selected]
        selected_chunks = {
            chunk_id: self._artifacts.chunks_by_id[chunk_id]["display_text"]
            for chunk_id in selected_ids
        }
        segments = [
            segment
            for chunk_id in selected_ids
            for segment in segment_chunk_nonoverlap(
                chunk_id, selected_chunks[chunk_id]
            )
        ]
        score_requirements = []
        for index, requirement in enumerate(requirements, 1):
            query = " ".join(
                part.strip()
                for part in (
                    str(requirement["subject"]),
                    str(requirement["relation"]),
                )
                if part.strip()
            )
            scores = self._score_pairs([(query, row["text"]) for row in segments])
            score_requirements.append(
                {
                    "requirement_index": index,
                    "requirement_id": requirement["requirement_id"],
                    "query": query,
                    "candidates": [
                        {**segment, "reranker_score": round(float(score), 8)}
                        for segment, score in zip(segments, scores, strict=True)
                    ],
                }
            )
        case = {
            "case_id": "demo_case",
            "dataset": "development_demo",
            "requirements": requirements,
            "selected_chunk_ids": selected_ids,
            "selected_chunks": selected_chunks,
        }
        score_row = {
            "case_id": "demo_case",
            "requirements": score_requirements,
        }
        return assemble_chunk_diverse_configuration(
            [case],
            [score_row],
            threshold=float(self._assembler_config["threshold"]),
            k=int(self._assembler_config["k"]),
        )[0]["decisions"]

    def _bounded_fallback(
        self,
        *,
        requirements: list[dict[str, Any]],
        route: dict[str, Any],
        baseline_selected: list[dict[str, Any]],
        baseline_decisions: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        before = shape_audit(requirements, baseline_decisions)
        detail = {
            "enabled": self.enable_bounded_fallback,
            "triggered": False,
            "committed": False,
            "bounded_source_ids": list(route["source_ids"]),
            "baseline_shape_audit": before,
            "fallback_shape_audit": before,
        }
        if (
            not self.enable_bounded_fallback
            or route["route_action"] != "retrieve"
            or before["veto_count"] == 0
        ):
            return baseline_selected, baseline_decisions, detail

        assert self._artifacts is not None
        allowed_sources = bounded_candidate_sources(route)
        detail["triggered"] = True
        detail["bounded_source_ids"] = list(allowed_sources)
        selected_by_id = {row["chunk_id"]: row for row in baseline_selected}
        for requirement in requirements:
            query = requirement_text(requirement)
            policy = SearchPolicy(
                default_exposure_only=route["default_exposure_only"],
                allowed_statuses=tuple(route["allowed_statuses"]),
                include_review_required=False,
                as_of=(
                    DEFAULT_AS_OF
                    if route["time_scope"] == "current"
                    else route["temporal_as_of"]
                ),
                source_ids=allowed_sources,
            )
            hits = retrieve_with_embedding(
                query,
                self._encode(query),
                self._artifacts,
                top_k=TOP_K,
                policy=policy,
            )
            if self.enable_v3_2_candidates:
                hits, _ = filter_hits_by_global_temporal(
                    hits,
                    time_scope=route["time_scope"],
                    temporal_by_document=self._global_temporal_by_document,
                )
            for row in self._rerank_chunks(query, hits):
                selected_by_id.setdefault(row["chunk_id"], row)

        fallback_selected = list(selected_by_id.values())
        fallback_decisions = self._assemble(requirements, fallback_selected)
        after = shape_audit(requirements, fallback_decisions)
        detail["fallback_shape_audit"] = after
        committed = after["supported_after_veto"] > before["supported_after_veto"]
        detail["committed"] = committed
        if committed:
            return fallback_selected, fallback_decisions, detail
        return baseline_selected, baseline_decisions, detail

    def _table_views(
        self,
        requirement: dict[str, Any],
        *,
        source_ids: tuple[str, ...],
        allowed_parent_document_ids: tuple[str, ...],
        time_scope: str,
    ) -> list[dict[str, Any]]:
        if (
            not self.enable_v3_2_candidates
            or self._table_bm25 is None
            or self._table_embeddings is None
            or not self._table_facts
            or not source_ids
            or not allowed_parent_document_ids
        ):
            return []
        assert self._embedder is not None
        assert self._artifacts is not None
        query = requirement_text(requirement)
        encoded = self._embedder.encode(
            [query],
            batch_size=1,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        candidates = search_sidecar(
            query=query,
            source_ids=source_ids,
            bm25=self._table_bm25,
            ordered_facts=self._table_facts,
            embeddings=self._table_embeddings,
            query_embedding=np.asarray(encoded[0], dtype=np.float32),
            allowed_parent_document_ids=allowed_parent_document_ids,
            time_scope=time_scope,
            as_of=DEFAULT_AS_OF,
            temporal_by_document=self._global_temporal_by_document,
        )
        scores = self._score_pairs(
            [(query, candidate["retrieval_text"]) for candidate in candidates]
        )
        selected = select_reranked_children(
            candidates,
            scores,
            threshold=TABLE_RERANKER_THRESHOLD,
            k=TABLE_RERANKER_K,
        )
        return assemble_table_group_answers(
            query=query,
            ranked_seed_facts=selected,
            all_facts=self._table_facts,
            chunks_by_id=self._artifacts.chunks_by_id,
        )

    def answer(self, question: str) -> dict[str, Any]:
        question = _require_nonempty_question(question)
        with self._lock:
            started = time.perf_counter()
            self._initialize()
            assert self._artifacts is not None
            assert self._overlay_rows is not None
            assert self._source_entity_index is not None
            assert self._planner_runtime is not None
            answerability = classify_answerability(question)
            if answerability["label"] == "false":
                route = route_question(
                    question,
                    candidate_hits=[],
                    documents=list(self._artifacts.documents_by_id.values()),
                    source_entity_index=self._source_entity_index,
                    overlay_rows=self._overlay_rows,
                )
                return self._finalize_result(
                    _route_only_result(
                        question=question,
                        requirements=[],
                        route=route,
                        planner_log={
                            "skipped": True,
                            "reason": "answerability_gate",
                        },
                        planner_runtime=self._planner_runtime,
                    ),
                    started=started,
                )

            requirements, planner_log = self._plan(question)
            embedding = self._encode(question)
            routed = route_and_retrieve_with_embedding(
                question,
                embedding,
                self._artifacts,
                self._overlay_rows,
                top_k=TOP_K,
                current_as_of=DEFAULT_AS_OF,
                source_entity_index=self._source_entity_index,
            )
            route = routed["route"]
            if route["route_action"] != "retrieve":
                return self._finalize_result(
                    _route_only_result(
                        question=question,
                        requirements=requirements,
                        route=route,
                        planner_log=planner_log,
                        planner_runtime=self._planner_runtime,
                    ),
                    started=started,
                )

            routed_hits = routed["hits"]
            temporal_denied_hits: list[dict[str, Any]] = []
            if self.enable_v3_2_candidates:
                routed_hits, temporal_denied_hits = filter_hits_by_global_temporal(
                    routed_hits,
                    time_scope=route["time_scope"],
                    temporal_by_document=self._global_temporal_by_document,
                )
            selected = self._rerank_chunks(question, routed_hits)
            decisions = self._assemble(requirements, selected)
            selected, decisions, fallback = self._bounded_fallback(
                requirements=requirements,
                route=route,
                baseline_selected=selected,
                baseline_decisions=decisions,
            )
            chunk_to_parent = {
                chunk_id: row["parent_document_id"]
                for chunk_id, row in self._artifacts.chunks_by_id.items()
            }
            requirement_results = []
            gated_decisions = []
            route_sources = tuple(
                fallback["bounded_source_ids"]
                if fallback["committed"]
                else route["source_ids"]
            )
            for requirement, decision in zip(requirements, decisions, strict=True):
                citations = []
                for span in decision["spans"]:
                    source = self._artifacts.chunks_by_id[span["chunk_id"]][
                        "display_text"
                    ]
                    validate_exact_citation(span, source)
                    metadata = {
                            **span,
                            **_citation_metadata(
                                span["chunk_id"],
                                chunks_by_id=self._artifacts.chunks_by_id,
                                documents_by_id=self._artifacts.documents_by_id,
                            ),
                        }
                    if self.enable_v3_2_candidates:
                        metadata = enrich_citation_metadata(
                            metadata,
                            temporal_by_document=self._global_temporal_by_document,
                            family_by_document=self._family_by_document,
                        )
                    citations.append(metadata)
                assembler_supported = decision["status"] == "supported_exact"
                cited_parent_ids = tuple(
                    sorted({row["parent_document_id"] for row in citations})
                )
                table_views = (
                    self._table_views(
                        requirement,
                        source_ids=route_sources,
                        allowed_parent_document_ids=cited_parent_ids,
                        time_scope=route["time_scope"],
                    )
                    if assembler_supported
                    else []
                )
                checked_decision, value_shape_audit = apply_table_value_shape_gate(
                    requirement,
                    decision,
                    table_views,
                )
                supported = checked_decision["status"] == "supported_exact"
                gated_decisions.append(checked_decision)
                requirement_results.append(
                    {
                        "requirement": requirement,
                        "status": "supported" if supported else "unsupported",
                        "message": None if supported else "문서에서 확인 불가",
                        "citations": citations if supported else [],
                        "table_views": table_views if supported else [],
                        "value_shape_audit": value_shape_audit,
                    }
                )
            backbone = summarize_grounded_decisions(
                gated_decisions,
                chunk_to_parent,
            )
            if backbone["response_mode"] == "abstain":
                message = "선택된 공식 문서에서 요구사항을 지지하는 근거를 확인하지 못했습니다."
            elif backbone["response_mode"] == "partial_answer":
                message = "확인된 요구사항만 원문으로 인용하며 나머지는 문서에서 확인 불가로 표시합니다."
            else:
                message = (
                    "아래 인용은 dirty canonical 원문의 exact slice입니다. "
                    "exact는 원문 복사를 뜻하며, 요구를 의미적으로 올바르게 지지한다는 검증은 아닙니다."
                )
            result = {
                "demo_version": DEMO_VERSION,
                "question": question,
                "route": {**route, "backbone_action": backbone["route_action"]},
                "response_mode": backbone["response_mode"],
                "message": message,
                "requirements": requirement_results,
                "planner": {"runtime": self._planner_runtime, "call": planner_log},
                "retrieval": {
                    "hit_count": len(routed_hits),
                    "temporal_denied_hit_count": len(temporal_denied_hits),
                    "selected_chunk_ids": [row["chunk_id"] for row in selected],
                    "bounded_fallback": fallback,
                },
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "provenance": {
                    "dirty_canonical_chunks_sha256": EXPECTED_DIRTY_CHUNKS_SHA256,
                    "planner_prompt_sha256": EXPECTED_PLANNER_PROMPT_SHA256,
                    "assembler_manifest": ASSEMBLER_MANIFEST.as_posix(),
                    "reranker_model": MODEL_NAME,
                    "reranker_revision": MODEL_REVISION,
                    "as_of": DEFAULT_AS_OF,
                    "v3_2_candidates_enabled": self.enable_v3_2_candidates,
                    "bounded_fallback_enabled": self.enable_bounded_fallback,
                    "runtime_promotion_status": RUNTIME_PROMOTION_STATUS,
                    "canonical_runtime_pointer": CANONICAL_RUNTIME_POINTER.as_posix(),
                    "canonical_runtime_manifest": self._canonical_runtime_manifest_ref,
                    "global_temporal_overlay": (
                        GLOBAL_TEMPORAL_OVERLAY.as_posix()
                        if self.enable_v3_2_candidates
                        else None
                    ),
                    "duplicate_family_overlay": (
                        DUPLICATE_FAMILY_OVERLAY.as_posix()
                        if self.enable_v3_2_candidates
                        else None
                    ),
                    "table_facts": (
                        self._table_facts_path
                        if self.enable_v3_2_candidates
                        else None
                    ),
                },
            }
            return self._finalize_result(result, started=started)


def render_result(
    result: dict[str, Any],
) -> tuple[str, list[list[str]], str, dict[str, Any]]:
    route = result["route"]
    route_action = route.get("backbone_action", route["route_action"])
    status = (
        f"### 라우팅: `{route_action}` · 응답: `{result['response_mode']}`\n\n"
        f"{result['message']}"
    )
    generation = result.get("generation") or {}
    if generation.get("enabled"):
        if generation.get("used_generated_text"):
            status += (
                "\n\n### \uc0dd\uc131 \ub2f5\ubcc0\n\n"
                + str(generation.get("answer_text") or "")
            )
        elif generation.get("mode") == "abstain":
            status += (
                "\n\n### \uc0dd\uc131 \ub2f5\ubcc0\n\n"
                + str(generation.get("answer_text") or "")
            )
        elif generation.get("mode") == "generation_error":
            status += (
                "\n\n> \uc0dd\uc131 \uc2e4\ud328: "
                "extractive \uadfc\uac70\ub9cc \ud45c\uc2dc\ud569\ub2c8\ub2e4."
            )
        else:
            status += (
                "\n\n> \uc0dd\uc131 \uac80\uc99d \uc2e4\ud328: "
                "extractive \uadfc\uac70\ub9cc \ud45c\uc2dc\ud569\ub2c8\ub2e4."
            )
    rows = []
    citation_sections = []
    for index, item in enumerate(result["requirements"], 1):
        label = _requirement_label(item["requirement"])
        rows.append([str(index), label, item["status"], item.get("message") or ""])
        if item["status"] != "supported":
            citation_sections.append(
                f"### 요구 {index} · {html.escape(label)}\n\n**{item.get('message') or '문서에서 확인 불가'}**"
            )
            continue
        blocks = [f"### 요구 {index} · {html.escape(label)}"]
        for citation_index, citation in enumerate(item["citations"], 1):
            url = html.escape(str(citation["canonical_url"]), quote=True)
            title = html.escape(str(citation["title"]))
            source = html.escape(str(citation["source_id"]))
            date_value = (
                citation.get("updated_at")
                or citation.get("published_at")
                or "날짜 미상"
            )
            revision = citation.get("revision_id") or "revision 없음"
            quote = html.escape(str(citation["text"]))
            validity = citation.get("validity_state")
            temporal_line = (
                f"유효성 `{html.escape(str(validity))}`"
                if validity
                else ""
            )
            family_line = ""
            if citation.get("duplicate_family_id"):
                family_line = (
                    f"duplicate family `{citation['duplicate_family_id']}` · "
                    f"출처 역할 `{html.escape(str(citation.get('source_role')))}`"
                )
            blocks.extend(
                [
                    f"**인용 {citation_index}** · [{title}]({url})",
                    f"출처 `{source}` · 날짜 `{date_value}` · revision `{revision}` · chunk `{citation['chunk_id']}`",
                    " · ".join(
                        value for value in (temporal_line, family_line) if value
                    ),
                    f"<blockquote><pre style='white-space:pre-wrap'>{quote}</pre></blockquote>",
                ]
            )
            if citation.get("temporal_warning"):
                blocks.append(
                    f"> ⚠️ {html.escape(str(citation['temporal_warning']))}"
                )
        for table_index, table_view in enumerate(item.get("table_views", []), 1):
            blocks.extend(
                [
                    f"**구조화 표 {table_index}** · exact row slices · development candidate",
                    table_view["rendered_markdown"],
                ]
            )
        citation_sections.append("\n\n".join(blocks))
    citations = "\n\n---\n\n".join(citation_sections) or "인용 없음"
    technical = {
        "demo_version": result["demo_version"],
        "route": result["route"],
        "response_mode": result["response_mode"],
        "provenance": result["provenance"],
        "latency_ms": result.get("latency_ms"),
        "generation": generation,
    }
    return status, rows, citations, technical


_RUNTIME: DemoBackbone | None = None
_RUNTIME_KEY: tuple[str, str, str | None, bool, bool, str] | None = None


def get_runtime(
    *,
    root: Path,
    planner_model: str,
    device: str | None,
    enable_v3_2_candidates: bool = True,
    enable_generation: bool = False,
    generator_model: str = DEFAULT_GENERATOR_MODEL,
) -> DemoBackbone:
    global _RUNTIME, _RUNTIME_KEY
    key = (
        str(root.resolve()),
        planner_model,
        device,
        enable_v3_2_candidates,
        enable_generation,
        generator_model,
    )
    if _RUNTIME is None or _RUNTIME_KEY != key:
        _RUNTIME = DemoBackbone(
            root=root,
            planner_model=planner_model,
            device=device,
            enable_v3_2_candidates=enable_v3_2_candidates,
            enable_generation=enable_generation,
            generator_model=generator_model,
        )
        _RUNTIME_KEY = key
    return _RUNTIME


def run_demo(
    question: str,
    *,
    root: Path,
    planner_model: str,
    device: str | None,
    enable_v3_2_candidates: bool = True,
    enable_generation: bool = False,
    generator_model: str = DEFAULT_GENERATOR_MODEL,
) -> tuple[str, list[list[str]], str, dict[str, Any]]:
    try:
        result = get_runtime(
            root=root,
            planner_model=planner_model,
            device=device,
            enable_v3_2_candidates=enable_v3_2_candidates,
            enable_generation=enable_generation,
            generator_model=generator_model,
        ).answer(question)
        return render_result(result)
    except Exception as exc:
        message = html.escape(str(exc))
        return (
            f"### 실행 오류\n\n{message}",
            [],
            "인용 없음",
            {"error": str(exc), "demo_version": DEMO_VERSION},
        )


def create_demo(
    *,
    root: Path,
    planner_model: str = DEFAULT_PLANNER_MODEL,
    device: str | None = None,
    enable_v3_2_candidates: bool = True,
    enable_generation: bool = False,
    generator_model: str = DEFAULT_GENERATOR_MODEL,
) -> gr.Blocks:
    def submit(question: str) -> tuple[str, list[list[str]], str, dict[str, Any]]:
        return run_demo(
            question,
            root=root,
            planner_model=planner_model,
            device=device,
            enable_v3_2_candidates=enable_v3_2_candidates,
            enable_generation=enable_generation,
            generator_model=generator_model,
        )

    css = """
    .demo-banner { border: 1px solid #d97706; background: #fff7ed; padding: 12px; border-radius: 10px; }
    .example-button { min-height: 54px; white-space: normal; }
    """
    with gr.Blocks(title="DNF RAG v3 정직한 백본 데모") as demo:
        gr.HTML(f"<style>{css}</style>")
        gr.Markdown("# DNF 공식 문서 QA/RAG v3 백본 데모")
        gr.Markdown(HONEST_BANNER, elem_classes=["demo-banner"])
        question = gr.Textbox(
            label="질문",
            placeholder="던파 공식 문서에서 확인할 질문을 입력하세요.",
            lines=2,
        )
        with gr.Row():
            for example in EXAMPLE_QUESTIONS:
                button = gr.Button(example, elem_classes=["example-button"])
                button.click(lambda value=example: value, outputs=question)
        submit_button = gr.Button("정확 인용으로 확인", variant="primary")
        route_status = gr.Markdown(label="라우팅·응답 상태")
        requirements = gr.Dataframe(
            headers=["번호", "요구사항", "상태", "메시지"],
            datatype=["str", "str", "str", "str"],
            interactive=False,
            wrap=True,
            label="요구별 판정",
        )
        citations = gr.Markdown(label="원문 인용과 출처")
        with gr.Accordion("기술 정보·프로즌 계보", open=False):
            technical = gr.JSON(label="route/provenance")
        submit_button.click(
            submit,
            inputs=question,
            outputs=[route_status, requirements, citations, technical],
        )
        question.submit(
            submit,
            inputs=question,
            outputs=[route_status, requirements, citations, technical],
        )
    return demo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the promoted-default DNF RAG v3.2 development runtime"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--planner-model", default=DEFAULT_PLANNER_MODEL)
    parser.add_argument("--generator-model", default=DEFAULT_GENERATOR_MODEL)
    parser.add_argument(
        "--enable-generation",
        action="store_true",
        help="Compose a verified answer with the configured generator model.",
    )
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--inbrowser", action="store_true")
    parser.add_argument(
        "--disable-v3-2-candidates",
        action="store_true",
        help="Diagnostic baseline control: disable the promoted v3.2 additive overlays.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    create_demo(
        root=args.root.resolve(),
        planner_model=args.planner_model,
        device=args.device,
        enable_v3_2_candidates=not args.disable_v3_2_candidates,
        enable_generation=args.enable_generation,
        generator_model=args.generator_model,
    ).queue(default_concurrency_limit=1).launch(
        server_name=args.host,
        server_port=args.port,
        inbrowser=args.inbrowser,
        show_error=True,
    )


if __name__ == "__main__":
    main()
