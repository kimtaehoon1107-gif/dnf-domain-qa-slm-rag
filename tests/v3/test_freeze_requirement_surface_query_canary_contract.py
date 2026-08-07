from __future__ import annotations

import unittest

from src.v3.freeze_requirement_surface_query_canary_contract import (
    PREREGISTERED_GATES,
    audit_slots,
    build_slots,
)


class FreezeRequirementSurfaceQueryCanaryContractTest(unittest.TestCase):
    def test_slots_are_balanced_empty_and_block_scoring(self) -> None:
        rows = build_slots()
        audit = audit_slots(rows)

        self.assertTrue(audit["gate_pass"])
        self.assertEqual(len(rows), 32)
        self.assertEqual(audit["action_counts"], {"apply": 16, "bypass": 16})
        self.assertTrue(all(row["question_text"] is None for row in rows))
        self.assertTrue(all(not row["sealed_scoring_allowed"] for row in rows))

    def test_gates_cover_precision_and_surplus_citations(self) -> None:
        self.assertEqual(
            PREREGISTERED_GATES["new_irrelevant_or_surplus_citation_count_max"], 0
        )
        self.assertEqual(
            PREREGISTERED_GATES["requirement_citation_precision_vs_baseline"],
            "non_decreasing",
        )
        self.assertEqual(PREREGISTERED_GATES["expected_apply_count"], 16)
        self.assertEqual(PREREGISTERED_GATES["expected_bypass_count"], 16)


if __name__ == "__main__":
    unittest.main()
