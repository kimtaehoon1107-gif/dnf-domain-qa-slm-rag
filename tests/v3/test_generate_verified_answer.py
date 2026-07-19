from __future__ import annotations

import unittest
from pathlib import Path

from src.v3.build_corpus import file_sha256
from src.v3.generate_verified_answer import (
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CONTRACT,
    DEFAULT_DECOMPOSED_CASES,
    DEFAULT_DECOMPOSED_MANIFEST,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_RETRIEVAL_SOURCE,
    DEFAULT_SELECTOR_SOURCE,
    build_answer_plan,
    extract_relevant_quote,
    freeze_extractive_generator,
    verify_answer_plan,
)


FROZEN_CASES = Path(
    "data/v3/generation/"
    "extractive_answer_cases_"
    "dca2d88deda9146058a0aaa77ef42fecd1616ed6f257eabbc18848127dacc199.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/generation/"
    "extractive_answer_manifest_"
    "99ab5c4249e3d86f4b531cf85869fcc6766679ab8928c9d657af2e07397ae784.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "extractive_generator_verifier_"
    "ce45dfddff9f1dbaec2271a4e3923d2a3ebf7ac6599a27d92b6298f57323c82b.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "extractive_generator_verifier_"
    "c7f8ec2156a4d01f37cf8c94c93e54fce660abc473b3fa892ebb924a79f071db.md"
)


class ExtractiveClaimTest(unittest.TestCase):
    def test_adjacent_conditions_remain_one_exact_quote(self) -> None:
        evidence = (
            "복구가 어려운 경우입니다.\n"
            "2) 해킹 피해 발생일로부터 60일이 경과한 경우\n"
            "3) 연 2회를 초과하여 복구 신청한 경우 (OTP 이용 시 제한 없음)\n"
            "자세한 사항은 운영정책을 참고하세요."
        )
        quote = extract_relevant_quote(
            "해킹 피해 복구의 60일·연 2회 조건은?", evidence
        )

        self.assertIn("60일", quote)
        self.assertIn("연 2회", quote)
        self.assertIn(quote, evidence)

    def test_field_label_and_value_are_kept_together(self) -> None:
        evidence = "상품명\n스페셜 상자\n삭제기일\n2026년 08월 13일 06시 일괄삭제\n바로가기"
        quote = extract_relevant_quote("스페셜 상자는 언제 삭제돼?", evidence)

        self.assertIn("2026년 08월 13일", quote)
        self.assertIn(quote, evidence)

    def test_sale_end_prefers_sale_window_over_generic_product_sentence(self) -> None:
        evidence = (
            "모든 상품은 판매 시점에 업데이트된 캐릭터에 적용됩니다.\n"
            "트로피컬 바캉스 패키지\n"
            "2026년 6월 4일 점검 후부터 2026년 8월 27일 점검 전까지 "
            "세라샵에서 만나보실 수 있습니다."
        )
        quote = extract_relevant_quote(
            "트로피컬 바캉스 패키지의 판매 종료 시점은?", evidence
        )

        self.assertIn("2026년 8월 27일", quote)
        self.assertIn("전까지", quote)
        self.assertNotIn("모든 상품", quote)

    def test_delete_question_does_not_return_sale_period(self) -> None:
        evidence = (
            "판매기간: 06.25 ~ 07.30\n"
            "[7월]스페셜 클론 레어 아바타 풀세트 상자\n"
            "삭제기일\n"
            "2026년 08월 13일 06시 일괄삭제"
        )
        quote = extract_relevant_quote(
            "7월 스페셜 클론 레어 아바타는 언제 삭제돼?", evidence
        )

        self.assertIn("2026년 08월 13일", quote)
        self.assertIn("삭제", quote)

    def test_loss_type_question_prefers_direct_impossibility_statement(self) -> None:
        evidence = (
            "게임 서비스 기술상의 오류가 아닌 상황의 피해, 고의, 이용자간 분쟁에 "
            "의한 손실은 복구가 불가능합니다.\n"
            "① 고객 PC 결함\n"
            "② 공지 미확인 피해\n"
            "③ 고의에 의한 손실\n"
            "④ 사용기간 경과 아이템은 복구가 가능하지 않습니다."
        )
        quote = extract_relevant_quote(
            "일반 복구가 불가능한 손실 유형은?", evidence
        )

        self.assertIn("이용자간 분쟁", quote)
        self.assertIn("복구가 불가능", quote)

    def test_item_question_does_not_narrow_to_one_component(self) -> None:
        evidence = (
            "획득한 모든 아이템은 2026년 7월 9일 06시 일괄 삭제됩니다.\n"
            "획득한 엠블렘은 2026년 7월 9일 06시에 일괄 삭제됩니다."
        )
        quote = extract_relevant_quote(
            "6월 이달의 아이템은 언제 삭제돼?", evidence
        )

        self.assertIn("모든 아이템", quote)
        self.assertNotIn("엠블렘", quote)


