from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy
from src.v3.generate_grounded_llm_answer import (
    build_grounded_prompt,
    generate_grounded_output,
    safe_abstention,
    verify_and_sanitize_output,
)
from src.v3.grounded_answer_generator import extract_factual_tokens
from src.v3.question_router import (
    DEFAULT_AS_OF,
    DEFAULT_OVERLAY,
    SOURCE_TO_INTENT,
    SOURCE_TO_KIND,
    SOURCE_TO_STORE,
    build_source_entity_index,
    route_question,
)
from src.v3.retrieve_v3 import (
    RuntimeArtifacts,
    load_runtime_artifacts,
    retrieve_with_embedding,
)
from src.v3.score_evidence_reranker import (
    BATCH_SIZE,
    MAX_LENGTH,
    MODEL_NAME,
    MODEL_REVISION,
)


SIMPLE_RAG_VERSION = "dnf-simple-domain-rag-v2"
DEFAULT_RETRIEVAL_DEPTH = 20
DEFAULT_RERANK_DEPTH = 5
GLOBAL_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)


def _compact_factual_token(value: Any) -> str:
    return re.sub(r"[\s,]+", "", str(value or "").lower())


def _render_answer(requirements: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {row['answer']} "
        + " ".join(
            f"[{citation['chunk_id']}]" for citation in row.get("citations", [])
        )
        for row in requirements
        if row.get("status") == "supported_exact"
    )


def enforce_factual_token_support(result: dict[str, Any]) -> dict[str, Any]:
    """Drop claims whose numeric/date tokens do not occur in their cited text."""

    requirements = []
    audits_by_index = {
        int(row["requirement_index"]): dict(row)
        for row in result.get("verification", {}).get("requirements", [])
    }
    for row in result.get("requirements", []):
        checked = {
            **row,
            "citations": [dict(citation) for citation in row.get("citations", [])],
        }
        index = int(checked["requirement_index"])
        audit = audits_by_index.setdefault(
            index,
            {
                "requirement_index": index,
                "model_status": checked.get("status"),
                "exposed_status": checked.get("status"),
                "failure_reasons": [],
            },
        )
        if checked.get("status") == "supported_exact":
            evidence_text = "\n".join(
                str(citation.get("text") or "")
                for citation in checked.get("citations", [])
            )
            evidence_compact = _compact_factual_token(evidence_text)
            missing = [
                token
                for token in extract_factual_tokens(str(checked.get("answer") or ""))
                if _compact_factual_token(token) not in evidence_compact
            ]
            if missing:
                checked["status"] = "unsupported"
                checked["answer"] = ""
                checked["citations"] = []
                audit["exposed_status"] = "unsupported"
                audit.setdefault("failure_reasons", []).append(
                    "answer_factual_tokens_not_in_citations"
                )
                audit["missing_factual_tokens"] = missing
        requirements.append(checked)

    supported_count = sum(
        row.get("status") == "supported_exact" for row in requirements
    )
    if supported_count == 0:
        response_mode = "abstain"
    elif supported_count == len(requirements):
        response_mode = "full_answer"
    else:
        response_mode = "partial_answer"
    audits = [audits_by_index[index] for index in sorted(audits_by_index)]
    verification = {
        **result.get("verification", {}),
        "requirements": audits,
        "factual_token_check": True,
        "raw_output_passed_without_sanitization": bool(
            result.get("verification", {}).get(
                "raw_output_passed_without_sanitization"
            )
            and all(not row.get("failure_reasons") for row in audits)
        ),
    }
    return {
        **result,
        "response_mode": response_mode,
        "requirements": requirements,
        "rendered_answer": _render_answer(requirements),
        "verification": verification,
    }


def select_top_reranked(
    hits: list[dict[str, Any]],
    scores: list[float],
    *,
    depth: int,
) -> list[dict[str, Any]]:
    if depth < 1:
        raise RuntimeError("rerank depth must be at least 1")
    if len(hits) != len(scores):
        raise RuntimeError("reranker score count differs from retrieval hit count")
    ranked = [
        {
            **hit,
            "reranker_score": round(float(score), 8),
        }
        for hit, score in zip(hits, scores, strict=True)
    ]
    return sorted(
        ranked,
        key=lambda row: (
            -float(row["reranker_score"]),
            int(row.get("rank") or 0),
            str(row["chunk_id"]),
        ),
    )[:depth]


