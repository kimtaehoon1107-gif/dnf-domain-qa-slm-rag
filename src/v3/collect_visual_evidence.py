from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from PIL import Image

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    normalize_block,
    normalize_space,
    parse_fixed_timestamp,
    write_immutable,
)
from src.v3.harden_detail_parsers import NOISE_SELECTORS, select_hardened_content


VISUAL_VERSION = "dnf_visual_evidence_pilot_v3.1"
ASSET_SCHEMA_VERSION = "dnf_visual_asset_ledger_v3.1"
DOCUMENT_SCHEMA_VERSION = "dnf_visual_document_evidence_v3.1"
OVERLAY_SCHEMA_VERSION = "dnf_discovery_correction_overlay_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_visual_evidence_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_visual_evidence_report_v3.1"
OCR_ENGINE = "Windows.Media.Ocr"
OCR_LANGUAGE = "ko"
OCR_MAX_DIMENSION = 2400

DEFAULT_REGISTRY = Path(
    "data/v3/discovery/"
    "source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
)
DEFAULT_LEDGER = Path(
    "data/v3/collections/"
    "detail_full_collection_ledger_0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b.jsonl"
)
DEFAULT_HARDENED_PREVIEW = Path(
    "data/v3/collections/"
    "detail_hardened_extraction_preview_ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8.jsonl"
)
DEFAULT_HARDENING_MANIFEST = Path(
    "data/v3/collections/"
    "detail_parser_hardening_manifest_ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29.json"
)
DEFAULT_ASSET_DIR = Path("data/v3/visual_assets")
DEFAULT_EVIDENCE_DIR = Path("data/v3/visual_evidence")
DEFAULT_REPORT_DIR = Path("reports/v3")
DEFAULT_OCR_SCRIPT = Path("src/v3/windows_ocr.ps1")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
CSS_IMAGE_DISCOVERY_KINDS = {"inline_stylesheet_url", "external_stylesheet_url"}
RESOLVED_VISUAL_STATUSES = {"resolved", "resolved_with_tolerated_css_404"}
MEDIA_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "text/css": ".css",
}


@dataclass(frozen=True)
class AssetFetchResult:
    status: str
    http_status: int | None
    content: bytes
    media_type: str | None
    retry_count: int
    error: str | None
    final_url: str


class RateLimitedAssetFetcher:
    def __init__(self, *, interval_seconds: float, retries: int, timeout_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "DNF-RAG-v3-visual-evidence-pilot/0.1 "
                    "(official-document-visual-validation; contact=local-research)"
                )
            }
        )
        self._last_request_at: float | None = None
        self._cache: dict[str, AssetFetchResult] = {}

    def __call__(self, url: str) -> AssetFetchResult:
        if url in self._cache:
            return self._cache[url]
        last_error: Exception | None = None
        last_status: int | None = None
        last_content = b""
        last_media_type: str | None = None
        last_final_url = url
        for attempt in range(self.retries + 1):
            if self._last_request_at is not None:
                remaining = self.interval_seconds - (time.monotonic() - self._last_request_at)
                if remaining > 0:
                    time.sleep(remaining)
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                self._last_request_at = time.monotonic()
                last_status = response.status_code
                last_content = response.content
                last_media_type = response.headers.get("content-type", "").split(";", 1)[0].lower() or None
                last_final_url = response.url
                blocked = response.status_code in {401, 403, 429} or any(
                    signal in response.content[:20000].lower()
                    for signal in (b"access denied", b"request blocked", b"captcha")
                )
                if blocked:
                    result = AssetFetchResult(
                        "blocked",
                        response.status_code,
                        response.content,
                        last_media_type,
                        attempt,
                        f"Blocked response: HTTP {response.status_code}",
                        response.url,
                    )
                    self._cache[url] = result
                    return result
                if 200 <= response.status_code < 300 and response.content:
                    result = AssetFetchResult(
                        "success",
                        response.status_code,
                        response.content,
                        last_media_type,
                        attempt,
                        None,
                        response.url,
                    )
                    self._cache[url] = result
                    return result
                last_error = RuntimeError(f"HTTP {response.status_code} or empty response")
            except requests.RequestException as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
            if attempt < self.retries:
                time.sleep(min(4.0, 0.5 * (2**attempt)))
        result = AssetFetchResult(
            "failed",
            last_status,
            last_content,
            last_media_type,
            self.retries,
            str(last_error),
            last_final_url,
        )
        self._cache[url] = result
        return result


def normalize_asset_url(base_url: str, value: str) -> str:
    absolute = urljoin(base_url, normalize_space(value))
    parts = urlsplit(absolute)
    scheme = "https" if parts.scheme in {"", "http", "https"} else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), parts.path, parts.query, ""))


