import json
import os
import sys
from pathlib import Path

import gradio as gr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))
os.chdir(PROJECT_ROOT)

from generate_answer import build_grounded_answer
from prompt_format import format_prompt
from retrieve import retrieve
from retrieval_config import BGE_M3_MODEL, DEFAULT_RANK_MODE, MINILM_MODEL, RANK_MODES
from run_tuned_slm_smoke import (
    contexts_to_documents,
    generate_answer,
    load_generation_model,
    load_tuned_model,
)


INDEXES = {
    "official_chunks_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma_official_chunks",
        "model": BGE_M3_MODEL,
    },
    "official_chunks_no_header_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma_official_chunks_no_header",
        "model": BGE_M3_MODEL,
    },
    "domain_chunks_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma_domain_chunks",
        "model": BGE_M3_MODEL,
    },
    "official_chunks_fixed_1200_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma_official_chunks_fixed_1200",
        "model": BGE_M3_MODEL,
    },
    "official_docs_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma_official",
        "model": BGE_M3_MODEL,
    },
    "guide_chunks_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma_guide_chunks",
        "model": BGE_M3_MODEL,
    },
    "synthetic_sample_bge_m3": {
        "path": PROJECT_ROOT / "outputs" / "chroma",
        "model": BGE_M3_MODEL,
    },
    "official_chunks_minilm_ablation": {
        "path": PROJECT_ROOT / "outputs" / "chroma_official_chunks_minilm",
        "model": MINILM_MODEL,
    },
}
MODE_LABELS = {
    "RAG-only": "rag_only",
    "Base SLM + RAG": "base_slm",
    "Tuned SLM": "tuned_slm",
    "LLM-RAG": "llm_rag",
}
DEFAULT_TUNED_MODEL = os.environ.get("TUNED_SLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
DEFAULT_ADAPTER_DIR = Path(
    os.environ.get(
        "TUNED_SLM_ADAPTER_DIR",
        PROJECT_ROOT
        / "outputs"
        / "slm_lora_random_control_blind_safe_final"
        / "checkpoint-250",
    )
)
_TUNED_MODEL_CACHE = None
_BASE_MODEL_CACHE = None


def chroma_persist_path(path: Path) -> Path:
    try:
        return path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def evidence_rows(contexts):
    rows = []
    for hit in contexts:
        metadata = hit.get("metadata") or {}
        rows.append(
            [
                hit["rank"],
                hit["doc_id"],
                metadata.get("parent_doc_id") or hit["doc_id"],
                hit["title"],
                hit["doc_type"],
                metadata.get("section", ""),
                hit.get("lexical_score", 0),
                round(hit["distance"], 4) if isinstance(hit.get("distance"), (int, float)) else "",
            ]
        )
    return rows


def load_cached_tuned_model():
    global _TUNED_MODEL_CACHE
    if _TUNED_MODEL_CACHE is None:
        if not DEFAULT_ADAPTER_DIR.exists():
            raise FileNotFoundError(f"Tuned SLM adapter not found: {DEFAULT_ADAPTER_DIR}")
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _TUNED_MODEL_CACHE = load_tuned_model(
            DEFAULT_TUNED_MODEL, DEFAULT_ADAPTER_DIR, device=device, fp16=device == "cuda"
        )
    return _TUNED_MODEL_CACHE


def load_cached_base_model():
    global _BASE_MODEL_CACHE
    if _BASE_MODEL_CACHE is None:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _BASE_MODEL_CACHE = load_generation_model(
            DEFAULT_TUNED_MODEL,
            adapter_dir=None,
            device=device,
            fp16=device == "cuda",
        )
    return _BASE_MODEL_CACHE


def rag_only_response(question: str, contexts: list[dict]) -> dict:
    response = build_grounded_answer(question, contexts).to_dict()
    return {"mode": "rag_only", **response}


def tuned_slm_response(question: str, contexts: list[dict], max_doc_chars: int, max_new_tokens: int) -> dict:
    torch_module, tokenizer, model = load_cached_tuned_model()
    prompt = format_prompt(
        question=question,
        documents=contexts_to_documents(contexts),
        max_doc_chars=max_doc_chars,
    )
    answer = generate_answer(
        torch_module=torch_module,
        tokenizer=tokenizer,
        model=model,
        prompt=prompt,
        max_new_tokens=max_new_tokens,
    )
    return {
        "mode": "tuned_slm",
        "model": DEFAULT_TUNED_MODEL,
        "adapter_dir": str(DEFAULT_ADAPTER_DIR),
        "raw_generation": answer,
    }


def base_slm_response(question: str, contexts: list[dict], max_doc_chars: int, max_new_tokens: int) -> dict:
    torch_module, tokenizer, model = load_cached_base_model()
    prompt = format_prompt(
        question=question,
        documents=contexts_to_documents(contexts),
        max_doc_chars=max_doc_chars,
    )
    answer = generate_answer(
        torch_module=torch_module,
        tokenizer=tokenizer,
        model=model,
        prompt=prompt,
        max_new_tokens=max_new_tokens,
    )
    return {
        "mode": "base_slm",
        "model": DEFAULT_TUNED_MODEL,
        "raw_generation": answer,
    }


def answer_question(
    question: str,
    top_k: int,
    index_name: str,
    rank_mode: str,
    mode_label: str,
    max_doc_chars: int,
    max_new_tokens: int,
):
    if not question.strip():
        return "질문을 입력해 주세요.", []

    index_config = INDEXES.get(index_name, INDEXES["official_chunks_bge_m3"])
    persist_dir = chroma_persist_path(index_config["path"])
    try:
        contexts = retrieve(
            question,
            persist_dir=persist_dir,
            top_k=top_k,
            model_name=index_config["model"],
            rank_mode=rank_mode,
        )
    except Exception as exc:
        message = {
            "error": "검색 인덱스를 찾을 수 없습니다.",
            "detail": str(exc),
            "hint": "README의 Chroma index build 명령을 먼저 실행해 주세요.",
        }
        return json.dumps(message, ensure_ascii=False, indent=2), []

    mode = MODE_LABELS.get(mode_label, "rag_only")
    try:
        if mode == "rag_only":
            response = rag_only_response(question, contexts)
        elif mode == "base_slm":
            response = base_slm_response(question, contexts, int(max_doc_chars), int(max_new_tokens))
        elif mode == "tuned_slm":
            response = tuned_slm_response(question, contexts, int(max_doc_chars), int(max_new_tokens))
        else:
            response = {
                "mode": "llm_rag",
                "status": "not_configured",
                "message": "외부 LLM-RAG 생성기는 아직 연결되지 않았습니다. 동일 held-out eval set 비교를 위한 자리입니다.",
            }
    except Exception as exc:
        response = {
            "mode": mode,
            "error": str(exc),
            "hint": "Tuned SLM은 TUNED_SLM_MODEL과 TUNED_SLM_ADAPTER_DIR 환경변수로 모델/어댑터를 지정할 수 있습니다.",
        }

    return json.dumps(response, ensure_ascii=False, indent=2), evidence_rows(contexts)


with gr.Blocks(title="DNF Domain QA SLM/RAG v2") as demo:
    gr.Markdown("# DNF Domain QA SLM/RAG v2")
    with gr.Row():
        question = gr.Textbox(label="Question", placeholder="예: 공식 문서에서 잔여 오류 관련 핵심 내용은 뭐야?")
        top_k = gr.Slider(label="Top K", minimum=1, maximum=10, step=1, value=3)
    with gr.Row():
        index_name = gr.Dropdown(label="Index", choices=list(INDEXES), value="domain_chunks_bge_m3")
        rank_mode = gr.Dropdown(label="Rank Mode", choices=list(RANK_MODES), value=DEFAULT_RANK_MODE)
        mode = gr.Dropdown(label="Mode", choices=list(MODE_LABELS), value="RAG-only")
        max_doc_chars = gr.Slider(label="Max Doc Chars", minimum=40, maximum=1200, step=20, value=900)
        max_new_tokens = gr.Slider(label="Max New Tokens", minimum=16, maximum=256, step=8, value=256)
    submit = gr.Button("Run")
    response = gr.Code(label="Response", language="json")
    evidence = gr.Dataframe(
        headers=["rank", "chunk_id", "parent_doc_id", "title", "doc_type", "section", "lexical_score", "distance"],
        label="Retrieved Evidence",
    )

    submit.click(
        answer_question,
        inputs=[question, top_k, index_name, rank_mode, mode, max_doc_chars, max_new_tokens],
        outputs=[response, evidence],
    )


if __name__ == "__main__":
    demo.launch()
