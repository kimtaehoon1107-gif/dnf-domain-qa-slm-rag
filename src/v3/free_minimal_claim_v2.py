from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.v3.minimal_claim_v2_replay import _render_batch
from src.v3.minimal_claim_verifier import verify_minimal_claim_batch
from src.v3.free_minimal_table import (
    choose_structured_table_answer,
    operation_identity_state,
    prefer_exact_title_parent_ids,
)
from src.v3.free_minimal_direct import choose_direct_entry_fame
from src.v3.free_simple_rag import (
    answer_simple_rag_from_candidates,
    cap_response_mode_to_model,
    render_simple_natural_answer,
)
from src.v3.minimal_structured_evidence import (
    annotate_prompt_with_structured_rows,
    build_structured_rows_by_coordinate,
)
from src.v3.metadata_query import (
    DEFAULT_RUNTIME_SNAPSHOT,
    load_metadata_freshness_snapshot,
    plan_metadata_query,
    render_metadata_query_result,
    resolve_metadata_freshness,
)
from src.v3.grounded_answer_generator import extract_factual_tokens
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_table_atomic_facts_arm1 import (
    RERANKER_K as TABLE_RERANKER_K,
    RERANKER_THRESHOLD as TABLE_RERANKER_THRESHOLD,
    search_sidecar,
    select_reranked_children,
)
from src.io_utils import read_jsonl
from src.v3.question_router import DEFAULT_AS_OF, DEFAULT_DOCUMENTS
from src.v3.claim_contract_relation_registry import (
    relation_contract,
    relation_families_for_value_type,
)
from src.v3.korean_particles import attach_subject
from src.v3.simple_domain_rag import SimpleDomainRAG
from src.v3.simple_rag_rc1 import MODEL_TAG, _verify_model
from src.v3.typed_evidence_ref import (
    build_typed_evidence_prompt_with_candidate_units,
    generate_typed_evidence_output,
    resolve_requirement_claim_contracts,
)


FREE_MINIMAL_VERSION = "dnf-free-minimal-claim-v2-experimental-v1"
PLANNER_OUTPUT_TOKENS = 384
PLANNER_CONTEXT_TOKENS = 8192
TABLE_INDEX_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_index_manifest_"
    "423dfd6ae35bbfa5db1cef0ea1caa61df547ed99c508c998fd134f44f1c4f79d.json"
)

_SAFE_UNREGISTERED_RELATION_TYPES = {
    "entry_fame": frozenset({"number"}),
    "entry_reputation": frozenset({"number"}),
    "included_items": frozenset({"entity_list"}),
    "published_at": frozenset({"datetime"}),
    "trade_status": frozenset({"enum"}),
    "enhancement_probability": frozenset({"percentage"}),
}

ValueType = Literal[
    "boolean",
    "currency",
    "date",
    "date_range",
    "datetime",
    "duration_range",
    "entity",
    "entity_list",
    "enum",
    "number",
    "percentage",
    "price",
    "text",
    "time",
    "time_range",
]


class LiveClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=160)
    relation: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    value_type: ValueType
    cardinality: Literal["single", "all"] = "single"
    expected_count: int | None = Field(default=None, ge=1, le=20)


class LiveClaimPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[LiveClaimDraft] = Field(min_length=1, max_length=6)


LIVE_CLAIM_SYSTEM_PROMPT = """You create the fixed ClaimSpec for one Korean DNF
official-document question. Enumerate exactly the facts explicitly requested by
the user. Split coordinated fields into separate requirements. Never add a field
just because it may occur in a document. subject is the exact entity that owns the
requested fact. relation is a concise English snake_case relation. Choose only the
value_type allowed by the JSON schema. Use cardinality=all only when the user asks
for a complete list; otherwise use single. Set expected_count only when the user
explicitly states the count. Do not answer, retrieve, cite, or invent evidence.
Preserve the complete product or rule identity in subject, including duration,
year, month, revision, or variant named by the user. Do not move those identity
terms into relation. A requested price or cost uses value_type=currency, never
number. Typical relations are price, trade_type, deletion_at, effective_at, and
entry_fame.
Do not duplicate one requested fact by turning its owner and its measurement into
separate requirements. For example, "What fame is required to enter channel X?"
is one requirement: subject=channel X, relation=entry_fame, value_type=number.
By contrast, "What are product X's price and trade type?" is two requirements.
Return only structured JSON."""

RELATION_LABELS = {
    "account_input_limit": "계정당 입력 제한",
    "account_purchase_limit": "계정당 구매 제한",
    "broadcast_at": "방송 시각",
    "broadcast_channels": "방송 채널",
    "deletion_at": "삭제 시각",
    "effective_at": "적용일",
    "enhancement_probability": "강화 성공 확률",
    "entry_fame": "필요 입장 명성",
    "entry_reputation": "필요 입장 명성",
    "event_period": "이벤트 기간",
    "included_items": "구성품",
    "price": "가격",
    "published_at": "게시일",
    "purchase_limit": "구매 제한",
    "sale_period": "판매 기간",
    "shop_price": "가격",
    "trade_status": "거래 타입",
    "trade_type": "거래 타입",
}


Planner = Callable[
    [str, str, float],
    tuple[list[dict[str, Any]], dict[str, Any]],
]
Generator = Callable[..., dict[str, Any]]


def _ollama_chat_url() -> str:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return f"{base_url}/api/chat"


