from __future__ import annotations

import inspect
import unittest

from src.v3.requirement_slot_claim_coverage import (
    MISSING_SLOT_TEMPLATE,
    build_requirement_slot_response,
    enumerate_requirement_slots,
    match_slots_within_one_parent,
)
from src.v3.run_unified_runtime import PARTIAL_DISCLAIMER


def _chunk(chunk_id: str, text: str, rank: int = 1) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_document_id": "doc-1",
        "source_id": "dnf_faq",
        "source_kind": "faq",
        "retrieval_rank": rank,
        "display_text": text,
        "status": "current",
        "default_exposure": True,
    }


def _document() -> dict:
    return {
        "document_id": "doc-1",
        "source_id": "dnf_faq",
        "source_kind": "faq",
        "revision_id": "revision-1",
        "status": "current",
        "default_exposure": True,
    }


def _route(source_id: str = "dnf_faq") -> dict:
    return {
        "route_action": "retrieve",
        "time_scope": "current",
        "source_ids": [source_id],
        "source_kinds": ["faq"],
    }


class RequirementSlotClaimCoverageTest(unittest.TestCase):
    question = "상품의 구매 조건과 사용 절차를 설명해줘."

    def test_signal_a_targets_are_reused_as_slots(self) -> None:
        slots = enumerate_requirement_slots(self.question)

        self.assertEqual(len(slots), 2)
        self.assertTrue(all(row["slot_id"].startswith("slot_sha256_") for row in slots))

    def test_clause_only_overenumeration_is_filtered_without_keywords(self) -> None:
        slots = enumerate_requirement_slots("재료를 어디서 얻고 어떻게 사용해?")

        self.assertEqual(slots, [])

    def test_full_slot_coverage_builds_one_exact_claim_per_slot(self) -> None:
        candidates = [
            _chunk("chunk-1", "상품 구매 조건은 계정 인증을 완료하는 것입니다."),
            _chunk("chunk-2", "상품 사용 절차는 메뉴에서 상품을 선택하는 것입니다.", 2),
        ]

        result = build_requirement_slot_response(
            case_id="case-1",
            question=self.question,
            answerability="true",
            route=_route(),
            candidates=candidates,
            baseline_response={"citation_chunk_ids": [], "claims": []},
            documents_by_id={"doc-1": _document()},
            current_policy_document_id=None,
            overlap_threshold=0.5,
        )

        self.assertEqual(result["slot_coverage"]["coverage_state"], "full")
        self.assertEqual(len(result["response"]["claims"]), 2)
        self.assertEqual(
            set(result["response"]["citation_chunk_ids"]),
            {"chunk-1", "chunk-2"},
        )
        self.assertTrue(all(row["verified"] for row in result["verification_results"]))
        for claim in result["response"]["claims"]:
            chunk = next(row for row in candidates if row["chunk_id"] == claim["citation_chunk_id"])
            self.assertIn(claim["claim_text"], chunk["display_text"])

    def test_missing_slot_is_disclosed_without_false_citation(self) -> None:
        result = build_requirement_slot_response(
            case_id="case-1",
            question=self.question,
            answerability="partial",
            route=_route(),
            candidates=[
                _chunk("chunk-1", "상품 구매 조건은 계정 인증을 완료하는 것입니다.")
            ],
            baseline_response={"citation_chunk_ids": [], "claims": []},
            documents_by_id={"doc-1": _document()},
            current_policy_document_id=None,
            overlap_threshold=0.5,
        )

        self.assertEqual(result["slot_coverage"]["coverage_state"], "partial")
        self.assertEqual(len(result["slot_coverage"]["missing_slots"]), 1)
        self.assertEqual(len(result["response"]["citation_chunk_ids"]), 1)
        self.assertTrue(result["response"]["rendered_answer"].startswith(PARTIAL_DISCLAIMER))
        self.assertIn(MISSING_SLOT_TEMPLATE, result["response"]["rendered_answer"])

    def test_single_slot_is_an_exact_passthrough(self) -> None:
        baseline = {
            "runtime_status": "success",
            "citation_chunk_ids": ["old"],
            "claims": [{"claim_text": "기존 출력"}],
        }

        result = build_requirement_slot_response(
            case_id="case-1",
            question="상품을 사용하는 방법을 알려줘.",
            answerability="true",
            route=_route(),
            candidates=[],
            baseline_response=baseline,
            documents_by_id={},
            current_policy_document_id=None,
            overlap_threshold=0.5,
        )

        self.assertEqual(result["mode"], "single_slot_passthrough")
        self.assertEqual(result["response"], baseline)
        self.assertIsNot(result["response"], baseline)

    def test_verification_failure_exposes_no_citation(self) -> None:
        result = build_requirement_slot_response(
            case_id="case-1",
            question=self.question,
            answerability="true",
            route=_route("dnf_notice"),
            candidates=[
                _chunk("chunk-1", "상품 구매 조건은 계정 인증을 완료하는 것입니다."),
                _chunk("chunk-2", "상품 사용 절차는 메뉴에서 상품을 선택하는 것입니다.", 2),
            ],
            baseline_response={"citation_chunk_ids": ["old"]},
            documents_by_id={"doc-1": _document()},
            current_policy_document_id=None,
            overlap_threshold=0.5,
        )

        self.assertEqual(result["mode"], "verification_failed_passthrough")
        self.assertEqual(result["response"]["citation_chunk_ids"], ["old"])

    def test_parent_selection_never_unions_cross_parent_slots(self) -> None:
        second = _chunk(
            "chunk-2", "상품 사용 절차는 메뉴에서 상품을 선택하는 것입니다.", 2
        )
        second["parent_document_id"] = "doc-2"

        coverage = match_slots_within_one_parent(
            self.question,
            [
                _chunk("chunk-1", "상품 구매 조건은 계정 인증을 완료하는 것입니다."),
                second,
            ],
            overlap_threshold=0.5,
        )

        self.assertEqual(coverage["coverage_state"], "partial")
        self.assertEqual(len(coverage["matches"]), 1)

    def test_runtime_signature_cannot_accept_gold_ids(self) -> None:
        parameters = set(inspect.signature(build_requirement_slot_response).parameters)

        self.assertNotIn("gold_chunk_ids", parameters)
        self.assertNotIn("gold_document_ids", parameters)
        self.assertNotIn("acceptable_chunk_ids", parameters)
        self.assertNotIn("evidence_groups", parameters)


if __name__ == "__main__":
    unittest.main()
