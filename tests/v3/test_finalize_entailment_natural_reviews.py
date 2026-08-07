from __future__ import annotations

import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.finalize_entailment_natural_reviews import (
    audit_claim_repair_coverage,
    audit_repair_reviews,
    audit_resolved_reviews,
    build_resolved_reviews,
)


PRIMARY = Path(
    "data/v3/evaluation/"
    "entailment_natural_primary_reviews_3ddc3f2b1dd80231d0fd820e82991ed9fecd4980b2fe55707bc9e2d67f3b0222.jsonl"
)
ADJUDICATION = Path(
    "data/v3/evaluation/"
    "entailment_natural_adjudication_reviews_860774601c888e8ea6df72ac221abdadc3dd8918d8391a6cf9e3a0bb8ed9262d.jsonl"
)
REPAIR_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_claim_repair_packet_4ab7ded1cc83ea7c1ffa658874ae2f5f2e6b642f321988dc73f789e018ed1a2b.jsonl"
)
REPAIR_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_claim_repair_draft_4ab7ded1cc83ea7c1ffa658874ae2f5f2e6b642f321988dc73f789e018ed1a2b.jsonl"
)
FOLLOWUP_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_claim_repair_followup_packet_6968e3f619ab1124fe1575975d7a9c935215adae96d2d553ec0d4a58f9cb51bf.jsonl"
)
FOLLOWUP_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_claim_repair_followup_draft_6968e3f619ab1124fe1575975d7a9c935215adae96d2d553ec0d4a58f9cb51bf.jsonl"
)
SAMPLING = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)
CORRECTIONS = Path(
    "data/v3/evaluation/"
    "entailment_claim_corrections_a019f22ec3f2fbb8ace3637bbd961a6eace23c5899dbc4e1b76211982d15aad9.jsonl"
)
ISSUES = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_issues_9ad7c4e8d4d220d40e58b2aff2f9a00f9bcce0b9d72b9094f6b11c6acbf4ad31.jsonl"
)


class EntailmentNaturalReviewFinalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.primary = read_jsonl(PRIMARY)
        cls.adjudication = read_jsonl(ADJUDICATION)
        cls.repair_packet = read_jsonl(REPAIR_PACKET)
        cls.repair = read_jsonl(REPAIR_DRAFT)
        cls.followup_packet = read_jsonl(FOLLOWUP_PACKET)
        cls.followup = read_jsonl(FOLLOWUP_DRAFT)
        cls.combined_repair = cls.repair + cls.followup
        cls.issues = read_jsonl(ISSUES)
        cls.sampling = read_jsonl(SAMPLING)
        cls.corrections = read_jsonl(CORRECTIONS)

    def test_claim_repair_review_is_merge_ready(self) -> None:
        audit = audit_repair_reviews(self.repair_packet, self.repair)
        self.assertTrue(audit["ready_for_merge"])
        self.assertEqual(audit["label_counts"], {"insufficient": 2, "support": 2})

        followup_audit = audit_repair_reviews(
            self.followup_packet, self.followup
        )
        self.assertTrue(followup_audit["ready_for_merge"])
        self.assertEqual(followup_audit["label_counts"], {"insufficient": 1})

    def test_claim_repair_coverage_requires_followup_relationship(self) -> None:
        prior = audit_claim_repair_coverage(
            self.sampling, self.corrections, self.repair
        )
        self.assertFalse(prior["complete"])
        self.assertEqual(prior["expected_relationship_count"], 5)
        self.assertEqual(len(prior["missing_primary_item_ids"]), 1)

        complete = audit_claim_repair_coverage(
            self.sampling, self.corrections, self.combined_repair
        )
        self.assertTrue(complete["complete"])
        self.assertEqual(complete["reviewed_relationship_count"], 5)

    def test_resolved_rows_preserve_40_relationships_and_apply_lineage(self) -> None:
        rows = build_resolved_reviews(
            self.primary,
            self.adjudication,
            self.combined_repair,
            self.issues,
            self.sampling,
            self.corrections,
        )
        self.assertEqual(len(rows), 40)
        self.assertEqual(
            sum(row["claim_revision_status"] == "corrected" for row in rows), 5
        )
        self.assertEqual(
            sum(not row["natural_evaluation_eligible"] for row in rows), 2
        )
        self.assertTrue(all(row["review_lineage"]["primary_item_id"] for row in rows))

    def test_resolved_audit_is_integrity_go_but_three_class_no_go(self) -> None:
        rows = build_resolved_reviews(
            self.primary,
            self.adjudication,
            self.combined_repair,
            self.issues,
            self.sampling,
            self.corrections,
        )
        audit = audit_resolved_reviews(rows)
        self.assertTrue(audit["integrity_ready"])
        self.assertFalse(audit["ready_for_three_class_scoring"])
        self.assertEqual(audit["label_counts"], {"insufficient": 23, "support": 17})
        self.assertEqual(
            audit["eligible_label_counts"], {"insufficient": 21, "support": 17}
        )


if __name__ == "__main__":
    unittest.main()
