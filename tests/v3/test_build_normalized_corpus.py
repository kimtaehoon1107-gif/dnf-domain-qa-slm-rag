from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256, stable_content_hash
from src.v3.build_normalized_corpus import build_normalized_corpus
from src.v3.schemas import (
    DOCUMENT_CONTENT_REQUIRED_FIELDS,
    NORMALIZED_DOCUMENT_REQUIRED_FIELDS,
    missing_required_fields,
)


BUILT_AT = "2026-07-17T23:50:00+09:00"
FROZEN_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
FROZEN_CONTENTS = Path(
    "data/v3/normalized/"
    "document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/normalized/"
    "normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "document_v3_promotion_bd6110d4201e8669ce096069bbdec6a4f0373ab2661bb9ae385dadb27b9093d4.json"
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _registry_row(
    url: str,
    *,
    source_id: str,
    source_kind: str,
    status: str,
    default_exposure: bool,
    listing_url: str | None = None,
    published_at: str | None = "2026-01-01",
) -> dict:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "listing_url": listing_url or url,
        "canonical_url": url,
        "canonical_url_kind": "official_url",
        "source_item_id": url.rsplit("/", 1)[-1],
        "title": "문서 제목",
        "category": "테스트",
        "discovered_at": BUILT_AT,
        "published_at": published_at,
        "period_start": published_at,
        "period_end": None,
        "page_number": 1,
        "eligible_for_collection": True,
        "eligibility_reason": "fixture",
        "status": status,
        "default_exposure": default_exposure,
        "is_pinned": False,
        "discovery_parser_version": "fixture-discovery",
    }


def _detail_rows(root: Path, registry: dict, *, text: str, eligible: bool = True) -> tuple[dict, dict]:
    content = f"<html><article>{text}</article></html>".encode("utf-8")
    content_hash = hashlib.sha256(content).hexdigest()
    raw_path = root / "raw" / f"{content_hash}.html"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(content)
    ledger = {
        "canonical_url": registry["canonical_url"],
        "canonical_url_kind": registry["canonical_url_kind"],
        "collector_version": "fixture-collector",
        "content_hash": content_hash,
        "default_exposure": registry["default_exposure"],
        "eligible_for_collection": True,
        "error": None,
        "fetch_status": "success",
        "fetch_url": registry["canonical_url"],
        "fetched_at": BUILT_AT,
        "final_url": registry["canonical_url"],
        "http_status": 200,
        "ledger_schema_version": "fixture-ledger",
        "pilot_bucket": "fixture",
        "raw_byte_count": len(content),
        "raw_snapshot_path": raw_path.as_posix(),
        "registry_category": registry["category"],
        "registry_sha256": "fixture",
        "registry_status": registry["status"],
        "registry_title": registry["title"],
        "retry_count": 0,
        "source_id": registry["source_id"],
        "source_kind": registry["source_kind"],
    }
    preview = {
        "canonical_url": registry["canonical_url"],
        "content_selector": "article",
        "content_status": "parsed" if eligible else "unavailable_redirect",
        "date_signals": [],
        "default_exposure": registry["default_exposure"],
        "eligible_for_collection": True,
        "error": None if eligible else "redirect",
        "extracted_text": text if eligible else "",
        "extraction_warnings": [],
        "faq_locator_validated": registry["source_id"] == "dnf_faq",
        "final_url": registry["canonical_url"],
        "guide_change_classification": None,
        "heading_count": 1,
        "image_count": 1 if registry["source_id"] == "dnf_faq" else 0,
        "image_dependency_reasons": [],
        "image_dependency_risk": "high" if registry["source_id"] == "dnf_faq" else "none",
        "navigation_residue_terms": [],
        "noise_nodes_removed": 0,
        "normalization_eligible": eligible and registry["source_id"] != "dnf_faq",
        "observed_updated_at": None,
        "parser_version": "fixture-parser",
        "policy_revision_validated": registry["source_id"] == "dnf_account_policy",
        "preview_schema_version": "fixture-preview",
        "previous_refresh_length_ratio": None,
        "price_signals": [],
        "published_at": registry["published_at"],
        "raw_content_hash": content_hash,
        "raw_snapshot_path": raw_path.as_posix(),
        "registry_category": registry["category"],
        "registry_status": registry["status"],
        "source_id": registry["source_id"],
        "source_kind": registry["source_kind"],
        "table_count": 0,
        "title": registry["title"],
        "title_source": "fixture",
        "title_validation_status": "matched",
        "valid_from": registry["period_start"],
        "valid_to": registry["period_end"],
    }
    return ledger, preview


