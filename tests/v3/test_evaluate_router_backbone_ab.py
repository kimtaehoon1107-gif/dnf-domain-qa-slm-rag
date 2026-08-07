from __future__ import annotations

import unittest
from unittest.mock import patch

from src.v3.evaluate_router_backbone_ab import (
    compare_arms,
    narrow_safety_reason,
    simulate_arm,
)


def _decision(status: str, chunk_id: str = "c1") -> dict:
    return {
        "requirement_id": "requirement_1",
        "status": status,
        "spans": (
            [{"chunk_id": chunk_id, "start_char": 0, "end_char": 1, "text": "x"}]
            if status == "supported_exact"
            else []
        ),
    }


class RouterBackboneAnswerSourceABTest(unittest.TestCase):
    def test_narrow_safety_does_not_reuse_private_or_realtime_reason(self) -> None:
        with patch(
            "src.v3.evaluate_router_backbone_ab.classify_answerability",
            return_value={"label": "false", "reason": "requires_private_account_state"},
        ):
            self.assertIsNone(narrow_safety_reason("private"))
        with patch(
            "src.v3.evaluate_router_backbone_ab.classify_answerability",
            return_value={"label": "false", "reason": "protected_internal_instruction"},
        ):
            self.assertEqual(
                narrow_safety_reason("injection"), "protected_internal_instruction"
            )

    @patch(
        "src.v3.evaluate_router_backbone_ab.narrow_safety_reason",
        return_value=None,
    )
    def test_front_suppresses_supported_docs_but_post_preserves_them(
        self, _safety: object
    ) -> None:
        decisions = [_decision("supported_exact")]
        predictions = [{"requirement_index": 1, "answer_source": "realtime"}]
        front = simulate_arm(
            placement="front",
            question="q",
            assembler_decisions=decisions,
            classifier_predictions=predictions,
            chunk_to_parent={"c1": "p1"},
        )
        post = simulate_arm(
            placement="post_search_evidence_priority",
            question="q",
            assembler_decisions=decisions,
            classifier_predictions=predictions,
            chunk_to_parent={"c1": "p1"},
        )
        self.assertEqual(front["route_action"], "realtime_api")
        self.assertEqual(front["cited_chunk_ids"], [])
        self.assertEqual(post["route_action"], "retrieve")
        self.assertEqual(post["cited_chunk_ids"], ["c1"])

    @patch(
        "src.v3.evaluate_router_backbone_ab.narrow_safety_reason",
        return_value=None,
    )
    def test_post_search_routes_only_when_evidence_is_unsupported(
        self, _safety: object
    ) -> None:
        arm = simulate_arm(
            placement="post_search_evidence_priority",
            question="q",
            assembler_decisions=[_decision("unsupported")],
            classifier_predictions=[
                {"requirement_index": 1, "answer_source": "personal_account"}
            ],
            chunk_to_parent={},
        )
        self.assertEqual(arm["route_action"], "realtime_api")
        self.assertEqual(arm["response_mode"], "route_without_document_answer")

    @patch(
        "src.v3.evaluate_router_backbone_ab.narrow_safety_reason",
        return_value=None,
    )
    def test_cross_parent_uses_supported_span_parents_only(
        self, _safety: object
    ) -> None:
        decisions = [_decision("supported_exact", "c1"), _decision("supported_exact", "c2")]
        arm = simulate_arm(
            placement="arm0",
            question="q",
            assembler_decisions=decisions,
            classifier_predictions=[],
            chunk_to_parent={"c1": "p1", "c2": "p2"},
        )
        self.assertTrue(arm["cross_parent_candidate"])
        self.assertEqual(arm["route_action"], "decompose_candidate")

    def test_classifier_gate_requires_net_improvement_and_no_regression(self) -> None:
        arm0 = self._summary(honest=90, overreject=0, suppressed=0, grounded=75, reject=11)
        worse = self._summary(honest=88, overreject=0, suppressed=0, grounded=75, reject=9)
        result = compare_arms(arm0, worse)
        self.assertFalse(result["pass"])
        self.assertFalse(result["checks"]["honest_correct_total_improved"])
        self.assertFalse(result["checks"]["reject_correctness_not_reduced"])

    @staticmethod
    def _summary(
        *, honest: int, overreject: int, suppressed: int, grounded: int, reject: int
    ) -> dict:
        return {
            "honest_correct_total": {"successes": honest},
            "answerable": {
                "overreject": {"successes": overreject},
                "suppressed_expected_docs_requirements": suppressed,
                "grounded_answer": {"successes": grounded},
            },
            "reject": {"correct_abstain_or_reject": {"successes": reject}},
            "realtime": {"preferred_route": {"successes": 0}},
        }


if __name__ == "__main__":
    unittest.main()

