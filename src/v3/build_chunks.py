from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_chunk_pilot import (
    MIN_MULTI_CHUNK_CHARS,
    SOURCE_CONFIG,
    TOKEN_COUNT_METHOD,
    _lexical_token_count,
    _retrieval_text,
    build_chunks_for_selection,
)
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    parse_fixed_timestamp,
    write_immutable,
)
from src.v3.schemas import (
    NORMALIZED_CHUNK_REQUIRED_FIELDS,
    NORMALIZED_CHUNK_SCHEMA_VERSION,
    missing_required_fields,
)


CHUNKER_VERSION = "dnf_offset_chunk_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_chunk_corpus_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_chunk_corpus_audit_v3.1"
AUDIT_COUNTER_KEYS = (
    "chunk_id_mismatches",
    "chunk_index_sequence_mismatches",
    "chunker_version_mismatches",
    "default_exposure_policy_violations",
    "document_without_dom_chunk",
    "empty_display_or_retrieval_text",
    "evidence_policy_mismatches",
    "invalid_offset_source",
    "invalid_offsets",
    "non_whitespace_coverage_gaps",
    "normalized_text_hash_mismatches",
    "offset_mismatches",
    "orphan_multi_document_chunks",
    "oversized_chunks",
    "parent_content_hash_mismatches",
    "parent_default_exposure_mismatches",
    "parent_metadata_mismatches",
    "retrieval_text_mismatches",
    "schema_missing_required_fields",
    "schema_version_mismatches",
    "source_config_mismatches",
    "token_count_method_mismatches",
    "token_count_mismatches",
    "unexpected_visual_chunk_parent",
    "unknown_parent_document",
    "visual_document_without_visual_chunk",
)

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CONTENTS = Path(
    "data/v3/normalized/"
    "document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl"
)
DEFAULT_NORMALIZED_MANIFEST = Path(
    "data/v3/normalized/"
    "normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json"
)
DEFAULT_PILOT_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_pilot_manifest_ba5e1d5a9b8a237df9a99e5fb698bbb8e0a4b6dc1668b3cabece9e971e0154e6.json"
)
DEFAULT_CHUNK_DIR = Path("data/v3/chunks")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0.0}
    ordered = sorted(values)

    def percentile(value: float) -> int:
        index = max(0, math.ceil(value * len(ordered)) - 1)
        return ordered[index]

    return {
        "min": ordered[0],
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 2),
    }


def _has_non_whitespace_gap(text: str, spans: list[tuple[int, int]]) -> bool:
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor and text[cursor:start].strip():
            return True
        cursor = max(cursor, end)
    return bool(text[cursor:].strip())


def _expected_chunk_id(row: dict[str, Any]) -> str:
    display_hash = _sha256_bytes(row["display_text"].encode("utf-8"))
    payload = (
        f"{row['parent_document_id']}\n{row['offset_source']}\n"
        f"{row['start_offset']}\n{row['end_offset']}\n{display_hash}\n"
        f"{row['chunker_version']}"
    )
    return f"chunk_sha256_{_sha256_bytes(payload.encode('utf-8'))}"


