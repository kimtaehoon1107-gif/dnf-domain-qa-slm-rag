from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
GENERIC_TERMS = (
    "핵심",
    "내용",
    "정보",
    "공지",
    "관련",
    "이용 조건",
    "변경/수정",
    "주의사항",
)


def tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {token.lower() for token in TOKEN_PATTERN.findall(text)}


def token_overlap_ratio(left: str | None, right: str | None) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def snippet(text: str | None, max_chars: int = 180) -> str:
    if not text:
        return ""
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3] + "..."


def parent_doc_id(chunk_id: str, chunk: dict[str, Any] | None = None) -> str:
    if chunk:
        return str(chunk.get("parent_doc_id") or chunk_id.split("__chunk_", 1)[0])
    return chunk_id.split("__chunk_", 1)[0]


def load_candidate_details(path: Path) -> list[dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    details = report.get("details")
    if not isinstance(details, list):
        raise ValueError(f"{path} does not contain a details list.")
    return details


def infer_doc_type(doc_id: str, chunk: dict[str, Any] | None = None) -> str:
    if chunk and chunk.get("doc_type"):
        return str(chunk["doc_type"])
    if doc_id.startswith("official_guide_"):
        return "guide"
    if doc_id.startswith("official_event_"):
        return "event"
    if doc_id.startswith("official_update_"):
        return "update"
    if doc_id.startswith("official_notice_"):
        return "notice"
    return "unknown"


def classify_row(
    eval_row: dict[str, Any],
    detail: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[str], str]:
    expected_ids = [str(item) for item in detail.get("expected_ids", []) if item]
    retrieved_chunk_ids = [str(item) for item in detail.get("retrieved_chunk_ids", []) if item]
    retrieved_parent_ids = [str(item) for item in detail.get("retrieved_parent_ids", []) if item]
    expected_parents = {
        parent_doc_id(chunk_id, chunks_by_id.get(chunk_id)) for chunk_id in expected_ids
    }

    categories: list[str] = []
    if any(chunk_id not in chunks_by_id for chunk_id in expected_ids):
        categories.append("expected_chunk_not_indexed")

    sibling_parent_retrieved = any(parent_id in retrieved_parent_ids for parent_id in expected_parents)
    if sibling_parent_retrieved:
        categories.append("sibling_parent_retrieved")

    question = str(eval_row.get("question") or detail.get("question") or "")
    evidence_span = str(eval_row.get("evidence_span") or eval_row.get("gold_answer") or "")
    expected_chunks = [chunks_by_id.get(chunk_id) for chunk_id in expected_ids if chunks_by_id.get(chunk_id)]
    expected_title = " ".join(str(chunk.get("title") or "") for chunk in expected_chunks)
    question_span_overlap = token_overlap_ratio(question, evidence_span)
    question_title_overlap = token_overlap_ratio(question, expected_title)

    has_generic_term = any(term in question for term in GENERIC_TERMS)
    if has_generic_term and question_span_overlap < 0.25:
        categories.append("generic_or_underspecified_question")
    if question_span_overlap < 0.15 and not sibling_parent_retrieved:
        categories.append("low_question_evidence_overlap")

    expected_doc_types = {
        infer_doc_type(chunk_id, chunks_by_id.get(chunk_id)) for chunk_id in expected_ids
    }
    top_doc_types = [
        infer_doc_type(chunk_id, chunks_by_id.get(chunk_id)) for chunk_id in retrieved_chunk_ids[:5]
    ]
    if expected_doc_types and not (expected_doc_types & set(top_doc_types)):
        categories.append("top5_doc_type_mismatch")

    if "guide" in expected_doc_types and top_doc_types.count("guide") >= 3:
        categories.append("guide_intra_corpus_confusion")

    date_like_question = bool(re.search(r"\d|언제|기간|몇\s*시|몇시|날짜", question))
    if date_like_question and "generic_or_underspecified_question" not in categories:
        categories.append("date_or_period_query")

    if not categories:
        categories.append("retriever_candidate_generation_miss")

    if "expected_chunk_not_indexed" in categories:
        action = "Fix index/eval references before tuning retrieval."
    elif "sibling_parent_retrieved" in categories:
        action = "Inspect chunk boundary or consider parent/window context while keeping chunk citation."
    elif "generic_or_underspecified_question" in categories:
        action = "Rewrite eval question from the evidence fact before retrieval tuning."
    elif "top5_doc_type_mismatch" in categories:
        action = "Inspect query routing/doc-type cues or retrieval ranking."
    else:
        action = "Treat as candidate-generation miss; inspect lexical/dense query behavior."

    return categories, action


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    details = load_candidate_details(args.candidate_report)
    eval_rows = {str(row.get("eval_id")): row for row in read_jsonl(args.eval_set)}
    chunks_by_id = {str(row.get("doc_id")): row for row in read_jsonl(args.chunks)}

    missing_details = [detail for detail in details if detail.get("gold_rank") is None]
    rows: list[dict[str, Any]] = []
    category_counter: Counter[str] = Counter()
    action_counter: Counter[str] = Counter()

    for detail in missing_details:
        eval_id = str(detail.get("eval_id"))
        eval_row = eval_rows.get(eval_id, {})
        categories, action = classify_row(eval_row, detail, chunks_by_id)
        category_counter.update(categories)
        action_counter[action] += 1

        expected_ids = [str(item) for item in detail.get("expected_ids", []) if item]
        expected_chunks = [chunks_by_id.get(chunk_id) for chunk_id in expected_ids if chunks_by_id.get(chunk_id)]
        retrieved_ids = [str(item) for item in detail.get("retrieved_chunk_ids", []) if item]
        retrieved_chunks = [chunks_by_id.get(chunk_id, {}) for chunk_id in retrieved_ids]
        expected_parents = [
            parent_doc_id(chunk_id, chunks_by_id.get(chunk_id)) for chunk_id in expected_ids
        ]
        retrieved_parent_ids = [str(item) for item in detail.get("retrieved_parent_ids", []) if item]
        sibling_ids = [
            chunk_id
            for chunk_id, parent_id in zip(retrieved_ids, retrieved_parent_ids)
            if parent_id in set(expected_parents)
        ]

        question = str(eval_row.get("question") or detail.get("question") or "")
        evidence_span = str(eval_row.get("evidence_span") or eval_row.get("gold_answer") or "")
        expected_title = " | ".join(
            sorted({str(chunk.get("title") or "") for chunk in expected_chunks if chunk.get("title")})
        )
        expected_doc_types = sorted(
            {infer_doc_type(chunk_id, chunks_by_id.get(chunk_id)) for chunk_id in expected_ids}
        )

        row = {
            "eval_id": eval_id,
            "question": question,
            "answerability": eval_row.get("answerability") or detail.get("answerability"),
            "intent": eval_row.get("intent"),
            "source_eval_type": eval_row.get("source_eval_type"),
            "expected_ids": expected_ids,
            "expected_parent_ids": expected_parents,
            "expected_title": expected_title,
            "expected_doc_types": expected_doc_types,
            "expected_chunk_exists": all(chunk_id in chunks_by_id for chunk_id in expected_ids),
            "parent_in_top20": any(parent_id in retrieved_parent_ids for parent_id in expected_parents),
            "sibling_ids_in_top20": sibling_ids,
            "question_evidence_overlap": round(token_overlap_ratio(question, evidence_span), 4),
            "question_title_overlap": round(token_overlap_ratio(question, expected_title), 4),
            "categories": categories,
            "recommended_action": action,
            "evidence_span": snippet(evidence_span),
            "gold_answer": snippet(str(eval_row.get("gold_answer") or "")),
            "top1_id": retrieved_ids[0] if len(retrieved_ids) > 0 else "",
            "top1_title": str(retrieved_chunks[0].get("title") or "") if len(retrieved_chunks) > 0 else "",
            "top1_doc_type": infer_doc_type(retrieved_ids[0], retrieved_chunks[0]) if len(retrieved_ids) > 0 else "",
            "top2_id": retrieved_ids[1] if len(retrieved_ids) > 1 else "",
            "top2_title": str(retrieved_chunks[1].get("title") or "") if len(retrieved_chunks) > 1 else "",
            "top2_doc_type": infer_doc_type(retrieved_ids[1], retrieved_chunks[1]) if len(retrieved_ids) > 1 else "",
            "top3_id": retrieved_ids[2] if len(retrieved_ids) > 2 else "",
            "top3_title": str(retrieved_chunks[2].get("title") or "") if len(retrieved_chunks) > 2 else "",
            "top3_doc_type": infer_doc_type(retrieved_ids[2], retrieved_chunks[2]) if len(retrieved_ids) > 2 else "",
            "top20_ids": retrieved_ids,
        }
        rows.append(row)

    return {
        "candidate_report": str(args.candidate_report),
        "eval_set": str(args.eval_set),
        "chunks": str(args.chunks),
        "summary": {
            "answerable_rows": len(details),
            "missing_rows": len(missing_details),
            "missing_rate": len(missing_details) / len(details) if details else 0.0,
            "category_counts": dict(category_counter.most_common()),
            "recommended_action_counts": dict(action_counter.most_common()),
        },
        "rows": rows,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "eval_id",
        "question",
        "answerability",
        "intent",
        "source_eval_type",
        "expected_ids",
        "expected_parent_ids",
        "expected_title",
        "expected_doc_types",
        "expected_chunk_exists",
        "parent_in_top20",
        "sibling_ids_in_top20",
        "question_evidence_overlap",
        "question_title_overlap",
        "categories",
        "recommended_action",
        "evidence_span",
        "gold_answer",
        "top1_id",
        "top1_title",
        "top1_doc_type",
        "top2_id",
        "top2_title",
        "top2_doc_type",
        "top3_id",
        "top3_title",
        "top3_doc_type",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat_row = dict(row)
            for key, value in flat_row.items():
                if isinstance(value, (list, dict)):
                    flat_row[key] = json.dumps(value, ensure_ascii=False)
            writer.writerow({key: flat_row.get(key, "") for key in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze domain eval rows missing gold chunks in top-20 retrieval.")
    parser.add_argument("--candidate-report", type=Path, default=Path("outputs/domain_retriever_candidate_report.json"))
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/domain_eval_set_expanded.jsonl"))
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument("--json-output", type=Path, default=Path("outputs/domain_retriever_missing_analysis.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("outputs/domain_retriever_missing_review.csv"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = analyze(args)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(args.csv_output, report["rows"])
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
