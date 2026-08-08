from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _extract_date_signals,
    _extract_price_signals,
    _select_content_node,
    _serialize_jsonl,
    normalize_block,
    normalize_space,
    parse_fixed_timestamp,
    resolve_faq_node,
    validate_policy_revision,
    write_immutable,
)


PARSER_VERSION = "dnf_detail_parser_hardened_v3.2"
PREVIEW_SCHEMA_VERSION = "dnf_detail_hardened_preview_v3.2"
MANIFEST_SCHEMA_VERSION = "dnf_detail_parser_hardening_manifest_v3.2"
REPORT_SCHEMA_VERSION = "dnf_detail_parser_hardening_report_v3.2"

DEFAULT_REGISTRY = Path(
    "data/v3/discovery/"
    "source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
)
DEFAULT_LEDGER = Path(
    "data/v3/collections/"
    "detail_full_collection_ledger_0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b.jsonl"
)
DEFAULT_PREVIOUS_PREVIEW = Path(
    "data/v3/collections/"
    "detail_full_extraction_preview_e48f58e205a7001e23e3286cc7df2d467bf8b549f9ce449b82a46a6accf8e1dd.jsonl"
)
DEFAULT_COLLECTION_MANIFEST = Path(
    "data/v3/collections/"
    "detail_full_collection_manifest_f3003742b55a515e51c2abaee5a993cea9b1f108297f59c74a9aeaa201f87e97.json"
)
DEFAULT_GUIDE_BASELINE = Path("data/raw/guide_docs.jsonl")
DEFAULT_COLLECTION_DIR = Path("data/v3/collections")
DEFAULT_REPORT_DIR = Path("reports/v3")

NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "footer",
    ".login_bar",
    ".right_item",
    ".evt_ing_wrap",
    ".evtbar_bottom",
    "#commonFooterArea",
    "#secureWarningLayer",
    ".ly_warnings",
    ".gnb",
    ".quick_menu",
)
NAVIGATION_TERMS = (
    "회사소개",
    "채용안내",
    "이용약관",
    "게임이용등급안내",
    "개인정보처리방침",
    "고객센터",
)
GENERIC_IMAGE_ALTS = {"dungeon & fighter", "게임스타트", "이미지", "image"}


def _compact_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.lower())


def _path_only(url: str) -> str:
    return urlsplit(url).path.rstrip("/") or "/"


def _table_text(table: Tag) -> str:
    rows = []
    for row in table.select("tr"):
        cells = [
            normalize_space(cell.get_text(" ", strip=True))
            for cell in row.find_all(["th", "td"])
        ]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    return "\n[TABLE]\n" + "\n".join(rows) + "\n[/TABLE]\n"


def structured_text_hardened(
    node: Tag,
) -> tuple[str, int, int, int, int, list[str]]:
    clone_soup = BeautifulSoup(str(node), "html.parser")
    root = clone_soup.find()
    if not isinstance(root, Tag):
        return "", 0, 0, 0, 0, []

    removed = 0
    removed_ids: set[int] = set()
    for selector in NOISE_SELECTORS:
        for tag in list(root.select(selector)):
            identity = id(tag)
            if identity in removed_ids or tag.parent is None:
                continue
            removed_ids.add(identity)
            tag.decompose()
            removed += 1

    heading_count = len(root.find_all(re.compile(r"^h[1-6]$")))
    table_count = len(root.find_all("table"))
    images = list(root.find_all("img"))
    image_count = len(images)
    seen_alts: set[str] = set()
    for image in images:
        if image.decomposed:
            continue
        alt = normalize_space(image.get("alt"))
        compact = alt.lower()
        if alt and compact not in GENERIC_IMAGE_ALTS and compact not in seen_alts:
            seen_alts.add(compact)
            image.replace_with(NavigableString(f"\n[IMAGE_ALT] {alt}\n"))
        else:
            image.decompose()

    for table in list(root.find_all("table")):
        table.replace_with(NavigableString(_table_text(table)))
    for heading in root.find_all(re.compile(r"^h[1-6]$")):
        level = int(heading.name[1])
        heading.insert_before(NavigableString(f"\n{'#' * level} "))
        heading.insert_after(NavigableString("\n"))
    for block in root.find_all(
        ["p", "li", "dt", "dd", "caption", "pre", "blockquote", "br", "button"]
    ):
        block.insert_after(NavigableString("\n"))

    text = normalize_block(root.get_text(" "))
    navigation_hits = [term for term in NAVIGATION_TERMS if term in text]
    return text, heading_count, table_count, image_count, removed, navigation_hits


