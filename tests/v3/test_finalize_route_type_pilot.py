from __future__ import annotations

import unittest

from src.v3.finalize_route_type_pilot import (
    CANONICAL_ROUTER_SHA256,
    build_final_report,
)


class FinalizeRouteTypePilotTest(unittest.TestCase):
    def test_two_no_go_arms_retain_the_canonical_router(self) -> None:
        signal_a = {
            "decisions": {"signal_a_prevalidation": "NO-GO"},
            "signal_a_canary_32": {},
            "development_63": {},
            "single_question_latency": {},
        }
        signal_b = {
            "decisions": {"signal_b_prevalidation": "NO-GO"},
            "signal_b_canary_32": {},
            "development_63": {},
            "single_question_latency": {},
        }

        report = build_final_report(signal_a, signal_b, CANONICAL_ROUTER_SHA256)

        self.assertEqual(report["cycle_decision"], "NO-GO")
        self.assertEqual(report["canonical_router"]["decision"], "RETAIN_BASELINE")
        self.assertFalse(
            report["canonical_router"]["experimental_route_type_change_promoted"]
        )
        self.assertFalse(report["scope_confirmation"]["new_store_expansion_implemented"])
        self.assertEqual(
            report["scope_confirmation"]["new_field_or_intent_keyword_rules_added"],
            0,
        )
        self.assertEqual(report["next_gate"]["new_40_canary_execution"], "NO-GO")

    def test_finalizer_rejects_an_unrestored_router(self) -> None:
        signal_a = {
            "decisions": {"signal_a_prevalidation": "NO-GO"},
            "signal_a_canary_32": {},
            "development_63": {},
            "single_question_latency": {},
        }
        signal_b = {
            "decisions": {"signal_b_prevalidation": "NO-GO"},
            "signal_b_canary_32": {},
            "development_63": {},
            "single_question_latency": {},
        }

        with self.assertRaisesRegex(RuntimeError, "not restored"):
            build_final_report(signal_a, signal_b, "0" * 64)


if __name__ == "__main__":
    unittest.main()