def append_one_baseline_fallback(
    routed: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    *,
    maximum: int,
) -> list[dict[str, Any]]:
    """Preserve one pre-router candidate without reopening the full source pool."""

    if maximum < len(routed):
        raise RuntimeError("maximum must preserve every routed candidate")
    if len(routed) >= maximum:
        return list(routed)
    seen = {row["chunk_id"] for row in routed}
    fallback = next(
        (row for row in baseline if row["chunk_id"] not in seen),
        None,
    )
    return [*routed, fallback] if fallback is not None else list(routed)


def _replace_simple_route_source(
    route: dict[str, Any],
    *,
    source_id: str,
    signal: str,
    time_scope: str = "current",
) -> dict[str, Any]:
    source_kinds = list(SOURCE_TO_KIND.get(source_id, ()))
    if source_id == "dnf_update" and not source_kinds:
        source_kinds = ["patch_note"]
    routing_signals = {
        **route.get("routing_signals", {}),
        "explicit": [
            *route.get("routing_signals", {}).get("explicit", []),
            signal,
        ],
    }
    current = time_scope == "current"
    return {
        **route,
        "intent": SOURCE_TO_INTENT[source_id],
        "matched_intents": [SOURCE_TO_INTENT[source_id]],
        "required_sources": [SOURCE_TO_STORE[source_id]],
        "source_ids": [source_id],
        "source_kinds": source_kinds,
        "time_scope": time_scope,
        "temporal_as_of": None,
        "default_exposure_only": current,
        "allowed_statuses": (
            ["current", "upcoming"]
            if current
            else ["current", "expired", "superseded", "unknown"]
        ),
        "needs_decomposition": False,
        "needs_clarification": False,
        "clarification_reason": None,
        "route_action": "retrieve",
        "routing_signals": routing_signals,
    }


def refine_simple_domain_route(
    question: str,
    route: dict[str, Any],
) -> dict[str, Any]:
    """Apply high-confidence product routes without changing the frozen router."""

    normalized = " ".join(question.lower().split())
    if any(
        marker in normalized
        for marker in ("npay 포인트", "넥슨 쿠폰", "세라 쿠폰")
    ):
        return _replace_simple_route_source(
            route,
            source_id="dnf_faq",
            signal="simple:faq_support",
        )
    if "던파on 출석체크" in normalized:
        return _replace_simple_route_source(
            route,
            source_id="dnf_game_guide",
            signal="simple:guide_attendance",
        )
    if (
        "운영정책" in normalized
        and any(marker in normalized for marker in ("변경", "개정"))
        and any(
            marker in normalized
            for marker in ("공지", "시행", "적용", "예정", "언제")
        )
    ):
        return _replace_simple_route_source(
            route,
            source_id="dnf_notice",
            signal="simple:policy_change_notice",
            time_scope="historical",
        )
    general_notice = any(
        marker in normalized
        for marker in (
            "chrome",
            "isp 결제",
            "권한 알림",
            "세리아의 특별 상점",
        )
    ) or (
        "추첨" in normalized
        and any(
            marker in normalized
            for marker in ("세리아와 함께한", "20주년 선물")
        )
    )
    if general_notice:
        return _replace_simple_route_source(
            route,
            source_id="dnf_notice",
            signal="simple:general_notice",
        )
    if "이달의 아이템" in normalized or "이달 의 아이템" in normalized:
        return _replace_simple_route_source(
            route,
            source_id="dnf_monthly_item",
            signal="simple:monthly_item",
            time_scope="historical" if "삭제됐" in normalized else "current",
        )
    if "패키지에 포함" in normalized or "이벤트 퀘스트" in normalized:
        return _replace_simple_route_source(
            route,
            source_id="dnf_event",
            signal="simple:event_document",
        )
    if "업데이트에서" in normalized:
        return _replace_simple_route_source(
            route,
            source_id="dnf_update",
            signal="simple:update_document",
        )
    return route


