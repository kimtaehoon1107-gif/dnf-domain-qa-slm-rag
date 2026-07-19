from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.discover_sources import (
    EVENT_ARCHIVE_URL,
    MONTHLY_ITEM_ARCHIVE_URL,
    REGISTRY_REQUIRED_FIELDS,
    apply_update_policy,
    calculate_coverage,
    deduplicate_registry,
    detect_season_start,
    discover_board_source,
    discover_event_source,
    discover_monthly_item_source,
    make_registry_row,
    parse_board_page,
    parse_event_page,
    parse_faq_page,
    parse_guide_page,
    parse_policy_page,
    parse_shop_page,
    serialize_registry,
    set_query_params,
)


DISCOVERED_AT = "2026-07-17T12:00:00+09:00"
ROOT = Path(__file__).resolve().parents[2]
FROZEN_REGISTRY = ROOT / "data/v3/discovery/source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
FROZEN_MANIFEST = ROOT / "data/v3/discovery/source_registry_manifest_4cbd8c441fd694ec16ad30b6b42c4c6f28326dc9a768d883399419ef87ee9ea2.json"
FROZEN_REPORT = ROOT / "reports/v3/source_discovery_coverage_808b68170bcf209dcbeb871efe249fa6eb151dc9efdb4ab887a8a5e137c0ff45.json"


def _board_html(items: list[dict], last_page: int = 1) -> str:
    rows = []
    for item in items:
        row_class = ' class="notice"' if item.get("pinned") else ""
        rows.append(
            f"""
            <ul{row_class}>
              <li class="category">{item['category']}</li>
              <li class="title" data-no="{item['id']}">{item['title']}</li>
              <li class="date">{item['date']}</li>
            </ul>
            """
        )
    return (
        "<article class=\"board_list\">"
        + "".join(rows)
        + f"</article><div class=\"paging\"><a class=\"end\" data-page=\"{last_page}\"></a></div>"
    )


def _registry_row(url: str, *, eligible: bool = True) -> dict:
    return make_registry_row(
        source_id="dnf_notice",
        source_kind="general_notice",
        listing_url="https://df.nexon.com/community/news/notice/list?page=1",
        canonical_url=url,
        title="테스트",
        category="공지",
        discovered_at=DISCOVERED_AT,
        published_at="2026-07-01",
        period_start=None,
        period_end=None,
        page_number=1,
        eligible_for_collection=eligible,
        eligibility_reason="fixture",
        status="current",
        default_exposure=eligible,
        source_item_id=url.rsplit("/", 1)[-1],
    )