def select_hardened_content(
    row: dict[str, Any],
    ledger_row: dict[str, Any],
    raw_html: bytes,
) -> tuple[Tag | None, str, str, bool | None, bool | None]:
    soup = BeautifulSoup(raw_html, "html.parser")
    faq_validated: bool | None = None
    policy_validated: bool | None = None

    if row["source_id"] == "dnf_faq":
        node = resolve_faq_node(raw_html, row["source_item_id"])
        return (
            node,
            f'li[data-no="{row["source_item_id"]}"]',
            "parsed",
            True,
            None,
        )

    if row["source_id"] == "dnf_account_policy":
        validate_policy_revision(raw_html, row["source_item_id"])
        policy_validated = True

    if row["source_id"] == "dnf_event":
        if _path_only(row["canonical_url"]) != _path_only(ledger_row["final_url"]):
            return None, "redirected_off_canonical_path", "unavailable_redirect", None, None
        if "/community/news/" not in _path_only(row["canonical_url"]):
            wrap = soup.select_one("#wrap")
            if not isinstance(wrap, Tag):
                raise RuntimeError("Custom event page is missing #wrap")
            return wrap, "#wrap:event_custom", "parsed", None, None

    node, selector = _select_content_node(soup, row["source_id"])
    if selector in {"body", "document"}:
        raise RuntimeError(f"Unsupported broad content fallback: {selector}")
    return node, selector, "parsed", faq_validated, policy_validated


def classify_title(
    row: dict[str, Any],
    content_text: str,
    *,
    content_status: str,
) -> str:
    title = normalize_space(row.get("title"))
    probe = normalize_space(re.sub(r"^\[종료\]\s*", "", title))
    if probe and _compact_text(probe) in _compact_text(content_text):
        return "matched_content"
    if row["source_id"] == "dnf_account_policy" and row["source_item_id"] in title:
        return "policy_revision_title_validated"
    if row["source_id"] == "dnf_game_guide":
        return "official_guide_registry_title"
    if row["source_id"] == "dnf_monthly_item":
        return "official_listing_title"
    if row["source_id"] == "dnf_event":
        return (
            "official_listing_title_source_unavailable"
            if content_status == "unavailable_redirect"
            else "official_listing_title"
        )
    return "unresolved_mismatch"


def classify_image_dependency(
    *,
    source_id: str,
    selector: str,
    text: str,
    image_count: int,
    table_count: int,
    price_signals: list[str],
) -> tuple[str, list[str]]:
    high_reasons: list[str] = []
    medium_reasons: list[str] = []
    text_chars = len(text)
    custom_event = selector == "#wrap:event_custom"
    if custom_event and text_chars < 400:
        high_reasons.append("custom_event_short_dom_text_or_css_assets")
    if image_count and text_chars < 160:
        high_reasons.append("short_text_with_images")
    if image_count >= 3 and table_count == 0 and text_chars / image_count < 80:
        if custom_event or (source_id in {"dnf_faq", "dnf_game_guide"} and text_chars < 600):
            high_reasons.append("low_text_per_image_without_table")
        else:
            medium_reasons.append("many_images_relative_to_dom_text")
    if (
        source_id in {"dnf_monthly_item", "dnf_seria_shop"}
        and image_count
        and not price_signals
        and table_count == 0
        and text_chars < 600
    ):
        high_reasons.append("commerce_page_image_without_price_signal")
    if high_reasons:
        return "high", high_reasons
    if medium_reasons:
        return "medium", medium_reasons
    if custom_event:
        return "medium", ["custom_event_assets_require_visual_review"]
    if image_count:
        return "low", ["images_present_with_substantial_dom_text"]
    return "none", []


