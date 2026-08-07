from __future__ import annotations

import unittest

from src.v3.prepare_equivalent_official_sibling_review import build_review_row


class PrepareEquivalentOfficialSiblingReviewTest(unittest.TestCase):
    def test_builds_pending_additive_proposal_with_exact_offsets(self) -> None:
        span = "official fact"
        authored = [
            {
                "dev_id": "target",
                "question": "question",
                "source_ids": ["source_a"],
                "gold_document_ids": ["doc_a"],
                "gold_chunk_ids": ["chunk_a"],
                "evidence_groups": [
                    {"group_id": "evidence_1", "evidence_span": span}
                ],
            }
        ]
        documents = [
            {
                "document_id": "doc_b",
                "source_id": "source_b",
                "source_kind": "guide",
                "title": "title",
                "canonical_url": "https://example.invalid",
                "status": "current",
                "default_exposure": True,
            }
        ]
        chunks = [
            {
                "chunk_id": "chunk_b",
                "parent_document_id": "doc_b",
                "display_text": f"prefix {span} suffix",
            }
        ]

        from src.v3 import prepare_equivalent_official_sibling_review as module

        original_target = module.TARGET_DEV_ID
        original_document = module.PROPOSED_DOCUMENT_ID
        original_chunk = module.PROPOSED_CHUNK_ID
        try:
            module.TARGET_DEV_ID = "target"
            module.PROPOSED_DOCUMENT_ID = "doc_b"
            module.PROPOSED_CHUNK_ID = "chunk_b"
            row = build_review_row(authored, documents, chunks)
        finally:
            module.TARGET_DEV_ID = original_target
            module.PROPOSED_DOCUMENT_ID = original_document
            module.PROPOSED_CHUNK_ID = original_chunk

        proposal = row["proposed_sibling"]["evidence_groups"][0]
        self.assertTrue(proposal["exact_substring"])
        self.assertEqual(proposal["start_char"], 7)
        self.assertFalse(row["strict_gold_changed"])
        self.assertFalse(row["acceptable_sibling_applied"])
        self.assertIsNone(row["human_review_decision"])


if __name__ == "__main__":
    unittest.main()