class DiscoverSourcesTest(unittest.TestCase):
    def test_board_pagination_and_url_dedup_are_complete(self) -> None:
        listing_url = "https://df.nexon.com/community/news/notice/list"
        first = _board_html(
            [
                {"id": "100", "category": "공지", "title": "고정 공지", "date": "2024.01.01", "pinned": True},
                {"id": "101", "category": "점검", "title": "점검 안내", "date": "2026.07.01"},
            ],
            last_page=2,
        )
        second = _board_html(
            [
                {"id": "100", "category": "공지", "title": "고정 공지", "date": "2024.01.01", "pinned": True},
                {"id": "99", "category": "공지", "title": "오래된 공지", "date": "2024.01.01"},
            ],
            last_page=2,
        )
        pages = {listing_url: first, set_query_params(listing_url, page=2): second}
        fetched: list[str] = []

        def fetch(url: str) -> str:
            fetched.append(url)
            return pages[url]

        observations, run, _context = discover_board_source(
            source_id="dnf_notice",
            section="notice",
            fetch_html=fetch,
            discovered_at=DISCOVERED_AT,
            as_of=date(2026, 7, 17),
            progress=lambda _message: None,
        )
        registry, duplicate_count = deduplicate_registry(observations)

        self.assertEqual(fetched, [listing_url, set_query_params(listing_url, page=2)])
        self.assertEqual(run["pages_fetched"], 2)
        self.assertTrue(run["pagination_complete"])
        self.assertEqual(len(observations), 4)
        self.assertEqual(len(registry), 3)
        self.assertEqual(duplicate_count, 1)
        by_id = {row["source_item_id"]: row for row in registry}
        self.assertTrue(by_id["100"]["eligible_for_collection"])
        self.assertEqual(by_id["101"]["source_kind"], "maintenance")
        self.assertFalse(by_id["99"]["eligible_for_collection"])

    def test_update_policy_separates_live_preview_and_old_revisions(self) -> None:
        html = _board_html(
            [
                {"id": "3", "category": "업데이트", "title": "시즌 11 Act 1. 시작", "date": "2026.04.22"},
                {"id": "2", "category": "퍼스트서버", "title": "퍼스트 서버 업데이트", "date": "2026.05.01"},
                {"id": "1", "category": "업데이트", "title": "과거 업데이트", "date": "2025.01.01"},
            ]
        )
        rows = parse_board_page(
            source_id="dnf_update",
            section="update",
            html=html,
            listing_url="https://df.nexon.com/community/news/update/list",
            page_number=1,
            discovered_at=DISCOVERED_AT,
            as_of=date(2026, 7, 17),
        )
        season_start = detect_season_start(rows)
        apply_update_policy(rows, season_start)
        by_id = {row["source_item_id"]: row for row in rows}

        self.assertEqual(season_start, "2026-04-22")
        self.assertTrue(by_id["3"]["eligible_for_collection"])
        self.assertTrue(by_id["3"]["default_exposure"])
        self.assertEqual(by_id["2"]["source_kind"], "preview_patch")
        self.assertTrue(by_id["2"]["eligible_for_collection"])
        self.assertFalse(by_id["2"]["default_exposure"])
        self.assertFalse(by_id["1"]["eligible_for_collection"])

    def test_event_archive_completes_scope_and_deduplicates_current_urls(self) -> None:
        current_url = "https://df.nexon.com/community/news/event/list"
        current_html = (
            '<article class="board_eventlist">'
            '<li class="title" data-no="10"><b>진행 이벤트</b><span>2026.07.01 ~ 2026.08.01</span></li>'
            "</article>"
        )
        archive_html = (
            '<article class="board_eventlist">'
            '<li class="title" data-no="10"><b>진행 이벤트</b><span>2026.07.01 ~ 2026.08.01</span></li>'
            '<li class="title" data-no="9"><b>[종료] 지난 이벤트</b><span>2026.01.01 ~ 2026.04.01</span></li>'
            "</article>"
        )
        pages = {current_url: current_html, EVENT_ARCHIVE_URL: archive_html}

        rows, run = discover_event_source(
            pages.__getitem__,
            discovered_at=DISCOVERED_AT,
            as_of=date(2026, 7, 17),
            progress=lambda _message: None,
        )
        registry, duplicate_count = deduplicate_registry(rows)

        self.assertEqual(run["status"], "complete")
        self.assertTrue(run["scope_complete"])
        self.assertEqual(run["pages_fetched"], 2)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(registry), 2)
        self.assertEqual(duplicate_count, 1)
        ended = next(row for row in registry if row["source_item_id"] == "9")
        self.assertEqual(ended["status"], "expired")
        self.assertTrue(ended["eligible_for_collection"])
        self.assertFalse(ended["default_exposure"])

    def test_monthly_item_archive_paginates_and_applies_shop_window(self) -> None:
        current_url = "https://df.nexon.com/community/news/monthlyitem/"
        current_html = "<main><h3>7월 이달의 아이템</h3><p>2026.06.25 ~ 2026.07.30</p></main>"

        def archive_html(item_id: str, title: str, period: str, last_page: int = 2) -> str:
            return (
                f'<article class="seriashop"><ul data-id="{item_id}"><li><b>{title}</b></li>'
                f"<li>{period}</li></ul></article>"
                f'<div class="paging"><a class="end" data-page="{last_page}"></a></div>'
            )

        second_url = set_query_params(MONTHLY_ITEM_ARCHIVE_URL, page=2)
        pages = {
            current_url: current_html,
            MONTHLY_ITEM_ARCHIVE_URL: archive_html(
                "8", "6월 이달의 아이템", "2026.05.28 ~ 2026.06.25"
            ),
            second_url: archive_html(
                "7", "과거 이달의 아이템", "2024.01.01 ~ 2024.02.01"
            ),
        }

        rows, run = discover_monthly_item_source(
            pages.__getitem__,
            discovered_at=DISCOVERED_AT,
            as_of=date(2026, 7, 17),
            progress=lambda _message: None,
        )

        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["pages_fetched"], 3)
        self.assertTrue(run["pagination_complete"])
        self.assertEqual(len(rows), 3)
        archive_rows = [row for row in rows if row["canonical_url"].endswith(("/7", "/8"))]
        self.assertTrue(all(row["source_kind"] == "monthly_item" for row in archive_rows))
        self.assertTrue(next(row for row in archive_rows if row["source_item_id"] == "8")["eligible_for_collection"])
        self.assertFalse(next(row for row in archive_rows if row["source_item_id"] == "7")["eligible_for_collection"])

    def test_source_specific_parsers_preserve_status_and_locator_semantics(self) -> None:
        guide_rows = parse_guide_page(
            '<article class="nav"><dl><dt>초보자가이드</dt><dd><a href="/guide?no=125">성장 가이드</a></dd></dl></article>',
            listing_url="https://df.nexon.com/guide",
            discovered_at=DISCOVERED_AT,
        )
        faq_rows = parse_faq_page(
            '<div class="faq_cont"><li data-no="77"><b>[보안] OTP 문의</b></li><li data-no="78"><b>[이벤트] 기간 한정</b></li></div>',
            listing_url="https://df.nexon.com/customer/faq",
            page_number=1,
            discovered_at=DISCOVERED_AT,
        )
        policy_rows = parse_policy_page(
            '<select id="revisionList"><option value="2026-03-15">current</option><option value="2025-01-01">old</option></select>',
            listing_url="https://df.nexon.com/customer/policy/home?type=1",
            discovered_at=DISCOVERED_AT,
        )
        event_rows = parse_event_page(
            '<article class="board_eventlist"><li class="title" data-no="55"><b>종료 이벤트</b><span>2026.01.01 ~ 2026.04.01</span></li></article>',
            listing_url="https://df.nexon.com/community/news/event/list",
            discovered_at=DISCOVERED_AT,
            as_of=date(2026, 7, 17),
        )
        shop_rows = parse_shop_page(
            '<article class="seriashop"><ul data-id="88"><li><b>판매 상품</b></li><li>2026.01.01 ~ 2026.03.01</li></ul></article>',
            listing_url="https://df.nexon.com/community/news/seriashop/list?category=2",
            page_number=1,
            discovered_at=DISCOVERED_AT,
            as_of=date(2026, 7, 17),
            sale_category="closed",
        )

        self.assertEqual(guide_rows[0]["category"], "초보자가이드")
        self.assertEqual(faq_rows[0]["canonical_url_kind"], "synthetic_inline_item_locator")
        self.assertFalse(faq_rows[1]["eligible_for_collection"])
        self.assertEqual(policy_rows[0]["status"], "current")
        self.assertEqual(policy_rows[1]["status"], "superseded")
        self.assertTrue(event_rows[0]["eligible_for_collection"])
        self.assertFalse(event_rows[0]["default_exposure"])
        self.assertTrue(shop_rows[0]["eligible_for_collection"])
        self.assertFalse(shop_rows[0]["default_exposure"])

    def test_registry_hash_is_order_independent_and_required_keys_are_enforced(self) -> None:
        rows = [
            _registry_row("https://df.nexon.com/community/news/notice/2"),
            _registry_row("https://df.nexon.com/community/news/notice/1"),
        ]
        first = serialize_registry(rows)
        second = serialize_registry(list(reversed(rows)))

        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
        self.assertTrue(set(REGISTRY_REQUIRED_FIELDS).issubset(rows[0]))
        invalid = [dict(rows[0])]
        invalid[0].pop("canonical_url")
        with self.assertRaisesRegex(RuntimeError, "missing required fields"):
            serialize_registry(invalid)

    def test_coverage_compares_only_eligible_urls_with_existing_documents(self) -> None:
        covered = _registry_row("https://df.nexon.com/community/news/notice/1")
        missing = _registry_row("https://df.nexon.com/community/news/notice/2")
        ineligible = _registry_row(
            "https://df.nexon.com/community/news/notice/3", eligible=False
        )
        source_runs = [
            {
                "source_id": "dnf_notice",
                "status": "complete",
                "duplicate_url_count": 0,
                "discovered_observation_count": 3,
            }
        ]
        coverage = calculate_coverage(
            [covered, missing, ineligible],
            source_runs,
            [{"canonical_url": covered["canonical_url"]}],
        )

        self.assertEqual(coverage["discovered_total"], 3)
        self.assertEqual(coverage["eligible_total"], 2)
        self.assertEqual(coverage["already_covered"], 1)
        self.assertEqual(coverage["missing_eligible"], 1)
        self.assertEqual(coverage["duplicate_url"], 0)
        self.assertEqual(coverage["cross_source_duplicate_url"], 0)

    def test_coverage_counts_cross_source_url_duplicates(self) -> None:
        registry = [_registry_row("https://df.nexon.com/community/news/notice/1")]
        source_runs = [
            {
                "source_id": "dnf_notice",
                "status": "complete",
                "duplicate_url_count": 0,
                "discovered_observation_count": 1,
            },
            {
                "source_id": "dnf_event",
                "status": "partial",
                "duplicate_url_count": 0,
                "discovered_observation_count": 1,
            },
        ]

        coverage = calculate_coverage(registry, source_runs, [])

        self.assertEqual(coverage["duplicate_url"], 1)
        self.assertEqual(coverage["cross_source_duplicate_url"], 1)


