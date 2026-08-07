from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    ALLOWED_OUTCOMES,
    COLLECTOR_VERSION,
    FAQ_BUCKETS,
    FULL_COLLECTOR_VERSION,
    FetchResult,
    LEDGER_REQUIRED_FIELDS,
    NOTICE_KINDS,
    PREVIEW_REQUIRED_FIELDS,
    collect_detail_full,
    extract_preview,
    freeze_collection_artifacts,
    resolve_fetch_url,
    resolve_faq_node,
    select_full_rows,
    select_pilot_rows,
    structured_text,
    validate_policy_revision,
    write_immutable,
)


FETCHED_AT = "2026-07-17T20:00:00+09:00"
ROOT = Path(__file__).resolve().parents[2]
FROZEN_LEDGER = ROOT / "data/v3/collections/detail_collection_ledger_6cd39a7473272b78a0581ae739610ce73f8f7a9fa2134d5afaef919dfa18a3b7.jsonl"
FROZEN_PREVIEW = ROOT / "data/v3/collections/detail_extraction_preview_0a1a450075579dd3569ecde66fc813bf65b7660c5390f68bb995a9fd3839233a.jsonl"
FROZEN_MANIFEST = ROOT / "data/v3/collections/detail_collection_manifest_71386a3b3d6bb627422d14eccf4c29e22da5d8e666793c4e428bb93be506a07a.json"
FROZEN_REPORT = ROOT / "reports/v3/detail_collection_pilot_b06f5df59bbab93ff9852583195f9037bf93c727d9da1ee2e906c2e7ca3d17b0.json"
FROZEN_FULL_LEDGER = ROOT / "data/v3/collections/detail_full_collection_ledger_0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b.jsonl"
FROZEN_FULL_PREVIEW = ROOT / "data/v3/collections/detail_full_extraction_preview_e48f58e205a7001e23e3286cc7df2d467bf8b549f9ce449b82a46a6accf8e1dd.jsonl"
FROZEN_FULL_MANIFEST = ROOT / "data/v3/collections/detail_full_collection_manifest_f3003742b55a515e51c2abaee5a993cea9b1f108297f59c74a9aeaa201f87e97.json"
FROZEN_FULL_REPORT = ROOT / "reports/v3/detail_full_collection_8dbeef595121a34850e0358de6458999acd603b0252e632a52aec517058c3cd2.json"


def _row(
    index: int,
    *,
    source_id: str,
    source_kind: str,
    status: str = "current",
    category: str = "general",
    title: str | None = None,
    eligible: bool = True,
    exposure: bool = True,
    published_at: str | None = "2026-01-01",
    period_end: str | None = None,
    canonical_kind: str = "official_url",
) -> dict:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "listing_url": f"https://example.test/{source_id}/list?page={index}",
        "canonical_url": f"https://example.test/{source_id}/{index}",
        "canonical_url_kind": canonical_kind,
        "source_item_id": str(index),
        "title": title or f"fixture {index}",
        "category": category,
        "discovered_at": FETCHED_AT,
        "published_at": published_at,
        "period_start": published_at,
        "period_end": period_end,
        "page_number": 1,
        "eligible_for_collection": eligible,
        "eligibility_reason": "fixture",
        "status": status,
        "default_exposure": exposure,
        "is_pinned": False,
        "discovery_parser_version": "fixture",
    }


