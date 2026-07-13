from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compare_partial_controlled_arm import (  # noqa: E402
    build_comparison,
    compare_requirements,
)


def generation_report(eval_id: str = "e1") -> dict:
    return {
        "rows": 1,
        "eval_set": "same.jsonl",
        "persist_dir": "index",
        "embedding_model_name": "BAAI/bge-m3",
        "rank_mode": "hybrid",
        "top_k": 3,
        "candidate_k": 100,
        "max_doc_chars": 900,
        "max_new_tokens": 256,
        "instruction_mode": "legacy",
        "seed": 42,
        "deterministic": True,
        "reranker_model": None,
        "rerank_candidates": 20,
        "reranker_max_length": 512,
        "summary": {
            "retrieval_expected_hit_rate": 1.0,
            "avg_generation_latency_sec": 1.0,
        },
        "details": [
            {
                "eval_id": eval_id,
                "retrieved_chunk_ids": ["c1", "c2", "c3"],
                "retrieval_expected_hit": True,
            }
        ],
    }


def quality_report(partial_success: int = 0) -> dict:
    return {
        "summary": {
            "answerable_rows": 2,
            "exact_citation_set_match_rate": 0.5,
            "evidence_token_recall_in_answer_mean": 0.5,
            "partial_rows": 1,
            "partial_joint_success_rate": float(partial_success),
            "false_rows": 1,
            "false_joint_correct_rate": 1.0,
            "safety_false_rows": 1,
            "unsafe_answer_rate_on_safety_false": 0.0,
        }
    }


def requirement_report(answered_cited: int, joint: int) -> dict:
    return {
        "counts": {
            "grounded_slots_answered": answered_cited,
            "grounded_slots_answered_and_cited": answered_cited,
            "grounded_slots_over_refused": 1,
            "unsupported_slots_abstained": 1,
            "unsupported_slots_over_answered": 0,
            "unsupported_slots_omitted": 0,
            "partial_requirement_joint_success": joint,
        },
        "details": [
            {
                "eval_id": "p1",
                "partial_requirement_joint_success": bool(joint),
                "failure_types": [] if joint else ["grounded_slot_missing"],
            }
        ],
    }


class ComparePartialControlledArmTests(unittest.TestCase):
    def test_requirement_comparison_reports_recovery(self) -> None:
        result = compare_requirements(requirement_report(0, 0), requirement_report(1, 1))
        self.assertEqual(result["recovered_joint_rows"], ["p1"])
        self.assertEqual(result["counts"]["grounded_slots_answered_and_cited"]["delta"], 1)

    def test_all_gates_pass_for_controlled_improvement(self) -> None:
        baseline_reports = {name: generation_report(name) for name in ("domain", "official", "fresh_dev", "human_partial")}
        candidate_reports = deepcopy(baseline_reports)
        baseline_quality = {name: quality_report(0) for name in baseline_reports}
        candidate_quality = {name: quality_report(0) for name in baseline_reports}
        candidate_quality["fresh_dev"] = quality_report(1)
        report = build_comparison(
            baseline_reports,
            baseline_quality,
            candidate_reports,
            candidate_quality,
            requirement_report(0, 0),
            requirement_report(1, 1),
        )
        self.assertTrue(report["all_promotion_gates_passed"])
        self.assertEqual(report["status"], "eligible_for_blind")

    def test_retrieval_change_blocks_promotion(self) -> None:
        baseline_reports = {name: generation_report(name) for name in ("domain", "official", "fresh_dev", "human_partial")}
        candidate_reports = deepcopy(baseline_reports)
        candidate_reports["domain"]["details"][0]["retrieved_chunk_ids"] = ["other"]
        quality = {name: quality_report(1) for name in baseline_reports}
        report = build_comparison(
            baseline_reports,
            quality,
            candidate_reports,
            quality,
            requirement_report(0, 0),
            requirement_report(1, 1),
        )
        self.assertFalse(report["all_promotion_gates_passed"])
        self.assertFalse(report["datasets"]["domain"]["retrieval_rows_invariant"])


if __name__ == "__main__":
    unittest.main()
