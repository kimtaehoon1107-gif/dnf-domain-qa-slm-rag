from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    parse_fixed_timestamp,
    write_immutable,
)


INDEX_SCHEMA_VERSION = "dnf_bm25_index_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_bm25_manifest_v3.1"
SMOKE_SCHEMA_VERSION = "dnf_bm25_smoke_v3.1"
REPORT_SCHEMA_VERSION = "dnf_bm25_baseline_report_v3.1"
TOKENIZER_VERSION = "dnf_lexical_nfkc_word_date_v1"
BM25_K1 = 1.2
BM25_B = 0.75
DEFAULT_AS_OF = "2026-07-18"
EXPECTED_CHUNK_COUNT = 3599
EXPECTED_DEFAULT_EXPOSURE_CHUNKS = 2527
BGE_M3_MODEL = "BAAI/bge-m3"

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CHUNK_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_INDEX_DIR = Path("data/v3/indexes")
DEFAULT_RETRIEVAL_DIR = Path("data/v3/retrieval")
DEFAULT_REPORT_DIR = Path("reports/v3")

TOKEN_PATTERN = re.compile(r"[0-9a-z가-힣_]+")
KOREAN_DATE_PATTERN = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
SLASH_DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})")
ISO_DATE_PATTERN = re.compile(r"20\d{2}[.-](\d{1,2})[.-](\d{1,2})")


@dataclass(frozen=True)
class SearchPolicy:
    default_exposure_only: bool = True
    allowed_statuses: tuple[str, ...] | None = ("current", "upcoming")
    include_review_required: bool = False
    as_of: str | None = None
    source_ids: tuple[str, ...] | None = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tokenize_lexical(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = TOKEN_PATTERN.findall(normalized)
    for pattern in (KOREAN_DATE_PATTERN, SLASH_DATE_PATTERN, ISO_DATE_PATTERN):
        for month, day in pattern.findall(normalized):
            month_value = str(int(month))
            day_value = str(int(day))
            tokens.extend(
                [
                    f"{month_value}/{day_value}",
                    f"{month_value:0>2}-{day_value:0>2}",
                    f"{month_value}월",
                    f"{day_value}일",
                ]
            )
    return tokens


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0.0}
    ordered = sorted(values)

    def percentile(value: float) -> int:
        return ordered[max(0, math.ceil(value * len(ordered)) - 1)]

    return {
        "min": ordered[0],
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 2),
    }


