from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl

CHOICE_FIELDS = ("intent", "answerability", "evidence_quality")
TEXT_FIELDS = ("evidence_doc_ids", "corrected_answer", "review_notes")


def load_docs(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    return {row["doc_id"]: row for row in read_jsonl(path)}


def get_item_id(row: dict[str, Any]) -> str:
    for key in ("qa_id", "eval_id", "raft_id", "id"):
        if row.get(key):
            return str(row[key])
    raise ValueError(f"Row has no supported ID field: {row}")


def get_evidence_ids(row: dict[str, Any]) -> list[str]:
    for key in ("evidence_doc_ids", "expected_evidence_doc_ids", "citations"):
        value = row.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if item]
    return []


def format_candidate_evidence(evidence_ids: list[str], docs: dict[str, dict[str, Any]]) -> str:
    if not evidence_ids:
        return "No candidate evidence IDs were provided."

    blocks = []
    for doc_id in evidence_ids:
        doc = docs.get(doc_id)
        if not doc:
            blocks.append(f"[{doc_id}]\nDocument text not loaded.")
            continue
        title = doc.get("title", "")
        text = str(doc.get("text", ""))
        if len(text) > 1800:
            text = text[:1800].rstrip() + "..."
        blocks.append(f"[{doc_id}] {title}\n{text}")
    return "\n\n".join(blocks)


def make_prediction(row: dict[str, Any], evidence_ids: list[str]) -> dict[str, Any]:
    results = []
    for field in CHOICE_FIELDS:
        value = row.get(field)
        if value:
            results.append(
                {
                    "from_name": field,
                    "to_name": "question",
                    "type": "choices",
                    "value": {"choices": [str(value)]},
                }
            )

    if evidence_ids:
        results.append(
            {
                "from_name": "evidence_doc_ids",
                "to_name": "question",
                "type": "textarea",
                "value": {"text": [", ".join(evidence_ids)]},
            }
        )

    expected_answer = row.get("expected_answer") or row.get("answer")
    if expected_answer:
        results.append(
            {
                "from_name": "corrected_answer",
                "to_name": "question",
                "type": "textarea",
                "value": {"text": [str(expected_answer)]},
            }
        )

    return {"model_version": "source-labels", "result": results}


def export_tasks(args: argparse.Namespace) -> None:
    rows = read_jsonl(args.input)
    docs = load_docs(args.docs)
    tasks = []

    for row in rows:
        item_id = get_item_id(row)
        evidence_ids = get_evidence_ids(row)
        expected_answer = row.get("expected_answer") or row.get("answer") or ""
        task = {
            "data": {
                "item_id": item_id,
                "question": row.get("question", ""),
                "expected_answer": expected_answer,
                "candidate_evidence": format_candidate_evidence(evidence_ids, docs),
            },
            "meta": {
                "source_split": row.get("split", ""),
                "source_intent": row.get("intent", ""),
                "source_answerability": row.get("answerability", ""),
                "source_evidence_doc_ids": evidence_ids,
            },
        }
        if args.include_prelabels:
            task["predictions"] = [make_prediction(row, evidence_ids)]
        tasks.append(task)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "output": str(args.output)}, ensure_ascii=False))


def first_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = task.get("annotations") or []
    completed = [item for item in annotations if not item.get("was_cancelled")]
    if completed:
        return completed[-1]
    return annotations[-1] if annotations else None


def text_value(result: dict[str, Any]) -> str:
    text = result.get("value", {}).get("text", [])
    if isinstance(text, list):
        return text[0].strip() if text else ""
    return str(text).strip()


def choices_value(result: dict[str, Any]) -> str:
    choices = result.get("value", {}).get("choices", [])
    if isinstance(choices, list):
        return choices[0] if choices else ""
    return str(choices)


def split_doc_ids(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def parse_annotation(task: dict[str, Any]) -> dict[str, str]:
    annotation = first_annotation(task)
    values = {field: "" for field in (*CHOICE_FIELDS, *TEXT_FIELDS)}
    if not annotation:
        return values

    for result in annotation.get("result", []):
        field = result.get("from_name")
        if field in CHOICE_FIELDS:
            values[field] = choices_value(result)
        elif field in TEXT_FIELDS:
            values[field] = text_value(result)
    return values


def convert_export(args: argparse.Namespace) -> None:
    tasks = json.loads(args.input.read_text(encoding="utf-8-sig"))
    rows = []

    for task in tasks:
        data = task.get("data", {})
        labels = parse_annotation(task)
        item_id = data.get("item_id") or task.get("id")
        row = {
            "item_id": str(item_id),
            "question": data.get("question", ""),
            "intent": labels["intent"],
            "answerability": labels["answerability"],
            "evidence_quality": labels["evidence_quality"],
            "evidence_doc_ids": split_doc_ids(labels["evidence_doc_ids"]),
            "corrected_answer": labels["corrected_answer"],
            "review_notes": labels["review_notes"],
            "source_split": task.get("meta", {}).get("source_split", ""),
            "source_payload": data,
        }
        rows.append(row)

    write_jsonl(args.output, rows)
    print(json.dumps({"rows": len(rows), "output": str(args.output)}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and normalize Label Studio data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-tasks", help="Convert project JSONL rows to Label Studio import tasks.")
    export_parser.add_argument("--input", type=Path, required=True)
    export_parser.add_argument("--docs", type=Path, default=None)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--include-prelabels", action="store_true")
    export_parser.set_defaults(func=export_tasks)

    convert_parser = subparsers.add_parser("convert-export", help="Convert Label Studio JSON export to normalized JSONL.")
    convert_parser.add_argument("--input", type=Path, required=True)
    convert_parser.add_argument("--output", type=Path, required=True)
    convert_parser.set_defaults(func=convert_export)

    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
