from __future__ import annotations

import unittest

from src.v3.freeze_replacement_canary_contract import (
    PREREGISTERED_GATES,
    audit_replacement_slots,
    build_replacement_slots,
)


class FreezeReplacementCanaryContractTest(unittest.TestCase):
    def test_40_slots_are_source_balanced_and_unwritten(self) -> None:
        rows = build_replacement_slots()
        audit = audit_replacement_slots(rows)

        self.assertTrue(audit["gate_pass"])
        self.assertEqual(len(rows), 40)
        self.assertEqual(set(audit["source_counts"].values()), {5})
        self.assertEqual(set(audit["stratum_counts"].values()), {8})
        self.assertTrue(all(row["question_text"] is None for row in rows))
        self.assertTrue(all(row["gold_answer"] is None for row in rows))
        self.assertTrue(all(row["evidence_groups"] is None for row in rows))

    def test_compound_slots_forbid_old_surface_trigger_words(self) -> None:
        rows = build_replacement_slots()
        compound = [
            row
            for row in rows
            if row["stratum"] == "compound_without_surface_keywords"
        ]

        self.assertEqual(len(compound), 8)
        self.assertTrue(
            all(
                row["forbidden_surface_tokens"] == ["각각", "비교", "함께"]
                for row in compound
            )
        )

    def test_safety_and_parent_exceptions_are_preregistered(self) -> None:
        audit = audit_replacement_slots(build_replacement_slots())

        self.assertEqual(
            audit["source_safety_query_kind_counts"],
            {
                "comparison": 1,
                "false": 1,
                "historical": 4,
                "preview": 1,
                "realtime": 1,
            },
        )
        self.assertEqual(
            audit["parent_disjointness_exception_counts"],
            {
                "current_policy_revision_required": 5,
                "single_current_monthly_parent": 4,
                "zero_evidence_control": 2,
            },
        )

    def test_new_canary_gates_are_fixed_before_authoring(self) -> None:
        self.assertEqual(PREREGISTERED_GATES["route_action_exact_min"], 0.85)
        self.assertEqual(
            PREREGISTERED_GATES["route_action_drop_from_frozen_development_max"],
            0.05,
        )
        self.assertEqual(PREREGISTERED_GATES["strict_regression_count_max"], 0)
        self.assertEqual(
            PREREGISTERED_GATES["temporal_revision_violation_count_max"], 0
        )
        self.assertEqual(
            PREREGISTERED_GATES["false_realtime_evidence_exposure_count_max"],
            0,
        )
        self.assertEqual(
            PREREGISTERED_GATES["partial_disclaimer_required"], "8_of_8"
        )


if __name__ == "__main__":
    unittest.main()
