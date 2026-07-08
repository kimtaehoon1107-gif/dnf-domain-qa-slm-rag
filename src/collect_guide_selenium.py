from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from io_utils import write_jsonl


GUIDE_URL = "https://df.nexon.com/guide"
ARTICLE_LINK_SELECTOR = 'a[href*="guide?no="]'
# The guide body is rendered client-side (jQuery.tmpl). These containers hold the
# article once rendered; we pick the largest match and fall back to a cleaned body.
CONTENT_SELECTORS = [
    "section.content",
    ".guide_view",
    ".view_content",
    ".guide_cont",
    ".cont_wrap",
    "#contents",
    ".cont",
    "article",
    "main",
]
FOOTER_ANCHOR = "회사소개"
# Guide bodies end with a "이 문서는 YYYY-MM-DD에 업데이트 되었습니다" line and a
# "텍스트복사" copy-button label; we lift the date into published_at and drop both.
UPDATE_DATE_PATTERN = re.compile(r"이\s*문서는\s*(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})\s*에?\s*업데이트")
COPY_BUTTON_LABEL = "텍스트복사"
CATEGORY_SUFFIXES = ["상급 던전", "특수 던전", "일반 던전", "장비 시스템", "레이드", "시스템", "던전"]
# The landing "게임가이드" h1 is a section header; the real article title is the
# first heading after it.
GENERIC_TITLES = {"게임가이드", "가이드", "가이드 홈", "추천 가이드"}


def normalize_space(text: Any) -> str:
    return " ".join(str(text or "").split())


def normalize_block(text: Any) -> str:
    """Collapse whitespace within each line but preserve line breaks."""
    lines = [normalize_space(line) for line in str(text or "").split("\n")]
    return "\n".join(line for line in lines if line)


