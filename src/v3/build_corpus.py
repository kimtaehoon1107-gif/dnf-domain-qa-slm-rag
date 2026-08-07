from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.io_utils import read_jsonl
from src.v3.schemas import CORPUS_MANIFEST_SCHEMA_VERSION, CorpusManifestV3, DocumentV3


DEFAULT_GUIDE_DOCS = Path("data/raw/guide_docs.jsonl")
DEFAULT_OFFICIAL_DOCS = Path("data/raw/official_docs.jsonl")
DEFAULT_SNAPSHOT_DIR = Path("data/v3/raw_snapshots")
DEFAULT_NORMALIZED_DIR = Path("data/v3/normalized")

SNAPSHOTTER_VERSION = "dnf_raw_snapshot_v3.0"
DOCUMENT_PARSER_VERSION = "dnf_v2_raw_normalizer_v3.0"
GUIDE_SOURCE_PARSER_VERSION = "collect_guide_selenium.legacy-v2-unversioned"
OFFICIAL_SOURCE_PARSER_VERSION = "collect_official_docs.legacy-v2-unversioned"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    path: Path
    parser_version: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_immutable_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError(f"Refusing to overwrite immutable artifact with different content: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise RuntimeError(f"Immutable artifact was created concurrently with different content: {path}")


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def _nullable_string(value: Any) -> str | None:
    normalized = _normalize_space(value)
    return normalized or None


def canonicalize_url(value: Any) -> str:
    raw_url = str(value or "").strip()
    parsed = urlsplit(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Document has no canonicalizable HTTP(S) source URL: {raw_url!r}")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def source_kind(row: dict[str, Any]) -> str:
    doc_type = _normalize_space(row.get("doc_type"))
    mapped = {
        "game_guide": "game_guide",
        "patch_note": "patch_note",
        "event": "event",
        "notice": "notice",
        "account_payment": "account_policy",
        "bug_known_issue": "known_issue",
    }.get(doc_type)
    if mapped:
        return mapped
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    section = _normalize_space(metadata.get("official_section"))
    return {
        "guide": "game_guide",
        "update": "patch_note",
        "event": "event",
        "notice": "notice",
    }.get(section, doc_type or section or "unknown")


def category_path(row: dict[str, Any]) -> list[str]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    section = _normalize_space(metadata.get("official_section"))
    leaf_key = "guide_category" if row.get("doc_type") == "game_guide" else "category"
    leaf = _normalize_space(metadata.get(leaf_key))
    result: list[str] = []
    for value in (section, leaf):
        if value and value not in result:
            result.append(value)
    return result or [source_kind(row)]


def stable_content_hash(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    stable_metadata = {key: value for key, value in metadata.items() if key != "collected_at"}
    payload = {
        "source_type": row.get("source_type"),
        "doc_type": row.get("doc_type"),
        "title": row.get("title"),
        "published_at": row.get("published_at"),
        "effective_start": row.get("effective_start"),
        "effective_end": row.get("effective_end"),
        "tags": row.get("tags"),
        "text": row.get("text"),
        "metadata": stable_metadata,
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _extract_fetched_at(rows: list[dict[str, Any]], source_path: Path) -> str:
    values = {
        _normalize_space(row.get("metadata", {}).get("collected_at"))
        for row in rows
        if isinstance(row.get("metadata"), dict)
        and _normalize_space(row["metadata"].get("collected_at"))
    }
    if len(values) != 1:
        raise RuntimeError(
            f"Raw artifact must contain exactly one metadata.collected_at value: {source_path} "
            f"(found {len(values)})"
        )
    return next(iter(values))


def _validate_source_name(value: str) -> None:
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise RuntimeError(f"Source name must match [a-z0-9_]+: {value!r}")


def create_snapshot_entry(
    spec: SourceSpec,
    snapshot_dir: Path,
) -> dict[str, Any]:
    _validate_source_name(spec.name)
    if not spec.path.is_file():
        raise RuntimeError(f"Required raw artifact does not exist: {spec.path}")
    source_bytes = spec.path.read_bytes()
    source_hash = _sha256_bytes(source_bytes)
    snapshot_path = snapshot_dir / f"raw_snapshot_{spec.name}_v2_{source_hash[:12]}.jsonl"
    _write_immutable_bytes(snapshot_path, source_bytes)
    rows = read_jsonl(snapshot_path)
    return {
        "snapshot_id": f"snapshot_sha256_{source_hash}",
        "source_name": spec.name,
        "source_path": spec.path.as_posix(),
        "snapshot_path": snapshot_path.as_posix(),
        "sha256": source_hash,
        "fetched_at": _extract_fetched_at(rows, spec.path),
        "parser_version": spec.parser_version,
        "row_count": len(rows),
        "byte_count": len(source_bytes),
    }


def make_manifest(
    entries: list[dict[str, Any]],
    corpus_name: str = "dnf_official",
) -> CorpusManifestV3:
    sorted_entries = sorted(entries, key=lambda item: (item["source_name"], item["source_path"]))
    unsigned = {
        "manifest_schema_version": CORPUS_MANIFEST_SCHEMA_VERSION,
        "corpus_name": corpus_name,
        "snapshotter_version": SNAPSHOTTER_VERSION,
        "artifacts": sorted_entries,
        "total_row_count": sum(int(item["row_count"]) for item in sorted_entries),
    }
    manifest_hash = _sha256_bytes(_canonical_json_bytes(unsigned))
    return {
        "manifest_schema_version": CORPUS_MANIFEST_SCHEMA_VERSION,
        "manifest_id": f"manifest_sha256_{manifest_hash}",
        "corpus_name": corpus_name,
        "snapshotter_version": SNAPSHOTTER_VERSION,
        "artifacts": sorted_entries,
        "total_row_count": unsigned["total_row_count"],
    }


def _parse_fetched_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Invalid fetched_at timestamp: {value!r}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _temporal_status(document: dict[str, Any]) -> str:
    fetched_date = _parse_fetched_at(document["fetched_at"]).date()
    valid_from_value = document["valid_from"]
    valid_to_value = document["valid_to"]
    valid_from = _parse_date(valid_from_value)
    valid_to = _parse_date(valid_to_value)
    if (valid_from_value and valid_from is None) or (valid_to_value and valid_to is None):
        return "unknown"
    if valid_from and valid_to and valid_from > valid_to:
        return "unknown"
    if valid_from and valid_from > fetched_date:
        return "upcoming"
    if valid_to and valid_to < fetched_date:
        return "expired"
    return "current"


def _make_document(row: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    canonical_url = canonicalize_url(row.get("source_url"))
    content_hash = stable_content_hash(row)
    identity_hash = _sha256_bytes(f"{canonical_url}\n{content_hash}".encode("utf-8"))
    return {
        "document_id": f"document_sha256_{identity_hash}",
        "source_snapshot_id": entry["snapshot_id"],
        "canonical_url": canonical_url,
        "source_kind": source_kind(row),
        "authority": _normalize_space(row.get("source_type")) or "official",
        "title": _normalize_space(row.get("title")),
        "category_path": category_path(row),
        "published_at": _nullable_string(row.get("published_at")),
        "valid_from": _nullable_string(row.get("effective_start")),
        "valid_to": _nullable_string(row.get("effective_end")),
        "revision_id": f"revision_sha256_{identity_hash}",
        "supersedes_document_id": None,
        "status": "unknown",
        "content_hash": content_hash,
        "fetched_at": entry["fetched_at"],
        "parser_version": DOCUMENT_PARSER_VERSION,
        "raw_source_path": entry["snapshot_path"],
    }


def build_document_rows(manifest: CorpusManifestV3) -> list[DocumentV3]:
    observations: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in manifest["artifacts"]:
        snapshot_path = Path(entry["snapshot_path"])
        if file_sha256(snapshot_path) != entry["sha256"]:
            raise RuntimeError(f"Snapshot hash does not match manifest: {snapshot_path}")
        for row in read_jsonl(snapshot_path):
            document = _make_document(row, entry)
            observations[(document["canonical_url"], document["content_hash"])].append(document)

    unique_documents: list[dict[str, Any]] = []
    for duplicates in observations.values():
        unique_documents.append(
            max(
                duplicates,
                key=lambda item: (
                    _parse_fetched_at(item["fetched_at"]),
                    item["source_snapshot_id"],
                    item["raw_source_path"],
                ),
            )
        )

    by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in unique_documents:
        by_url[document["canonical_url"]].append(document)

    result: list[DocumentV3] = []
    for canonical_url, revisions in sorted(by_url.items()):
        timestamps = [_parse_fetched_at(item["fetched_at"]) for item in revisions]
        if len(timestamps) != len(set(timestamps)):
            raise RuntimeError(
                "Cannot order distinct content revisions captured at the same fetched_at: "
                f"{canonical_url}"
            )
        revisions.sort(key=lambda item: (_parse_fetched_at(item["fetched_at"]), item["content_hash"]))
        previous_document_id: str | None = None
        for index, document in enumerate(revisions):
            document["supersedes_document_id"] = previous_document_id
            document["status"] = "superseded" if index < len(revisions) - 1 else _temporal_status(document)
            previous_document_id = document["document_id"]
            result.append(document)
    return result


def _serialize_manifest(manifest: CorpusManifestV3) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _serialize_jsonl(rows: list[DocumentV3]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def build_corpus(
    source_specs: list[SourceSpec],
    snapshot_dir: Path,
    normalized_dir: Path,
    corpus_name: str = "dnf_official",
) -> dict[str, Any]:
    if len({spec.name for spec in source_specs}) != len(source_specs):
        raise RuntimeError("Source names must be unique")
    for spec in source_specs:
        if not spec.path.is_file():
            raise RuntimeError(f"Required raw artifact does not exist: {spec.path}")
    source_hashes_before = {spec.path: file_sha256(spec.path) for spec in source_specs}
    entries = [create_snapshot_entry(spec, snapshot_dir) for spec in source_specs]
    for spec in source_specs:
        if file_sha256(spec.path) != source_hashes_before[spec.path]:
            raise RuntimeError(f"Raw input changed while snapshotting: {spec.path}")

    manifest = make_manifest(entries, corpus_name=corpus_name)
    artifact_suffix = manifest["manifest_id"].removeprefix("manifest_sha256_")[:12]
    manifest_path = snapshot_dir / f"corpus_manifest_{corpus_name}_v3.0_{artifact_suffix}.json"
    _write_immutable_bytes(manifest_path, _serialize_manifest(manifest))

    documents = build_document_rows(manifest)
    normalized_path = normalized_dir / f"documents_{corpus_name}_v3.0_{artifact_suffix}.jsonl"
    _write_immutable_bytes(normalized_path, _serialize_jsonl(documents))

    for spec in source_specs:
        if file_sha256(spec.path) != source_hashes_before[spec.path]:
            raise RuntimeError(f"Raw input changed while building corpus: {spec.path}")

    return {
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": file_sha256(manifest_path),
        "normalized_path": normalized_path.as_posix(),
        "normalized_sha256": file_sha256(normalized_path),
        "snapshot_paths": [entry["snapshot_path"] for entry in manifest["artifacts"]],
        "snapshot_count": len(manifest["artifacts"]),
        "source_row_count": manifest["total_row_count"],
        "document_count": len(documents),
        "deduplicated_observation_count": manifest["total_row_count"] - len(documents),
        "source_hashes_before": {
            path.as_posix(): digest for path, digest in source_hashes_before.items()
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create immutable v3 raw snapshots, a manifest, and revision-aware DocumentV3 rows."
    )
    parser.add_argument("--guide-docs", type=Path, default=DEFAULT_GUIDE_DOCS)
    parser.add_argument("--official-docs", type=Path, default=DEFAULT_OFFICIAL_DOCS)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--normalized-dir", type=Path, default=DEFAULT_NORMALIZED_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_corpus(
        [
            SourceSpec("guide_docs", args.guide_docs, GUIDE_SOURCE_PARSER_VERSION),
            SourceSpec("official_docs", args.official_docs, OFFICIAL_SOURCE_PARSER_VERSION),
        ],
        snapshot_dir=args.snapshot_dir,
        normalized_dir=args.normalized_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