def _selection_fixture() -> list[dict]:
    rows: list[dict] = []
    index = 1
    for kind in NOTICE_KINDS:
        for _ in range(2):
            rows.append(_row(index, source_id="dnf_notice", source_kind=kind))
            index += 1
    for _ in range(4):
        rows.append(_row(index, source_id="dnf_update", source_kind="patch_note"))
        index += 1
    for _ in range(2):
        rows.append(
            _row(
                index,
                source_id="dnf_update",
                source_kind="preview_patch",
                status="unknown",
                exposure=False,
            )
        )
        index += 1
    for _ in range(3):
        rows.append(_row(index, source_id="dnf_event", source_kind="event"))
        index += 1
    for offset in range(3):
        rows.append(
            _row(
                index,
                source_id="dnf_event",
                source_kind="event",
                status="expired",
                eligible=offset < 2,
                exposure=False,
            )
        )
        index += 1
    for category in ("A", "B", "C", "D", "E", "F"):
        rows.append(
            _row(index, source_id="dnf_game_guide", source_kind="game_guide", category=category)
        )
        index += 1
    faq_examples = {
        "아이디정보/보안": ("아이디 정보", "OTP 문의"),
        "설치/실행": ("설치/실행 오류", "실행 문의"),
        "게임문의": ("게임 이용", "게임 문의"),
        "복구": ("삭제 캐릭터 복구", "복구 문의"),
        "결제": ("결제 한도", "결제 문의"),
        "PC방": ("던파PC방찾기", "PC방 문의"),
        "이벤트": ("이벤트", "이벤트 문의"),
        "던파ON": ("이용 문의", "던파ON 문의"),
    }
    for bucket in FAQ_BUCKETS:
        category, title = faq_examples[bucket]
        for _ in range(2):
            is_event = bucket == "이벤트"
            rows.append(
                _row(
                    index,
                    source_id="dnf_faq",
                    source_kind="faq",
                    status="unknown" if is_event else "current",
                    category=category,
                    title=title,
                    eligible=not is_event,
                    exposure=not is_event,
                    canonical_kind="synthetic_inline_item_locator",
                )
            )
            index += 1
    for year in range(2011, 2027):
        current = year == 2026
        rows.append(
            _row(
                index,
                source_id="dnf_account_policy",
                source_kind="account_policy",
                status="current" if current else "superseded",
                category="운영정책",
                exposure=current,
                published_at=f"{year}-01-01",
            )
        )
        index += 1
    shop_shapes = (
        ("current", True, True, None),
        ("current", True, True, "2026-12-01"),
        ("expired", True, False, "2026-01-01"),
        ("expired", False, False, "2024-01-01"),
    )
    for status, eligible, exposure, period_end in shop_shapes:
        for _ in range(2):
            rows.append(
                _row(
                    index,
                    source_id="dnf_seria_shop",
                    source_kind="shop_product",
                    status=status,
                    category="active" if status == "current" else "closed",
                    eligible=eligible,
                    exposure=exposure,
                    period_end=period_end,
                )
            )
            index += 1
    monthly_shapes = (
        ("current", True, True, 1),
        ("expired", True, False, 2),
        ("expired", False, False, 2),
    )
    for status, eligible, exposure, count in monthly_shapes:
        for _ in range(count):
            rows.append(
                _row(
                    index,
                    source_id="dnf_monthly_item",
                    source_kind="monthly_item",
                    status=status,
                    category="monthly_item" if status == "current" else "closed",
                    eligible=eligible,
                    exposure=exposure,
                )
            )
            index += 1
    return rows


