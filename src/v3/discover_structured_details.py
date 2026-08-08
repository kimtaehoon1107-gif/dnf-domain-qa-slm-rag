from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.collect_details import write_immutable
from src.v3.collect_structured_details import (
    DEFAULT_DETAIL_DIR,
    is_allowed_official_detail_url,
)


DISCOVERY_VERSION = "dnf_structured_detail_discovery_v1.0"
EVENT_REWARD_CALL = re.compile(r"eventRewardPop\s*\(\s*['\"]?(\d+)", re.IGNORECASE)
INFORMATION_HEADING = re.compile(r"(\ubcf4\uc0c1|\ube44\uc6a9|\uc7ac\ub8cc|\uc885\ub958)")
LITERAL_DETAIL_CALLS = (
    ("window_open", re.compile(r"window\.open\s*\(\s*['\"]([^'\"]+)", re.IGNORECASE)),
    ("fetch", re.compile(r"\bfetch\s*\(\s*['\"]([^'\"]+)", re.IGNORECASE)),
    ("axios", re.compile(r"\baxios(?:\.(?:get|post))?\s*\(\s*['\"]([^'\"]+)", re.IGNORECASE)),
)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split())


def _element_locator(soup: BeautifulSoup, tag: Tag, attribute: str | None = None) -> str:
    same = soup.find_all(tag.name)
    index = next((i for i, item in enumerate(same, start=1) if item is tag), 1)
    locator = f"{tag.name}:nth-of-type({index})"
    return f"{locator}@{attribute}" if attribute else locator