def _css_urls(text: str, base_url: str) -> list[str]:
    values = re.findall(r"url\(\s*['\"]?([^)'\"]+)", text, re.IGNORECASE)
    urls = []
    for value in values:
        value = value.strip()
        if not value or value.startswith("data:"):
            continue
        url = normalize_asset_url(base_url, value)
        if Path(urlsplit(url).path).suffix.lower() in IMAGE_EXTENSIONS:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _page_specific_stylesheet(url: str) -> bool:
    parts = urlsplit(url)
    return parts.netloc.lower() == "bbscdn.df.nexon.com" and parts.path.lower().endswith(".css")


def discover_initial_asset_refs(
    registry_row: dict[str, Any],
    ledger_row: dict[str, Any],
    raw_html: bytes,
) -> list[dict[str, Any]]:
    node, selector, status, _, _ = select_hardened_content(registry_row, ledger_row, raw_html)
    if status != "parsed" or not isinstance(node, Tag):
        return []
    content = BeautifulSoup(str(node), "html.parser")
    for noise_selector in NOISE_SELECTORS:
        for tag in list(content.select(noise_selector)):
            tag.decompose()

    refs: dict[tuple[str, str], dict[str, Any]] = {}

    def add(url: str, asset_kind: str, discovery_kind: str, parent: str | None = None) -> None:
        key = (asset_kind, url)
        item = refs.setdefault(
            key,
            {
                "asset_url": url,
                "asset_kind": asset_kind,
                "discovery_kinds": [],
                "parent_stylesheet_urls": [],
            },
        )
        if discovery_kind not in item["discovery_kinds"]:
            item["discovery_kinds"].append(discovery_kind)
        if parent and parent not in item["parent_stylesheet_urls"]:
            item["parent_stylesheet_urls"].append(parent)

    for image in content.find_all("img"):
        value = normalize_space(image.get("src") or image.get("data-src"))
        if value:
            add(normalize_asset_url(ledger_row["final_url"], value), "image", "content_img")

    for tag in content.find_all(style=True):
        for url in _css_urls(str(tag.get("style")), ledger_row["final_url"]):
            add(url, "image", "content_style_url")

    if selector == "#wrap:event_custom":
        soup = BeautifulSoup(raw_html, "html.parser")
        for style in soup.find_all("style"):
            for url in _css_urls(style.get_text(" "), ledger_row["final_url"]):
                add(url, "image", "inline_stylesheet_url")
        for link in soup.find_all("link", href=True):
            rel = {str(value).lower() for value in (link.get("rel") or [])}
            if "stylesheet" not in rel:
                continue
            url = normalize_asset_url(ledger_row["final_url"], link["href"])
            if _page_specific_stylesheet(url):
                add(url, "stylesheet", "page_specific_stylesheet")

    return sorted(
        refs.values(), key=lambda row: (row["asset_kind"], row["asset_url"])
    )


def expand_stylesheet_refs(
    stylesheet_url: str, content: bytes
) -> list[dict[str, Any]]:
    text = content.decode("utf-8", errors="replace")
    return [
        {
            "asset_url": url,
            "asset_kind": "image",
            "discovery_kinds": ["external_stylesheet_url"],
            "parent_stylesheet_urls": [stylesheet_url],
        }
        for url in _css_urls(text, stylesheet_url)
    ]