def classify_guide_change(
    previous_preview: dict[str, Any],
    baseline: dict[str, Any] | None,
    extracted_text: str,
) -> tuple[str | None, str | None]:
    if previous_preview.get("source_id") != "dnf_game_guide":
        return None, None
    observed_match = re.search(
        r"이 문서는\s*(20\d{2}-\d{2}-\d{2})에 업데이트", extracted_text
    )
    observed_updated_at = observed_match.group(1) if observed_match else None
    ratio = previous_preview.get("refresh_length_ratio")
    if ratio is None:
        return "baseline_not_comparable", observed_updated_at
    if 0.7 <= ratio <= 1.5:
        return "within_expected_range", observed_updated_at
    collected_at = normalize_space((baseline or {}).get("metadata", {}).get("collected_at"))
    collected_date = collected_at[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", collected_at) else None
    if observed_updated_at and collected_date and observed_updated_at > collected_date:
        return "official_revision_after_baseline", observed_updated_at
    return "unresolved_material_change", observed_updated_at


def _base_preview(
    row: dict[str, Any],
    ledger_row: dict[str, Any],
    previous_preview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "preview_schema_version": PREVIEW_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "canonical_url": row["canonical_url"],
        "source_id": row["source_id"],
        "source_kind": row["source_kind"],
        "registry_status": row["status"],
        "registry_category": row["category"],
        "eligible_for_collection": row["eligible_for_collection"],
        "default_exposure": row["default_exposure"],
        "final_url": ledger_row["final_url"],
        "content_status": "parser_failed",
        "normalization_eligible": False,
        "title": normalize_space(row.get("title")),
        "title_source": "official_registry",
        "title_validation_status": "unvalidated",
        "extracted_text": "",
        "heading_count": 0,
        "table_count": 0,
        "image_count": 0,
        "noise_nodes_removed": 0,
        "navigation_residue_terms": [],
        "published_at": row.get("published_at"),
        "valid_from": row.get("period_start"),
        "valid_to": row.get("period_end"),
        "date_signals": [],
        "price_signals": [],
        "content_selector": None,
        "faq_locator_validated": None,
        "policy_revision_validated": None,
        "image_dependency_risk": "unknown",
        "image_dependency_reasons": [],
        "guide_change_classification": None,
        "observed_updated_at": None,
        "previous_refresh_length_ratio": previous_preview.get("refresh_length_ratio"),
        "extraction_warnings": [],
        "raw_snapshot_path": ledger_row["raw_snapshot_path"],
        "raw_content_hash": ledger_row["content_hash"],
        "error": None,
    }


def extract_hardened_preview(
    row: dict[str, Any],
    ledger_row: dict[str, Any],
    previous_preview: dict[str, Any],
    raw_html: bytes,
    guide_baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    preview = _base_preview(row, ledger_row, previous_preview)
    node, selector, status, faq_validated, policy_validated = select_hardened_content(
        row, ledger_row, raw_html
    )
    preview.update(
        content_status=status,
        content_selector=selector,
        faq_locator_validated=faq_validated,
        policy_revision_validated=policy_validated,
    )
    if status == "unavailable_redirect":
        preview.update(
            title_validation_status=classify_title(
                row, "", content_status=status
            ),
            image_dependency_risk="unknown",
            extraction_warnings=["source_unavailable_redirect"],
            error=(
                f"Canonical path {_path_only(row['canonical_url'])} redirected to "
                f"{_path_only(ledger_row['final_url'])}"
            ),
        )
        return preview
    if not isinstance(node, Tag):
        raise RuntimeError("Parsed content does not have a DOM node")

    text, headings, tables, images, noise_removed, navigation_hits = (
        structured_text_hardened(node)
    )
    title_status = classify_title(row, text, content_status=status)
    price_signals = _extract_price_signals(text)
    image_risk, image_reasons = classify_image_dependency(
        source_id=row["source_id"],
        selector=selector,
        text=text,
        image_count=images,
        table_count=tables,
        price_signals=price_signals,
    )
    guide_change, observed_updated_at = classify_guide_change(
        previous_preview, guide_baseline, text
    )
    warnings: list[str] = []
    # Policy prose legitimately names the Terms of Use, Privacy Policy, and
    # Customer Center together. Its exact revision node is already validated,
    # so those terms are content evidence rather than site-chrome residue.
    if row["source_id"] != "dnf_account_policy" and len(navigation_hits) >= 3:
        warnings.append("navigation_or_footer_residue")
    if title_status == "unresolved_mismatch":
        warnings.append("unresolved_title_mismatch")
    if images:
        warnings.append("image_content_not_ocr")
    if image_risk in {"high", "medium"}:
        warnings.append(f"image_dependency_{image_risk}")
    if guide_change == "official_revision_after_baseline":
        warnings.append("guide_official_revision_after_baseline")
    elif guide_change == "unresolved_material_change":
        warnings.append("guide_unresolved_material_change")
    if not text:
        raise RuntimeError("Parsed content text is empty")

    preview.update(
        content_status="parsed",
        normalization_eligible=image_risk != "high",
        title_validation_status=title_status,
        extracted_text=text,
        heading_count=headings,
        table_count=tables,
        image_count=images,
        noise_nodes_removed=noise_removed,
        navigation_residue_terms=navigation_hits,
        date_signals=_extract_date_signals(text),
        price_signals=price_signals,
        image_dependency_risk=image_risk,
        image_dependency_reasons=image_reasons,
        guide_change_classification=guide_change,
        observed_updated_at=observed_updated_at,
        extraction_warnings=warnings,
    )
    return preview


def build_hardened_previews(
    *,
    registry: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    previous_previews: list[dict[str, Any]],
    guide_baselines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    registry_by_url = {row["canonical_url"]: row for row in registry}
    previous_by_url = {row["canonical_url"]: row for row in previous_previews}
    guide_by_url = {
        row["source_url"]: row for row in guide_baselines if row.get("source_url")
    }
    ledger_urls = [row["canonical_url"] for row in ledger]
    if len(ledger_urls) != len(set(ledger_urls)):
        raise RuntimeError("Ledger contains duplicate canonical URLs")
    if set(ledger_urls) - registry_by_url.keys():
        raise RuntimeError("Ledger contains URLs missing from registry")
    if set(ledger_urls) != previous_by_url.keys():
        raise RuntimeError("Ledger and previous preview URL sets differ")

    previews = []
    for ledger_row in sorted(ledger, key=lambda row: (row["source_id"], row["canonical_url"])):
        row = registry_by_url[ledger_row["canonical_url"]]
        previous = previous_by_url[ledger_row["canonical_url"]]
        raw_path = Path(ledger_row["raw_snapshot_path"])
        if not raw_path.is_file() or file_sha256(raw_path) != ledger_row["content_hash"]:
            raise RuntimeError(f"Raw snapshot hash mismatch: {raw_path}")
        try:
            preview = extract_hardened_preview(
                row,
                ledger_row,
                previous,
                raw_path.read_bytes(),
                guide_by_url.get(row["canonical_url"]),
            )
        except Exception as exc:
            preview = _base_preview(row, ledger_row, previous)
            preview["error"] = str(exc)
            preview["extraction_warnings"] = ["parser_failed"]
        previews.append(preview)
    return previews


def _build_report(
    previews: list[dict[str, Any]],
    *,
    parsed_at: str,
    manifest_path: Path,
    manifest_sha256: str,
    preview_path: Path,
    preview_sha256: str,
) -> dict[str, Any]:
    status_counts = Counter(row["content_status"] for row in previews)
    risk_counts = Counter(row["image_dependency_risk"] for row in previews)
    title_counts = Counter(row["title_validation_status"] for row in previews)
    guide_counts = Counter(
        row["guide_change_classification"]
        for row in previews
        if row["guide_change_classification"] is not None
    )
    parsed = [row for row in previews if row["content_status"] == "parsed"]
    parser_failed = [row for row in previews if row["content_status"] == "parser_failed"]
    unavailable = [
        row for row in previews if row["content_status"] == "unavailable_redirect"
    ]
    body_fallback = [
        row for row in previews if row["content_selector"] in {"body", "document"}
    ]
    navigation_residue = [
        row for row in previews if "navigation_or_footer_residue" in row["extraction_warnings"]
    ]
    unresolved_titles = [
        row for row in previews if row["title_validation_status"] == "unresolved_mismatch"
    ]
    empty_parsed = [
        row for row in parsed if not row["title"].strip() or not row["extracted_text"].strip()
    ]
    faq_errors = [
        row
        for row in previews
        if row["source_id"] == "dnf_faq" and row["faq_locator_validated"] is not True
    ]
    policy_errors = [
        row
        for row in previews
        if row["source_id"] == "dnf_account_policy"
        and row["policy_revision_validated"] is not True
    ]
    unresolved_guide = [
        row
        for row in previews
        if row["guide_change_classification"] == "unresolved_material_change"
    ]
    default_unavailable = [row for row in unavailable if row["default_exposure"]]
    default_high_image = [
        row
        for row in parsed
        if row["default_exposure"] and row["image_dependency_risk"] == "high"
    ]
    parser_go = not any(
        (
            parser_failed,
            body_fallback,
            navigation_residue,
            unresolved_titles,
            empty_parsed,
            faq_errors,
            policy_errors,
            unresolved_guide,
        )
    )
    document_go = parser_go and not default_unavailable and not default_high_image

    by_source: dict[str, Any] = {}
    for source_id in sorted({row["source_id"] for row in previews}):
        rows = [row for row in previews if row["source_id"] == source_id]
        by_source[source_id] = {
            "total": len(rows),
            "content_status": dict(sorted(Counter(row["content_status"] for row in rows).items())),
            "image_dependency_risk": dict(
                sorted(Counter(row["image_dependency_risk"] for row in rows).items())
            ),
            "normalization_candidates": sum(row["normalization_eligible"] for row in rows),
        }

    warning_counts = Counter(
        warning for row in previews for warning in row["extraction_warnings"]
    )
    warning_rows = [
        {
            "canonical_url": row["canonical_url"],
            "source_id": row["source_id"],
            "content_status": row["content_status"],
            "default_exposure": row["default_exposure"],
            "warnings": row["extraction_warnings"],
            "error": row["error"],
        }
        for row in previews
        if row["extraction_warnings"]
    ]
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "parsed_at": parsed_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "preview_path": preview_path.as_posix(),
        "preview_sha256": preview_sha256,
        "summary": {
            "total": len(previews),
            "parsed": status_counts["parsed"],
            "unavailable_redirect": status_counts["unavailable_redirect"],
            "parser_failed": status_counts["parser_failed"],
            "normalization_candidates": sum(
                row["normalization_eligible"] for row in previews
            ),
            "body_fallback": len(body_fallback),
            "navigation_or_footer_residue": len(navigation_residue),
            "unresolved_title_mismatch": len(unresolved_titles),
            "empty_parsed_title_or_text": len(empty_parsed),
            "faq_resolution_errors": len(faq_errors),
            "policy_revision_errors": len(policy_errors),
            "raw_hash_mismatches": 0,
            "unresolved_guide_changes": len(unresolved_guide),
            "default_exposed_unavailable": len(default_unavailable),
            "default_exposed_high_image_risk": len(default_high_image),
        },
        "content_status_distribution": dict(sorted(status_counts.items())),
        "image_dependency_risk_distribution": dict(sorted(risk_counts.items())),
        "title_validation_distribution": dict(sorted(title_counts.items())),
        "guide_change_distribution": dict(sorted(guide_counts.items())),
        "warning_distribution": dict(sorted(warning_counts.items())),
        "by_source": by_source,
        "warning_rows": warning_rows,
        "gate_details": {
            "parser_failed_urls": [row["canonical_url"] for row in parser_failed],
            "unavailable_redirect_urls": [row["canonical_url"] for row in unavailable],
            "default_exposed_unavailable_urls": [
                row["canonical_url"] for row in default_unavailable
            ],
            "default_exposed_high_image_risk_urls": [
                row["canonical_url"] for row in default_high_image
            ],
            "unresolved_title_urls": [row["canonical_url"] for row in unresolved_titles],
            "navigation_residue_urls": [row["canonical_url"] for row in navigation_residue],
            "unresolved_guide_change_urls": [row["canonical_url"] for row in unresolved_guide],
        },
        "parser_hardening_decision": "GO" if parser_go else "NO-GO",
        "document_v3_promotion_decision": "GO" if document_go else "NO-GO",
    }


def render_report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DNF RAG v3 상세 parser 품질 보강",
        "",
        f"- parser version: `{report['parser_version']}`",
        f"- parsed_at: `{report['parsed_at']}`",
        f"- preview SHA-256: `{report['preview_sha256']}`",
        f"- manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## 결과",
        "",
        "| total | parsed | unavailable redirect | parser failed | normalization candidates |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {summary['total']} | {summary['parsed']} | {summary['unavailable_redirect']} | "
            f"{summary['parser_failed']} | {summary['normalization_candidates']} |"
        ),
        "",
        "## 출처별 상태",
        "",
        "| source | total | content status | image risk | candidates |",
        "|---|---:|---|---|---:|",
    ]
    for source_id, values in report["by_source"].items():
        status = ", ".join(f"{k}:{v}" for k, v in values["content_status"].items())
        risk = ", ".join(
            f"{k}:{v}" for k, v in values["image_dependency_risk"].items()
        )
        lines.append(
            f"| `{source_id}` | {values['total']} | {status} | {risk} | "
            f"{values['normalization_candidates']} |"
        )
    lines.extend(["", "## 품질 게이트", ""])
    for key, value in summary.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## 판정",
            "",
            f"- parser hardening: **{report['parser_hardening_decision']}**",
            f"- DocumentV3 promotion: **{report['document_v3_promotion_decision']}**",
            "",
            "이 사이클은 frozen raw를 재추출했으며 네트워크 수집, DocumentV3 재빌드, ChunkV3, 검색, 학습은 실행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def freeze_hardening_artifacts(
    previews: list[dict[str, Any]],
    *,
    parsed_at: str,
    registry_path: Path,
    ledger_path: Path,
    previous_preview_path: Path,
    collection_manifest_path: Path,
    guide_baseline_path: Path,
    collection_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    preview_bytes = _serialize_jsonl(
        previews, lambda row: (row["source_id"], row["canonical_url"])
    )
    preview_sha256 = hashlib.sha256(preview_bytes).hexdigest()
    preview_path = collection_dir / f"detail_hardened_extraction_preview_{preview_sha256}.jsonl"
    write_immutable(preview_path, preview_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "parsed_at": parsed_at,
        "registry_path": registry_path.as_posix(),
        "registry_sha256": file_sha256(registry_path),
        "ledger_path": ledger_path.as_posix(),
        "ledger_sha256": file_sha256(ledger_path),
        "previous_preview_path": previous_preview_path.as_posix(),
        "previous_preview_sha256": file_sha256(previous_preview_path),
        "collection_manifest_path": collection_manifest_path.as_posix(),
        "collection_manifest_sha256": file_sha256(collection_manifest_path),
        "guide_baseline_path": guide_baseline_path.as_posix(),
        "guide_baseline_sha256": file_sha256(guide_baseline_path),
        "preview_path": preview_path.as_posix(),
        "preview_sha256": preview_sha256,
        "preview_row_count": len(previews),
        "raw_snapshot_count": len(
            {row["raw_snapshot_path"] for row in previews if row["raw_snapshot_path"]}
        ),
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = collection_dir / f"detail_parser_hardening_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = _build_report(
        previews,
        parsed_at=parsed_at,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        preview_path=preview_path,
        preview_sha256=preview_sha256,
    )
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    report_json_path = report_dir / f"detail_parser_hardening_{report_sha256}.json"
    report_md_path = report_dir / f"detail_parser_hardening_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_md_path, render_report_markdown(report).encode("utf-8"))
    return {
        "preview_path": preview_path.as_posix(),
        "preview_sha256": preview_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_md_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": report["by_source"],
        "parser_hardening_decision": report["parser_hardening_decision"],
        "document_v3_promotion_decision": report["document_v3_promotion_decision"],
    }