def _selected_evidence(
    *,
    chunk_id: str = "chunk_current",
    document_id: str = "doc_current",
    status: str = "current",
    default_exposure: bool = True,
    display_text: str = "복구 신청은 90일 이내에 가능합니다.",
) -> dict[str, object]:
    return {
        "selector_version": "fixture",
        "selected_rank": 1,
        "retrieval_rank": 1,
        "chunk_id": chunk_id,
        "parent_document_id": document_id,
        "source_id": "dnf_account_policy",
        "source_kind": "account_policy",
        "status": status,
        "default_exposure": default_exposure,
        "review_required": False,
        "heading_path": [],
        "chunk_type": "section",
        "display_text": display_text,
        "query_token_coverage": 1.0,
        "selector_score": 1.0,
        "selection_reason": "fixture",
        "guardrail_injected": False,
    }


def _case(selected: dict[str, object]) -> dict[str, object]:
    return {
        "case_id": "parent",
        "parent_question": "복구 신청 기한은?",
        "children": [
            {
                "subquestion": {
                    "subquestion_id": "sub_1",
                    "ordinal": 1,
                    "question": "운영정책 기준으로 복구 신청 기한은?",
                    "relationship": "first_clause",
                    "time_hint": "inherit_parent",
                    "source_hint": "dnf_account_policy",
                },
                "route": {
                    "source_ids": ["dnf_account_policy"],
                    "source_kinds": ["account_policy"],
                    "time_scope": "current",
                },
                "temporal_resolution": {
                    "selected_document_id": "doc_current",
                    "selected_revision_id": "rev_current",
                },
                "temporal_window": None,
                "selected_evidence": [selected],
            }
        ],
        "merge": {
            "merge_status": "resolved_no_conflict",
            "merged_candidates": [{"chunk_id": selected["chunk_id"]}],
        },
    }


class AnswerPlanVerifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = {
            "doc_current": {
                "document_id": "doc_current",
                "lineage_id": "policy",
                "revision_id": "rev_current",
                "status": "current",
                "default_exposure": True,
                "valid_from": "2026-06-01",
                "valid_to": None,
            }
        }

    def test_plan_binds_claim_to_selected_chunk_and_verifies(self) -> None:
        case = _case(_selected_evidence())
        plan = build_answer_plan(case, self.documents)
        verification = verify_answer_plan(plan, case, self.documents)

        self.assertEqual(len(plan["claims"]), 1)
        self.assertEqual(plan["claims"][0]["citation_chunk_id"], "chunk_current")
        self.assertIn(plan["claims"][0]["claim_text"], plan["rendered_answer"])
        self.assertTrue(verification["verified"])
        self.assertTrue(all(verification["gates"].values()))

    def test_citation_outside_selected_evidence_fails_closed(self) -> None:
        case = _case(_selected_evidence())
        plan = build_answer_plan(case, self.documents)
        plan["claims"][0]["citation_chunk_id"] = "chunk_unknown"
        verification = verify_answer_plan(plan, case, self.documents)

        self.assertFalse(verification["verified"])
        self.assertFalse(verification["gates"]["citations_selected"])

    def test_current_claim_rejects_expired_non_default_document(self) -> None:
        selected = _selected_evidence(
            document_id="doc_old", status="expired", default_exposure=False
        )
        case = _case(selected)
        case["children"][0]["temporal_resolution"] = None
        documents = {
            "doc_old": {
                "document_id": "doc_old",
                "lineage_id": "policy",
                "revision_id": "rev_old",
                "status": "expired",
                "default_exposure": False,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
            }
        }
        plan = build_answer_plan(case, documents)
        verification = verify_answer_plan(plan, case, documents)

        self.assertFalse(verification["verified"])
        self.assertFalse(verification["gates"]["temporal_policy_valid"])


class ExtractiveGeneratorArtifactTest(unittest.TestCase):
    def test_actual_adaptive_pilot_refreezes_deterministically(self) -> None:
        kwargs = {
            "root": Path.cwd(),
            "documents_path": DEFAULT_DOCUMENTS,
            "dev_set_path": DEFAULT_DEV_SET,
            "decomposed_cases_path": DEFAULT_DECOMPOSED_CASES,
            "decomposed_manifest_path": DEFAULT_DECOMPOSED_MANIFEST,
            "builder_source_path": DEFAULT_BUILDER_SOURCE,
            "retrieval_source_path": DEFAULT_RETRIEVAL_SOURCE,
            "selector_source_path": DEFAULT_SELECTOR_SOURCE,
            "contract_path": DEFAULT_CONTRACT,
        }
        first = freeze_extractive_generator(**kwargs)
        second = freeze_extractive_generator(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["cases_sha256"], file_sha256(FROZEN_CASES))
        self.assertEqual(first["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(
            first["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD)
        )
        self.assertTrue(all(first["gates"].values()))
        self.assertEqual(first["metrics"]["verified_claims"], 8)
        self.assertEqual(
            first["decisions"]["schema_constrained_extractive_generator"], "GO"
        )
        self.assertEqual(
            first["decisions"]["deterministic_claim_verifier"], "GO"
        )


if __name__ == "__main__":
    unittest.main()
