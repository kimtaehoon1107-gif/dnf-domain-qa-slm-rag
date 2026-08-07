from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from src.io_utils import read_jsonl
from src.v3.schemas import CHUNK_REQUIRED_FIELDS, DOCUMENT_REQUIRED_FIELDS


DEFAULT_GUIDE_DOCS = Path("data/raw/guide_docs.jsonl")
DEFAULT_OFFICIAL_DOCS = Path("data/raw/official_docs.jsonl")
DEFAULT_CHUNKS = Path("data/processed/domain_doc_chunks.jsonl")
DEFAULT_JSON_OUTPUT = Path("reports/v3/corpus_audit_v2_baseline.json")
DEFAULT_MARKDOWN_OUTPUT = Path("reports/v3/corpus_audit_v2_baseline.md")


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _category(row: dict[str, Any]) -> str:
    metadata = _metadata(row)
    if row.get("doc_type") == "game_guide":
        return normalize_text(metadata.get("guide_category"))
    return normalize_text(metadata.get("category"))


def _source_kind(row: dict[str, Any]) -> str:
    doc_type = normalize_text(row.get("doc_type"))
    mapped_doc_type = {
        "game_guide": "game_guide",
        "patch_note": "patch_note",
        "event": "event",
        "notice": "notice",
        "account_payment": "account_policy",
        "bug_known_issue": "known_issue",
    }.get(doc_type)
    if mapped_doc_type:
        return mapped_doc_type
    section = normalize_text(_metadata(row).get("official_section"))
    return {
        "update": "patch_note",
        "event": "event",
        "notice": "notice",
    }.get(section, doc_type or section or "unknown")


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return bool(value)
    return True