def _asset_extension(media_type: str | None, final_url: str) -> str:
    if media_type in MEDIA_EXTENSIONS:
        return MEDIA_EXTENSIONS[media_type]
    suffix = Path(urlsplit(final_url).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS | {".css"} else ".bin"


def _fetch_asset_row(
    *,
    document: dict[str, Any],
    ref: dict[str, Any],
    fetched_at: str,
    fetcher: Callable[[str], AssetFetchResult],
    asset_dir: Path,
) -> tuple[dict[str, Any], bytes]:
    result = fetcher(ref["asset_url"])
    content_hash: str | None = None
    snapshot_path: str | None = None
    if result.content:
        content_hash = hashlib.sha256(result.content).hexdigest()
        extension = _asset_extension(result.media_type, result.final_url)
        path = asset_dir / document["source_id"] / f"visual_asset_{content_hash}{extension}"
        write_immutable(path, result.content)
        snapshot_path = path.as_posix()
    row = {
        "asset_schema_version": ASSET_SCHEMA_VERSION,
        "visual_version": VISUAL_VERSION,
        "document_url": document["canonical_url"],
        "source_id": document["source_id"],
        "asset_url": ref["asset_url"],
        "asset_kind": ref["asset_kind"],
        "discovery_kinds": sorted(ref["discovery_kinds"]),
        "parent_stylesheet_urls": sorted(ref["parent_stylesheet_urls"]),
        "fetch_status": result.status,
        "http_status": result.http_status,
        "fetched_at": fetched_at,
        "final_url": result.final_url,
        "media_type": result.media_type,
        "content_hash": content_hash,
        "snapshot_path": snapshot_path,
        "byte_count": len(result.content),
        "retry_count": result.retry_count,
        "image_width": None,
        "image_height": None,
        "image_frame_count": None,
        "ocr_status": "not_applicable" if ref["asset_kind"] == "stylesheet" else "pending",
        "ocr_engine": OCR_ENGINE if ref["asset_kind"] == "image" else None,
        "ocr_language": OCR_LANGUAGE if ref["asset_kind"] == "image" else None,
        "ocr_scale": None,
        "ocr_text": "",
        "ocr_char_count": 0,
        "ocr_signal_char_count": 0,
        "ocr_hangul_char_count": 0,
        "error": result.error,
    }
    return row, result.content


def _prepare_ocr_images(
    asset_rows: list[dict[str, Any]], temp_dir: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    metadata: dict[str, dict[str, Any]] = {}
    requests_by_hash: dict[str, str] = {}
    for row in asset_rows:
        content_hash = row.get("content_hash")
        if (
            row["asset_kind"] != "image"
            or row["fetch_status"] != "success"
            or not content_hash
            or content_hash in metadata
        ):
            continue
        try:
            with Image.open(Path(row["snapshot_path"])) as image:
                width, height = image.size
                frames = int(getattr(image, "n_frames", 1))
                image.seek(0)
                converted = image.convert("RGBA")
                background = Image.new("RGBA", converted.size, "white")
                background.alpha_composite(converted)
                prepared = background.convert("RGB")
                scale = min(1.0, OCR_MAX_DIMENSION / max(width, height))
                if scale < 1.0:
                    prepared = prepared.resize(
                        (max(1, round(width * scale)), max(1, round(height * scale))),
                        Image.Resampling.LANCZOS,
                    )
                temp_path = temp_dir / f"{content_hash}.png"
                prepared.save(temp_path, format="PNG")
            metadata[content_hash] = {
                "image_width": width,
                "image_height": height,
                "image_frame_count": frames,
                "ocr_scale": round(scale, 8),
                "prepare_error": None,
            }
            requests_by_hash[content_hash] = str(temp_path.resolve())
        except Exception as exc:
            metadata[content_hash] = {
                "image_width": None,
                "image_height": None,
                "image_frame_count": None,
                "ocr_scale": None,
                "prepare_error": str(exc),
            }
    return metadata, requests_by_hash


def run_windows_ocr(
    requests_by_hash: dict[str, str], script_path: Path
) -> dict[str, dict[str, Any]]:
    if not requests_by_hash:
        return {}
    input_text = "".join(
        json.dumps({"id": key, "path": path}, ensure_ascii=False) + "\n"
        for key, path in sorted(requests_by_hash.items())
    )
    process = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-LanguageTag",
            OCR_LANGUAGE,
        ],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=max(120, len(requests_by_hash) * 20),
        check=False,
    )
    if process.returncode != 0:
        error = normalize_space(process.stderr or process.stdout)
        return {
            key: {"status": "failed", "text": "", "error": error}
            for key in requests_by_hash
        }
    results: dict[str, dict[str, Any]] = {}
    for line in process.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line.lstrip("\ufeff"))
        results[row["id"]] = row
    for key in requests_by_hash:
        results.setdefault(
            key,
            {"status": "failed", "text": "", "error": "Missing OCR response"},
        )
    return results


def apply_ocr_results(
    asset_rows: list[dict[str, Any]],
    *,
    ocr_script_path: Path,
    ocr_runner: Callable[[dict[str, str], Path], dict[str, dict[str, Any]]] = run_windows_ocr,
) -> None:
    with tempfile.TemporaryDirectory(prefix="dnf_v3_ocr_") as temp_dir_value:
        metadata, requests_by_hash = _prepare_ocr_images(asset_rows, Path(temp_dir_value))
        results = ocr_runner(requests_by_hash, ocr_script_path)
    for row in asset_rows:
        if row["asset_kind"] != "image":
            continue
        content_hash = row.get("content_hash")
        if row["fetch_status"] != "success" or not content_hash:
            row["ocr_status"] = "not_run_fetch_failed"
            continue
        values = metadata.get(content_hash, {})
        row.update(
            image_width=values.get("image_width"),
            image_height=values.get("image_height"),
            image_frame_count=values.get("image_frame_count"),
            ocr_scale=values.get("ocr_scale"),
        )
        if values.get("prepare_error"):
            row["ocr_status"] = "prepare_failed"
            row["error"] = values["prepare_error"]
            continue
        result = results[content_hash]
        text = normalize_block(result.get("text", ""))
        row["ocr_status"] = result.get("status", "failed")
        row["ocr_text"] = text
        row["ocr_char_count"] = len(text)
        row["ocr_signal_char_count"] = len(re.findall(r"[0-9A-Za-z가-힣]", text))
        row["ocr_hangul_char_count"] = len(re.findall(r"[가-힣]", text))
        if result.get("error"):
            row["error"] = normalize_space(result["error"])


