from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from prompt_format import (
    RAG_INSTRUCTIONS,
    evidence_span_visible,
    format_prompt,
    instruction_for_mode,
    select_query_window,
)
from retrieve import retrieve
from retrieval_config import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RANK_MODE,
    DEFAULT_RERANK_CANDIDATES,
    DEFAULT_RERANKER_BATCH_SIZE,
    DEFAULT_RERANKER_MAX_LENGTH,
    RANK_MODES,
)


CHUNK_ID_PATTERN = re.compile(r"[A-Za-z0-9_]+__chunk_\d+")
CONTEXT_MODES = ("chunk", "sibling_window")


def parent_doc_id(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") or {}
    return str(metadata.get("parent_doc_id") or hit.get("doc_id"))


def parse_generated_fields(text: str) -> dict[str, Any]:
    answerability_match = re.search(r"(?im)^\s*answerability\s*:\s*(true|false|partial)\b", text)
    citations_match = re.search(r"(?im)^\s*citations\s*:\s*(.*)$", text)
    answer_match = re.search(r"(?ims)^\s*answer\s*:\s*(.*)$", text)

    citations_text = citations_match.group(1).strip() if citations_match else ""
    answer_text = answer_match.group(1).strip() if answer_match else ""
    return {
        "parsed_answerability": answerability_match.group(1).lower() if answerability_match else "",
        "has_answerability_field": bool(answerability_match),
        "has_citations_field": bool(citations_match),
        "parsed_citations": CHUNK_ID_PATTERN.findall(citations_text),
        "has_answer_field": bool(answer_match),
        "parsed_answer": answer_text,
        "parsed_answer_chars": len(answer_text),
    }


def contexts_to_documents(contexts: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "doc_id": str(hit.get("doc_id")),
            "role": "retrieved",
            "title": str(hit.get("title", "")),
            "text": str(hit.get("text", "")),
        }
        for hit in contexts
    ]


def chunk_parent_id(row: dict[str, Any]) -> str:
    return str(row.get("parent_doc_id") or row.get("doc_id") or "")


