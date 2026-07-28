from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from src.v3.simple_domain_rag import SimpleDomainRAG
from src.v3.simple_rag_incremental_guards import (
    apply_relation_value_colocation_guard,
    apply_subject_period_identity_guard,
    apply_temporal_role_guard,
)


RC1_VERSION = "dnf-simple-rag-rc1"
BASE_SOURCE_COMMIT = "f34eec002196fb008b411da76d9d8f4772a6dc3c"
BASE_SOURCE_SHA256 = (
    "b7714a3e4c0cf52c7480f8d777ec73dff138b6c58ea11b4ecfb33edc0880145b"
)
MODEL_TAG = "qwen3-8b:ctx8192"
MODEL_BLOB_SHA256 = (
    "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
)
GUARD_STAGES = (
    "A1_subject_period_identity",
    "A2_relation_value_colocation",
    "A3_explicit_temporal_conflict",
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_base_source(root: Path) -> None:
    source = root / "src/v3/simple_domain_rag.py"
    actual = _file_sha256(source)
    if actual != BASE_SOURCE_SHA256:
        raise RuntimeError(
            "RC1 requires the frozen Simple RAG v2 source "
            f"{BASE_SOURCE_SHA256}, got {actual}"
        )


def _verify_model(model: str) -> None:
    if model != MODEL_TAG:
        raise RuntimeError(f"RC1 requires model {MODEL_TAG}, got {model}")
    completed = subprocess.run(
        ["ollama", "show", model, "--modelfile"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"FROM .+sha256-([0-9a-f]{64})", completed.stdout)
    if match is None or match.group(1) != MODEL_BLOB_SHA256:
        raise RuntimeError("RC1 Ollama model blob does not match the seal")
    if "PARAMETER num_ctx 8192" not in completed.stdout:
        raise RuntimeError("RC1 Ollama model must use num_ctx 8192")


def _guard_failures(result: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for audit in result.get("verification", {}).get("requirements", []):
        failures = [
            reason
            for reason in audit.get("failure_reasons", [])
            if reason
            in {
                "explicit_subject_period_identity_mismatch",
                "relation_value_not_colocated",
                "temporal_role_conflict",
            }
        ]
        if failures:
            output.append(
                {
                    "requirement_index": audit.get("requirement_index"),
                    "failure_reasons": failures,
                    "guard_details": audit.get("guard_details") or {},
                }
            )
    return output


class SimpleRAGRC1:
    """Frozen Simple RAG v2 plus the three minimal RC1 safety guards."""

    def __init__(
        self,
        *,
        root: Path,
        model: str = MODEL_TAG,
        device: str | None = None,
        timeout: float = 180.0,
        base: Any | None = None,
    ) -> None:
        self.root = root.resolve()
        if base is None:
            _verify_base_source(self.root)
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
        self.model = model

    def answer(self, question: str) -> dict[str, Any]:
        baseline = self.base.answer(question)
        artifacts = getattr(self.base, "_artifacts", None)
        if artifacts is None:
            return {
                **baseline,
                "rc1_version": RC1_VERSION,
                "rc1": {
                    "base_source_commit": BASE_SOURCE_COMMIT,
                    "base_source_sha256": BASE_SOURCE_SHA256,
                    "model": self.model,
                    "guard_stages": list(GUARD_STAGES),
                    "guard_failures": [],
                },
            }

        guard_started = time.perf_counter()
        guarded = apply_subject_period_identity_guard(
            baseline,
            question=question,
            chunks_by_id=artifacts.chunks_by_id,
            documents_by_id=artifacts.documents_by_id,
        )
        guarded = apply_relation_value_colocation_guard(
            guarded,
            question=question,
        )
        guarded = apply_temporal_role_guard(
            guarded,
            question=question,
            chunks_by_id=artifacts.chunks_by_id,
            documents_by_id=artifacts.documents_by_id,
        )
        guard_latency_ms = round(
            (time.perf_counter() - guard_started) * 1000,
            3,
        )

        candidates = []
        for candidate in guarded.get("candidates", []):
            chunk = artifacts.chunks_by_id.get(candidate["chunk_id"], {})
            document = artifacts.documents_by_id.get(
                candidate.get("parent_document_id")
                or chunk.get("parent_document_id"),
                {},
            )
            candidates.append(
                {
                    **candidate,
                    "title": document.get("title"),
                    "published_at": document.get("published_at"),
                    "status": document.get("status"),
                }
            )

        verification = {
            **guarded.get("verification", {}),
            "rc1_guard_stages": list(GUARD_STAGES),
            "rc1_guard_failures": _guard_failures(guarded),
        }
        return {
            **guarded,
            "rc1_version": RC1_VERSION,
            "candidates": candidates,
            "verification": verification,
            "rc1": {
                "base_source_commit": BASE_SOURCE_COMMIT,
                "base_source_sha256": BASE_SOURCE_SHA256,
                "model": self.model,
                "model_blob_sha256": MODEL_BLOB_SHA256,
                "guard_stages": list(GUARD_STAGES),
                "guard_latency_ms": guard_latency_ms,
                "guard_failures": verification["rc1_guard_failures"],
                "non_promoted_features": {
                    "typed_evidence_ref": False,
                    "b134_citation_repair": False,
                    "relation_semantic_selector": False,
                    "subject_anchored_search": False,
                    "semantic_fallback": False,
                },
            },
            "latency_ms": round(
                float(guarded.get("latency_ms") or 0.0) + guard_latency_ms,
                3,
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
    parser.add_argument("--device")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    runtime = SimpleRAGRC1(
        root=args.root,
        model=args.model,
        device=args.device,
        timeout=args.timeout,
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
