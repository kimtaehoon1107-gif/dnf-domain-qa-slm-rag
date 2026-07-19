from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import canonicalize_url, file_sha256


COLLECTOR_VERSION = "dnf_detail_pilot_v3.0"
FULL_COLLECTOR_VERSION = "dnf_detail_full_v3.0"
LEDGER_SCHEMA_VERSION = "dnf_detail_collection_ledger_v3.0"
MANIFEST_SCHEMA_VERSION = "dnf_detail_collection_manifest_v3.0"
PREVIEW_SCHEMA_VERSION = "dnf_detail_extraction_preview_v3.0"
REPORT_SCHEMA_VERSION = "dnf_detail_collection_pilot_v3.1"
FULL_REPORT_SCHEMA_VERSION = "dnf_detail_full_collection_v3.1"
CHECKPOINT_SCHEMA_VERSION = "dnf_detail_full_checkpoint_v3.0"

DEFAULT_REGISTRY = Path(
    "data/v3/discovery/"
    "source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
)
DEFAULT_REGISTRY_MANIFEST = Path(
    "data/v3/discovery/"
    "source_registry_manifest_4cbd8c441fd694ec16ad30b6b42c4c6f28326dc9a768d883399419ef87ee9ea2.json"
)
DEFAULT_GUIDE_BASELINE = Path("data/raw/guide_docs.jsonl")
DEFAULT_DETAIL_DIR = Path("data/v3/detail_snapshots")
DEFAULT_COLLECTION_DIR = Path("data/v3/collections")
DEFAULT_REPORT_DIR = Path("reports/v3")

ALLOWED_OUTCOMES = {"success", "failed", "blocked", "parser_failed"}
NOTICE_KINDS = (
    "maintenance",
    "known_issue",
    "hotfix",
    "account_policy",
    "enforcement_notice",
    "general_notice",
)
FAQ_BUCKETS = (
    "아이디정보/보안",
    "설치/실행",
    "게임문의",
    "복구",
    "결제",
    "PC방",
    "이벤트",
    "던파ON",
)

LEDGER_REQUIRED_FIELDS = (
    "registry_sha256",
    "source_id",
    "source_kind",
    "canonical_url",
    "canonical_url_kind",
    "eligible_for_collection",
    "default_exposure",
    "fetch_status",
    "http_status",
    "fetched_at",
    "content_hash",
    "raw_snapshot_path",
    "collector_version",
    "retry_count",
    "error",
)

PREVIEW_REQUIRED_FIELDS = (
    "canonical_url",
    "source_id",
    "title",
    "extracted_text",
    "heading_count",
    "table_count",
    "image_count",
    "published_at",
    "valid_from",
    "valid_to",
    "price_signals",
    "extraction_warnings",
    "raw_snapshot_path",
)


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_block(value: Any) -> str:
    lines = [normalize_space(line) for line in str(value or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _canonical_json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    if indent is None:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
    return (text + "\n").encode("utf-8")


def _serialize_jsonl(rows: list[dict[str, Any]], sort_key: Callable[[dict[str, Any]], Any]) -> bytes:
    return b"".join(
        _canonical_json_bytes(row)
        for row in sorted(rows, key=sort_key)
    )


def write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError(f"Immutable artifact collision: {path}")
        return
    path.write_bytes(content)


def parse_fixed_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Invalid ISO timestamp: {value!r}") from exc


def _stable_key(row: dict[str, Any]) -> tuple[str, str]:
    url = row["canonical_url"]
    return hashlib.sha256(url.encode("utf-8")).hexdigest(), url


def _take(
    rows: list[dict[str, Any]],
    count: int,
    *,
    prefer_eligible: bool = True,
) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            0 if (row["eligible_for_collection"] or not prefer_eligible) else 1,
            *_stable_key(row),
        ),
    )[:count]


