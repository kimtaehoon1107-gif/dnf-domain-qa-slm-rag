from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from generate_answer import build_grounded_answer
from io_utils import read_jsonl
from retrieve import retrieve
from retrieval_config import DEFAULT_EMBEDDING_MODEL, DEFAULT_RANK_MODE, RANK_MODES


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?\n。]+")
NO_ANSWER_HINTS = [
    "충분한 근거가 없습니다",
    "확인할 수 없습니다",
    "공식 문서만으로는",
    "수집된 문서만으로는",
]
BOILERPLATE_PREFIXES = [
    "확인 가능한 근거는 다음과 같습니다.",
    "문서에서 일부 확인 가능한 내용은 다음과 같습니다.",
]
GENERIC_EXPECTED_ANSWER_HINTS = [
    "수집된 공식 문서를 근거로 답변해야 합니다",
    "공식 문서를 근거로 답변해야",
]
STOPWORDS = {
    "그리고",
    "그러나",
    "따라서",
    "다음",
    "문서",
    "근거",
    "확인",
    "가능",
    "내용",
    "질문",
    "답변",
    "있습니다",
    "합니다",
    "됩니다",
}


def tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(text)
        if len(token) >= 2 and token.lower() not in STOPWORDS
    }


def expected_answerability(row: dict[str, Any]) -> str:
    if row.get("answerability"):
        return str(row["answerability"])
    return "true" if row.get("expected_evidence_doc_ids") or row.get("expected_chunk_ids") else "false"


