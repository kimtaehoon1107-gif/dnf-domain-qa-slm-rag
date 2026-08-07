from __future__ import annotations

import unittest
from pathlib import Path

from src.v3.audit_claim_reranker_canonical import audit_canonical_state


class ClaimRerankerCanonicalAuditTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_56_is_exact_reproducible_canonical_and_57_is_development_only(self) -> None:
        result = audit_canonical_state(self.ROOT)

        self.assertEqual(result["canonical"]["cited_group_hits"], 56)
        self.assertTrue(result["canonical"]["replay_exact"])
        self.assertEqual(result["v3_2_development"]["cited_group_hits"], 57)
        self.assertFalse(result["v3_2_development"]["canonical_promotion"])
        self.assertEqual(result["shared_immutable_input_mismatches"], [])
        self.assertEqual(len(result["selection_changes"]), 1)


if __name__ == "__main__":
    unittest.main()
