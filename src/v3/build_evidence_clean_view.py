from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "evidence-clean-view-v3.2-arm2.0"
VIEW_SCHEMA_VERSION = "evidence-clean-view-v3.2"
MANIFEST_SCHEMA_VERSION = "evidence-clean-view-manifest-v3.2"
_NUMBERED_HEADING = re.compile(r"^\d+\.\s+\S")

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/v3/evidence")
DEFAULT_CONTRACT = Path("docs/v3/evidence_clean_view_arm2.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _line_records(text: str) -> list[dict[str, Any]]:
    output = []
    cursor = 0
    for raw in text.splitlines(keepends=True):
        end = cursor + len(raw)
        output.append(
            {"start": cursor, "end": end, "stripped": raw.strip()}
        )
        cursor = end
    if cursor < len(text):
        output.append(
            {"start": cursor, "end": len(text), "stripped": text[cursor:].strip()}
        )
    return output


def _policy_exclusion(lines: list[dict[str, Any]]) -> tuple[int, int] | None:
    stripped = [row["stripped"] for row in lines]
    try:
        selector_start = stripped.index("시행일자")
        print_index = stripped.index("인쇄", selector_start + 1)
    except ValueError:
        return None
    first_heading = next(
        (
            index
            for index in range(print_index + 1, len(lines))
            if _NUMBERED_HEADING.match(stripped[index])
        ),
        None,
    )
    if first_heading is None:
        return None
    repeated_heading = next(
        (
            index
            for index in range(first_heading + 1, len(lines))
            if stripped[index] == stripped[first_heading]
        ),
        None,
    )
    if repeated_heading is None:
        return None
    return lines[selector_start]["start"], lines[repeated_heading]["start"]


def _footer_exclusion(lines: list[dict[str, Any]], text_length: int) -> tuple[int, int] | None:
    footer_index = next(
        (
            index
            for index in range(len(lines) - 1)
            if lines[index]["stripped"] == "텍스트복사"
            and lines[index + 1]["stripped"] == "목록"
        ),
        None,
    )
    if footer_index is None:
        return None
    if (
        footer_index > 0
        and lines[footer_index - 1]["stripped"].startswith("[IMAGE_ALT]")
        and "피싱방지" in lines[footer_index - 1]["stripped"]
    ):
        footer_index -= 1
    return lines[footer_index]["start"], text_length


def _merge_exclusions(
    ranges: list[tuple[int, int, str]], text_length: int
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for start, end, reason in sorted(ranges):
        if not (0 <= start < end <= text_length):
            raise RuntimeError(f"Invalid excluded range: {start}:{end}")
        if merged and start <= merged[-1]["end_offset"]:
            merged[-1]["end_offset"] = max(merged[-1]["end_offset"], end)
            merged[-1]["reasons"] = sorted(
                set([*merged[-1]["reasons"], reason])
            )
            continue
        merged.append(
            {
                "start_offset": start,
                "end_offset": end,
                "reasons": [reason],
            }
        )
    return merged


def build_evidence_view(chunk: dict[str, Any]) -> dict[str, Any] | None:
    original = chunk["display_text"]
    lines = _line_records(original)
    exclusions: list[tuple[int, int, str]] = []
    if chunk["source_id"] == "dnf_account_policy":
        policy = _policy_exclusion(lines)
        if policy is not None:
            exclusions.append((*policy, "policy_revision_selector_and_toc"))
    footer = _footer_exclusion(lines, len(original))
    if footer is not None:
        exclusions.append((*footer, "navigation_footer_or_listing_tail"))
    merged = _merge_exclusions(exclusions, len(original))
    if not merged:
        return None

    included = []
    cursor = 0
    clean_cursor = 0
    clean_parts = []
    for excluded in merged:
        if cursor < excluded["start_offset"]:
            start, end = cursor, excluded["start_offset"]
            value = original[start:end]
            clean_parts.append(value)
            included.append(
                {
                    "clean_start_offset": clean_cursor,
                    "clean_end_offset": clean_cursor + len(value),
                    "original_start_offset": start,
                    "original_end_offset": end,
                }
            )
            clean_cursor += len(value)
        cursor = excluded["end_offset"]
    if cursor < len(original):
        value = original[cursor:]
        clean_parts.append(value)
        included.append(
            {
                "clean_start_offset": clean_cursor,
                "clean_end_offset": clean_cursor + len(value),
                "original_start_offset": cursor,
                "original_end_offset": len(original),
            }
        )
    evidence_text = "".join(clean_parts)
    for mapping in included:
        clean_slice = evidence_text[
            mapping["clean_start_offset"] : mapping["clean_end_offset"]
        ]
        original_slice = original[
            mapping["original_start_offset"] : mapping["original_end_offset"]
        ]
        if clean_slice != original_slice:
            raise RuntimeError(f"Offset map mismatch: {chunk['chunk_id']}")
    return {
        "view_schema_version": VIEW_SCHEMA_VERSION,
        "chunk_id": chunk["chunk_id"],
        "parent_document_id": chunk["parent_document_id"],
        "source_id": chunk["source_id"],
        "original_display_text_sha256": _sha256_bytes(original.encode("utf-8")),
        "evidence_text_clean": evidence_text,
        "evidence_text_clean_sha256": _sha256_bytes(evidence_text.encode("utf-8")),
        "evidence_to_original_offset_map": included,
        "excluded_ranges": merged,
        "removed_character_count": sum(
            row["end_offset"] - row["start_offset"] for row in merged
        ),
        "fully_excluded_from_evidence": not bool(evidence_text.strip()),
    }


def span_is_eligible(
    view: dict[str, Any] | None, *, start_offset: int, end_offset: int
) -> bool:
    if view is None:
        return True
    return any(
        start_offset >= row["original_start_offset"]
        and end_offset <= row["original_end_offset"]
        for row in view["evidence_to_original_offset_map"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offset-preserving evidence clean views")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    resolve = lambda value: value if value.is_absolute() else root / value
    chunks_path = resolve(args.chunks)
    contract_path = resolve(args.contract)
    chunks = read_jsonl(chunks_path)
    views = [view for chunk in chunks if (view := build_evidence_view(chunk))]
    payload = _serialize_jsonl(views, lambda row: row["chunk_id"])
    artifact_sha = _sha256_bytes(payload)
    output_dir = resolve(args.output_dir)
    artifact_path = output_dir / f"evidence_clean_view_v3.2_{artifact_sha}.jsonl"
    write_immutable(artifact_path, payload)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {
            "chunks": {"path": args.chunks.as_posix(), "sha256": file_sha256(chunks_path)},
            "contract": {"path": args.contract.as_posix(), "sha256": file_sha256(contract_path)},
            "builder_source": {
                "path": Path(__file__).resolve().relative_to(root).as_posix(),
                "sha256": file_sha256(Path(__file__).resolve()),
            },
        },
        "artifact": {
            "path": artifact_path.relative_to(root).as_posix(),
            "sha256": artifact_sha,
            "modified_chunk_count": len(views),
            "removed_character_count": sum(row["removed_character_count"] for row in views),
            "fully_excluded_chunk_count": sum(
                row["fully_excluded_from_evidence"] for row in views
            ),
            "offset_map_mismatch_count": 0,
        },
        "scope": {
            "dirty_canonical_changed": False,
            "retrieval_ranking_changed": False,
            "gold_changed": False,
            "citation_offsets_changed": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"evidence_clean_view_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"artifact": artifact_path.relative_to(root).as_posix(), "manifest": manifest_path.relative_to(root).as_posix(), "audit": manifest["artifact"]}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
