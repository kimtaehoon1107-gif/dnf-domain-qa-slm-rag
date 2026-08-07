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

from src.io_utils import read_jsonl, write_jsonl
from src.v3.evaluate_grounded_llm_replay import score_verified_output
from src.v3.generate_grounded_llm_answer import (
    build_grounded_prompt,
    generate_grounded_output,
    safe_abstention,
    verify_and_sanitize_output,
)
from src.v3.simple_domain_rag import (
    DEFAULT_AS_OF,
    SimpleDomainRAG,
    enforce_factual_token_support,
)
from src.v3.subject_anchored_retrieval import (
    candidate_supports_subject,
    enforce_subject_citation_support,
)


EVALUATOR_VERSION = "simple-subject-anchored-generation-v1"
DEFAULT_EVAL_SET = Path(
    "data/v3/evaluation/requirement_surface_query_canary_reviewed_"
    "533a4b031369cdd63872cd4f52a33d9128fbcf6cf42a344e2693b4959a76c561.jsonl"
)
DEFAULT_RETRIEVAL_AB = Path(
    "outputs/v3/simple_subject_anchored_retrieval_ab_cases.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/simple_subject_anchored_generation_slots21_24.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/simple_subject_anchored_generation_slots21_24_summary.json"
)


def _generate_case(
    reviewed: dict[str, Any],
    retrieval_ab: dict[str, Any],
    *,
    rag: SimpleDomainRAG,
    candidate_depth: int,
    subject_only: bool,
) -> dict[str, Any]:
    assert rag._artifacts is not None
    chunks = rag._artifacts.chunks_by_id
    documents = rag._artifacts.documents_by_id
    subject = retrieval_ab["plan"]["subject"]
    candidate_ids = list(retrieval_ab["arm_candidate_ids"])
    if subject_only:
        candidate_ids = [
            chunk_id
            for chunk_id in candidate_ids
            if candidate_supports_subject(
                subject,
                chunk=chunks[chunk_id],
                document=documents[
                    chunks[chunk_id]["parent_document_id"]
                ],
            )
        ]
    candidate_ids = candidate_ids[:candidate_depth]
    if not candidate_ids:
        raise RuntimeError("subject filtering removed every candidate")
    started = time.perf_counter()
    try:
        prompt = build_grounded_prompt(
            question=reviewed["question_text"],
            as_of=DEFAULT_AS_OF,
            candidate_chunk_ids=candidate_ids,
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=rag.temporal_by_document,
        )
        generated = generate_grounded_output(
            prompt=prompt,
            model=rag.model,
            timeout_seconds=rag.timeout,
        )
        verified = verify_and_sanitize_output(
            generated["output"],
            candidate_chunk_ids=candidate_ids,
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=rag.temporal_by_document,
        )
        subject_checked = enforce_subject_citation_support(
            verified,
            subject=subject,
            chunks_by_id=chunks,
            documents_by_id=documents,
        )
        checked = enforce_factual_token_support(subject_checked)
        result = {
            "question": reviewed["question_text"],
            **checked,
            "candidates": [
                {
                    "candidate_ref": str(index),
                    "chunk_id": chunk_id,
                    "parent_document_id": chunks[chunk_id][
                        "parent_document_id"
                    ],
                    "source_id": documents[
                        chunks[chunk_id]["parent_document_id"]
                    ]["source_id"],
                }
                for index, chunk_id in enumerate(candidate_ids, 1)
            ],
            "generation": {
                "model": rag.model,
                "provider": generated["provider"],
                "usage": generated["usage"],
                "latency_ms": generated["latency_ms"],
            },
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        }
    except Exception as exc:
        result = {
            "question": reviewed["question_text"],
            **safe_abstention(exc),
            "candidates": [
                {
                    "candidate_ref": str(index),
                    "chunk_id": chunk_id,
                    "parent_document_id": chunks[chunk_id][
                        "parent_document_id"
                    ],
                    "source_id": documents[
                        chunks[chunk_id]["parent_document_id"]
                    ]["source_id"],
                }
                for index, chunk_id in enumerate(candidate_ids, 1)
            ],
            "generation": {"model": rag.model, "error": str(exc)},
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        }
    score = score_verified_output(
        reviewed,
        candidate_chunk_ids=candidate_ids,
        verified=result,
        chunks_by_id=chunks,
    )
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "candidate_id": reviewed["candidate_id"],
        "slot_ordinal": reviewed["slot_ordinal"],
        "question_text": reviewed["question_text"],
        "subject": subject,
        "score": score,
        "result": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--retrieval-ab", type=Path, default=DEFAULT_RETRIEVAL_AB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--slots", type=int, nargs="+", default=[21, 22, 23, 24])
    parser.add_argument("--candidate-depth", type=int, default=5)
    parser.add_argument("--subject-only", action="store_true")
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    selected_slots = set(args.slots)
    reviewed_by_id = {
        row["candidate_id"]: row
        for row in read_jsonl(resolved(args.eval_set))
        if row["slot_ordinal"] in selected_slots
    }
    retrieval_rows = [
        row
        for row in read_jsonl(resolved(args.retrieval_ab))
        if row["slot_ordinal"] in selected_slots
    ]
    if {row["slot_ordinal"] for row in retrieval_rows} != selected_slots:
        raise RuntimeError("retrieval A/B does not contain every requested slot")
    if any(row["plan"] is None for row in retrieval_rows):
        raise RuntimeError("requested generation case has no subject plan")

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    rag = SimpleDomainRAG(
        root=root,
        model=args.model,
        device=args.device,
        timeout=args.timeout,
    )
    rag._initialize()

    output_path = resolved(args.output)
    completed = read_jsonl(output_path) if output_path.exists() else []
    completed_by_id = {row["candidate_id"]: row for row in completed}
    output_rows = []
    for index, retrieval_ab in enumerate(retrieval_rows, 1):
        candidate_id = retrieval_ab["candidate_id"]
        if candidate_id in completed_by_id:
            case = completed_by_id[candidate_id]
            status = "resumed"
        else:
            case = _generate_case(
                reviewed_by_id[candidate_id],
                retrieval_ab,
                rag=rag,
                candidate_depth=args.candidate_depth,
                subject_only=args.subject_only,
            )
            completed_by_id[candidate_id] = case
            status = "evaluated"
        output_rows.append(case)
        write_jsonl(output_path, output_rows)
        print(
            json.dumps(
                {
                    "progress": f"{index}/{len(retrieval_rows)}",
                    "status": status,
                    "slot": case["slot_ordinal"],
                    "response_mode": case["result"]["response_mode"],
                    "candidate_covered": case["score"][
                        "candidate_all_groups_covered"
                    ],
                    "literal": case["score"]["all_evidence_spans_hit"],
                    "false_full": case["score"]["false_full"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = {
        "evaluator_version": EVALUATOR_VERSION,
        "case_count": len(output_rows),
        "candidate_depth": args.candidate_depth,
        "subject_only": args.subject_only,
        "model": args.model,
        "candidate_covered": sum(
            row["score"]["candidate_all_groups_covered"] for row in output_rows
        ),
        "literal": sum(
            row["score"]["all_evidence_spans_hit"] for row in output_rows
        ),
        "false_full": sum(row["score"]["false_full"] for row in output_rows),
        "response_modes": {
            mode: sum(
                row["result"]["response_mode"] == mode for row in output_rows
            )
            for mode in ("full_answer", "partial_answer", "abstain")
        },
        "subject_gate_failures": sum(
            "citation_subject_mismatch"
            in audit.get("failure_reasons", [])
            for row in output_rows
            for audit in row["result"].get("verification", {}).get(
                "requirements",
                [],
            )
        ),
    }
    summary_path = resolved(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
