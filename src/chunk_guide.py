from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


SECTION_H2 = "## "
SECTION_H3 = "### "
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+")


def split_sections(text: str) -> list[tuple[list[str], str]]:
    """Split heading-marked text (## / ###) into (heading_path, body) sections."""
    sections: list[tuple[list[str], str]] = []
    h2: str | None = None
    h3: str | None = None
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(([h for h in (h2, h3) if h], body))

    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped.startswith(SECTION_H2) or stripped.startswith(SECTION_H3):
            flush()
            buf.clear()
            if stripped.startswith(SECTION_H2):
                h2, h3 = stripped[len(SECTION_H2):].strip(), None
            else:
                h3 = stripped[len(SECTION_H3):].strip()
        else:
            buf.append(raw)
    flush()
    return sections


def split_units(body: str, max_chars: int) -> list[str]:
    """Break a section body into atoms no larger than max_chars: paragraphs,
    then sentences, then a hard character cut as a last resort."""
    units: list[str] = []
    for paragraph in re.split(r"\n+", body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        for sentence in SENTENCE_SPLIT.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                units.append(sentence)
            else:
                for start in range(0, len(sentence), max_chars):
                    units.append(sentence[start:start + max_chars])
    return units


def pack_units(units: list[str], max_chars: int) -> list[str]:
    """Greedily pack atoms into chunks <= max_chars, carrying the last atom into
    the next chunk as a one-unit overlap for context continuity."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for unit in units:
        extra = len(unit) + (1 if current else 0)
        if current and length + extra > max_chars:
            chunks.append(" ".join(current))
            current = [current[-1]] if len(current) > 1 else []
            length = len(current[0]) if current else 0
        current.append(unit)
        length += len(unit) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_document(doc: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    title = doc.get("title", "")
    rows: list[dict[str, Any]] = []
    pieces: list[tuple[str, str]] = []  # (section_label, chunk_text)
    for heading_path, body in split_sections(doc["text"]):
        section_label = " > ".join(heading_path)
        header = f"{section_label}\n" if section_label else ""
        body_budget = max(200, max_chars - len(header))
        for body_chunk in pack_units(split_units(body, body_budget), body_budget):
            pieces.append((section_label, f"{header}{body_chunk}"))

    for index, (section_label, chunk_text) in enumerate(pieces, start=1):
        rows.append(
            {
                **doc,
                "doc_id": f"{doc['doc_id']}__chunk_{index:03d}",
                "parent_doc_id": doc["doc_id"],
                "chunk_index": index,
                "chunk_count": len(pieces),
                "section": section_label,
                "text": chunk_text,
            }
        )
    return rows


def make_chunks(docs: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in docs:
        rows.extend(chunk_document(doc, max_chars=max_chars))
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Heading-aware recursive chunker for structured guide docs.")
    parser.add_argument("--docs", type=Path, default=Path("data/raw/guide_docs.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/guide_chunks.jsonl"))
    parser.add_argument("--max-chars", type=int, default=900)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    docs = read_jsonl(args.docs)
    chunks = make_chunks(docs, max_chars=args.max_chars)
    write_jsonl(args.output, chunks)
    sections = sum(1 for chunk in chunks if chunk["section"])
    print(
        json.dumps(
            {
                "output": str(args.output),
                "docs": len(docs),
                "chunks": len(chunks),
                "chunks_with_section_header": sections,
                "avg_chunks_per_doc": round(len(chunks) / len(docs), 1) if docs else 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
