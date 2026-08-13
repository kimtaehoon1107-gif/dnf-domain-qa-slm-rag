from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import write_immutable
from src.v3.harden_detail_parsers import (
    PARSER_VERSION,
    classify_guide_change,
    classify_image_dependency,
    classify_title,
    extract_hardened_preview,
    freeze_hardening_artifacts,
    harden_detail_parsers,
    select_hardened_content,
    structured_text_hardened,
)


PARSED_AT = "2026-07-17T23:00:00+09:00"
ROOT = Path(__file__).resolve().parents[2]
FROZEN_PREVIEW = ROOT / "data/v3/collections/detail_hardened_extraction_preview_ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8.jsonl"
FROZEN_MANIFEST = ROOT / "data/v3/collections/detail_parser_hardening_manifest_ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29.json"
FROZEN_REPORT = ROOT / "reports/v3/detail_parser_hardening_cd65971ef73d7adbd3221a9dafcac483db3cfd2e845523f8274888a3cce25e1a.json"
FROZEN_PARSED_AT = "2026-07-17T22:29:29.7534422+09:00"


def _registry_row() -> dict:
    return {
        "source_id": "dnf_event",
        "source_kind": "event",
        "listing_url": "https://example.test/events",
        "canonical_url": "https://example.test/pg/event1",
        "canonical_url_kind": "official_url",
        "source_item_id": "event1",
        "title": "공식 이벤트",
        "category": "event",
        "discovered_at": PARSED_AT,
        "published_at": "2026-07-01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "page_number": 1,
        "eligible_for_collection": True,
        "eligibility_reason": "fixture",
        "status": "current",
        "default_exposure": True,
        "is_pinned": False,
        "discovery_parser_version": "fixture",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    content = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for row in rows
    )
    write_immutable(path, content)