def audit_chunk_corpus(
    documents: list[dict[str, Any]],
    contents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    *,
    expected_document_count: int,
    expected_source_ids: set[str],
) -> dict[str, Any]:
    document_ids = [row["document_id"] for row in documents]
    content_ids = [row["document_id"] for row in contents]
    documents_by_id = {row["document_id"]: row for row in documents}
    contents_by_id = {row["document_id"]: row for row in contents}
    chunk_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    coverage_spans: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)

    counters = Counter()
    for row in chunks:
        if missing_required_fields(row, NORMALIZED_CHUNK_REQUIRED_FIELDS):
            counters["schema_missing_required_fields"] += 1
        parent_id = row.get("parent_document_id")
        if parent_id not in documents_by_id or parent_id not in contents_by_id:
            counters["unknown_parent_document"] += 1
            continue
        document = documents_by_id[parent_id]
        content = contents_by_id[parent_id]
        offset_source = row.get("offset_source")
        if offset_source == "dom_text":
            source_text = content["text"]
            source_hash = content["text_hash"]
            expected_default_exposure = document["default_exposure"]
            expected_quality = "official_dom_text"
            expected_review = False
        elif offset_source == "visual_ocr" and content["visual_evidence"]:
            source_text = content["visual_evidence"]["text"]
            source_hash = content["visual_evidence"]["text_hash"]
            expected_default_exposure = False
            expected_quality = "unverified_ocr"
            expected_review = True
        else:
            counters["invalid_offset_source"] += 1
            continue

        chunk_groups[(parent_id, offset_source)].append(row)
        start = row.get("start_offset")
        end = row.get("end_offset")
        valid_offsets = (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(source_text)
        )
        if not valid_offsets:
            counters["invalid_offsets"] += 1
        else:
            coverage_spans[(parent_id, offset_source)].append((start, end))
            if source_text[start:end] != row.get("display_text"):
                counters["offset_mismatches"] += 1

        if row.get("chunk_schema_version") != NORMALIZED_CHUNK_SCHEMA_VERSION:
            counters["schema_version_mismatches"] += 1
        if row.get("chunker_version") != CHUNKER_VERSION:
            counters["chunker_version_mismatches"] += 1
        if row.get("chunk_id") != _expected_chunk_id(row):
            counters["chunk_id_mismatches"] += 1
        if not row.get("display_text") or not row.get("retrieval_text"):
            counters["empty_display_or_retrieval_text"] += 1
        if row.get("retrieval_text") != _retrieval_text(
            document["title"], row.get("heading_path", []), row.get("display_text", "")
        ):
            counters["retrieval_text_mismatches"] += 1
        if row.get("token_count") != _lexical_token_count(row.get("display_text", "")):
            counters["token_count_mismatches"] += 1
        if row.get("token_count_method") != TOKEN_COUNT_METHOD:
            counters["token_count_method_mismatches"] += 1
        if row.get("normalized_text_hash") != source_hash:
            counters["normalized_text_hash_mismatches"] += 1
        if row.get("parent_content_hash") != document["content_hash"]:
            counters["parent_content_hash_mismatches"] += 1
        if any(
            row.get(key) != document[key]
            for key in ("source_id", "source_kind", "status", "valid_from", "valid_to")
        ):
            counters["parent_metadata_mismatches"] += 1
        if row.get("default_exposure") != expected_default_exposure:
            counters["parent_default_exposure_mismatches"] += 1
        if (
            row.get("evidence_quality") != expected_quality
            or row.get("review_required") != expected_review
        ):
            counters["evidence_policy_mismatches"] += 1
        if row.get("default_exposure") and (
            row.get("status") not in {"current", "upcoming"}
            or row.get("source_kind") in {"preview_patch", "roadmap_statement"}
        ):
            counters["default_exposure_policy_violations"] += 1
        source_config = SOURCE_CONFIG.get(document["source_id"])
        if source_config is None or (
            row.get("max_chars"), row.get("overlap_chars")
        ) != source_config:
            counters["source_config_mismatches"] += 1
        if row.get("oversized_atomic") or len(row.get("display_text", "")) > row.get(
            "max_chars", 0
        ):
            counters["oversized_chunks"] += 1

    expected_dom_parents = set(documents_by_id)
    expected_visual_parents = {
        document_id
        for document_id, content in contents_by_id.items()
        if content["visual_evidence"] is not None
    }
    actual_dom_parents = {
        document_id for document_id, offset_source in chunk_groups if offset_source == "dom_text"
    }
    actual_visual_parents = {
        document_id
        for document_id, offset_source in chunk_groups
        if offset_source == "visual_ocr"
    }

    for key, rows in chunk_groups.items():
        ordered = sorted(rows, key=lambda row: row["chunk_index"])
        if [row["chunk_index"] for row in ordered] != list(range(1, len(ordered) + 1)) or any(
            row["chunk_count"] != len(ordered) for row in ordered
        ):
            counters["chunk_index_sequence_mismatches"] += 1
        if len(ordered) > 1:
            counters["orphan_multi_document_chunks"] += sum(
                len(row["display_text"]) < MIN_MULTI_CHUNK_CHARS for row in ordered
            )
        content = contents_by_id[key[0]]
        source_text = (
            content["text"] if key[1] == "dom_text" else content["visual_evidence"]["text"]
        )
        if _has_non_whitespace_gap(source_text, coverage_spans[key]):
            counters["non_whitespace_coverage_gaps"] += 1

    counters["document_without_dom_chunk"] = len(expected_dom_parents - actual_dom_parents)
    counters["visual_document_without_visual_chunk"] = len(
        expected_visual_parents - actual_visual_parents
    )
    counters["unexpected_visual_chunk_parent"] = len(
        actual_visual_parents - expected_visual_parents
    )

    dom_chunks = [row for row in chunks if row.get("offset_source") == "dom_text"]
    visual_chunks = [row for row in chunks if row.get("offset_source") == "visual_ocr"]
    duplicate_document_ids = len(document_ids) - len(set(document_ids))
    duplicate_content_ids = len(content_ids) - len(set(content_ids))
    gates: dict[str, bool | int] = {
        "document_count_matches_expected": len(documents) == expected_document_count,
        "all_expected_sources_represented": {row["source_id"] for row in documents}
        == expected_source_ids,
        "duplicate_document_ids": duplicate_document_ids,
        "duplicate_content_ids": duplicate_content_ids,
        "document_content_id_set_mismatch": len(set(document_ids) ^ set(content_ids)),
        "duplicate_chunk_ids": len(chunks) - len({row.get("chunk_id") for row in chunks}),
        **{key: counters[key] for key in AUDIT_COUNTER_KEYS},
    }
    gate_go = all(
        value is True if isinstance(value, bool) else value == 0 for value in gates.values()
    )

    by_source = {}
    for source_id in sorted(expected_source_ids):
        source_documents = [row for row in documents if row["source_id"] == source_id]
        source_chunks = [row for row in chunks if row.get("source_id") == source_id]
        source_dom = [row for row in source_chunks if row.get("offset_source") == "dom_text"]
        by_source[source_id] = {
            "documents": len(source_documents),
            "default_exposure_documents": sum(row["default_exposure"] for row in source_documents),
            "dom_chunks": len(source_dom),
            "visual_ocr_chunks": sum(
                row.get("offset_source") == "visual_ocr" for row in source_chunks
            ),
            "default_exposure_chunks": sum(row.get("default_exposure", False) for row in source_chunks),
            "char_length": _distribution([len(row["display_text"]) for row in source_dom]),
            "lexical_token_count": _distribution([row["token_count"] for row in source_dom]),
        }

    by_status = {}
    for status in sorted({row["status"] for row in documents}):
        status_documents = [row for row in documents if row["status"] == status]
        status_chunks = [row for row in chunks if row.get("status") == status]
        by_status[status] = {
            "documents": len(status_documents),
            "dom_chunks": sum(row.get("offset_source") == "dom_text" for row in status_chunks),
            "visual_ocr_chunks": sum(
                row.get("offset_source") == "visual_ocr" for row in status_chunks
            ),
            "default_exposure_chunks": sum(row.get("default_exposure", False) for row in status_chunks),
        }

    return {
        "summary": {
            "documents": len(documents),
            "contents": len(contents),
            "chunks": len(chunks),
            "dom_chunks": len(dom_chunks),
            "visual_ocr_chunks": len(visual_chunks),
            "visual_evidence_documents": len(expected_visual_parents),
            "default_exposure_documents": sum(row["default_exposure"] for row in documents),
            "default_exposure_chunks": sum(row.get("default_exposure", False) for row in chunks),
            "table_or_mixed_dom_chunks": sum(
                row.get("chunk_type") in {"table", "mixed"} for row in dom_chunks
            ),
            "heading_path_dom_chunks": sum(bool(row.get("heading_path")) for row in dom_chunks),
            "char_length": _distribution([len(row["display_text"]) for row in dom_chunks]),
            "lexical_token_count": _distribution([row["token_count"] for row in dom_chunks]),
            "document_status": dict(sorted(Counter(row["status"] for row in documents).items())),
            "chunk_type": dict(sorted(Counter(row["chunk_type"] for row in chunks).items())),
        },
        "by_source": by_source,
        "by_status": by_status,
        "gates": gates,
        "indexing_decision": "GO" if gate_go else "NO-GO",
    }


