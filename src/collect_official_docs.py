import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from io_utils import write_jsonl


BASE_URL = "https://df.nexon.com"
LIST_ENDPOINTS = {
    "notice": "/community/news/notice/list",
    "update": "/community/news/update/list",
    "event": "/community/news/event/list",
}
DETAIL_ENDPOINTS = {
    "notice": "/community/news/notice/{doc_no}",
    "update": "/community/news/update/{doc_no}",
    "event": "/community/news/event/{doc_no}",
}
SESSION_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DNF-Domain-QA-SLM-v2/0.1; +portfolio-crawler)"
}


@dataclass
class ListItem:
    doc_type: str
    category: str
    title: str
    doc_no: str
    published_at: str
    source_url: str
    effective_start: str | None = None
    effective_end: str | None = None


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def parse_date(value: str) -> str | None:
    match = re.search(r"20\d{2}[.-]\d{2}[.-]\d{2}", value)
    if not match:
        return None
    return match.group(0).replace(".", "-")


def fetch_html(session: requests.Session, url: str, timeout: int = 20) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def list_url(doc_type: str, page: int) -> str:
    path = LIST_ENDPOINTS[doc_type]
    if page <= 1:
        return urljoin(BASE_URL, path)
    return urljoin(BASE_URL, f"{path}?page={page}")


