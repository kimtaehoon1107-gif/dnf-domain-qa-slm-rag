from __future__ import annotations

import unittest

from src.v3.freeze_v3_2_promotion_canary_contract import (
    PLANNER_MODEL_BLOB_SHA256,
    PREREGISTERED_GATES,
    audit_slots,
    build_slots,
)


class FreezeV32PromotionCanaryContractTest(unittest.TestCase):
    def test_slots_are_balanced_and_unwritten(self) -> None:
        rows = build_slots()
        audit = audit_slots(rows)

        self.assertTrue(audit["gate_pass"])
        self.assertEqual(len(rows), 40)
        self.assertEqual(set(audit["source_counts"].values()), {5})
        self.assertTrue(all(row["question_text"] is None for row in rows))
        self.assertTrue(all(row["requirements"] is None for row in rows))
        self.assertTrue(all(row["evidence_groups"] is None for row in rows))

    def test_candidate_features_and_safety_controls_are_preregistered(self) -> None:
        audit = audit_slots(build_slots())

        self.assertEqual(audit["feature_counts"]["table_atomic"], 3)
        self.assertGreaterEqual(audit["feature_counts"]["global_temporal"], 10)
        self.assertGreaterEqual(audit["feature_counts"]["duplicate_family"], 5)
        self.assertGreaterEqual(
            sum(
                count
                for scope, count in audit["time_scope_counts"].items()
                if scope != "current"
            ),
            6,
        )

    def test_promotion_gates_are_fixed_before_authoring(self) -> None:
        self.assertEqual(PREREGISTERED_GATES["strict_question_regression_count_max"], 0)
        self.assertEqual(PREREGISTERED_GATES["false_full_count_max"], 0)
        self.assertEqual(PREREGISTERED_GATES["exact_citation_slice_rate_min"], 1.0)
        self.assertEqual(
            PREREGISTERED_GATES["temporal_revision_preview_expired_violation_count_max"],
            0,
        )
        self.assertEqual(len(PLANNER_MODEL_BLOB_SHA256), 64)


if __name__ == "__main__":
    unittest.main()