def _combine_ocr_text(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: item["asset_url"]):
        for line in row["ocr_text"].splitlines():
            normalized = normalize_space(line)
            signature = normalized.lower()
            if normalized and signature not in seen:
                seen.add(signature)
                lines.append(normalized)
    return "\n".join(lines)


def _is_tolerated_css_404(row: dict[str, Any]) -> bool:
    discovery_kinds = set(row.get("discovery_kinds") or [])
    return (
        row.get("fetch_status") == "failed"
        and row.get("http_status") == 404
        and bool(discovery_kinds)
        and discovery_kinds <= CSS_IMAGE_DISCOVERY_KINDS
    )


def _has_meaningful_ocr(text: str) -> bool:
    signal_chars = len(re.findall(r"[0-9A-Za-z가-힣]", text))
    hangul_chars = len(re.findall(r"[가-힣]", text))
    digit_chars = len(re.findall(r"[0-9]", text))
    return hangul_chars >= 10 and (
        signal_chars >= 40 or (signal_chars >= 30 and digit_chars >= 2)
    )


def build_document_evidence(
    targets: list[dict[str, Any]], asset_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    evidence = []
    for document in sorted(targets, key=lambda row: (row["source_id"], row["canonical_url"])):
        rows = [
            row
            for row in asset_rows
            if row["document_url"] == document["canonical_url"]
            and row["asset_kind"] == "image"
        ]
        combined = _combine_ocr_text(rows)
        signal_chars = len(re.findall(r"[0-9A-Za-z가-힣]", combined))
        hangul_chars = len(re.findall(r"[가-힣]", combined))
        digit_chars = len(re.findall(r"[0-9]", combined))
        fetched = sum(row["fetch_status"] == "success" for row in rows)
        ocr_success = sum(row["ocr_status"] == "success" for row in rows)
        meaningful = _has_meaningful_ocr(combined)
        tolerated_failures = [row for row in rows if _is_tolerated_css_404(row)]
        required_rows = [row for row in rows if row not in tolerated_failures]
        required_complete = bool(rows) and all(
            row["fetch_status"] == "success" and row["ocr_status"] == "success"
            for row in required_rows
        )
        if meaningful and required_complete:
            status = (
                "resolved_with_tolerated_css_404"
                if tolerated_failures
                else "resolved"
            )
        elif combined:
            status = "partial"
        elif not rows:
            status = "unresolved_no_assets"
        else:
            status = "unresolved_no_ocr_text"
        evidence.append(
            {
                "document_schema_version": DOCUMENT_SCHEMA_VERSION,
                "visual_version": VISUAL_VERSION,
                "canonical_url": document["canonical_url"],
                "source_id": document["source_id"],
                "title": document["title"],
                "default_exposure": document["default_exposure"],
                "previous_image_dependency_risk": document["image_dependency_risk"],
                "asset_count": len(rows),
                "asset_fetch_success": fetched,
                "asset_fetch_failed": len(rows) - fetched,
                "ocr_success": ocr_success,
                "ocr_nonempty": sum(bool(row["ocr_text"]) for row in rows),
                "ocr_text": combined,
                "ocr_char_count": len(combined),
                "ocr_signal_char_count": signal_chars,
                "ocr_hangul_char_count": hangul_chars,
                "ocr_digit_char_count": digit_chars,
                "meaningful_ocr": meaningful,
                "visual_evidence_status": status,
                "normalization_eligible_after_visual": status in RESOLVED_VISUAL_STATUSES,
                "tolerated_css_404_asset_urls": [
                    row["asset_url"] for row in tolerated_failures
                ],
                "unresolved_asset_urls": [
                    row["asset_url"]
                    for row in rows
                    if row["fetch_status"] != "success" or row["ocr_status"] != "success"
                ],
            }
        )
    return evidence


def build_correction_overlay(
    hardened_previews: list[dict[str, Any]],
    registry_by_url: dict[str, dict[str, Any]],
    ledger_by_url: dict[str, dict[str, Any]],
    *,
    observed_at: str,
) -> list[dict[str, Any]]:
    overlay = []
    for preview in hardened_previews:
        if preview["content_status"] != "unavailable_redirect":
            continue
        registry = registry_by_url[preview["canonical_url"]]
        ledger = ledger_by_url[preview["canonical_url"]]
        overlay.append(
            {
                "overlay_schema_version": OVERLAY_SCHEMA_VERSION,
                "visual_version": VISUAL_VERSION,
                "canonical_url": preview["canonical_url"],
                "source_id": preview["source_id"],
                "observed_at": observed_at,
                "observed_final_url": ledger["final_url"],
                "evidence_content_hash": ledger["content_hash"],
                "original_status": registry["status"],
                "original_eligible_for_collection": registry["eligible_for_collection"],
                "original_default_exposure": registry["default_exposure"],
                "effective_status": "unavailable_redirect",
                "effective_eligible_for_collection": False,
                "effective_default_exposure": False,
                "normalization_eligible": False,
                "correction_reason": "canonical_detail_redirected_off_path",
            }
        )
    return sorted(overlay, key=lambda row: row["canonical_url"])


def _build_report(
    *,
    asset_rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    overlay: list[dict[str, Any]],
    normalization_candidates_before_visual: int,
    fetched_at: str,
    manifest_path: Path,
    manifest_sha256: str,
) -> dict[str, Any]:
    image_rows = [row for row in asset_rows if row["asset_kind"] == "image"]
    status_counts = Counter(row["visual_evidence_status"] for row in evidence)
    fetch_counts = Counter(row["fetch_status"] for row in asset_rows)
    ocr_counts = Counter(row["ocr_status"] for row in image_rows)
    corrected_default = sum(row["original_default_exposure"] for row in overlay)
    unresolved_default = [
        row
        for row in evidence
        if row["default_exposure"] and not row["normalization_eligible_after_visual"]
    ]
    visual_go = not unresolved_default and fetch_counts["blocked"] == 0
    document_go = visual_go and corrected_default == 1
    by_source: dict[str, Any] = {}
    for source_id in sorted({row["source_id"] for row in evidence}):
        rows = [row for row in evidence if row["source_id"] == source_id]
        by_source[source_id] = {
            "documents": len(rows),
            "status": dict(
                sorted(Counter(row["visual_evidence_status"] for row in rows).items())
            ),
            "assets": sum(row["asset_count"] for row in rows),
            "ocr_chars": sum(row["ocr_char_count"] for row in rows),
        }
    failures = [
        {
            "document_url": row["document_url"],
            "asset_url": row["asset_url"],
            "fetch_status": row["fetch_status"],
            "ocr_status": row["ocr_status"],
            "tolerated_for_document": _is_tolerated_css_404(row),
            "error": row["error"],
        }
        for row in asset_rows
        if row["fetch_status"] != "success"
        or (row["asset_kind"] == "image" and row["ocr_status"] != "success")
    ]
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "visual_version": VISUAL_VERSION,
        "fetched_at": fetched_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "summary": {
            "target_documents": len(evidence),
            "resolved_documents": sum(
                row["normalization_eligible_after_visual"] for row in evidence
            ),
            "resolved_with_tolerated_css_404": status_counts[
                "resolved_with_tolerated_css_404"
            ],
            "partial_documents": status_counts["partial"],
            "unresolved_documents": sum(
                row["visual_evidence_status"].startswith("unresolved") for row in evidence
            ),
            "normalization_candidates_after_visual": normalization_candidates_before_visual
            + sum(row["normalization_eligible_after_visual"] for row in evidence),
            "asset_rows": len(asset_rows),
            "image_asset_rows": len(image_rows),
            "stylesheet_rows": sum(row["asset_kind"] == "stylesheet" for row in asset_rows),
            "asset_fetch_success": fetch_counts["success"],
            "asset_fetch_failed": fetch_counts["failed"],
            "asset_fetch_blocked": fetch_counts["blocked"],
            "tolerated_css_404_assets": sum(
                len(row["tolerated_css_404_asset_urls"]) for row in evidence
            ),
            "ocr_success": ocr_counts["success"],
            "ocr_engine_failed": sum(
                ocr_counts[status] for status in ("failed", "prepare_failed")
            ),
            "ocr_not_run_fetch_failed": ocr_counts["not_run_fetch_failed"],
            "ocr_nonempty_assets": sum(bool(row["ocr_text"]) for row in image_rows),
            "ocr_total_chars": sum(row["ocr_char_count"] for row in image_rows),
            "correction_overlay_rows": len(overlay),
            "default_exposure_corrections": corrected_default,
            "unresolved_default_documents": len(unresolved_default),
            "asset_hash_mismatches": 0,
        },
        "document_status_distribution": dict(sorted(status_counts.items())),
        "asset_fetch_distribution": dict(sorted(fetch_counts.items())),
        "ocr_status_distribution": dict(sorted(ocr_counts.items())),
        "by_source": by_source,
        "unresolved_documents": [
            {
                "canonical_url": row["canonical_url"],
                "source_id": row["source_id"],
                "status": row["visual_evidence_status"],
                "asset_count": row["asset_count"],
                "ocr_char_count": row["ocr_char_count"],
                "unresolved_asset_urls": row["unresolved_asset_urls"],
                "tolerated_css_404_asset_urls": row["tolerated_css_404_asset_urls"],
            }
            for row in evidence
            if not row["normalization_eligible_after_visual"]
        ],
        "failure_rows": failures,
        "correction_overlay": overlay,
        "visual_evidence_decision": "GO" if visual_go else "NO-GO",
        "document_v3_promotion_decision": "GO" if document_go else "NO-GO",
    }


