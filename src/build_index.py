import argparse
import json
import sys
from pathlib import Path

# Must load before chromadb: see retrieve.py for why.
import torch  # noqa: F401
import sentence_transformers  # noqa: F401

import chromadb
from chromadb.utils import embedding_functions

from io_utils import read_jsonl
from retrieval_config import DEFAULT_EMBEDDING_MODEL


COLLECTION_NAME = "dnf_docs"


def to_chroma_metadata(doc: dict) -> dict:
    metadata = {
        "doc_id": doc["doc_id"],
        "source_type": doc["source_type"],
        "doc_type": doc["doc_type"],
        "title": doc["title"],
        "published_at": doc.get("published_at") or "",
        "effective_start": doc.get("effective_start") or "",
        "effective_end": doc.get("effective_end") or "",
        "source_url": doc.get("source_url") or "",
        "tags": ",".join(doc.get("tags", [])),
    }
    if doc.get("parent_doc_id"):
        metadata["parent_doc_id"] = doc["parent_doc_id"]
    if "chunk_index" in doc and doc["chunk_index"] is not None:
        metadata["chunk_index"] = int(doc["chunk_index"])
    if "chunk_count" in doc and doc["chunk_count"] is not None:
        metadata["chunk_count"] = int(doc["chunk_count"])
    if doc.get("section"):
        metadata["section"] = doc["section"]
    if doc.get("chunking"):
        metadata["chunking"] = doc["chunking"]
    if doc.get("chunk_max_chars") is not None:
        metadata["chunk_max_chars"] = int(doc["chunk_max_chars"])
    return metadata


def build_index(
    docs_path: Path,
    persist_dir: Path,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    reset: bool = False,
) -> int:
    docs = read_jsonl(docs_path)
    persist_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(persist_dir))
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    collection.upsert(
        ids=[doc["doc_id"] for doc in docs],
        documents=[f"{doc['title']}\n\n{doc['text']}" for doc in docs],
        metadatas=[to_chroma_metadata(doc) for doc in docs],
    )
    return len(docs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Chroma index for DNF documents.")
    parser.add_argument("--docs", type=Path, default=Path("data/raw/docs.jsonl"))
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma"))
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    count = build_index(args.docs, args.persist_dir, args.model_name, args.reset)
    print(
        json.dumps(
            {
                "indexed_docs": count,
                "persist_dir": str(args.persist_dir),
                "model_name": args.model_name,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