def search_policy_for_simple_route(route: dict[str, Any]) -> SearchPolicy:
    """Apply explicit source routes and preserve fallback for inferred routes."""

    explicit_signals = route.get("routing_signals", {}).get("explicit", [])
    routed_sources = tuple(route.get("source_ids") or ())
    source_ids = (
        routed_sources
        if explicit_signals and len(routed_sources) == 1
        else None
    )
    if route.get("time_scope") == "current":
        return SearchPolicy(as_of=DEFAULT_AS_OF, source_ids=source_ids)
    return SearchPolicy(
        default_exposure_only=False,
        allowed_statuses=None,
        as_of=route.get("temporal_as_of"),
        source_ids=source_ids,
    )


class SimpleDomainRAG:
    """Conventional retrieve-rerank-generate baseline over the frozen DNF corpus."""

    def __init__(
        self,
        *,
        root: Path,
        model: str = "qwen3-8b:ctx8192",
        device: str | None = None,
        retrieval_depth: int = DEFAULT_RETRIEVAL_DEPTH,
        rerank_depth: int = DEFAULT_RERANK_DEPTH,
        timeout: float = 180.0,
    ) -> None:
        if retrieval_depth < rerank_depth:
            raise RuntimeError("retrieval depth must be at least rerank depth")
        self.root = root.resolve()
        self.model = model
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.retrieval_depth = retrieval_depth
        self.rerank_depth = rerank_depth
        self.timeout = timeout
        self.temporal_by_document = {
            row["document_id"]: row
            for row in read_jsonl(self.root / GLOBAL_TEMPORAL_OVERLAY)
        }
        self._artifacts: RuntimeArtifacts | None = None
        self._overlay_rows: list[dict[str, Any]] | None = None
        self._source_entity_index: dict[str, list[frozenset[str]]] | None = None
        self._embedder: SentenceTransformer | None = None
        self._reranker: CrossEncoder | None = None

    def _initialize(self) -> None:
        if self._artifacts is not None:
            return
        self._artifacts = load_runtime_artifacts(self.root)
        self._overlay_rows = read_jsonl(self.root / DEFAULT_OVERLAY)
        self._source_entity_index = build_source_entity_index(
            list(self._artifacts.documents_by_id.values()),
            list(self._artifacts.chunks_by_id.values()),
        )
        dense_model = self._artifacts.dense_model
        self._embedder = SentenceTransformer(
            dense_model["model_name"],
            device=self.device,
            local_files_only=True,
        )
        self._embedder.max_seq_length = dense_model["max_sequence_length"]
        self._reranker = CrossEncoder(
            MODEL_NAME,
            revision=MODEL_REVISION,
            max_length=MAX_LENGTH,
            device=self.device,
            local_files_only=True,
        )

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
            raise RuntimeError("reranker scores are missing or non-finite")
        return values.tolist()

    def _retrieve_and_rerank(self, question: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self._initialize()
        assert self._artifacts is not None
        assert self._overlay_rows is not None
        query_embedding = self._encode(question)
        global_hits = retrieve_with_embedding(
            question,
            query_embedding,
            self._artifacts,
            top_k=20,
            policy=SearchPolicy(as_of=DEFAULT_AS_OF),
        )
        route = route_question(
            question,
            candidate_hits=global_hits,
            documents=list(self._artifacts.documents_by_id.values()),
            source_entity_index=self._source_entity_index,
            overlay_rows=self._overlay_rows,
        )
        route = refine_simple_domain_route(question, route)
        if route["route_action"] != "retrieve":
            return {"route": route, "hits": []}, []
        baseline_pairs = [
            (
                question,
                self._artifacts.chunks_by_id[hit["chunk_id"]]["retrieval_text"],
            )
            for hit in global_hits
        ]
        baseline_selected = select_top_reranked(
            global_hits,
            self._score_pairs(baseline_pairs),
            depth=self.rerank_depth,
        )
        policy = search_policy_for_simple_route(route)
        if (
            policy.source_ids is None
            and policy.default_exposure_only
            and policy.allowed_statuses == ("current", "upcoming")
            and policy.as_of == DEFAULT_AS_OF
        ):
            return {"route": route, "hits": global_hits}, baseline_selected
        hits = retrieve_with_embedding(
            question,
            query_embedding,
            self._artifacts,
            top_k=self.retrieval_depth,
            policy=policy,
        )
        routed = {"route": route, "hits": hits}
        pairs = [
            (
                question,
                self._artifacts.chunks_by_id[hit["chunk_id"]]["retrieval_text"],
            )
            for hit in hits
        ]
        selected = select_top_reranked(
            hits,
            self._score_pairs(pairs),
            depth=self.rerank_depth,
        )
        if policy.source_ids is not None:
            selected = append_one_baseline_fallback(
                selected,
                baseline_selected,
                maximum=self.rerank_depth + 1,
            )
        return routed, selected

    def answer(self, question: str) -> dict[str, Any]:
        normalized = " ".join(str(question or "").split())
        if not normalized:
            raise RuntimeError("question must not be empty")
        started = time.perf_counter()
        try:
            routed, selected = self._retrieve_and_rerank(normalized)
            candidate_ids = [row["chunk_id"] for row in selected]
            if not candidate_ids:
                return {
                    "simple_rag_version": SIMPLE_RAG_VERSION,
                    "question": normalized,
                    "response_mode": "abstain",
                    "rendered_answer": "",
                    "requirements": [],
                    "route": routed.get("route"),
                    "candidates": [],
                    "verification": {
                        "all_exposed_citations_verified": True,
                        "factual_token_check": True,
                        "reason": "no_retrieval_candidates",
                    },
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                }

            assert self._artifacts is not None
            prompt = build_grounded_prompt(
                question=normalized,
                as_of=DEFAULT_AS_OF,
                candidate_chunk_ids=candidate_ids,
                chunks_by_id=self._artifacts.chunks_by_id,
                documents_by_id=self._artifacts.documents_by_id,
                temporal_by_document=self.temporal_by_document,
            )
            generated = generate_grounded_output(
                prompt=prompt,
                model=self.model,
                timeout_seconds=self.timeout,
            )
            verified = verify_and_sanitize_output(
                generated["output"],
                candidate_chunk_ids=candidate_ids,
                chunks_by_id=self._artifacts.chunks_by_id,
                documents_by_id=self._artifacts.documents_by_id,
                temporal_by_document=self.temporal_by_document,
            )
            checked = enforce_factual_token_support(verified)
            return {
                "simple_rag_version": SIMPLE_RAG_VERSION,
                "question": normalized,
                **checked,
                "route": routed.get("route"),
                "candidates": [
                    {
                        "candidate_ref": str(index),
                        "chunk_id": row["chunk_id"],
                        "parent_document_id": row["parent_document_id"],
                        "source_id": row["source_id"],
                        "reranker_score": row["reranker_score"],
                    }
                    for index, row in enumerate(selected, 1)
                ],
                "generation": {
                    "model": self.model,
                    "provider": generated["provider"],
                    "usage": generated["usage"],
                    "latency_ms": generated["latency_ms"],
                },
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except Exception as exc:
            abstained = safe_abstention(exc)
            return {
                "simple_rag_version": SIMPLE_RAG_VERSION,
                "question": normalized,
                **abstained,
                "candidates": [],
                "generation": {"model": self.model, "error": str(exc)},
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--device")
    parser.add_argument("--retrieval-depth", type=int, default=DEFAULT_RETRIEVAL_DEPTH)
    parser.add_argument("--rerank-depth", type=int, default=DEFAULT_RERANK_DEPTH)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    rag = SimpleDomainRAG(
        root=args.root,
        model=args.model,
        device=args.device,
        retrieval_depth=args.retrieval_depth,
        rerank_depth=args.rerank_depth,
        timeout=args.timeout,
    )
    print(json.dumps(rag.answer(args.question), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
