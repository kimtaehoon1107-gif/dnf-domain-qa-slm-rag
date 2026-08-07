from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from src.io_utils import read_jsonl
from src.v3.build_corpus import canonicalize_url, file_sha256


BASE_URL = "https://df.nexon.com"
DISCOVERY_PARSER_VERSION = "dnf_source_discovery_v3.1"
REGISTRY_SCHEMA_VERSION = "dnf_source_registry_v3.0"
MANIFEST_SCHEMA_VERSION = "dnf_source_registry_manifest_v3.0"
REPORT_SCHEMA_VERSION = "dnf_source_discovery_coverage_v3.1"

DEFAULT_EXISTING_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_v3.0_c77299d729a6.jsonl"
)
DEFAULT_DISCOVERY_DIR = Path("data/v3/discovery")
DEFAULT_REPORT_DIR = Path("reports/v3")

LISTING_URLS = {
    "dnf_notice": f"{BASE_URL}/community/news/notice/list",
    "dnf_update": f"{BASE_URL}/community/news/update/list",
    "dnf_event": f"{BASE_URL}/community/news/event/list",
    "dnf_game_guide": f"{BASE_URL}/guide",
    "dnf_faq": f"{BASE_URL}/customer/faq",
    "dnf_account_policy": f"{BASE_URL}/customer/policy/home?type=1",
    "dnf_seria_shop": f"{BASE_URL}/community/news/seriashop/list",
    "dnf_monthly_item": f"{BASE_URL}/community/news/monthlyitem/",
}
EVENT_ARCHIVE_URL = f"{BASE_URL}/community/news/event/list?categoryType=3"
MONTHLY_ITEM_ARCHIVE_URL = (
    f"{BASE_URL}/community/news/seriashop/list?category=2&searchKeyword=%EC%9D%B4%EB%8B%AC"
)

RegistryRow = dict[str, Any]
FetchHtml = Callable[[str], str]
Progress = Callable[[str], None]

REGISTRY_REQUIRED_FIELDS = (
    "source_id",
    "source_kind",
    "listing_url",
    "canonical_url",
    "canonical_url_kind",
    "source_item_id",
    "title",
    "category",
    "discovered_at",
    "published_at",
    "period_start",
    "period_end",
    "page_number",
    "eligible_for_collection",
    "eligibility_reason",
    "status",
    "default_exposure",
    "is_pinned",
    "discovery_parser_version",
)


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def parse_date(value: Any) -> str | None:
    match = re.search(r"20\d{2}[.-]\d{1,2}[.-]\d{1,2}", str(value or ""))
    if not match:
        return None
    year, month, day = re.split(r"[.-]", match.group(0))
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def parse_period(value: Any) -> tuple[str | None, str | None]:
    matches = re.findall(r"20\d{2}[.-]\d{1,2}[.-]\d{1,2}", str(value or ""))
    parsed = [parse_date(item) for item in matches[:2]]
    return (
        parsed[0] if parsed else None,
        parsed[1] if len(parsed) > 1 else None,
    )


def parse_discovered_at(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Invalid --discovered-at ISO timestamp: {value!r}") from exc


def subtract_months(value: date, months: int) -> date:
    year = value.year
    month = value.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = value.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def set_query_params(url: str, **updates: Any) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in updates.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = str(value)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(query.items())), "")
    )


