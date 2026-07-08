import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

# Must load before chromadb: importing torch/sentence-transformers after
# chromadb has already loaded its own native deps causes a native crash
# (segfault) with the CUDA build of torch on Windows. Importing torch first
# lets it claim shared native DLLs (CUDA runtime/OpenMP) before chromadb does.
import torch  # noqa: F401
import sentence_transformers  # noqa: F401

import chromadb
from chromadb.utils import embedding_functions

from build_index import COLLECTION_NAME
from retrieval_config import DEFAULT_EMBEDDING_MODEL, DEFAULT_RANK_MODE, RANK_MODES


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
KOREAN_DATE_PATTERN = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
SLASH_DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})")
ISO_DATE_PATTERN = re.compile(r"20\d{2}[.-](\d{1,2})[.-](\d{1,2})")
RRF_K = 60


@lru_cache(maxsize=16)
def get_collection(persist_dir: Path, model_name: str = DEFAULT_EMBEDDING_MODEL):
    client = chromadb.PersistentClient(path=str(persist_dir))
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    return client.get_collection(name=COLLECTION_NAME, embedding_function=embedding_fn)


def tokenize(text: str) -> set[str]:
    tokens = {token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) >= 2}
    for pattern in (KOREAN_DATE_PATTERN, SLASH_DATE_PATTERN, ISO_DATE_PATTERN):
        for month, day in pattern.findall(text):
            month_value = str(int(month))
            day_value = str(int(day))
            tokens.add(f"{month_value}/{day_value}")
            tokens.add(f"{month_value:0>2}-{day_value:0>2}")
            tokens.add(f"{month_value}월")
            tokens.add(f"{day_value}일")
    return tokens


def lexical_score(question: str, document: str, metadata: dict) -> int:
    question_tokens = tokenize(question)
    title_tokens = tokenize(metadata.get("title", ""))
    doc_tokens = tokenize(f"{metadata.get('tags', '')} {document}")
    title_overlap = len(question_tokens & title_tokens)
    body_overlap = len(question_tokens & doc_tokens)
    return (title_overlap * 3) + body_overlap


def apply_rank_mode(hits: list[dict], rank_mode: str) -> list[dict]:
    if rank_mode == "semantic":
        return sorted(hits, key=lambda hit: hit["distance"])
    if rank_mode == "lexical_first":
        return sorted(hits, key=lambda hit: (-hit["lexical_score"], hit["distance"]))
    if rank_mode == "rrf":
        semantic_order = sorted(hits, key=lambda hit: hit["distance"])
        lexical_order = sorted(hits, key=lambda hit: (-hit["lexical_score"], hit["distance"]))
        semantic_ranks = {hit["doc_id"]: rank for rank, hit in enumerate(semantic_order, start=1)}
        lexical_ranks = {hit["doc_id"]: rank for rank, hit in enumerate(lexical_order, start=1)}
        for hit in hits:
            semantic_rank = semantic_ranks[hit["doc_id"]]
            lexical_rank = lexical_ranks[hit["doc_id"]]
            hit["semantic_rank"] = semantic_rank
            hit["lexical_rank"] = lexical_rank
            hit["rrf_score"] = (1 / (RRF_K + semantic_rank)) + (1 / (RRF_K + lexical_rank))
        return sorted(hits, key=lambda hit: (-hit["rrf_score"], hit["distance"]))
    if rank_mode != "hybrid":
        raise ValueError(f"Unknown rank_mode: {rank_mode}")

    max_lexical = max((hit["lexical_score"] for hit in hits), default=0) or 1
    distances = [float(hit["distance"]) for hit in hits]
    min_distance = min(distances, default=0.0)
    max_distance = max(distances, default=min_distance)
    distance_range = max(max_distance - min_distance, 1e-9)
    for hit in hits:
        lexical_norm = hit["lexical_score"] / max_lexical
        semantic_norm = 1.0 - ((float(hit["distance"]) - min_distance) / distance_range)
        hit["hybrid_score"] = (lexical_norm + semantic_norm) / 2.0
    return sorted(hits, key=lambda hit: (-hit["hybrid_score"], hit["distance"]))


def retrieve(
    question: str,
    persist_dir: Path = Path("outputs/chroma"),
    top_k: int = 5,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    candidate_k: int | None = None,
    rank_mode: str = DEFAULT_RANK_MODE,
) -> list[dict]:
    collection = get_collection(persist_dir, model_name)
    doc_count = collection.count()
    if doc_count == 0:
        return []
    n_results = min(candidate_k or max(top_k * 20, 100), doc_count)
    result = collection.query(query_texts=[question], n_results=n_results)

    hits = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for doc_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        hits.append(
            {
                "rank": 0,
                "doc_id": doc_id,
                "title": metadata.get("title", ""),
                "doc_type": metadata.get("doc_type", ""),
                "distance": distance,
                "lexical_score": lexical_score(question, document, metadata),
                "text": document,
                "metadata": metadata,
            }
        )
    ranked_hits = apply_rank_mode(hits, rank_mode)
    for rank, hit in enumerate(ranked_hits[:top_k], start=1):
        hit["rank"] = rank
        hit["rank_mode"] = rank_mode
    return ranked_hits[:top_k]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrieve DNF documents for a question.")
    parser.add_argument("question")
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    hits = retrieve(
        args.question,
        persist_dir=args.persist_dir,
        top_k=args.top_k,
        model_name=args.model_name,
        candidate_k=args.candidate_k,
        rank_mode=args.rank_mode,
    )
    print(json.dumps(hits, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
