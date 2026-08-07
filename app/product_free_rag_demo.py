from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import gradio as gr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.v3.product_free_rag import (
    ProductFreeRAG,
    render_product_clarification_options,
    resolve_product_clarification_followup,
    rewrite_product_clarification_question,
)


PIPELINES = ("legacy_experimental", "product_free_rag_v1")
MODEL_TAG = "qwen3-8b:ctx8192"
EXPANDED_TABLE_INDEX_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_index_manifest_"
    "888974fe242b695e8dd2dbdd0ab30c859223390a9b69e15da7d2937a6b4a23cf.json"
)
_RUNTIMES: dict[str, Any] = {}


def _runtime(pipeline: str) -> Any:
    if pipeline in _RUNTIMES:
        return _RUNTIMES[pipeline]
    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    if pipeline == "product_free_rag_v1":
        runtime = ProductFreeRAG(
            root=PROJECT_ROOT,
            model=MODEL_TAG,
            device="cuda",
            timeout=180.0,
            use_identity_shortlist=True,
            use_compact_evidence_pack=True,
            use_atomic_evidence_reranker=True,
            handoff_cuda_to_generation=True,
        )
    elif pipeline == "legacy_experimental":
        from src.v3.free_minimal_claim_v2 import FreeMinimalClaimV2

        runtime = FreeMinimalClaimV2(
            root=PROJECT_ROOT,
            device="cpu",
            timeout=90.0,
            generation_timeout=30.0,
            fallback_mode="simple_rag",
            table_index_manifest=EXPANDED_TABLE_INDEX_MANIFEST,
            enable_metadata_queries=True,
        )
    else:
        raise RuntimeError(f"unsupported pipeline: {pipeline}")
    _RUNTIMES[pipeline] = runtime
    return runtime


def _mode(result: dict[str, Any]) -> str:
    return str(result.get("mode") or result.get("response_mode") or "unsupported")


def _answer_markdown(
    result: dict[str, Any],
    *,
    pipeline: str,
) -> str:
    rendered = str(result.get("rendered_answer") or "").strip()
    latency = result.get("latency") or {}
    total_ms = float(
        latency.get("total_ms") or result.get("latency_ms") or 0
    )
    generation_ms = float(latency.get("generation_ms") or 0)
    return "\n\n".join(
        (
            f"### 상태: `{_mode(result)}`",
            rendered or "검증 가능한 공식 문서 근거를 찾지 못했습니다.",
            (
                f"파이프라인 `{pipeline}` · 전체 **{total_ms / 1000:.2f}초**"
                f" · Qwen **{generation_ms / 1000:.2f}초**"
            ),
        )
    )


def _citation_rows(result: dict[str, Any]) -> list[list[Any]]:
    rows = []
    if "claims" in result:
        for claim in result.get("claims") or []:
            for citation in claim.get("citations") or []:
                rows.append(
                    [
                        citation.get("evidence_ref"),
                        citation.get("title"),
                        citation.get("chunk_id"),
                        citation.get("start_char"),
                        citation.get("end_char"),
                        citation.get("text"),
                    ]
                )
        return rows
    for requirement in result.get("requirements") or []:
        for citation in requirement.get("citations") or []:
            rows.append(
                [
                    citation.get("evidence_ref"),
                    citation.get("title"),
                    citation.get("chunk_id") or citation.get("document_id"),
                    citation.get("start_char"),
                    citation.get("end_char"),
                    citation.get("text"),
                ]
            )
    return rows


def _candidate_rows(result: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            row.get("candidate_ref"),
            row.get("source_id"),
            row.get("title"),
            row.get("published_at"),
            row.get("status"),
            row.get("chunk_id") or row.get("document_id"),
            row.get("reranker_score"),
        ]
        for row in result.get("candidates") or []
    ]


