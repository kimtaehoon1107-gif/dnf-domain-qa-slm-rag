from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.collect_details import write_immutable


COLLECTOR_VERSION = "dnf_structured_detail_collector_v1.0"
ALLOWED_DETAIL_HOSTS = frozenset({"df.nexon.com"})
DEFAULT_DETAIL_DIR = Path("data/v3/structured_details")


def is_allowed_official_detail_url(url: str) -> bool:
    parsed = urlparse(str(url))
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_DETAIL_HOSTS


def _canonical_json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    if indent is None:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
    return (text + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(row) for row in rows)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def collect_structured_detail_references(
    references: list[dict[str, Any]],
    *,
    root: Path,
    documents: list[dict[str, Any]],
    fetched_at: str,
    detail_dir: Path = DEFAULT_DETAIL_DIR,
    timeout: float = 30.0,
    max_attempts: int = 2,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    root = root.resolve()
    output_dir = detail_dir if detail_dir.is_absolute() else root / detail_dir
    by_url = {row["canonical_url"]: row for row in documents}
    supported = [
        row
        for row in references
        if row.get("detail_kind") == "official_event_reward_popup"
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for reference in supported:
        detail_url = str(reference["detail_url"])
        if not is_allowed_official_detail_url(detail_url):
            raise RuntimeError(f"Structured detail URL is not an allowed official URL: {detail_url}")
        grouped.setdefault(detail_url, []).append(reference)

    client = session or requests.Session()
    client.headers.setdefault("User-Agent", "DNF-RAG-Structured-Detail/1.0")
    rows: list[dict[str, Any]] = []
    fetches: dict[str, dict[str, Any]] = {}
    try:
        for detail_url in sorted(grouped):
            response = None
            error = None
            attempts = 0
            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                try:
                    candidate = client.get(detail_url, timeout=timeout)
                    if candidate.status_code == 200:
                        response = candidate
                        break
                    error = f"HTTP {candidate.status_code}"
                except requests.RequestException as exc:
                    error = f"{type(exc).__name__}: {exc}"
                if attempt < max_attempts:
                    time.sleep(0.25 * attempt)

            if response is None:
                fetches[detail_url] = {
                    "fetch_status": "failed",
                    "http_status": None,
                    "retry_count": max(0, attempts - 1),
                    "error": error or "unknown fetch failure",
                    "snapshot_path": None,
                    "snapshot_sha256": None,
                    "byte_count": 0,
                }
            else:
                content = response.content
                snapshot_sha256 = hashlib.sha256(content).hexdigest()
                snapshot_path = (
                    output_dir
                    / "snapshots"
                    / "official_event_reward_popup"
                    / f"detail_{snapshot_sha256}.html"
                )
                write_immutable(snapshot_path, content)
                fetches[detail_url] = {
                    "fetch_status": "success",
                    "http_status": int(response.status_code),
                    "retry_count": max(0, attempts - 1),
                    "error": None,
                    "snapshot_path": _relative(root, snapshot_path),
                    "snapshot_sha256": snapshot_sha256,
                    "byte_count": len(content),
                }

            for reference in sorted(
                grouped[detail_url], key=lambda row: row["parent_canonical_url"]
            ):
                parent = by_url.get(reference["parent_canonical_url"])
                fetch = fetches[detail_url]
                rows.append(
                    {
                        "collection_schema_version": "dnf_structured_detail_collection_v1.0",
                        "collector_version": COLLECTOR_VERSION,
                        "parent_canonical_url": reference["parent_canonical_url"],
                        "parent_document_id": parent.get("document_id") if parent else None,
                        "parent_revision_id": parent.get("revision_id") if parent else None,
                        "parent_lineage_id": parent.get("lineage_id") if parent else None,
                        "detail_kind": reference["detail_kind"],
                        "detail_url": detail_url,
                        "event_reward_id": reference.get("event_reward_id"),
                        "source_locator": reference["source_locator"],
                        "fetched_at": fetched_at,
                        **fetch,
                    }
                )
    finally:
        if session is None:
            client.close()

    audit = {
        "reference_count": len(supported),
        "unique_detail_url_count": len(grouped),
        "network_fetch_count": len(fetches),
        "success_url_count": sum(
            row["fetch_status"] == "success" for row in fetches.values()
        ),
        "failed_url_count": sum(
            row["fetch_status"] == "failed" for row in fetches.values()
        ),
        "deduplicated_fetch_count": len(supported) - len(grouped),
        "all_urls_official": all(is_allowed_official_detail_url(url) for url in grouped),
        "parent_metadata_missing_count": sum(
            row["parent_revision_id"] is None for row in rows
        ),
    }
    return rows, audit


def freeze_collection(
    rows: list[dict[str, Any]],
    *,
    root: Path,
    detail_dir: Path = DEFAULT_DETAIL_DIR,
    fetched_at: str,
    discovery_path: Path,
    audit: dict[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = detail_dir if detail_dir.is_absolute() else root / detail_dir
    ordered = sorted(rows, key=lambda row: (row["detail_url"], row["parent_canonical_url"]))
    collection_bytes = _jsonl_bytes(ordered)
    collection_sha256 = hashlib.sha256(collection_bytes).hexdigest()
    collection_path = output_dir / f"structured_detail_collection_{collection_sha256}.jsonl"
    write_immutable(collection_path, collection_bytes)
    manifest = {
        "manifest_schema_version": "dnf_structured_detail_collection_manifest_v1.0",
        "collector_version": COLLECTOR_VERSION,
        "fetched_at": fetched_at,
        "discovery_path": _relative(root, discovery_path),
        "discovery_sha256": hashlib.sha256(discovery_path.read_bytes()).hexdigest(),
        "collection_path": _relative(root, collection_path),
        "collection_sha256": collection_sha256,
        "collection_row_count": len(ordered),
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output_dir / f"structured_detail_collection_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "collection_path": collection_path,
        "collection_sha256": collection_sha256,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect newly discovered official structured details")
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--detail-dir", type=Path, default=DEFAULT_DETAIL_DIR)
    parser.add_argument("--fetched-at", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    discovery_path = args.discovery if args.discovery.is_absolute() else root / args.discovery
    documents_path = args.documents if args.documents.is_absolute() else root / args.documents
    rows, audit = collect_structured_detail_references(
        read_jsonl(discovery_path),
        root=root,
        documents=read_jsonl(documents_path),
        fetched_at=args.fetched_at,
        detail_dir=args.detail_dir,
        timeout=args.timeout,
    )
    result = freeze_collection(
        rows,
        root=root,
        detail_dir=args.detail_dir,
        fetched_at=args.fetched_at,
        discovery_path=discovery_path,
        audit=audit,
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