def _canonical_json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            indent=indent,
        )
        + ("\n" if indent is not None else "")
    ).encode("utf-8")


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError(f"Refusing to overwrite immutable artifact: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise RuntimeError(f"Immutable artifact changed during write: {path}")


class RateLimitedFetcher:
    def __init__(
        self,
        *,
        interval_seconds: float,
        retries: int,
        timeout_seconds: float,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; DNF-RAG-v3-source-discovery/0.1; "
                    "+https://df.nexon.com/)"
                )
            }
        )
        self.interval_seconds = interval_seconds
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self._last_request_at = 0.0

    def __call__(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            wait_seconds = self.interval_seconds - (time.monotonic() - self._last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                self._last_request_at = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    raise RuntimeError(f"HTTP {response.status_code} for {url}")
                response.raise_for_status()
                if not response.text.strip():
                    raise RuntimeError(f"Empty response for {url}")
                return response.text
            except (requests.RequestException, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(8.0, 1.0 * (2**attempt)))
        raise RuntimeError(f"Fetch failed after {self.retries + 1} attempts: {url}: {last_error}")


def make_registry_row(
    *,
    source_id: str,
    source_kind: str,
    listing_url: str,
    canonical_url: str,
    title: str,
    category: str,
    discovered_at: str,
    published_at: str | None,
    period_start: str | None,
    period_end: str | None,
    page_number: int,
    eligible_for_collection: bool,
    eligibility_reason: str,
    status: str,
    default_exposure: bool,
    source_item_id: str,
    canonical_url_kind: str = "official_url",
    is_pinned: bool = False,
) -> RegistryRow:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "listing_url": canonicalize_url(listing_url),
        "canonical_url": canonicalize_url(canonical_url),
        "canonical_url_kind": canonical_url_kind,
        "source_item_id": source_item_id,
        "title": normalize_space(title),
        "category": normalize_space(category),
        "discovered_at": discovered_at,
        "published_at": published_at,
        "period_start": period_start,
        "period_end": period_end,
        "page_number": page_number,
        "eligible_for_collection": eligible_for_collection,
        "eligibility_reason": eligibility_reason,
        "status": status,
        "default_exposure": default_exposure,
        "is_pinned": is_pinned,
        "discovery_parser_version": DISCOVERY_PARSER_VERSION,
    }


def parse_last_page(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    end = soup.select_one(".paging a.end[data-page]")
    if end:
        try:
            return max(1, int(end["data-page"]))
        except (TypeError, ValueError):
            pass
    pages = []
    for node in soup.select(".paging [data-page]"):
        try:
            pages.append(int(node["data-page"]))
        except (TypeError, ValueError):
            continue
    return max(pages, default=1)


def classify_notice(category: str, title: str) -> tuple[str, str]:
    text = normalize_space(f"{category} {title}")
    if category == "점검" or "점검" in text:
        return "maintenance", "category_or_title_maintenance"
    if re.search(r"확인된 오류|오류 현상|알려진 문제|버그", text):
        return "known_issue", "title_known_issue_signal"
    if re.search(r"클라이언트 패치|핫픽스|긴급 패치", text):
        return "hotfix", "title_hotfix_signal"
    if re.search(r"불량이용자|단속결과|제재|운영정책 위반", text):
        return "enforcement_notice", "title_enforcement_signal"
    if re.search(r"피싱|계정 도용|OTP|보안|이용약관|개인정보", text):
        return "account_policy", "title_account_policy_signal"
    return "general_notice", "listing_metadata_no_specific_signal"


def _notice_policy(
    published_at: str | None,
    is_pinned: bool,
    as_of: date,
) -> tuple[bool, str, str, bool]:
    cutoff = subtract_months(as_of, 12)
    if is_pinned:
        return True, "pinned_notice", "current", True
    if published_at and date.fromisoformat(published_at) >= cutoff:
        return True, f"published_on_or_after_{cutoff.isoformat()}", "current", True
    if published_at:
        return False, f"older_than_{cutoff.isoformat()}", "unknown", False
    return False, "missing_published_at", "unknown", False


def parse_board_page(
    *,
    source_id: str,
    section: str,
    html: str,
    listing_url: str,
    page_number: int,
    discovered_at: str,
    as_of: date,
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[RegistryRow] = []
    for node in soup.select("article.board_list ul"):
        title_node = node.select_one("li.title[data-no]")
        if not title_node:
            continue
        item_id = normalize_space(title_node.get("data-no"))
        title = normalize_space(title_node.get_text(" ", strip=True))
        category_node = node.select_one("li.category")
        date_node = node.select_one("li.date")
        category = normalize_space(category_node.get_text(" ", strip=True)) if category_node else ""
        published_at = parse_date(date_node.get_text(" ", strip=True)) if date_node else None
        if not item_id or not title:
            continue
        is_pinned = "notice" in (node.get("class") or [])
        if section == "notice":
            source_kind, classification_reason = classify_notice(category, title)
            eligible, reason, status, exposure = _notice_policy(published_at, is_pinned, as_of)
            reason = f"{reason};{classification_reason}"
        else:
            source_kind = "preview_patch" if category == "퍼스트서버" or "퍼스트 서버" in title else "patch_note"
            eligible, reason, status, exposure = False, "update_policy_pending", "unknown", False
        detail_url = f"{BASE_URL}/community/news/{section}/{item_id}"
        rows.append(
            make_registry_row(
                source_id=source_id,
                source_kind=source_kind,
                listing_url=set_query_params(listing_url, page=page_number),
                canonical_url=detail_url,
                title=title,
                category=category,
                discovered_at=discovered_at,
                published_at=published_at,
                period_start=None,
                period_end=None,
                page_number=page_number,
                eligible_for_collection=eligible,
                eligibility_reason=reason,
                status=status,
                default_exposure=exposure,
                source_item_id=item_id,
                is_pinned=is_pinned,
            )
        )
    return rows


def detect_season_start(rows: list[RegistryRow]) -> str | None:
    candidates = [
        row["published_at"]
        for row in rows
        if row["published_at"]
        and re.search(r"시즌\s*\d+\s*Act\s*1(?:\D|$)", row["title"], re.IGNORECASE)
    ]
    return max(candidates, default=None)


def apply_update_policy(rows: list[RegistryRow], season_start: str | None) -> None:
    for row in rows:
        published_at = row["published_at"]
        if season_start is None:
            row.update(
                eligible_for_collection=False,
                eligibility_reason="season_start_not_configured",
                status="unknown",
                default_exposure=False,
            )
            continue
        if not published_at:
            row.update(
                eligible_for_collection=False,
                eligibility_reason="missing_published_at",
                status="unknown",
                default_exposure=False,
            )
            continue
        eligible = published_at >= season_start
        preview = row["source_kind"] == "preview_patch"
        row.update(
            eligible_for_collection=eligible,
            eligibility_reason=(
                f"preview_on_or_after_season_start_{season_start}"
                if eligible and preview
                else f"live_on_or_after_season_start_{season_start}"
                if eligible
                else f"before_season_start_{season_start}"
            ),
            status="current" if eligible and not preview else "unknown",
            default_exposure=eligible and not preview,
        )


def parse_event_page(
    html: str,
    *,
    listing_url: str,
    discovered_at: str,
    as_of: date,
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    cutoff = subtract_months(as_of, 6)
    rows: list[RegistryRow] = []
    for index, node in enumerate(soup.select("article.board_eventlist li.title"), start=1):
        title_node = node.select_one("b")
        if not title_node:
            continue
        title = normalize_space(title_node.get_text(" ", strip=True))
        period_node = node.select_one("span")
        period_start, period_end = parse_period(
            period_node.get_text(" ", strip=True) if period_node else ""
        )
        item_id = normalize_space(node.get("data-no"))
        onclick = node.get("onclick") or ""
        match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
        if item_id:
            detail_url = f"{BASE_URL}/community/news/event/{item_id}"
        elif match:
            detail_url = urljoin(BASE_URL, match.group(1))
            item_id = urlsplit(detail_url).path.rstrip("/").split("/")[-1]
        else:
            detail_url = set_query_params(listing_url, event_card=index)
            item_id = f"event_card_{index:03d}"
        start_date = date.fromisoformat(period_start) if period_start else None
        end_date = date.fromisoformat(period_end) if period_end else None
        if start_date and start_date > as_of:
            status, eligible, reason, exposure = "upcoming", True, "upcoming_event", True
        elif end_date and end_date < as_of:
            eligible = end_date >= cutoff
            status, exposure = "expired", False
            reason = (
                f"ended_on_or_after_{cutoff.isoformat()}"
                if eligible
                else f"ended_before_{cutoff.isoformat()}"
            )
        elif start_date:
            status, eligible, reason, exposure = "current", True, "active_or_open_ended_event", True
        else:
            status, eligible, reason, exposure = "unknown", False, "missing_event_period", False
        rows.append(
            make_registry_row(
                source_id="dnf_event",
                source_kind="event",
                listing_url=listing_url,
                canonical_url=detail_url,
                title=title,
                category="event",
                discovered_at=discovered_at,
                published_at=period_start,
                period_start=period_start,
                period_end=period_end,
                page_number=1,
                eligible_for_collection=eligible,
                eligibility_reason=reason,
                status=status,
                default_exposure=exposure,
                source_item_id=item_id,
            )
        )
    return rows


def parse_guide_page(
    html: str,
    *,
    listing_url: str,
    discovered_at: str,
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[RegistryRow] = []
    for group in soup.select("article.nav dl"):
        category_node = group.find("dt")
        category = normalize_space(category_node.get_text(" ", strip=True)) if category_node else ""
        for anchor in group.select('a[href*="guide?no="]'):
            href = urljoin(listing_url, anchor.get("href") or "")
            query = dict(parse_qsl(urlsplit(href).query))
            item_id = query.get("no", "")
            title = normalize_space(anchor.get_text(" ", strip=True))
            if not item_id or not title:
                continue
            rows.append(
                make_registry_row(
                    source_id="dnf_game_guide",
                    source_kind="game_guide",
                    listing_url=listing_url,
                    canonical_url=f"{BASE_URL}/guide?no={item_id}",
                    title=title,
                    category=category,
                    discovered_at=discovered_at,
                    published_at=None,
                    period_start=None,
                    period_end=None,
                    page_number=1,
                    eligible_for_collection=True,
                    eligibility_reason="currently_listed_guide",
                    status="current",
                    default_exposure=True,
                    source_item_id=item_id,
                )
            )
    return rows


def parse_faq_page(
    html: str,
    *,
    listing_url: str,
    page_number: int,
    discovered_at: str,
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[RegistryRow] = []
    for node in soup.select(".faq_cont li[data-no]"):
        item_id = normalize_space(node.get("data-no"))
        title_node = node.find("b")
        title = normalize_space(title_node.get_text(" ", strip=True)) if title_node else ""
        if not item_id or not title:
            continue
        category_match = re.match(r"^\[([^\]]+)\]", title)
        category = category_match.group(1) if category_match else "unknown"
        is_event = category == "이벤트"
        rows.append(
            make_registry_row(
                source_id="dnf_faq",
                source_kind="faq",
                listing_url=set_query_params(listing_url, page=page_number),
                canonical_url=set_query_params(f"{BASE_URL}/customer/faq", faq_no=item_id),
                title=title,
                category=category,
                discovered_at=discovered_at,
                published_at=None,
                period_start=None,
                period_end=None,
                page_number=page_number,
                eligible_for_collection=not is_event,
                eligibility_reason=(
                    "event_faq_requires_validity_from_detail" if is_event else "currently_listed_faq"
                ),
                status="unknown" if is_event else "current",
                default_exposure=not is_event,
                source_item_id=item_id,
                canonical_url_kind="synthetic_inline_item_locator",
            )
        )
    return rows


def parse_policy_page(
    html: str,
    *,
    listing_url: str,
    discovered_at: str,
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    select = soup.select_one("#revisionList")
    if not select:
        return []
    revisions = sorted(
        {
            normalize_space(option.get("value"))
            for option in select.find_all("option")
            if parse_date(option.get("value"))
        },
        reverse=True,
    )
    current = revisions[0] if revisions else None
    rows = []
    for revision in revisions:
        is_current = revision == current
        rows.append(
            make_registry_row(
                source_id="dnf_account_policy",
                source_kind="account_policy",
                listing_url=listing_url,
                canonical_url=set_query_params(listing_url, revision=revision, type=1),
                title=f"던전앤파이터 운영정책 ({revision} 시행)",
                category="운영정책",
                discovered_at=discovered_at,
                published_at=revision,
                period_start=revision,
                period_end=None,
                page_number=1,
                eligible_for_collection=True,
                eligibility_reason="current_policy_revision" if is_current else "historical_policy_revision",
                status="current" if is_current else "superseded",
                default_exposure=is_current,
                source_item_id=revision,
            )
        )
    return rows


def parse_shop_page(
    html: str,
    *,
    listing_url: str,
    page_number: int,
    discovered_at: str,
    as_of: date,
    sale_category: str,
    source_id: str = "dnf_seria_shop",
    source_kind: str = "shop_product",
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    cutoff = subtract_months(as_of, 12)
    rows = []
    for node in soup.select("article.seriashop ul[data-id]"):
        item_id = normalize_space(node.get("data-id"))
        title_node = node.select_one("li b")
        title = normalize_space(title_node.get_text(" ", strip=True)) if title_node else ""
        period_start, period_end = parse_period(node.get_text(" ", strip=True))
        if not item_id or not title:
            continue
        if sale_category == "active":
            eligible, reason, status, exposure = True, "currently_sold_or_listed", "current", True
        elif period_end:
            eligible = date.fromisoformat(period_end) >= cutoff
            reason = (
                f"ended_on_or_after_{cutoff.isoformat()}"
                if eligible
                else f"ended_before_{cutoff.isoformat()}"
            )
            status, exposure = "expired", False
        else:
            eligible, reason, status, exposure = False, "closed_sale_missing_end_date", "unknown", False
        rows.append(
            make_registry_row(
                source_id=source_id,
                source_kind=source_kind,
                listing_url=set_query_params(listing_url, page=page_number),
                canonical_url=f"{BASE_URL}/community/news/seriashop/{item_id}",
                title=title,
                category=sale_category,
                discovered_at=discovered_at,
                published_at=period_start,
                period_start=period_start,
                period_end=period_end,
                page_number=page_number,
                eligible_for_collection=eligible,
                eligibility_reason=reason,
                status=status,
                default_exposure=exposure,
                source_item_id=item_id,
            )
        )
    return rows


def parse_monthly_item_page(
    html: str,
    *,
    listing_url: str,
    discovered_at: str,
    as_of: date,
) -> list[RegistryRow]:
    soup = BeautifulSoup(html, "html.parser")
    heading = next(
        (normalize_space(node.get_text(" ", strip=True)) for node in soup.find_all("h3") if normalize_space(node.get_text(" ", strip=True))),
        "",
    )
    if not heading:
        return []
    period_start, period_end = parse_period(soup.get_text(" ", strip=True))
    cutoff = subtract_months(as_of, 12)
    if period_end and date.fromisoformat(period_end) < as_of:
        eligible = date.fromisoformat(period_end) >= cutoff
        reason, status, exposure = (
            f"ended_on_or_after_{cutoff.isoformat()}" if eligible else f"ended_before_{cutoff.isoformat()}",
            "expired",
            False,
        )
    else:
        eligible, reason, status, exposure = True, "currently_listed_monthly_item", "current", True
    return [
        make_registry_row(
            source_id="dnf_monthly_item",
            source_kind="monthly_item",
            listing_url=listing_url,
            canonical_url=listing_url,
            title=heading,
            category="monthly_item",
            discovered_at=discovered_at,
            published_at=period_start,
            period_start=period_start,
            period_end=period_end,
            page_number=1,
            eligible_for_collection=eligible,
            eligibility_reason=reason,
            status=status,
            default_exposure=exposure,
            source_item_id=period_start or heading,
        )
    ]


def _progress_page(progress: Progress, source_id: str, page: int, last_page: int) -> None:
    if page == 1 or page == last_page or page % 25 == 0:
        progress(f"[{source_id}] page {page}/{last_page}")


def discover_board_source(
    *,
    source_id: str,
    section: str,
    fetch_html: FetchHtml,
    discovered_at: str,
    as_of: date,
    progress: Progress,
    season_start_override: str | None = None,
) -> tuple[list[RegistryRow], dict[str, Any], dict[str, Any]]:
    listing_url = LISTING_URLS[source_id]
    first_html = fetch_html(listing_url)
    last_page = parse_last_page(first_html)
    rows: list[RegistryRow] = []
    for page in range(1, last_page + 1):
        html = first_html if page == 1 else fetch_html(set_query_params(listing_url, page=page))
        page_rows = parse_board_page(
            source_id=source_id,
            section=section,
            html=html,
            listing_url=listing_url,
            page_number=page,
            discovered_at=discovered_at,
            as_of=as_of,
        )
        if not page_rows:
            raise RuntimeError(f"Parser returned no rows at {source_id} page {page}/{last_page}")
        rows.extend(page_rows)
        _progress_page(progress, source_id, page, last_page)
    context: dict[str, Any] = {}
    if section == "update":
        season_start = season_start_override or detect_season_start(rows)
        apply_update_policy(rows, season_start)
        context["season_start"] = season_start
        context["season_start_method"] = "cli_override" if season_start_override else "latest_season_act_1_listing"
    return rows, {
        "source_id": source_id,
        "status": "complete",
        "listing_urls": [listing_url],
        "pages_expected": last_page,
        "pages_fetched": last_page,
        "pagination_complete": True,
        "scope_complete": True,
        "notes": [],
        "errors": [],
    }, context


def discover_simple_source(
    *,
    source_id: str,
    fetch_html: FetchHtml,
    discovered_at: str,
    as_of: date,
) -> tuple[list[RegistryRow], dict[str, Any]]:
    listing_url = LISTING_URLS[source_id]
    html = fetch_html(listing_url)
    if source_id == "dnf_game_guide":
        rows = parse_guide_page(html, listing_url=listing_url, discovered_at=discovered_at)
        status, notes = "complete", []
    elif source_id == "dnf_account_policy":
        rows = parse_policy_page(html, listing_url=listing_url, discovered_at=discovered_at)
        status, notes = "complete", []
    else:
        raise RuntimeError(f"Unsupported simple source: {source_id}")
    if not rows:
        raise RuntimeError(f"Parser returned no rows for {source_id}")
    return rows, {
        "source_id": source_id,
        "status": status,
        "listing_urls": [listing_url],
        "pages_expected": 1,
        "pages_fetched": 1,
        "pagination_complete": True,
        "scope_complete": status == "complete",
        "notes": notes,
        "errors": [],
    }


def discover_event_source(
    fetch_html: FetchHtml,
    *,
    discovered_at: str,
    as_of: date,
    progress: Progress,
) -> tuple[list[RegistryRow], dict[str, Any]]:
    source_id = "dnf_event"
    current_url = LISTING_URLS[source_id]
    current_html = fetch_html(current_url)
    current_rows = parse_event_page(
        current_html,
        listing_url=current_url,
        discovered_at=discovered_at,
        as_of=as_of,
    )
    if not current_rows:
        raise RuntimeError("Parser returned no rows for current events")

    archive_html = fetch_html(EVENT_ARCHIVE_URL)
    archive_last_page = parse_last_page(archive_html)
    archive_rows: list[RegistryRow] = []
    for page in range(1, archive_last_page + 1):
        page_url = EVENT_ARCHIVE_URL if page == 1 else set_query_params(
            EVENT_ARCHIVE_URL, page=page
        )
        html = archive_html if page == 1 else fetch_html(page_url)
        page_rows = parse_event_page(
            html,
            listing_url=page_url,
            discovered_at=discovered_at,
            as_of=as_of,
        )
        if not page_rows:
            raise RuntimeError(
                f"Parser returned no ended-event rows at page {page}/{archive_last_page}"
            )
        archive_rows.extend(page_rows)
        _progress_page(progress, f"{source_id}:archive", page, archive_last_page)

    return current_rows + archive_rows, {
        "source_id": source_id,
        "status": "complete",
        "listing_urls": [current_url, EVENT_ARCHIVE_URL],
        "pages_expected": 1 + archive_last_page,
        "pages_fetched": 1 + archive_last_page,
        "pagination_complete": True,
        "scope_complete": True,
        "notes": [
            "Ended events were discovered through categoryType=3; URLs repeated on the current listing are deduplicated."
        ],
        "errors": [],
    }


def discover_monthly_item_source(
    fetch_html: FetchHtml,
    *,
    discovered_at: str,
    as_of: date,
    progress: Progress,
) -> tuple[list[RegistryRow], dict[str, Any]]:
    source_id = "dnf_monthly_item"
    current_url = LISTING_URLS[source_id]
    current_html = fetch_html(current_url)
    current_rows = parse_monthly_item_page(
        current_html,
        listing_url=current_url,
        discovered_at=discovered_at,
        as_of=as_of,
    )
    if not current_rows:
        raise RuntimeError("Parser returned no current monthly-item row")

    archive_html = fetch_html(MONTHLY_ITEM_ARCHIVE_URL)
    archive_last_page = parse_last_page(archive_html)
    archive_rows: list[RegistryRow] = []
    for page in range(1, archive_last_page + 1):
        page_url = MONTHLY_ITEM_ARCHIVE_URL if page == 1 else set_query_params(
            MONTHLY_ITEM_ARCHIVE_URL, page=page
        )
        html = archive_html if page == 1 else fetch_html(page_url)
        page_rows = parse_shop_page(
            html,
            listing_url=page_url,
            page_number=page,
            discovered_at=discovered_at,
            as_of=as_of,
            sale_category="closed",
            source_id=source_id,
            source_kind="monthly_item",
        )
        if not page_rows:
            raise RuntimeError(
                f"Parser returned no monthly-item archive rows at page {page}/{archive_last_page}"
            )
        archive_rows.extend(page_rows)
        _progress_page(progress, f"{source_id}:archive", page, archive_last_page)

    return current_rows + archive_rows, {
        "source_id": source_id,
        "status": "complete",
        "listing_urls": [current_url, MONTHLY_ITEM_ARCHIVE_URL],
        "pages_expected": 1 + archive_last_page,
        "pages_fetched": 1 + archive_last_page,
        "pagination_complete": True,
        "scope_complete": True,
        "notes": [
            "Historical monthly items were discovered through the closed Seria Shop searchKeyword route."
        ],
        "errors": [],
    }


def discover_faq_source(
    fetch_html: FetchHtml,
    *,
    discovered_at: str,
    progress: Progress,
) -> tuple[list[RegistryRow], dict[str, Any]]:
    source_id = "dnf_faq"
    listing_url = LISTING_URLS[source_id]
    first_html = fetch_html(listing_url)
    last_page = parse_last_page(first_html)
    rows: list[RegistryRow] = []
    for page in range(1, last_page + 1):
        html = first_html if page == 1 else fetch_html(set_query_params(listing_url, page=page))
        page_rows = parse_faq_page(
            html,
            listing_url=listing_url,
            page_number=page,
            discovered_at=discovered_at,
        )
        if not page_rows:
            raise RuntimeError(f"Parser returned no FAQ rows at page {page}/{last_page}")
        rows.extend(page_rows)
        _progress_page(progress, source_id, page, last_page)
    return rows, {
        "source_id": source_id,
        "status": "complete",
        "listing_urls": [listing_url],
        "pages_expected": last_page,
        "pages_fetched": last_page,
        "pagination_complete": True,
        "scope_complete": True,
        "notes": ["FAQ entries are inline items; canonical_url is a deterministic synthetic locator by data-no."],
        "errors": [],
    }


def _closed_shop_page_is_outside_policy(rows: list[RegistryRow], cutoff: date) -> bool:
    if not rows or any(not row["period_end"] for row in rows):
        return False
    return all(date.fromisoformat(row["period_end"]) < cutoff for row in rows)


def discover_shop_source(
    fetch_html: FetchHtml,
    *,
    discovered_at: str,
    as_of: date,
    progress: Progress,
) -> tuple[list[RegistryRow], dict[str, Any]]:
    source_id = "dnf_seria_shop"
    base_listing = LISTING_URLS[source_id]
    rows: list[RegistryRow] = []
    pages_expected = 0
    pages_fetched = 0
    stopped_at_policy_cutoff = False
    cutoff = subtract_months(as_of, 12)
    listing_urls = []
    for category_number, sale_category in ((1, "active"), (2, "closed")):
        listing_url = set_query_params(base_listing, category=category_number)
        listing_urls.append(listing_url)
        first_html = fetch_html(listing_url)
        last_page = parse_last_page(first_html)
        pages_expected += last_page
        for page in range(1, last_page + 1):
            html = first_html if page == 1 else fetch_html(set_query_params(listing_url, page=page))
            page_rows = parse_shop_page(
                html,
                listing_url=listing_url,
                page_number=page,
                discovered_at=discovered_at,
                as_of=as_of,
                sale_category=sale_category,
            )
            if not page_rows:
                raise RuntimeError(
                    f"Parser returned no shop rows for {sale_category} page {page}/{last_page}"
                )
            rows.extend(page_rows)
            pages_fetched += 1
            _progress_page(progress, f"{source_id}:{sale_category}", page, last_page)
            if sale_category == "closed" and _closed_shop_page_is_outside_policy(page_rows, cutoff):
                stopped_at_policy_cutoff = page < last_page
                break
    notes = []
    if stopped_at_policy_cutoff:
        notes.append(
            f"Closed-sale pagination stopped after a full page ended before policy cutoff {cutoff.isoformat()}."
        )
    return rows, {
        "source_id": source_id,
        "status": "complete_for_policy_window",
        "listing_urls": listing_urls,
        "pages_expected": pages_expected,
        "pages_fetched": pages_fetched,
        "pagination_complete": pages_fetched == pages_expected,
        "scope_complete": True,
        "notes": notes,
        "errors": [],
    }


def deduplicate_registry(rows: list[RegistryRow]) -> tuple[list[RegistryRow], int]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            row["canonical_url"],
            row["source_id"],
            row["page_number"],
            row["title"],
        ),
    )
    unique: dict[str, RegistryRow] = {}
    for row in sorted_rows:
        unique.setdefault(row["canonical_url"], row)
    result = sorted(
        unique.values(),
        key=lambda row: (row["source_id"], row["canonical_url"], row["source_kind"]),
    )
    return result, len(rows) - len(result)


def _finalize_source_runs(
    source_runs: list[dict[str, Any]], observations: list[RegistryRow]
) -> None:
    by_source: dict[str, list[RegistryRow]] = defaultdict(list)
    for row in observations:
        by_source[row["source_id"]].append(row)
    for run in source_runs:
        source_rows = by_source.get(run["source_id"], [])
        unique_urls = {row["canonical_url"] for row in source_rows}
        run["discovered_observation_count"] = len(source_rows)
        run["unique_url_count"] = len(unique_urls)
        run["duplicate_url_count"] = len(source_rows) - len(unique_urls)


def discover_all_sources(
    fetch_html: FetchHtml,
    *,
    discovered_at: str,
    season_start_override: str | None = None,
    progress: Progress | None = None,
) -> tuple[list[RegistryRow], list[dict[str, Any]], dict[str, Any]]:
    as_of = parse_discovered_at(discovered_at).date()
    progress = progress or (lambda _message: None)
    observations: list[RegistryRow] = []
    source_runs: list[dict[str, Any]] = []
    context: dict[str, Any] = {
        "as_of_date": as_of.isoformat(),
        "notice_cutoff": subtract_months(as_of, 12).isoformat(),
        "event_cutoff": subtract_months(as_of, 6).isoformat(),
        "shop_cutoff": subtract_months(as_of, 12).isoformat(),
    }

    def run(source_id: str, operation: Callable[[], tuple[list[RegistryRow], dict[str, Any], dict[str, Any] | None]]) -> None:
        try:
            rows, metadata, source_context = operation()
            observations.extend(rows)
            source_runs.append(metadata)
            if source_context:
                context.update(source_context)
        except Exception as exc:
            source_runs.append(
                {
                    "source_id": source_id,
                    "status": "blocked",
                    "listing_urls": [LISTING_URLS[source_id]],
                    "pages_expected": None,
                    "pages_fetched": 0,
                    "pagination_complete": False,
                    "scope_complete": False,
                    "notes": [],
                    "errors": [str(exc)],
                }
            )
            progress(f"[{source_id}] blocked: {exc}")

    run(
        "dnf_notice",
        lambda: (*discover_board_source(
            source_id="dnf_notice",
            section="notice",
            fetch_html=fetch_html,
            discovered_at=discovered_at,
            as_of=as_of,
            progress=progress,
        ),),
    )
    run(
        "dnf_update",
        lambda: (*discover_board_source(
            source_id="dnf_update",
            section="update",
            fetch_html=fetch_html,
            discovered_at=discovered_at,
            as_of=as_of,
            progress=progress,
            season_start_override=season_start_override,
        ),),
    )

    for source_id in ("dnf_game_guide", "dnf_account_policy"):
        run(
            source_id,
            lambda source_id=source_id: (*discover_simple_source(
                source_id=source_id,
                fetch_html=fetch_html,
                discovered_at=discovered_at,
                as_of=as_of,
            ), None),
        )
    run(
        "dnf_event",
        lambda: (*discover_event_source(
            fetch_html,
            discovered_at=discovered_at,
            as_of=as_of,
            progress=progress,
        ), None),
    )
    run(
        "dnf_monthly_item",
        lambda: (*discover_monthly_item_source(
            fetch_html,
            discovered_at=discovered_at,
            as_of=as_of,
            progress=progress,
        ), None),
    )
    run(
        "dnf_faq",
        lambda: (*discover_faq_source(
            fetch_html,
            discovered_at=discovered_at,
            progress=progress,
        ), None),
    )
    run(
        "dnf_seria_shop",
        lambda: (*discover_shop_source(
            fetch_html,
            discovered_at=discovered_at,
            as_of=as_of,
            progress=progress,
        ), None),
    )

    source_runs.sort(key=lambda item: item["source_id"])
    _finalize_source_runs(source_runs, observations)
    registry, duplicate_count = deduplicate_registry(observations)
    context["duplicate_url_count"] = duplicate_count
    return registry, source_runs, context


def calculate_coverage(
    registry: list[RegistryRow],
    source_runs: list[dict[str, Any]],
    existing_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    existing_urls = {canonicalize_url(row["canonical_url"]) for row in existing_documents}
    run_by_source = {run["source_id"]: run for run in source_runs}
    rows_by_source: dict[str, list[RegistryRow]] = defaultdict(list)
    for row in registry:
        rows_by_source[row["source_id"]].append(row)

    by_source: dict[str, Any] = {}
    all_eligible: set[str] = set()
    all_covered: set[str] = set()
    for source_id in sorted(run_by_source):
        rows = rows_by_source.get(source_id, [])
        discovered = {row["canonical_url"] for row in rows}
        eligible = {row["canonical_url"] for row in rows if row["eligible_for_collection"]}
        covered = eligible & existing_urls
        missing = eligible - existing_urls
        all_eligible.update(eligible)
        all_covered.update(covered)
        by_source[source_id] = {
            "status": run_by_source[source_id]["status"],
            "discovered_total": len(discovered),
            "eligible_total": len(eligible),
            "already_covered": len(covered),
            "missing_eligible": len(missing),
            "duplicate_url": run_by_source[source_id].get("duplicate_url_count", 0),
            "coverage_rate": round(len(covered) / len(eligible), 6) if eligible else None,
            "covered_urls": sorted(covered),
            "missing_eligible_urls": sorted(missing),
        }

    discovered_urls = {row["canonical_url"] for row in registry}
    within_source_duplicates = sum(
        run.get("duplicate_url_count", 0) for run in source_runs
    )
    observation_counts = [run.get("discovered_observation_count") for run in source_runs]
    if all(isinstance(count, int) for count in observation_counts):
        duplicate_count = sum(observation_counts) - len(discovered_urls)
    else:
        duplicate_count = within_source_duplicates
    return {
        "discovered_total": len(discovered_urls),
        "eligible_total": len(all_eligible),
        "already_covered": len(all_covered),
        "missing_eligible": len(all_eligible - existing_urls),
        "duplicate_url": duplicate_count,
        "cross_source_duplicate_url": duplicate_count - within_source_duplicates,
        "coverage_rate": round(len(all_covered) / len(all_eligible), 6) if all_eligible else None,
        "existing_document_total": len(existing_documents),
        "existing_document_url_total": len(existing_urls),
        "blocked_sources": sorted(
            run["source_id"] for run in source_runs if run["status"] == "blocked"
        ),
        "partial_sources": sorted(
            run["source_id"] for run in source_runs if run["status"] == "partial"
        ),
        "by_source": by_source,
    }


def validate_registry_rows(rows: list[RegistryRow]) -> None:
    seen_urls: set[str] = set()
    for index, row in enumerate(rows, start=1):
        missing = [key for key in REGISTRY_REQUIRED_FIELDS if key not in row]
        if missing:
            raise RuntimeError(f"Registry row {index} is missing required fields: {missing}")
        canonical_url = row["canonical_url"]
        if canonical_url in seen_urls:
            raise RuntimeError(f"Registry contains duplicate canonical_url: {canonical_url}")
        seen_urls.add(canonical_url)


def serialize_registry(rows: list[RegistryRow]) -> bytes:
    validate_registry_rows(rows)
    ordered = sorted(rows, key=lambda row: (row["source_id"], row["canonical_url"]))
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for row in ordered
    )


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DNF RAG v3 공식 출처 URL discovery coverage",
        "",
        f"- discovery 기준 시각: `{report['discovered_at']}`",
        f"- registry: `{report['registry_path']}`",
        f"- registry SHA-256: `{report['registry_sha256']}`",
        f"- manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## 전체 결과",
        "",
        "| discovered | eligible | existing covered | missing eligible | duplicate observations | coverage |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['discovered_total']} | {summary['eligible_total']} | "
            f"{summary['already_covered']} | {summary['missing_eligible']} | "
            f"{summary['duplicate_url']} | {summary['coverage_rate']} |"
        ),
        "",
        "## 출처별 coverage",
        "",
        "| source | 상태 | 발견 | eligible | covered | missing | duplicate | coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for source_id, item in report["by_source"].items():
        lines.append(
            f"| `{source_id}` | {item['status']} | {item['discovered_total']} | "
            f"{item['eligible_total']} | {item['already_covered']} | "
            f"{item['missing_eligible']} | {item['duplicate_url']} | {item['coverage_rate']} |"
        )
    lines.extend(
        [
            "",
            "## pagination·scope 상태",
            "",
            "| source | fetched / expected pages | pagination | scope | 비고 |",
            "|---|---:|---|---|---|",
        ]
    )
    for run in report["source_runs"]:
        expected = "?" if run["pages_expected"] is None else str(run["pages_expected"])
        notes = " ".join([*run.get("notes", []), *run.get("errors", [])])
        lines.append(
            f"| `{run['source_id']}` | {run['pages_fetched']} / {expected} | "
            f"{run['pagination_complete']} | {run['scope_complete']} | {notes} |"
        )
    blocked = report["summary"]["blocked_sources"]
    partial = report["summary"]["partial_sources"]
    archive_note = (
        "- partial source의 archive 경로는 추가 discovery가 필요하다."
        if partial
        else "- 종료 이벤트와 과거 이달의 아이템 archive 경로까지 실측했다."
    )
    lines.extend(
        [
            "",
            "## 차단·미측정",
            "",
            f"- blocked sources: {', '.join(blocked) if blocked else '없음'}",
            f"- partial sources: {', '.join(partial) if partial else '없음'}",
            archive_note,
            "- FAQ는 direct detail URL이 없는 inline 항목이라 `data-no` 기반 synthetic locator를 사용했다.",
            "- 출처별 duplicate는 각 listing 내 반복이며, 전체 duplicate에는 서로 다른 listing이 같은 canonical URL을 발견한 경우도 포함한다.",
            "",
            "## 승격 판정",
            "",
            f"**상세 본문 수집: {report['detail_collection_decision']}**",
            "",
            report["decision_reason"],
            "",
            "이번 실행은 URL/항목 discovery만 수행했다. 상세 본문, ChunkV3, BM25, Router, 학습은 실행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def freeze_discovery(
    *,
    registry: list[RegistryRow],
    source_runs: list[dict[str, Any]],
    context: dict[str, Any],
    discovered_at: str,
    existing_documents_path: Path,
    discovery_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    existing_documents = read_jsonl(existing_documents_path)
    registry_bytes = serialize_registry(registry)
    registry_sha256 = hashlib.sha256(registry_bytes).hexdigest()
    registry_path = discovery_dir / f"source_registry_{registry_sha256}.jsonl"
    _write_immutable(registry_path, registry_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "discovery_parser_version": DISCOVERY_PARSER_VERSION,
        "discovered_at": discovered_at,
        "registry_path": registry_path.as_posix(),
        "registry_sha256": registry_sha256,
        "registry_row_count": len(registry),
        "existing_documents_path": existing_documents_path.as_posix(),
        "existing_documents_sha256": file_sha256(existing_documents_path),
        "existing_document_count": len(existing_documents),
        "policy_context": context,
        "source_runs": source_runs,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = discovery_dir / f"source_registry_manifest_{manifest_sha256}.json"
    _write_immutable(manifest_path, manifest_bytes)

    coverage = calculate_coverage(registry, source_runs, existing_documents)
    detail_decision = "GO" if not coverage["blocked_sources"] and not coverage["partial_sources"] else "NO-GO"
    if detail_decision == "GO":
        decision_reason = "모든 출처의 discovery scope가 완료되어 source별 detail 수집 arm을 설계할 수 있다."
    else:
        decision_reason = (
            "전체 공식 코퍼스의 상세 수집으로 승격하지 않는다. blocked/partial scope를 먼저 해소하거나 "
            "명시적으로 제외 승인한 뒤 source별 수집 arm을 시작해야 한다."
        )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "discovered_at": discovered_at,
        "registry_path": registry_path.as_posix(),
        "registry_sha256": registry_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "existing_documents_path": existing_documents_path.as_posix(),
        "existing_documents_sha256": file_sha256(existing_documents_path),
        "summary": {key: value for key, value in coverage.items() if key != "by_source"},
        "by_source": coverage["by_source"],
        "source_runs": source_runs,
        "policy_context": context,
        "detail_collection_decision": detail_decision,
        "decision_reason": decision_reason,
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    report_json_path = report_dir / f"source_discovery_coverage_{report_sha256}.json"
    report_md_path = report_dir / f"source_discovery_coverage_{report_sha256}.md"
    _write_immutable(report_json_path, report_bytes)
    _write_immutable(report_md_path, render_markdown(report).encode("utf-8"))
    return {
        "registry_path": registry_path.as_posix(),
        "registry_sha256": registry_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_md_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": report["by_source"],
        "detail_collection_decision": detail_decision,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover official DNF source URLs without collecting detail bodies."
    )
    parser.add_argument(
        "--discovered-at",
        required=True,
        help="Fixed ISO timestamp used in every row so a repeated freeze can be deterministic.",
    )
    parser.add_argument("--season-start", help="Optional explicit current-season start date (YYYY-MM-DD).")
    parser.add_argument("--existing-documents", type=Path, default=DEFAULT_EXISTING_DOCUMENTS)
    parser.add_argument("--discovery-dir", type=Path, default=DEFAULT_DISCOVERY_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
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
    parse_discovered_at(args.discovered_at)
    if args.season_start and not parse_date(args.season_start):
        raise RuntimeError(f"Invalid --season-start date: {args.season_start!r}")
    if not args.existing_documents.is_file():
        raise RuntimeError(f"Existing DocumentV3 artifact does not exist: {args.existing_documents}")
    fetcher = RateLimitedFetcher(
        interval_seconds=args.request_interval,
        retries=args.retries,
        timeout_seconds=args.timeout,
    )
    registry, source_runs, context = discover_all_sources(
        fetcher,
        discovered_at=args.discovered_at,
        season_start_override=args.season_start,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    result = freeze_discovery(
        registry=registry,
        source_runs=source_runs,
        context=context,
        discovered_at=args.discovered_at,
        existing_documents_path=args.existing_documents,
        discovery_dir=args.discovery_dir,
        report_dir=args.report_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
