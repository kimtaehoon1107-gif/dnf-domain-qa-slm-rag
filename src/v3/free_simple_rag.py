from __future__ import annotations

import json
import os
import time
from typing import Any, Literal
from urllib.request import Request, urlopen

from src.v3.generate_grounded_llm_answer import (
    GroundedAnswerOutput,
    SYSTEM_INSTRUCTIONS,
    build_grounded_prompt,
    generate_grounded_output,
    verify_and_sanitize_output,
)
from src.v3.simple_evidence_refs import (
    ATOMIC_EVIDENCE_REF_VERSION,
    SIMPLE_EVIDENCE_REF_SYSTEM_INSTRUCTIONS,
    SIMPLE_EVIDENCE_REF_VERSION,
    SimpleEvidenceRefOutput,
    build_atomic_evidence_units,
    build_simple_evidence_ref_prompt,
    build_simple_evidence_units,
    verify_simple_evidence_ref_output,
)
from src.v3.simple_domain_rag import enforce_factual_token_support
from src.v3.simple_rag_incremental_guards import (
    apply_relation_value_colocation_guard,
    apply_subject_period_identity_guard,
    apply_temporal_role_guard,
)


FREE_SIMPLE_RAG_VERSION = "dnf-free-simple-rag-experimental-v1"
OUTPUT_TOKENS = 1200
CONTEXT_TOKENS = 8192
_RESPONSE_MODE_RANK = {
    "abstain": 0,
    "partial_answer": 1,
    "full_answer": 2,
}
def cap_response_mode_to_model(
    computed_mode: str,
    *,
    model_mode: str | None,
) -> str:
    """Allow verification to downgrade exposure, never upgrade the model."""

    if model_mode not in _RESPONSE_MODE_RANK:
        return computed_mode
    if _RESPONSE_MODE_RANK[computed_mode] <= _RESPONSE_MODE_RANK[model_mode]:
        return computed_mode
    return model_mode


def _ollama_chat_url() -> str:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return f"{base_url}/api/chat"


def _generation_request_diagnostics(
    *,
    prompt: str,
    model: str,
    timeout_seconds: float,
    evidence_mode: str,
    backend: str,
    candidate_count: int,
    evidence_unit_count: int,
    max_output_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "backend": backend,
        "evidence_mode": evidence_mode,
        "timeout_seconds": timeout_seconds,
        "prompt_chars": len(prompt),
        "prompt_utf8_bytes": len(prompt.encode("utf-8")),
        "candidate_count": candidate_count,
        "evidence_unit_count": evidence_unit_count,
        "max_output_tokens": max_output_tokens,
    }


def _attach_generation_diagnostics(
    exc: Exception,
    diagnostics: dict[str, Any],
) -> None:
    setattr(exc, "generation_diagnostics", diagnostics)


