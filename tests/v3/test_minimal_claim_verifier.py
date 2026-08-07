from __future__ import annotations

import unittest

from src.v3.minimal_claim_verifier import verify_minimal_claim_batch
from src.v3.minimal_structured_evidence import (
    build_structured_rows_by_coordinate,
)


def _fixture(title: str) -> tuple[dict, dict]:
    text = (
        f"# {title}\n"
        "| 상점판매가격 | 12,900 세라 |\n"
        "| 거래타입 | 교환가능 |"
    )
    chunk = {
        "chunk_id": "chunk-1",
        "parent_document_id": "document-1",
        "display_text": text,
    }
    start = text.index("| 상점판매가격")
    end = text.index("\n| 거래타입")
    unit = {
        "evidence_ref": "E1",
        "candidate_ref": "1",
        "chunk_id": "chunk-1",
        "parent_document_id": "document-1",
        "source_id": "dnf_seria_shop",
        "source_kind": "shop_product",
        "revision_id": "revision-1",
        "title": title,
        "context_text": f"# {title}",
        "start_char": start,
        "end_char": end,
        "text": text[start:end],
        "context_refs": [],
    }
    return chunk, unit


class MinimalClaimVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requirement = {
            "requirement_id": "price",
            "subject": "2026 DNF 폴리스 아바타 콤보 상자",
            "relation": "shop_price",
            "value_type": "currency",
        }

    def test_fixed_value_and_server_evidence_ref_pass(self) -> None:
        chunk, unit = _fixture(
            "2026 DNF 폴리스 아바타 콤보 상자"
        )
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "price",
                        "status": "supported",
                        "value_type": "currency",
                        "value": "12,900 세라",
                        "evidence_refs": ["E1"],
                    }
                ]
            },
            requirements=[self.requirement],
            question="2026 DNF 폴리스 아바타 콤보 상자 가격은?",
            as_of="2026-07-28",
            evidence_units_by_ref={"E1": unit},
            chunks_by_id={"chunk-1": chunk},
        )
        self.assertEqual(result["response_mode"], "full_answer")
        self.assertEqual(
            result["requirements"][0]["status"],
            "supported_exact",
        )
        self.assertEqual(
            result["requirements"][0]["citations"][0]["text"],
            "| 상점판매가격 | 12,900 세라 |",
        )

    def test_sibling_product_value_is_blocked(self) -> None:
        chunk, unit = _fixture(
            "2026 나비 무도회 아바타 콤보 상자"
        )
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "price",
                        "status": "supported",
                        "value_type": "currency",
                        "value": "12,900 세라",
                        "evidence_refs": ["E1"],
                    }
                ]
            },
            requirements=[self.requirement],
            question="2026 DNF 폴리스 아바타 콤보 상자 가격은?",
            as_of="2026-07-28",
            evidence_units_by_ref={"E1": unit},
            chunks_by_id={"chunk-1": chunk},
        )
        self.assertEqual(result["response_mode"], "abstain")
        verification = result["requirements"][0]["verification"]
        self.assertIn(
            "record_identity_failed",
            verification["failure_reasons"],
        )

    def test_unknown_evidence_ref_is_blocked(self) -> None:
        chunk, _ = _fixture(
            "2026 DNF 폴리스 아바타 콤보 상자"
        )
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "price",
                        "status": "supported",
                        "value_type": "currency",
                        "value": "12,900 세라",
                        "evidence_refs": ["E9"],
                    }
                ]
            },
            requirements=[self.requirement],
            question="2026 DNF 폴리스 아바타 콤보 상자 가격은?",
            as_of="2026-07-28",
            evidence_units_by_ref={},
            chunks_by_id={"chunk-1": chunk},
        )
        self.assertEqual(result["response_mode"], "abstain")
        self.assertIn(
            "evidence_ref_not_in_candidates",
            result["requirements"][0]["verification"]["failure_reasons"],
        )

    def test_requirement_id_rewrite_fails_closed(self) -> None:
        chunk, unit = _fixture(
            "2026 DNF 폴리스 아바타 콤보 상자"
        )
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "sale_period",
                        "status": "supported",
                        "value_type": "currency",
                        "value": "12,900 세라",
                        "evidence_refs": ["E1"],
                    }
                ]
            },
            requirements=[self.requirement],
            question="2026 DNF 폴리스 아바타 콤보 상자 가격은?",
            as_of="2026-07-28",
            evidence_units_by_ref={"E1": unit},
            chunks_by_id={"chunk-1": chunk},
        )
        self.assertEqual(result["response_mode"], "abstain")
        self.assertEqual(
            result["verification"]["batch_failure_reasons"],
            ["fixed_requirement_contract_mismatch"],
        )

    def test_wrong_policy_table_scope_is_blocked(self) -> None:
        text = "\n".join(
            (
                "[커뮤니티 이용제한]",
                "| 구분 | 1차 | 2차 |",
                (
                    "| 운영자, 직원을 사칭하는 내용 "
                    "| 게시물100일 등록제한 | 게시물1년 등록제한 |"
                ),
            )
        )
        row_text = text.splitlines()[-1]
        start = text.index(row_text)
        chunk = {
            "chunk_id": "chunk-policy",
            "display_text": text,
        }
        unit = {
            "evidence_ref": "E1",
            "chunk_id": "chunk-policy",
            "parent_document_id": "policy-2021",
            "source_id": "dnf_account_policy",
            "revision_id": "2021-01-21",
            "start_char": start,
            "end_char": start + len(row_text),
            "text": row_text,
            "context_text": "",
            "title": "운영정책",
            "context_refs": [],
        }
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "impersonation_first_penalty",
                        "status": "supported",
                        "value_type": "duration",
                        "value": "게시물100일 등록제한",
                        "evidence_refs": ["E1"],
                    }
                ]
            },
            requirements=[
                {
                    "requirement_id": "impersonation_first_penalty",
                    "subject": "운영자·직원 사칭",
                    "relation": "first_penalty",
                    "value_type": "duration",
                }
            ],
            question="운영자·직원 사칭의 1차 이용제한은?",
            as_of="2026-07-28",
            evidence_units_by_ref={"E1": unit},
            chunks_by_id={"chunk-policy": chunk},
            structured_rows_by_coordinate=(
                build_structured_rows_by_coordinate(
                    ["chunk-policy"],
                    chunks_by_id={"chunk-policy": chunk},
                )
            ),
        )
        self.assertEqual(result["response_mode"], "abstain")
        self.assertIn(
            "structured_row_binding_failed",
            result["requirements"][0]["verification"]["failure_reasons"],
        )

    def test_narrative_negative_boolean_is_supported(self) -> None:
        text = (
            "랭킹은 챌린지모드에서만 집계합니다. "
            "일반모드는 랭킹 집계와 무관합니다."
        )
        chunk = {
            "chunk_id": "chunk-narrative",
            "display_text": text,
        }
        unit = {
            "evidence_ref": "E1",
            "chunk_id": "chunk-narrative",
            "parent_document_id": "document-narrative",
            "source_id": "dnf_event",
            "source_kind": "event",
            "revision_id": "revision-narrative",
            "title": "트리니티",
            "context_text": "트리니티 일반모드",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "context_refs": [],
        }
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "normal_mode_counted",
                        "status": "supported",
                        "value_type": "boolean",
                        "value": False,
                        "evidence_refs": ["E1"],
                    }
                ]
            },
            requirements=[
                {
                    "requirement_id": "normal_mode_counted",
                    "subject": "트리니티 일반모드",
                    "relation": "ranked",
                    "value_type": "boolean",
                }
            ],
            question="트리니티 일반모드도 랭킹 집계에 포함됐어?",
            as_of="2026-07-28",
            evidence_units_by_ref={"E1": unit},
            chunks_by_id={"chunk-narrative": chunk},
        )
        self.assertEqual(result["response_mode"], "full_answer")
        self.assertEqual(
            result["requirements"][0]["verification"][
                "evidence_contract"
            ]["branch"],
            "narrative",
        )

    def test_product_unlimited_means_no_deletion_deadline(self) -> None:
        text = (
            "# [11월 이달의 아이템] : 시브의 보조장비 보주\n"
            "* 시브의 보조장비 보주는 기간 무제한 아이템입니다."
        )
        start = text.index("* 시브")
        chunk = {
            "chunk_id": "chunk-monthly",
            "display_text": text,
        }
        unit = {
            "evidence_ref": "E1",
            "chunk_id": "chunk-monthly",
            "parent_document_id": "document-monthly",
            "source_id": "dnf_monthly_item",
            "source_kind": "monthly_item",
            "revision_id": "revision-monthly",
            "title": "11월 이달의 아이템",
            "context_text": (
                "# [11월 이달의 아이템] : 시브의 보조장비 보주"
            ),
            "start_char": start,
            "end_char": len(text),
            "text": text[start:],
            "context_refs": [],
        }
        result = verify_minimal_claim_batch(
            {
                "requirements": [
                    {
                        "requirement_id": "has_deletion_deadline",
                        "status": "supported",
                        "value_type": "boolean",
                        "value": False,
                        "evidence_refs": ["E1"],
                    }
                ]
            },
            requirements=[
                {
                    "requirement_id": "has_deletion_deadline",
                    "subject": "2025년 11월 시브의 보조장비 보주",
                    "relation": "has_deletion_deadline",
                    "value_type": "boolean",
                }
            ],
            question=(
                "2025년 11월 시브의 보조장비 보주는 "
                "삭제 기한이 정해져 있었어?"
            ),
            as_of="2026-07-28",
            evidence_units_by_ref={"E1": unit},
            chunks_by_id={"chunk-monthly": chunk},
        )
        self.assertEqual(result["response_mode"], "full_answer")
        verification = result["requirements"][0]["verification"]
        self.assertEqual(
            verification["evidence_contract"]["branch"],
            "product_record",
        )
        self.assertEqual(
            verification["record_identity"]["state"],
            "matched",
        )

    def test_optional_atomic_proof_blocks_sibling_narrative_fact(self) -> None:
        text = "\n".join(
            (
                "## 큐브 버프 효과",
                "- 흑색 큐브 조각 : 30초 마다 무기에 암속성 부여",
                "- 흰색 큐브 조각 : 30초 마다 무기에 명속성 부여",
            )
        )
        evidence_text = text.splitlines()[-1]
        start = text.index(evidence_text)
        chunk = {
            "chunk_id": "chunk-cube",
            "parent_document_id": "document-cube",
            "display_text": text,
        }
        unit = {
            "evidence_ref": "E1",
            "chunk_id": "chunk-cube",
            "parent_document_id": "document-cube",
            "source_id": "dnf_game_guide",
            "source_kind": "game_guide",
            "revision_id": "revision-cube",
            "title": "큐브의 계약",
            "context_text": "## 큐브 버프 효과",
            "start_char": start,
            "end_char": start + len(evidence_text),
            "text": evidence_text,
            "context_refs": [],
        }
        requirement = {
            "requirement_id": "black_cube_attribute",
            "subject": "흑색 큐브 조각",
            "relation": "weapon_attribute",
            "value_type": "enum",
        }
        output = {
            "requirements": [
                {
                    "requirement_id": "black_cube_attribute",
                    "status": "supported",
                    "value_type": "enum",
                    "value": "명속성",
                    "evidence_refs": ["E1"],
                }
            ]
        }
        common = {
            "requirements": [requirement],
            "question": (
                "큐브의 계약에서 흑색 큐브 조각은 "
                "무기에 어떤 속성을 부여해?"
            ),
            "as_of": "2026-07-28",
            "evidence_units_by_ref": {"E1": unit},
            "chunks_by_id": {"chunk-cube": chunk},
            "profile": "v2",
        }

        baseline = verify_minimal_claim_batch(output, **common)
        guarded = verify_minimal_claim_batch(
            output,
            enable_atomic_proof=True,
            **common,
        )

        self.assertEqual(baseline["response_mode"], "full_answer")
        self.assertEqual(guarded["response_mode"], "abstain")
        verification = guarded["requirements"][0]["verification"]
        self.assertIn(
            "atomic_claim_proof_failed",
            verification["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