def _official_or_blocked_reference(
    *,
    detail_url: str,
    detail_kind: str,
    parent_canonical_url: str,
    source_locator: str,
    event_reward_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    row = {
        "discovery_schema_version": DISCOVERY_VERSION,
        "parent_canonical_url": parent_canonical_url,
        "detail_kind": detail_kind,
        "detail_url": detail_url,
        "event_reward_id": event_reward_id,
        "source_locator": source_locator,
    }
    if is_allowed_official_detail_url(detail_url):
        return "accepted", row
    return "blocked", {**row, "reason": "external_domain"}


def _css_background_for_container(source: str, container: Tag) -> bool:
    if container.find(["img", "svg", "video", "source"]):
        return True
    inline = str(container.get("style") or "")
    if re.search(r"(?:background|content)\s*:[^;]*url\(", inline, re.IGNORECASE):
        return True
    for class_name in container.get("class") or []:
        pattern = re.compile(
            rf"\.{re.escape(str(class_name))}(?:[^{{}}]*)\{{[^}}]*url\(",
            re.IGNORECASE | re.DOTALL,
        )
        if pattern.search(source):
            return True
    return False


def _section_has_values(container: Tag, heading: Tag) -> bool:
    if container.find(["table", "ul", "ol", "dl"]):
        return True
    clone = BeautifulSoup(str(container), "html.parser")
    clone_heading = clone.find(heading.name)
    if clone_heading:
        clone_heading.decompose()
    for tag in clone.find_all(["script", "style", "a", "button"]):
        tag.decompose()
    remaining = _normalize(clone.get_text(" ", strip=True))
    return bool(re.search(r"\d", remaining)) or len(remaining) >= 40


def _visual_sections(
    source: str,
    soup: BeautifulSoup,
    *,
    parent_canonical_url: str,
    structured_detail_available: bool,
) -> list[dict[str, Any]]:
    output = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = _normalize(heading.get_text(" ", strip=True))
        if not INFORMATION_HEADING.search(heading_text):
            continue
        container = heading.find_parent(["section", "article"])
        if container is None:
            container = heading.parent
        if container is None or _section_has_values(container, heading):
            continue
        if not _css_background_for_container(source, container):
            continue
        output.append(
            {
                "diagnostic_schema_version": "dnf_visual_section_diagnostic_v1.0",
                "parent_canonical_url": parent_canonical_url,
                "heading": heading_text,
                "section_locator": _element_locator(soup, container),
                "status": "visual_section_incomplete",
                "structured_detail_available": structured_detail_available,
                "ocr_candidate": not structured_detail_available,
                "review_required": True,
                "default_exposure": False,
                "reasons": [
                    "information_heading_present",
                    "structured_values_absent",
                    "visual_asset_present",
                ],
            }
        )
    return output


def discover_structured_details(
    source: str,
    parent_canonical_url: str,
) -> dict[str, list[dict[str, Any]]]:
    soup = BeautifulSoup(source, "html.parser")
    references: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for tag in soup.find_all(True):
        candidates: list[tuple[str, str]] = []
        for attribute, value in tag.attrs.items():
            joined = " ".join(value) if isinstance(value, list) else str(value)
            candidates.append((attribute, joined))
        if tag.name == "script" and tag.string:
            candidates.append(("text", str(tag.string)))
        for attribute, value in candidates:
            for match in EVENT_REWARD_CALL.finditer(value):
                reward_id = int(match.group(1))
                detail_url = urljoin(
                    parent_canonical_url,
                    f"/POP/common/event/event_reward_item.php?id={reward_id}",
                )
                key = ("official_event_reward_popup", detail_url)
                if key in seen:
                    continue
                seen.add(key)
                status, row = _official_or_blocked_reference(
                    detail_url=detail_url,
                    detail_kind="official_event_reward_popup",
                    parent_canonical_url=parent_canonical_url,
                    source_locator=_element_locator(
                        soup, tag, None if attribute == "text" else attribute
                    ),
                    event_reward_id=reward_id,
                )
                (references if status == "accepted" else blocked).append(row)

        if tag.has_attr("data-api-url"):
            detail_url = urljoin(parent_canonical_url, str(tag["data-api-url"]))
            key = ("official_internal_detail", detail_url)
            if key not in seen:
                seen.add(key)
                status, row = _official_or_blocked_reference(
                    detail_url=detail_url,
                    detail_kind="official_internal_detail",
                    parent_canonical_url=parent_canonical_url,
                    source_locator=_element_locator(soup, tag, "data-api-url"),
                )
                (references if status == "accepted" else blocked).append(row)

    for kind, pattern in LITERAL_DETAIL_CALLS:
        for match in pattern.finditer(source):
            raw = match.group(1)
            if not re.search(r"/(?:POP|api)/|reward|detail", raw, re.IGNORECASE):
                continue
            detail_url = urljoin(parent_canonical_url, raw)
            key = (kind, detail_url)
            if key in seen:
                continue
            seen.add(key)
            status, row = _official_or_blocked_reference(
                detail_url=detail_url,
                detail_kind=f"official_{kind}_detail",
                parent_canonical_url=parent_canonical_url,
                source_locator=f"script:{kind}",
            )
            (references if status == "accepted" else blocked).append(row)

    visual_sections = _visual_sections(
        source,
        soup,
        parent_canonical_url=parent_canonical_url,
        structured_detail_available=bool(references),
    )
    return {
        "references": sorted(references, key=lambda row: (row["detail_url"], row["source_locator"])),
        "blocked_references": sorted(blocked, key=lambda row: (row["detail_url"], row["source_locator"])),
        "visual_sections": visual_sections,
    }


def _canonical_json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    if indent is None:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
    return (text + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(row) for row in rows)


def discover_snapshot_corpus(
    *,
    root: Path,
    ledger: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    by_url = {row["canonical_url"]: row for row in documents}
    references = []
    visual_sections = []
    blocked = []
    for ledger_row in ledger:
        snapshot = ledger_row.get("raw_snapshot_path")
        if ledger_row.get("fetch_status") != "success" or not snapshot:
            continue
        source = (root / snapshot).read_text(encoding="utf-8", errors="replace")
        result = discover_structured_details(source, ledger_row["canonical_url"])
        parent = by_url.get(ledger_row["canonical_url"], {})
        parent_fields = {
            "parent_document_id": parent.get("document_id"),
            "parent_revision_id": parent.get("revision_id"),
            "parent_lineage_id": parent.get("lineage_id"),
            "parent_raw_snapshot_path": snapshot,
        }
        references.extend({**row, **parent_fields} for row in result["references"])
        visual_sections.extend({**row, **parent_fields} for row in result["visual_sections"])
        blocked.extend({**row, **parent_fields} for row in result["blocked_references"])
    references.sort(key=lambda row: (row["detail_url"], row["parent_canonical_url"]))
    visual_sections.sort(key=lambda row: (row["parent_canonical_url"], row["section_locator"]))
    audit = {
        "raw_snapshot_count": len(ledger),
        "reference_count": len(references),
        "reference_document_count": len({row["parent_canonical_url"] for row in references}),
        "unique_detail_url_count": len({row["detail_url"] for row in references}),
        "event_reward_reference_count": sum(
            row["detail_kind"] == "official_event_reward_popup" for row in references
        ),
        "blocked_external_reference_count": len(blocked),
        "visual_section_incomplete_count": len(visual_sections),
        "visual_section_document_count": len(
            {row["parent_canonical_url"] for row in visual_sections}
        ),
        "ocr_candidate_count": sum(row["ocr_candidate"] for row in visual_sections),
        "all_accepted_urls_official": all(
            is_allowed_official_detail_url(row["detail_url"]) for row in references
        ),
    }
    return references, visual_sections, audit


def freeze_discovery(
    references: list[dict[str, Any]],
    visual_sections: list[dict[str, Any]],
    *,
    root: Path,
    detail_dir: Path,
    ledger_path: Path,
    documents_path: Path,
    audit: dict[str, Any],
) -> dict[str, Any]:
    output_dir = detail_dir if detail_dir.is_absolute() else root / detail_dir
    reference_bytes = _jsonl_bytes(references)
    reference_sha = hashlib.sha256(reference_bytes).hexdigest()
    reference_path = output_dir / f"structured_detail_discovery_{reference_sha}.jsonl"
    write_immutable(reference_path, reference_bytes)
    visual_bytes = _jsonl_bytes(visual_sections)
    visual_sha = hashlib.sha256(visual_bytes).hexdigest()
    visual_path = output_dir / f"visual_section_diagnostic_{visual_sha}.jsonl"
    write_immutable(visual_path, visual_bytes)
    manifest = {
        "manifest_schema_version": "dnf_structured_detail_discovery_manifest_v1.0",
        "discovery_version": DISCOVERY_VERSION,
        "ledger_path": ledger_path.resolve().relative_to(root.resolve()).as_posix(),
        "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "documents_path": documents_path.resolve().relative_to(root.resolve()).as_posix(),
        "documents_sha256": hashlib.sha256(documents_path.read_bytes()).hexdigest(),
        "discovery_path": reference_path.resolve().relative_to(root.resolve()).as_posix(),
        "discovery_sha256": reference_sha,
        "visual_diagnostic_path": visual_path.resolve().relative_to(root.resolve()).as_posix(),
        "visual_diagnostic_sha256": visual_sha,
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output_dir / f"structured_detail_discovery_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "discovery_path": reference_path,
        "visual_diagnostic_path": visual_path,
        "manifest_path": manifest_path,
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover structured detail endpoints in local snapshots")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--detail-dir", type=Path, default=DEFAULT_DETAIL_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
    documents_path = args.documents if args.documents.is_absolute() else root / args.documents
    references, visual_sections, audit = discover_snapshot_corpus(
        root=root,
        ledger=read_jsonl(ledger_path),
        documents=read_jsonl(documents_path),
    )
    result = freeze_discovery(
        references,
        visual_sections,
        root=root,
        detail_dir=args.detail_dir,
        ledger_path=ledger_path,
        documents_path=documents_path,
        audit=audit,
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
