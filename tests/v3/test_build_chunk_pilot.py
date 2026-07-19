from __future__ import annotations

import collections
import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.build_chunk_pilot import (
    SOURCE_CONFIG,
    SOURCE_TARGETS,
    build_chunk_pilot,
    build_chunks_for_selection,
    select_pilot_documents,
    split_offset_chunks,
)
from src.v3.schemas import NORMALIZED_CHUNK_REQUIRED_FIELDS, missing_required_fields


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
FROZEN_SELECTION = Path(
    "data/v3/chunks/"
    "chunk_pilot_selection_af717de4e375b7c6f74a4a6da41640280c1ea2c4c5550278c1811c2954553b2b.jsonl"
)
FROZEN_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_pilot_f97e62d54d2fa4419f8a33ef3543f93916b14c27b978cd1ff6b38b2fff7b0dbe.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/chunks/"
    "chunk_pilot_manifest_ba5e1d5a9b8a237df9a99e5fb698bbb8e0a4b6dc1668b3cabece9e971e0154e6.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "chunk_pilot_d35f24f989135a1bad7c6a5c1f3f9eaccbcc5bd018268c2bbc8db731395a189d.json"
)
BUILT_AT = "2026-07-18T00:30:00+09:00"


class BuildChunkPilotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = read_jsonl(DOCUMENTS)
        cls.contents = read_jsonl(CONTENTS)
        cls.documents_by_id = {row["document_id"]: row for row in cls.documents}
        cls.contents_by_id = {row["document_id"]: row for row in cls.contents}

    def test_selection_is_deterministic_stratified_and_includes_all_visual_documents(self) -> None:
        first = select_pilot_documents(self.documents, self.contents_by_id)
        second = select_pilot_documents(list(reversed(self.documents)), self.contents_by_id)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 63)
        self.assertEqual(
            collections.Counter(row["source_id"] for row in first),
            collections.Counter(SOURCE_TARGETS),
        )
        self.assertEqual({row["status"] for row in first}, {"current", "expired", "superseded", "unknown"})
        self.assertEqual(sum(row["has_visual_evidence"] for row in first), 18)
        guide_revisions = [
            row for row in first if row["canonical_url"] == "https://df.nexon.com/guide?no=1535"
        ]
        self.assertEqual(len(guide_revisions), 2)

    def test_offset_split_preserves_headings_tables_and_long_text(self) -> None:
        long_sentence = "긴문장 " * 80
        text = "# 첫 제목\n도입 문장입니다.\n## 표 제목\n항목 | 값\n보상 | 100개\n" + long_sentence

        spans = split_offset_chunks(text, max_chars=100, overlap_chars=20)

        self.assertGreater(len(spans), 3)
        for span in spans:
            display = text[span["start"] : span["end"]]
            self.assertTrue(display)
            self.assertLessEqual(len(display), 100)
        self.assertTrue(any(span["heading_path"] == ["첫 제목", "표 제목"] for span in spans))
        self.assertTrue(any(span["chunk_type"] in {"table", "mixed"} for span in spans))
        covered = set()
        for span in spans:
            covered.update(range(span["start"], span["end"]))
        self.assertTrue(all(index in covered for index, value in enumerate(text) if not value.isspace()))

    def test_heading_only_sections_merge_without_losing_offsets(self) -> None:
        text = "문서 제목\n## 참여 방법\n## 플레이 가이드\n실제 설명이 이어집니다."

        spans = split_offset_chunks(text, max_chars=100, overlap_chars=20)

        self.assertEqual(len(spans), 1)
        self.assertEqual(text[spans[0]["start"] : spans[0]["end"]], text)
        self.assertEqual(spans[0]["chunk_type"], "section")

    def test_oversized_table_row_splits_without_losing_offset_coverage(self) -> None:
        text = "## 비교표\n| " + ("변경 전 내용 " * 30) + "| " + ("변경 후 내용 " * 20) + "|"

        spans = split_offset_chunks(text, max_chars=100, overlap_chars=20)

        self.assertGreater(len(spans), 2)
        self.assertTrue(all(len(text[row["start"] : row["end"]]) <= 100 for row in spans))
        self.assertTrue(any(row["chunk_type"] in {"table", "mixed"} for row in spans))
        covered = set()
        for row in spans:
            covered.update(range(row["start"], row["end"]))
        self.assertTrue(all(index in covered for index, value in enumerate(text) if not value.isspace()))

    def test_unmergeable_short_section_expands_with_bounded_overlap(self) -> None:
        text = "짧은 도입\n## 본문\n" + ("긴 설명 " * 50)

        spans = split_offset_chunks(text, max_chars=100, overlap_chars=20)

        self.assertGreater(len(spans), 1)
        self.assertTrue(all(len(text[row["start"] : row["end"]]) <= 100 for row in spans))
        self.assertTrue(all(len(text[row["start"] : row["end"]]) >= 80 for row in spans))
        self.assertLess(spans[1]["start"], spans[0]["end"])

    def test_visual_ocr_chunks_are_separate_review_only_and_offsets_reproduce(self) -> None:
        selection = select_pilot_documents(self.documents, self.contents_by_id)
        visual_selection = [row for row in selection if row["has_visual_evidence"]][:1]

        chunks = build_chunks_for_selection(
            visual_selection, self.documents_by_id, self.contents_by_id
        )

        self.assertTrue(chunks)
        self.assertTrue(
            all(not missing_required_fields(row, NORMALIZED_CHUNK_REQUIRED_FIELDS) for row in chunks)
        )
        dom = [row for row in chunks if row["offset_source"] == "dom_text"]
        visual = [row for row in chunks if row["offset_source"] == "visual_ocr"]
        self.assertTrue(dom)
        self.assertTrue(visual)
        content = self.contents_by_id[visual_selection[0]["document_id"]]
        for row in dom:
            self.assertEqual(
                content["text"][row["start_offset"] : row["end_offset"]], row["display_text"]
            )
        for row in visual:
            self.assertEqual(
                content["visual_evidence"]["text"][row["start_offset"] : row["end_offset"]],
                row["display_text"],
            )
            self.assertFalse(row["default_exposure"])
            self.assertTrue(row["review_required"])
            self.assertEqual(row["evidence_quality"], "unverified_ocr")
            self.assertEqual(
                (row["max_chars"], row["overlap_chars"]),
                SOURCE_CONFIG[row["source_id"]],
            )


