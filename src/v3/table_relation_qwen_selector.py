from __future__ import annotations

import json
import os
import time
from typing import Any, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from src.v3.table_relation_shadow import relation_selector_text


SELECTOR_VERSION = "dnf-table-relation-qwen-selector-shadow-v1"
SELECTOR_CONTEXT_TOKENS = 2048
SELECTOR_OUTPUT_TOKENS = 128


class RelationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["select", "clarification", "unsupported"]
    selection_id: str = Field(default="", max_length=12)
    qualifier: str = Field(default="", max_length=80)
    clarification: str = Field(default="", max_length=240)


SYSTEM_PROMPT = """Select evidence for one Korean DNF question from a closed
list of exact official-document table fields. Do not answer the question and do
not produce any number, date, item, or value.

Return mode=select only when one option's document subject and field match the
question's intended meaning. Interpret ordinary paraphrases semantically, but
never repair a wrong document subject. If the option has qualifiers and the
question names one qualifier, copy that exact qualifier. Leave qualifier empty
when the question requests the complete field across all qualifiers.

Return mode=clarification when the question is broad enough to refer to
different facts, such as a generic reward question when the options only prove
a reward count, condition, or one reward subtype. Ask one short clarification.
Return mode=unsupported when no option supports the requested subject and
relation. Use only a supplied selection_id and exact supplied qualifier. Return
only schema-valid JSON."""


def _ollama_chat_url() -> str:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return f"{base_url}/api/chat"


def build_relation_options(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    options = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, 1):
        option_id = f"R{index}"
        option = {
            "selection_id": option_id,
            "document_title": row["title"],
            "section": " > ".join(
                str(value) for value in row.get("heading_path") or []
            ),
            "table": row.get("table_caption") or "",
            "field": row["relation_label"],
            "qualifiers": list(row.get("qualifiers") or []),
        }
        options.append(option)
        by_id[option_id] = row
    return options, by_id


def build_selector_prompt(
    question: str,
    options: list[dict[str, Any]],
) -> str:
    return (
        f"질문:\n{question}\n\n"
        "선택 가능한 실제 표 항목:\n"
        + json.dumps(options, ensure_ascii=False, indent=2)
    )


def validate_relation_selection(
    selection: RelationSelection,
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    selection_id = selection.selection_id.strip()
    qualifier = selection.qualifier.strip()
    clarification = selection.clarification.strip()
    if selection.mode == "select":
        if clarification:
            raise RuntimeError("select_must_not_include_clarification")
        if selection_id not in by_id:
            raise RuntimeError("unknown_relation_selection_id")
        row = by_id[selection_id]
        qualifiers = list(row.get("qualifiers") or [])
        if qualifier and qualifier not in qualifiers:
            raise RuntimeError("unknown_relation_qualifier")
        if qualifier and len(qualifiers) != len(row.get("values") or []):
            raise RuntimeError("relation_qualifier_value_mismatch")
        return row
    if selection_id or qualifier:
        raise RuntimeError("non_select_must_not_choose_evidence")
    if selection.mode == "clarification":
        if not clarification:
            raise RuntimeError("clarification_text_required")
        return None
    if clarification:
        raise RuntimeError("unsupported_must_not_include_clarification")
    return None


def selected_relation_values(
    row: dict[str, Any],
    qualifier: str,
) -> tuple[list[str], list[str]]:
    qualifier = qualifier.strip()
    values = list(row.get("values") or [])
    qualifiers = list(row.get("qualifiers") or [])
    if not qualifier:
        return values, qualifiers
    index = qualifiers.index(qualifier)
    return [values[index]], [qualifier]


def select_relation_with_qwen(
    question: str,
    rows: list[dict[str, Any]],
    *,
    model: str,
    timeout: float,
) -> tuple[RelationSelection, dict[str, Any] | None, dict[str, Any]]:
    options, by_id = build_relation_options(rows)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_selector_prompt(question, options),
            },
        ],
        "stream": False,
        "think": False,
        "format": RelationSelection.model_json_schema(),
        "options": {
            "temperature": 0,
            "num_ctx": SELECTOR_CONTEXT_TOKENS,
            "num_predict": SELECTOR_OUTPUT_TOKENS,
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
        raise RuntimeError("relation_selector_returned_no_content")
    selection = RelationSelection.model_validate_json(content)
    row = validate_relation_selection(selection, by_id)
    return selection, row, {
        "selector_version": SELECTOR_VERSION,
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
        "options": options,
    }


def relation_row_reranker_text(row: dict[str, Any]) -> str:
    qualifiers = ", ".join(row.get("qualifiers") or [])
    base = relation_selector_text(row)
    return base + (
        f"\n가능한 한정자: {qualifiers}" if qualifiers else ""
    )
