from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audit_raft_distractors import audit  # noqa: E402


class AuditRaftDistractorsTests(unittest.TestCase):
    def test_reports_answer_like_same_parent_and_human_blocked_distractors(self) -> None:
        evidence = "입장 레벨 115 이상이며 모험가 명성 90000 이상이 필요합니다"
        docs = [
            {"doc_id": "gold", "parent_doc_id": "gold_parent", "text": evidence},
            {"doc_id": "duplicate", "parent_doc_id": "other", "text": evidence},
            {"doc_id": "same_parent", "parent_doc_id": "gold_parent", "text": "다른 내용"},
            {"doc_id": "blocked", "parent_doc_id": "blocked_parent", "text": "다른 내용"},
        ]
        raft = [
            {
                "source_qa_id": "qa_1",
                "expected_doc_id": "gold_parent",
                "evidence_span": evidence,
                "documents": [
                    {"doc_id": "gold", "role": "gold"},
                    {"doc_id": "duplicate", "role": "distractor"},
                    {"doc_id": "same_parent", "role": "distractor"},
                    {"doc_id": "blocked", "role": "distractor"},
                ],
            }
        ]
        report = audit(docs, raft, {"qa_1": {"blocked"}}, threshold=0.5)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["exact_span_occurrences"], 1)
        self.assertEqual(report["high_overlap_occurrences"], 1)
        self.assertEqual(report["same_parent_occurrences"], 1)
        self.assertEqual(report["human_blocked_occurrences"], 1)


if __name__ == "__main__":
    unittest.main()