def generate_grounded_output_native(
    *,
    prompt: str,
    model: str,
    timeout_seconds: float,
    num_ctx: int = CONTEXT_TOKENS,
    num_predict: int = OUTPUT_TOKENS,
    seed: int | None = None,
    think: bool = False,
) -> dict[str, Any]:
    options = {
        "temperature": 0,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
    }
    if seed is not None:
        options["seed"] = seed
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": think,
        "format": GroundedAnswerOutput.model_json_schema(),
        "options": options,
    }
    request = Request(
        _ollama_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = str((raw.get("message") or {}).get("content") or "")
    if not content:
        raise RuntimeError("simple_rag_generator_returned_no_content")
    parsed = GroundedAnswerOutput.model_validate_json(content)
    input_tokens = int(raw.get("prompt_eval_count") or 0)
    output_tokens = int(raw.get("eval_count") or 0)
    return {
        "output": parsed.model_dump(),
        "model": raw.get("model") or model,
        "provider": "ollama_native",
        "thinking_enabled": think,
        "latency_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def generate_evidence_ref_output_native(
    *,
    prompt: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": SIMPLE_EVIDENCE_REF_SYSTEM_INSTRUCTIONS,
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "format": SimpleEvidenceRefOutput.model_json_schema(),
        "options": {
            "temperature": 0,
            "num_ctx": CONTEXT_TOKENS,
            "num_predict": OUTPUT_TOKENS,
        },
    }
    request = Request(
        _ollama_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = str((raw.get("message") or {}).get("content") or "")
    if not content:
        raise RuntimeError("simple_rag_ref_generator_returned_no_content")
    parsed = SimpleEvidenceRefOutput.model_validate_json(content)
    input_tokens = int(raw.get("prompt_eval_count") or 0)
    output_tokens = int(raw.get("eval_count") or 0)
    return {
        "output": parsed.model_dump(),
        "model": raw.get("model") or model,
        "provider": "ollama_native",
        "thinking_enabled": False,
        "latency_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def render_simple_natural_answer(
    requirements: list[dict[str, Any]],
) -> str:
    supported = [
        row
        for row in requirements
        if row.get("status") == "supported_exact"
    ]
    evidence_numbers: dict[str, int] = {}
    for row in supported:
        for citation in row.get("citations", []):
            chunk_id = str(citation.get("chunk_id") or "")
            if chunk_id and chunk_id not in evidence_numbers:
                evidence_numbers[chunk_id] = len(evidence_numbers) + 1
    lines = []
    for row in supported:
        refs = " ".join(
            f"[근거 {evidence_numbers[chunk_id]}]"
            for chunk_id in dict.fromkeys(
                str(citation.get("chunk_id") or "")
                for citation in row.get("citations", [])
            )
            if chunk_id in evidence_numbers
        )
        answer = str(row.get("answer") or "").strip()
        lines.append(f"- {answer}" + (f" {refs}" if refs else ""))
    return "\n".join(lines)


def answer_simple_rag_from_candidates(
    *,
    question: str,
    model: str,
    timeout: float,
    selected: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    route: dict[str, Any],
    candidates: list[dict[str, Any]],
    retrieval_ms: float,
    started: float,
    evidence_mode: Literal[
        "exact_quote",
        "server_ref",
        "atomic_ref",
    ] = "exact_quote",
    exact_quote_generation_options: dict[str, Any] | None = None,
    exact_quote_backend: Literal[
        "native",
        "openai_compatible",
    ] = "native",
    include_temporal_role_annotations: bool = False,
) -> dict[str, Any]:
    candidate_ids = [row["chunk_id"] for row in selected]
    evidence_units: list[dict[str, Any]] = []
    if evidence_mode in {"server_ref", "atomic_ref"}:
        if evidence_mode == "atomic_ref":
            evidence_units = build_atomic_evidence_units(
                candidate_ids,
                question=question,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                temporal_by_document=temporal_by_document,
            )
        else:
            evidence_units = build_simple_evidence_units(
                candidate_ids,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                temporal_by_document=temporal_by_document,
            )
        prompt = build_simple_evidence_ref_prompt(
            question=question,
            as_of=str(route.get("temporal_as_of") or "2026-07-16"),
            evidence_units=evidence_units,
        )
        request_diagnostics = _generation_request_diagnostics(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout,
            evidence_mode=evidence_mode,
            backend="ollama_native",
            candidate_count=len(candidate_ids),
            evidence_unit_count=len(evidence_units),
            max_output_tokens=OUTPUT_TOKENS,
        )
        try:
            generated = generate_evidence_ref_output_native(
                prompt=prompt,
                model=model,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            _attach_generation_diagnostics(exc, request_diagnostics)
            raise
        generated["request"] = request_diagnostics
        verified = verify_simple_evidence_ref_output(
            generated["output"],
            question=question,
            evidence_units=evidence_units,
            chunks_by_id=chunks_by_id,
        )
    else:
        prompt = build_grounded_prompt(
            question=question,
            as_of=str(
                route.get("temporal_as_of") or "2026-07-16"
            ),
            candidate_chunk_ids=candidate_ids,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
            include_temporal_role_annotations=(
                include_temporal_role_annotations
            ),
        )
        generation_options = dict(exact_quote_generation_options or {})
        max_output_tokens = int(
            generation_options.get("num_predict") or OUTPUT_TOKENS
        )
        request_diagnostics = _generation_request_diagnostics(
            prompt=prompt,
            model=model,
            timeout_seconds=timeout,
            evidence_mode=evidence_mode,
            backend=exact_quote_backend,
            candidate_count=len(candidate_ids),
            evidence_unit_count=len(evidence_units),
            max_output_tokens=max_output_tokens,
        )
        request_diagnostics["temporal_role_annotations"] = (
            include_temporal_role_annotations
        )
        try:
            if exact_quote_backend == "native":
                generated = generate_grounded_output_native(
                    prompt=prompt,
                    model=model,
                    timeout_seconds=timeout,
                    **generation_options,
                )
            elif exact_quote_backend == "openai_compatible":
                unsupported = set(generation_options) - {"num_predict"}
                if unsupported:
                    raise RuntimeError(
                        "openai-compatible exact quote only supports "
                        f"num_predict, got {sorted(unsupported)}"
                    )
                generated = generate_grounded_output(
                    prompt=prompt,
                    model=model,
                    timeout_seconds=timeout,
                    max_output_tokens=max_output_tokens,
                )
            else:
                raise RuntimeError(
                    f"unsupported exact quote backend: {exact_quote_backend}"
                )
        except Exception as exc:
            _attach_generation_diagnostics(exc, request_diagnostics)
            raise
        generated["request"] = request_diagnostics
        verified = verify_and_sanitize_output(
            generated["output"],
            candidate_chunk_ids=candidate_ids,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
        )
    checked = enforce_factual_token_support(verified)
    checked = apply_subject_period_identity_guard(
        checked,
        question=question,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
    )
    checked = apply_relation_value_colocation_guard(
        checked,
        question=question,
    )
    checked = apply_temporal_role_guard(
        checked,
        question=question,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
    )
    checked["rendered_answer"] = render_simple_natural_answer(
        checked["requirements"]
    )
    generation_ms = float(generated.get("latency_ms") or 0)
    return {
        "free_simple_rag_version": FREE_SIMPLE_RAG_VERSION,
        "evidence_mode": evidence_mode,
        "exact_quote_backend": (
            exact_quote_backend if evidence_mode == "exact_quote" else None
        ),
        "evidence_ref_version": (
            (
                ATOMIC_EVIDENCE_REF_VERSION
                if evidence_mode == "atomic_ref"
                else SIMPLE_EVIDENCE_REF_VERSION
            )
            if evidence_mode in {"server_ref", "atomic_ref"}
            else None
        ),
        "evidence_unit_count": len(evidence_units),
        "question": question,
        **checked,
        "live_claimspec": [],
        "route": route,
        "candidates": candidates,
        "planner": {
            "mode": "not_used_by_simple_rag",
            "latency_ms": 0.0,
        },
        "generation": generated,
        "latency": {
            "retrieval_ms": retrieval_ms,
            "planner_ms": 0.0,
            "generation_ms": generation_ms,
            "total_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        },
        "evaluation_boundary": (
            "experimental live free-question path; not a frozen "
            "generalization result"
        ),
    }