def harden_detail_parsers(
    *,
    parsed_at: str,
    registry_path: Path,
    ledger_path: Path,
    previous_preview_path: Path,
    collection_manifest_path: Path,
    guide_baseline_path: Path,
    collection_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    parse_fixed_timestamp(parsed_at)
    previews = build_hardened_previews(
        registry=read_jsonl(registry_path),
        ledger=read_jsonl(ledger_path),
        previous_previews=read_jsonl(previous_preview_path),
        guide_baselines=read_jsonl(guide_baseline_path),
    )
    return freeze_hardening_artifacts(
        previews,
        parsed_at=parsed_at,
        registry_path=registry_path,
        ledger_path=ledger_path,
        previous_preview_path=previous_preview_path,
        collection_manifest_path=collection_manifest_path,
        guide_baseline_path=guide_baseline_path,
        collection_dir=collection_dir,
        report_dir=report_dir,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-extract frozen DNF v3 raw details with hardened source parsers."
    )
    parser.add_argument("--parsed-at", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--previous-preview", type=Path, default=DEFAULT_PREVIOUS_PREVIEW)
    parser.add_argument("--collection-manifest", type=Path, default=DEFAULT_COLLECTION_MANIFEST)
    parser.add_argument("--guide-baseline", type=Path, default=DEFAULT_GUIDE_BASELINE)
    parser.add_argument("--collection-dir", type=Path, default=DEFAULT_COLLECTION_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    for path in (
        args.registry,
        args.ledger,
        args.previous_preview,
        args.collection_manifest,
        args.guide_baseline,
    ):
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    result = harden_detail_parsers(
        parsed_at=args.parsed_at,
        registry_path=args.registry,
        ledger_path=args.ledger,
        previous_preview_path=args.previous_preview,
        collection_manifest_path=args.collection_manifest,
        guide_baseline_path=args.guide_baseline,
        collection_dir=args.collection_dir,
        report_dir=args.report_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
