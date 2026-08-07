from __future__ import annotations

import unittest

from src.v3.freeze_canary_contract import (
    PREREGISTERED_GATES,
    audit_slots,
    build_canary_slots,
)


class EarlyGeneralizationCanaryContractTest(unittest.TestCase):
    def test_32_slots_are_balanced_and_unwritten(self) -> None:
        rows = build_canary_slots()
        audit = audit_slots(rows)

        self.assertTrue(audit["gate_pass"])
        self.assertEqual(audit["source_counts"], {
            "dnf_account_policy": 4,
            "dnf_event": 4,
            "dnf_faq": 4,
            "dnf_game_guide": 4,
            "dnf_monthly_item": 4,
            "dnf_notice": 4,
            "dnf_seria_shop": 4,
            "dnf_update": 4,
        })
        self.assertTrue(all(row["question_text"] is None for row in rows))
        self.assertTrue(all(row["gold_answer"] is None for row in rows))

    def test_metrics_and_gates_are_preregistered(self) -> None:
        self.assertEqual(
            PREREGISTERED_GATES["strict_regression_count_max"], 0
        )
        self.assertEqual(
            PREREGISTERED_GATES["temporal_revision_violation_count_max"], 0
        )
        self.assertEqual(
            PREREGISTERED_GATES["false_realtime_evidence_exposure_count_max"], 0
        )
        self.assertEqual(
            PREREGISTERED_GATES["confidence_interval"], "wilson_95_percent"
        )

    def test_unavoidable_corpus_disjointness_exceptions_are_preregistered(self) -> None:
        rows = build_canary_slots()
        audit = audit_slots(rows)

        self.assertEqual(audit["disjointness_exception_counts"], {
            "single_current_monthly_document_and_chunk": 1,
            "single_current_monthly_document_and_chunk_all_facts_in_dev": 1,
            "single_current_policy_revision_parent": 3,
        })
        policy_current = [
            row for row in rows
            if row["source_id"] == "dnf_account_policy"
            and row["time_scope"] in {"current", "mixed"}
        ]
        self.assertTrue(all(row["dev_chunk_disjoint_required"] for row in policy_current))
        monthly_current = [
            row for row in rows
            if row["source_id"] == "dnf_monthly_item"
            and row["time_scope"] == "current"
            and row["expected_route_action"] not in {"reject", "realtime_api"}
        ]
        monthly_by_kind = {row["query_kind"]: row for row in monthly_current}
        self.assertTrue(monthly_by_kind["single"]["dev_claim_disjoint_required"])
        self.assertFalse(monthly_by_kind["multi"]["dev_claim_disjoint_required"])
        self.assertTrue(
            monthly_by_kind["multi"]["question_composition_disjoint_required"]
        )
        self.assertTrue(audit["gate_pass"])


if __name__ == "__main__":
    unittest.main()
