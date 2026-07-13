from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


PREFIX_VERSION = "deterministic_context_v1"
DOC_TYPE_LABELS = {
    "account_payment": "계정/결제 안내",
    "bug_known_issue": "알려진 문제",
    "event": "이벤트",
    "game_guide": "게임 가이드",
    "notice": "공지",
    "patch_note": "업데이트/패치 노트",
}


def clean_value(value: Any) -> str:
    return " ".join(str(value or "").split())


def build_contextual_prefix(doc: dict[str, Any]) -> str:
    doc_type = clean_value(doc.get("doc_type"))
    lines = [f"문서 유형: {DOC_TYPE_LABELS.get(doc_type, doc_type)}"]

    published_at = clean_value(doc.get("published_at"))
    if published_at:
        lines.append(f"게시일: {published_at}")

    effective_start = clean_value(doc.get("effective_start"))
    effective_end = clean_value(doc.get("effective_end"))
    if effective_start and effective_end:
        lines.append(f"적용 기간: {effective_start} ~ {effective_end}")
    elif effective_start:
        lines.append(f"적용 시작: {effective_start}")
    elif effective_end:
        lines.append(f"적용 종료: {effective_end}")

    section = clean_value(doc.get("section"))
    if section:
        lines.append(f"섹션: {section}")
    return "\n".join(lines)


def add_contextual_prefix(doc: dict[str, Any]) -> dict[str, Any]:
    text = str(doc.get("text") or "").strip()
    if not text:
        raise ValueError(f"Chunk {doc.get('doc_id', '<unknown>')} has empty text.")
    prefix = build_contextual_prefix(doc)
    result = dict(doc)
    result["text"] = f"{prefix}\n\n{text}"
    result["contextual_prefix"] = prefix
    result["contextual_prefix_version"] = PREFIX_VERSION
    return result


def make_contextual_chunks(input_path: Path, output_path: Path) -> dict[str, Any]:
    docs = read_jsonl(input_path)
    contextual_docs = [add_contextual_prefix(doc) for doc in docs]
    if len({doc["doc_id"] for doc in contextual_docs}) != len(contextual_docs):
        raise ValueError("Contextual chunk output contains duplicate doc_id values.")
    write_jsonl(output_path, contextual_docs)
    return {
        "input": str(input_path),
        "output": str(output_path),
        "rows": len(contextual_docs),
        "prefix_version": PREFIX_VERSION,
        "doc_ids_preserved": [doc["doc_id"] for doc in docs]
        == [doc["doc_id"] for doc in contextual_docs],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a separate deterministic-contextual-prefix chunk artifact."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(json.dumps(make_contextual_chunks(args.input, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
