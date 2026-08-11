from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.v3.product_free_rag import ProductFreeRAG


MODEL_TAG = "qwen3-8b:ctx8192"

_RUNTIME: ProductFreeRAG | None = None
_RUNTIME_LOCK = threading.Lock()
_ANSWER_LOCK = threading.Lock()


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


app = FastAPI(title="DNF Product Free RAG API")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_TAG,
        "runtime_loaded": _RUNTIME is not None,
    }


@app.post("/answer")
def answer(request: AnswerRequest) -> dict[str, Any]:
    runtime = _runtime()
    with _ANSWER_LOCK:
        return runtime.answer(request.question)
