from __future__ import annotations

import unittest

from src.v3.freeze_typed_evidence_ref_generalization import approve_for_seal


class FreezeTypedEvidenceRefGeneralizationTest(unittest.TestCase):
    def test_approval_opens_scoring_but_keeps_training_locked(self) -> None:
        source = [
            {
                "candidate_id": "case_1",
                "execution_allowed": False,
                "training_allowed": False,
                "author_status": "draft_complete_pending_human_review",
                "review": {
                    "status": "pending",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "rationale": None,
                },
            }
        ]

        sealed = approve_for_seal(
            source,
            reviewer_id="kimdh",
            reviewed_at="2026-07-24T12:00:00+09:00",
        )

        self.assertEqual(sealed[0]["human_review_decision"], "approve")
        self.assertEqual(sealed[0]["review"]["status"], "approved")
        self.assertTrue(sealed[0]["sealed_scoring_allowed"])
        self.assertTrue(sealed[0]["execution_allowed"])
        self.assertFalse(sealed[0]["training_allowed"])
        self.assertFalse(source[0]["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