def _duplicate_groups(
    rows: Iterable[dict[str, Any]],
    *,
    value_key: str,
    id_key: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        value = normalize_text(row.get(value_key))
        if value:
            groups[value].append(str(row.get(id_key) or "<missing-id>"))
    duplicates = [
        {
            "normalized_value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "row_count": len(row_ids),
            "row_ids": sorted(row_ids),
        }
        for value, row_ids in groups.items()
        if len(row_ids) > 1
    ]
    return sorted(duplicates, key=lambda item: (-item["row_count"], item["row_ids"]))


def _field_presence(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, int]:
    return {
        field: sum(1 for row in rows if field in row and _nonempty(row.get(field)))
        for field in fields
    }


def _distribution(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": min(values),
        "median": round(float(median(values)), 1),
        "max": max(values),
    }


def audit_rows(
    guide_docs: list[dict[str, Any]],
    official_docs: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    documents = [*guide_docs, *official_docs]
    document_ids = {str(row.get("doc_id")) for row in documents if row.get("doc_id")}
    chunk_lengths = [len(normalize_text(row.get("text"))) for row in chunks]
    chunks_per_parent = Counter(
        str(row.get("parent_doc_id")) for row in chunks if row.get("parent_doc_id")
    )
    duplicate_document_text = _duplicate_groups(documents, value_key="text", id_key="doc_id")
    duplicate_chunk_text = _duplicate_groups(chunks, value_key="text", id_key="doc_id")

    source_kind_counts = Counter(_source_kind(row) for row in documents)
    doc_type_counts = Counter(normalize_text(row.get("doc_type")) or "unknown" for row in documents)
    official_section_counts = Counter(
        normalize_text(_metadata(row).get("official_section")) or "unknown" for row in official_docs
    )
    missing_parent = [str(row.get("doc_id") or "<missing-id>") for row in chunks if not row.get("parent_doc_id")]
    orphan_chunks = [
        str(row.get("doc_id") or "<missing-id>")
        for row in chunks
        if row.get("parent_doc_id") and str(row["parent_doc_id"]) not in document_ids
    ]

    guide_category_missing = sum(1 for row in guide_docs if not _category(row))
    guide_updated_at_missing = sum(
        1 for row in guide_docs if not _nonempty(_metadata(row).get("guide_updated_at"))
    )
    document_category_missing = sum(1 for row in documents if not _category(row))
    document_published_at_missing = sum(1 for row in documents if not _nonempty(row.get("published_at")))
    documents_with_validity = sum(
        1 for row in documents if _nonempty(row.get("effective_start")) or _nonempty(row.get("effective_end"))
    )

    issues: list[dict[str, Any]] = []

    def add_issue(severity: str, check: str, count: int | None, detail: str) -> None:
        issues.append({"severity": severity, "check": check, "count": count, "detail": detail})

    add_issue(
        "not_measured",
        "source_discovery_coverage",
        None,
        "수집 시점의 공식 사이트 URL 발견 목록이 없어 사이트 전체 대비 수집률을 계산할 수 없음",
    )
    if document_category_missing:
        add_issue("warning", "missing_document_category", document_category_missing, "문서 유형별 category_path 보강 필요")
    if guide_updated_at_missing:
        add_issue("warning", "missing_guide_updated_at", guide_updated_at_missing, "가이드 revision 판정에 필요한 갱신일 누락")
    if documents_with_validity < len(documents):
        add_issue(
            "warning",
            "missing_validity",
            len(documents) - documents_with_validity,
            "valid_from/valid_to/status를 문서 유형별로 판정해야 함",
        )
    if duplicate_chunk_text:
        add_issue(
            "warning",
            "duplicate_chunk_text",
            sum(item["row_count"] for item in duplicate_chunk_text),
            "동일 normalized text 청크가 여러 ID로 존재함",
        )
    short_chunks = sum(length < 200 for length in chunk_lengths)
    if short_chunks:
        add_issue("warning", "short_chunks_under_200", short_chunks, "고립 여부와 형제 병합 가능성 검토 필요")
    missing_offsets = sum(
        1 for row in chunks if not isinstance(row.get("start_offset"), int) or not isinstance(row.get("end_offset"), int)
    )
    if missing_offsets:
        add_issue("error", "missing_chunk_offsets", missing_offsets, "원문 위치 역추적 불가")
    if missing_parent:
        add_issue("error", "missing_parent_doc_id", len(missing_parent), "청크-부모 관계 누락")
    if orphan_chunks:
        add_issue("error", "orphan_chunks", len(orphan_chunks), "입력 원본에서 부모 문서를 찾을 수 없음")

    return {
        "audit_version": "dnf_corpus_audit_v3.0",
        "scope": "local_v2_artifacts_read_only",
        "documents": {
            "total": len(documents),
            "guide_rows": len(guide_docs),
            "official_rows": len(official_docs),
            "source_kind_counts": dict(sorted(source_kind_counts.items())),
            "legacy_doc_type_counts": dict(sorted(doc_type_counts.items())),
            "official_section_counts": dict(sorted(official_section_counts.items())),
            "unique_document_ids": len(document_ids),
            "missing_title": sum(1 for row in documents if not normalize_text(row.get("title"))),
            "missing_published_at": document_published_at_missing,
            "missing_category": document_category_missing,
            "guide_missing_category": guide_category_missing,
            "guide_missing_updated_at": guide_updated_at_missing,
            "with_any_validity_range": documents_with_validity,
            "duplicate_text_group_count": len(duplicate_document_text),
            "duplicate_text_row_count": sum(item["row_count"] for item in duplicate_document_text),
            "duplicate_text_groups": duplicate_document_text,
            "v3_direct_field_presence": _field_presence(documents, DOCUMENT_REQUIRED_FIELDS),
        },
        "chunks": {
            "total": len(chunks),
            "unique_chunk_ids": len({str(row.get("doc_id")) for row in chunks if row.get("doc_id")}),
            "parents_represented": len(chunks_per_parent),
            "characters": _distribution(chunk_lengths),
            "under_100_characters": sum(length < 100 for length in chunk_lengths),
            "under_200_characters": short_chunks,
            "empty_text": sum(length == 0 for length in chunk_lengths),
            "chunks_per_parent": _distribution(list(chunks_per_parent.values())),
            "missing_parent_doc_id": len(missing_parent),
            "missing_parent_doc_id_examples": missing_parent[:20],
            "orphan_chunk_count": len(orphan_chunks),
            "orphan_chunk_examples": orphan_chunks[:20],
            "with_valid_offsets": len(chunks) - missing_offsets,
            "duplicate_text_group_count": len(duplicate_chunk_text),
            "duplicate_text_row_count": sum(item["row_count"] for item in duplicate_chunk_text),
            "duplicate_text_groups": duplicate_chunk_text,
            "v3_direct_field_presence": _field_presence(chunks, CHUNK_REQUIRED_FIELDS),
        },
        "issues": issues,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_files(guide_docs_path: Path, official_docs_path: Path, chunks_path: Path) -> dict[str, Any]:
    inputs = [guide_docs_path, official_docs_path, chunks_path]
    for path in inputs:
        if not path.is_file():
            raise RuntimeError(f"Required corpus artifact does not exist: {path}")
    report = audit_rows(
        read_jsonl(guide_docs_path),
        read_jsonl(official_docs_path),
        read_jsonl(chunks_path),
    )
    report["input_artifacts"] = [
        {"path": path.as_posix(), "sha256": file_sha256(path)} for path in inputs
    ]
    return report


def render_markdown(report: dict[str, Any]) -> str:
    documents = report["documents"]
    chunks = report["chunks"]
    lines = [
        "# DNF RAG v3 코퍼스 감사 — v2 기준선",
        "",
        "> v2 원본과 canonical 청크를 읽기 전용으로 감사한 결과다. 이 보고서는 v3 코퍼스 변환 결과가 아니다.",
        "",
        "## 입력 artifact",
        "",
        "| 경로 | SHA-256 |",
        "|---|---|",
    ]
    for item in report.get("input_artifacts", []):
        lines.append(f"| `{item['path']}` | `{item['sha256']}` |")
    lines.extend(
        [
            "",
            "## 핵심 통계",
            "",
            "| 항목 | 값 |",
            "|---|---:|",
            f"| 부모 문서 | {documents['total']} |",
            f"| 게임 가이드 문서 | {documents['source_kind_counts'].get('game_guide', 0)} |",
            f"| 패치노트 문서 | {documents['source_kind_counts'].get('patch_note', 0)} |",
            f"| 이벤트 문서 | {documents['source_kind_counts'].get('event', 0)} |",
            f"| 공지 문서 | {documents['source_kind_counts'].get('notice', 0)} |",
            f"| 계정·결제 정책 문서 | {documents['source_kind_counts'].get('account_policy', 0)} |",
            f"| 알려진 문제 문서 | {documents['source_kind_counts'].get('known_issue', 0)} |",
            f"| 청크 | {chunks['total']} |",
            f"| 청크 길이 중앙값 | {chunks['characters']['median']}자 |",
            f"| 100자 미만 청크 | {chunks['under_100_characters']} |",
            f"| 200자 미만 청크 | {chunks['under_200_characters']} |",
            f"| 동일 텍스트 청크 그룹 | {chunks['duplicate_text_group_count']} |",
            f"| 동일 텍스트 그룹 소속 청크 | {chunks['duplicate_text_row_count']} |",
            f"| 원문 offset 보유 청크 | {chunks['with_valid_offsets']} / {chunks['total']} |",
            f"| orphan 청크 | {chunks['orphan_chunk_count']} |",
            "",
            "## 문서 메타데이터",
            "",
            f"- category 누락: {documents['missing_category']} / {documents['total']}",
            f"- 가이드 category 누락: {documents['guide_missing_category']} / {documents['guide_rows']}",
            f"- 가이드 갱신일 누락: {documents['guide_missing_updated_at']} / {documents['guide_rows']}",
            f"- 유효기간 필드가 하나라도 있는 문서: {documents['with_any_validity_range']} / {documents['total']}",
            "",
            "## 발견된 문제",
            "",
            "| 심각도 | 검사 | 건수 | 설명 |",
            "|---|---|---:|---|",
        ]
    )
    for issue in report["issues"]:
        count = "측정 불가" if issue["count"] is None else str(issue["count"])
        lines.append(f"| {issue['severity']} | `{issue['check']}` | {count} | {issue['detail']} |")
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "- v2 artifact는 기준선 비교용으로 유지하며 이 입력 파일들을 수정하지 않는다.",
            "- 첫 v3 변환은 snapshot/revision/hash를 먼저 만들고, 그 뒤 문서 유형별 parser와 chunker를 적용한다.",
            "- 사이트 전체 대비 수집률은 URL discovery snapshot이 생기기 전에는 정직하게 측정 불가로 둔다.",
            "- Router, Evidence Selector, 학습은 corpus 및 independent BM25 후보 recall이 검증된 뒤 진행한다.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit v2 DNF corpus artifacts without mutating them.")
    parser.add_argument("--guide-docs", type=Path, default=DEFAULT_GUIDE_DOCS)
    parser.add_argument("--official-docs", type=Path, default=DEFAULT_OFFICIAL_DOCS)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = audit_files(args.guide_docs, args.official_docs, args.chunks)
    write_report(args.json_output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_report(args.markdown_output, render_markdown(report))
    print(
        json.dumps(
            {
                "json_output": str(args.json_output),
                "markdown_output": str(args.markdown_output),
                "documents": report["documents"]["total"],
                "chunks": report["chunks"]["total"],
                "issues": len(report["issues"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
