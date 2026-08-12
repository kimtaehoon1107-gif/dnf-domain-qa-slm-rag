from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import write_immutable
from src.v3.collect_visual_evidence import (
    ASSET_SCHEMA_VERSION,
    VISUAL_VERSION,
    apply_ocr_results,
    build_correction_overlay,
    build_document_evidence,
    discover_initial_asset_refs,
    expand_stylesheet_refs,
    finalize_visual_evidence_from_ledger,
    freeze_visual_artifacts,
)


FETCHED_AT = "2026-07-17T23:30:00+09:00"
FROZEN_FETCHED_AT = "2026-07-17T23:28:32.5730462+09:00"
FROZEN_ASSET_LEDGER = Path(
    "data/v3/visual_evidence/"
    "visual_asset_ledger_9b871e8ed168bb155c183165713c944afbed09e72b68c8ea4a633541bcc82df8.jsonl"
)
FROZEN_REUSED_ASSET_LEDGER = Path(
    "data/v3/visual_evidence/"
    "visual_asset_ledger_bcb1ee45aecc1dbfa6c3fe454238866371ad25aa35e455eb6cfdf5b1157aefbd.jsonl"
)
FROZEN_EVIDENCE = Path(
    "data/v3/visual_evidence/"
    "visual_document_evidence_c7362de31d59ee1f0877477caa8c5d4848fdbdf40719b5c64cdb861c29469d38.jsonl"
)
FROZEN_OVERLAY = Path(
    "data/v3/visual_evidence/"
    "discovery_correction_overlay_0841fdad1f8c80dcda51036162b524ed4c7cf3cd31fb2bdb26a915cf77ddf61b.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/visual_evidence/"
    "visual_evidence_manifest_ff585eb897627edd9bceae3f643fe5ac23904a07fcbed7b5fbe51cb59e64050b.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "visual_evidence_pilot_e40f7acd38a3848e6da2c0637f6ebe4ee76dff553ab2ef8f73b5c97e3c209873.json"
)


def _document() -> dict:
    return {
        "canonical_url": "https://example.test/pg/event",
        "source_id": "dnf_event",
        "title": "이미지 이벤트",
        "default_exposure": True,
        "image_dependency_risk": "high",
    }


def _registry() -> dict:
    return {
        "canonical_url": "https://example.test/pg/event",
        "source_id": "dnf_event",
        "source_kind": "event",
        "source_item_id": "event",
        "title": "이미지 이벤트",
        "status": "current",
        "eligible_for_collection": True,
        "default_exposure": True,
    }


def _asset_row(path: Path) -> dict:
    content_hash = file_sha256(path)
    return {
        "asset_schema_version": ASSET_SCHEMA_VERSION,
        "visual_version": VISUAL_VERSION,
        "document_url": "https://example.test/pg/event",
        "source_id": "dnf_event",
        "asset_url": "https://cdn.example.test/reward.png",
        "asset_kind": "image",
        "discovery_kinds": ["content_img"],
        "parent_stylesheet_urls": [],
        "fetch_status": "success",
        "http_status": 200,
        "fetched_at": FETCHED_AT,
        "final_url": "https://cdn.example.test/reward.png",
        "media_type": "image/png",
        "content_hash": content_hash,
        "snapshot_path": path.as_posix(),
        "byte_count": path.stat().st_size,
        "retry_count": 0,
        "image_width": None,
        "image_height": None,
        "image_frame_count": None,
        "ocr_status": "pending",
        "ocr_engine": "Windows.Media.Ocr",
        "ocr_language": "ko",
        "ocr_scale": None,
        "ocr_text": "",
        "ocr_char_count": 0,
        "ocr_signal_char_count": 0,
        "ocr_hangul_char_count": 0,
        "error": None,
    }


