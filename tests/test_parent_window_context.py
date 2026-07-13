from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_tuned_slm_smoke import build_sibling_lookup, expand_sibling_contexts  # noqa: E402


class ParentWindowContextTests(unittest.TestCase):
    def test_expands_only_immediate_same_parent_siblings(self) -> None:
        chunks = [
            {
                "doc_id": f"p__chunk_{index:03d}",
                "parent_doc_id": "p",
                "chunk_index": index,
                "title": "parent",
                "text": f"text {index}",
            }
            for index in range(1, 5)
        ]
        chunks.append(
            {
                "doc_id": "other__chunk_002",
                "parent_doc_id": "other",
                "chunk_index": 2,
                "title": "other",
                "text": "other text",
            }
        )
        by_id, by_parent_index = build_sibling_lookup(chunks)
        contexts = [{"doc_id": "p__chunk_002", "title": "parent", "text": "text 2"}]

        expanded = expand_sibling_contexts(
            contexts,
            chunks_by_id=by_id,
            siblings_by_parent_index=by_parent_index,
            question="text",
            max_doc_chars=100,
        )

        self.assertEqual(expanded[0]["doc_id"], "p__chunk_002")
        self.assertEqual(
            expanded[0]["context_chunk_ids"],
            ["p__chunk_001", "p__chunk_002", "p__chunk_003"],
        )
        self.assertIn("text 2", expanded[0]["text"])
        self.assertIn("[previous sibling context", expanded[0]["text"])
        self.assertNotIn("text 4", expanded[0]["text"])
        self.assertNotIn("other text", expanded[0]["text"])

    def test_boundary_anchor_has_only_existing_neighbors(self) -> None:
        chunks = [
            {
                "doc_id": f"p__chunk_{index:03d}",
                "parent_doc_id": "p",
                "chunk_index": index,
                "title": "parent",
                "text": f"text {index}",
            }
            for index in (1, 2)
        ]
        by_id, by_parent_index = build_sibling_lookup(chunks)
        expanded = expand_sibling_contexts(
            [{"doc_id": "p__chunk_001", "title": "parent", "text": "text 1"}],
            by_id,
            by_parent_index,
            question="text",
            max_doc_chars=100,
        )
        self.assertEqual(expanded[0]["context_chunk_ids"], ["p__chunk_001", "p__chunk_002"])

    def test_does_not_duplicate_sibling_that_is_already_retrieved(self) -> None:
        chunks = [
            {
                "doc_id": f"p__chunk_{index:03d}",
                "parent_doc_id": "p",
                "chunk_index": index,
                "title": "parent",
                "text": f"text {index}",
            }
            for index in (1, 2, 3)
        ]
        by_id, by_parent_index = build_sibling_lookup(chunks)
        expanded = expand_sibling_contexts(
            [
                {"doc_id": "p__chunk_001", "title": "parent", "text": "text 1"},
                {"doc_id": "p__chunk_002", "title": "parent", "text": "text 2"},
            ],
            by_id,
            by_parent_index,
            question="text",
            max_doc_chars=100,
        )
        self.assertEqual(expanded[0]["context_chunk_ids"], ["p__chunk_001"])
        self.assertEqual(expanded[1]["context_chunk_ids"], ["p__chunk_002", "p__chunk_003"])


if __name__ == "__main__":
    unittest.main()
