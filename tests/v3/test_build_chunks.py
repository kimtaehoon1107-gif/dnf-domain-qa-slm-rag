from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_chunk_pilot import build_chunks_for_selection
from src.v3.build_chunk_pilot import SOURCE_CONFIG
from src.v3.build_chunks import (
    CHUNKER_VERSION,
    audit_chunk_corpus,
    build_chunk_corpus,
)
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _serialize_jsonl
from src.v3.schemas import NORMALIZED_CHUNK_REQUIRED_FIELDS, missing_required_fields


BUILT_AT = "2026-07-18T01:30:00+09:00"
CANONICAL_BUILT_AT = "2026-07-18T01:10:47+09:00"
DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
CONTENTS = Path(
    "data/v3/normalized/"
    "document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl"
)
NORMALIZED_MANIFEST = Path(
    "data/v3/normalized/"
    "normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json"
)
PILOT_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_pilot_manifest_ba5e1d5a9b8a237df9a99e5fb698bbb8e0a4b6dc1668b3cabece9e971e0154e6.json"
)
FROZEN_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "chunk_corpus_audit_6526c24d365bff8433079ecd551afda35f9e56bc561cc04da56198fbd1a6a7c9.json"
)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _document(document_id: str, *, status: str, default_exposure: bool) -> dict:
    return {
        "document_id": document_id,
        "source_id": "dnf_notice",
        "source_kind": "general_notice",
        "status": status,
        "default_exposure": default_exposure,
        "title": f"문서 {document_id}",
        "valid_from": None,
        "valid_to": None,
        "content_hash": _hash_text(f"content:{document_id}"),
    }


def _content(document_id: str, text: str, visual_text: str | None = None) -> dict:
    visual = None
    if visual_text is not None:
        visual = {"text": visual_text, "text_hash": _hash_text(visual_text)}
    return {
        "document_id": document_id,
        "text": text,
        "text_hash": _hash_text(text),
        "visual_evidence": visual,
    }


class BuildChunkCorpusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = [
            _document("document_a", status="current", default_exposure=True),
            _document("document_b", status="expired", default_exposure=False),
        ]
        self.contents = [
            _content("document_a", "## 공지\n본문 내용입니다."),
            _content("document_b", "## 종료 공지\n종료된 내용입니다.", "이미지 가격 1,000 세라"),
        ]

    def test_fixture_build_is_content_addressed_reproducible_and_go(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            documents_path = root / "documents.jsonl"
            contents_path = root / "contents.jsonl"
            normalized_manifest_path = root / "normalized_manifest.json"
            pilot_manifest_path = root / "pilot_manifest.json"
            documents_path.write_bytes(
                _serialize_jsonl(self.documents, lambda row: row["document_id"])
            )
            contents_path.write_bytes(
                _serialize_jsonl(self.contents, lambda row: row["document_id"])
            )
            normalized_manifest_path.write_text(
                json.dumps({"documents": {"row_count": 2}}) + "\n",
                encoding="utf-8",
            )
            pilot_manifest_path.write_text("{}\n", encoding="utf-8")
            input_hashes = {
                path: file_sha256(path)
                for path in (
                    documents_path,
                    contents_path,
                    normalized_manifest_path,
                    pilot_manifest_path,
                )
            }
            kwargs = {
                "built_at": BUILT_AT,
                "documents_path": documents_path,
                "contents_path": contents_path,
                "normalized_manifest_path": normalized_manifest_path,
                "pilot_manifest_path": pilot_manifest_path,
                "chunk_dir": root / "chunks",
                "report_dir": root / "reports",
                "expected_source_ids": {"dnf_notice"},
            }

            first = build_chunk_corpus(**kwargs)
            second = build_chunk_corpus(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["indexing_decision"], "GO")
            self.assertEqual(file_sha256(Path(first["chunk_path"])), first["chunk_sha256"])
            self.assertEqual(file_sha256(Path(first["manifest_path"])), first["manifest_sha256"])
            self.assertEqual(file_sha256(Path(first["report_json_path"])), first["report_sha256"])
            report = json.loads(Path(first["report_json_path"]).read_text(encoding="utf-8"))
            self.assertTrue(all(value is True or value == 0 for value in report["gates"].values()))
            self.assertEqual(report["summary"]["documents"], 2)
            self.assertEqual(report["summary"]["visual_evidence_documents"], 1)
            for path, digest in input_hashes.items():
                self.assertEqual(file_sha256(path), digest)

    def test_audit_rejects_offset_hash_and_visual_exposure_corruption(self) -> None:
        documents_by_id = {row["document_id"]: row for row in self.documents}
        contents_by_id = {row["document_id"]: row for row in self.contents}
        chunks = build_chunks_for_selection(
            [{"document_id": row["document_id"]} for row in self.documents],
            documents_by_id,
            contents_by_id,
            chunker_version=CHUNKER_VERSION,
        )
        corrupted = copy.deepcopy(chunks)
        corrupted[0]["display_text"] += "변조"
        visual = next(row for row in corrupted if row["offset_source"] == "visual_ocr")
        visual["default_exposure"] = True

        audit = audit_chunk_corpus(
            self.documents,
            self.contents,
            corrupted,
            expected_document_count=2,
            expected_source_ids={"dnf_notice"},
        )

        self.assertEqual(audit["indexing_decision"], "NO-GO")
        self.assertGreater(audit["gates"]["offset_mismatches"], 0)
        self.assertGreater(audit["gates"]["chunk_id_mismatches"], 0)
        self.assertGreater(audit["gates"]["parent_default_exposure_mismatches"], 0)


class FrozenChunkCorpusArtifactTest(unittest.TestCase):
    def test_actual_full_chunk_artifacts_pass_hash_coverage_and_safety_gates(self) -> None:
        documents = read_jsonl(DOCUMENTS)
        contents = read_jsonl(CONTENTS)
        chunks = read_jsonl(FROZEN_CHUNKS)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

        self.assertEqual(file_sha256(FROZEN_CHUNKS), FROZEN_CHUNKS.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[1])
        self.assertEqual(len(documents), 980)
        self.assertEqual(len(contents), 980)
        self.assertEqual(len(chunks), 3599)
        self.assertEqual(len({row["chunk_id"] for row in chunks}), len(chunks))
        self.assertTrue(
            all(not missing_required_fields(row, NORMALIZED_CHUNK_REQUIRED_FIELDS) for row in chunks)
        )
        self.assertEqual(
            {row["document_id"] for row in documents},
            {row["parent_document_id"] for row in chunks if row["offset_source"] == "dom_text"},
        )
        self.assertEqual(sum(row["offset_source"] == "visual_ocr" for row in chunks), 22)
        audit = audit_chunk_corpus(
            documents,
            contents,
            chunks,
            expected_document_count=980,
            expected_source_ids=set(SOURCE_CONFIG),
        )
        self.assertEqual(audit["gates"], report["gates"])
        self.assertEqual(audit["summary"], report["summary"])
        self.assertEqual(audit["indexing_decision"], "GO")
        self.assertTrue(all(value is True or value == 0 for value in report["gates"].values()))
        self.assertEqual(manifest["chunks"]["row_count"], 3599)
        self.assertEqual(manifest["chunks"]["sha256"], file_sha256(FROZEN_CHUNKS))

    def test_actual_full_chunk_refreeze_is_reproducible(self) -> None:
        kwargs = {
            "built_at": CANONICAL_BUILT_AT,
            "documents_path": DOCUMENTS,
            "contents_path": CONTENTS,
            "normalized_manifest_path": NORMALIZED_MANIFEST,
            "pilot_manifest_path": PILOT_MANIFEST,
            "chunk_dir": Path("data/v3/chunks"),
            "report_dir": Path("reports/v3"),
        }

        first = build_chunk_corpus(**kwargs)
        second = build_chunk_corpus(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["chunk_sha256"], file_sha256(FROZEN_CHUNKS))
        self.assertEqual(first["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(first["indexing_decision"], "GO")


if __name__ == "__main__":
    unittest.main()