class CollectVisualEvidenceTest(unittest.TestCase):
    def test_discovers_content_images_inline_css_and_page_stylesheet(self) -> None:
        row = _registry()
        ledger = {"final_url": row["canonical_url"]}
        html = b"""
        <html><head><style>.hero{background:url('/img/hero.png')}</style>
        <link rel="stylesheet" href="https://bbscdn.df.nexon.com/pg/event/event.css" />
        <link rel="stylesheet" href="https://resource.df.nexon.com/ui/css/event.css" />
        </head><body><div id="wrap"><div class="evt_ing_wrap"><img src="/noise.png" /></div>
        <section><img src="/img/reward.png" /><div style="background:url('/img/item.jpg')"></div></section>
        </div></body></html>
        """

        refs = discover_initial_asset_refs(row, ledger, html)
        urls = {ref["asset_url"] for ref in refs}

        self.assertIn("https://example.test/img/reward.png", urls)
        self.assertIn("https://example.test/img/item.jpg", urls)
        self.assertIn("https://example.test/img/hero.png", urls)
        self.assertIn("https://bbscdn.df.nexon.com/pg/event/event.css", urls)
        self.assertNotIn("https://example.test/noise.png", urls)
        self.assertNotIn("https://resource.df.nexon.com/ui/css/event.css", urls)

    def test_expands_only_image_urls_from_stylesheet(self) -> None:
        refs = expand_stylesheet_refs(
            "https://cdn.example.test/css/event.css",
            b".a{background:url('../img/a.png')} @font-face{src:url('../font/a.woff2')}",
        )

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["asset_url"], "https://cdn.example.test/img/a.png")
        self.assertEqual(refs[0]["parent_stylesheet_urls"], ["https://cdn.example.test/css/event.css"])

    def test_prepares_image_and_applies_injected_ocr_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.png"
            Image.new("RGB", (3200, 800), "white").save(path)
            row = _asset_row(path)

            def fake_runner(requests: dict[str, str], _script: Path) -> dict[str, dict]:
                self.assertEqual(len(requests), 1)
                return {
                    next(iter(requests)): {
                        "status": "success",
                        "text": "이벤트 보상은 계정당 한 번 받을 수 있습니다. 참여 기간은 7월 31일까지입니다.",
                        "error": None,
                    }
                }

            apply_ocr_results([row], ocr_script_path=Path("fixture.ps1"), ocr_runner=fake_runner)

            self.assertEqual(row["ocr_status"], "success")
            self.assertEqual((row["image_width"], row["image_height"]), (3200, 800))
            self.assertLess(row["ocr_scale"], 1.0)
            self.assertGreater(row["ocr_hangul_char_count"], 10)

    def test_document_resolution_requires_complete_meaningful_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.png"
            Image.new("RGB", (100, 100), "white").save(path)
            row = _asset_row(path)
            row.update(
                ocr_status="success",
                ocr_text=(
                    "이벤트 보상은 계정당 한 번 받을 수 있습니다. 참여 기간은 7월 31일까지입니다. "
                    "보상 수령은 이벤트 페이지의 받기 버튼을 이용해 주세요."
                ),
                ocr_char_count=75,
                ocr_signal_char_count=65,
                ocr_hangul_char_count=50,
            )

            evidence = build_document_evidence([_document()], [row])

            self.assertEqual(evidence[0]["visual_evidence_status"], "resolved")
            self.assertTrue(evidence[0]["normalization_eligible_after_visual"])

    def test_compact_numeric_table_ocr_is_meaningful(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.png"
            Image.new("RGB", (100, 100), "white").save(path)
            row = _asset_row(path)
            row.update(
                ocr_status="success",
                ocr_text="전환 한도 구분 청소년은 월 7만원 성인은 월 300만원으로 적용됩니다",
                ocr_char_count=30,
                ocr_signal_char_count=30,
                ocr_hangul_char_count=18,
            )

            evidence = build_document_evidence([_document()], [row])

            self.assertEqual(evidence[0]["visual_evidence_status"], "resolved")
            self.assertTrue(evidence[0]["meaningful_ocr"])

    def test_tolerates_only_css_404_when_other_visual_evidence_is_meaningful(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.png"
            Image.new("RGB", (100, 100), "white").save(path)
            content = _asset_row(path)
            content.update(
                ocr_status="success",
                ocr_text=(
                    "이벤트 기간은 7월 17일부터 8월 6일까지이며 미션 보상은 계정당 한 번 지급됩니다."
                ),
                ocr_char_count=50,
                ocr_signal_char_count=45,
                ocr_hangul_char_count=35,
            )
            stale_css = dict(content)
            stale_css.update(
                asset_url="https://cdn.example.test/old-tooltip.png",
                discovery_kinds=["inline_stylesheet_url"],
                fetch_status="failed",
                http_status=404,
                content_hash=None,
                snapshot_path=None,
                byte_count=0,
                ocr_status="not_run_fetch_failed",
                ocr_text="",
            )

            evidence = build_document_evidence([_document()], [content, stale_css])

            self.assertEqual(
                evidence[0]["visual_evidence_status"],
                "resolved_with_tolerated_css_404",
            )
            self.assertTrue(evidence[0]["normalization_eligible_after_visual"])
            self.assertEqual(
                evidence[0]["tolerated_css_404_asset_urls"],
                ["https://cdn.example.test/old-tooltip.png"],
            )

            stale_css["discovery_kinds"] = ["content_img"]
            evidence = build_document_evidence([_document()], [content, stale_css])
            self.assertEqual(evidence[0]["visual_evidence_status"], "partial")
            self.assertFalse(evidence[0]["normalization_eligible_after_visual"])

    def test_correction_overlay_disables_redirected_default_exposure(self) -> None:
        preview = {
            "canonical_url": "https://example.test/pg/old",
            "source_id": "dnf_event",
            "content_status": "unavailable_redirect",
        }
        registry = {
            preview["canonical_url"]: {
                "status": "current",
                "eligible_for_collection": True,
                "default_exposure": True,
            }
        }
        ledger = {
            preview["canonical_url"]: {
                "final_url": "https://example.test/",
                "content_hash": "abc",
            }
        }

        overlay = build_correction_overlay(
            [preview], registry, ledger, observed_at=FETCHED_AT
        )

        self.assertEqual(len(overlay), 1)
        self.assertFalse(overlay[0]["effective_default_exposure"])
        self.assertFalse(overlay[0]["normalization_eligible"])

    def test_freeze_is_content_addressed_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "asset.png"
            Image.new("RGB", (100, 100), "white").save(image_path)
            row = _asset_row(image_path)
            row.update(
                ocr_status="success",
                ocr_text=(
                    "이벤트 보상은 계정당 한 번 받을 수 있습니다. 참여 기간은 7월 31일까지입니다. "
                    "보상 수령은 이벤트 페이지의 받기 버튼을 이용해 주세요."
                ),
                ocr_char_count=75,
                ocr_signal_char_count=65,
                ocr_hangul_char_count=50,
            )
            evidence = build_document_evidence([_document()], [row])
            overlay = [
                {
                    "overlay_schema_version": "fixture",
                    "visual_version": VISUAL_VERSION,
                    "canonical_url": "https://example.test/pg/old",
                    "source_id": "dnf_event",
                    "observed_at": FETCHED_AT,
                    "observed_final_url": "https://example.test/",
                    "evidence_content_hash": "abc",
                    "original_status": "current",
                    "original_eligible_for_collection": True,
                    "original_default_exposure": True,
                    "effective_status": "unavailable_redirect",
                    "effective_eligible_for_collection": False,
                    "effective_default_exposure": False,
                    "normalization_eligible": False,
                    "correction_reason": "fixture",
                }
            ]
            input_paths = []
            for name in ("registry.jsonl", "ledger.jsonl", "preview.jsonl", "manifest.json"):
                path = root / name
                write_immutable(path, b"{}\n")
                input_paths.append(path)
            kwargs = {
                "asset_rows": [row],
                "evidence": evidence,
                "overlay": overlay,
                "fetched_at": FETCHED_AT,
                "registry_path": input_paths[0],
                "ledger_path": input_paths[1],
                "hardened_preview_path": input_paths[2],
                "hardening_manifest_path": input_paths[3],
                "normalization_candidates_before_visual": 7,
                "evidence_dir": root / "evidence",
                "report_dir": root / "reports",
            }

            first = freeze_visual_artifacts(**kwargs)
            second = freeze_visual_artifacts(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["visual_evidence_decision"], "GO")
            self.assertEqual(first["document_v3_promotion_decision"], "GO")
            self.assertEqual(first["summary"]["normalization_candidates_after_visual"], 8)
            self.assertEqual(file_sha256(Path(first["manifest_path"])), first["manifest_sha256"])


class FrozenVisualEvidenceArtifactTest(unittest.TestCase):
    def test_actual_visual_artifacts_pass_integrity_and_promotion_gates(self) -> None:
        asset_rows = read_jsonl(FROZEN_ASSET_LEDGER)
        evidence = read_jsonl(FROZEN_EVIDENCE)
        overlay = read_jsonl(FROZEN_OVERLAY)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

        self.assertEqual(file_sha256(FROZEN_ASSET_LEDGER), FROZEN_ASSET_LEDGER.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_EVIDENCE), FROZEN_EVIDENCE.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_OVERLAY), FROZEN_OVERLAY.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[1])
        self.assertEqual((len(asset_rows), len(evidence), len(overlay)), (180, 18, 3))
        self.assertTrue(all(row["normalization_eligible_after_visual"] for row in evidence))
        failed = [row for row in asset_rows if row["fetch_status"] != "success"]
        self.assertEqual(len(failed), 3)
        self.assertTrue(all(row["http_status"] == 404 for row in failed))
        self.assertTrue(
            all(set(row["discovery_kinds"]) <= {"inline_stylesheet_url", "external_stylesheet_url"} for row in failed)
        )
        for row in asset_rows:
            if row.get("snapshot_path"):
                self.assertEqual(file_sha256(Path(row["snapshot_path"])), row["content_hash"])
        self.assertEqual(sum(row["original_default_exposure"] for row in overlay), 1)
        self.assertEqual(manifest["snapshot_count"], 166)
        self.assertEqual(report["summary"]["ocr_engine_failed"], 0)
        self.assertEqual(report["summary"]["unresolved_default_documents"], 0)
        self.assertEqual(report["visual_evidence_decision"], "GO")
        self.assertEqual(report["document_v3_promotion_decision"], "GO")

    def test_actual_visual_ledger_refreeze_is_reproducible_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kwargs = {
                "fetched_at": FROZEN_FETCHED_AT,
                "reused_asset_ledger_path": FROZEN_REUSED_ASSET_LEDGER,
                "registry_path": Path(
                    "data/v3/discovery/"
                    "source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
                ),
                "ledger_path": Path(
                    "data/v3/collections/"
                    "detail_full_collection_ledger_0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b.jsonl"
                ),
                "hardened_preview_path": Path(
                    "data/v3/collections/"
                    "detail_hardened_extraction_preview_ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8.jsonl"
                ),
                "hardening_manifest_path": Path(
                    "data/v3/collections/"
                    "detail_parser_hardening_manifest_ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29.json"
                ),
                "evidence_dir": root / "evidence",
                "report_dir": root / "reports",
            }

            first = finalize_visual_evidence_from_ledger(**kwargs)
            second = finalize_visual_evidence_from_ledger(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["asset_ledger_sha256"], file_sha256(FROZEN_ASSET_LEDGER))
            self.assertEqual(first["document_evidence_sha256"], file_sha256(FROZEN_EVIDENCE))
            self.assertEqual(first["correction_overlay_sha256"], file_sha256(FROZEN_OVERLAY))
            self.assertEqual(first["visual_evidence_decision"], "GO")
            self.assertEqual(first["document_v3_promotion_decision"], "GO")


if __name__ == "__main__":
    unittest.main()