def _ollama_runtime_status(
    timeout_seconds: float = 1.0,
) -> dict[str, Any]:
    status_url = _ollama_chat_url().removesuffix(
        "/api/chat"
    ) + "/api/ps"
    started = time.perf_counter()
    try:
        with urlopen(
            Request(status_url, method="GET"),
            timeout=timeout_seconds,
        ) as response:
            raw = json.loads(response.read().decode("utf-8"))
        models = []
        for row in raw.get("models") or []:
            details = row.get("details") or {}
            models.append(
                {
                    "name": row.get("name") or row.get("model"),
                    "size_vram": int(row.get("size_vram") or 0),
                    "parameter_size": details.get("parameter_size"),
                    "quantization_level": details.get(
                        "quantization_level"
                    ),
                }
            )
        return {
            "reachable": True,
            "loaded_models": models,
            "probe_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        }
    except Exception as exc:
        return {
            "reachable": False,
            "loaded_models": [],
            "probe_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _fixed_requirements(plan: LiveClaimPlan) -> list[dict[str, Any]]:
    output = []
    for index, draft in enumerate(plan.requirements, 1):
        requirement = {
            "requirement_id": f"requirement_{index}",
            "subject": draft.subject.strip(),
            "relation": draft.relation.strip(),
            "value_type": draft.value_type,
        }
        if draft.cardinality != "single":
            requirement["cardinality"] = draft.cardinality
        if draft.expected_count is not None:
            requirement["expected_count"] = draft.expected_count
        output.append(requirement)
    return output


def _resolved_live_requirements(
    requirements: list[dict[str, Any]],
    *,
    question: str,
) -> list[dict[str, Any]]:
    normalized = []
    for requirement in requirements:
        row = dict(requirement)
        if (
            "강화" in question
            and "확률" in question
        ):
            row["relation"] = "enhancement_probability"
            row["value_type"] = "percentage"
        contract = relation_contract(row)
        if contract is None:
            allowed_types = _SAFE_UNREGISTERED_RELATION_TYPES.get(
                str(row.get("relation") or "")
            )
            if (
                allowed_types is None
                or str(row.get("value_type") or "") not in allowed_types
            ):
                raise RuntimeError(
                    "unregistered_live_relation:"
                    f"{row.get('relation')}"
                )
            normalized.append(row)
            continue
        if (
            len(contract.allowed_value_types) == 1
        ):
            row["value_type"] = next(iter(contract.allowed_value_types))
        normalized.append(row)
    return resolve_requirement_claim_contracts(
        normalized,
        question_text=question,
    )


def _resolved_live_requirements_strict_shadow(
    requirements: list[dict[str, Any]],
    *,
    question: str,
) -> list[dict[str, Any]]:
    """Admit schema-valid unknown relations without weakening exposure checks."""

    valid_value_types = set(ValueType.__args__)
    normalized = []
    for requirement in requirements:
        row = dict(requirement)
        value_type = str(row.get("value_type") or "")
        if value_type not in valid_value_types:
            raise RuntimeError(
                f"invalid_live_value_type:{value_type}"
            )
        contract = relation_contract(row)
        if contract is not None:
            if len(contract.allowed_value_types) == 1:
                row["value_type"] = next(
                    iter(contract.allowed_value_types)
                )
            row["_relation_admission_mode"] = "registered"
            normalized.append(row)
            continue

        families = relation_families_for_value_type(value_type)
        row["relation_validation_mode"] = "strict"
        row["_relation_admission_mode"] = "unregistered_strict_shadow"
        row["_relation_family_candidates"] = list(families)
        row["_inferred_relation_family_candidate"] = (
            families[0] if len(families) == 1 else None
        )
        normalized.append(row)
    return resolve_requirement_claim_contracts(
        normalized,
        question_text=question,
    )


def _evidence_numbers(
    requirements: list[dict[str, Any]],
) -> dict[str, int]:
    output: dict[str, int] = {}
    for requirement in requirements:
        for citation in requirement.get("citations", []):
            chunk_id = str(citation.get("chunk_id") or "")
            if chunk_id and chunk_id not in output:
                output[chunk_id] = len(output) + 1
    return output


def render_natural_answer(
    requirements: list[dict[str, Any]],
) -> str:
    supported = [
        row
        for row in requirements
        if row.get("status") == "supported_exact"
    ]
    if not supported:
        return ""
    evidence_numbers = _evidence_numbers(supported)
    subjects = {
        str(row.get("subject") or "").strip()
        for row in supported
        if str(row.get("subject") or "").strip()
    }
    show_subject = len(subjects) > 1
    lines = []
    for row in supported:
        relation = str(row.get("relation") or "").strip()
        label = RELATION_LABELS.get(
            relation,
            relation.replace("_", " ").strip() or "요청한 값",
        )
        try:
            labeled = attach_subject(label)
        except ValueError:
            labeled = f"{label}:"
        subject = str(row.get("subject") or "").strip()
        prefix = f"{subject}의 " if show_subject and subject else ""
        cited_chunk_ids = dict.fromkeys(
            citation.get("chunk_id")
            for citation in row.get("citations", [])
            if citation.get("chunk_id") in evidence_numbers
        )
        refs = " ".join(
            f"[근거 {evidence_numbers[chunk_id]}]"
            for chunk_id in cited_chunk_ids
        )
        answer = str(row.get("answer") or "").strip()
        line = f"- {prefix}{labeled} {answer}입니다."
        if refs:
            line += f" {refs}"
        lines.append(line)
    return "\n".join(lines)


def plan_live_claims(
    question: str,
    model: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LIVE_CLAIM_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
        "format": LiveClaimPlan.model_json_schema(),
        "options": {
            "temperature": 0,
            "num_ctx": PLANNER_CONTEXT_TOKENS,
            "num_predict": PLANNER_OUTPUT_TOKENS,
        },
    }
    request = Request(
        _ollama_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = str((raw.get("message") or {}).get("content") or "")
    if not content:
        raise RuntimeError("live_claim_planner_returned_no_content")
    parsed = LiveClaimPlan.model_validate_json(content)
    requirements = _fixed_requirements(parsed)
    return requirements, {
        "model": raw.get("model") or model,
        "provider": "ollama_native",
        "thinking_enabled": False,
        "latency_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
        "usage": {
            "input_tokens": int(raw.get("prompt_eval_count") or 0),
            "output_tokens": int(raw.get("eval_count") or 0),
        },
        "raw_content": content,
    }


class FreeMinimalClaimV2:
    """Experimental free-question path using a live fixed ClaimSpec."""

    def __init__(
        self,
        *,
        root: Path,
        model: str = MODEL_TAG,
        device: str = "cpu",
        timeout: float = 180.0,
        generation_timeout: float | None = None,
        base: SimpleDomainRAG | None = None,
        planner: Planner = plan_live_claims,
        generator: Generator = generate_typed_evidence_output,
        fallback_mode: Literal["typed_claim", "simple_rag"] = "typed_claim",
        simple_rag_evidence_mode: Literal[
            "exact_quote", "server_ref"
        ] = "exact_quote",
        table_index_manifest: Path | None = None,
        enable_metadata_queries: bool = False,
        metadata_as_of: str | None = None,
        metadata_snapshot_path: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.model = model
        self.timeout = timeout
        self.generation_timeout = (
            timeout if generation_timeout is None else generation_timeout
        )
        if base is None:
            _verify_model(model)
            base = SimpleDomainRAG(
                root=self.root,
                model=model,
                device=device,
                retrieval_depth=20,
                rerank_depth=5,
                timeout=timeout,
            )
        self.base = base
        self.planner = planner
        self.generator = generator
        self.fallback_mode = fallback_mode
        self.simple_rag_evidence_mode = simple_rag_evidence_mode
        self.table_index_manifest = (
            table_index_manifest or TABLE_INDEX_MANIFEST
        )
        self.enable_metadata_queries = enable_metadata_queries
        self.metadata_as_of = metadata_as_of or date.today().isoformat()
        self.metadata_snapshot_path = (
            metadata_snapshot_path or DEFAULT_RUNTIME_SNAPSHOT
        )
        self._metadata_snapshot: dict[str, Any] | None = None
        self._metadata_documents: list[dict[str, Any]] | None = None
        self._table_bm25: dict[str, Any] | None = None
        self._table_facts: list[dict[str, Any]] | None = None
        self._table_embeddings: Any = None

    def _initialize_table_sidecar(self) -> None:
        if self._table_facts is not None:
            return
        import numpy as np

        manifest = json.loads(
            (self.root / self.table_index_manifest).read_text(
                encoding="utf-8"
            )
        )
        bm25_path = self.root / manifest["bm25"]["path"]
        facts_path = self.root / manifest["dense"]["metadata_path"]
        embeddings_path = self.root / manifest["dense"]["path"]
        for path, expected in (
            (bm25_path, manifest["bm25"]["sha256"]),
            (facts_path, manifest["dense"]["metadata_sha256"]),
            (embeddings_path, manifest["dense"]["sha256"]),
        ):
            if file_sha256(path) != expected:
                raise RuntimeError(
                    f"table_sidecar_hash_mismatch:{path}"
                )
        self._table_bm25 = json.loads(
            bm25_path.read_text(encoding="utf-8")
        )
        self._table_facts = read_jsonl(facts_path)
        self._table_embeddings = np.fromfile(
            embeddings_path,
            dtype="<f4",
        ).reshape(
            len(self._table_facts),
            manifest["dense"]["dimension"],
        )

    def _candidate_rows(
        self,
        selected: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        artifacts = self.base._artifacts
        if artifacts is None:
            raise RuntimeError("runtime artifacts were not initialized")
        candidates = []
        for index, hit in enumerate(selected, 1):
            chunk = artifacts.chunks_by_id[hit["chunk_id"]]
            document = artifacts.documents_by_id[
                chunk["parent_document_id"]
            ]
            candidates.append(
                {
                    "candidate_ref": str(index),
                    "chunk_id": hit["chunk_id"],
                    "source_id": document["source_id"],
                    "title": document.get("title"),
                    "published_at": document.get("published_at"),
                    "status": document.get("status"),
                    "reranker_score": hit.get("reranker_score"),
                }
            )
        return candidates

    def _structured_table_answer(
        self,
        question: str,
        *,
        routed: dict[str, Any],
        selected: list[dict[str, Any]],
        retrieval_ms: float,
        started: float,
    ) -> dict[str, Any] | None:
        import numpy as np

        artifacts = self.base._artifacts
        if artifacts is None:
            raise RuntimeError("runtime artifacts were not initialized")
        self._initialize_table_sidecar()
        assert self._table_bm25 is not None
        assert self._table_facts is not None
        route = routed.get("route") or {}
        parent_ids = tuple(
            dict.fromkeys(
                hit["parent_document_id"]
                for hit in routed.get("hits", [])
            )
        )
        parent_ids = prefer_exact_title_parent_ids(
            question,
            parent_ids=parent_ids,
            documents_by_id=artifacts.documents_by_id,
        )
        source_ids = tuple(
            dict.fromkeys(
                artifacts.documents_by_id[parent_id]["source_id"]
                for parent_id in parent_ids
                if parent_id in artifacts.documents_by_id
            )
        )
        if not parent_ids or not source_ids:
            return None
        table_started = time.perf_counter()
        encoded = self.base._encode(question)
        candidates = search_sidecar(
            query=question,
            source_ids=source_ids,
            bm25=self._table_bm25,
            ordered_facts=self._table_facts,
            embeddings=self._table_embeddings,
            query_embedding=np.asarray(encoded, dtype=np.float32),
            allowed_parent_document_ids=parent_ids,
            time_scope=str(route.get("time_scope") or "current"),
            as_of=str(route.get("temporal_as_of") or DEFAULT_AS_OF),
            temporal_by_document=self.base.temporal_by_document,
        )
        scores = self.base._score_pairs(
            [
                (question, candidate["retrieval_text"])
                for candidate in candidates
            ]
        )
        seeds = select_reranked_children(
            candidates,
            scores,
            threshold=TABLE_RERANKER_THRESHOLD,
            k=TABLE_RERANKER_K,
        )
        selected_answer = choose_structured_table_answer(
            question=question,
            ranked_seed_facts=seeds,
            all_facts=self._table_facts,
            chunks_by_id=artifacts.chunks_by_id,
        )
        if selected_answer is None:
            return None
        table_ms = round(
            (time.perf_counter() - table_started) * 1000,
            3,
        )
        answer_views = list(
            selected_answer.get("views")
            or (
                [selected_answer["view"]]
                if selected_answer.get("view") is not None
                else []
            )
        )
        evidence_chunk_ids = {
            row["source_chunk_id"]
            for view in answer_views
            for row in view["rows"]
        }
        selected_for_result = list(selected)
        selected_chunk_ids = {
            hit["chunk_id"] for hit in selected_for_result
        }
        selected_for_result.extend(
            hit
            for hit in routed.get("hits", [])
            if hit["chunk_id"] in evidence_chunk_ids
            and hit["chunk_id"] not in selected_chunk_ids
        )
        return self._render_structured_table_result(
            question,
            selected_answer=selected_answer,
            selected=selected_for_result,
            route=route,
            retrieval_ms=retrieval_ms,
            table_ms=table_ms,
            started=started,
        )

    def _render_direct_entry_fame_result(
        self,
        question: str,
        *,
        direct: dict[str, Any],
        selected: list[dict[str, Any]],
        route: dict[str, Any],
        retrieval_ms: float,
        started: float,
    ) -> dict[str, Any]:
        citation = direct["citation"]
        value = direct["value"]
        requirement = {
            "requirement_id": "direct_1",
            "subject": direct["subject"],
            "relation": "entry_fame",
            "value_type": "number",
            "status": "supported_exact",
            "value": value,
            "answer": value,
            "citations": [citation],
            "verification": {
                "failure_reasons": [],
                "server_direct_fact": True,
                "subject_identity_matched": True,
            },
        }
        return {
            "free_minimal_version": FREE_MINIMAL_VERSION,
            "question": question,
            "response_mode": "full_answer",
            "rendered_answer": (
                f"- 입장 명성은 {value}입니다. [근거 1]"
            ),
            "requirements": [requirement],
            "live_claimspec": [
                {
                    "requirement_id": "direct_1",
                    "subject": direct["subject"],
                    "relation": "entry_fame",
                    "value_type": "number",
                }
            ],
            "route": route,
            "candidates": self._candidate_rows(selected),
            "planner": {
                "mode": "bypassed_for_direct_fact",
                "latency_ms": 0.0,
            },
            "generation": {
                "mode": "bypassed_for_direct_fact",
                "latency_ms": 0.0,
            },
            "verification": {
                "all_exposed_citations_verified": True,
                "server_direct_fact": True,
            },
            "latency": {
                "retrieval_ms": retrieval_ms,
                "planner_ms": 0.0,
                "generation_ms": 0.0,
                "total_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
            },
            "evaluation_boundary": (
                "experimental live path; not the frozen Minimal Claim v2 "
                "5.66-second evaluation result"
            ),
        }

    def _render_structured_table_result(
        self,
        question: str,
        *,
        selected_answer: dict[str, Any],
        selected: list[dict[str, Any]],
        route: dict[str, Any],
        retrieval_ms: float,
        table_ms: float,
        started: float,
    ) -> dict[str, Any]:
        kind = selected_answer["kind"]
        if kind == "table_group_clarification":
            ambiguous = ", ".join(
                selected_answer.get("ambiguous_targets") or []
            )
            return {
                "free_minimal_version": FREE_MINIMAL_VERSION,
                "question": question,
                "response_mode": "clarification",
                "rendered_answer": (
                    f"'{ambiguous}'에 해당하는 표가 여러 개입니다. "
                    "대상이나 범위를 조금 더 구체적으로 알려주세요."
                ),
                "requirements": [],
                "live_claimspec": [],
                "route": route,
                "candidates": self._candidate_rows(selected),
                "planner": {
                    "mode": "bypassed_for_structured_table",
                    "latency_ms": 0.0,
                },
                "generation": {
                    "mode": "bypassed_for_structured_table",
                    "latency_ms": 0.0,
                },
                "table_views": [],
                "verification": {
                    "all_exposed_citations_verified": True,
                    "server_structured_table": True,
                    "table_group_ambiguous": True,
                },
                "latency": {
                    "retrieval_ms": retrieval_ms,
                    "table_ms": table_ms,
                    "planner_ms": 0.0,
                    "generation_ms": 0.0,
                    "total_ms": round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    ),
                },
                "evaluation_boundary": (
                    "experimental live path; not the frozen Minimal Claim "
                    "v2 5.66-second evaluation result"
                ),
            }

        if kind in {
            "complete_table",
            "complete_table_group",
            "partial_table_group",
        }:
            items = (
                list(selected_answer["items"])
                if kind.endswith("_group")
                else [selected_answer]
            )
            requirements = []
            rendered_tables = []
            views = []
            for index, item in enumerate(items, 1):
                view = item["view"]
                views.append(view)
                rows = list(view["rows"])
                citations = [
                    {
                        "chunk_id": row["source_chunk_id"],
                        "parent_document_id": view[
                            "parent_document_id"
                        ],
                        "source_id": next(
                            fact["source_id"]
                            for fact in self._table_facts or []
                            if fact["row_id"] == row["row_id"]
                        ),
                        "revision_id": None,
                        "start_char": row["start_offset"],
                        "end_char": row["end_offset"],
                        "text": row["exact_row_text"],
                        "evidence_ref": row["row_id"],
                    }
                    for row in rows
                ]
                display_attributes = list(
                    item.get("display_attributes") or []
                )
                rendered_markdown = view["rendered_markdown"]
                if display_attributes:
                    header = " | ".join(
                        str(attribute).replace("|", "\\|")
                        for attribute in display_attributes
                    )
                    lines = [
                        "### "
                        + str(
                            view["table_subject"]
                            if kind.endswith("_group")
                            else (
                                view.get("scope_title")
                                or view["table_subject"]
                                or view["title"]
                            )
                        ),
                        "",
                        f"| {header} |",
                        "| "
                        + " | ".join(
                            "---" for _ in display_attributes
                        )
                        + " |",
                    ]
                    for row in rows:
                        values = " | ".join(
                            str(
                                row["values"].get(attribute, "")
                            ).replace("|", "\\|")
                            for attribute in display_attributes
                        )
                        lines.append(f"| {values} |")
                    rendered_markdown = "\n".join(lines) + "\n"
                rendered_tables.append(
                    f"{rendered_markdown}[근거 {index}]"
                )
                requirements.append(
                    {
                        "requirement_id": f"table_{index}",
                        "subject": view["table_subject"],
                        "relation": "complete_cost_table",
                        "value_type": "text",
                        "status": "supported_exact",
                        "value": f"{view['row_count']} rows",
                        "answer": (
                            f"구조화 표 {view['row_count']}행"
                        ),
                        "citations": citations,
                        "verification": {
                            "failure_reasons": [],
                            "server_structured_table": True,
                            "exact_offset_mismatch_count": view[
                                "exact_offset_mismatch_count"
                            ],
                        },
                    }
                )
            unresolved = list(
                selected_answer.get("unresolved_targets") or []
            )
            if unresolved:
                rendered_tables.append(
                    "다음 대상은 현재 근거에서 정확한 표를 하나로 "
                    "연결하지 못했습니다: "
                    + ", ".join(unresolved)
                )
                for unresolved_index, target in enumerate(
                    unresolved,
                    len(requirements) + 1,
                ):
                    requirements.append(
                        {
                            "requirement_id": (
                                f"table_{unresolved_index}"
                            ),
                            "subject": target,
                            "relation": "complete_cost_table",
                            "value_type": "text",
                            "status": "unsupported",
                            "value": None,
                            "answer": "",
                            "citations": [],
                            "verification": {
                                "failure_reasons": [
                                    "requested_table_not_uniquely_matched"
                                ],
                                "server_structured_table": True,
                            },
                        }
                    )
            answer = "\n\n".join(rendered_tables)
            response_mode = (
                "partial"
                if kind == "partial_table_group"
                else "full_answer"
            )
        else:
            view = selected_answer["view"]
            row = selected_answer["row"]
            values = selected_answer["values"]
            rendered_values = []
            for attribute, value in values.items():
                suffix = (
                    "개"
                    if "몇 개" in question
                    and str(value).strip() != "-"
                    else ""
                )
                rendered_values.append(
                    f"{attribute}은 {value}{suffix}입니다"
                )
            owner_prefix = (
                ""
                if len(values) == 1
                and next(iter(values)) == row["label"]
                else f"{row['label']}의 "
            )
            answer = (
                f"- {owner_prefix}"
                + ", ".join(rendered_values)
                + ". [근거 1]"
            )
            source_fact = next(
                fact
                for fact in self._table_facts or []
                if fact["row_id"] == row["row_id"]
            )
            citation = {
                "chunk_id": row["source_chunk_id"],
                "parent_document_id": view["parent_document_id"],
                "source_id": source_fact["source_id"],
                "revision_id": None,
                "start_char": row["start_offset"],
                "end_char": row["end_offset"],
                "text": row["exact_row_text"],
                "evidence_ref": row["row_id"],
            }
            requirements = [
                {
                    "requirement_id": "table_1",
                    "subject": row["subject"],
                    "relation": "table_attribute_value",
                    "value_type": "text",
                    "status": "supported_exact",
                    "value": values,
                    "answer": "; ".join(
                        f"{attribute}: {value}"
                        for attribute, value in values.items()
                    ),
                    "citations": [citation],
                    "verification": {
                        "failure_reasons": [],
                        "server_structured_table": True,
                        "row_id": row["row_id"],
                    },
                }
            ]
            views = [view]
            response_mode = "full_answer"
        live_claims = [
            {
                key: requirement[key]
                for key in (
                    "requirement_id",
                    "subject",
                    "relation",
                    "value_type",
                )
            }
            for requirement in requirements
        ]
        return {
            "free_minimal_version": FREE_MINIMAL_VERSION,
            "question": question,
            "response_mode": response_mode,
            "rendered_answer": answer,
            "requirements": requirements,
            "live_claimspec": live_claims,
            "route": route,
            "candidates": self._candidate_rows(selected),
            "planner": {
                "mode": "bypassed_for_structured_table",
                "latency_ms": 0.0,
            },
            "generation": {
                "mode": "bypassed_for_structured_table",
                "latency_ms": 0.0,
            },
            "table_views": views,
            "verification": {
                "all_exposed_citations_verified": True,
                "server_structured_table": True,
                "table_group_complete": (
                    kind == "complete_table_group"
                ),
                "table_group_partial": (
                    kind == "partial_table_group"
                ),
            },
            "latency": {
                "retrieval_ms": retrieval_ms,
                "table_ms": table_ms,
                "planner_ms": 0.0,
                "generation_ms": 0.0,
                "total_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
            },
            "evaluation_boundary": (
                "experimental live path; not the frozen Minimal Claim v2 "
                "5.66-second evaluation result"
            ),
        }

    def _apply_operation_guard(
        self,
        result: dict[str, Any],
        *,
        question: str,
    ) -> dict[str, Any]:
        artifacts = self.base._artifacts
        if artifacts is None:
            raise RuntimeError("runtime artifacts were not initialized")
        guarded = []
        guard_audits = []
        for requirement in result["requirements"]:
            row = dict(requirement)
            if row.get("status") != "supported_exact":
                guarded.append(row)
                continue
            valid_citations = []
            rejected_citations = []
            for citation in row.get("citations", []):
                chunk = artifacts.chunks_by_id[citation["chunk_id"]]
                document = artifacts.documents_by_id[
                    chunk["parent_document_id"]
                ]
                state = operation_identity_state(
                    question,
                    title=str(document.get("title") or ""),
                    heading_path=list(chunk.get("heading_path") or []),
                    evidence_text=str(citation.get("text") or ""),
                )
                if state == "match":
                    valid_citations.append(citation)
                else:
                    rejected_citations.append(
                        {
                            "chunk_id": citation["chunk_id"],
                            "state": state,
                        }
                    )
            if valid_citations:
                evidence_compact = re.sub(
                    r"[\s,]+",
                    "",
                    "\n".join(
                        str(citation.get("text") or "")
                        for citation in valid_citations
                    ).casefold(),
                )
                missing_factual_tokens = [
                    token
                    for token in extract_factual_tokens(
                        str(row.get("answer") or "")
                    )
                    if re.sub(
                        r"[\s,]+",
                        "",
                        str(token).casefold(),
                    )
                    not in evidence_compact
                ]
            else:
                missing_factual_tokens = []
            if valid_citations and not missing_factual_tokens:
                verification = dict(row.get("verification") or {})
                verification["operation_identity_guard"] = {
                    "mode": "contradiction_only",
                    "rejected_citations": rejected_citations,
                }
                guarded.append(
                    {
                        **row,
                        "citations": valid_citations,
                        "verification": verification,
                    }
                )
                guard_audits.append(
                    {
                        "requirement_index": row.get(
                            "requirement_index"
                        ),
                        "requirement_id": row.get("requirement_id"),
                        "status": "supported_exact",
                        "rejected_citations": rejected_citations,
                    }
                )
                continue
            verification = dict(row.get("verification") or {})
            rejected_states = {
                item["state"] for item in rejected_citations
            }
            if missing_factual_tokens:
                failure_reason = (
                    "operation_value_not_supported_after_pruning"
                )
                verification["missing_factual_tokens"] = (
                    missing_factual_tokens
                )
            else:
                failure_reason = (
                    "operation_identity_conflict"
                    if "conflict" in rejected_states
                    else "operation_identity_unproven"
                )
            verification["failure_reasons"] = list(
                dict.fromkeys(
                    [
                        *verification.get("failure_reasons", []),
                        failure_reason,
                    ]
                )
            )
            guarded.append(
                {
                    **row,
                    "status": "unsupported",
                    "value": None,
                    "answer": "",
                    "citations": [],
                    "verification": verification,
                }
            )
            guard_audits.append(
                {
                    "requirement_index": row.get(
                        "requirement_index"
                    ),
                    "requirement_id": row.get("requirement_id"),
                    "status": "unsupported",
                    "failure_reason": failure_reason,
                    "rejected_citations": rejected_citations,
                }
            )
        supported = [
            row
            for row in guarded
            if row.get("status") == "supported_exact"
        ]
        if not supported:
            response_mode = "abstain"
        elif len(supported) == len(guarded):
            response_mode = "full_answer"
        else:
            response_mode = "partial_answer"
        response_mode = cap_response_mode_to_model(
            response_mode,
            model_mode=result.get("model_response_mode"),
        )
        result_verification = dict(result.get("verification") or {})
        verification_audits = [
            dict(audit)
            for audit in result_verification.get(
                "requirements",
                [],
            )
        ]
        for guard_audit in guard_audits:
            matching_audit = next(
                (
                    audit
                    for audit in verification_audits
                    if (
                        guard_audit.get("requirement_index")
                        is not None
                        and audit.get("requirement_index")
                        == guard_audit["requirement_index"]
                    )
                    or (
                        guard_audit.get("requirement_id")
                        is not None
                        and audit.get("requirement_id")
                        == guard_audit["requirement_id"]
                    )
                ),
                None,
            )
            if matching_audit is None:
                continue
            matching_audit["exposed_status"] = guard_audit["status"]
            if guard_audit.get("failure_reason"):
                matching_audit["failure_reasons"] = list(
                    dict.fromkeys(
                        [
                            *matching_audit.get(
                                "failure_reasons",
                                [],
                            ),
                            guard_audit["failure_reason"],
                        ]
                    )
                )
            matching_audit["operation_identity_guard"] = guard_audit
        result_verification["requirements"] = verification_audits
        result_verification["operation_identity_guard"] = {
            "mode": "contradiction_only",
            "requirements": guard_audits,
        }
        return {
            **result,
            "response_mode": response_mode,
            "requirements": guarded,
            "verification": result_verification,
        }

    def answer(self, question: str) -> dict[str, Any]:
        normalized = " ".join(str(question or "").split())
        if not normalized:
            raise RuntimeError("question must not be empty")
        started = time.perf_counter()
        stage_started = started
        failure_stage = "metadata_planning"
        retrieval_ms = 0.0
        try:
            if getattr(self, "enable_metadata_queries", False):
                metadata_plan = plan_metadata_query(
                    normalized,
                    as_of=self.metadata_as_of,
                )
                if metadata_plan is not None:
                    failure_stage = "metadata_render"
                    stage_started = time.perf_counter()
                    freshness = None
                    if metadata_plan.mode == "metadata":
                        if self._metadata_snapshot is None:
                            self._metadata_snapshot = (
                                load_metadata_freshness_snapshot(
                                    root=self.root,
                                    snapshot_path=(
                                        self.metadata_snapshot_path
                                    ),
                                )
                            )
                        freshness = resolve_metadata_freshness(
                            source_id=metadata_plan.source_id,
                            requested_as_of=self.metadata_as_of,
                            snapshot=self._metadata_snapshot,
                        )
                        if freshness.effective_as_of is not None:
                            metadata_plan = replace(
                                metadata_plan,
                                as_of=freshness.effective_as_of,
                            )
                    if (
                        metadata_plan.mode == "metadata"
                        and self._metadata_documents is None
                    ):
                        self._metadata_documents = read_jsonl(
                            self.root / DEFAULT_DOCUMENTS
                        )
                    metadata_result = render_metadata_query_result(
                        question=normalized,
                        plan=metadata_plan,
                        documents=self._metadata_documents or [],
                        started=started,
                        freshness=freshness,
                    )
                    return {
                        "free_minimal_version": FREE_MINIMAL_VERSION,
                        **metadata_result,
                        "evaluation_boundary": (
                            "experimental metadata query path; not a "
                            "frozen generalization result"
                        ),
                    }

            failure_stage = "retrieval"
            stage_started = time.perf_counter()
            retrieval_started = time.perf_counter()
            routed, selected = self.base._retrieve_and_rerank(normalized)
            retrieval_ms = round(
                (time.perf_counter() - retrieval_started) * 1000,
                3,
            )
            candidate_ids = [row["chunk_id"] for row in selected]
            if not candidate_ids:
                return self._abstain(
                    normalized,
                    reason="no_retrieval_candidates",
                    started=started,
                    route=routed.get("route"),
                    retrieval_ms=retrieval_ms,
                )

            failure_stage = "direct_entry_fame"
            stage_started = time.perf_counter()
            artifacts = self.base._artifacts
            if artifacts is None:
                raise RuntimeError("runtime artifacts were not initialized")
            direct = choose_direct_entry_fame(
                normalized,
                selected_hits=selected,
                chunks_by_id=artifacts.chunks_by_id,
                documents_by_id=artifacts.documents_by_id,
            )
            if direct is not None:
                return self._render_direct_entry_fame_result(
                    normalized,
                    direct=direct,
                    selected=selected,
                    route=routed.get("route") or {},
                    retrieval_ms=retrieval_ms,
                    started=started,
                )

            failure_stage = "structured_table"
            stage_started = time.perf_counter()
            table_result = self._structured_table_answer(
                normalized,
                routed=routed,
                selected=selected,
                retrieval_ms=retrieval_ms,
                started=started,
            )
            if table_result is not None:
                return table_result

            if self.fallback_mode == "simple_rag":
                failure_stage = "simple_rag_generation"
                stage_started = time.perf_counter()
                simple_result = answer_simple_rag_from_candidates(
                    question=normalized,
                    model=self.model,
                    timeout=getattr(
                        self,
                        "generation_timeout",
                        self.timeout,
                    ),
                    selected=selected,
                    chunks_by_id=artifacts.chunks_by_id,
                    documents_by_id=artifacts.documents_by_id,
                    temporal_by_document=self.base.temporal_by_document,
                    route=routed.get("route") or {},
                    candidates=self._candidate_rows(selected),
                    retrieval_ms=retrieval_ms,
                    started=started,
                    evidence_mode=self.simple_rag_evidence_mode,
                )
                simple_result = self._apply_operation_guard(
                    simple_result,
                    question=normalized,
                )
                simple_result["rendered_answer"] = (
                    render_simple_natural_answer(
                        simple_result["requirements"]
                    )
                )
                return simple_result

            failure_stage = "live_claim_planning"
            stage_started = time.perf_counter()
            requirements, planner_call = self.planner(
                normalized,
                self.model,
                self.timeout,
            )
            requirements = _resolved_live_requirements(
                requirements,
                question=normalized,
            )
            route = routed.get("route") or {}
            question_time_scope = str(
                route.get("time_scope") or "current"
            )
            as_of = str(route.get("temporal_as_of") or DEFAULT_AS_OF)
            failure_stage = "typed_evidence_prompt"
            stage_started = time.perf_counter()
            prompt, visible_units, _ = (
                build_typed_evidence_prompt_with_candidate_units(
                    question=normalized,
                    requirements=requirements,
                    question_time_scope=question_time_scope,
                    as_of=as_of,
                    candidate_chunk_ids=candidate_ids,
                    chunks_by_id=artifacts.chunks_by_id,
                    documents_by_id=artifacts.documents_by_id,
                    temporal_by_document=self.base.temporal_by_document,
                    selector_mode="baseline",
                )
            )
            structured_rows = build_structured_rows_by_coordinate(
                candidate_ids,
                chunks_by_id=artifacts.chunks_by_id,
            )
            prompt = annotate_prompt_with_structured_rows(
                prompt,
                evidence_units_by_ref=visible_units,
                structured_rows_by_coordinate=structured_rows,
            )
            failure_stage = "typed_generation"
            stage_started = time.perf_counter()
            generation = self.generator(
                prompt=prompt,
                model=self.model,
                timeout_seconds=self.timeout,
            )
            protocol_error = generation.get("protocol_error")
            if protocol_error:
                raise RuntimeError(protocol_error)
            failure_stage = "typed_verification"
            stage_started = time.perf_counter()
            verified = verify_minimal_claim_batch(
                generation["output"],
                requirements=requirements,
                question=normalized,
                as_of=as_of,
                evidence_units_by_ref=visible_units,
                chunks_by_id=artifacts.chunks_by_id,
                structured_rows_by_coordinate=structured_rows,
                profile="v2",
            )
            rendered = _render_batch(verified, requirements)
            rendered = self._apply_operation_guard(
                rendered,
                question=normalized,
            )
            rendered["rendered_answer"] = render_natural_answer(
                rendered["requirements"]
            )
            return {
                "free_minimal_version": FREE_MINIMAL_VERSION,
                "question": normalized,
                **rendered,
                "live_claimspec": requirements,
                "route": route,
                "candidates": self._candidate_rows(selected),
                "planner": planner_call,
                "generation": generation,
                "latency": {
                    "retrieval_ms": retrieval_ms,
                    "planner_ms": float(
                        planner_call.get("latency_ms") or 0
                    ),
                    "generation_ms": float(
                        generation.get("latency_ms") or 0
                    ),
                    "total_ms": round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    ),
                },
                "evaluation_boundary": (
                    "experimental live path; not the frozen Minimal Claim v2 "
                    "5.66-second evaluation result"
                ),
            }
        except Exception as exc:
            generation_diagnostics = getattr(
                exc,
                "generation_diagnostics",
                None,
            )
            ollama_status = (
                _ollama_runtime_status()
                if failure_stage
                in {"simple_rag_generation", "typed_generation"}
                else None
            )
            return self._abstain(
                normalized,
                reason=f"{type(exc).__name__}: {exc}",
                started=started,
                failure_stage=failure_stage,
                failure_stage_ms=round(
                    (time.perf_counter() - stage_started) * 1000,
                    3,
                ),
                retrieval_ms=(
                    round(
                        (time.perf_counter() - stage_started) * 1000,
                        3,
                    )
                    if failure_stage == "retrieval"
                    else retrieval_ms
                ),
                generation_diagnostics=generation_diagnostics,
                ollama_status=ollama_status,
            )

    def _abstain(
        self,
        question: str,
        *,
        reason: str,
        started: float,
        route: dict[str, Any] | None = None,
        retrieval_ms: float = 0.0,
        failure_stage: str | None = None,
        failure_stage_ms: float | None = None,
        generation_diagnostics: dict[str, Any] | None = None,
        ollama_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        generation_failure = failure_stage in {
            "simple_rag_generation",
            "typed_generation",
        }
        return {
            "free_minimal_version": FREE_MINIMAL_VERSION,
            "question": question,
            "response_mode": "abstain",
            "rendered_answer": "",
            "requirements": [],
            "live_claimspec": [],
            "route": route,
            "candidates": [],
            "verification": {
                "all_exposed_citations_verified": True,
                "reason": reason,
                "failure_stage": failure_stage,
            },
            "error": reason,
            "failure_stage": failure_stage,
            "generation": {
                "request": generation_diagnostics or {},
                "usage": {
                    "input_tokens": None,
                    "output_tokens": 0,
                    "total_tokens": None,
                },
                "ollama_status": ollama_status,
            },
            "latency": {
                "retrieval_ms": retrieval_ms,
                "planner_ms": 0.0,
                "generation_ms": (
                    failure_stage_ms if generation_failure else 0.0
                ),
                "failure_stage_ms": failure_stage_ms,
                "total_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
            },
            "evaluation_boundary": (
                "experimental live path; not the frozen Minimal Claim v2 "
                "5.66-second evaluation result"
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--model", default=MODEL_TAG)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--generation-timeout", type=float)
    args = parser.parse_args()
    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    runtime = FreeMinimalClaimV2(
        root=args.root,
        model=args.model,
        device=args.device,
        timeout=args.timeout,
        generation_timeout=args.generation_timeout,
    )
    print(
        json.dumps(
            runtime.answer(args.question),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
