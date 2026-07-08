from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl
from prepare_chunks import validate_chunk_args


BOARD_HEADER_PATTERN = re.compile(
    r"^(공지사항|업데이트|이벤트)\s+.*?20\d{2}\.\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}\s+[\d,]+\s+"
)
DATE_SECTION_PATTERN = re.compile(r"\s+((?:20\d{2}/)?\d{1,2}/\d{1,2}\s+추가)")
NUMBERED_ITEM_PATTERN = re.compile(r"\s+(\d+\.\s+)")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")

SECTION_MARKERS = (
    "패치 내용",
    "업데이트 내용",
    "개선 및 변경 사항",
    "변경 사항",
    "버그수정",
    "버그 수정",
    "이벤트 기간",
    "이벤트 내용",
    "이벤트 참여 방법",
    "보상",
    "보상 안내",
    "유의사항",
    "참고 사항",
    "주의 사항",
    "모험가님 꼭",
    "모험가님, 꼭",
    "꼭 알아두세요",
    "최초 공지",
)


def normalize_space(text: Any) -> str:
    return " ".join(str(text or "").split())


def clean_document_text(text: str) -> str:
    text = normalize_space(text)
    text = BOARD_HEADER_PATTERN.sub("", text)
    for suffix in ("텍스트복사 목록", "액션쾌감!!! 던전앤파이터"):
        text = text.replace(suffix, " ")
    return normalize_space(text)


def inject_section_breaks(text: str) -> str:
    text = DATE_SECTION_PATTERN.sub(r"\n\1", text)
    text = re.sub(r"\s+(최초 공지)", r"\n\1", text)
    for marker in SECTION_MARKERS:
        text = re.sub(rf"\s+({re.escape(marker)})", r"\n\1", text)
    text = re.sub(r"\s+([#▣■])", r"\n\1", text)
    text = NUMBERED_ITEM_PATTERN.sub(r"\n\1", text)
    return text


def section_label_for(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if re.match(r"(?:20\d{2}/)?\d{1,2}/\d{1,2}\s+추가", stripped):
        return stripped[:40]
    if stripped.startswith(("▣", "■", "#")):
        return stripped[:50]
    if re.match(r"\d+\.\s+", stripped):
        return "목록 항목"
    for marker in SECTION_MARKERS:
        if stripped.startswith(marker):
            return marker
    return ""


def split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_label = "본문"
    current_parts: list[str] = []

    def flush() -> None:
        body = normalize_space(" ".join(current_parts))
        if body:
            sections.append((current_label, body))

    for line in inject_section_breaks(text).split("\n"):
        line = normalize_space(line)
        if not line:
            continue
        label = section_label_for(line)
        if label and current_parts:
            flush()
            current_parts = []
        if label:
            current_label = label
        current_parts.append(line)
    flush()
    return sections


def hard_split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return [piece for piece in pieces if piece]


def split_units(body: str, max_chars: int, overlap_chars: int) -> list[str]:
    units: list[str] = []
    for sentence in SENTENCE_SPLIT_PATTERN.split(body):
        sentence = normalize_space(sentence)
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            units.append(sentence)
        else:
            units.extend(hard_split(sentence, max_chars, overlap_chars))
    return units


def pack_units(units: list[str], max_chars: int, overlap_units: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        extra = len(unit) + (1 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append(" ".join(current))
            current = current[-overlap_units:] if overlap_units else []
            current_len = len(" ".join(current))
        current.append(unit)
        current_len = len(" ".join(current))
    if current:
        chunks.append(" ".join(current))
    return chunks


def make_section_chunks(
    text: str,
    max_chars: int,
    overlap_chars: int,
    overlap_units: int,
    include_section_header: bool,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for section_label, section_body in split_sections(text):
        header = f"섹션: {section_label}\n" if include_section_header and section_label else ""
        body_budget = max(200, max_chars - len(header))
        units = split_units(section_body, body_budget, overlap_chars)
        for chunk in pack_units(units, body_budget, overlap_units):
            rows.append((section_label, f"{header}{chunk}".strip()))
    return rows


def make_chunks(
    docs: list[dict[str, Any]],
    max_chars: int,
    overlap_chars: int,
    overlap_units: int,
    include_section_header: bool,
) -> list[dict[str, Any]]:
    validate_chunk_args(max_chars, overlap_chars)
    rows: list[dict[str, Any]] = []
    for doc in docs:
        text = clean_document_text(doc.get("text", ""))
        pieces = make_section_chunks(
            text=text,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            overlap_units=overlap_units,
            include_section_header=include_section_header,
        )
        if not pieces and text:
            pieces = [("본문", text[:max_chars])]
        for index, (section_label, chunk_text) in enumerate(pieces, start=1):
            rows.append(
                {
                    **doc,
                    "doc_id": f"{doc['doc_id']}__chunk_{index:03d}",
                    "parent_doc_id": doc["doc_id"],
                    "chunk_index": index,
                    "chunk_count": len(pieces),
                    "section": section_label,
                    "chunking": "official_section_v1",
                    "chunk_max_chars": max_chars,
                    "text": chunk_text,
                }
            )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Section-aware chunker for flat official DNF documents.")
    parser.add_argument("--docs", type=Path, default=Path("data/raw/official_docs.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, required=True)
    parser.add_argument("--overlap-chars", type=int, default=80)
    parser.add_argument("--overlap-units", type=int, default=1)
    parser.add_argument("--no-section-header", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    docs = read_jsonl(args.docs)
    chunks = make_chunks(
        docs=docs,
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
        overlap_units=args.overlap_units,
        include_section_header=not args.no_section_header,
    )
    write_jsonl(args.output, chunks)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "docs": len(docs),
                "chunks": len(chunks),
                "max_chars": args.max_chars,
                "chunks_with_section": sum(1 for chunk in chunks if chunk.get("section")),
                "avg_chunks_per_doc": round(len(chunks) / len(docs), 1) if docs else 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
