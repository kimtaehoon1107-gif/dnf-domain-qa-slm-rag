from __future__ import annotations

import json
import os
import time
from typing import Any, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


LLM_QUERY_PLAN_VERSION = "dnf-llm-query-plan-experimental-v1"
QUERY_PLAN_OUTPUT_TOKENS = 192
QUERY_PLAN_CONTEXT_TOKENS = 2048

RouteMode = Literal[
    "metadata",
    "semantic_rag",
    "metadata_then_rag",
    "clarification",
]
Collection = Literal[
    "events",
    "updates",
    "notices",
    "faq",
    "guides",
    "policies",
    "seria_shop",
    "monthly_items",
    "unknown",
]
Operation = Literal["list_all", "count", "latest", "none"]
SortField = Literal[
    "published_at",
    "valid_from",
    "valid_to",
    "effective_at",
    "none",
]


COLLECTION_SOURCE_IDS = {
    "events": "dnf_event",
    "updates": "dnf_update",
    "notices": "dnf_notice",
    "faq": "dnf_faq",
    "guides": "dnf_game_guide",
    "policies": "dnf_account_policy",
    "seria_shop": "dnf_seria_shop",
    "monthly_items": "dnf_monthly_item",
}

_METADATA_SORT_FIELDS = {
    "events": frozenset({"published_at", "valid_from", "valid_to"}),
    "updates": frozenset({"published_at"}),
    "notices": frozenset({"published_at"}),
}


class LlmQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RouteMode
    collection: Collection
    operation: Operation = "none"
    sort_field: SortField = "none"
    active_only: bool = False
    content_query: str = Field(default="", max_length=300)
    clarification: str = Field(default="", max_length=300)


QUERY_PLAN_SYSTEM_PROMPT = """Classify one Korean DNF official-document
question into a small executable query plan. Do not answer the question.

Modes:
- metadata: deterministic list, count, current/active, latest/first, or sorting
  over document records.
- semantic_rag: answer a fact from document content.
- metadata_then_rag: first select documents by metadata, then answer a content
  question inside those documents.
- clarification: the requested ordering or meaning is materially ambiguous.

Collections:
events, updates, notices, faq, guides, policies, seria_shop, monthly_items,
unknown.

Rules:
- "current/ongoing events" means events + active_only=true.
- "latest update/notice" means latest by published_at.
- "most recently started event" means latest by valid_from.
- Bare "latest event" is ambiguous: clarify whether latest published, latest
  started, or currently active.
- A reward, benefit, condition, price, entry fame, method, item, rule, or other
  document-content question is semantic_rag.
- If a question says "in the latest update/notice, what changed...", use
  metadata_then_rag with latest and preserve the requested content in
  content_query.
- operation is none for semantic_rag and clarification.
- sort_field is none unless metadata ordering is required.
- Never invent a collection outside the enum. Return only schema-valid JSON."""


def _ollama_chat_url() -> str:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return f"{base_url}/api/chat"


def validate_llm_query_plan(plan: LlmQueryPlan) -> None:
    if plan.mode == "clarification":
        if not plan.clarification.strip():
            raise RuntimeError("clarification_text_required")
        if plan.operation != "none" or plan.sort_field != "none":
            raise RuntimeError("clarification_must_not_execute")
        return

    if plan.mode == "semantic_rag":
        if plan.operation != "none" or plan.sort_field != "none":
            raise RuntimeError("semantic_rag_must_not_execute_metadata")
        return

    allowed_sort_fields = _METADATA_SORT_FIELDS.get(plan.collection)
    if allowed_sort_fields is None:
        raise RuntimeError(
            f"metadata_collection_not_supported:{plan.collection}"
        )
    if plan.operation == "none":
        raise RuntimeError("metadata_operation_required")
    if plan.operation == "latest":
        if plan.sort_field not in allowed_sort_fields:
            raise RuntimeError(
                "metadata_sort_field_not_allowed:"
                f"{plan.collection}:{plan.sort_field}"
            )
    elif plan.sort_field != "none":
        raise RuntimeError("metadata_sort_only_allowed_for_latest")
    if plan.active_only and plan.collection != "events":
        raise RuntimeError("active_only_requires_events")
    if plan.mode == "metadata_then_rag" and not plan.content_query.strip():
        raise RuntimeError("metadata_then_rag_content_query_required")


def plan_query_with_qwen(
    question: str,
    *,
    model: str,
    timeout: float,
) -> tuple[LlmQueryPlan, dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": QUERY_PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
        "format": LlmQueryPlan.model_json_schema(),
        "options": {
            "temperature": 0,
            "num_ctx": QUERY_PLAN_CONTEXT_TOKENS,
            "num_predict": QUERY_PLAN_OUTPUT_TOKENS,
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
        raise RuntimeError("llm_query_planner_returned_no_content")
    plan = LlmQueryPlan.model_validate_json(content)
    validate_llm_query_plan(plan)
    return plan, {
        "query_plan_version": LLM_QUERY_PLAN_VERSION,
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
