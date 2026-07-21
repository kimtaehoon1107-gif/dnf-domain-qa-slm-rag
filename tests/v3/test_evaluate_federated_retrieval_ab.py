from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.v3.evaluate_federated_retrieval_ab import (
    apply_candidate_hygiene,
    classify_failure,
    evaluate_gate,
    federated_policy_from_frozen,
    rrf_fuse_source_hits,
    temporal_safety_metrics,
)


def _hit(
    chunk_id: str,
    parent_id: str,
    *,
    source_id: str = "dnf_notice",
    score: float = 1.0,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": parent_id,
        "source_id": source_id,
        "source_kind": "general_notice",
        "status": "current",
        "default_exposure": True,
        "valid_from": None,
        "valid_to": None,
        "base_hybrid_rank": 1,
        "base_hybrid_score": score,
        "guardrail_injected": False,
    }


class FederatedRetrievalABTest(unittest.TestCase):
    def test_federated_policy_removes_only_source_and_tightens_current_mode(self) -> None:
        policy = federated_policy_from_frozen(
            {
                "default_exposure_only": True,
                "allowed_statuses": ["current", "upcoming"],
                "include_review_required": False,
                "as_of": "2026-07-19",
                "source_ids": ["dnf_notice"],
            }
        )
        self.assertIsNotNone(policy)
        self.assertIsNone(policy.source_ids)
        self.assertEqual(policy.allowed_statuses, ("current", "active"))
        self.assertTrue(policy.default_exposure_only)
        self.assertEqual(policy.as_of, "2026-07-19")

    def test_hygiene_deduplicates_content_caps_parent_and_filters_policy_revision(self) -> None:
        artifacts = SimpleNamespace(
            documents_by_id={
                "p1": {"content_hash": "same"},
                "p2": {"content_hash": "same"},
                "p3": {"content_hash": "three"},
                "policy-old": {"content_hash": "policy-old"},
            }
        )
        hits = [
            _hit("c1", "p1"),
            _hit("c2", "p1"),
            _hit("c3", "p1"),
            _hit("c4", "p2"),
            _hit("c5", "p3"),
            _hit("c6", "policy-old", source_id="dnf_account_policy"),
        ]
        kept, counters = apply_candidate_hygiene(
            hits,
            artifacts,
            allowed_account_policy_document_ids={"policy-current"},
        )
        self.assertEqual([row["chunk_id"] for row in kept], ["c1", "c2", "c5"])
        self.assertEqual(counters["parent_cap_filtered"], 1)
        self.assertEqual(counters["content_hash_deduplicated"], 1)
        self.assertEqual(counters["policy_revision_filtered"], 1)

    def test_rrf_uses_rank_not_raw_cross_source_score(self) -> None:
        fused = rrf_fuse_source_hits(
            {
                "dnf_notice": [
                    _hit("notice-1", "pn", score=0.01),
                    _hit("notice-2", "pn2", score=999.0),
                ],
                "dnf_update": [_hit("update-1", "pu", score=5000.0)],
            }
        )
        first_rank_ids = {row["chunk_id"] for row in fused[:2]}
        self.assertEqual(first_rank_ids, {"notice-1", "update-1"})
        self.assertGreater(fused[0]["federated_rrf_score"], fused[2]["federated_rrf_score"])

    def test_failure_taxonomy_uses_earliest_stage(self) -> None:
        chunks = {
            "gold": {"parent_document_id": "p-gold"},
            "sibling": {"parent_document_id": "p-gold"},
            "other": {"parent_document_id": "p-other"},
        }
        groups = [{"group_id": "g1", "acceptable_chunk_ids": ["gold"]}]
        reqs = [{"requirement_id": "r1"}]
        self.assertEqual(
            classify_failure(
                requirements=[],
                evidence_groups=groups,
                candidate_ids=set(),
                cited_ids=set(),
                eligible_ids={"gold"},
                chunks_by_id=chunks,
            ),
            "ENUM_MISS",
        )
        self.assertEqual(
            classify_failure(
                requirements=reqs,
                evidence_groups=groups,
                candidate_ids=set(),
                cited_ids=set(),
                eligible_ids=set(),
                chunks_by_id=chunks,
            ),
            "SOURCE_SCOPE_MISS",
        )
        self.assertEqual(
            classify_failure(
                requirements=reqs,
                evidence_groups=groups,
                candidate_ids={"other"},
                cited_ids={"other"},
                eligible_ids={"gold"},
                chunks_by_id=chunks,
            ),
            "RETRIEVAL_MISS",
        )
        self.assertEqual(
            classify_failure(
                requirements=reqs,
                evidence_groups=groups,
                candidate_ids={"gold", "sibling"},
                cited_ids={"sibling"},
                eligible_ids={"gold"},
                chunks_by_id=chunks,
            ),
            "ATTRIBUTE_MISMATCH",
        )
        self.assertEqual(
            classify_failure(
                requirements=reqs,
                evidence_groups=groups,
                candidate_ids={"gold", "other"},
                cited_ids={"other"},
                eligible_ids={"gold"},
                chunks_by_id=chunks,
            ),
            "ASSEMBLY_MISS",
        )
        self.assertIsNone(
            classify_failure(
                requirements=reqs,
                evidence_groups=groups,
                candidate_ids={"gold"},
                cited_ids={"gold"},
                eligible_ids={"gold"},
                chunks_by_id=chunks,
            )
        )

    def test_gate_requires_recovery_and_all_safety_guards(self) -> None:
        baseline = {"answerable": {"grounded_answer": {"successes": 73}}}
        candidate = {
            "answerable": {
                "grounded_answer": {"successes": 74},
                "new_false_full_case_count": 0,
            },
            "reject": {"correct_abstain_or_reject": {"successes": 11}},
            "realtime": {
                "safe_abstain": {"successes": 2},
                "static_exposure": {"successes": 0},
            },
        }
        baseline_selection = {
            "mean_spans_per_supported_requirement": 3.0,
            "question_level_nonacceptable_unique_citation_count": 10,
        }
        candidate_selection = {
            "mean_spans_per_supported_requirement": 2.5,
            "question_level_nonacceptable_unique_citation_count": 9,
            "span_validity": {"invalid": 0},
        }
        retrieval = {"false_full_to_grounded_recovery": {"successes": 1}}
        cross = {"same_parent_not_decomposed": {"successes": 7}}
        safety = {"violation_count": 0}
        self.assertTrue(
            evaluate_gate(
                baseline,
                candidate,
                baseline_selection,
                candidate_selection,
                retrieval,
                cross,
                safety,
            )["pass"]
        )
        safety["violation_count"] = 1
        self.assertFalse(
            evaluate_gate(
                baseline,
                candidate,
                baseline_selection,
                candidate_selection,
                retrieval,
                cross,
                safety,
            )["pass"]
        )

    def test_temporal_safety_maps_assembler_requirement_id(self) -> None:
        retrieval = [
            {
                "case_id": "case-1",
                "requirement_index": 1,
                "requirement_id": "requirement_1",
                "federated_policy": {
                    "default_exposure_only": True,
                    "allowed_statuses": ["current", "active"],
                    "include_review_required": False,
                    "as_of": "2026-07-19",
                    "source_ids": None,
                },
                "allowed_account_policy_document_ids": ["policy-current"],
            }
        ]
        assembled = [
            {
                "case_id": "case-1",
                "decisions": [
                    {
                        "requirement_id": "requirement_1",
                        "status": "supported_exact",
                        "spans": [{"chunk_id": "chunk-1"}],
                    }
                ],
            }
        ]
        chunks = [
            {
                "chunk_id": "chunk-1",
                "parent_document_id": "parent-1",
                "source_id": "dnf_notice",
                "status": "current",
                "default_exposure": True,
                "review_required": False,
                "valid_from": "2026-01-01",
                "valid_to": None,
            }
        ]
        metrics = temporal_safety_metrics(
            retrieval, assembled, chunks, arm="federated_global"
        )
        self.assertEqual(metrics["violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
