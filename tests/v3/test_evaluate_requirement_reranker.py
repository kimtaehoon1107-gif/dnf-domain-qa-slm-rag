from __future__ import annotations

import unittest

from src.v3.evaluate_requirement_reranker import (
    attach_requirement_scores,
    build_cases,
    evaluate_rows,
    gate,
    prepare_model_pairs,
    requirement_text,
    aggregate,
)


def _chunk(chunk_id: str) -> dict:
    return {"chunk_id": chunk_id, "retrieval_text": f"text {chunk_id}"}


def _gold(case_id: str, groups: list[list[str]]) -> dict:
    return {
        "dev_id": case_id,
        "question": "상품 가격과 삭제일을 알려줘",
        "source_ids": ["dnf_monthly_item"],
        "answerability": "true",
        "evidence_groups": [
            {
                "group_id": f"g{index}",
                "acceptable_chunk_ids": acceptable,
            }
            for index, acceptable in enumerate(groups, 1)
        ],
    }


def _enumeration(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "requirements": [
            {
                "requirement_id": "r1",
                "subject": "상품",
                "relation": "가격",
                "value_type": "amount",
                "subject_group": "상품",
            },
            {
                "requirement_id": "r2",
                "subject": "상품",
                "relation": "삭제일",
                "value_type": "date",
                "subject_group": "상품",
            },
        ],
    }


def _candidates(case_id: str) -> dict:
    return {
        "dev_id": case_id,
        "candidates": [
            {"chunk_id": "c1", "selected_rank": 1, "reranker_score": 0.9},
            {"chunk_id": "c3", "selected_rank": 2, "reranker_score": 0.8},
            {"chunk_id": "c4", "selected_rank": 3, "reranker_score": 0.7},
            {"chunk_id": "c2", "selected_rank": 4, "reranker_score": 0.6},
        ],
    }


class RequirementRerankerTest(unittest.TestCase):
    def test_requirement_text_is_subject_plus_relation_only(self) -> None:
        requirement = _enumeration("x")["requirements"][0]
        self.assertEqual(requirement_text(requirement), "상품 가격")

    def test_model_pairs_do_not_contain_gold_ids(self) -> None:
        case = {
            "case_id": "x",
            "requirements": _enumeration("x")["requirements"],
            "candidates": [
                {
                    "chunk_id": "c1",
                    "original_rank": 1,
                    "question_reranker_score": 0.1,
                }
            ],
        }
        requests = prepare_model_pairs([case], [_chunk("c1")])
        serialized = repr(requests)
        self.assertNotIn("evidence_group", serialized)
        self.assertNotIn("acceptable_chunk", serialized)

    def test_build_cases_requires_exact_population(self) -> None:
        with self.assertRaisesRegex(RuntimeError, r"32\+63"):
            build_cases(
                [_gold("x", [["c1"]])],
                [],
                [_enumeration("x")],
                [_candidates("x")],
                [],
                [_chunk(name) for name in ("c1", "c2", "c3", "c4")],
            )

    def test_requirement_union_can_recover_second_group(self) -> None:
        case = {
            "case_id": "x",
            "dataset": "fixture",
            "question": "상품 가격과 삭제일을 알려줘",
            "source_ids": ["dnf_monthly_item"],
            "gold_answerability": "true",
            "evidence_groups": _gold("x", [["c1"], ["c2"]])["evidence_groups"],
            "requirements": _enumeration("x")["requirements"],
            "candidates": [
                {
                    "chunk_id": row["chunk_id"],
                    "original_rank": row["selected_rank"],
                    "question_reranker_score": row["reranker_score"],
                }
                for row in _candidates("x")["candidates"]
            ],
        }
        requests = prepare_model_pairs(
            [case], [_chunk(name) for name in ("c1", "c2", "c3", "c4")]
        )
        requests[0]["scores"] = [0.9, 0.2, 0.1, 0.0]
        requests[1]["scores"] = [0.1, 0.2, 0.0, 0.9]
        scored = attach_requirement_scores([case], requests)
        rows = evaluate_rows([case], scored)
        self.assertFalse(rows[0]["baseline"]["all_groups_covered"])
        self.assertTrue(rows[0]["requirement_aware"]["all_groups_covered"])
        metrics = aggregate(rows)
        self.assertEqual(
            metrics["comparison"]["all_groups_question_improvement_count"], 1
        )
        self.assertTrue(gate(metrics)["pass"])

    def test_retrieval_bound_group_is_excluded_from_gate(self) -> None:
        case = {
            "case_id": "x",
            "dataset": "fixture",
            "question": "가격",
            "source_ids": [],
            "gold_answerability": "true",
            "evidence_groups": _gold("x", [["missing"]])["evidence_groups"],
            "requirements": _enumeration("x")["requirements"][:1],
            "candidates": [
                {
                    "chunk_id": "c1",
                    "original_rank": 1,
                    "question_reranker_score": 0.9,
                }
            ],
        }
        requests = prepare_model_pairs([case], [_chunk("c1")])
        requests[0]["scores"] = [0.8]
        rows = evaluate_rows([case], attach_requirement_scores([case], requests))
        metrics = aggregate(rows)
        self.assertEqual(metrics["retrieval_bound_question_count"], 1)
        self.assertEqual(metrics["question_gate_eligible_count"], 0)


if __name__ == "__main__":
    unittest.main()