class HardenDetailParsersTest(unittest.TestCase):
    def test_custom_event_selector_removes_site_chrome_and_preserves_alt_and_notice(self) -> None:
        row = _registry_row()
        ledger = {"final_url": row["canonical_url"]}
        html = """
        <div id="wrap">
          <div class="evt_ing_wrap">회사소개 채용안내 이용약관 개인정보처리방침</div>
          <section class="event"><h1>공식 이벤트</h1><img alt="핵심 보상" />
          <p>이벤트 참여 방법과 보상에 대한 공식 설명입니다.</p></section>
          <div class="noti">이벤트 기간은 7월 31일까지입니다.</div>
          <div id="commonFooterArea">회사소개 개인정보처리방침</div>
        </div>
        """.encode("utf-8")

        node, selector, status, _, _ = select_hardened_content(row, ledger, html)
        self.assertEqual((selector, status), ("#wrap:event_custom", "parsed"))
        self.assertIsNotNone(node)
        text, headings, tables, images, removed, navigation = structured_text_hardened(node)

        self.assertIn("공식 이벤트", text)
        self.assertIn("[IMAGE_ALT] 핵심 보상", text)
        self.assertIn("7월 31일까지", text)
        self.assertNotIn("회사소개", text)
        self.assertEqual((headings, tables, images), (1, 0, 1))
        self.assertGreaterEqual(removed, 2)
        self.assertEqual(navigation, [])

    def test_event_redirect_is_unavailable_instead_of_body_fallback(self) -> None:
        row = _registry_row()
        ledger = {"final_url": "https://example.test/"}

        node, selector, status, _, _ = select_hardened_content(
            row, ledger, b"<html><body>homepage</body></html>"
        )

        self.assertIsNone(node)
        self.assertEqual(selector, "redirected_off_canonical_path")
        self.assertEqual(status, "unavailable_redirect")

    def test_title_rules_distinguish_revision_and_registry_authority(self) -> None:
        policy = _registry_row()
        policy.update(
            source_id="dnf_account_policy",
            source_item_id="2026-07-01",
            title="던전앤파이터 운영정책 (2026-07-01 시행)",
        )
        guide = _registry_row()
        guide.update(source_id="dnf_game_guide", title="공식 가이드 제목")

        self.assertEqual(
            classify_title(policy, "운영정책 본문", content_status="parsed"),
            "policy_revision_title_validated",
        )
        self.assertEqual(
            classify_title(guide, "본문에는 제목이 없음", content_status="parsed"),
            "official_guide_registry_title",
        )

    def test_policy_terms_are_not_misclassified_as_navigation_residue(self) -> None:
        row = _registry_row()
        row.update(
            source_id="dnf_account_policy",
            source_kind="account_policy",
            source_item_id="2026-07-01",
            canonical_url="https://example.test/policy?revision=2026-07-01",
            title="던전앤파이터 운영정책 (2026-07-01 시행)",
        )
        ledger = {
            "final_url": row["canonical_url"],
            "raw_snapshot_path": "fixture.html",
            "content_hash": "fixture",
        }
        previous = {
            "source_id": row["source_id"],
            "refresh_length_ratio": None,
        }
        html = """
        <select id="revisionList"><option value="2026-07-01" selected>current</option></select>
        <section class="content"><p>Policy content references terms.</p>
        <p>이용약관 개인정보처리방침 고객센터 관련 운영 기준을 설명합니다.</p></section>
        """.encode("utf-8")

        preview = extract_hardened_preview(row, ledger, previous, html, None)

        self.assertEqual(preview["content_status"], "parsed")
        self.assertTrue(preview["policy_revision_validated"])
        self.assertNotIn("navigation_or_footer_residue", preview["extraction_warnings"])

    def test_guide_material_change_is_classified_as_later_official_revision(self) -> None:
        previous = {"source_id": "dnf_game_guide", "refresh_length_ratio": 1.578164}
        baseline = {"metadata": {"collected_at": "2026-07-05T21:42:43"}}

        classification, updated_at = classify_guide_change(
            previous,
            baseline,
            "본문 이 문서는 2026-07-16에 업데이트 되었습니다.",
        )

        self.assertEqual(classification, "official_revision_after_baseline")
        self.assertEqual(updated_at, "2026-07-16")

    def test_image_dependency_flags_short_custom_and_commerce_pages(self) -> None:
        custom_risk, custom_reasons = classify_image_dependency(
            source_id="dnf_event",
            selector="#wrap:event_custom",
            text="짧은 본문",
            image_count=0,
            table_count=0,
            price_signals=[],
        )
        shop_risk, shop_reasons = classify_image_dependency(
            source_id="dnf_seria_shop",
            selector="section.content.news",
            text="상품 설명" * 100,
            image_count=1,
            table_count=0,
            price_signals=[],
        )

        self.assertEqual(custom_risk, "high")
        self.assertIn("custom_event_short_dom_text_or_css_assets", custom_reasons)
        self.assertEqual(shop_risk, "high")
        self.assertIn("commerce_page_image_without_price_signal", shop_reasons)

        notice_risk, notice_reasons = classify_image_dependency(
            source_id="dnf_notice",
            selector="section.content.news",
            text="충분한 공식 안내 본문 " * 100,
            image_count=30,
            table_count=0,
            price_signals=[],
        )
        self.assertEqual(notice_risk, "medium")
        self.assertIn("many_images_relative_to_dom_text", notice_reasons)

    def test_full_hardening_freeze_is_reproducible_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            row = _registry_row()
            body = (
                "공식 이벤트 참여 방법, 기간, 보상, 유의사항을 설명하는 충분한 본문입니다. "
                * 12
            )
            raw = (
                f'<div id="wrap"><div class="evt_ing_wrap">다른 이벤트</div>'
                f'<section><h1>{row["title"]}</h1><img alt="보상"/><p>{body}</p></section>'
                '<div class="noti">계정당 1회 참여 가능합니다.</div></div>'
            ).encode("utf-8")
            raw_path = root / "raw.html"
            write_immutable(raw_path, raw)
            ledger = {
                "source_id": row["source_id"],
                "source_kind": row["source_kind"],
                "canonical_url": row["canonical_url"],
                "final_url": row["canonical_url"],
                "raw_snapshot_path": raw_path.as_posix(),
                "content_hash": file_sha256(raw_path),
            }
            previous = {
                "canonical_url": row["canonical_url"],
                "source_id": row["source_id"],
                "refresh_length_ratio": None,
            }
            registry_path = root / "registry.jsonl"
            ledger_path = root / "ledger.jsonl"
            previous_path = root / "previous.jsonl"
            guide_path = root / "guide.jsonl"
            collection_manifest_path = root / "collection_manifest.json"
            _write_jsonl(registry_path, [row])
            _write_jsonl(ledger_path, [ledger])
            _write_jsonl(previous_path, [previous])
            write_immutable(guide_path, b"")
            write_immutable(collection_manifest_path, b"{}\n")
            kwargs = {
                "parsed_at": PARSED_AT,
                "registry_path": registry_path,
                "ledger_path": ledger_path,
                "previous_preview_path": previous_path,
                "collection_manifest_path": collection_manifest_path,
                "guide_baseline_path": guide_path,
                "collection_dir": root / "collections",
                "report_dir": root / "reports",
            }

            first = harden_detail_parsers(**kwargs)
            second = harden_detail_parsers(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["parser_hardening_decision"], "GO")
            self.assertEqual(first["document_v3_promotion_decision"], "GO")
            self.assertEqual(file_sha256(Path(first["preview_path"])), first["preview_sha256"])
            preview = read_jsonl(Path(first["preview_path"]))[0]
            self.assertEqual(preview["parser_version"], PARSER_VERSION)
            self.assertEqual(preview["content_status"], "parsed")
            self.assertNotIn("다른 이벤트", preview["extracted_text"])