class CollectDetailsTest(unittest.TestCase):
    def test_full_selection_is_deterministic_and_eligible_only(self) -> None:
        fixture = _selection_fixture()
        first, first_info = select_full_rows(fixture)
        second, second_info = select_full_rows(list(reversed(fixture)))

        self.assertEqual(first, second)
        self.assertEqual(first_info, second_info)
        self.assertEqual(len(first), sum(row["eligible_for_collection"] for row in fixture))
        self.assertTrue(all(row["eligible_for_collection"] for row in first))
        self.assertEqual(
            len(first), len({row["canonical_url"] for row in first})
        )
        self.assertEqual(first_info["selection_version"], FULL_COLLECTOR_VERSION)

    def test_pilot_selection_is_deterministic_and_stratified(self) -> None:
        fixture = _selection_fixture()
        first, first_info = select_pilot_rows(fixture)
        second, second_info = select_pilot_rows(list(reversed(fixture)))

        self.assertEqual(first, second)
        self.assertEqual(first_info, second_info)
        self.assertEqual(len(first), 64)
        self.assertEqual(first_info["selected_total"], 64)
        self.assertEqual(first_info["selected_by_source"]["dnf_faq"], 16)
        self.assertEqual(first_info["selected_by_source"]["dnf_notice"], 12)
        event_faq = [row for row in first if row["pilot_bucket"] == "faq:이벤트"]
        self.assertEqual(len(event_faq), 2)
        self.assertTrue(all(not row["eligible_for_collection"] for row in event_faq))
        preview_updates = [row for row in first if row["source_kind"] == "preview_patch"]
        self.assertTrue(preview_updates)
        self.assertTrue(all(not row["default_exposure"] for row in preview_updates))

    def test_faq_resolution_uses_data_no_from_listing_snapshot(self) -> None:
        html = b'<ul class="faq_cont"><li data-no="77"><b>Question</b><div>Answer</div></li></ul>'
        node = resolve_faq_node(html, "77")
        self.assertEqual("Question Answer", " ".join(node.get_text(" ", strip=True).split()))
        with self.assertRaisesRegex(RuntimeError, "data-no not found"):
            resolve_faq_node(html, "78")

    def test_fetch_url_resolves_inline_faq_and_monthly_trailing_slash(self) -> None:
        faq = _row(
            1,
            source_id="dnf_faq",
            source_kind="faq",
            canonical_kind="synthetic_inline_item_locator",
        )
        monthly = _row(2, source_id="dnf_monthly_item", source_kind="monthly_item")
        monthly["canonical_url"] = "https://df.nexon.com/community/news/monthlyitem"

        self.assertEqual(resolve_fetch_url(faq), faq["listing_url"])
        self.assertEqual(
            resolve_fetch_url(monthly),
            "https://df.nexon.com/community/news/monthlyitem/",
        )

    def test_policy_revision_must_be_the_selected_option(self) -> None:
        html = b'<select id="revisionList"><option value="2025-01-01">old</option><option value="2026-01-01" selected>current</option></select>'
        validate_policy_revision(html, "2026-01-01")
        with self.assertRaisesRegex(RuntimeError, "Policy revision mismatch"):
            validate_policy_revision(html, "2025-01-01")

    def test_structured_text_preserves_table_rows_and_columns(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            '<article><h2>상품</h2><table><tr><th>아이템</th><th>가격</th></tr><tr><td>상자</td><td>1,000원</td></tr></table><img src="x.png"></article>',
            "html.parser",
        )
        text, heading_count, table_count, image_count = structured_text(soup.article)

        self.assertEqual((heading_count, table_count, image_count), (1, 1, 1))
        self.assertIn("[TABLE]", text)
        self.assertIn("| 아이템 | 가격 |", text)
        self.assertIn("| 상자 | 1,000원 |", text)

    def test_extract_preview_validates_faq_and_records_price_table(self) -> None:
        row = _row(
            77,
            source_id="dnf_faq",
            source_kind="faq",
            category="결제",
            title="[결제] 가격은?",
            canonical_kind="synthetic_inline_item_locator",
        )
        row["source_item_id"] = "77"
        row["pilot_bucket"] = "faq:결제"
        html = '<ul class="faq_cont"><li data-no="77"><h3>[결제] 가격은?</h3><table><tr><td>가격</td><td>1,000원</td></tr></table></li></ul>'.encode()

        preview = extract_preview(row, html, "raw.html", {})

        self.assertTrue(preview["faq_locator_validated"])
        self.assertEqual(preview["table_count"], 1)
        self.assertTrue(preview["price_signals"])

    def test_immutable_write_and_freeze_hashes_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "detail" / "dnf_notice" / "raw_detail_fixture.html"
            raw_bytes = b"<html><article>fixture detail</article></html>"
            write_immutable(raw_path, raw_bytes)
            write_immutable(raw_path, raw_bytes)
            with self.assertRaisesRegex(RuntimeError, "Immutable artifact collision"):
                write_immutable(raw_path, b"different")

            registry_path = root / "registry.jsonl"
            registry_manifest_path = root / "registry_manifest.json"
            guide_baseline_path = root / "guide.jsonl"
            write_immutable(registry_path, b"{}\n")
            write_immutable(registry_manifest_path, b"{}\n")
            write_immutable(guide_baseline_path, b"{}\n")
            content_hash = file_sha256(raw_path)
            ledger = [
                {
                    "ledger_schema_version": "fixture",
                    "registry_sha256": file_sha256(registry_path),
                    "source_id": "dnf_notice",
                    "source_kind": "general_notice",
                    "registry_status": "current",
                    "registry_category": "general",
                    "registry_title": "fixture",
                    "pilot_bucket": "notice:general_notice",
                    "canonical_url": "https://example.test/notice/1",
                    "canonical_url_kind": "official_url",
                    "fetch_url": "https://example.test/notice/1",
                    "final_url": "https://example.test/notice/1",
                    "eligible_for_collection": True,
                    "default_exposure": True,
                    "fetch_status": "success",
                    "http_status": 200,
                    "fetched_at": FETCHED_AT,
                    "content_hash": content_hash,
                    "raw_snapshot_path": raw_path.as_posix(),
                    "raw_byte_count": len(raw_bytes),
                    "collector_version": COLLECTOR_VERSION,
                    "retry_count": 0,
                    "error": None,
                }
            ]
            previews = [
                {
                    "preview_schema_version": "fixture",
                    "canonical_url": "https://example.test/notice/1",
                    "source_id": "dnf_notice",
                    "source_kind": "general_notice",
                    "registry_status": "current",
                    "pilot_bucket": "notice:general_notice",
                    "eligible_for_collection": True,
                    "default_exposure": True,
                    "fetch_status": "success",
                    "title": "fixture",
                    "extracted_text": "fixture detail",
                    "heading_count": 0,
                    "table_count": 0,
                    "image_count": 0,
                    "published_at": "2026-01-01",
                    "valid_from": None,
                    "valid_to": None,
                    "date_signals": [],
                    "price_signals": [],
                    "extraction_warnings": [],
                    "raw_snapshot_path": raw_path.as_posix(),
                    "content_selector": "article",
                    "faq_locator_validated": None,
                    "policy_revision_validated": None,
                    "baseline_text_hash": None,
                    "baseline_text_chars": None,
                    "refresh_text_hash": None,
                    "refresh_text_chars": None,
                    "refresh_length_ratio": None,
                    "refresh_text_match": None,
                }
            ]
            kwargs = {
                "ledger": ledger,
                "previews": previews,
                "selection_info": {"selected_total": 1, "selected_by_source": {"dnf_notice": 1}},
                "registry_path": registry_path,
                "registry_manifest_path": registry_manifest_path,
                "registry_sha256": file_sha256(registry_path),
                "guide_baseline_path": guide_baseline_path,
                "fetched_at": FETCHED_AT,
                "collection_dir": root / "collections",
                "report_dir": root / "reports",
            }

            first = freeze_collection_artifacts(**kwargs)
            second = freeze_collection_artifacts(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["full_collection_decision"], "GO")
            self.assertEqual(file_sha256(Path(first["ledger_path"])), first["ledger_sha256"])
            self.assertEqual(file_sha256(Path(first["manifest_path"])), first["manifest_sha256"])
            self.assertEqual(file_sha256(Path(first["report_json_path"])), first["report_sha256"])

    def test_full_collection_checkpoint_resumes_without_refetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rows = [
                _row(1, source_id="dnf_notice", source_kind="general_notice"),
                _row(2, source_id="dnf_notice", source_kind="maintenance"),
                _row(
                    3,
                    source_id="dnf_notice",
                    source_kind="general_notice",
                    eligible=False,
                    exposure=False,
                ),
            ]
            registry_path = root / "registry.jsonl"
            registry_bytes = b"".join(
                (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                for row in rows
            )
            write_immutable(registry_path, registry_bytes)
            registry_manifest_path = root / "registry_manifest.json"
            write_immutable(
                registry_manifest_path,
                (
                    json.dumps(
                        {"registry_sha256": file_sha256(registry_path)},
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            guide_baseline_path = root / "guide.jsonl"
            write_immutable(guide_baseline_path, b"")
            checkpoint_path = root / "collections" / "checkpoint.jsonl"
            calls: list[str] = []

            def fetcher(url: str) -> FetchResult:
                calls.append(url)
                title = next(row["title"] for row in rows if row["canonical_url"] == url)
                content = (
                    f'<section class="content news"><h1>{title}</h1>'
                    f'<p>{title} 본문 검증을 위한 충분히 긴 공식 상세 문서 fixture 텍스트입니다. '
                    "같은 checkpoint로 재실행할 때 네트워크 요청이 없어야 합니다.</p></section>"
                ).encode("utf-8")
                return FetchResult("success", 200, content, 0, None, url)

            kwargs = {
                "registry_path": registry_path,
                "registry_manifest_path": registry_manifest_path,
                "guide_baseline_path": guide_baseline_path,
                "fetched_at": FETCHED_AT,
                "fetcher": fetcher,
                "detail_dir": root / "details",
                "collection_dir": root / "collections",
                "report_dir": root / "reports",
                "checkpoint_path": checkpoint_path,
            }
            first = collect_detail_full(**kwargs)
            self.assertEqual(len(calls), 2)
            calls.clear()
            second = collect_detail_full(**kwargs)

            self.assertEqual(calls, [])
            self.assertEqual(first, second)
            self.assertEqual(first["summary"]["selected_total"], 2)
            self.assertEqual(first["summary"]["success"], 2)
            self.assertEqual(first["next_stage_decision"], "GO")
            self.assertEqual(first["document_v3_promotion_decision"], "GO")
            self.assertTrue(Path(first["checkpoint_path"]).is_file())

    def test_frozen_registry_full_selection_has_982_rows(self) -> None:
        registry = read_jsonl(
            ROOT
            / "data/v3/discovery/source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
        )
        selected, selection_info = select_full_rows(registry)

        self.assertEqual(len(selected), 982)
        self.assertEqual(selection_info["selected_total"], 982)
        self.assertEqual(selection_info["selected_by_source"]["dnf_faq"], 279)


class FrozenDetailPilotArtifactTest(unittest.TestCase):
    def test_actual_pilot_artifacts_pass_integrity_and_safety_gates(self) -> None:
        ledger = read_jsonl(FROZEN_LEDGER)
        previews = read_jsonl(FROZEN_PREVIEW)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        preview_by_url = {row["canonical_url"]: row for row in previews}

        self.assertEqual(file_sha256(FROZEN_LEDGER), FROZEN_LEDGER.stem.rsplit("_", 1)[-1])
        self.assertEqual(file_sha256(FROZEN_PREVIEW), FROZEN_PREVIEW.stem.rsplit("_", 1)[-1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[-1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[-1])
        self.assertEqual((len(ledger), len(previews)), (64, 64))
        self.assertEqual(manifest["raw_snapshot_count"], 60)
        self.assertTrue(all(set(LEDGER_REQUIRED_FIELDS).issubset(row) for row in ledger))
        self.assertTrue(all(set(PREVIEW_REQUIRED_FIELDS).issubset(row) for row in previews))
        self.assertTrue(all(row["fetch_status"] in ALLOWED_OUTCOMES for row in ledger))
        self.assertTrue(all(row["fetch_status"] == "success" for row in ledger))
        self.assertTrue(
            all(preview_by_url[row["canonical_url"]]["title"] for row in ledger)
        )
        self.assertTrue(
            all(preview_by_url[row["canonical_url"]]["extracted_text"] for row in ledger)
        )
        for row in ledger:
            raw_path = ROOT / row["raw_snapshot_path"]
            self.assertEqual(file_sha256(raw_path), row["content_hash"])
        faq_rows = [row for row in previews if row["source_id"] == "dnf_faq"]
        policy_rows = [row for row in previews if row["source_id"] == "dnf_account_policy"]
        self.assertEqual(len(faq_rows), 16)
        self.assertTrue(all(row["faq_locator_validated"] is True for row in faq_rows))
        self.assertEqual(len(policy_rows), 5)
        self.assertTrue(all(row["policy_revision_validated"] is True for row in policy_rows))
        restricted = [
            row
            for row in ledger
            if row["registry_status"] in {"expired", "superseded"}
            or row["source_kind"] == "preview_patch"
        ]
        self.assertTrue(restricted)
        self.assertTrue(all(not row["default_exposure"] for row in restricted))
        self.assertEqual(report["summary"]["success_rate"], 1.0)
        self.assertEqual(report["summary"]["raw_hash_mismatches"], 0)
        self.assertEqual(report["full_collection_decision"], "GO")


class FrozenFullDetailCollectionArtifactTest(unittest.TestCase):
    def test_actual_full_artifacts_pass_collection_and_safety_gates(self) -> None:
        ledger = read_jsonl(FROZEN_FULL_LEDGER)
        previews = read_jsonl(FROZEN_FULL_PREVIEW)
        manifest = json.loads(FROZEN_FULL_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_FULL_REPORT.read_text(encoding="utf-8"))

        for path in (
            FROZEN_FULL_LEDGER,
            FROZEN_FULL_PREVIEW,
            FROZEN_FULL_MANIFEST,
            FROZEN_FULL_REPORT,
        ):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[-1])
        self.assertEqual((len(ledger), len(previews)), (982, 982))
        self.assertEqual(manifest["raw_snapshot_count"], 719)
        self.assertTrue(all(row["eligible_for_collection"] for row in ledger))
        self.assertTrue(all(row["fetch_status"] == "success" for row in ledger))
        self.assertTrue(all(row["title"] for row in previews))
        self.assertTrue(all(row["extracted_text"] for row in previews))

        raw_by_path = {
            row["raw_snapshot_path"]: row["content_hash"]
            for row in ledger
            if row["raw_snapshot_path"]
        }
        self.assertEqual(len(raw_by_path), 719)
        for path_value, content_hash in raw_by_path.items():
            self.assertEqual(file_sha256(ROOT / path_value), content_hash)

        faq_rows = [row for row in previews if row["source_id"] == "dnf_faq"]
        policy_rows = [
            row for row in previews if row["source_id"] == "dnf_account_policy"
        ]
        self.assertEqual(len(faq_rows), 279)
        self.assertTrue(all(row["faq_locator_validated"] is True for row in faq_rows))
        self.assertEqual(len(policy_rows), 51)
        self.assertTrue(
            all(row["policy_revision_validated"] is True for row in policy_rows)
        )
        restricted = [
            row
            for row in ledger
            if row["registry_status"] in {"expired", "superseded"}
            or row["source_kind"] == "preview_patch"
        ]
        self.assertTrue(restricted)
        self.assertTrue(all(not row["default_exposure"] for row in restricted))
        self.assertEqual(report["summary"]["success_rate"], 1.0)
        self.assertEqual(report["summary"]["raw_hash_mismatches"], 0)
        self.assertEqual(report["raw_collection_decision"], "GO")
        self.assertEqual(report["next_stage_decision"], "GO")
        self.assertEqual(report["document_v3_promotion_decision"], "NO-GO")
        self.assertEqual(report["document_v3_blocking_warning_rows"], 136)


if __name__ == "__main__":
    unittest.main()
