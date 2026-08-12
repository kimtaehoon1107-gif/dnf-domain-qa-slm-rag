from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.v3.product_free_rag import (
    DEFAULT_PRODUCT_BM25_MANIFEST,
    ProductFreeRAG,
)
from app.ui.adapter import to_view_model


MODEL_TAG = "qwen3-8b:ctx8192"
PIPELINE_TAG = "product_free_rag_v1"
UI_DIR = PROJECT_ROOT / "app" / "ui"
_INDEX_MANIFEST = json.loads(
    (PROJECT_ROOT / DEFAULT_PRODUCT_BM25_MANIFEST).read_text(encoding="utf-8")
)
CORPUS_BASIS_DATE = str(_INDEX_MANIFEST["built_at"]).split("T", 1)[0]

_RUNTIME: ProductFreeRAG | None = None
_RUNTIME_LOCK = threading.Lock()
_ANSWER_LOCK = threading.Lock()
_RETRIEVAL_READY = False


def _runtime() -> ProductFreeRAG:
    """Load the product runtime once; the CUDA handoff makes it single-use."""

    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            os.environ.setdefault(
                "OPENAI_BASE_URL",
                "http://localhost:11434/v1",
            )
            os.environ.setdefault("OPENAI_API_KEY", "ollama")
            _RUNTIME = ProductFreeRAG(
                root=PROJECT_ROOT,
                model=MODEL_TAG,
                device="cuda",
                timeout=180.0,
                use_identity_shortlist=True,
                use_compact_evidence_pack=True,
                use_atomic_evidence_reranker=True,
                use_table_comparison_reservation=True,
                use_server_availability_rendering=True,
                use_server_content_kind_rendering=True,
                use_server_reward_kind_rendering=True,
                handoff_cuda_to_generation=True,
            )
        return _RUNTIME


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


app = FastAPI(title="DNF Product Free RAG v1 API")
app.mount(
    "/ui/assets",
    StaticFiles(directory=UI_DIR / "assets"),
    name="ui-assets",
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "pipeline": PIPELINE_TAG,
        "model": MODEL_TAG,
        "corpus_basis_date": CORPUS_BASIS_DATE,
        "runtime_loaded": _RUNTIME is not None,
        "retrieval_ready": _RETRIEVAL_READY,
    }


@app.post("/answer")
def answer(request: AnswerRequest) -> dict[str, Any]:
    global _RETRIEVAL_READY

    runtime = _runtime()
    with _ANSWER_LOCK:
        result = runtime.answer(request.question)
        _RETRIEVAL_READY = True
        return result


@app.post("/warmup")
def warmup() -> dict[str, Any]:
    """Load retrieval models before a recording without calling Qwen."""

    global _RETRIEVAL_READY

    runtime = _runtime()
    with _ANSWER_LOCK:
        result = runtime.preinitialize_retrieval()
        _RETRIEVAL_READY = True
        return {"status": "ready", **result}


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/ui", include_in_schema=False)
def ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/ui/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(UI_DIR / "chat_preview.html")


@app.post("/ui/answer")
def ui_answer(request: AnswerRequest) -> dict[str, Any]:
    view = asdict(to_view_model(answer(request)))
    view["developer"]["pipeline"] = PIPELINE_TAG
    return view