def parse_board_list(doc_type: str, html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.select("article.board_list ul"):
        title_el = row.select_one("li.title")
        if not title_el:
            continue
        doc_no = title_el.get("data-no")
        if not doc_no:
            continue
        category = normalize_space(row.select_one("li.category").get_text(" ", strip=True)) if row.select_one("li.category") else ""
        title = normalize_space(title_el.get_text(" ", strip=True))
        published_at = parse_date(row.select_one("li.date").get_text(" ", strip=True)) if row.select_one("li.date") else None
        if not title or not published_at:
            continue
        detail_path = DETAIL_ENDPOINTS[doc_type].format(doc_no=doc_no)
        items.append(
            ListItem(
                doc_type=doc_type,
                category=category,
                title=title,
                doc_no=doc_no,
                published_at=published_at,
                source_url=urljoin(BASE_URL, detail_path),
            )
        )
    return items


def parse_event_list(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for idx, row in enumerate(soup.select("article.board_eventlist li.title"), start=1):
        title_el = row.select_one("b")
        period_el = row.select_one("span")
        if not title_el:
            continue
        title = normalize_space(title_el.get_text(" ", strip=True))
        period = normalize_space(period_el.get_text(" ", strip=True)) if period_el else ""
        dates = [date.replace(".", "-") for date in re.findall(r"20\d{2}\.\d{2}\.\d{2}", period)]
        doc_no = row.get("data-no") or f"event_card_{idx:03d}"
        onclick = row.get("onclick", "")
        onclick_match = re.search(r"window\.location\.href='([^']+)'", onclick)
        if row.get("data-no"):
            source_url = urljoin(BASE_URL, DETAIL_ENDPOINTS["event"].format(doc_no=doc_no))
        elif onclick_match:
            source_url = urljoin(BASE_URL, onclick_match.group(1))
        else:
            source_url = urljoin(BASE_URL, LIST_ENDPOINTS["event"])
        effective_start = dates[0] if dates else None
        effective_end = dates[1] if len(dates) > 1 else None
        items.append(
            ListItem(
                doc_type="event",
                category="진행중",
                title=title,
                doc_no=doc_no,
                published_at=effective_start or datetime.now().strftime("%Y-%m-%d"),
                effective_start=effective_start,
                effective_end=effective_end,
                source_url=source_url,
            )
        )
    return items


def extract_detail_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("section.content.news") or soup.select_one("section.content")
    if not content:
        content = soup.body or soup
    for tag in content.select("script, style, nav, footer"):
        tag.decompose()
    return normalize_space(content.get_text(" ", strip=True))


def clean_event_text(text: str, item: ListItem) -> str:
    start = text.rfind(item.title)
    if start >= 0:
        text = text[start:]
    period = ""
    if item.effective_start or item.effective_end:
        period = f"이벤트 기간: {item.effective_start or ''} ~ {item.effective_end or ''}."
    if period and period not in text:
        text = f"{item.title} {period} {text}"
    return normalize_space(text)


def infer_doc_type(item: ListItem, detail_text: str) -> str:
    if item.doc_type == "update":
        return "patch_note"
    if item.doc_type == "event":
        return "event"
    text = f"{item.category} {item.title} {detail_text[:300]}"
    if "점검" in text:
        return "notice"
    if "오류" in text or "버그" in text:
        return "bug_known_issue"
    if "결제" in text or "계정" in text or "OTP" in text:
        return "account_payment"
    if "불량이용자" in text or "제재" in text or "단속" in text:
        return "operation_policy"
    if "이벤트" in text:
        return "event"
    return "notice"


def make_doc(item: ListItem, detail_text: str, collected_at: str) -> dict:
    doc_type = infer_doc_type(item, detail_text)
    source_section = item.doc_type
    doc_id = f"official_{source_section}_{item.doc_no}"
    tags = ["official", source_section, item.category, doc_type]
    return {
        "doc_id": doc_id,
        "source_type": "official",
        "doc_type": doc_type,
        "title": item.title,
        "published_at": item.published_at,
        "effective_start": item.effective_start,
        "effective_end": item.effective_end,
        "source_url": item.source_url,
        "tags": [tag for tag in tags if tag],
        "text": detail_text,
        "metadata": {
            "official_section": source_section,
            "category": item.category,
            "doc_no": item.doc_no,
            "collected_at": collected_at,
        },
    }


def collect_documents(doc_types: list[str], pages: int, limit: int, sleep_seconds: float) -> list[dict]:
    session = requests.Session()
    session.headers.update(SESSION_HEADERS)
    collected_at = datetime.now().isoformat(timespec="seconds")
    docs = []
    seen_urls = set()

    for doc_type in doc_types:
        for page in range(1, pages + 1):
            html = fetch_html(session, list_url(doc_type, page))
            items = parse_event_list(html) if doc_type == "event" else parse_board_list(doc_type, html)
            if not items:
                break
            for item in items:
                if item.source_url in seen_urls:
                    continue
                seen_urls.add(item.source_url)
                try:
                    detail_html = fetch_html(session, item.source_url)
                    detail_text = extract_detail_text(detail_html)
                    if item.doc_type == "event":
                        detail_text = clean_event_text(detail_text, item)
                except Exception as exc:
                    print(
                        f"[warn] detail fetch failed for {item.source_url}: {exc}",
                        file=sys.stderr,
                    )
                    period = ""
                    if item.effective_start or item.effective_end:
                        period = f" 기간: {item.effective_start or ''} ~ {item.effective_end or ''}."
                    detail_text = normalize_space(f"{item.title}.{period} 원문 상세 페이지를 수집하지 못했습니다.")
                if len(detail_text) >= 80:
                    docs.append(make_doc(item, detail_text, collected_at))
                if len(docs) >= limit:
                    return docs
                time.sleep(sleep_seconds)
    return docs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect official DNF notice/update/event documents.")
    parser.add_argument("--output", type=Path, default=Path("data/raw/official_docs.jsonl"))
    parser.add_argument("--types", nargs="+", choices=sorted(LIST_ENDPOINTS), default=["notice", "update", "event"])
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--sleep", type=float, default=0.2)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    docs = collect_documents(args.types, args.pages, args.limit, args.sleep)
    write_jsonl(args.output, docs)
    summary = {
        "output": str(args.output),
        "documents": len(docs),
        "by_doc_type": {},
        "by_source_section": {},
    }
    for doc in docs:
        summary["by_doc_type"][doc["doc_type"]] = summary["by_doc_type"].get(doc["doc_type"], 0) + 1
        section = doc["metadata"]["official_section"]
        summary["by_source_section"][section] = summary["by_source_section"].get(section, 0) + 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
