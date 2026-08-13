from __future__ import annotations

import unittest
from pathlib import Path

from src.v3.build_bm25 import build_bm25_index
from src.v3.build_corpus import file_sha256
from src.v3.question_decomposer import (
    DEFAULT_BM25_INDEX,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_CONTRACT,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_OVERLAY,
    DEFAULT_ROUTER_CASES,
    DEFAULT_ROUTER_MANIFEST,
    DEFAULT_ROUTER_SOURCE,
    DEFAULT_SCHEMA_SOURCE,
    apply_parent_source_hints,
    decompose_question,
    freeze_question_decomposition,
)
from src.v3.schemas import (
    DECOMPOSED_SUBQUESTION_REQUIRED_FIELDS,
    QUESTION_DECOMPOSITION_REQUIRED_FIELDS,
)


class QuestionDecomposerRuleTest(unittest.TestCase):
    def test_month_pair_restores_historical_year(self) -> None:
        result = decompose_question(
            "parent_month",
            "7월과 6월 스페셜 클론 레어 아바타 이달의 아이템은 각각 언제 삭제돼?",
            as_of="2026-07-18",
        )
        self.assertEqual(set(result), set(QUESTION_DECOMPOSITION_REQUIRED_FIELDS))
        self.assertEqual(result["strategy"], "month_pair")
        self.assertEqual(
            [row["time_hint"] for row in result["subquestions"]],
            ["current", "historical"],
        )
        self.assertIn("2026년 6월 당시", result["subquestions"][1]["question"])
        self.assertTrue(
            all(
                set(row) == set(DECOMPOSED_SUBQUESTION_REQUIRED_FIELDS)
                for row in result["subquestions"]
            )
        )

    def test_shared_attribute_is_split_between_left_and_right_items(self) -> None:
        result = decompose_question(
            "parent_shop",
            "트로피컬 바캉스 패키지와 아라드 패스 2026 시즌3의 판매·진행 종료 시점을 비교해줘.",
        )
        self.assertEqual(result["strategy"], "shared_attribute_comparison")
        self.assertEqual(
            [row["question"] for row in result["subquestions"]],
            [
                "트로피컬 바캉스 패키지의 판매 종료 시점은?",
                "아라드 패스 2026 시즌3의 진행 종료 시점은?",
            ],
        )

    def test_paired_clauses_remain_independently_answerable(self) -> None:
        result = decompose_question(
            "parent_policy",
            "ID 탈퇴 취소 기한과 이용제한 이의신청 근거 데이터 보관기간을 각각 알려줘.",
        )
        self.assertEqual(result["strategy"], "paired_clauses")
        self.assertEqual(
            [row["question"] for row in result["subquestions"]],
            ["ID 탈퇴 취소 기한은?", "이용제한 이의신청 근거 데이터 보관기간은?"],
        )

    def test_unsupported_pattern_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            decompose_question("parent", "복잡한 질문을 적당히 나눠줘.")
        with self.assertRaises(RuntimeError):
            decompose_question("parent", "")


class ParentSourceHintTest(unittest.TestCase):
    def test_two_parent_sources_are_assigned_by_child_affinity(self) -> None:
        documents = [
            {
                "document_id": "faq_doc",
                "canonical_url": "https://example.test/faq",
                "title": "ID 탈퇴 취소 FAQ",
            },
            {
                "document_id": "policy_doc",
                "canonical_url": "https://example.test/policy",
                "title": "운영정책 이용제한 이의신청",
            },
        ]
        chunks = [
            {
                "chunk_id": "faq_chunk",
                "parent_document_id": "faq_doc",
                "retrieval_text": "ID 탈퇴 취소 기한 7일 FAQ",
                "source_id": "dnf_faq",
                "source_kind": "faq",
                "status": "current",
                "default_exposure": True,
                "review_required": False,
                "offset_source": "dom_text",
                "valid_from": None,
                "valid_to": None,
            },
            {
                "chunk_id": "policy_chunk",
                "parent_document_id": "policy_doc",
                "retrieval_text": "운영정책 이용제한 이의신청 데이터 보관기간",
                "source_id": "dnf_account_policy",
                "source_kind": "account_policy",
                "status": "current",
                "default_exposure": True,
                "review_required": False,
                "offset_source": "dom_text",
                "valid_from": None,
                "valid_to": None,
            },
        ]
        index = build_bm25_index(chunks, documents)
        decomposition = decompose_question(
            "parent",
            "ID 탈퇴 취소 기한과 이용제한 이의신청 데이터 보관기간을 각각 알려줘.",
        )
        hinted = apply_parent_source_hints(
            decomposition,
            {"source_ids": ["dnf_account_policy", "dnf_faq"]},
            index,
        )
        self.assertEqual(
            [row["source_hint"] for row in hinted["subquestions"]],
            ["dnf_faq", "dnf_account_policy"],
        )
        self.assertTrue(hinted["subquestions"][0]["question"].startswith("FAQ 기준으로"))
        self.assertTrue(
            hinted["subquestions"][1]["question"].startswith("운영정책 기준으로")
        )


def test_actual_adaptive_pilot_refreezes_deterministically(tmp_path: Path) -> None:
    kwargs = {
        "root": Path.cwd(),
        "artifact_root": tmp_path,
        "documents_path": DEFAULT_DOCUMENTS,
        "chunks_path": DEFAULT_CHUNKS,
        "bm25_index_path": DEFAULT_BM25_INDEX,
        "overlay_path": DEFAULT_OVERLAY,
        "dev_set_path": DEFAULT_DEV_SET,
        "router_cases_path": DEFAULT_ROUTER_CASES,
        "router_manifest_path": DEFAULT_ROUTER_MANIFEST,
        "builder_source_path": DEFAULT_BUILDER_SOURCE,
        "router_source_path": DEFAULT_ROUTER_SOURCE,
        "schema_source_path": DEFAULT_SCHEMA_SOURCE,
        "contract_path": DEFAULT_CONTRACT,
    }
    first = freeze_question_decomposition(**kwargs)
    second = freeze_question_decomposition(**kwargs)
    assert first == second
    for key in ("cases", "manifest", "report", "report_markdown"):
        assert file_sha256(Path(first[f"{key}_path"])) == first[f"{key}_sha256"]
    assert all(first["gates"].values())
    assert first["metrics"]["evidence_group_hits_at_10"] == 8
    assert first["decisions"]["deterministic_question_decomposition"] == "GO"
    assert first["decisions"]["child_hybrid_retrieval"] == "NO-GO"


if __name__ == "__main__":
    unittest.main()