def _build_kwargs(root: Path, *, registry: list[dict], ledger: list[dict], previews: list[dict], visual: list[dict], overlay: list[dict], baseline: list[dict]) -> dict:
    paths = {
        "registry_path": root / "registry.jsonl",
        "ledger_path": root / "ledger.jsonl",
        "hardened_preview_path": root / "previews.jsonl",
        "visual_evidence_path": root / "visual.jsonl",
        "correction_overlay_path": root / "overlay.jsonl",
        "visual_manifest_path": root / "visual_manifest.json",
        "baseline_documents_path": root / "baseline.jsonl",
    }
    _write_jsonl(paths["registry_path"], registry)
    _write_jsonl(paths["ledger_path"], ledger)
    _write_jsonl(paths["hardened_preview_path"], previews)
    _write_jsonl(paths["visual_evidence_path"], visual)
    _write_jsonl(paths["correction_overlay_path"], overlay)
    _write_json(paths["visual_manifest_path"], {"fixture": True})
    _write_jsonl(paths["baseline_documents_path"], baseline)
    return {
        "built_at": BUILT_AT,
        **paths,
        "normalized_dir": root / "normalized",
        "report_dir": root / "reports",
        "corpus_name": "fixture",
    }


class BuildNormalizedCorpusTest(unittest.TestCase):
    def test_joins_inputs_links_policy_revisions_and_keeps_ocr_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_listing = "https://example.test/policy?type=1"
            rows = [
                _registry_row(
                    "https://example.test/policy?revision=2025-01-01&type=1",
                    source_id="dnf_account_policy",
                    source_kind="account_policy",
                    status="superseded",
                    default_exposure=False,
                    listing_url=policy_listing,
                    published_at="2025-01-01",
                ),
                _registry_row(
                    policy_listing,
                    source_id="dnf_account_policy",
                    source_kind="account_policy",
                    status="current",
                    default_exposure=True,
                    listing_url=policy_listing,
                    published_at="2026-01-01",
                ),
                _registry_row(
                    "https://example.test/faq?faq_no=1",
                    source_id="dnf_faq",
                    source_kind="faq",
                    status="current",
                    default_exposure=True,
                ),
                _registry_row(
                    "https://example.test/pg/unavailable",
                    source_id="dnf_event",
                    source_kind="event",
                    status="current",
                    default_exposure=True,
                ),
            ]
            details = [
                _detail_rows(root, rows[0], text="과거 정책 본문"),
                _detail_rows(root, rows[1], text="현재 정책 본문"),
                _detail_rows(root, rows[2], text="FAQ DOM 본문"),
                _detail_rows(root, rows[3], text="", eligible=False),
            ]
            visual = [
                {
                    "canonical_url": rows[2]["canonical_url"],
                    "normalization_eligible_after_visual": True,
                    "ocr_text": "이미지 표의 월 한도는 300만원입니다",
                    "visual_version": "fixture-visual",
                    "visual_evidence_status": "resolved",
                    "asset_count": 1,
                    "asset_fetch_failed": 0,
                    "tolerated_css_404_asset_urls": [],
                }
            ]
            overlay = [
                {
                    "canonical_url": rows[3]["canonical_url"],
                    "normalization_eligible": False,
                    "correction_reason": "fixture_redirect",
                    "effective_status": "unavailable_redirect",
                    "effective_default_exposure": False,
                }
            ]
            kwargs = _build_kwargs(
                root,
                registry=rows,
                ledger=[item[0] for item in details],
                previews=[item[1] for item in details],
                visual=visual,
                overlay=overlay,
                baseline=[],
            )
            input_bytes = {
                path: path.read_bytes()
                for key, path in kwargs.items()
                if key.endswith("_path") and isinstance(path, Path)
            }

            first = build_normalized_corpus(**kwargs)
            second = build_normalized_corpus(**kwargs)
            documents = read_jsonl(Path(first["document_path"]))
            contents = read_jsonl(Path(first["content_path"]))

            self.assertEqual(first, second)
            self.assertEqual(first["promotion_decision"], "GO")
            self.assertEqual(len(documents), 3)
            self.assertEqual(len(contents), 3)
            self.assertTrue(
                all(not missing_required_fields(row, NORMALIZED_DOCUMENT_REQUIRED_FIELDS) for row in documents)
            )
            self.assertTrue(
                all(not missing_required_fields(row, DOCUMENT_CONTENT_REQUIRED_FIELDS) for row in contents)
            )
            policies = sorted(
                (row for row in documents if row["source_id"] == "dnf_account_policy"),
                key=lambda row: row["published_at"],
            )
            self.assertEqual(policies[0]["lineage_id"], policies[1]["lineage_id"])
            self.assertEqual(policies[0]["status"], "superseded")
            self.assertFalse(policies[0]["default_exposure"])
            self.assertEqual(policies[1]["supersedes_document_id"], policies[0]["document_id"])
            self.assertTrue(policies[1]["default_exposure"])
            faq_document = next(row for row in documents if row["source_id"] == "dnf_faq")
            faq_content = next(row for row in contents if row["document_id"] == faq_document["document_id"])
            self.assertEqual(faq_content["text"], "FAQ DOM 본문")
            self.assertNotIn(faq_content["visual_evidence"]["text"], faq_content["text"])
            self.assertTrue(faq_content["visual_evidence"]["unverified_ocr"])
            self.assertIn("visual_ocr_unverified_supplement", faq_content["extraction_warnings"])
            for path, content in input_bytes.items():
                self.assertEqual(path.read_bytes(), content)

    def test_preserves_material_guide_baseline_as_superseded_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            url = "https://example.test/guide?no=1535"
            registry = _registry_row(
                url,
                source_id="dnf_game_guide",
                source_kind="game_guide",
                status="current",
                default_exposure=True,
                listing_url="https://example.test/guide",
            )
            ledger, preview = _detail_rows(root, registry, text="공식 갱신 본문")
            preview["guide_change_classification"] = "official_revision_after_baseline"
            old_raw_row = {
                "source_type": "official",
                "doc_type": "game_guide",
                "title": "문서 제목",
                "published_at": None,
                "effective_start": None,
                "effective_end": None,
                "source_url": url,
                "tags": [],
                "text": "이전 기준선 본문",
                "metadata": {"collected_at": "2026-07-05T00:00:00"},
            }
            baseline_raw = root / "baseline_raw.jsonl"
            _write_jsonl(baseline_raw, [old_raw_row])
            old_content_hash = stable_content_hash(old_raw_row)
            old_identity = hashlib.sha256(f"{url}\n{old_content_hash}".encode("utf-8")).hexdigest()
            baseline = {
                "document_id": f"document_sha256_{old_identity}",
                "source_snapshot_id": f"snapshot_sha256_{file_sha256(baseline_raw)}",
                "canonical_url": url,
                "source_kind": "game_guide",
                "authority": "official",
                "title": "문서 제목",
                "category_path": ["guide", "테스트"],
                "published_at": None,
                "valid_from": None,
                "valid_to": None,
                "revision_id": f"revision_sha256_{old_identity}",
                "supersedes_document_id": None,
                "status": "current",
                "content_hash": old_content_hash,
                "fetched_at": "2026-07-05T00:00:00",
                "parser_version": "dnf_v2_raw_normalizer_v3.0",
                "raw_source_path": baseline_raw.as_posix(),
            }
            kwargs = _build_kwargs(
                root,
                registry=[registry],
                ledger=[ledger],
                previews=[preview],
                visual=[],
                overlay=[],
                baseline=[baseline],
            )

            result = build_normalized_corpus(**kwargs)
            documents = read_jsonl(Path(result["document_path"]))
            contents = read_jsonl(Path(result["content_path"]))

            self.assertEqual(len(documents), 2)
            old, new = sorted(documents, key=lambda row: row["fetched_at"])
            self.assertEqual(old["document_id"], baseline["document_id"])
            self.assertEqual(old["status"], "superseded")
            self.assertFalse(old["default_exposure"])
            self.assertEqual(new["supersedes_document_id"], old["document_id"])
            self.assertEqual(new["status"], "current")
            self.assertTrue(new["default_exposure"])
            old_content = next(row for row in contents if row["document_id"] == old["document_id"])
            self.assertEqual(old_content["text_source"], "legacy_v2_normalized_text")
            self.assertEqual(old_content["text"], "이전 기준선 본문")
            self.assertEqual(result["summary"]["preserved_baseline_revisions"], 1)


