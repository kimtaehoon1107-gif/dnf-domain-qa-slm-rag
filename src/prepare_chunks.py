import argparse
import json
import re
import sys
from pathlib import Path

from io_utils import read_jsonl, write_jsonl


BOARD_HEADER_PATTERN = re.compile(
    r"^(공지사항|업데이트|이벤트)\s+.*?20\d{2}[./-]\d{1,2}[./-]\d{1,2}\s+\d{1,2}:\d{2}\s+[\d,]+\s+"
)
DNF_GREETING_PATTERN = re.compile(r"안녕하세요[.!?。]?\s*던전앤파이터\s*입니다[.!?。]?\s*")
FOOTER_NOISE = ("텍스트복사 목록", "액션쾌감!!! 던전앤파이터")


def validate_chunk_args(max_chars: int, overlap_chars: int) -> None:
    if max_chars <= 0:
        raise ValueError("--max-chars must be greater than 0.")
    if overlap_chars < 0:
        raise ValueError("--overlap-chars must be greater than or equal to 0.")
    if overlap_chars >= max_chars:
        raise ValueError("--overlap-chars must be smaller than --max-chars.")


def normalize_space(text: str) -> str:
    return " ".join(str(text or "").split())


def clean_board_header(text: str) -> str:
    text = normalize_space(text)
    text = BOARD_HEADER_PATTERN.sub("", text)
    text = DNF_GREETING_PATTERN.sub("", text)
    for noise in FOOTER_NOISE:
        text = text.replace(noise, " ")
    return normalize_space(text)


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    validate_chunk_args(max_chars, overlap_chars)
    text = normalize_space(text)
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return [chunk for chunk in chunks if chunk]


def make_chunks(
    docs: list[dict],
    max_chars: int,
    overlap_chars: int,
    clean_headers: bool = False,
) -> list[dict]:
    rows = []
    for doc in docs:
        text = clean_board_header(doc["text"]) if clean_headers else doc["text"]
        chunks = chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
        for index, chunk in enumerate(chunks, start=1):
            chunk_doc = {
                **doc,
                "doc_id": f"{doc['doc_id']}__chunk_{index:03d}",
                "parent_doc_id": doc["doc_id"],
                "chunk_index": index,
                "chunk_count": len(chunks),
                "text": chunk,
            }
            if clean_headers:
                chunk_doc["chunking"] = "official_fixed_no_header_v1"
                chunk_doc["chunk_max_chars"] = max_chars
                chunk_doc["header_cleaned"] = True
            rows.append(chunk_doc)
    return rows

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split collected DNF documents into retrieval chunks.")
    parser.add_argument("--docs", type=Path, default=Path("data/raw/official_docs.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/official_doc_chunks.jsonl"))
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--overlap-chars", type=int, default=200)
    parser.add_argument(
        "--clean-board-header",
        action="store_true",
        help="Remove board category/date/view boilerplate and generic DNF greeting before fixed-size chunking.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    docs = read_jsonl(args.docs)
    chunks = make_chunks(docs, args.max_chars, args.overlap_chars, clean_headers=args.clean_board_header)
    write_jsonl(args.output, chunks)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "docs": len(docs),
                "chunks": len(chunks),
                "clean_board_header": args.clean_board_header,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