def parent_doc_id(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") or {}
    return str(metadata.get("parent_doc_id") or hit.get("doc_id"))


def normalize_citations(answer_evidence: list[str], contexts: list[dict[str, Any]], match_scope: str) -> list[str]:
    if match_scope == "chunk":
        return [str(doc_id) for doc_id in answer_evidence]
    chunk_to_parent = {str(hit.get("doc_id")): parent_doc_id(hit) for hit in contexts}
    return [chunk_to_parent.get(str(doc_id), str(doc_id)) for doc_id in answer_evidence]


def strip_answer_boilerplate(answer: str) -> str:
    stripped = answer.strip()
    for prefix in BOILERPLATE_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def split_atomic_facts(answer: str) -> list[str]:
    facts = []
    for sentence in SENTENCE_SPLIT_PATTERN.split(strip_answer_boilerplate(answer)):
        sentence = sentence.strip(" -:;\t")
        if not sentence:
            continue
        parts = [part.strip() for part in re.split(r",|/| 및 | 그리고 | 또한 ", sentence) if part.strip()]
        facts.extend(part for part in parts if len(tokens(part)) >= 2)
    return facts


def support_score(fact: str, evidence_text: str) -> float:
    fact_tokens = tokens(fact)
    if not fact_tokens:
        return 0.0
    evidence_tokens = tokens(evidence_text)
    token_overlap = len(fact_tokens & evidence_tokens) / len(fact_tokens)

    fact_numbers = {token for token in fact_tokens if any(ch.isdigit() for ch in token)}
    if fact_numbers:
        number_overlap = len(fact_numbers & evidence_tokens) / len(fact_numbers)
        return (token_overlap + number_overlap) / 2
    return token_overlap


def context_relevance(question: str, contexts: list[dict[str, Any]]) -> float:
    question_tokens = tokens(question)
    if not question_tokens or not contexts:
        return 0.0
    scores = []
    for hit in contexts:
        context_tokens = tokens(f"{hit.get('title', '')} {hit.get('text', '')}")
        scores.append(len(question_tokens & context_tokens) / len(question_tokens))
    return max(scores) if scores else 0.0


def answer_relevance(answer: str, expected_answer: str, expected: str) -> float | None:
    if expected == "false":
        return 1.0 if any(hint in answer for hint in NO_ANSWER_HINTS) else 0.0
    if any(hint in expected_answer for hint in GENERIC_EXPECTED_ANSWER_HINTS):
        return None
    expected_tokens = tokens(expected_answer)
    if not expected_tokens:
        return 0.0
    answer_tokens = tokens(answer)
    return len(expected_tokens & answer_tokens) / len(expected_tokens)


def citation_metrics(expected_ids: list[str], citations: list[str], expected: str) -> dict[str, float | bool]:
    expected_set = set(expected_ids)
    citation_set = set(citations)
    if expected == "false":
        return {
            "citation_precision": 1.0 if not citations else 0.0,
            "citation_recall": 1.0,
            "citation_hit": not citations,
        }
    if not expected_set:
        return {"citation_precision": 0.0, "citation_recall": 0.0, "citation_hit": False}
    if not citation_set:
        return {"citation_precision": 0.0, "citation_recall": 0.0, "citation_hit": False}

    intersection = expected_set & citation_set
    return {
        "citation_precision": len(intersection) / len(citation_set),
        "citation_recall": len(intersection) / len(expected_set),
        "citation_hit": bool(intersection),
    }


def factscore_style(answer: str, evidence_text: str, expected: str) -> dict[str, Any]:
    if expected == "false":
        no_answer = any(hint in answer for hint in NO_ANSWER_HINTS)
        return {
            "atomic_fact_count": 0,
            "supported_fact_count": 0,
            "atomic_fact_support_rate": 1.0 if no_answer else 0.0,
            "unsupported_facts": [] if no_answer else [answer],
        }

    facts = split_atomic_facts(answer)
    if not facts:
        return {
            "atomic_fact_count": 0,
            "supported_fact_count": 0,
            "atomic_fact_support_rate": 0.0,
            "unsupported_facts": [],
        }

    supported = []
    unsupported = []
    for fact in facts:
        if support_score(fact, evidence_text) >= 0.55:
            supported.append(fact)
        else:
            unsupported.append(fact)

    return {
        "atomic_fact_count": len(facts),
        "supported_fact_count": len(supported),
        "atomic_fact_support_rate": len(supported) / len(facts),
        "unsupported_facts": unsupported,
    }


def expected_ids_and_scope(row: dict[str, Any]) -> tuple[list[str], str]:
    chunk_ids = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        chunk_ids = [str(row["expected_chunk_id"])]
    if chunk_ids:
        return chunk_ids, "chunk"
    return [str(item) for item in row.get("expected_evidence_doc_ids", []) if item], "parent_doc"


def evaluate_row(
    row: dict[str, Any],
    persist_dir: Path,
    top_k: int,
    candidate_k: int | None,
    model_name: str,
    rank_mode: str,
) -> dict[str, Any]:
    contexts = retrieve(
        row["question"],
        persist_dir=persist_dir,
        top_k=top_k,
        candidate_k=candidate_k,
        model_name=model_name,
        rank_mode=rank_mode,
    )
    generated = build_grounded_answer(row["question"], contexts).to_dict()
    expected = expected_answerability(row)
    expected_ids, match_scope = expected_ids_and_scope(row)
    citations = normalize_citations(generated.get("evidence", []), contexts, match_scope)
    evidence_text = "\n\n".join(str(hit.get("text", "")) for hit in contexts)

    citation = citation_metrics(expected_ids, citations, expected)
    factscore = factscore_style(generated["answer"], evidence_text, expected)
    detail = {
        "eval_id": row.get("eval_id") or row.get("qa_id"),
        "question": row["question"],
        "expected_answerability": expected,
        "predicted_answerability": generated["answerability"],
        "answerability_correct": generated["answerability"] == expected,
        "expected_evidence_doc_ids": row.get("expected_evidence_doc_ids", []),
        "expected_chunk_ids": row.get("expected_chunk_ids", []),
        "match_scope": match_scope,
        "model_name": model_name,
        "rank_mode": rank_mode,
        "citations": citations,
        "context_relevance": context_relevance(row["question"], contexts),
        "answer_relevance": answer_relevance(generated["answer"], row.get("expected_answer", ""), expected),
        "faithfulness_style": factscore["atomic_fact_support_rate"],
        "answer": generated["answer"],
        "unsupported_facts": factscore["unsupported_facts"],
        "retrieved_parent_doc_ids": [parent_doc_id(hit) for hit in contexts],
        "retrieved_chunk_ids": [hit["doc_id"] for hit in contexts],
    }
    detail.update(citation)
    detail.update({key: value for key, value in factscore.items() if key != "unsupported_facts"})
    return detail


def summarize(details: list[dict[str, Any]]) -> dict[str, Any]:
    if not details:
        raise ValueError("No evaluation rows were produced.")

    def avg(key: str) -> float | None:
        values = [row[key] for row in details if row.get(key) is not None]
        if not values:
            return None
        return mean(float(value) for value in values)

    # Citation metrics over all rows count unanswerable rows as vacuously perfect
    # (recall=1.0), which inflates the aggregate. Report answerable-only versions
    # so the real retrieval-grounded citation quality is visible.
    answerable = [row for row in details if row.get("expected_answerability") != "false"]

    def avg_answerable(key: str) -> float | None:
        values = [float(row[key]) for row in answerable if row.get(key) is not None]
        return mean(values) if values else None

    # faithfulness_style scores answer facts against *whatever was retrieved*.
    # For an extractive generator the answer is copied from that same retrieved
    # text, so the score is ~1.0 even when the wrong document was retrieved
    # (circular). Condition on citation_hit so the score only counts rows where
    # the cited evidence was actually correct.
    citation_hit_rows = [row for row in answerable if row.get("citation_hit")]
    faithfulness_when_citation_hit = (
        mean(float(row["faithfulness_style"]) for row in citation_hit_rows if row.get("faithfulness_style") is not None)
        if citation_hit_rows
        else None
    )

    return {
        "rows": len(details),
        "answerability_accuracy": avg("answerability_correct"),
        "citation_hit_rate": avg("citation_hit"),
        "citation_precision": avg("citation_precision"),
        "citation_recall": avg("citation_recall"),
        "answerable_rows": len(answerable),
        "citation_hit_rate_answerable": avg_answerable("citation_hit"),
        "citation_precision_answerable": avg_answerable("citation_precision"),
        "citation_recall_answerable": avg_answerable("citation_recall"),
        "context_relevance": avg("context_relevance"),
        "answer_relevance": avg("answer_relevance"),
        "answer_relevance_rows": sum(1 for row in details if row.get("answer_relevance") is not None),
        "faithfulness_style": avg("faithfulness_style"),
        "faithfulness_when_citation_hit": faithfulness_when_citation_hit,
        "faithfulness_citation_hit_rows": len(citation_hit_rows),
        "atomic_fact_support_rate": avg("atomic_fact_support_rate"),
        "unsupported_fact_rows": sum(1 for row in details if row["unsupported_facts"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run lightweight RAGAS-style and FActScore-style answer evaluation."
    )
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/eval_set.jsonl"))
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("outputs/answer_eval_report.json"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.eval_set)
    if args.limit is not None:
        rows = rows[: args.limit]

    details = [
        evaluate_row(
            row,
            persist_dir=args.persist_dir,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            model_name=args.model_name,
            rank_mode=args.rank_mode,
        )
        for row in rows
    ]
    report = {
        "summary": summarize(details),
        "config": {
            "eval_set": str(args.eval_set),
            "persist_dir": str(args.persist_dir),
            "model_name": args.model_name,
            "rank_mode": args.rank_mode,
            "top_k": args.top_k,
            "candidate_k": args.candidate_k,
        },
        "details": details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
