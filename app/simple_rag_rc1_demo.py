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

from src.v3.simple_rag_rc1 import MODEL_TAG, RC1_VERSION, SimpleRAGRC1


_RUNTIME: SimpleRAGRC1 | None = None


def _runtime() -> SimpleRAGRC1:
    global _RUNTIME
    if _RUNTIME is None:
        os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
        os.environ.setdefault("OPENAI_API_KEY", "ollama")
        _RUNTIME = SimpleRAGRC1(root=PROJECT_ROOT)
    return _RUNTIME


def _answer_markdown(result: dict[str, Any]) -> str:
    mode = result.get("response_mode") or "abstain"
    rendered = str(result.get("rendered_answer") or "").strip()
    latency = float(result.get("latency_ms") or 0.0) / 1000
    generation = result.get("generation") or {}
    generation_error = generation.get("error") or result.get(
        "verification", {}
    ).get("generation_error")
    guard_failures = result.get("rc1", {}).get("guard_failures") or []

    parts = [
        f"### 상태: `{mode}`",
        rendered or "문서 근거로 확인 가능한 답변이 없습니다.",
        f"총 처리시간: **{latency:.2f}초**",
    ]
    if guard_failures:
        parts.append(
            "안전 검증 차단:\n```json\n"
            + json.dumps(guard_failures, ensure_ascii=False, indent=2)
            + "\n```"
        )
    if generation_error:
        parts.append(f"생성 오류: `{generation_error}`")
    return "\n\n".join(parts)


def _citation_rows(result: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for requirement in result.get("requirements", []):
        for citation in requirement.get("citations", []):
            rows.append(
                [
                    requirement.get("requirement_index"),
                    requirement.get("question_part"),
                    requirement.get("answer"),
                    citation.get("source_id"),
                    citation.get("chunk_id"),
                    citation.get("start_char"),
                    citation.get("end_char"),
                    citation.get("text"),
                ]
            )
    return rows


def _candidate_rows(result: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            candidate.get("candidate_ref"),
            candidate.get("source_id"),
            candidate.get("title"),
            candidate.get("published_at"),
            candidate.get("status"),
            candidate.get("chunk_id"),
            candidate.get("reranker_score"),
        ]
        for candidate in result.get("candidates", [])
    ]


def answer_question(
    question: str,
) -> tuple[str, str, list[list[Any]], list[list[Any]]]:
    if not str(question or "").strip():
        return "질문을 입력해 주세요.", "{}", [], []
    try:
        result = _runtime().answer(question)
    except Exception as exc:
        error = {
            "response_mode": "abstain",
            "error": f"{type(exc).__name__}: {exc}",
        }
        return (
            f"### 실행 실패\n\n`{error['error']}`",
            json.dumps(error, ensure_ascii=False, indent=2),
            [],
            [],
        )
    return (
        _answer_markdown(result),
        json.dumps(result, ensure_ascii=False, indent=2),
        _citation_rows(result),
        _candidate_rows(result),
    )


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="DNF Simple RAG RC1") as demo:
        gr.Markdown(
            "# DNF Simple RAG RC1\n\n"
            f"`{RC1_VERSION}` · `{MODEL_TAG}` · Product Router v2 "
            "+ A1~A3 Minimal Safety Guards\n\n"
            "포트폴리오·연구 데모이며 실제 제품 기본 배포 모델은 아닙니다."
        )
        question = gr.Textbox(
            label="질문",
            placeholder="예: 업데이트는 언제 적용됐어?",
            lines=3,
        )
        submit = gr.Button("질문하기", variant="primary")
        answer = gr.Markdown(label="답변")
        with gr.Accordion("원문 인용", open=True):
            citations = gr.Dataframe(
                headers=[
                    "요구",
                    "질문 부분",
                    "답변",
                    "출처",
                    "청크 ID",
                    "시작",
                    "끝",
                    "원문",
                ],
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
                    "청크 ID",
                    "reranker",
                ],
                interactive=False,
            )
        with gr.Accordion("전체 JSON", open=False):
            raw = gr.Code(label="RC1 출력", language="json")

        submit.click(
            answer_question,
            inputs=question,
            outputs=[answer, raw, citations, candidates],
        )
        question.submit(
            answer_question,
            inputs=question,
            outputs=[answer, raw, citations, candidates],
        )
    return demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-name", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args()
    build_demo().queue(default_concurrency_limit=1).launch(
        server_name=args.server_name,
        server_port=args.server_port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
