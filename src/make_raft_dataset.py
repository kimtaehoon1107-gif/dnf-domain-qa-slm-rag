import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from prompt_format import DEFAULT_RAG_INSTRUCTION


GENERIC_ANSWER_HINTS = (
    "수집된 공식 문서를 근거로 답변해야 합니다",
    "공식 문서를 근거로 답변해야",
)
DEFAULT_NO_ANSWER = "수집된 공식 문서만으로는 해당 질문에 답변할 충분한 근거가 없습니다."

def truncate(text: str, max_chars: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def is_generic_answer(answer: str) -> bool:
    return any(hint in answer for hint in GENERIC_ANSWER_HINTS)


def answer_for_row(row: dict[str, Any]) -> str:
    for key in ("gold_answer", "corrected_answer", "expected_answer", "answer", "evidence_span"):
        value = str(row.get(key) or "").strip()
        if value and not is_generic_answer(value):
            return value
    if str(row.get("answerability", "")).lower() == "false":
        return DEFAULT_NO_ANSWER
    return ""


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    values = row.get("expected_chunk_ids") or []
    if row.get("expected_chunk_id"):
        values = [row["expected_chunk_id"]]
    return [str(value) for value in values if value]


def gold_ids_for_row(row: dict[str, Any]) -> list[str]:
    chunk_ids = expected_chunk_ids(row)
    if chunk_ids:
        return chunk_ids
    for key in ("evidence_doc_ids", "expected_evidence_doc_ids", "citations"):
        value = row.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value if item]
    return []


def parent_id(doc: dict[str, Any]) -> str:
    return str(doc.get("parent_doc_id") or doc["doc_id"])