def render_report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DNF RAG v3 visual evidence/OCR 파일럿",
        "",
        f"- visual version: `{report['visual_version']}`",
        f"- fetched_at: `{report['fetched_at']}`",
        f"- manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## 결과",
        "",
        "| targets | resolved | partial | unresolved | image assets | OCR chars |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['target_documents']} | {summary['resolved_documents']} | "
            f"{summary['partial_documents']} | {summary['unresolved_documents']} | "
            f"{summary['image_asset_rows']} | {summary['ocr_total_chars']} |"
        ),
        "",
        "## 출처별 결과",
        "",
        "| source | documents | status | assets | OCR chars |",
        "|---|---:|---|---:|---:|",
    ]
    for source_id, values in report["by_source"].items():
        status = ", ".join(f"{key}:{value}" for key, value in values["status"].items())
        lines.append(
            f"| `{source_id}` | {values['documents']} | {status} | "
            f"{values['assets']} | {values['ocr_chars']} |"
        )
    lines.extend(
        [
            "",
            "## 게이트",
            "",
            *[f"- {key}: `{value}`" for key, value in summary.items()],
            "",
            "## 판정",
            "",
            f"- visual evidence: **{report['visual_evidence_decision']}**",
            f"- DocumentV3 promotion: **{report['document_v3_promotion_decision']}**",
            "",
            "이 파일럿은 targeted image/CSS asset과 OCR evidence만 생성했다. DocumentV3, ChunkV3, 검색, 학습은 실행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def freeze_visual_artifacts(
    *,
    asset_rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    overlay: list[dict[str, Any]],
    fetched_at: str,
    registry_path: Path,
    ledger_path: Path,
    hardened_preview_path: Path,
    hardening_manifest_path: Path,
    normalization_candidates_before_visual: int,
    evidence_dir: Path,
    report_dir: Path,
    reused_asset_ledger_path: Path | None = None,
) -> dict[str, Any]:
    asset_bytes = _serialize_jsonl(
        asset_rows,
        lambda row: (row["source_id"], row["document_url"], row["asset_kind"], row["asset_url"]),
    )
    asset_sha256 = hashlib.sha256(asset_bytes).hexdigest()
    asset_path = evidence_dir / f"visual_asset_ledger_{asset_sha256}.jsonl"
    write_immutable(asset_path, asset_bytes)

    evidence_bytes = _serialize_jsonl(
        evidence, lambda row: (row["source_id"], row["canonical_url"])
    )
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    evidence_path = evidence_dir / f"visual_document_evidence_{evidence_sha256}.jsonl"
    write_immutable(evidence_path, evidence_bytes)

    overlay_bytes = _serialize_jsonl(overlay, lambda row: row["canonical_url"])
    overlay_sha256 = hashlib.sha256(overlay_bytes).hexdigest()
    overlay_path = evidence_dir / f"discovery_correction_overlay_{overlay_sha256}.jsonl"
    write_immutable(overlay_path, overlay_bytes)

    snapshots: dict[str, dict[str, Any]] = {}
    for row in asset_rows:
        path_value = row.get("snapshot_path")
        if not path_value:
            continue
        item = snapshots.setdefault(
            path_value,
            {
                "snapshot_path": path_value,
                "content_hash": row["content_hash"],
                "byte_count": Path(path_value).stat().st_size,
                "reference_count": 0,
            },
        )
        item["reference_count"] += 1
        if file_sha256(Path(path_value)) != row["content_hash"]:
            raise RuntimeError(f"Visual asset hash mismatch: {path_value}")

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "visual_version": VISUAL_VERSION,
        "fetched_at": fetched_at,
        "registry_path": registry_path.as_posix(),
        "registry_sha256": file_sha256(registry_path),
        "ledger_path": ledger_path.as_posix(),
        "ledger_sha256": file_sha256(ledger_path),
        "hardened_preview_path": hardened_preview_path.as_posix(),
        "hardened_preview_sha256": file_sha256(hardened_preview_path),
        "hardening_manifest_path": hardening_manifest_path.as_posix(),
        "hardening_manifest_sha256": file_sha256(hardening_manifest_path),
        "asset_ledger_path": asset_path.as_posix(),
        "asset_ledger_sha256": asset_sha256,
        "asset_ledger_row_count": len(asset_rows),
        "document_evidence_path": evidence_path.as_posix(),
        "document_evidence_sha256": evidence_sha256,
        "document_evidence_row_count": len(evidence),
        "correction_overlay_path": overlay_path.as_posix(),
        "correction_overlay_sha256": overlay_sha256,
        "correction_overlay_row_count": len(overlay),
        "snapshot_count": len(snapshots),
        "snapshots": sorted(snapshots.values(), key=lambda row: row["snapshot_path"]),
    }
    if reused_asset_ledger_path is not None:
        manifest["reused_asset_ledger_path"] = reused_asset_ledger_path.as_posix()
        manifest["reused_asset_ledger_sha256"] = file_sha256(reused_asset_ledger_path)
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"visual_evidence_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = _build_report(
        asset_rows=asset_rows,
        evidence=evidence,
        overlay=overlay,
        normalization_candidates_before_visual=normalization_candidates_before_visual,
        fetched_at=fetched_at,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
    )
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    report_json_path = report_dir / f"visual_evidence_pilot_{report_sha256}.json"
    report_md_path = report_dir / f"visual_evidence_pilot_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_md_path, render_report_markdown(report).encode("utf-8"))
    return {
        "asset_ledger_path": asset_path.as_posix(),
        "asset_ledger_sha256": asset_sha256,
        "document_evidence_path": evidence_path.as_posix(),
        "document_evidence_sha256": evidence_sha256,
        "correction_overlay_path": overlay_path.as_posix(),
        "correction_overlay_sha256": overlay_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_md_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": report["by_source"],
        "visual_evidence_decision": report["visual_evidence_decision"],
        "document_v3_promotion_decision": report["document_v3_promotion_decision"],
    }