class FrozenDiscoveryArtifactTest(unittest.TestCase):
    def test_actual_cli_artifacts_are_content_addressed_and_complete(self) -> None:
        registry = read_jsonl(FROZEN_REGISTRY)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        runs = {run["source_id"]: run for run in manifest["source_runs"]}

        self.assertEqual(len(registry), 13_214)
        self.assertEqual(file_sha256(FROZEN_REGISTRY), FROZEN_REGISTRY.stem.rsplit("_", 1)[-1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[-1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[-1])
        self.assertEqual(hashlib.sha256(serialize_registry(registry)).hexdigest(), manifest["registry_sha256"])
        self.assertEqual(manifest["registry_row_count"], len(registry))
        self.assertEqual(len({row["canonical_url"] for row in registry}), len(registry))
        self.assertTrue(all(set(REGISTRY_REQUIRED_FIELDS).issubset(row) for row in registry))
        self.assertEqual((runs["dnf_notice"]["pages_fetched"], runs["dnf_notice"]["pages_expected"]), (518, 518))
        self.assertEqual((runs["dnf_update"]["pages_fetched"], runs["dnf_update"]["pages_expected"]), (95, 95))
        self.assertEqual((runs["dnf_faq"]["pages_fetched"], runs["dnf_faq"]["pages_expected"]), (16, 16))
        self.assertEqual((runs["dnf_event"]["pages_fetched"], runs["dnf_event"]["pages_expected"]), (2, 2))
        self.assertEqual((runs["dnf_monthly_item"]["pages_fetched"], runs["dnf_monthly_item"]["pages_expected"]), (26, 26))
        self.assertIn(EVENT_ARCHIVE_URL, runs["dnf_event"]["listing_urls"])
        self.assertIn(MONTHLY_ITEM_ARCHIVE_URL, runs["dnf_monthly_item"]["listing_urls"])
        restricted_rows = [
            row
            for row in registry
            if row["status"] in {"expired", "superseded"}
            or row["source_kind"] == "preview_patch"
        ]
        self.assertTrue(restricted_rows)
        self.assertTrue(all(not row["default_exposure"] for row in restricted_rows))
        self.assertEqual(report["summary"]["blocked_sources"], [])
        self.assertEqual(report["summary"]["partial_sources"], [])
        self.assertEqual(report["detail_collection_decision"], "GO")


if __name__ == "__main__":
    unittest.main()
