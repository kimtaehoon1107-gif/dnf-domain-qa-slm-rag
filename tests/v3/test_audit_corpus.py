from __future__ import annotations

import unittest

from src.v3.audit_corpus import audit_rows
from src.v3.schemas import CHUNK_REQUIRED_FIELDS, DOCUMENT_REQUIRED_FIELDS, missing_required_fields


class CorpusAuditTest(unittest.TestCase):
    def test_reports_quality_gaps_without_transforming_rows(self) -> None:
        guide = {
            "doc_id": "guide_1",
            "doc_type": "game_guide",
            "title": "가이드",
            "published_at": "2026-01-01",
            "text": "같은 본문",
            "metadata": {"guide_category": "", "guide_updated_at": ""},
        }
        official = {
            "doc_id": "notice_1",
            "doc_type": "notice",
            "title": "공지",
            "published_at": "2026-01-02",
            "text": "공식 본문",
            "metadata": {"official_section": "notice", "category": "일반"},
        }
        chunks = [
            {"doc_id": "guide_1__chunk_001", "parent_doc_id": "guide_1", "text": "중복 청크"},
            {"doc_id": "notice_1__chunk_001", "parent_doc_id": "notice_1", "text": "중복 청크"},
            {"doc_id": "orphan__chunk_001", "parent_doc_id": "missing", "text": "짧음"},
        ]

        report = audit_rows([guide], [official], chunks)

        self.assertEqual(report["documents"]["total"], 2)
        self.assertEqual(report["documents"]["guide_missing_category"], 1)
        self.assertEqual(report["documents"]["source_kind_counts"]["notice"], 1)
        self.assertEqual(report["chunks"]["duplicate_text_group_count"], 1)
        self.assertEqual(report["chunks"]["orphan_chunk_count"], 1)
        self.assertEqual(report["chunks"]["with_valid_offsets"], 0)
        self.assertNotIn("start_offset", chunks[0])

    def test_schema_missing_fields_treats_nullable_keys_as_present(self) -> None:
        document = {field: None for field in DOCUMENT_REQUIRED_FIELDS}
        chunk = {field: None for field in CHUNK_REQUIRED_FIELDS}

        self.assertEqual(missing_required_fields(document, DOCUMENT_REQUIRED_FIELDS), [])
        self.assertEqual(missing_required_fields(chunk, CHUNK_REQUIRED_FIELDS), [])


if __name__ == "__main__":
    unittest.main()