def collect_visual_evidence(
    *,
    fetched_at: str,
    registry_path: Path,
    ledger_path: Path,
    hardened_preview_path: Path,
    hardening_manifest_path: Path,
    asset_dir: Path,
    evidence_dir: Path,
    report_dir: Path,
    ocr_script_path: Path,
    fetcher: Callable[[str], AssetFetchResult],
    ocr_runner: Callable[[dict[str, str], Path], dict[str, dict[str, Any]]] = run_windows_ocr,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    parse_fixed_timestamp(fetched_at)
    progress = progress or (lambda _message: None)
    registry = read_jsonl(registry_path)
    ledger = read_jsonl(ledger_path)
    hardened = read_jsonl(hardened_preview_path)
    registry_by_url = {row["canonical_url"]: row for row in registry}
    ledger_by_url = {row["canonical_url"]: row for row in ledger}
    targets = [
        row
        for row in hardened
        if row["default_exposure"] and row["image_dependency_risk"] == "high"
    ]
    if not targets:
        raise RuntimeError("No high-image default documents found")

    asset_rows: list[dict[str, Any]] = []
    for document_index, document in enumerate(
        sorted(targets, key=lambda row: (row["source_id"], row["canonical_url"])), start=1
    ):
        registry_row = registry_by_url[document["canonical_url"]]
        ledger_row = ledger_by_url[document["canonical_url"]]
        raw_html = Path(ledger_row["raw_snapshot_path"]).read_bytes()
        refs = discover_initial_asset_refs(registry_row, ledger_row, raw_html)
        ref_map = {(ref["asset_kind"], ref["asset_url"]): ref for ref in refs}
        stylesheet_rows: list[tuple[dict[str, Any], bytes]] = []
        for ref in refs:
            if ref["asset_kind"] != "stylesheet":
                continue
            progress(
                f"[{document_index}/{len(targets)}] stylesheet {document['canonical_url']} {ref['asset_url']}"
            )
            row, content = _fetch_asset_row(
                document=document,
                ref=ref,
                fetched_at=fetched_at,
                fetcher=fetcher,
                asset_dir=asset_dir,
            )
            asset_rows.append(row)
            stylesheet_rows.append((row, content))
        for stylesheet_row, content in stylesheet_rows:
            if stylesheet_row["fetch_status"] != "success":
                continue
            for ref in expand_stylesheet_refs(stylesheet_row["asset_url"], content):
                key = (ref["asset_kind"], ref["asset_url"])
                existing = ref_map.get(key)
                if existing:
                    existing["discovery_kinds"] = sorted(
                        set(existing["discovery_kinds"] + ref["discovery_kinds"])
                    )
                    existing["parent_stylesheet_urls"] = sorted(
                        set(existing["parent_stylesheet_urls"] + ref["parent_stylesheet_urls"])
                    )
                else:
                    ref_map[key] = ref
        image_refs = sorted(
            (ref for ref in ref_map.values() if ref["asset_kind"] == "image"),
            key=lambda row: row["asset_url"],
        )
        for asset_index, ref in enumerate(image_refs, start=1):
            progress(
                f"[{document_index}/{len(targets)} {asset_index}/{len(image_refs)}] image "
                f"{document['canonical_url']} {ref['asset_url']}"
            )
            row, _ = _fetch_asset_row(
                document=document,
                ref=ref,
                fetched_at=fetched_at,
                fetcher=fetcher,
                asset_dir=asset_dir,
            )
            asset_rows.append(row)

    apply_ocr_results(
        asset_rows, ocr_script_path=ocr_script_path, ocr_runner=ocr_runner
    )
    evidence = build_document_evidence(targets, asset_rows)
    overlay = build_correction_overlay(
        hardened, registry_by_url, ledger_by_url, observed_at=fetched_at
    )
    return freeze_visual_artifacts(
        asset_rows=asset_rows,
        evidence=evidence,
        overlay=overlay,
        fetched_at=fetched_at,
        registry_path=registry_path,
        ledger_path=ledger_path,
        hardened_preview_path=hardened_preview_path,
        hardening_manifest_path=hardening_manifest_path,
        normalization_candidates_before_visual=sum(
            row["normalization_eligible"] for row in hardened
        ),
        evidence_dir=evidence_dir,
        report_dir=report_dir,
    )


def finalize_visual_evidence_from_ledger(
    *,
    fetched_at: str,
    reused_asset_ledger_path: Path,
    registry_path: Path,
    ledger_path: Path,
    hardened_preview_path: Path,
    hardening_manifest_path: Path,
    evidence_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    parse_fixed_timestamp(fetched_at)
    registry = read_jsonl(registry_path)
    ledger = read_jsonl(ledger_path)
    hardened = read_jsonl(hardened_preview_path)
    targets = [
        row
        for row in hardened
        if row["default_exposure"] and row["image_dependency_risk"] == "high"
    ]
    if not targets:
        raise RuntimeError("No high-image default documents found")
    asset_rows = []
    for source_row in read_jsonl(reused_asset_ledger_path):
        row = dict(source_row)
        row["asset_schema_version"] = ASSET_SCHEMA_VERSION
        row["visual_version"] = VISUAL_VERSION
        asset_rows.append(row)
    evidence = build_document_evidence(targets, asset_rows)
    overlay = build_correction_overlay(
        hardened,
        {row["canonical_url"]: row for row in registry},
        {row["canonical_url"]: row for row in ledger},
        observed_at=fetched_at,
    )
    return freeze_visual_artifacts(
        asset_rows=asset_rows,
        evidence=evidence,
        overlay=overlay,
        fetched_at=fetched_at,
        registry_path=registry_path,
        ledger_path=ledger_path,
        hardened_preview_path=hardened_preview_path,
        hardening_manifest_path=hardening_manifest_path,
        normalization_candidates_before_visual=sum(
            row["normalization_eligible"] for row in hardened
        ),
        evidence_dir=evidence_dir,
        report_dir=report_dir,
        reused_asset_ledger_path=reused_asset_ledger_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect and OCR targeted visual evidence for DNF v3 high-image documents."
    )
    parser.add_argument("--fetched-at", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--hardened-preview", type=Path, default=DEFAULT_HARDENED_PREVIEW)
    parser.add_argument("--hardening-manifest", type=Path, default=DEFAULT_HARDENING_MANIFEST)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--ocr-script", type=Path, default=DEFAULT_OCR_SCRIPT)
    parser.add_argument(
        "--reuse-asset-ledger",
        type=Path,
        help="Re-freeze evidence from an immutable prior visual asset ledger without network or OCR.",
    )
    parser.add_argument("--request-interval", type=float, default=0.25)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    required_paths = [
        args.registry,
        args.ledger,
        args.hardened_preview,
        args.hardening_manifest,
    ]
    required_paths.append(args.reuse_asset_ledger or args.ocr_script)
    for path in required_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    if args.reuse_asset_ledger:
        result = finalize_visual_evidence_from_ledger(
            fetched_at=args.fetched_at,
            reused_asset_ledger_path=args.reuse_asset_ledger,
            registry_path=args.registry,
            ledger_path=args.ledger,
            hardened_preview_path=args.hardened_preview,
            hardening_manifest_path=args.hardening_manifest,
            evidence_dir=args.evidence_dir,
            report_dir=args.report_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    fetcher = RateLimitedAssetFetcher(
        interval_seconds=args.request_interval,
        retries=args.retries,
        timeout_seconds=args.timeout,
    )
    result = collect_visual_evidence(
        fetched_at=args.fetched_at,
        registry_path=args.registry,
        ledger_path=args.ledger,
        hardened_preview_path=args.hardened_preview,
        hardening_manifest_path=args.hardening_manifest,
        asset_dir=args.asset_dir,
        evidence_dir=args.evidence_dir,
        report_dir=args.report_dir,
        ocr_script_path=args.ocr_script,
        fetcher=fetcher,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
