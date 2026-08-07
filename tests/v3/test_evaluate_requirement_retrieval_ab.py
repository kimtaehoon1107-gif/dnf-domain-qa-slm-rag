from __future__ import annotations

import unittest

from src.v3.evaluate_requirement_retrieval_ab import (
    ARM_REQUIREMENT_ONLY,
    ARM_UNION,
    build_arm_cases,
    build_retrieval_requests,
    evaluate_gate,
    merge_candidate_ids,
    policy_from_frozen_route,
)


def _chunk(chunk_id: str, *, source: str = "dnf_notice") -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": f"parent-{chunk_id}",
        "source_id": source,
        "status": "current",
        "default_exposure": True,
        "review_required": False,
        "display_text": f"text {chunk_id}",
    }


def _case() -> dict:
    return {
        "case_id": "case-1",
        "dataset": "adaptive_dev_63",
        "question": "question",
        "source_ids": ["dnf_notice"],
        "gold_answerability": "true",
        "requirements": [
            {
                "requirement_id": "requirement_1",
                "subject": "상품",
                "relation": "가격",
                "value_type": "amount",
                "subject_group": "상품",
            },
            {
                "requirement_id": "requirement_2",
                "subject": "상품",
                "relation": "삭제일",
                "value_type": "date",
                "subject_group": "상품",
            },
        ],
        "evidence_groups": [
            {"group_id": "g1", "acceptable_chunk_ids": ["r1"]}
        ],
        "selected_chunk_ids": ["q1"],
        "selected_chunks": {"q1": "text q1"},
        "requirement_attribution": [],
        "baseline_cited_group_ids": [],
        "retrieval_bound_group_ids": ["g1"],
    }


def _retrieval_rows() -> list[dict]:
    return [
        {
            "case_id": "case-1",
            "requirement_index": 1,
            "hits": [{"chunk_id": "r1"}, {"chunk_id": "q1"}],
        },
        {
            "case_id": "case-1",
            "requirement_index": 2,
            "hits": [{"chunk_id": "r2"}],
        },
    ]


class RequirementRetrievalABTest(unittest.TestCase):
    def test_policy_is_reused_from_frozen_route(self) -> None:
        route = {
            "route_action": "retrieve",
            "source_ids": ["dnf_notice", "dnf_update"],
            "allowed_statuses": ["current", "expired"],
            "default_exposure_only": False,
            "temporal_as_of": None,
        }
        policy = policy_from_frozen_route(route, as_of="2026-07-21")
        self.assertIsNotNone(policy)
        self.assertEqual(policy.source_ids, ("dnf_notice", "dnf_update"))
        self.assertEqual(policy.allowed_statuses, ("current", "expired"))
        self.assertFalse(policy.default_exposure_only)
        self.assertFalse(policy.include_review_required)

    def test_candidate_union_is_ordered_and_deduplicated(self) -> None:
        self.assertEqual(
            merge_candidate_ids(["q1", "q2"], ["q2", "r1"], ["q1", "r2"]),
            ["q1", "q2", "r1", "r2"],
        )

    def test_requirement_only_and_union_keep_per_requirement_pools(self) -> None:
        chunks = [_chunk("q1"), _chunk("r1"), _chunk("r2")]
        requirement_only = build_arm_cases(
            [_case()], _retrieval_rows(), chunks, arm=ARM_REQUIREMENT_ONLY
        )[0]
        union = build_arm_cases([_case()], _retrieval_rows(), chunks, arm=ARM_UNION)[0]
        self.assertEqual(
            requirement_only["requirement_candidate_pools"][0][
                "candidate_chunk_ids"
            ],
            ["r1", "q1"],
        )
        self.assertEqual(
            requirement_only["requirement_candidate_pools"][1][
                "candidate_chunk_ids"
            ],
            ["r2"],
        )
        self.assertEqual(
            union["requirement_candidate_pools"][0]["candidate_chunk_ids"],
            ["q1", "r1"],
        )
        self.assertEqual(
            union["requirement_candidate_pools"][1]["candidate_chunk_ids"],
            ["q1", "r2"],
        )

    def test_gold_ids_do_not_change_query_or_policy(self) -> None:
        case = _case()
        changed = _case()
        changed["evidence_groups"][0]["acceptable_chunk_ids"] = ["other-gold"]
        evaluation = [{"dev_id": "case-1", "as_of": "2026-07-21"}]
        runtime = [
            {
                "case_id": "case-1",
                "route": {
                    "route_action": "retrieve",
                    "source_ids": ["dnf_notice"],
                    "allowed_statuses": ["current"],
                    "default_exposure_only": True,
                    "temporal_as_of": None,
                },
            }
        ]
        first = build_retrieval_requests([case], evaluation, runtime)
        second = build_retrieval_requests([changed], evaluation, runtime)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["query"], "상품 가격")
        self.assertFalse(first[0]["gold_ids_available_to_query_or_policy"])

    def test_gate_requires_recovery_without_grounded_or_selection_regression(self) -> None:
        baseline = {
            "answerable": {"grounded_answer": {"successes": 73}}
        }
        candidate = {
            "answerable": {
                "grounded_answer": {"successes": 74},
                "new_false_full_case_count": 0,
            },
            "reject": {"correct_abstain_or_reject": {"successes": 11}},
            "realtime": {"safe_abstain": {"successes": 2}},
        }
        baseline_selection = {
            "mean_spans_per_supported_requirement": 2.9,
            "question_level_nonacceptable_unique_citation_count": 10,
        }
        candidate_selection = {
            "mean_spans_per_supported_requirement": 2.8,
            "question_level_nonacceptable_unique_citation_count": 9,
            "span_validity": {"invalid": 0},
        }
        retrieval = {"false_full_to_grounded_recovery": {"successes": 1}}
        cross = {"same_parent_not_decomposed": {"successes": 7}}
        self.assertTrue(
            evaluate_gate(
                baseline,
                candidate,
                baseline_selection,
                candidate_selection,
                retrieval,
                cross,
            )["pass"]
        )
        candidate["answerable"]["grounded_answer"]["successes"] = 72
        self.assertFalse(
            evaluate_gate(
                baseline,
                candidate,
                baseline_selection,
                candidate_selection,
                retrieval,
                cross,
            )["pass"]
        )


if __name__ == "__main__":
    unittest.main()