def build_bm25_index(
    chunks: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> dict[str, Any]:
    documents_by_id = {row["document_id"]: row for row in documents}
    if len(documents_by_id) != len(documents):
        raise RuntimeError("Duplicate document_id in normalized documents")
    entries = []
    postings: dict[str, list[list[int]]] = defaultdict(list)
    ordered_chunks = sorted(chunks, key=lambda row: row["chunk_id"])
    for ordinal, chunk in enumerate(ordered_chunks):
        parent = documents_by_id.get(chunk["parent_document_id"])
        if parent is None:
            raise RuntimeError(f"Unknown parent document: {chunk['parent_document_id']}")
        term_counts = Counter(tokenize_lexical(chunk["retrieval_text"]))
        entries.append(
            {
                "ordinal": ordinal,
                "chunk_id": chunk["chunk_id"],
                "parent_document_id": chunk["parent_document_id"],
                "canonical_url": parent["canonical_url"],
                "title": parent["title"],
                "source_id": chunk["source_id"],
                "source_kind": chunk["source_kind"],
                "status": chunk["status"],
                "default_exposure": chunk["default_exposure"],
                "review_required": chunk["review_required"],
                "offset_source": chunk["offset_source"],
                "valid_from": chunk["valid_from"],
                "valid_to": chunk["valid_to"],
                "document_length": sum(term_counts.values()),
            }
        )
        for term, frequency in sorted(term_counts.items()):
            postings[term].append([ordinal, frequency])
    total_length = sum(row["document_length"] for row in entries)
    return {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "indexed_text_field": "retrieval_text",
        "bm25_parameters": {"k1": BM25_K1, "b": BM25_B},
        "document_count": len(entries),
        "average_document_length": total_length / len(entries) if entries else 0.0,
        "entries": entries,
        "postings": dict(sorted(postings.items())),
    }


def _iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else None


def _allowed(entry: dict[str, Any], policy: SearchPolicy) -> bool:
    if policy.default_exposure_only and not entry["default_exposure"]:
        return False
    if policy.allowed_statuses is not None and entry["status"] not in policy.allowed_statuses:
        return False
    if not policy.include_review_required and entry["review_required"]:
        return False
    if policy.source_ids is not None and entry["source_id"] not in policy.source_ids:
        return False
    if policy.as_of is not None:
        as_of = _iso_date(policy.as_of)
        if as_of is None:
            raise RuntimeError(f"Invalid as_of date: {policy.as_of}")
        valid_from = _iso_date(entry["valid_from"])
        valid_to = _iso_date(entry["valid_to"])
        if valid_from is not None and valid_from > as_of:
            return False
        if valid_to is not None and valid_to < as_of:
            return False
    return True


def search_bm25(
    index: dict[str, Any],
    query: str,
    *,
    top_k: int = 5,
    policy: SearchPolicy | None = None,
) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise RuntimeError("top_k must be positive")
    policy = SearchPolicy() if policy is None else policy
    query_counts = Counter(tokenize_lexical(query))
    if not query_counts:
        return []
    entries = index["entries"]
    document_count = index["document_count"]
    average_length = index["average_document_length"] or 1.0
    k1 = index["bm25_parameters"]["k1"]
    b = index["bm25_parameters"]["b"]
    scores: dict[int, float] = defaultdict(float)
    for term, query_frequency in query_counts.items():
        term_postings = index["postings"].get(term, [])
        document_frequency = len(term_postings)
        if document_frequency == 0:
            continue
        inverse_document_frequency = math.log(
            1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        for ordinal, term_frequency in term_postings:
            entry = entries[ordinal]
            if not _allowed(entry, policy):
                continue
            length_norm = 1.0 - b + b * entry["document_length"] / average_length
            score = inverse_document_frequency * (
                term_frequency * (k1 + 1.0) / (term_frequency + k1 * length_norm)
            )
            scores[ordinal] += query_frequency * score
    ranked = sorted(scores.items(), key=lambda item: (-item[1], entries[item[0]]["chunk_id"]))
    results = []
    for rank, (ordinal, score) in enumerate(ranked[:top_k], start=1):
        results.append({"rank": rank, "score": score, **entries[ordinal]})
    return results


def audit_bm25_index(
    chunks: list[dict[str, Any]], index: dict[str, Any], *, expected_chunk_count: int
) -> dict[str, bool | int]:
    entries = index["entries"]
    expected_ids = {row["chunk_id"] for row in chunks}
    actual_ids = {row["chunk_id"] for row in entries}
    invalid_postings = 0
    for term, postings in index["postings"].items():
        if not term:
            invalid_postings += 1
        for ordinal, frequency in postings:
            if not isinstance(ordinal, int) or not 0 <= ordinal < len(entries) or frequency <= 0:
                invalid_postings += 1
    rebuilt = build_bm25_index(
        chunks,
        [
            {
                "document_id": entry["parent_document_id"],
                "canonical_url": entry["canonical_url"],
                "title": entry["title"],
            }
            for entry in {
                row["parent_document_id"]: row for row in entries
            }.values()
        ],
    )
    return {
        "chunk_count_matches_expected": len(chunks) == expected_chunk_count,
        "index_document_count_matches_chunks": index["document_count"] == len(chunks),
        "duplicate_index_chunk_ids": len(entries) - len(actual_ids),
        "index_chunk_id_set_mismatch": len(expected_ids ^ actual_ids),
        "entry_ordinal_sequence_mismatches": sum(
            entry["ordinal"] != ordinal for ordinal, entry in enumerate(entries)
        ),
        "invalid_postings": invalid_postings,
        "deterministic_rebuild_mismatch": int(rebuilt != index),
    }


def _title_rarity(index: dict[str, Any], title: str) -> float:
    document_count = index["document_count"]
    score = 0.0
    for token in set(tokenize_lexical(title)):
        frequency = len(index["postings"].get(token, []))
        if frequency:
            score += math.log(1.0 + document_count / frequency)
    return score


def _pick_title_document(
    index: dict[str, Any], documents: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("No candidate document for BM25 smoke case")
    return sorted(
        candidates,
        key=lambda row: (-_title_rarity(index, row["title"]), row["document_id"]),
    )[0]


def run_bm25_smoke(
    index: dict[str, Any],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    *,
    as_of: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parse_fixed_timestamp(f"{as_of}T00:00:00+09:00")
    default_policy = SearchPolicy(as_of=as_of)
    rows = []
    default_policy_violations = 0
    title_hits = 0
    source_ids = sorted({row["source_id"] for row in documents})
    for source_id in source_ids:
        document = _pick_title_document(
            index,
            documents,
            [
                row
                for row in documents
                if row["source_id"] == source_id
                and row["default_exposure"]
                and row["status"] in {"current", "upcoming"}
            ],
        )
        results = search_bm25(index, document["title"], top_k=5, policy=default_policy)
        rank = next(
            (row["rank"] for row in results if row["parent_document_id"] == document["document_id"]),
            None,
        )
        default_policy_violations += sum(not _allowed(row, default_policy) for row in results)
        title_hits += rank is not None
        rows.append(
            {
                "smoke_schema_version": SMOKE_SCHEMA_VERSION,
                "case_id": f"default_title_lookup:{source_id}",
                "case_kind": "default_title_lookup",
                "query": document["title"],
                "source_id": source_id,
                "target_parent_document_id": document["document_id"],
                "target_chunk_id": None,
                "default_target_leaked": None,
                "control_hit_at_5": rank is not None,
                "control_rank": rank,
                "result_chunk_ids": [row["chunk_id"] for row in results],
            }
        )

    control_hits = 0
    non_default_leaks = 0
    for status in ("expired", "superseded", "unknown"):
        document = _pick_title_document(
            index,
            documents,
            [row for row in documents if row["status"] == status],
        )
        default_results = search_bm25(index, document["title"], top_k=10, policy=default_policy)
        control_policy = SearchPolicy(
            default_exposure_only=False,
            allowed_statuses=(status,),
            include_review_required=False,
            as_of=None,
        )
        control_results = search_bm25(index, document["title"], top_k=5, policy=control_policy)
        leaked = any(
            row["parent_document_id"] == document["document_id"] for row in default_results
        )
        rank = next(
            (
                row["rank"]
                for row in control_results
                if row["parent_document_id"] == document["document_id"]
            ),
            None,
        )
        non_default_leaks += leaked
        control_hits += rank is not None
        rows.append(
            {
                "smoke_schema_version": SMOKE_SCHEMA_VERSION,
                "case_id": f"historical_control:{status}",
                "case_kind": "historical_control",
                "query": document["title"],
                "source_id": document["source_id"],
                "target_parent_document_id": document["document_id"],
                "target_chunk_id": None,
                "default_target_leaked": leaked,
                "control_hit_at_5": rank is not None,
                "control_rank": rank,
                "result_chunk_ids": [row["chunk_id"] for row in control_results],
            }
        )

    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    visual_entries = [row for row in index["entries"] if row["review_required"]]
    visual_candidates = []
    for entry in visual_entries:
        chunk = chunks_by_id[entry["chunk_id"]]
        tokens = sorted(
            set(tokenize_lexical(chunk["display_text"])),
            key=lambda token: (len(index["postings"].get(token, [])), token),
        )
        query_tokens = [token for token in tokens if len(token) >= 2][:6]
        if query_tokens:
            visual_candidates.append((sum(_title_rarity(index, token) for token in query_tokens), entry, query_tokens))
    if not visual_candidates:
        raise RuntimeError("No visual OCR smoke candidate")
    _, visual_entry, visual_query_tokens = sorted(
        visual_candidates, key=lambda item: (-item[0], item[1]["chunk_id"])
    )[0]
    visual_query = " ".join(visual_query_tokens)
    visual_default = search_bm25(index, visual_query, top_k=10, policy=default_policy)
    visual_control = search_bm25(
        index,
        visual_query,
        top_k=5,
        policy=SearchPolicy(
            default_exposure_only=False,
            allowed_statuses=(visual_entry["status"],),
            include_review_required=True,
            as_of=None,
        ),
    )
    visual_leaked = any(row["chunk_id"] == visual_entry["chunk_id"] for row in visual_default)
    visual_rank = next(
        (row["rank"] for row in visual_control if row["chunk_id"] == visual_entry["chunk_id"]),
        None,
    )
    non_default_leaks += visual_leaked
    control_hits += visual_rank is not None
    rows.append(
        {
            "smoke_schema_version": SMOKE_SCHEMA_VERSION,
            "case_id": "visual_ocr_control",
            "case_kind": "visual_ocr_control",
            "query": visual_query,
            "source_id": visual_entry["source_id"],
            "target_parent_document_id": visual_entry["parent_document_id"],
            "target_chunk_id": visual_entry["chunk_id"],
            "default_target_leaked": visual_leaked,
            "control_hit_at_5": visual_rank is not None,
            "control_rank": visual_rank,
            "result_chunk_ids": [row["chunk_id"] for row in visual_control],
        }
    )

    summary = {
        "default_title_lookup_cases": len(source_ids),
        "default_title_lookup_hit_at_5": title_hits,
        "historical_and_visual_control_cases": 4,
        "historical_and_visual_control_hit_at_5": control_hits,
        "default_policy_violations": default_policy_violations,
        "non_default_target_leaks": non_default_leaks,
    }
    summary["smoke_decision"] = (
        "GO"
        if title_hits == len(source_ids)
        and control_hits == 4
        and default_policy_violations == 0
        and non_default_leaks == 0
        else "NO-GO"
    )
    return sorted(rows, key=lambda row: row["case_id"]), summary


def measure_bge_m3_token_lengths(
    chunks: list[dict[str, Any]], *, model_name: str = BGE_M3_MODEL
) -> dict[str, Any]:
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        lengths = []
        batch_size = 32
        for start in range(0, len(chunks), batch_size):
            batch = [row["retrieval_text"] for row in chunks[start : start + batch_size]]
            encoded = tokenizer(
                batch,
                add_special_tokens=True,
                truncation=False,
                return_length=True,
            )
            lengths.extend(int(value) for value in encoded["length"])
        model_max_length = int(tokenizer.model_max_length)
        thresholds = [512, 1024, 2048, model_max_length]
        return {
            "status": "measured",
            "model_name": model_name,
            "tokenizer_class": tokenizer.__class__.__name__,
            "model_max_length": model_max_length,
            "row_count": len(lengths),
            "token_length": _distribution(lengths),
            "over_threshold": {
                str(threshold): sum(value > threshold for value in lengths)
                for threshold in sorted(set(thresholds))
            },
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "not_measured",
            "model_name": model_name,
            "tokenizer_class": None,
            "model_max_length": None,
            "row_count": 0,
            "token_length": _distribution([]),
            "over_threshold": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


def _render_report(report: dict[str, Any]) -> str:
    smoke = report["smoke"]
    dense = report["dense_token_measurement"]
    lines = [
        "# DNF RAG v3 BM25 lexical baseline",
        "",
        f"- built_at: `{report['built_at']}`",
        f"- lexical baseline decision: **{report['lexical_baseline_decision']}**",
        f"- dense tokenizer readiness: **{report['dense_tokenizer_readiness']}**",
        "",
        "## Index",
        "",
        f"- indexed chunks: {report['summary']['indexed_chunks']}",
        f"- vocabulary terms: {report['summary']['vocabulary_terms']}",
        f"- default searchable chunks: {report['summary']['default_searchable_chunks']}",
        f"- tokenizer: `{TOKENIZER_VERSION}`",
        f"- BM25: k1={BM25_K1}, b={BM25_B}",
        "",
        "## Smoke",
        "",
        f"- title lookup hit@5: {smoke['default_title_lookup_hit_at_5']}/{smoke['default_title_lookup_cases']}",
        f"- historical/OCR controls hit@5: {smoke['historical_and_visual_control_hit_at_5']}/{smoke['historical_and_visual_control_cases']}",
        f"- default policy violations: {smoke['default_policy_violations']}",
        f"- non-default target leaks: {smoke['non_default_target_leaks']}",
        "",
        "제목 lookup은 배관 검증용이며 retrieval 품질 평가가 아니다.",
        "",
        "## BGE-M3 tokenizer length",
        "",
        f"- status: `{dense['status']}`",
        f"- model max length: {dense['model_max_length']}",
        f"- distribution: `{json.dumps(dense['token_length'], ensure_ascii=False, sort_keys=True)}`",
        f"- over threshold: `{json.dumps(dense['over_threshold'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Audit gates",
        "",
        *[f"- {key}: `{value}`" for key, value in report["gates"].items()],
        "",
        "Dense index, Router, decomposition, generator, verifier, 평가, 학습은 실행하지 않았다.",
        "",
    ]
    return "\n".join(lines)


def build_bm25_artifacts(
    *,
    built_at: str,
    chunks_path: Path,
    chunk_manifest_path: Path,
    documents_path: Path,
    index_dir: Path,
    retrieval_dir: Path,
    report_dir: Path,
    expected_chunk_count: int = EXPECTED_CHUNK_COUNT,
    expected_default_exposure_chunks: int = EXPECTED_DEFAULT_EXPOSURE_CHUNKS,
    smoke_as_of: str = DEFAULT_AS_OF,
    run_dense_measurement: bool = False,
    dense_measurement_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_fixed_timestamp(built_at)
    input_paths = [chunks_path, chunk_manifest_path, documents_path]
    for path in input_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    input_hashes = {path: file_sha256(path) for path in input_paths}
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)

    index = build_bm25_index(chunks, documents)
    index_bytes = _canonical_json_bytes(index)
    index_sha256 = _sha256_bytes(index_bytes)
    index_path = index_dir / f"bm25_index_{index_sha256}.json"
    write_immutable(index_path, index_bytes)

    default_searchable_chunks = sum(
        _allowed(entry, SearchPolicy()) for entry in index["entries"]
    )
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "built_at": built_at,
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "bm25_parameters": {"k1": BM25_K1, "b": BM25_B},
        "indexed_text_field": "retrieval_text",
        "default_filter": {
            "default_exposure_only": True,
            "allowed_statuses": ["current", "upcoming"],
            "include_review_required": False,
        },
        "inputs": [
            {
                "role": "chunk_v3",
                "path": chunks_path.as_posix(),
                "sha256": input_hashes[chunks_path],
                "row_count": len(chunks),
            },
            {
                "role": "chunk_corpus_manifest",
                "path": chunk_manifest_path.as_posix(),
                "sha256": input_hashes[chunk_manifest_path],
                "row_count": None,
            },
            {
                "role": "document_v3",
                "path": documents_path.as_posix(),
                "sha256": input_hashes[documents_path],
                "row_count": len(documents),
            },
        ],
        "index": {
            "path": index_path.as_posix(),
            "sha256": index_sha256,
            "row_count": index["document_count"],
            "vocabulary_terms": len(index["postings"]),
            "default_searchable_chunks": default_searchable_chunks,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_path = index_dir / f"bm25_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    smoke_rows, smoke_summary = run_bm25_smoke(
        index, chunks, documents, as_of=smoke_as_of
    )
    smoke_bytes = _serialize_jsonl(smoke_rows, lambda row: row["case_id"])
    smoke_sha256 = _sha256_bytes(smoke_bytes)
    smoke_path = retrieval_dir / f"bm25_smoke_{smoke_sha256}.jsonl"
    write_immutable(smoke_path, smoke_bytes)

    gates = audit_bm25_index(
        chunks, index, expected_chunk_count=expected_chunk_count
    )
    gates["default_searchable_chunk_count_matches_expected"] = (
        default_searchable_chunks == expected_default_exposure_chunks
    )
    gates["smoke_decision_is_go"] = smoke_summary["smoke_decision"] == "GO"
    gate_go = all(
        value is True if isinstance(value, bool) else value == 0 for value in gates.values()
    )

    if dense_measurement_override is not None:
        dense_measurement = dense_measurement_override
    elif run_dense_measurement:
        dense_measurement = measure_bge_m3_token_lengths(chunks)
    else:
        dense_measurement = {
            "status": "not_measured",
            "model_name": BGE_M3_MODEL,
            "tokenizer_class": None,
            "model_max_length": None,
            "row_count": 0,
            "token_length": _distribution([]),
            "over_threshold": {},
            "error": "measurement_not_requested",
        }
    model_limit = dense_measurement.get("model_max_length")
    dense_ready = (
        dense_measurement.get("status") == "measured"
        and dense_measurement.get("row_count") == len(chunks)
        and model_limit is not None
        and dense_measurement.get("over_threshold", {}).get(str(model_limit)) == 0
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "built_at": built_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "smoke_path": smoke_path.as_posix(),
        "smoke_sha256": smoke_sha256,
        "summary": {
            "indexed_chunks": index["document_count"],
            "vocabulary_terms": len(index["postings"]),
            "default_searchable_chunks": default_searchable_chunks,
            "average_document_length": index["average_document_length"],
        },
        "smoke": smoke_summary,
        "dense_token_measurement": dense_measurement,
        "gates": gates,
        "lexical_baseline_decision": "GO" if gate_go else "NO-GO",
        "dense_tokenizer_readiness": "GO" if dense_ready else "NO-GO",
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = _sha256_bytes(report_bytes)
    report_json_path = report_dir / f"bm25_baseline_{report_sha256}.json"
    report_markdown_path = report_dir / f"bm25_baseline_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_markdown_path, _render_report(report).encode("utf-8"))

    for path, digest in input_hashes.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f"Input changed while building BM25 artifacts: {path}")
    return {
        "index_path": index_path.as_posix(),
        "index_sha256": index_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "smoke_path": smoke_path.as_posix(),
        "smoke_sha256": smoke_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_markdown_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "smoke": smoke_summary,
        "dense_token_measurement": dense_measurement,
        "lexical_baseline_decision": report["lexical_baseline_decision"],
        "dense_tokenizer_readiness": report["dense_tokenizer_readiness"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic BM25 artifacts and run v3 lexical safety smoke tests."
    )
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--chunk-manifest", type=Path, default=DEFAULT_CHUNK_MANIFEST)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--retrieval-dir", type=Path, default=DEFAULT_RETRIEVAL_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--smoke-as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--measure-bge-m3-token-lengths", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_bm25_artifacts(
        built_at=args.built_at,
        chunks_path=args.chunks,
        chunk_manifest_path=args.chunk_manifest,
        documents_path=args.documents,
        index_dir=args.index_dir,
        retrieval_dir=args.retrieval_dir,
        report_dir=args.report_dir,
        smoke_as_of=args.smoke_as_of,
        run_dense_measurement=args.measure_bge_m3_token_lengths,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
