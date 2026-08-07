from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)


CLEANER_VERSION = "retrieval-corpus-hygiene-v3.1.0"
MANIFEST_SCHEMA_VERSION = "retrieval-corpus-hygiene-manifest-v3.1"
AUDIT_SCHEMA_VERSION = "retrieval-corpus-hygiene-audit-v3.1"
DUPLICATE_SCHEMA_VERSION = "retrieval-corpus-duplicate-parent-v3.1"

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)

_NUMBERED_HEADING = re.compile(r"^\d+\.\s+\S")
_TITLE_KEY = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)
_SHOP_NAV_MARKERS = frozenset({"제목", "삭제", "판매중", "종료"})
_PAGER_MARKERS = frozenset({"FIRST", "PREV", "NEXT", "END"})
_TARGET_DUPLICATE_SOURCES = frozenset(
    {"dnf_event", "dnf_seria_shop", "dnf_monthly_item"}
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _strip_policy_selector_and_toc(
    lines: list[str],
) -> tuple[list[str], list[str], list[str]]:
    stripped = [line.strip() for line in lines]
    try:
        selector_start = stripped.index("시행일자")
        print_index = stripped.index("인쇄", selector_start + 1)
    except ValueError:
        return lines, [], []

    first_heading = next(
        (
            index
            for index in range(print_index + 1, len(lines))
            if _NUMBERED_HEADING.match(stripped[index])
        ),
        None,
    )
    if first_heading is None:
        return lines, [], ["policy_selector_without_toc_heading"]
    repeated_heading = next(
        (
            index
            for index in range(first_heading + 1, len(lines))
            if stripped[index] == stripped[first_heading]
        ),
        None,
    )
    if repeated_heading is None:
        return lines, [], ["policy_toc_without_repeated_body_heading"]
    return (
        lines[:selector_start] + lines[repeated_heading:],
        ["policy_revision_selector", "policy_table_of_contents"],
        [],
    )


def _strip_trailing_footer(
    lines: list[str],
) -> tuple[list[str], list[str], dict[str, int]]:
    stripped = [line.strip() for line in lines]
    footer_start = next(
        (
            index
            for index in range(len(lines) - 1)
            if stripped[index] == "텍스트복사" and stripped[index + 1] == "목록"
        ),
        None,
    )
    if footer_start is None:
        return lines, [], {}

    removed = stripped[footer_start:]
    types = ["textcopy_list_footer"]
    counters: dict[str, int] = {}
    if _SHOP_NAV_MARKERS.issubset(set(removed)):
        types.append("shop_or_monthly_listing_tail")
    if _PAGER_MARKERS.issubset(set(removed)):
        types.append("pagination_tail")

    cut = footer_start
    if cut and stripped[cut - 1].startswith("[IMAGE_ALT]") and "피싱방지" in stripped[
        cut - 1
    ]:
        cut -= 1
        types.append("known_phishing_banner_alt")
        counters["known_banner_lines_removed"] = 1
    counters["footer_lines_removed"] = len(lines) - cut
    return lines[:cut], types, counters


def clean_retrieval_text(
    text: str, *, source_id: str
) -> tuple[str, list[str], list[str], dict[str, int]]:
    lines = text.splitlines()
    types: list[str] = []
    warnings: list[str] = []
    counters: Counter[str] = Counter()

    if source_id == "dnf_account_policy":
        lines, policy_types, policy_warnings = _strip_policy_selector_and_toc(lines)
        types.extend(policy_types)
        warnings.extend(policy_warnings)

    lines, footer_types, footer_counts = _strip_trailing_footer(lines)
    types.extend(footer_types)
    counters.update(footer_counts)

    while lines and not lines[-1].strip():
        lines.pop()
    cleaned = "\n".join(lines)
    return cleaned, sorted(set(types)), sorted(set(warnings)), dict(counters)


def clean_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    removed_chars = 0

    for row in rows:
        cleaned_text, types, warnings, counters = clean_retrieval_text(
            row["retrieval_text"], source_id=row["source_id"]
        )
        if not cleaned_text.strip():
            raise RuntimeError(f"Cleaning removed the full retrieval text: {row['chunk_id']}")
        cleaned = {**row, "retrieval_text": cleaned_text}
        output.append(cleaned)
        if cleaned_text != row["retrieval_text"]:
            removed = len(row["retrieval_text"]) - len(cleaned_text)
            if removed <= 0:
                raise RuntimeError("Retrieval hygiene may remove text only")
            removed_chars += removed
            source_counts[row["source_id"]] += 1
            type_counts.update(types)
            warning_counts.update(warnings)
            audit.append(
                {
                    "audit_schema_version": AUDIT_SCHEMA_VERSION,
                    "chunk_id": row["chunk_id"],
                    "parent_document_id": row["parent_document_id"],
                    "source_id": row["source_id"],
                    "contamination_types": types,
                    "before_retrieval_text_sha256": _sha256_bytes(
                        row["retrieval_text"].encode("utf-8")
                    ),
                    "after_retrieval_text_sha256": _sha256_bytes(
                        cleaned_text.encode("utf-8")
                    ),
                    "before_chars": len(row["retrieval_text"]),
                    "after_chars": len(cleaned_text),
                    "removed_chars": removed,
                    "warnings": warnings,
                    "counters": counters,
                }
            )

    return (
        output,
        sorted(audit, key=lambda row: row["chunk_id"]),
        {
            "input_rows": len(rows),
            "output_rows": len(output),
            "modified_unique_chunks": len(audit),
            "removed_characters": removed_chars,
            "contamination_type_counts": dict(sorted(type_counts.items())),
            "modified_chunks_by_source": dict(sorted(source_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "pure_navigation_chunks_excluded": 0,
        },
    )


def _non_retrieval_hash(row: dict[str, Any]) -> str:
    return _sha256_bytes(
        _canonical_json_bytes({key: value for key, value in row.items() if key != "retrieval_text"})
    )


def audit_integrity(
    dirty_rows: list[dict[str, Any]],
    clean_rows_: list[dict[str, Any]],
    evaluation_sets: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    dirty = {row["chunk_id"]: row for row in dirty_rows}
    clean = {row["chunk_id"]: row for row in clean_rows_}
    if set(dirty) != set(clean):
        raise RuntimeError("Chunk IDs changed during retrieval-only cleaning")

    protected_fields = (
        "chunk_id",
        "parent_document_id",
        "display_text",
        "start_offset",
        "end_offset",
        "normalized_text_hash",
        "parent_content_hash",
        "source_id",
        "source_kind",
        "status",
        "default_exposure",
    )
    changed_fields: Counter[str] = Counter()
    non_retrieval_hash_mismatches = 0
    for chunk_id, before in dirty.items():
        after = clean[chunk_id]
        for field in protected_fields:
            if before[field] != after[field]:
                changed_fields[field] += 1
        non_retrieval_hash_mismatches += _non_retrieval_hash(before) != _non_retrieval_hash(
            after
        )

    set_metrics = {}
    lost_exact_examples = []
    for name, questions in evaluation_sets.items():
        groups = 0
        dirty_display_exact = 0
        clean_display_exact = 0
        dirty_retrieval_exact = 0
        clean_retrieval_exact = 0
        for question in questions:
            for group in question.get("evidence_groups", []):
                groups += 1
                span = group.get("evidence_span", "")
                acceptable = [
                    chunk_id
                    for chunk_id in group.get("acceptable_chunk_ids", [])
                    if chunk_id in dirty
                ]
                dirty_display = any(span in dirty[cid]["display_text"] for cid in acceptable)
                clean_display = any(span in clean[cid]["display_text"] for cid in acceptable)
                dirty_retrieval = any(
                    span in dirty[cid]["retrieval_text"] for cid in acceptable
                )
                clean_retrieval = any(
                    span in clean[cid]["retrieval_text"] for cid in acceptable
                )
                dirty_display_exact += dirty_display
                clean_display_exact += clean_display
                dirty_retrieval_exact += dirty_retrieval
                clean_retrieval_exact += clean_retrieval
                if (dirty_display and not clean_display) or (
                    dirty_retrieval and not clean_retrieval
                ):
                    lost_exact_examples.append(
                        {"evaluation_set": name, "case_id": question["dev_id"], "group_id": group["group_id"]}
                    )
        set_metrics[name] = {
            "evidence_groups": groups,
            "dirty_display_exact": dirty_display_exact,
            "clean_display_exact": clean_display_exact,
            "dirty_retrieval_exact": dirty_retrieval_exact,
            "clean_retrieval_exact": clean_retrieval_exact,
            "preexisting_nonexact_evidence_spans": groups - dirty_display_exact,
            "new_exact_span_losses": dirty_display_exact - clean_display_exact,
            "new_retrieval_exact_span_losses": dirty_retrieval_exact
            - clean_retrieval_exact,
        }

    result = {
        "chunk_ids_preserved": len(dirty) == len(clean) == len(dirty_rows) == len(clean_rows_),
        "row_order_preserved": [row["chunk_id"] for row in dirty_rows]
        == [row["chunk_id"] for row in clean_rows_],
        "protected_field_change_counts": dict(sorted(changed_fields.items())),
        "non_retrieval_row_hash_mismatches": non_retrieval_hash_mismatches,
        "gold_acceptable_chunk_ids_missing": sum(
            1
            for questions in evaluation_sets.values()
            for question in questions
            for group in question.get("evidence_groups", [])
            for chunk_id in group.get("acceptable_chunk_ids", [])
            if chunk_id not in clean
        ),
        "evaluation_sets": set_metrics,
        "lost_exact_examples": lost_exact_examples,
    }
    result["pass"] = (
        result["chunk_ids_preserved"]
        and result["row_order_preserved"]
        and not changed_fields
        and non_retrieval_hash_mismatches == 0
        and result["gold_acceptable_chunk_ids_missing"] == 0
        and not lost_exact_examples
    )
    return result


def duplicate_parent_relations(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [row for row in documents if row["source_id"] in _TARGET_DUPLICATE_SOURCES]
    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        key = _TITLE_KEY.sub("", row.get("title", "").lower())
        if key:
            by_title[key].append(row)

    output = []
    for key, rows in sorted(by_title.items()):
        source_ids = {row["source_id"] for row in rows}
        if len(rows) < 2 or len(source_ids) < 2:
            continue
        output.append(
            {
                "duplicate_schema_version": DUPLICATE_SCHEMA_VERSION,
                "relation_kind": "cross_source_normalized_title_candidate",
                "normalized_title_key": key,
                "parent_documents": [
                    {
                        "parent_document_id": row["document_id"],
                        "source_id": row["source_id"],
                        "canonical_url": row["canonical_url"],
                        "title": row["title"],
                        "content_hash": row["content_hash"],
                    }
                    for row in sorted(rows, key=lambda item: item["document_id"])
                ],
                "used_for_deduplication": False,
            }
        )
    return output


def build_and_freeze(
    root: Path,
    *,
    chunks_path: Path,
    documents_path: Path,
    dev_path: Path,
    canary_path: Path,
    built_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "dirty_chunks": chunks_path.resolve(),
        "documents": documents_path.resolve(),
        "adaptive_dev_63": dev_path.resolve(),
        "downgraded_canary_32": canary_path.resolve(),
        "cleaner_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in input_paths.items()}
    dirty_rows = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    evaluations = {
        "adaptive_dev_63": read_jsonl(dev_path),
        "downgraded_canary_32": read_jsonl(canary_path),
    }
    cleaned_rows, audit_rows, cleaning = clean_rows(dirty_rows)
    integrity = audit_integrity(dirty_rows, cleaned_rows, evaluations)
    if not integrity["pass"]:
        raise RuntimeError("Retrieval corpus hygiene integrity gate failed")
    duplicates = duplicate_parent_relations(documents)

    chunks_dir = root / "data/v3/chunks"
    clean_bytes = _serialize_jsonl(cleaned_rows, lambda row: row["chunk_id"])
    clean_sha = _sha256_bytes(clean_bytes)
    clean_path = chunks_dir / f"chunks_dnf_official_retrieval_clean_v3.1_{clean_sha}.jsonl"
    write_immutable(clean_path, clean_bytes)

    audit_bytes = _serialize_jsonl(audit_rows, lambda row: row["chunk_id"])
    audit_sha = _sha256_bytes(audit_bytes)
    audit_path = chunks_dir / f"retrieval_cleaning_audit_{audit_sha}.jsonl"
    write_immutable(audit_path, audit_bytes)

    duplicate_bytes = _serialize_jsonl(
        duplicates, lambda row: (row["normalized_title_key"], row["relation_kind"])
    )
    duplicate_sha = _sha256_bytes(duplicate_bytes)
    duplicate_path = chunks_dir / f"duplicate_parent_relations_{duplicate_sha}.jsonl"
    write_immutable(duplicate_path, duplicate_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "cleaner_version": CLEANER_VERSION,
        "built_at": built_at,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in input_paths.items()
        },
        "contract": {
            "only_retrieval_text_may_change": True,
            "display_text_chunk_id_parent_id_offsets_preserved": True,
            "pure_navigation_chunks_excluded": False,
            "reason_no_exclusion": "all contaminated chunks retain substantive body text after suffix or selector removal",
            "gold_content_changed": False,
            "gold_id_remap_count": 0,
            "search_model_or_pipeline_changed": False,
        },
        "cleaning": cleaning,
        "integrity": integrity,
        "duplicate_parent_relation_candidates": {
            "row_count": len(duplicates),
            "path": _relative(root, duplicate_path),
            "sha256": duplicate_sha,
            "applied_to_runtime": False,
        },
        "artifacts": {
            "clean_chunks": {
                "path": _relative(root, clean_path),
                "sha256": clean_sha,
                "row_count": len(cleaned_rows),
            },
            "cleaning_audit": {
                "path": _relative(root, audit_path),
                "sha256": audit_sha,
                "row_count": len(audit_rows),
            },
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = chunks_dir / f"retrieval_clean_corpus_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != before[name]:
            raise RuntimeError(f"Input changed during retrieval hygiene build: {name}")
    return {
        "clean_chunks_path": str(clean_path),
        "clean_chunks_sha256": clean_sha,
        "cleaning_audit_path": str(audit_path),
        "cleaning_audit_sha256": audit_sha,
        "duplicate_relations_path": str(duplicate_path),
        "duplicate_relations_sha256": duplicate_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "cleaning": cleaning,
        "integrity": integrity,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Remove measured navigation contaminants from retrieval_text only"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--dev", type=Path, default=root / DEFAULT_DEV)
    parser.add_argument("--canary", type=Path, default=root / DEFAULT_CANARY)
    parser.add_argument(
        "--built-at", default=datetime.now(timezone.utc).isoformat(), help="ISO-8601"
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root,
        chunks_path=args.chunks,
        documents_path=args.documents,
        dev_path=args.dev,
        canary_path=args.canary,
        built_at=args.built_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