class FrozenNormalizedCorpusArtifactTest(unittest.TestCase):
    def test_actual_normalized_artifacts_pass_revision_and_safety_gates(self) -> None:
        documents = read_jsonl(FROZEN_DOCUMENTS)
        contents = read_jsonl(FROZEN_CONTENTS)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

        self.assertEqual(file_sha256(FROZEN_DOCUMENTS), FROZEN_DOCUMENTS.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_CONTENTS), FROZEN_CONTENTS.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[1])
        self.assertEqual((len(documents), len(contents)), (980, 980))
        self.assertEqual(
            {row["document_id"] for row in documents},
            {row["document_id"] for row in contents},
        )
        self.assertTrue(
            all(not missing_required_fields(row, NORMALIZED_DOCUMENT_REQUIRED_FIELDS) for row in documents)
        )
        self.assertTrue(
            all(not missing_required_fields(row, DOCUMENT_CONTENT_REQUIRED_FIELDS) for row in contents)
        )

        contents_by_id = {row["document_id"]: row for row in contents}
        raw_hashes: dict[str, str] = {}
        for document in documents:
            content = contents_by_id[document["document_id"]]
            self.assertEqual(document["normalized_text_hash"], content["text_hash"])
            self.assertEqual(
                content["text_hash"], hashlib.sha256(content["text"].encode("utf-8")).hexdigest()
            )
            path = document["raw_source_path"]
            raw_hashes.setdefault(path, file_sha256(Path(path)))
            self.assertEqual(raw_hashes[path], document["raw_content_hash"])
            if document["default_exposure"]:
                self.assertIn(document["status"], {"current", "upcoming"})
                self.assertNotIn(document["source_kind"], {"preview_patch", "roadmap_statement"})

        visual_contents = [row for row in contents if row["visual_evidence"] is not None]
        self.assertEqual(len(visual_contents), 18)
        self.assertTrue(all(row["visual_evidence"]["unverified_ocr"] for row in visual_contents))
        self.assertTrue(
            all("visual_ocr_unverified_supplement" in row["extraction_warnings"] for row in visual_contents)
        )

        policies = [row for row in documents if row["source_id"] == "dnf_account_policy"]
        self.assertEqual(len(policies), 51)
        self.assertEqual(len({row["lineage_id"] for row in policies}), 1)
        self.assertEqual(sum(row["supersedes_document_id"] is None for row in policies), 1)
        self.assertEqual(sum(row["status"] == "current" for row in policies), 1)
        guide = [row for row in documents if row["canonical_url"] == "https://df.nexon.com/guide?no=1535"]
        self.assertEqual(len(guide), 2)
        old, new = sorted(guide, key=lambda row: row["fetched_at"])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["supersedes_document_id"], old["document_id"])
        self.assertEqual(len(manifest["excluded_documents"]), 3)
        self.assertEqual(report["summary"]["candidate_documents"], 979)
        self.assertEqual(report["summary"]["default_exposure_documents"], 871)
        self.assertTrue(report["gates"]["visual_ocr_has_separate_unverified_provenance"])
        self.assertEqual(report["promotion_decision"], "GO")

    def test_actual_normalized_corpus_refreeze_is_reproducible(self) -> None:
        kwargs = {
            "built_at": BUILT_AT,
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
            "visual_evidence_path": Path(
                "data/v3/visual_evidence/"
                "visual_document_evidence_c7362de31d59ee1f0877477caa8c5d4848fdbdf40719b5c64cdb861c29469d38.jsonl"
            ),
            "correction_overlay_path": Path(
                "data/v3/visual_evidence/"
                "discovery_correction_overlay_0841fdad1f8c80dcda51036162b524ed4c7cf3cd31fb2bdb26a915cf77ddf61b.jsonl"
            ),
            "visual_manifest_path": Path(
                "data/v3/visual_evidence/"
                "visual_evidence_manifest_ff585eb897627edd9bceae3f643fe5ac23904a07fcbed7b5fbe51cb59e64050b.json"
            ),
            "baseline_documents_path": Path(
                "data/v3/normalized/documents_dnf_official_v3.0_c77299d729a6.jsonl"
            ),
            "normalized_dir": Path("data/v3/normalized"),
            "report_dir": Path("reports/v3"),
        }

        first = build_normalized_corpus(**kwargs)
        second = build_normalized_corpus(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["document_sha256"], file_sha256(FROZEN_DOCUMENTS))
        self.assertEqual(first["content_sha256"], file_sha256(FROZEN_CONTENTS))
        refreshed_manifest = json.loads(Path(first["manifest_path"]).read_text(encoding="utf-8"))
        refreshed_report = json.loads(Path(first["report_json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(refreshed_manifest["builder_version"], "dnf_normalized_corpus_builder_v3.2")
        self.assertTrue(all(value is True or value == 0 for value in refreshed_report["gates"].values()))
        self.assertEqual(first["promotion_decision"], "GO")


if __name__ == "__main__":
    unittest.main()