def _annotate(rows: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    return [dict(row, pilot_bucket=bucket) for row in rows]


def faq_bucket(row: dict[str, Any]) -> str:
    text = normalize_space(f"{row.get('category', '')} {row.get('title', '')}")
    if "던파ON" in text:
        return "던파ON"
    if re.search(r"PC방|지정PC|던파PC", text, re.IGNORECASE):
        return "PC방"
    if "복구" in text:
        return "복구"
    if re.search(r"결제|충전|구매|세라|캐시|청약철회", text):
        return "결제"
    if re.search(r"설치|실행|접속|튜김|끊김|렉", text):
        return "설치/실행"
    if "이벤트" in text:
        return "이벤트"
    if re.search(
        r"아이디|계정|비밀번호|OTP|보안|마이핀|본인인증|도용|해킹|IP차단|간편잠금|고블린패드",
        text,
        re.IGNORECASE,
    ):
        return "아이디정보/보안"
    return "게임문의"


def select_pilot_rows(
    registry: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in registry:
        by_source[row["source_id"]].append(row)

    selected: list[dict[str, Any]] = []
    adjustments: list[str] = []

    notice_rows = by_source["dnf_notice"]
    for source_kind in NOTICE_KINDS:
        candidates = [
            row
            for row in notice_rows
            if row["source_kind"] == source_kind and row["eligible_for_collection"]
        ]
        chosen = _take(candidates, 2)
        selected.extend(_annotate(chosen, f"notice:{source_kind}"))
        if len(chosen) < 2:
            adjustments.append(f"notice:{source_kind} selected {len(chosen)}/2")

    update_rows = by_source["dnf_update"]
    selected.extend(
        _annotate(
            _take(
                [row for row in update_rows if row["source_kind"] == "patch_note" and row["eligible_for_collection"]],
                4,
            ),
            "update:live_patch",
        )
    )
    selected.extend(
        _annotate(
            _take(
                [row for row in update_rows if row["source_kind"] == "preview_patch" and row["eligible_for_collection"]],
                2,
            ),
            "update:preview_control",
        )
    )

    event_rows = by_source["dnf_event"]
    upcoming = [row for row in event_rows if row["status"] == "upcoming"]
    if upcoming:
        event_plan = (("current", 2), ("upcoming", 2), ("expired", 2))
    else:
        event_plan = (("current", 3), ("expired", 3))
        adjustments.append("event: no upcoming rows in frozen registry; allocated sample to current/expired")
    for status, count in event_plan:
        candidates = [row for row in event_rows if row["status"] == status]
        selected.extend(_annotate(_take(candidates, count), f"event:{status}"))

    guide_rows = by_source["dnf_game_guide"]
    categories = sorted({row["category"] for row in guide_rows})[:6]
    for category in categories:
        candidates = [row for row in guide_rows if row["category"] == category]
        selected.extend(_annotate(_take(candidates, 1), f"guide:{category}"))
    if len(categories) < 6:
        adjustments.append(f"guide: selected {len(categories)}/6 distinct categories")

    faq_rows = by_source["dnf_faq"]
    for bucket in FAQ_BUCKETS:
        candidates = [row for row in faq_rows if faq_bucket(row) == bucket]
        if bucket == "이벤트":
            exact_event = [row for row in candidates if row["category"] == "이벤트"]
            chosen = _take(exact_event or candidates, 2, prefer_eligible=False)
        else:
            chosen = _take(candidates, 2)
        selected.extend(_annotate(chosen, f"faq:{bucket}"))
        if len(chosen) < 2:
            adjustments.append(f"faq:{bucket} selected {len(chosen)}/2")

    policy_rows = sorted(
        by_source["dnf_account_policy"],
        key=lambda row: (row["published_at"] or "", row["canonical_url"]),
        reverse=True,
    )
    policy_indices = (0, 1, len(policy_rows) // 3, (2 * len(policy_rows)) // 3, len(policy_rows) - 1)
    seen_policy_urls: set[str] = set()
    for label, index in zip(("current", "recent", "middle_recent", "middle_old", "oldest"), policy_indices):
        row = policy_rows[index]
        if row["canonical_url"] not in seen_policy_urls:
            selected.extend(_annotate([row], f"policy:{label}"))
            seen_policy_urls.add(row["canonical_url"])

    shop_rows = by_source["dnf_seria_shop"]
    shop_plan = (
        ("active_no_end", lambda row: row["status"] == "current" and not row["period_end"]),
        ("active_has_end", lambda row: row["status"] == "current" and bool(row["period_end"])),
        ("expired_eligible", lambda row: row["status"] == "expired" and row["eligible_for_collection"]),
        ("expired_control", lambda row: row["status"] == "expired" and not row["eligible_for_collection"]),
    )
    for label, predicate in shop_plan:
        chosen = _take([row for row in shop_rows if predicate(row)], 2)
        selected.extend(_annotate(chosen, f"shop:{label}"))
        if len(chosen) < 2:
            adjustments.append(f"shop:{label} selected {len(chosen)}/2")

    monthly_rows = by_source["dnf_monthly_item"]
    monthly_plan = (
        ("current", lambda row: row["status"] == "current", 1),
        ("expired_eligible", lambda row: row["status"] == "expired" and row["eligible_for_collection"], 2),
        ("expired_control", lambda row: row["status"] == "expired" and not row["eligible_for_collection"], 2),
    )
    for label, predicate, count in monthly_plan:
        chosen = _take([row for row in monthly_rows if predicate(row)], count)
        selected.extend(_annotate(chosen, f"monthly:{label}"))
        if len(chosen) < count:
            adjustments.append(f"monthly:{label} selected {len(chosen)}/{count}")

    selected = sorted(selected, key=lambda row: (row["source_id"], row["pilot_bucket"], row["canonical_url"]))
    urls = [row["canonical_url"] for row in selected]
    if len(urls) != len(set(urls)):
        raise RuntimeError("Pilot selection contains duplicate canonical URLs")
    counts = Counter(row["source_id"] for row in selected)
    return selected, {
        "selection_version": COLLECTOR_VERSION,
        "requested_by_source": {
            "dnf_notice": 12,
            "dnf_update": 6,
            "dnf_event": 6,
            "dnf_game_guide": 6,
            "dnf_faq": 16,
            "dnf_account_policy": 5,
            "dnf_seria_shop": 8,
            "dnf_monthly_item": 5,
        },
        "selected_by_source": dict(sorted(counts.items())),
        "selected_total": len(selected),
        "adjustments": adjustments,
    }


def select_full_rows(
    registry: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = [
        dict(
            row,
            pilot_bucket=f"full:{row['source_kind']}:{row['status']}",
        )
        for row in registry
        if row["eligible_for_collection"]
    ]
    selected.sort(key=lambda row: (row["source_id"], row["canonical_url"]))
    urls = [row["canonical_url"] for row in selected]
    if len(urls) != len(set(urls)):
        raise RuntimeError("Full selection contains duplicate canonical URLs")
    if any(not row["eligible_for_collection"] for row in selected):
        raise RuntimeError("Full selection contains an ineligible row")
    return selected, {
        "selection_version": FULL_COLLECTOR_VERSION,
        "policy": "all frozen registry rows with eligible_for_collection=true",
        "selected_by_source": dict(
            sorted(Counter(row["source_id"] for row in selected).items())
        ),
        "selected_total": len(selected),
        "default_exposure_true": sum(row["default_exposure"] for row in selected),
        "default_exposure_false": sum(not row["default_exposure"] for row in selected),
        "adjustments": [],
    }


@dataclass(frozen=True)
class FetchResult:
    status: str
    http_status: int | None
    content: bytes
    retry_count: int
    error: str | None
    final_url: str


class RateLimitedFetcher:
    def __init__(
        self,
        *,
        interval_seconds: float,
        retries: int,
        timeout_seconds: float,
        user_agent: str = "DNF-RAG-v3-detail-pilot/0.1",
    ) -> None:
        self.interval_seconds = interval_seconds
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    f"{user_agent} "
                    "(official-document-validation; contact=local-research)"
                )
            }
        )
        self._last_request_at: float | None = None
        self._cache: dict[str, FetchResult] = {}

    def __call__(self, url: str) -> FetchResult:
        if url in self._cache:
            return self._cache[url]
        last_error: Exception | None = None
        last_http_status: int | None = None
        last_content = b""
        last_final_url = url
        for attempt in range(self.retries + 1):
            if self._last_request_at is not None:
                remaining = self.interval_seconds - (time.monotonic() - self._last_request_at)
                if remaining > 0:
                    time.sleep(remaining)
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                self._last_request_at = time.monotonic()
                content = response.content
                last_http_status = response.status_code
                last_content = content
                last_final_url = response.url
                blocked = response.status_code in {401, 403, 429} or any(
                    signal in content[:20000].lower()
                    for signal in (b"access denied", b"request blocked", b"captcha")
                )
                if blocked:
                    result = FetchResult(
                        "blocked",
                        response.status_code,
                        content,
                        attempt,
                        f"Blocked response: HTTP {response.status_code}",
                        response.url,
                    )
                    self._cache[url] = result
                    return result
                if 200 <= response.status_code < 300 and content:
                    result = FetchResult(
                        "success", response.status_code, content, attempt, None, response.url
                    )
                    self._cache[url] = result
                    return result
                last_error = RuntimeError(f"HTTP {response.status_code} or empty response")
            except requests.RequestException as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
            if attempt < self.retries:
                time.sleep(min(4.0, 0.5 * (2**attempt)))
        result = FetchResult(
            "failed",
            last_http_status,
            last_content,
            self.retries,
            str(last_error),
            last_final_url,
        )
        self._cache[url] = result
        return result


def resolve_fetch_url(row: dict[str, Any]) -> str:
    if row["canonical_url_kind"] == "synthetic_inline_item_locator":
        return row["listing_url"]
    if (
        row["source_id"] == "dnf_monthly_item"
        and row["canonical_url"].rstrip("/").endswith("/community/news/monthlyitem")
    ):
        return row["canonical_url"].rstrip("/") + "/"
    return row["canonical_url"]


def resolve_faq_node(raw_html: bytes, source_item_id: str) -> Tag:
    soup = BeautifulSoup(raw_html, "html.parser")
    node = soup.find("li", attrs={"data-no": source_item_id})
    if not isinstance(node, Tag):
        raise RuntimeError(f"FAQ data-no not found in listing snapshot: {source_item_id}")
    return node


def validate_policy_revision(raw_html: bytes, expected_revision: str) -> None:
    soup = BeautifulSoup(raw_html, "html.parser")
    selected = soup.select("#revisionList option[selected]")
    selected_values = [normalize_space(option.get("value")) for option in selected]
    if selected_values != [expected_revision]:
        raise RuntimeError(
            f"Policy revision mismatch: expected {expected_revision}, selected {selected_values}"
        )


def _select_content_node(soup: BeautifulSoup, source_id: str) -> tuple[Tag, str]:
    selectors_by_source = {
        "dnf_game_guide": ("article.content.gg_template", ".guide_view", ".view_content"),
        "dnf_account_policy": ("section.content", ".policy_cont", ".terms_cont"),
        "dnf_event": (
            "section.content.news",
            ".event_wrap",
            ".event-container",
            "main",
            "#contents",
            "section.content",
        ),
    }
    selectors = selectors_by_source.get(
        source_id,
        ("section.content.news", ".view_content", ".news_view", "article.board_view", "section.content"),
    )
    for selector in selectors:
        candidates = soup.select(selector)
        if candidates:
            node = max(candidates, key=lambda item: len(normalize_space(item.get_text(" ", strip=True))))
            if normalize_space(node.get_text(" ", strip=True)):
                return node, selector
    if isinstance(soup.body, Tag):
        return soup.body, "body"
    return soup, "document"


def _table_text(table: Tag) -> str:
    lines = []
    for row in table.select("tr"):
        cells = [normalize_space(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if cells:
            lines.append("| " + " | ".join(cells) + " |")
    return "\n[TABLE]\n" + "\n".join(lines) + "\n[/TABLE]\n"


def structured_text(node: Tag) -> tuple[str, int, int, int]:
    clone_soup = BeautifulSoup(str(node), "html.parser")
    root = clone_soup.find()
    if not isinstance(root, Tag):
        return "", 0, 0, 0
    for tag in root.select("script, style, nav, footer, form, button, noscript"):
        tag.decompose()
    heading_count = len(root.find_all(re.compile(r"^h[1-6]$")))
    table_count = len(root.find_all("table"))
    image_count = len(root.find_all("img"))
    for table in list(root.find_all("table")):
        table.replace_with(NavigableString(_table_text(table)))
    for heading in root.find_all(re.compile(r"^h[1-6]$")):
        level = int(heading.name[1])
        heading.insert_before(NavigableString(f"\n{'#' * level} "))
        heading.insert_after(NavigableString("\n"))
    for block in root.find_all(["p", "li", "dt", "dd", "caption", "pre", "blockquote", "br"]):
        block.insert_after(NavigableString("\n"))
    return normalize_block(root.get_text(" ")), heading_count, table_count, image_count


def _extract_date_signals(text: str) -> list[str]:
    values: list[str] = []
    for year, month, day in re.findall(r"(20\d{2})[.\-/\ub144]\s*(\d{1,2})[.\-/\uc6d4]\s*(\d{1,2})", text):
        value = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        if value not in values:
            values.append(value)
    return values[:30]


def _extract_price_signals(text: str) -> list[str]:
    patterns = (
        r"(?:상점s*)?판매s*가격\s*[:：]?\s*[^\n|]{0,40}",
        r"(?:가격|판매가|상점판매가)\s*[:：]?\s*[^\n|]{0,40}",
        r"\d[\d,]*(?:\.\d+)?\s*(?:세라|골드|원|M)(?:\b|\s)",
    )
    signals: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            signal = normalize_space(match.group(0))
            if signal and signal not in signals:
                signals.append(signal)
    return signals[:20]


def load_guide_baselines(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {
        canonicalize_url(row["source_url"]): row
        for row in read_jsonl(path)
        if row.get("source_url")
    }


def make_empty_preview(row: dict[str, Any], raw_snapshot_path: str | None) -> dict[str, Any]:
    return {
        "preview_schema_version": PREVIEW_SCHEMA_VERSION,
        "canonical_url": row["canonical_url"],
        "source_id": row["source_id"],
        "source_kind": row["source_kind"],
        "registry_status": row["status"],
        "pilot_bucket": row["pilot_bucket"],
        "eligible_for_collection": row["eligible_for_collection"],
        "default_exposure": row["default_exposure"],
        "fetch_status": "failed",
        "title": "",
        "extracted_text": "",
        "heading_count": 0,
        "table_count": 0,
        "image_count": 0,
        "published_at": row["published_at"],
        "valid_from": row["period_start"],
        "valid_to": row["period_end"],
        "date_signals": [],
        "price_signals": [],
        "extraction_warnings": [],
        "raw_snapshot_path": raw_snapshot_path,
        "content_selector": None,
        "faq_locator_validated": None,
        "policy_revision_validated": None,
        "baseline_text_hash": None,
        "baseline_text_chars": None,
        "refresh_text_hash": None,
        "refresh_text_chars": None,
        "refresh_length_ratio": None,
        "refresh_text_match": None,
    }


def extract_preview(
    row: dict[str, Any],
    raw_html: bytes,
    raw_snapshot_path: str,
    guide_baselines: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    preview = make_empty_preview(row, raw_snapshot_path)
    soup = BeautifulSoup(raw_html, "html.parser")
    warnings: list[str] = []
    if row["source_id"] == "dnf_faq":
        node = resolve_faq_node(raw_html, row["source_item_id"])
        selector = f'li[data-no="{row["source_item_id"]}"]'
        preview["faq_locator_validated"] = True
    else:
        if row["source_id"] == "dnf_account_policy":
            validate_policy_revision(raw_html, row["source_item_id"])
            preview["policy_revision_validated"] = True
        node, selector = _select_content_node(soup, row["source_id"])
    text, heading_count, table_count, image_count = structured_text(node)
    title = normalize_space(row.get("title"))
    if not title:
        heading = node.find(re.compile(r"^h[1-3]$"))
        title = normalize_space(heading.get_text(" ", strip=True)) if heading else ""
    title_probe = normalize_space(re.sub(r"^\[종료\]\s*", "", title))
    if title_probe and title_probe not in normalize_space(node.get_text(" ", strip=True)):
        warnings.append("registry_title_not_found_in_selected_content")
    if selector in {"body", "document"}:
        warnings.append("body_fallback_navigation_risk")
    if any(signal in text for signal in ("회사소개", "개인정보처리방침", "TOP")):
        warnings.append("navigation_or_footer_signal")
    if table_count and "[TABLE]" not in text:
        warnings.append("table_relationship_not_preserved")
    if image_count:
        warnings.append("image_content_not_ocr")
    if len(text) < 80:
        warnings.append("short_extracted_text")
    if not title or not text:
        raise RuntimeError("Extracted title or text is empty")

    preview.update(
        fetch_status="success",
        title=title,
        extracted_text=text,
        heading_count=heading_count,
        table_count=table_count,
        image_count=image_count,
        date_signals=_extract_date_signals(text),
        price_signals=_extract_price_signals(text),
        extraction_warnings=warnings,
        content_selector=selector,
    )

    if row["source_id"] == "dnf_game_guide":
        baseline = guide_baselines.get(canonicalize_url(row["canonical_url"]))
        refresh_normalized = normalize_block(text)
        preview["refresh_text_hash"] = hashlib.sha256(
            refresh_normalized.encode("utf-8")
        ).hexdigest()
        preview["refresh_text_chars"] = len(refresh_normalized)
        if baseline:
            baseline_normalized = normalize_block(baseline.get("text", ""))
            preview["baseline_text_hash"] = hashlib.sha256(
                baseline_normalized.encode("utf-8")
            ).hexdigest()
            preview["baseline_text_chars"] = len(baseline_normalized)
            preview["refresh_text_match"] = baseline_normalized == refresh_normalized
            preview["refresh_length_ratio"] = round(
                len(refresh_normalized) / len(baseline_normalized), 6
            ) if baseline_normalized else None
            ratio = preview["refresh_length_ratio"]
            if ratio is not None and (ratio < 0.7 or ratio > 1.5):
                warnings.append("guide_refresh_material_length_change")
        else:
            warnings.append("guide_baseline_not_found")
    return preview


def _validate_rows(
    rows: list[dict[str, Any]], required_fields: tuple[str, ...], label: str
) -> None:
    for index, row in enumerate(rows, start=1):
        missing = [field for field in required_fields if field not in row]
        if missing:
            raise RuntimeError(f"{label} row {index} missing required fields: {missing}")


def _raw_hash_mismatches(ledger: list[dict[str, Any]]) -> list[str]:
    mismatches = []
    checked: set[str] = set()
    for row in ledger:
        path_value = row.get("raw_snapshot_path")
        content_hash = row.get("content_hash")
        if not path_value or path_value in checked:
            continue
        checked.add(path_value)
        path = Path(path_value)
        if not path.is_file() or file_sha256(path) != content_hash:
            mismatches.append(path_value)
    return sorted(mismatches)


def _build_report(
    *,
    ledger: list[dict[str, Any]],
    previews: list[dict[str, Any]],
    selection_info: dict[str, Any],
    registry_sha256: str,
    registry_path: Path,
    manifest_path: Path,
    manifest_sha256: str,
    ledger_path: Path,
    ledger_sha256: str,
    preview_path: Path,
    preview_sha256: str,
    fetched_at: str,
    collection_mode: str = "pilot",
    collector_version: str = COLLECTOR_VERSION,
) -> dict[str, Any]:
    preview_by_url = {row["canonical_url"]: row for row in previews}
    outcome_counts = Counter(row["fetch_status"] for row in ledger)
    success_count = outcome_counts["success"]
    total = len(ledger)
    success_rate = round(success_count / total, 6) if total else 0.0

    by_source: dict[str, Any] = {}
    for source_id in sorted({row["source_id"] for row in ledger}):
        source_rows = [row for row in ledger if row["source_id"] == source_id]
        outcomes = Counter(row["fetch_status"] for row in source_rows)
        by_source[source_id] = {
            "selected": len(source_rows),
            "success": outcomes["success"],
            "failed": outcomes["failed"],
            "blocked": outcomes["blocked"],
            "parser_failed": outcomes["parser_failed"],
            "status_distribution": dict(
                sorted(Counter(row["registry_status"] for row in source_rows).items())
            ),
            "bucket_distribution": dict(
                sorted(Counter(row["pilot_bucket"] for row in source_rows).items())
            ),
        }

    success_previews = [
        preview_by_url[row["canonical_url"]]
        for row in ledger
        if row["fetch_status"] == "success"
    ]
    title_empty = sorted(
        row["canonical_url"] for row in success_previews if not row["title"].strip()
    )
    text_empty = sorted(
        row["canonical_url"] for row in success_previews if not row["extracted_text"].strip()
    )
    faq_resolution_errors = sorted(
        row["canonical_url"]
        for row in previews
        if row["source_id"] == "dnf_faq" and row["faq_locator_validated"] is False
    )
    policy_revision_errors = sorted(
        row["canonical_url"]
        for row in previews
        if row["source_id"] == "dnf_account_policy"
        and row["policy_revision_validated"] is False
    )
    default_exposure_violations = sorted(
        row["canonical_url"]
        for row in ledger
        if row["default_exposure"]
        and (
            row["registry_status"] in {"expired", "superseded"}
            or row["source_kind"] == "preview_patch"
        )
    )
    raw_hash_mismatches = _raw_hash_mismatches(ledger)
    warnings = sorted(
        (
            {
                "canonical_url": row["canonical_url"],
                "source_id": row["source_id"],
                "warnings": sorted(row["extraction_warnings"]),
            }
            for row in previews
            if row["extraction_warnings"]
        ),
        key=lambda row: (row["source_id"], row["canonical_url"]),
    )
    failures = sorted(
        (
            {
                "canonical_url": row["canonical_url"],
                "source_id": row["source_id"],
                "fetch_status": row["fetch_status"],
                "http_status": row["http_status"],
                "error": row["error"],
            }
            for row in ledger
            if row["fetch_status"] != "success"
        ),
        key=lambda row: (row["source_id"], row["canonical_url"]),
    )
    missing_source_success = sorted(
        source_id for source_id, values in by_source.items() if values["success"] < 1
    )
    issues_recorded = (
        len(failures) == total - success_count
        and len(warnings)
        == sum(bool(row["extraction_warnings"]) for row in previews)
    )
    go = all(
        (
            not missing_source_success,
            success_rate >= 0.95,
            not title_empty,
            not text_empty,
            not faq_resolution_errors,
            not policy_revision_errors,
            not raw_hash_mismatches,
            not default_exposure_violations,
            issues_recorded,
        )
    )
    decision = "GO" if go else "NO-GO"
    if collection_mode == "full":
        reason = (
            "전체 eligible 집합이 95% 이상 성공했고 특수 locator·raw hash·노출 정책 게이트를 충족했다."
            if go
            else "정규화 승격 전에 전체 수집 실패 또는 게이트 미충족 항목을 수정해야 한다."
        )
    else:
        reason = (
            "모든 출처의 실제 성공 표본과 95% 이상 fetch success, 특수 locator·raw hash·노출 정책 게이트를 충족했다."
            if go
            else "전체 수집 전에 실패 또는 게이트 미충족 항목을 수정해야 한다."
        )
    report = {
        "report_schema_version": (
            FULL_REPORT_SCHEMA_VERSION if collection_mode == "full" else REPORT_SCHEMA_VERSION
        ),
        "collector_version": collector_version,
        "fetched_at": fetched_at,
        "registry_path": registry_path.as_posix(),
        "registry_sha256": registry_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "ledger_path": ledger_path.as_posix(),
        "ledger_sha256": ledger_sha256,
        "preview_path": preview_path.as_posix(),
        "preview_sha256": preview_sha256,
        "selection": selection_info,
        "summary": {
            "selected_total": total,
            "success": success_count,
            "failed": outcome_counts["failed"],
            "blocked": outcome_counts["blocked"],
            "parser_failed": outcome_counts["parser_failed"],
            "success_rate": success_rate,
            "missing_source_success": missing_source_success,
            "success_title_empty": len(title_empty),
            "success_text_empty": len(text_empty),
            "faq_resolution_errors": len(faq_resolution_errors),
            "policy_revision_errors": len(policy_revision_errors),
            "raw_hash_mismatches": len(raw_hash_mismatches),
            "default_exposure_violations": len(default_exposure_violations),
            "parser_warnings_and_failures_recorded": issues_recorded,
        },
        "by_source": by_source,
        "extraction": {
            "heading_rows": sum(row["heading_count"] > 0 for row in success_previews),
            "table_rows": sum(row["table_count"] > 0 for row in success_previews),
            "table_count": sum(row["table_count"] for row in success_previews),
            "image_rows": sum(row["image_count"] > 0 for row in success_previews),
            "image_count": sum(row["image_count"] for row in success_previews),
            "date_metadata_rows": sum(
                bool(row["published_at"] or row["valid_from"] or row["valid_to"])
                for row in success_previews
            ),
            "date_signal_rows": sum(bool(row["date_signals"]) for row in success_previews),
            "price_signal_rows": sum(bool(row["price_signals"]) for row in success_previews),
            "guide_refresh_rows": sum(
                row["source_id"] == "dnf_game_guide" and row["baseline_text_hash"] is not None
                for row in success_previews
            ),
            "guide_refresh_exact_match_rows": sum(
                row["source_id"] == "dnf_game_guide" and row["refresh_text_match"] is True
                for row in success_previews
            ),
        },
        "warning_rows": warnings,
        "failure_rows": failures,
        "gate_details": {
            "title_empty_urls": title_empty,
            "text_empty_urls": text_empty,
            "faq_resolution_error_urls": faq_resolution_errors,
            "policy_revision_error_urls": policy_revision_errors,
            "raw_hash_mismatch_paths": raw_hash_mismatches,
            "default_exposure_violation_urls": default_exposure_violations,
        },
        "full_collection_decision": decision,
        "decision_reason": reason,
    }
    if collection_mode == "full":
        document_v3_blocking_warning_names = {
            "body_fallback_navigation_risk",
            "guide_refresh_material_length_change",
            "navigation_or_footer_signal",
            "registry_title_not_found_in_selected_content",
        }
        document_v3_blocking_rows = [
            row
            for row in warnings
            if document_v3_blocking_warning_names.intersection(row["warnings"])
        ]
        document_v3_blocking_counts = Counter(
            warning
            for row in document_v3_blocking_rows
            for warning in row["warnings"]
            if warning in document_v3_blocking_warning_names
        )
        report.update(
            collection_mode="full",
            next_stage="parser_quality_hardening",
            next_stage_decision=decision,
            raw_collection_decision=decision,
            document_v3_promotion_decision=(
                "NO-GO" if document_v3_blocking_rows else decision
            ),
            document_v3_blocking_warning_rows=len(document_v3_blocking_rows),
            document_v3_blocking_warning_counts=dict(
                sorted(document_v3_blocking_counts.items())
            ),
        )
    return report


def render_report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    extraction = report["extraction"]
    lines = [
        (
            "# DNF RAG v3 전체 eligible 상세 본문 수집"
            if report.get("collection_mode") == "full"
            else "# DNF RAG v3 상세 본문 수집기 파일럿"
        ),
        "",
        f"- 수집 기준 시각: `{report['fetched_at']}`",
        f"- registry SHA-256: `{report['registry_sha256']}`",
        f"- ledger SHA-256: `{report['ledger_sha256']}`",
        f"- preview SHA-256: `{report['preview_sha256']}`",
        f"- manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## 전체 결과",
        "",
        "| selected | success | failed | blocked | parser failed | success rate |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['selected_total']} | {summary['success']} | {summary['failed']} | "
            f"{summary['blocked']} | {summary['parser_failed']} | {summary['success_rate']} |"
        ),
        "",
        "## 출처별 결과",
        "",
        "| source | selected | success | failed | blocked | parser failed | status distribution |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for source_id, values in report["by_source"].items():
        status_text = ", ".join(
            f"{key}:{value}" for key, value in values["status_distribution"].items()
        )
        lines.append(
            f"| `{source_id}` | {values['selected']} | {values['success']} | "
            f"{values['failed']} | {values['blocked']} | {values['parser_failed']} | {status_text} |"
        )
    lines.extend(
        [
            "",
            "## 추출 상태",
            "",
            f"- heading 포함 row: {extraction['heading_rows']}",
            f"- table 포함 row / 전체 table: {extraction['table_rows']} / {extraction['table_count']}",
            f"- image 포함 row / 전체 image: {extraction['image_rows']} / {extraction['image_count']}",
            f"- date metadata / date signal row: {extraction['date_metadata_rows']} / {extraction['date_signal_rows']}",
            f"- price signal row: {extraction['price_signal_rows']}",
            f"- guide refresh 비교 / exact match: {extraction['guide_refresh_rows']} / {extraction['guide_refresh_exact_match_rows']}",
            "",
            "## 게이트",
            "",
        ]
    )
    for key, value in summary.items():
        if key not in {"selected_total", "success", "failed", "blocked", "parser_failed", "success_rate"}:
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## 경고·실패", ""])
    if report["failure_rows"]:
        for row in report["failure_rows"]:
            lines.append(
                f"- `{row['fetch_status']}` {row['canonical_url']}: {row['error']}"
            )
    else:
        lines.append("- fetch/parser 실패 없음")
    for row in report["warning_rows"]:
        lines.append(f"- `{row['source_id']}` {row['canonical_url']}: {', '.join(row['warnings'])}")
    lines.extend(
        [
            "",
            "## 승격 판정",
            "",
            (
                f"**전체 eligible raw 수집: {report['raw_collection_decision']}**  "
                f"\n**parser 품질 보강: {report['next_stage_decision']}**  "
                f"\n**DocumentV3 승격: {report['document_v3_promotion_decision']}**"
                if report.get("collection_mode") == "full"
                else f"**전체 eligible 상세 수집: {report['full_collection_decision']}**"
            ),
            "",
            report["decision_reason"],
            "",
            (
                "전체 eligible raw detail만 수집했다. DocumentV3, ChunkV3, BM25, Router, 학습은 실행하지 않았다."
                if report.get("collection_mode") == "full"
                else "이 파일럿은 선택 표본만 수집했다. DocumentV3, ChunkV3, BM25, Router, 학습은 실행하지 않았다."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def freeze_collection_artifacts(
    *,
    ledger: list[dict[str, Any]],
    previews: list[dict[str, Any]],
    selection_info: dict[str, Any],
    registry_path: Path,
    registry_manifest_path: Path,
    registry_sha256: str,
    guide_baseline_path: Path,
    fetched_at: str,
    collection_dir: Path,
    report_dir: Path,
    collection_mode: str = "pilot",
    collector_version: str = COLLECTOR_VERSION,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    _validate_rows(ledger, LEDGER_REQUIRED_FIELDS, "ledger")
    _validate_rows(previews, PREVIEW_REQUIRED_FIELDS, "preview")
    if any(row["fetch_status"] not in ALLOWED_OUTCOMES for row in ledger):
        raise RuntimeError("Ledger contains an unsupported fetch_status")
    if {row["canonical_url"] for row in ledger} != {
        row["canonical_url"] for row in previews
    }:
        raise RuntimeError("Ledger and preview canonical URL sets differ")

    ledger_bytes = _serialize_jsonl(
        ledger, lambda row: (row["source_id"], row["canonical_url"])
    )
    ledger_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
    artifact_prefix = "detail_full_collection" if collection_mode == "full" else "detail_collection"
    ledger_path = collection_dir / f"{artifact_prefix}_ledger_{ledger_sha256}.jsonl"
    write_immutable(ledger_path, ledger_bytes)

    preview_bytes = _serialize_jsonl(
        previews, lambda row: (row["source_id"], row["canonical_url"])
    )
    preview_sha256 = hashlib.sha256(preview_bytes).hexdigest()
    preview_prefix = "detail_full_extraction_preview" if collection_mode == "full" else "detail_extraction_preview"
    preview_path = collection_dir / f"{preview_prefix}_{preview_sha256}.jsonl"
    write_immutable(preview_path, preview_bytes)

    raw_by_path: dict[str, dict[str, Any]] = {}
    for row in ledger:
        path_value = row.get("raw_snapshot_path")
        if not path_value:
            continue
        item = raw_by_path.setdefault(
            path_value,
            {
                "raw_snapshot_path": path_value,
                "content_hash": row["content_hash"],
                "byte_count": Path(path_value).stat().st_size,
                "source_id": row["source_id"],
                "ledger_reference_count": 0,
            },
        )
        item["ledger_reference_count"] += 1

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "collector_version": collector_version,
        "fetched_at": fetched_at,
        "registry_path": registry_path.as_posix(),
        "registry_sha256": registry_sha256,
        "registry_manifest_path": registry_manifest_path.as_posix(),
        "registry_manifest_sha256": file_sha256(registry_manifest_path),
        "guide_baseline_path": guide_baseline_path.as_posix(),
        "guide_baseline_sha256": file_sha256(guide_baseline_path),
        "selection": selection_info,
        "ledger_path": ledger_path.as_posix(),
        "ledger_sha256": ledger_sha256,
        "ledger_row_count": len(ledger),
        "preview_path": preview_path.as_posix(),
        "preview_sha256": preview_sha256,
        "preview_row_count": len(previews),
        "raw_snapshot_count": len(raw_by_path),
        "raw_snapshots": sorted(raw_by_path.values(), key=lambda row: row["raw_snapshot_path"]),
    }
    if collection_mode == "full":
        manifest.update(
            collection_mode="full",
            checkpoint_path=checkpoint_path.as_posix() if checkpoint_path else None,
            checkpoint_sha256=(file_sha256(checkpoint_path) if checkpoint_path else None),
        )
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = collection_dir / f"{artifact_prefix}_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = _build_report(
        ledger=ledger,
        previews=previews,
        selection_info=selection_info,
        registry_sha256=registry_sha256,
        registry_path=registry_path,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        ledger_path=ledger_path,
        ledger_sha256=ledger_sha256,
        preview_path=preview_path,
        preview_sha256=preview_sha256,
        fetched_at=fetched_at,
        collection_mode=collection_mode,
        collector_version=collector_version,
    )
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    report_prefix = "detail_full_collection" if collection_mode == "full" else "detail_collection_pilot"
    report_json_path = report_dir / f"{report_prefix}_{report_sha256}.json"
    report_md_path = report_dir / f"{report_prefix}_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_md_path, render_report_markdown(report).encode("utf-8"))
    result = {
        "ledger_path": ledger_path.as_posix(),
        "ledger_sha256": ledger_sha256,
        "preview_path": preview_path.as_posix(),
        "preview_sha256": preview_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_md_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": report["by_source"],
        "full_collection_decision": report["full_collection_decision"],
    }
    if collection_mode == "full":
        result.update(
            collection_mode="full",
            checkpoint_path=checkpoint_path.as_posix() if checkpoint_path else None,
            next_stage_decision=report["next_stage_decision"],
            document_v3_promotion_decision=report[
                "document_v3_promotion_decision"
            ],
        )
    return result


def _load_frozen_registry(
    registry_path: Path,
    registry_manifest_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    registry_manifest = json.loads(registry_manifest_path.read_text(encoding="utf-8"))
    registry_sha256 = file_sha256(registry_path)
    if registry_manifest.get("registry_sha256") != registry_sha256:
        raise RuntimeError("Registry bytes do not match the frozen registry manifest")
    return read_jsonl(registry_path), registry_sha256


def _default_full_checkpoint_path(
    collection_dir: Path,
    registry_sha256: str,
    fetched_at: str,
) -> Path:
    token = hashlib.sha256(
        f"{registry_sha256}\0{fetched_at}".encode("utf-8")
    ).hexdigest()[:16]
    return collection_dir / "checkpoints" / f"detail_full_checkpoint_{token}.jsonl"


def _load_collection_checkpoint(
    checkpoint_path: Path | None,
    *,
    registry_sha256: str,
    fetched_at: str,
    collector_version: str,
    selected_urls: set[str],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    if checkpoint_path is None or not checkpoint_path.is_file():
        return {}
    completed: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    with checkpoint_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid checkpoint JSON at line {line_number}: {checkpoint_path}"
                ) from exc
            if record.get("checkpoint_schema_version") != CHECKPOINT_SCHEMA_VERSION:
                raise RuntimeError("Checkpoint schema version mismatch")
            if record.get("registry_sha256") != registry_sha256:
                raise RuntimeError("Checkpoint registry SHA-256 mismatch")
            if record.get("fetched_at") != fetched_at:
                raise RuntimeError("Checkpoint fetched_at mismatch")
            if record.get("collector_version") != collector_version:
                raise RuntimeError("Checkpoint collector version mismatch")
            ledger_row = record.get("ledger")
            preview = record.get("preview")
            if not isinstance(ledger_row, dict) or not isinstance(preview, dict):
                raise RuntimeError("Checkpoint row is missing ledger or preview data")
            canonical_url = ledger_row.get("canonical_url")
            if canonical_url not in selected_urls:
                raise RuntimeError(f"Checkpoint URL is not in the selected set: {canonical_url}")
            if canonical_url in completed:
                raise RuntimeError(f"Duplicate checkpoint URL: {canonical_url}")
            if preview.get("canonical_url") != canonical_url:
                raise RuntimeError(f"Checkpoint ledger/preview URL mismatch: {canonical_url}")
            raw_path_value = ledger_row.get("raw_snapshot_path")
            if raw_path_value:
                raw_path = Path(raw_path_value)
                if not raw_path.is_file() or file_sha256(raw_path) != ledger_row.get("content_hash"):
                    raise RuntimeError(f"Checkpoint raw snapshot mismatch: {raw_path_value}")
            completed[canonical_url] = (ledger_row, preview)
    return completed


def _append_collection_checkpoint(
    checkpoint_path: Path,
    *,
    registry_sha256: str,
    fetched_at: str,
    collector_version: str,
    ledger_row: dict[str, Any],
    preview: dict[str, Any],
) -> None:
    record = {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "registry_sha256": registry_sha256,
        "fetched_at": fetched_at,
        "collector_version": collector_version,
        "ledger": ledger_row,
        "preview": preview,
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint_path.open("ab") as handle:
        handle.write(_canonical_json_bytes(record))


def _collect_selected_details(
    *,
    selected: list[dict[str, Any]],
    selection_info: dict[str, Any],
    registry_path: Path,
    registry_manifest_path: Path,
    registry_sha256: str,
    guide_baseline_path: Path,
    fetched_at: str,
    fetcher: Callable[[str], FetchResult],
    detail_dir: Path,
    collection_dir: Path,
    report_dir: Path,
    collection_mode: str,
    collector_version: str,
    checkpoint_path: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    parse_fixed_timestamp(fetched_at)
    guide_baselines = load_guide_baselines(guide_baseline_path)
    progress = progress or (lambda _message: None)
    selected_urls = {row["canonical_url"] for row in selected}
    completed = _load_collection_checkpoint(
        checkpoint_path,
        registry_sha256=registry_sha256,
        fetched_at=fetched_at,
        collector_version=collector_version,
        selected_urls=selected_urls,
    )

    ledger: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        checkpoint_row = completed.get(row["canonical_url"])
        if checkpoint_row is not None:
            progress(
                f"[{index}/{len(selected)}] resume {row['source_id']} {row['canonical_url']}"
            )
            ledger.append(checkpoint_row[0])
            previews.append(checkpoint_row[1])
            continue
        fetch_url = resolve_fetch_url(row)
        progress(f"[{index}/{len(selected)}] {row['source_id']} {fetch_url}")
        result = fetcher(fetch_url)
        content_hash: str | None = None
        raw_snapshot_path: str | None = None
        if result.content:
            content_hash = hashlib.sha256(result.content).hexdigest()
            path = detail_dir / row["source_id"] / f"raw_detail_{content_hash}.html"
            write_immutable(path, result.content)
            raw_snapshot_path = path.as_posix()

        ledger_row = {
            "ledger_schema_version": LEDGER_SCHEMA_VERSION,
            "registry_sha256": registry_sha256,
            "source_id": row["source_id"],
            "source_kind": row["source_kind"],
            "registry_status": row["status"],
            "registry_category": row["category"],
            "registry_title": row["title"],
            "pilot_bucket": row["pilot_bucket"],
            "canonical_url": row["canonical_url"],
            "canonical_url_kind": row["canonical_url_kind"],
            "fetch_url": fetch_url,
            "final_url": result.final_url,
            "eligible_for_collection": row["eligible_for_collection"],
            "default_exposure": row["default_exposure"],
            "fetch_status": result.status,
            "http_status": result.http_status,
            "fetched_at": fetched_at,
            "content_hash": content_hash,
            "raw_snapshot_path": raw_snapshot_path,
            "raw_byte_count": len(result.content),
            "collector_version": collector_version,
            "retry_count": result.retry_count,
            "error": result.error,
        }
        preview = make_empty_preview(row, raw_snapshot_path)
        preview["fetch_status"] = result.status
        if result.status == "success" and raw_snapshot_path:
            try:
                preview = extract_preview(
                    row, result.content, raw_snapshot_path, guide_baselines
                )
                ledger_row["fetch_status"] = "success"
            except Exception as exc:
                ledger_row["fetch_status"] = "parser_failed"
                ledger_row["error"] = str(exc)
                preview["fetch_status"] = "parser_failed"
                if row["source_id"] == "dnf_faq":
                    preview["faq_locator_validated"] = False
                    preview["extraction_warnings"].append("faq_locator_mismatch")
                elif row["source_id"] == "dnf_account_policy":
                    preview["policy_revision_validated"] = False
                    preview["extraction_warnings"].append("policy_revision_mismatch")
                else:
                    preview["extraction_warnings"].append("parser_failed")
        else:
            preview["extraction_warnings"].append(f"fetch_{result.status}")
        ledger.append(ledger_row)
        previews.append(preview)
        if checkpoint_path is not None:
            _append_collection_checkpoint(
                checkpoint_path,
                registry_sha256=registry_sha256,
                fetched_at=fetched_at,
                collector_version=collector_version,
                ledger_row=ledger_row,
                preview=preview,
            )

    return freeze_collection_artifacts(
        ledger=ledger,
        previews=previews,
        selection_info=selection_info,
        registry_path=registry_path,
        registry_manifest_path=registry_manifest_path,
        registry_sha256=registry_sha256,
        guide_baseline_path=guide_baseline_path,
        fetched_at=fetched_at,
        collection_dir=collection_dir,
        report_dir=report_dir,
        collection_mode=collection_mode,
        collector_version=collector_version,
        checkpoint_path=checkpoint_path,
    )


def collect_detail_pilot(
    *,
    registry_path: Path,
    registry_manifest_path: Path,
    guide_baseline_path: Path,
    fetched_at: str,
    fetcher: Callable[[str], FetchResult],
    detail_dir: Path,
    collection_dir: Path,
    report_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    registry, registry_sha256 = _load_frozen_registry(
        registry_path, registry_manifest_path
    )
    selected, selection_info = select_pilot_rows(registry)
    return _collect_selected_details(
        selected=selected,
        selection_info=selection_info,
        registry_path=registry_path,
        registry_manifest_path=registry_manifest_path,
        registry_sha256=registry_sha256,
        guide_baseline_path=guide_baseline_path,
        fetched_at=fetched_at,
        fetcher=fetcher,
        detail_dir=detail_dir,
        collection_dir=collection_dir,
        report_dir=report_dir,
        collection_mode="pilot",
        collector_version=COLLECTOR_VERSION,
        progress=progress,
    )


def collect_detail_full(
    *,
    registry_path: Path,
    registry_manifest_path: Path,
    guide_baseline_path: Path,
    fetched_at: str,
    fetcher: Callable[[str], FetchResult],
    detail_dir: Path,
    collection_dir: Path,
    report_dir: Path,
    checkpoint_path: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    registry, registry_sha256 = _load_frozen_registry(
        registry_path, registry_manifest_path
    )
    selected, selection_info = select_full_rows(registry)
    checkpoint_path = checkpoint_path or _default_full_checkpoint_path(
        collection_dir, registry_sha256, fetched_at
    )
    return _collect_selected_details(
        selected=selected,
        selection_info=selection_info,
        registry_path=registry_path,
        registry_manifest_path=registry_manifest_path,
        registry_sha256=registry_sha256,
        guide_baseline_path=guide_baseline_path,
        fetched_at=fetched_at,
        fetcher=fetcher,
        detail_dir=detail_dir,
        collection_dir=collection_dir,
        report_dir=report_dir,
        collection_mode="full",
        collector_version=FULL_COLLECTOR_VERSION,
        checkpoint_path=checkpoint_path,
        progress=progress,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect deterministic DNF v3 detail pages from a frozen registry."
    )
    parser.add_argument("--mode", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--fetched-at", required=True, help="Fixed ISO timestamp for deterministic freeze metadata.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--registry-manifest", type=Path, default=DEFAULT_REGISTRY_MANIFEST)
    parser.add_argument("--guide-baseline", type=Path, default=DEFAULT_GUIDE_BASELINE)
    parser.add_argument("--detail-dir", type=Path, default=DEFAULT_DETAIL_DIR)
    parser.add_argument("--collection-dir", type=Path, default=DEFAULT_COLLECTION_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Append-only resume checkpoint. Full mode derives a deterministic default when omitted.",
    )
    parser.add_argument("--request-interval", type=float, default=0.35)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    for path in (args.registry, args.registry_manifest, args.guide_baseline):
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    fetcher = RateLimitedFetcher(
        interval_seconds=args.request_interval,
        retries=args.retries,
        timeout_seconds=args.timeout,
        user_agent=(
            "DNF-RAG-v3-detail-full/0.1"
            if args.mode == "full"
            else "DNF-RAG-v3-detail-pilot/0.1"
        ),
    )
    collect = collect_detail_full if args.mode == "full" else collect_detail_pilot
    kwargs: dict[str, Any] = {}
    if args.mode == "full":
        kwargs["checkpoint_path"] = args.checkpoint
    elif args.checkpoint is not None:
        raise RuntimeError("--checkpoint is only supported in full mode")
    result = collect(
        registry_path=args.registry,
        registry_manifest_path=args.registry_manifest,
        guide_baseline_path=args.guide_baseline,
        fetched_at=args.fetched_at,
        fetcher=fetcher,
        detail_dir=args.detail_dir,
        collection_dir=args.collection_dir,
        report_dir=args.report_dir,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
        **kwargs,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