class FrozenChunkPilotArtifactTest(unittest.TestCase):
    def test_actual_chunk_pilot_artifacts_pass_offset_and_safety_gates(self) -> None:
        documents = {row["document_id"]: row for row in read_jsonl(DOCUMENTS)}
        contents = {row["document_id"]: row for row in read_jsonl(CONTENTS)}
        selection = read_jsonl(FROZEN_SELECTION)
        chunks = read_jsonl(FROZEN_CHUNKS)
        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

        self.assertEqual(file_sha256(FROZEN_SELECTION), FROZEN_SELECTION.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_CHUNKS), FROZEN_CHUNKS.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_MANIFEST), FROZEN_MANIFEST.stem.rsplit("_", 1)[1])
        self.assertEqual(file_sha256(FROZEN_REPORT), FROZEN_REPORT.stem.rsplit("_", 1)[1])
        self.assertEqual(len(selection), 63)
        self.assertEqual(len(chunks), 467)
        self.assertEqual(
            collections.Counter(row["source_id"] for row in selection),
            collections.Counter(SOURCE_TARGETS),
        )
        self.assertEqual(len({row["chunk_id"] for row in chunks}), len(chunks))
        self.assertTrue(
            all(not missing_required_fields(row, NORMALIZED_CHUNK_REQUIRED_FIELDS) for row in chunks)
        )
        selected_ids = {row["document_id"] for row in selection}
        self.assertEqual(
            selected_ids,
            {row["parent_document_id"] for row in chunks if row["offset_source"] == "dom_text"},
        )
        for row in chunks:
            content = contents[row["parent_document_id"]]
            source_text = (
                content["text"]
                if row["offset_source"] == "dom_text"
                else content["visual_evidence"]["text"]
            )
            self.assertEqual(
                source_text[row["start_offset"] : row["end_offset"]], row["display_text"]
            )
            self.assertLessEqual(len(row["display_text"]), row["max_chars"])
            if row["default_exposure"]:
                self.assertIn(row["status"], {"current", "upcoming"})
                self.assertNotIn(row["source_kind"], {"preview_patch", "roadmap_statement"})
        visual = [row for row in chunks if row["offset_source"] == "visual_ocr"]
        self.assertEqual(len(visual), 22)
        self.assertTrue(all(not row["default_exposure"] and row["review_required"] for row in visual))
        self.assertEqual(manifest["chunks"]["row_count"], 467)
        self.assertTrue(all(value is True or value == 0 for value in report["gates"].values()))
        self.assertEqual(report["full_chunking_decision"], "GO")

    def test_actual_chunk_pilot_refreeze_is_reproducible(self) -> None:
        kwargs = {
            "built_at": BUILT_AT,
            "documents_path": DOCUMENTS,
            "contents_path": CONTENTS,
            "normalized_manifest_path": NORMALIZED_MANIFEST,
            "chunk_dir": Path("data/v3/chunks"),
            "report_dir": Path("reports/v3"),
        }

        first = build_chunk_pilot(**kwargs)
        second = build_chunk_pilot(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["selection_sha256"], file_sha256(FROZEN_SELECTION))
        self.assertEqual(first["chunk_sha256"], file_sha256(FROZEN_CHUNKS))
        self.assertEqual(first["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(first["full_chunking_decision"], "GO")


if __name__ == "__main__":
    unittest.main()
