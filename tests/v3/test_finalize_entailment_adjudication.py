from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.finalize_entailment_adjudication import (
    build_claim_corrections,
    build_claim_repair_packet,
    build_issue_ledger,
    classify_review_issues,
)
from src.v3.prepare_entailment_review import REVIEW_FIELDS


ADJUDICATION_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_natural_adjudication_draft_2c82048a7ca51177278bbd9ec8782a80afae18d2f446ab0e6d365ae62de82b31.jsonl"
)
SAMPLING_LEDGER = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)


class EntailmentAdjudicationFinalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reviewed = read_jsonl(ADJUDICATION_DRAFT)
        cls.sampling = read_jsonl(SAMPLING_LEDGER)

    def test_explicit_human_issue_markers_are_classified(self) -> None:
        claim = {"review_rationale": "[CLAIM 오류] 잘못된 claim", "needs_adjudication": True}
        evidence = {
            "review_rationale": "[EVIDENCE 오류] 부모 문서 혼입",
            "needs_adjudication": False,
        }
        pending = {"review_rationale": "추가 확인 필요", "needs_adjudication": True}
        self.assertEqual(classify_review_issues(claim), ["claim_error"])
        self.assertEqual(classify_review_issues(evidence), ["evidence_error"])
        self.assertEqual(classify_review_issues(pending), ["unresolved_adjudication"])

    def test_issue_ledger_uses_only_post_review_provenance(self) -> None:
        issues = build_issue_ledger(self.reviewed, self.sampling)
        counts = {}
        for row in issues:
            for issue_type in row["issue_types"]:
                counts[issue_type] = counts.get(issue_type, 0) + 1
        self.assertEqual(counts, {"claim_error": 4, "evidence_error": 2})
        self.assertTrue(all(row["dev_id"].startswith("retrieval_dev_sha256_") for row in issues))

    def test_two_claim_corrections_cover_four_relationships(self) -> None:
        issues = build_issue_ledger(self.reviewed, self.sampling)
        corrections = build_claim_corrections(self.reviewed, issues)
        self.assertEqual(len(corrections), 2)
        self.assertEqual(sum(row["source_relationship_count"] for row in corrections), 4)
        by_question = {row["question"]: row for row in corrections}
        island = by_question["일렁이는 군도 보스 맵 배경에서 무엇이 제거됐어?"]
        self.assertEqual(
            island["proposed_claim_text"],
            "일렁이는 군도 던전의 보스 맵 배경에서 일각수 크라켄의 촉수가 제거됩니다.",
        )
        payment = by_question["외부 결제 요구 주의사항은 뭐야?"]
        self.assertIn("사이버안전지킴이", payment["proposed_claim_text"])
        self.assertIn("한국인터넷진흥원", payment["proposed_claim_text"])

    def test_repair_packet_resets_only_new_human_review_fields(self) -> None:
        issues = build_issue_ledger(self.reviewed, self.sampling)
        corrections = build_claim_corrections(self.reviewed, issues)
        packet = build_claim_repair_packet(self.reviewed, issues, corrections)
        self.assertEqual(len(packet), 4)
        for row in packet:
            self.assertTrue(all(row[field] is None for field in REVIEW_FIELDS))
            self.assertNotEqual(
                row["claim_text"], row["claim_repair"]["original_claim_text"]
            )
            self.assertIn("prior_adjudicated_label", row["claim_repair"])


if __name__ == "__main__":
    unittest.main()
