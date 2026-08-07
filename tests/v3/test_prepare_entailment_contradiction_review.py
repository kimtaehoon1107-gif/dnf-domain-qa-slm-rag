from __future__ import annotations

import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.collect_details import _serialize_jsonl
from src.v3.prepare_entailment_contradiction_review import (
    audit_packet,
    build_packet,
)


DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
CONTENTS = Path(
    "data/v3/normalized/"
    "document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl"
)
CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)


class EntailmentRevisionConflictReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = read_jsonl(DOCUMENTS)
        cls.contents = read_jsonl(CONTENTS)
        cls.chunks = read_jsonl(CHUNKS)
        cls.rows = build_packet(cls.documents, cls.contents, cls.chunks)

    def test_packet_contains_six_exact_cross_revision_candidates(self) -> None:
        audit = audit_packet(self.rows)
        self.assertTrue(audit["gate_pass"])
        self.assertEqual(len(self.rows), 6)
        self.assertTrue(
            all(
                row["claim_time_scope"]
                == "cross_revision_proposition_comparison"
                for row in self.rows
            )
        )
        self.assertTrue(
            all(
                row["revision_comparison"]["claim_is_exact_official_excerpt"]
                for row in self.rows
            )
        )

    def test_packet_hides_expected_labels_and_disables_reuse(self) -> None:
        self.assertTrue(all(row["review_label"] is None for row in self.rows))
        self.assertTrue(
            all(
                row["revision_comparison"]["expected_label_in_packet"] is False
                for row in self.rows
            )
        )
        self.assertFalse(any(row["training_allowed"] for row in self.rows))
        self.assertFalse(any(row["final_benchmark_eligible"] for row in self.rows))

    def test_build_is_deterministic(self) -> None:
        again = build_packet(self.documents, self.contents, self.chunks)
        self.assertEqual(
            _serialize_jsonl(self.rows, lambda row: row["item_ordinal"]),
            _serialize_jsonl(again, lambda row: row["item_ordinal"]),
        )


if __name__ == "__main__":
    unittest.main()
