from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.minimal_claim_verifier import verify_minimal_claim_batch
from src.v3.minimal_structured_evidence import (
    annotate_prompt_with_structured_rows,
    build_structured_rows_by_coordinate,
)
from src.v3.retrieve_v3 import DEFAULT_CHUNKS, DEFAULT_DOCUMENTS
from src.v3.simple_domain_rag import GLOBAL_TEMPORAL_OVERLAY
from src.v3.simple_rag_rc1 import MODEL_TAG, _verify_model
from src.v3.typed_evidence_ref import (
    build_typed_evidence_prompt_with_candidate_units,
    generate_typed_evidence_output,
)


REPLAY_VERSION = "dnf-minimal-claim-v2-qwen-replay-v1"
DEFAULT_SEALED = Path(
    "data/v3/evaluation/"
    "simple_rag_untouched32_sealed_"
    "6b2bc67087d255af1b4cfdc9076b8dfd8d0cce2b2194e2e2210af08eb8a95198.jsonl"
)
DEFAULT_SOURCE = Path(
    "outputs/v3/untouched/"
    "simple_rag_original_vs_b134_untouched32_one_shot_20260728.jsonl"
)
EVALUATION_NOTE = (
    "이 화면은 Minimal Claim v2의 측정 조건을 재현한다. 저장된 후보와 "
    "사람 검수 fixed requirements를 사용하며, Qwen3 8B 생성과 "
    "Minimal v2 검증은 클릭할 때마다 실제로 실행한다. 자유 질문용 "
    "planner·실시간 검색 성능은 이 점수에 포함되지 않는다."
)


def _render_batch(
    verified: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = {
        row["requirement_id"]: row
        for row in requirements
    }
    rows = []
    for row in verified["requirements"]:
        requirement = metadata[row["requirement_id"]]
        rows.append(
            {
                **row,
                "subject": requirement["subject"],
                "relation": requirement["relation"],
            }
        )
    supported = [
        row for row in rows if row["status"] == "supported_exact"
    ]
    if not supported:
        response_mode = "abstain"
    elif len(supported) == len(rows):
        response_mode = "full_answer"
    else:
        response_mode = "partial_answer"
    return {
        "response_mode": response_mode,
        "requirements": rows,
        "rendered_answer": "\n".join(
            f"- {row['relation']}: {row['answer']} "
            + " ".join(
                f"[{chunk_id}]"
                for chunk_id in dict.fromkeys(
                    citation["chunk_id"]
                    for citation in row["citations"]
                )
            )
            for row in supported
        ),
        "verification": {
            **verified.get("verification", {}),
            "all_exposed_citations_verified": all(
                row["citations"] for row in supported
            ),
        },
    }


class MinimalClaimV2Replay:
    """Run the measured Minimal Claim v2 generator on its frozen inputs."""

    def __init__(
        self,
        *,
        root: Path,
        model: str = MODEL_TAG,
        timeout: float = 180.0,
    ) -> None:
        self.root = root.resolve()
        self.model = model
        self.timeout = timeout
        _verify_model(model)

        self.sealed_rows = read_jsonl(self.root / DEFAULT_SEALED)
        source_rows = read_jsonl(self.root / DEFAULT_SOURCE)
        if len(self.sealed_rows) != 32 or len(source_rows) != 32:
            raise RuntimeError("Minimal Claim v2 replay requires 32 rows")
        self.source_by_id = {
            row["candidate_id"]: row
            for row in source_rows
        }
        if {
            row["candidate_id"] for row in self.sealed_rows
        } != set(self.source_by_id):
            raise RuntimeError("sealed and stored candidate IDs differ")

        chunks = read_jsonl(self.root / DEFAULT_CHUNKS)
        documents = read_jsonl(self.root / DEFAULT_DOCUMENTS)
        temporal = read_jsonl(self.root / GLOBAL_TEMPORAL_OVERLAY)
        self.chunks_by_id = {
            row["chunk_id"]: row
            for row in chunks
        }
        self.documents_by_id = {
            row["document_id"]: row
            for row in documents
        }
        self.temporal_by_document = {
            row["document_id"]: row
            for row in temporal
        }
        self.sealed_by_question = {
            row["question_text"]: row
            for row in self.sealed_rows
        }
        if len(self.sealed_by_question) != 32:
            raise RuntimeError("replay questions must be unique")

    @property
    def questions(self) -> list[str]:
        return [
            row["question_text"]
            for row in sorted(
                self.sealed_rows,
                key=lambda item: item["slot_ordinal"],
            )
        ]

    def answer(self, question: str) -> dict[str, Any]:
        sealed = self.sealed_by_question.get(str(question or "").strip())
        if sealed is None:
            raise RuntimeError(
                "Minimal Claim v2 replay only accepts one of the 32 "
                "human-reviewed questions"
            )
        started = time.perf_counter()
        source = self.source_by_id[sealed["candidate_id"]]
        candidate_ids = list(source["candidate_chunk_ids"])
        prompt, visible_units, _ = (
            build_typed_evidence_prompt_with_candidate_units(
                question=sealed["question_text"],
                requirements=sealed["requirements"],
                question_time_scope=sealed["time_scope"],
                as_of=sealed["as_of"],
                candidate_chunk_ids=candidate_ids,
                chunks_by_id=self.chunks_by_id,
                documents_by_id=self.documents_by_id,
                temporal_by_document=self.temporal_by_document,
                selector_mode="baseline",
            )
        )
        structured_rows = build_structured_rows_by_coordinate(
            candidate_ids,
            chunks_by_id=self.chunks_by_id,
        )
        prompt = annotate_prompt_with_structured_rows(
            prompt,
            evidence_units_by_ref=visible_units,
            structured_rows_by_coordinate=structured_rows,
        )
        generation = generate_typed_evidence_output(
            prompt=prompt,
            model=self.model,
            timeout_seconds=self.timeout,
        )
        protocol_error = generation.get("protocol_error")
        if protocol_error:
            raise RuntimeError(protocol_error)
        verified = verify_minimal_claim_batch(
            generation["output"],
            requirements=sealed["requirements"],
            question=sealed["question_text"],
            as_of=sealed["as_of"],
            evidence_units_by_ref=visible_units,
            chunks_by_id=self.chunks_by_id,
            structured_rows_by_coordinate=structured_rows,
            profile="v2",
        )
        final = _render_batch(verified, sealed["requirements"])
        candidates = []
        for index, chunk_id in enumerate(candidate_ids, 1):
            chunk = self.chunks_by_id[chunk_id]
            document = self.documents_by_id[chunk["parent_document_id"]]
            candidates.append(
                {
                    "candidate_ref": str(index),
                    "chunk_id": chunk_id,
                    "parent_document_id": document["document_id"],
                    "source_id": document["source_id"],
                    "title": document.get("title"),
                    "published_at": document.get("published_at"),
                    "status": document.get("status"),
                }
            )
        return {
            "replay_version": REPLAY_VERSION,
            "evaluation_note": EVALUATION_NOTE,
            "slot_ordinal": sealed["slot_ordinal"],
            "question": sealed["question_text"],
            **final,
            "fixed_requirements": sealed["requirements"],
            "candidate_mode": "stored_subject_source_aware_candidates",
            "candidate_count": len(candidate_ids),
            "candidates": candidates,
            "generation": generation,
            "latency": {
                "generation_ms": float(
                    generation.get("latency_ms") or 0
                ),
                "total_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
            },
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
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    runtime = MinimalClaimV2Replay(
        root=args.root,
        model=args.model,
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