def excluded_ids(eval_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    chunks = set()
    parents = set()
    for row in eval_rows:
        chunks.update(expected_chunk_ids(row))
        for key in ("expected_doc_id", "expected_evidence_doc_ids"):
            value = row.get(key)
            if isinstance(value, list):
                parents.update(str(item) for item in value if item)
            elif value:
                parents.add(str(value))
    return chunks, parents


def row_is_trainable(row: dict[str, Any], train_splits: set[str], allow_unsplit: bool) -> bool:
    split = row.get("split")
    if split is None or split == "":
        return allow_unsplit
    return str(split) in train_splits


def make_context_doc(doc: dict[str, Any], role: str, max_chars: int, evidence_span: str = "") -> dict[str, str]:
    text = evidence_span if role == "gold" and evidence_span else doc.get("text", "")
    return {
        "doc_id": str(doc["doc_id"]),
        "role": role,
        "title": str(doc.get("title", "")),
        "text": truncate(text, max_chars),
    }


def select_balanced_rows(rows: list[dict[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    if len(rows) <= max_rows:
        selected = rows
    else:
        required_ids = {
            id(row)
            for row in rows
            if str(row.get("answerability", "")).lower() != "true"
        }
        if len(required_ids) > max_rows:
            required_ids = set(list(required_ids)[:max_rows])

        remaining_slots = max_rows - len(required_ids)
        for row in rows:
            row_id = id(row)
            if row_id in required_ids:
                continue
            if remaining_slots <= 0:
                break
            required_ids.add(row_id)
            remaining_slots -= 1
        selected = [row for row in rows if id(row) in required_ids]

    for index, row in enumerate(selected, start=1):
        row["raft_id"] = f"raft_{index:04d}"
    return selected


def sample_distractor_ids(
    rng: random.Random,
    available_doc_ids: list[str],
    docs_by_id: dict[str, dict[str, Any]],
    gold_docs: list[dict[str, Any]],
    distractors: int,
) -> list[str]:
    gold_ids = {str(doc["doc_id"]) for doc in gold_docs}
    gold_parent_ids = {parent_id(doc) for doc in gold_docs}
    distractor_ids = [
        doc_id
        for doc_id in available_doc_ids
        if doc_id not in gold_ids and parent_id(docs_by_id[doc_id]) not in gold_parent_ids
    ]
    rng.shuffle(distractor_ids)
    return distractor_ids[:distractors]


def make_raft_rows(
    docs: list[dict[str, Any]],
    qa_rows: list[dict[str, Any]],
    max_rows: int,
    distractors: int,
    seed: int,
    train_splits: set[str],
    allow_unsplit: bool,
    excluded_chunk_ids: set[str],
    excluded_parent_ids: set[str],
    gold_text: str = "span",
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    docs_by_id = {str(doc["doc_id"]): doc for doc in docs}
    available_docs = [
        doc
        for doc in docs
        if str(doc["doc_id"]) not in excluded_chunk_ids and parent_id(doc) not in excluded_parent_ids
    ]
    available_doc_ids = [str(doc["doc_id"]) for doc in available_docs]
    rows = []

    for qa in qa_rows:
        if not row_is_trainable(qa, train_splits=train_splits, allow_unsplit=allow_unsplit):
            continue
        answer = answer_for_row(qa)
        if not answer:
            continue
        answerability = str(qa.get("answerability", "true"))
        gold_ids = gold_ids_for_row(qa)
        if answerability == "false":
            distractor_ids = list(available_doc_ids)
            rng.shuffle(distractor_ids)
            # Same document count as answerable rows (1 gold + N distractors):
            # otherwise document count alone predicts the label during training
            # (v2 data had false=2 docs vs answerable=3 docs).
            context_docs = [
                make_context_doc(docs_by_id[doc_id], "distractor", max_chars=900)
                for doc_id in distractor_ids[: max(1, distractors + 1)]
            ]
            if not context_docs:
                continue
            gold_ids = []
        else:
            if not gold_ids:
                continue
            if set(gold_ids) & excluded_chunk_ids:
                continue
            if str(qa.get("expected_doc_id") or "") in excluded_parent_ids:
                continue

            gold_docs = [docs_by_id[doc_id] for doc_id in gold_ids if doc_id in docs_by_id]
            if not gold_docs:
                continue
            if any(parent_id(doc) in excluded_parent_ids for doc in gold_docs):
                continue

            distractor_ids = sample_distractor_ids(
                rng=rng,
                available_doc_ids=available_doc_ids,
                docs_by_id=docs_by_id,
                gold_docs=gold_docs,
                distractors=distractors,
            )
            # gold_text="span" puts only the answer sentence in the gold doc,
            # which makes gold systematically the shortest document — a length
            # shortcut on top of unrealistic (noise-free) evidence. "chunk"
            # uses the full chunk text like inference-time retrieval does.
            evidence_span = str(qa.get("evidence_span") or "") if gold_text == "span" else ""
            gold_max_chars = 1200 if gold_text == "span" else 900
            context_docs = [
                make_context_doc(doc, "gold", max_chars=gold_max_chars, evidence_span=evidence_span)
                for doc in gold_docs
            ]
            context_docs.extend(
                make_context_doc(docs_by_id[doc_id], "distractor", max_chars=900)
                for doc_id in distractor_ids
            )
            # Shuffle so gold is not always document 1: v2 data had gold at
            # position 1 in 279/279 rows and the model learned to cite rank 1
            # mechanically instead of selecting evidence by content.
            rng.shuffle(context_docs)
        rows.append(
            {
                "raft_id": "",
                "instruction": qa.get("instruction") or DEFAULT_RAG_INSTRUCTION,
                "question": qa["question"],
                "documents": context_docs,
                "answer": answer,
                "citations": gold_ids,
                "answerability": answerability,
                "intent": qa.get("intent", "unknown"),
                "source_split": qa.get("split", ""),
                "expected_doc_id": qa.get("expected_doc_id", ""),
                "expected_chunk_ids": expected_chunk_ids(qa),
            }
        )
    return select_balanced_rows(rows, max_rows=max_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create RAFT-style training samples from docs and QA/eval rows.")
    parser.add_argument("--docs", type=Path, default=Path("data/raw/docs.jsonl"))
    parser.add_argument("--qa", type=Path, default=Path("data/processed/qa_dataset.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/raft_train_sample.jsonl"))
    parser.add_argument("--exclude-eval-set", type=Path, nargs="+", default=[])
    parser.add_argument("--max-rows", type=int, default=50)
    parser.add_argument("--distractors", type=int, default=2)
    parser.add_argument("--gold-text", choices=("span", "chunk"), default="span")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-splits", default="train")
    parser.add_argument("--allow-unsplit", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    docs = read_jsonl(args.docs)
    qa_rows = read_jsonl(args.qa)
    eval_rows = []
    for eval_set_path in args.exclude_eval_set:
        eval_rows.extend(read_jsonl(eval_set_path))
    excluded_chunk_ids, excluded_parent_ids = excluded_ids(eval_rows)
    rows = make_raft_rows(
        docs=docs,
        qa_rows=qa_rows,
        max_rows=args.max_rows,
        distractors=args.distractors,
        seed=args.seed,
        train_splits={item.strip() for item in args.train_splits.split(",") if item.strip()},
        allow_unsplit=args.allow_unsplit,
        excluded_chunk_ids=excluded_chunk_ids,
        excluded_parent_ids=excluded_parent_ids,
        gold_text=args.gold_text,
    )
    write_jsonl(args.output, rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(rows),
                "excluded_eval_sets": [str(path) for path in args.exclude_eval_set],
                "excluded_eval_chunks": len(excluded_chunk_ids),
                "excluded_eval_parent_docs": len(excluded_parent_ids),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
