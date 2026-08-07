from __future__ import annotations

import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.prepare_entailment_claim_repair_followup import (
    build_followup_packet,
    find_missing_repair_relationships,
)
from src.v3.prepare_entailment_review import REVIEW_FIELDS


PRIMARY = Path(
    "data/v3/evaluation/"
    "entailment_natural_primary_reviews_3ddc3f2b1dd80231d0fd820e82991ed9fecd4980b2fe55707bc9e2d67f3b0222.jsonl"
)
SAMPLING = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)
CORRECTIONS = Path(
    "data/v3/evaluation/"
    "entailment_claim_corrections_a019f22ec3f2fbb8ace3637bbd961a6eace23c5899dbc4e1b76211982d15aad9.jsonl"
)
PRIOR_REPAIRS = Path(
    "data/v3/evaluation/"
    "entailment_claim_repair_reviews_b36c096b6e8d7608971328dc28da02c083a5be3a7284ac8f646f5c0be4160abe.jsonl"
)


class EntailmentClaimRepairFollowupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.missing = find_missing_repair_relationships(
            read_jsonl(PRIMARY),
            read_jsonl(SAMPLING),
            read_jsonl(CORRECTIONS),
            read_jsonl(PRIOR_REPAIRS),
        )

    def test_exactly_one_same_dev_relationship_was_missing(self) -> None:
        self.assertEqual(len(self.missing), 1)
        primary, correction, stratum = self.missing[0]
        self.assertEqual(stratum, "default_hard_candidate")
        self.assertEqual(primary["question"], "외부 결제 요구 주의사항은 뭐야?")
        self.assertIn("사이버안전지킴이", correction["proposed_claim_text"])

    def test_followup_packet_resets_human_fields_and_preserves_lineage(self) -> None:
        packet = build_followup_packet(self.missing)
        self.assertEqual(len(packet), 1)
        row = packet[0]
        self.assertTrue(all(row[field] is None for field in REVIEW_FIELDS))
        self.assertTrue(row["repair_of_primary_item_id"].startswith("entailment_review_"))
        self.assertEqual(
            row["claim_repair"]["coverage_reason"],
            "same_dev_id_relationship_missing_from_initial_repair_packet",
        )


if __name__ == "__main__":
    unittest.main()
