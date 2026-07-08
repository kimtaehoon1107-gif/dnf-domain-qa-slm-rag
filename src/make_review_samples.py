from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from io_utils import read_jsonl


COMMA_ANCHOR_PATTERN = re.compile(r"^[^\s,]{1,12},")
GENERIC_QUESTION_HINTS = (
    "관련해서 공식 문서",
    "관련 기간이나 일정",
    "기준으로 공식 문서만",
)
SCAM_HINTS = ("사기", "개인정보", "인증번호", "외부 메신저", "현금거래")
FALSE_ANSWER_HINT = "충분한 근거가 없습니다"


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def row_id(row: dict[str, Any]) -> str:
    for key in ("eval_id", "qa_id", "raft_id", "id"):
        if row.get(key):
            return str(row[key])
    return "<missing-id>"


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    values = row.get("expected_chunk_ids") or []
    if row.get("expected_chunk_id"):
        values = [row["expected_chunk_id"]]
    return [str(value) for value in values if value]


def first_gold_document(row: dict[str, Any]) -> dict[str, Any]:
    documents = row.get("documents") or []
    for document in documents:
        if str(document.get("role")) == "gold":
            return document
    return documents[0] if documents else {}


def review_record(
    source: str,
    row: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    answerability = str(row.get("answerability", ""))
    question = normalize_space(row.get("question", ""))
    answer = normalize_space(row.get("gold_answer") or row.get("expected_answer") or row.get("answer"))
    evidence_span = normalize_space(row.get("evidence_span", ""))
    chunk_ids = expected_chunk_ids(row)
    citations = [str(item) for item in row.get("citations", []) or [] if item]

    chunk = chunks_by_id.get(chunk_ids[0], {}) if chunk_ids else {}
    if source == "raft":
        gold_doc = first_gold_document(row)
        chunk = chunks_by_id.get(str(gold_doc.get("doc_id")), gold_doc) if gold_doc else chunk
        if not evidence_span:
            evidence_span = normalize_space(gold_doc.get("text", "")) if gold_doc else ""

    flags = issue_flags(row, question, answer, evidence_span)

    return {
        "source": source,
        "row_id": row_id(row),
        "answerability": answerability,
        "intent": str(row.get("intent", "")),
        "question": question,
        "answer": answer,
        "evidence_span": evidence_span,
        "expected_chunk_ids": "|".join(chunk_ids),
        "citations": "|".join(citations),
        "title": normalize_space(chunk.get("title", "")),
        "source_url": normalize_space(chunk.get("source_url", "")),
        "chunk_text_snippet": normalize_space(chunk.get("text", ""))[:700],
        "issue_flags": "|".join(flags),
        "review_question_ok": "",
        "review_answer_ok": "",
        "review_evidence_ok": "",
        "review_answerability_ok": "",
        "rewrite_question": "",
        "rewrite_answer": "",
        "review_notes": "",
    }


def issue_flags(row: dict[str, Any], question: str, answer: str, evidence_span: str) -> list[str]:
    flags: list[str] = []
    answerability = str(row.get("answerability", "")).lower()
    intent = str(row.get("intent", ""))

    if COMMA_ANCHOR_PATTERN.search(question):
        flags.append("comma_anchor_question")
    if any(hint in question for hint in GENERIC_QUESTION_HINTS):
        flags.append("generic_template_question")
    if answerability != "false" and not evidence_span:
        flags.append("missing_evidence_span")
    if answerability != "false" and FALSE_ANSWER_HINT in answer:
        flags.append("generic_refusal_on_answerable")
    if intent == "account_payment" and any(hint in evidence_span for hint in SCAM_HINTS):
        flags.append("possible_account_security_intent")
    if answerability == "false" and (row.get("citations") or expected_chunk_ids(row)):
        flags.append("false_has_evidence")
    if float(row.get("title_overlap_ratio") or 0.0) > 0.35:
        flags.append("title_overlap_high")
    return flags


def pick_review_rows(records: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    flagged = [record for record in records if record["issue_flags"]]
    clean = [record for record in records if not record["issue_flags"]]

    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for record in flagged + clean:
        groups[(record["source"], record["answerability"])].append(record)

    selected: list[dict[str, str]] = []
    seen = set()
    keys = sorted(groups)
    while len(selected) < limit and any(groups.values()):
        progressed = False
        for key in keys:
            bucket = groups[key]
            while bucket:
                record = bucket.pop(0)
                record_key = (record["source"], record["row_id"])
                if record_key in seen:
                    continue
                selected.append(record)
                seen.add(record_key)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create human review samples for expanded DNF domain data.")
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/domain_eval_set_expanded.jsonl"))
    parser.add_argument("--raft", type=Path, default=Path("data/processed/domain_raft_sample_expanded.jsonl"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--csv-output", type=Path, default=Path("outputs/domain_review_samples.csv"))
    parser.add_argument("--jsonl-output", type=Path, default=Path("labeling/domain_review_tasks.jsonl"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    chunks = read_jsonl(args.chunks)
    eval_rows = read_jsonl(args.eval_set)
    raft_rows = read_jsonl(args.raft)
    chunks_by_id = {str(chunk["doc_id"]): chunk for chunk in chunks}

    records = [
        review_record("eval", row, chunks_by_id)
        for row in eval_rows
    ]
    records.extend(review_record("raft", row, chunks_by_id) for row in raft_rows)
    selected = pick_review_rows(records, limit=args.limit)

    write_csv(args.csv_output, selected)
    write_jsonl(args.jsonl_output, selected)

    summary = {
        "csv_output": str(args.csv_output),
        "jsonl_output": str(args.jsonl_output),
        "records_total": len(records),
        "records_selected": len(selected),
        "selected_answerability_counts": dict(Counter(row["answerability"] for row in selected)),
        "selected_issue_flag_counts": dict(
            Counter(flag for row in selected for flag in row["issue_flags"].split("|") if flag)
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