class FrozenHardenedParserArtifactTest(unittest.TestCase):
    def test_actual_hardened_artifacts_match_recorded_sha(self) -> None:
        previews = read_jsonl(FROZEN_PREVIEW)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

        for path in (FROZEN_PREVIEW, FROZEN_MANIFEST, FROZEN_REPORT):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[-1])
        self.assertEqual(len(previews), 982)
        self.assertEqual(manifest["raw_snapshot_count"], 719)
        self.assertEqual(report["summary"]["parsed"], 979)
        self.assertEqual(report["summary"]["unavailable_redirect"], 3)
        self.assertEqual(report["summary"]["parser_failed"], 0)
        self.assertEqual(report["summary"]["normalization_candidates"], 961)
        self.assertEqual(report["summary"]["body_fallback"], 0)
        self.assertEqual(report["summary"]["navigation_or_footer_residue"], 0)
        self.assertEqual(report["summary"]["unresolved_title_mismatch"], 0)
        self.assertEqual(report["summary"]["faq_resolution_errors"], 0)
        self.assertEqual(report["summary"]["policy_revision_errors"], 0)
        self.assertEqual(report["summary"]["raw_hash_mismatches"], 0)
        self.assertEqual(report["summary"]["default_exposed_unavailable"], 1)
        self.assertEqual(report["summary"]["default_exposed_high_image_risk"], 18)
        self.assertEqual(report["parser_hardening_decision"], "GO")
        self.assertEqual(report["document_v3_promotion_decision"], "NO-GO")

        faq = [row for row in previews if row["source_id"] == "dnf_faq"]
        policies = [
            row for row in previews if row["source_id"] == "dnf_account_policy"
        ]
        self.assertTrue(all(row["faq_locator_validated"] is True for row in faq))
        self.assertTrue(
            all(row["policy_revision_validated"] is True for row in policies)
        )
        guide_change = next(
            row
            for row in previews
            if row["canonical_url"] == "https://df.nexon.com/guide?no=1535"
        )
        self.assertEqual(
            guide_change["guide_change_classification"],
            "official_revision_after_baseline",
        )
        self.assertEqual(guide_change["observed_updated_at"], "2026-07-16")



def test_hardened_parser_generator_is_reproducible(tmp_path: Path) -> None:
    previews = read_jsonl(FROZEN_PREVIEW)
    manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
    kwargs = {
        "previews": previews,
        "parsed_at": FROZEN_PARSED_AT,
        "registry_path": Path(manifest["registry_path"]),
        "ledger_path": Path(manifest["ledger_path"]),
        "previous_preview_path": Path(manifest["previous_preview_path"]),
        "collection_manifest_path": Path(manifest["collection_manifest_path"]),
        "guide_baseline_path": Path(manifest["guide_baseline_path"]),
        "collection_dir": tmp_path / "data/v3/collections",
        "report_dir": tmp_path / "reports/v3",
    }

    first = freeze_hardening_artifacts(**kwargs)
    second = freeze_hardening_artifacts(**kwargs)

    assert first == second


if __name__ == "__main__":
    unittest.main()