def html_to_structured_text(html: str) -> str:
    """Flatten rendered HTML to text while keeping h2/h3 headings as ## / ###
    markers and one block element per line, so chunking can split on sections."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style"):
        tag.decompose()
    for heading in soup.find_all(["h1", "h2"]):
        heading.insert_before("\n\n## ")
        heading.insert_after("\n")
    for heading in soup.find_all(["h3", "h4", "h5"]):
        heading.insert_before("\n\n### ")
        heading.insert_after("\n")
    for block in soup.find_all(["p", "li", "tr", "caption", "dt", "dd", "br"]):
        block.insert_after("\n")
    return normalize_block(soup.get_text(" "))


def make_driver(headless: bool):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise RuntimeError(
            "Selenium is required. Install it with: pip install selenium (Chrome must be installed)."
        ) from exc

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    for arg in ("--disable-gpu", "--no-sandbox", "--window-size=1400,4000", "--log-level=3"):
        options.add_argument(arg)
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    return webdriver.Chrome(options=options)


def split_menu_label(label: str) -> tuple[str, str]:
    """Landing links look like '<title> <category>'; peel a known category suffix."""
    label = normalize_space(label)
    for category in CATEGORY_SUFFIXES:
        if label.endswith(" " + category) and len(label) > len(category) + 1:
            return label[: -len(category)].strip(), category
    return label, ""


def collect_article_links(driver, wait_seconds: float) -> list[dict[str, str]]:
    driver.get(GUIDE_URL)
    time.sleep(wait_seconds)
    items: dict[str, dict[str, str]] = {}
    for anchor in driver.find_elements("css selector", ARTICLE_LINK_SELECTOR):
        href = anchor.get_attribute("href") or ""
        match = re.search(r"[?&]no=(\d+)", href)
        if not match:
            continue
        no = match.group(1)
        title, category = split_menu_label(anchor.text)
        existing = items.get(no)
        if existing is None or (title and not existing["title"]):
            items[no] = {
                "no": no,
                "title": title,
                "category": category,
                "url": f"{GUIDE_URL}?no={no}",
            }
    return list(items.values())


def strip_boilerplate(body_text: str) -> str:
    text = normalize_space(body_text)
    footer_at = text.find(FOOTER_ANCHOR)
    if footer_at > 0:
        text = text[:footer_at]
    return text.strip()


def extract_title(driver, link: dict[str, str]) -> str:
    for selector in ("h1", "h2"):
        for element in driver.find_elements("css selector", selector):
            text = normalize_space(element.text)
            if text and text not in GENERIC_TITLES:
                return text
    return link.get("title") or f"가이드 {link['no']}"


def extract_content(driver) -> str:
    best_html = ""
    best_len = 0
    for selector in CONTENT_SELECTORS:
        for element in driver.find_elements("css selector", selector):
            length = len(element.text or "")
            if length > best_len:
                best_len = length
                best_html = element.get_attribute("innerHTML") or ""
    if best_len < 200:
        return strip_boilerplate(driver.find_element("tag name", "body").text)
    return html_to_structured_text(best_html)


def finalize_text(raw_text: str) -> tuple[str, str | None]:
    """Strip copy-button labels and lift the '업데이트' date into published_at."""
    text = normalize_block(str(raw_text or "").replace(COPY_BUTTON_LABEL, " "))
    published_at = None
    match = UPDATE_DATE_PATTERN.search(text)
    if match:
        year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
        published_at = f"{year}-{month:02d}-{day:02d}"
        text = normalize_block(text[: match.start()])
    return text, published_at


def make_doc(link: dict[str, str], title: str, text: str, published_at: str | None, collected_at: str) -> dict[str, Any]:
    category = link.get("category") or ""
    tags = [tag for tag in ["official", "guide", category] if tag]
    return {
        "doc_id": f"official_guide_{link['no']}",
        "source_type": "official",
        "doc_type": "game_guide",
        "title": title,
        "published_at": published_at,
        "effective_start": None,
        "effective_end": None,
        "source_url": link["url"],
        "tags": tags,
        "text": text,
        "metadata": {
            "official_section": "guide",
            "guide_no": link["no"],
            "guide_category": category,
            "guide_updated_at": published_at or "",
            "collected_at": collected_at,
        },
    }


def collect_guide(limit: int, headless: bool, wait_seconds: float, min_chars: int) -> list[dict[str, Any]]:
    driver = make_driver(headless)
    collected_at = datetime.now().isoformat(timespec="seconds")
    docs: list[dict[str, Any]] = []
    try:
        links = collect_article_links(driver, wait_seconds)
        print(f"discovered {len(links)} guide articles", file=sys.stderr)
        for link in links:
            if len(docs) >= limit:
                break
            try:
                driver.get(link["url"])
                time.sleep(wait_seconds)
                title = extract_title(driver, link)
                text, published_at = finalize_text(extract_content(driver))
            except Exception as exc:  # keep going; report which article failed
                print(f"  failed {link['url']}: {exc}", file=sys.stderr)
                continue
            if len(text) >= min_chars:
                docs.append(make_doc(link, title, text, published_at, collected_at))
            else:
                print(f"  skipped {link['url']} (only {len(text)} chars)", file=sys.stderr)
    finally:
        driver.quit()
    return docs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect DNF official game-guide articles via Selenium.")
    parser.add_argument("--output", type=Path, default=Path("data/raw/guide_docs.jsonl"))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--wait", type=float, default=4.0, help="seconds to wait for client-side render")
    parser.add_argument("--min-chars", type=int, default=200)
    parser.add_argument("--show-browser", action="store_true", help="run with a visible browser window")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    docs = collect_guide(
        limit=args.limit,
        headless=not args.show_browser,
        wait_seconds=args.wait,
        min_chars=args.min_chars,
    )
    write_jsonl(args.output, docs)
    summary = {
        "output": str(args.output),
        "documents": len(docs),
        "avg_text_chars": round(sum(len(doc["text"]) for doc in docs) / len(docs), 1) if docs else 0,
        "by_category": {},
    }
    for doc in docs:
        category = doc["metadata"]["guide_category"] or "(none)"
        summary["by_category"][category] = summary["by_category"].get(category, 0) + 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