def _render_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DNF RAG v3 ChunkV3 corpus-wide audit",
        "",
        f"- chunker: `{report['chunker_version']}`",
        f"- built_at: `{report['built_at']}`",
        f"- indexing decision: **{report['indexing_decision']}**",
        "",
        "## 요약",
        "",
        "| documents | DOM chunks | visual OCR chunks | total chunks | default exposure chunks |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {summary['documents']} | {summary['dom_chunks']} | "
            f"{summary['visual_ocr_chunks']} | {summary['chunks']} | "
            f"{summary['default_exposure_chunks']} |"
        ),
        "",
        "## 출처별",
        "",
        "| source | documents | DOM chunks | visual OCR | char p50 | char p95 | char max |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for source_id, values in report["by_source"].items():
        chars = values["char_length"]
        lines.append(
            f"| `{source_id}` | {values['documents']} | {values['dom_chunks']} | "
            f"{values['visual_ocr_chunks']} | {chars['p50']} | {chars['p95']} | {chars['max']} |"
        )
    lines.extend(
        [
            "",
            "## 게이트",
            "",
            *[f"- {key}: `{value}`" for key, value in report["gates"].items()],
            "",
            "visual OCR chunk는 review_required이며 default exposure=false다.",
            "BM25, dense index, Router, 생성, 평가, 학습은 실행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_chunk_corpus(
    *,
    built_at: str,
    documents_path: Path,
    contents_path: Path,
    normalized_manifest_path: Path,
    pilot_manifest_path: Path,
    chunk_dir: Path,
    report_dir: Path,
    expected_document_count: int | None = None,
    expected_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    parse_fixed_timestamp(built_at)
    expected_source_ids = set(SOURCE_CONFIG) if expected_source_ids is None else expected_source_ids
    input_paths = [
        documents_path,
        contents_path,
        normalized_manifest_path,
        pilot_manifest_path,
    ]
    for path in input_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    input_hashes = {path: file_sha256(path) for path in input_paths}
    normalized_manifest = json.loads(normalized_manifest_path.read_text(encoding="utf-8"))
    manifest_document_count = normalized_manifest.get("documents", {}).get("row_count")
    if expected_document_count is None:
        if not isinstance(manifest_document_count, int):
            raise RuntimeError("Normalized manifest has no integer documents.row_count")
        expected_document_count = manifest_document_count
    elif manifest_document_count is not None and manifest_document_count != expected_document_count:
        raise RuntimeError("Expected document count differs from normalized manifest")
    documents = read_jsonl(documents_path)
    contents = read_jsonl(contents_path)
    documents_by_id = {row["document_id"]: row for row in documents}
    contents_by_id = {row["document_id"]: row for row in contents}
    if len(documents_by_id) != len(documents) or len(contents_by_id) != len(contents):
        raise RuntimeError("Duplicate document_id in normalized input")
    if set(documents_by_id) != set(contents_by_id):
        raise RuntimeError("Normalized document/content ID sets differ")
    actual_source_ids = {row["source_id"] for row in documents}
    if actual_source_ids != expected_source_ids:
        raise RuntimeError(
            f"Normalized source IDs differ from contract: {sorted(actual_source_ids)}"
        )

    all_documents = [{"document_id": document_id} for document_id in documents_by_id]
    chunks = build_chunks_for_selection(
        all_documents,
        documents_by_id,
        contents_by_id,
        chunker_version=CHUNKER_VERSION,
    )
    chunk_bytes = _serialize_jsonl(
        chunks,
        lambda row: (
            row["source_id"],
            row["parent_document_id"],
            row["offset_source"],
            row["start_offset"],
            row["chunk_id"],
        ),
    )
    chunk_sha256 = _sha256_bytes(chunk_bytes)
    chunk_path = chunk_dir / f"chunks_dnf_official_v3.1_{chunk_sha256}.jsonl"
    write_immutable(chunk_path, chunk_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "built_at": built_at,
        "inputs": [
            {
                "role": "normalized_documents",
                "path": documents_path.as_posix(),
                "sha256": input_hashes[documents_path],
                "row_count": len(documents),
            },
            {
                "role": "normalized_contents",
                "path": contents_path.as_posix(),
                "sha256": input_hashes[contents_path],
                "row_count": len(contents),
            },
            {
                "role": "normalized_manifest",
                "path": normalized_manifest_path.as_posix(),
                "sha256": input_hashes[normalized_manifest_path],
                "row_count": None,
            },
            {
                "role": "approved_chunk_pilot_manifest",
                "path": pilot_manifest_path.as_posix(),
                "sha256": input_hashes[pilot_manifest_path],
                "row_count": None,
            },
        ],
        "expected_document_count": expected_document_count,
        "expected_source_ids": sorted(expected_source_ids),
        "token_count_method": TOKEN_COUNT_METHOD,
        "minimum_multi_chunk_chars": MIN_MULTI_CHUNK_CHARS,
        "source_config": {
            key: {"max_chars": value[0], "overlap_chars": value[1]}
            for key, value in sorted(SOURCE_CONFIG.items())
            if key in expected_source_ids
        },
        "chunks": {
            "path": chunk_path.as_posix(),
            "sha256": chunk_sha256,
            "row_count": len(chunks),
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_path = chunk_dir / f"chunk_corpus_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    audit = audit_chunk_corpus(
        documents,
        contents,
        chunks,
        expected_document_count=expected_document_count,
        expected_source_ids=expected_source_ids,
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "built_at": built_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        **audit,
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = _sha256_bytes(report_bytes)
    report_json_path = report_dir / f"chunk_corpus_audit_{report_sha256}.json"
    report_markdown_path = report_dir / f"chunk_corpus_audit_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_markdown_path, _render_report(report).encode("utf-8"))

    for path, digest in input_hashes.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f"Input changed while building full ChunkV3 corpus: {path}")
    return {
        "chunk_path": chunk_path.as_posix(),
        "chunk_sha256": chunk_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_markdown_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": report["by_source"],
        "indexing_decision": report["indexing_decision"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and audit the complete deterministic offset-preserving ChunkV3 corpus."
    )
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--contents", type=Path, default=DEFAULT_CONTENTS)
    parser.add_argument("--normalized-manifest", type=Path, default=DEFAULT_NORMALIZED_MANIFEST)
    parser.add_argument("--pilot-manifest", type=Path, default=DEFAULT_PILOT_MANIFEST)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_chunk_corpus(
        built_at=args.built_at,
        documents_path=args.documents,
        contents_path=args.contents,
        normalized_manifest_path=args.normalized_manifest,
        pilot_manifest_path=args.pilot_manifest,
        chunk_dir=args.chunk_dir,
        report_dir=args.report_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