def chunk_index(row: dict[str, Any]) -> int | None:
    value = row.get("chunk_index")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_sibling_lookup(
    chunks: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    by_id = {str(row["doc_id"]): row for row in chunks}
    by_parent_index = {
        (chunk_parent_id(row), index): row
        for row in chunks
        if (index := chunk_index(row)) is not None
    }
    return by_id, by_parent_index


def expand_sibling_contexts(
    contexts: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    siblings_by_parent_index: dict[tuple[str, int], dict[str, Any]],
    question: str,
    max_doc_chars: int,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    retrieved_anchor_ids = {str(hit.get("doc_id") or "") for hit in contexts}
    for hit in contexts:
        anchor_id = str(hit.get("doc_id") or "")
        anchor = chunks_by_id.get(anchor_id)
        anchor_index = chunk_index(anchor or {})
        parent_id = chunk_parent_id(anchor or {})
        if anchor is None or anchor_index is None or not parent_id:
            copied = dict(hit)
            copied["context_chunk_ids"] = [anchor_id]
            expanded.append(copied)
            continue

        context_chunks = []
        for index in range(anchor_index - 1, anchor_index + 2):
            sibling = siblings_by_parent_index.get((parent_id, index))
            if sibling is None:
                continue
            sibling_id = str(sibling.get("doc_id") or "")
            if sibling_id != anchor_id and sibling_id in retrieved_anchor_ids:
                continue
            context_chunks.append(sibling)
        blocks = []
        for sibling in context_chunks:
            sibling_index = chunk_index(sibling)
            title = str(sibling.get("title") or "")
            text = select_query_window(
                sibling.get("text", ""),
                question=question,
                max_chars=max_doc_chars,
                title=title,
            )
            if sibling_index == anchor_index:
                blocks.append(text)
            else:
                label = "previous sibling" if sibling_index < anchor_index else "next sibling"
                blocks.append(f"[{label} context | {title}]\n{text}")

        copied = dict(hit)
        copied["text"] = "\n\n".join(blocks)
        copied["context_chunk_ids"] = [str(row["doc_id"]) for row in context_chunks]
        expanded.append(copied)
    return expanded


def generation_context_ids(contexts: list[dict[str, Any]]) -> list[str]:
    ids = []
    for hit in contexts:
        values = hit.get("context_chunk_ids") or [hit.get("doc_id")]
        ids.extend(str(value) for value in values if value)
    return list(dict.fromkeys(ids))


def resolve_device(torch_module, requested_device: str) -> str:
    if requested_device != "auto":
        return requested_device
    return "cuda" if torch_module.cuda.is_available() else "cpu"


def setup_determinism(torch_module, seed: int, deterministic: bool) -> None:
    # Greedy decoding (do_sample=False) is still not bit-stable across runs on
    # GPU: nondeterministic kernels can flip borderline token choices (observed
    # as a 2-row swing on the 30-row fresh eval). warn_only keeps ops without a
    # deterministic implementation usable instead of crashing.
    torch_module.manual_seed(seed)
    if deterministic:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch_module.use_deterministic_algorithms(True, warn_only=True)
        if torch_module.cuda.is_available():
            torch_module.backends.cudnn.benchmark = False


def load_tuned_model(model_name: str, adapter_dir: Path, device: str, fp16: bool):
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        # RuntimeError (not SystemExit) so library callers such as the Gradio app
        # can catch it with `except Exception` and show a friendly message.
        raise RuntimeError(
            "Tuned-SLM smoke dependencies are missing. Install them with: pip install -r requirements-train.txt"
        ) from exc

    tokenizer_source: str | Path = (
        adapter_dir if (adapter_dir / "tokenizer_config.json").exists() else model_name
    )
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs: dict[str, Any] = {"trust_remote_code": True}
    if fp16 and device.startswith("cuda"):
        model_kwargs["torch_dtype"] = torch.float16
    base_model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
    model = PeftModel.from_pretrained(base_model, adapter_dir)
    model.to(device)
    model.eval()
    return torch, tokenizer, model


def generate_answer(
    torch_module,
    tokenizer,
    model,
    prompt: str,
    max_new_tokens: int,
) -> str:
    model_device = next(model.parameters()).device
    encoded = {
        key: value.to(model_device)
        for key, value in tokenizer(prompt, return_tensors="pt").items()
    }
    with torch_module.no_grad():
        output = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated_ids = output[0][encoded["input_ids"].shape[-1] :]
    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.eval_set)[: args.limit]
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for tuned-SLM evaluation.") from exc

    device = resolve_device(torch, args.device)
    setup_determinism(torch, seed=args.seed, deterministic=args.deterministic)
    torch_module, tokenizer, model = load_tuned_model(args.model_name, args.adapter_dir, device, args.fp16)
    chunks_by_id: dict[str, dict[str, Any]] = {}
    siblings_by_parent_index: dict[tuple[str, int], dict[str, Any]] = {}
    if args.context_mode == "sibling_window":
        chunks_by_id, siblings_by_parent_index = build_sibling_lookup(read_jsonl(args.chunks))

    details = []
    start = time.perf_counter()
    for row in rows:
        contexts = retrieve(
            row["question"],
            persist_dir=args.persist_dir,
            top_k=args.top_k,
            model_name=args.embedding_model_name,
            candidate_k=args.candidate_k,
            rank_mode=args.rank_mode,
            reranker_model=args.reranker_model,
            rerank_candidates=args.rerank_candidates,
            reranker_max_length=args.reranker_max_length,
            reranker_batch_size=args.reranker_batch_size,
        )
        generation_contexts = (
            expand_sibling_contexts(
                contexts,
                chunks_by_id=chunks_by_id,
                siblings_by_parent_index=siblings_by_parent_index,
                question=row["question"],
                max_doc_chars=args.max_doc_chars,
            )
            if args.context_mode == "sibling_window"
            else contexts
        )
        generation_max_doc_chars = (
            args.max_doc_chars * 3 + 512
            if args.context_mode == "sibling_window"
            else args.max_doc_chars
        )
        prompt = format_prompt(
            question=row["question"],
            documents=contexts_to_documents(generation_contexts),
            max_doc_chars=generation_max_doc_chars,
            instruction=instruction_for_mode(args.instruction_mode),
        )
        row_start = time.perf_counter()
        answer = generate_answer(
            torch_module=torch_module,
            tokenizer=tokenizer,
            model=model,
            prompt=prompt,
            max_new_tokens=args.max_new_tokens,
        )
        parsed_fields = parse_generated_fields(answer)
        expected_chunk_ids = [str(item) for item in row.get("expected_chunk_ids", []) if item]
        expected_parent_ids = [str(item) for item in row.get("expected_evidence_doc_ids", []) if item]
        retrieval_expected_hit = (
            any(doc_id in [hit["doc_id"] for hit in contexts] for doc_id in expected_chunk_ids)
            if expected_chunk_ids
            else any(doc_id in [parent_doc_id(hit) for hit in contexts] for doc_id in expected_parent_ids)
        )
        gold_contexts = [
            hit
            for hit in contexts
            if (
                str(hit.get("doc_id")) in expected_chunk_ids
                if expected_chunk_ids
                else parent_doc_id(hit) in expected_parent_ids
            )
        ]
        has_evidence_span = bool(str(row.get("evidence_span") or "").strip())
        gold_evidence_visible = (
            evidence_span_visible(
                question=row["question"],
                documents=gold_contexts,
                evidence_span=row.get("evidence_span", ""),
                max_doc_chars=args.max_doc_chars,
            )
            if has_evidence_span
            else None
        )
        context_ids = generation_context_ids(generation_contexts)
        generation_context_expected_hit = (
            any(doc_id in context_ids for doc_id in expected_chunk_ids)
            if expected_chunk_ids
            else any(doc_id in [parent_doc_id(hit) for hit in contexts] for doc_id in expected_parent_ids)
        )
        generation_gold_contexts = [
            hit
            for hit in generation_contexts
            if set(hit.get("context_chunk_ids") or [hit.get("doc_id")]) & set(expected_chunk_ids)
        ]
        generation_gold_evidence_visible = (
            evidence_span_visible(
                question=row["question"],
                documents=generation_gold_contexts,
                evidence_span=row.get("evidence_span", ""),
                max_doc_chars=generation_max_doc_chars,
            )
            if has_evidence_span and generation_gold_contexts
            else False
            if has_evidence_span
            else None
        )
        detail = {
            "eval_id": row.get("eval_id"),
            "question": row["question"],
            "expected_answerability": row.get("answerability"),
            "expected_evidence_doc_ids": row.get("expected_evidence_doc_ids", []),
            "expected_chunk_ids": row.get("expected_chunk_ids", []),
            "retrieved_parent_doc_ids": [parent_doc_id(hit) for hit in contexts],
            "retrieved_chunk_ids": [hit["doc_id"] for hit in contexts],
            "retrieval_expected_hit": retrieval_expected_hit,
            "gold_evidence_visible": gold_evidence_visible,
            "usable_gold_hit": bool(retrieval_expected_hit and gold_evidence_visible),
            "generation_context_chunk_ids": context_ids,
            "generation_context_expected_hit": generation_context_expected_hit,
            "generation_gold_evidence_visible": generation_gold_evidence_visible,
            "generation_usable_gold_hit": bool(
                generation_context_expected_hit and generation_gold_evidence_visible
            ),
            "generated_answer": answer,
            "latency_sec": round(time.perf_counter() - row_start, 3),
        }
        detail.update(parsed_fields)
        parsed_citation_set = set(parsed_fields["parsed_citations"])
        expected_chunk_set = set(expected_chunk_ids)
        detail["parsed_citation_hit"] = bool(expected_chunk_set & parsed_citation_set)
        detail["parsed_citation_in_retrieved"] = bool(parsed_citation_set & set(detail["retrieved_chunk_ids"]))
        details.append(detail)

    answerable_details = [row for row in details if row["expected_evidence_doc_ids"] or row["expected_chunk_ids"]]
    retrieval_hits = []
    for row in answerable_details:
        if row["expected_chunk_ids"]:
            retrieval_hits.append(any(doc_id in row["retrieved_chunk_ids"] for doc_id in row["expected_chunk_ids"]))
        else:
            retrieval_hits.append(
                any(doc_id in row["retrieved_parent_doc_ids"] for doc_id in row["expected_evidence_doc_ids"])
            )
    visibility_rows = [row for row in answerable_details if row["gold_evidence_visible"] is not None]
    visible_when_retrieved = [
        bool(row["gold_evidence_visible"])
        for row in visibility_rows
        if row["retrieval_expected_hit"]
    ]
    usable_gold_hits = [bool(row["usable_gold_hit"]) for row in visibility_rows]
    generation_context_hits = [bool(row["generation_context_expected_hit"]) for row in answerable_details]
    generation_visibility_rows = [
        row for row in answerable_details if row["generation_gold_evidence_visible"] is not None
    ]
    generation_visible_when_context_hit = [
        bool(row["generation_gold_evidence_visible"])
        for row in generation_visibility_rows
        if row["generation_context_expected_hit"]
    ]
    generation_usable_gold_hits = [
        bool(row["generation_usable_gold_hit"]) for row in generation_visibility_rows
    ]
    answerability_format_hits = [bool(row["has_answerability_field"]) for row in details]
    answerability_correct = [
        str(row.get("parsed_answerability") or "").lower()
        == str(row.get("expected_answerability") or "").lower()
        for row in details
    ]
    answerability_by_label: dict[str, dict[str, int | float]] = {}
    for row, is_correct in zip(details, answerability_correct, strict=True):
        label = str(row.get("expected_answerability") or "")
        stats = answerability_by_label.setdefault(label, {"correct": 0, "total": 0, "accuracy": 0.0})
        stats["total"] = int(stats["total"]) + 1
        if is_correct:
            stats["correct"] = int(stats["correct"]) + 1
    for stats in answerability_by_label.values():
        total = int(stats["total"])
        stats["accuracy"] = int(stats["correct"]) / total if total else 0.0
    citations_field_hits = [bool(row["has_citations_field"]) for row in details]
    answer_field_hits = [bool(row["has_answer_field"]) for row in details]
    parsed_chunk_citation_hits = [bool(row["parsed_citations"]) for row in details]
    citation_hits_when_retrieved = [
        bool(row["parsed_citation_hit"])
        for row in answerable_details
        if row["retrieval_expected_hit"]
    ]
    citation_in_retrieved_hits = [
        bool(row["parsed_citation_in_retrieved"])
        for row in details
        if row["parsed_citations"]
    ]
    avg_latency = (
        sum(row["latency_sec"] for row in details) / len(details)
        if details
        else 0.0
    )
    answer_chars = [row["parsed_answer_chars"] for row in details if row["has_answer_field"]]

    return {
        "report_schema_version": 2,
        "model_name": args.model_name,
        "adapter_dir": str(args.adapter_dir),
        "eval_set": str(args.eval_set),
        "persist_dir": str(args.persist_dir),
        "embedding_model_name": args.embedding_model_name,
        "rank_mode": args.rank_mode,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "max_doc_chars": args.max_doc_chars,
        "max_new_tokens": args.max_new_tokens,
        "instruction_mode": args.instruction_mode,
        "context_mode": args.context_mode,
        "chunks": str(args.chunks) if args.context_mode == "sibling_window" else "",
        "generation_max_doc_chars": (
            args.max_doc_chars * 3 + 512
            if args.context_mode == "sibling_window"
            else args.max_doc_chars
        ),
        "device": device,
        "seed": args.seed,
        "deterministic": args.deterministic,
        "reranker_model": args.reranker_model,
        "rerank_candidates": args.rerank_candidates,
        "reranker_max_length": args.reranker_max_length,
        "reranker_batch_size": args.reranker_batch_size,
        "rows": len(details),
        "total_runtime_sec": round(time.perf_counter() - start, 3),
        "summary": {
            "answerable_rows": len(answerable_details),
            "retrieval_expected_hit_rate": (
                sum(retrieval_hits) / len(retrieval_hits)
                if retrieval_hits
                else None
            ),
            "usable_gold_hit_rate": (
                sum(usable_gold_hits) / len(usable_gold_hits)
                if usable_gold_hits
                else None
            ),
            "generation_context_expected_hit_rate": (
                sum(generation_context_hits) / len(generation_context_hits)
                if generation_context_hits
                else None
            ),
            "generation_usable_gold_hit_rate": (
                sum(generation_usable_gold_hits) / len(generation_usable_gold_hits)
                if generation_usable_gold_hits
                else None
            ),
            "generation_evidence_visibility_when_context_hit": (
                sum(generation_visible_when_context_hit) / len(generation_visible_when_context_hit)
                if generation_visible_when_context_hit
                else None
            ),
            "evidence_visibility_when_retrieved": (
                sum(visible_when_retrieved) / len(visible_when_retrieved)
                if visible_when_retrieved
                else None
            ),
            "answerability_field_rate": (
                sum(answerability_format_hits) / len(answerability_format_hits)
                if answerability_format_hits
                else 0.0
            ),
            "answerability_accuracy": (
                sum(answerability_correct) / len(answerability_correct)
                if answerability_correct
                else 0.0
            ),
            "answerability_by_label": answerability_by_label,
            "citations_field_rate": (
                sum(citations_field_hits) / len(citations_field_hits)
                if citations_field_hits
                else 0.0
            ),
            "answer_field_rate": (
                sum(answer_field_hits) / len(answer_field_hits)
                if answer_field_hits
                else 0.0
            ),
            "parsed_chunk_citation_rate": (
                sum(parsed_chunk_citation_hits) / len(parsed_chunk_citation_hits)
                if parsed_chunk_citation_hits
                else 0.0
            ),
            "citation_hit_when_retrieval_hit": (
                sum(citation_hits_when_retrieved) / len(citation_hits_when_retrieved)
                if citation_hits_when_retrieved
                else None
            ),
            "citation_in_retrieved_rate": (
                sum(citation_in_retrieved_hits) / len(citation_in_retrieved_hits)
                if citation_in_retrieved_hits
                else None
            ),
            "avg_answer_chars": (
                round(sum(answer_chars) / len(answer_chars), 1)
                if answer_chars
                else 0.0
            ),
            "avg_generation_latency_sec": round(avg_latency, 3),
        },
        "details": details,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a minimal tuned-SLM LoRA adapter generation smoke test.")
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--adapter-dir", type=Path, default=Path("outputs/slm_lora_qwen_smoke"))
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/official_eval_set.jsonl"))
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma_official_chunks"))
    parser.add_argument("--embedding-model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    parser.add_argument("--output", type=Path, default=Path("outputs/tuned_slm_qwen_smoke_eval.json"))
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--candidate-k", type=int, default=DEFAULT_CANDIDATE_K)
    parser.add_argument("--max-doc-chars", type=int, default=300)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--instruction-mode", choices=tuple(RAG_INSTRUCTIONS), default="legacy")
    parser.add_argument("--context-mode", choices=CONTEXT_MODES, default="chunk")
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--reranker-model", default=None)
    parser.add_argument("--rerank-candidates", type=int, default=DEFAULT_RERANK_CANDIDATES)
    parser.add_argument("--reranker-max-length", type=int, default=DEFAULT_RERANKER_MAX_LENGTH)
    parser.add_argument("--reranker-batch-size", type=int, default=DEFAULT_RERANKER_BATCH_SIZE)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = run_smoke(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in report.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