def _clarification_state(
    *,
    original_question: str,
    pipeline: str,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    options = list(result.get("clarification_options") or [])
    if (
        pipeline != "product_free_rag_v1"
        or _mode(result) != "clarification"
        or not options
    ):
        return None
    return {
        "pipeline": pipeline,
        "original_question": original_question,
        "options": options,
        "candidates": list(result.get("candidates") or []),
    }


def _pending_clarification_result(
    question: str,
    *,
    options: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    clarification = render_product_clarification_options(options)
    return {
        "question": question,
        "mode": "clarification",
        "model_mode": None,
        "claims": [],
        "rejected_claims": [],
        "clarification": clarification,
        "clarification_options": options,
        "rendered_answer": clarification,
        "candidates": candidates,
        "generation": None,
        "verification": {
            "all_exposed_citations_verified": True,
            "qwen_called": False,
            "reason": reason,
        },
        "latency_ms": 0.0,
    }


def _looks_like_new_question(question: str) -> bool:
    normalized = " ".join(str(question or "").split())
    return len(normalized) >= 8 and any(
        cue in normalized
        for cue in ("알려", "설명", "어떻게", "언제", "몇", "?")
    )


def answer_question(
    question: str,
    pipeline: str,
    pending_state: dict[str, Any] | None = None,
) -> tuple[
    str,
    list[list[Any]],
    list[list[Any]],
    str,
    dict[str, Any] | None,
]:
    if not str(question or "").strip():
        return "질문을 입력해 주세요.", [], [], "{}", pending_state
    normalized = " ".join(str(question).split())
    pending = (
        pending_state
        if isinstance(pending_state, dict)
        and pending_state.get("pipeline") == pipeline
        and pipeline == "product_free_rag_v1"
        else None
    )
    effective_question = normalized
    resolution = None
    if pending is not None:
        if normalized in {"취소", "새 질문", "처음부터"}:
            result = {
                "mode": "clarification",
                "claims": [],
                "clarification": "이전 선택을 취소했습니다. 새 질문을 입력해 주세요.",
                "rendered_answer": "이전 선택을 취소했습니다. 새 질문을 입력해 주세요.",
                "candidates": [],
                "verification": {"qwen_called": False, "reason": "cancelled"},
            }
            return (
                _answer_markdown(result, pipeline=pipeline),
                [],
                [],
                json.dumps(result, ensure_ascii=False, indent=2),
                None,
            )
        resolution = resolve_product_clarification_followup(
            normalized,
            list(pending.get("options") or []),
        )
        if resolution["status"] != "resolved":
            if (
                resolution["status"] == "unmatched"
                and _looks_like_new_question(normalized)
            ):
                pending = None
            else:
                options = (
                    resolution.get("options")
                    or list(pending.get("options") or [])
                )
                result = _pending_clarification_result(
                    normalized,
                    options=options,
                    candidates=list(pending.get("candidates") or []),
                    reason=(
                        "clarification_followup_still_ambiguous"
                        if resolution["status"] == "clarification"
                        else "clarification_followup_unmatched"
                    ),
                )
                next_state = {
                    **pending,
                    "options": options,
                }
                return (
                    _answer_markdown(result, pipeline=pipeline),
                    [],
                    _candidate_rows(result),
                    json.dumps(result, ensure_ascii=False, indent=2),
                    next_state,
                )
        if pending is not None and resolution["status"] == "resolved":
            effective_question = rewrite_product_clarification_question(
                str(pending["original_question"]),
                resolution["option"],
            )
    try:
        answer_kwargs = {}
        if pending is not None and resolution is not None:
            answer_kwargs["required_parent_document_id"] = str(
                resolution["option"]["parent_document_id"]
            )
        result = _runtime(pipeline).answer(
            effective_question,
            **answer_kwargs,
        )
        if pending is not None and resolution is not None:
            result["clarification_resolution"] = {
                "original_question": pending["original_question"],
                "followup": normalized,
                "selected_option": resolution["option"],
                "rewritten_question": effective_question,
            }
    except Exception as exc:
        result = {
            "mode": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        return (
            f"### 실행 실패\n\n`{type(exc).__name__}: {exc}`",
            [],
            [],
            json.dumps(result, ensure_ascii=False, indent=2),
            pending_state,
        )
    next_state = _clarification_state(
        original_question=effective_question,
        pipeline=pipeline,
        result=result,
    )
    return (
        _answer_markdown(result, pipeline=pipeline),
        _citation_rows(result),
        _candidate_rows(result),
        json.dumps(result, ensure_ascii=False, indent=2),
        next_state,
    )


def build_demo(*, default_pipeline: str) -> gr.Blocks:
    with gr.Blocks(title="DNF Product Free RAG v1") as demo:
        gr.Markdown(
            "# DNF Product Free RAG v1\n\n"
            "기존 연구 파이프라인과 새 최소 제품 경로를 같은 질문으로 "
            "비교합니다. 기본값은 승격 전까지 `legacy_experimental`입니다."
        )
        pipeline = gr.Radio(
            choices=list(PIPELINES),
            value=default_pipeline,
            label="파이프라인",
        )
        question = gr.Textbox(
            label="질문",
            placeholder="예: 최후의 과업이랑 디레지에 입장 명성 알려줘",
            lines=3,
        )
        submit = gr.Button("질문하기", variant="primary")
        answer = gr.Markdown(label="답변")
        with gr.Accordion("서버가 복원한 원문 인용", open=True):
            citations = gr.Dataframe(
                headers=["근거", "제목", "청크", "시작", "끝", "원문"],
                interactive=False,
            )
        with gr.Accordion("검색 후보", open=False):
            candidates = gr.Dataframe(
                headers=[
                    "후보",
                    "출처",
                    "문서 제목",
                    "게시일",
                    "상태",
                    "청크",
                    "reranker",
                ],
                interactive=False,
            )
        with gr.Accordion("전체 JSON", open=False):
            raw = gr.Code(label="출력", language="json")
        pending_clarification = gr.State(None)
        for trigger in (submit.click, question.submit):
            trigger(
                answer_question,
                inputs=[question, pipeline, pending_clarification],
                outputs=[
                    answer,
                    citations,
                    candidates,
                    raw,
                    pending_clarification,
                ],
            )
    return demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", choices=PIPELINES, default=PIPELINES[0])
    parser.add_argument("--server-name", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=7861)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args()
    build_demo(default_pipeline=args.pipeline).queue(
        default_concurrency_limit=1
    ).launch(
        server_name=args.server_name,
        server_port=args.server_port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
