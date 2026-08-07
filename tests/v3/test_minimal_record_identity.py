from __future__ import annotations

import unittest

from src.v3.minimal_record_identity import (
    assess_record_identity_sufficiency,
    evaluate_record_identity,
    explicit_record_constraints,
)


def _unit(
    title: str,
    *,
    parent: str = "document-1",
    source_id: str = "dnf_seria_shop",
    source_kind: str = "shop_product",
    context_text: str = "",
    text: str = "",
) -> dict:
    return {
        "title": title,
        "context_text": context_text,
        "text": text,
        "parent_document_id": parent,
        "revision_id": parent,
        "source_id": source_id,
        "source_kind": source_kind,
    }


class MinimalRecordIdentityTests(unittest.TestCase):
    def test_matching_shop_product_record_passes(self) -> None:
        requirement = {
            "subject": "2026 DNF 폴리스 아바타 콤보 상자",
            "relation": "included_boxes",
        }
        result = evaluate_record_identity(
            requirement,
            [_unit("2026 DNF 폴리스 아바타 콤보 상자")],
            question=(
                "2026 DNF 폴리스 아바타 콤보 상자의 가격과 "
                "구매 시 받는 두 상자는?"
            ),
        )
        self.assertEqual(result["state"], "matched")

    def test_sibling_shop_products_fail_even_when_both_are_selected(self) -> None:
        requirement = {
            "subject": "2026 DNF 폴리스 아바타 콤보 상자",
            "relation": "included_boxes",
        }
        result = evaluate_record_identity(
            requirement,
            [
                _unit(
                    "2026 나비 무도회 아바타 콤보 상자",
                    parent="document-butterfly",
                ),
                _unit(
                    "2026 아라드패스 웨딩 아바타 콤보 상자",
                    parent="document-wedding",
                ),
            ],
            question=(
                "2026 DNF 폴리스 아바타 콤보 상자의 가격과 "
                "구매 시 받는 두 상자는?"
            ),
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn("canonical_subject_mismatch", result["failures"])

    def test_monthly_record_requires_the_explicit_product_month(self) -> None:
        requirement = {
            "subject": "2026년 1월 해방의 열쇠 100개 상자",
            "relation": "deletion_at",
        }
        result = evaluate_record_identity(
            requirement,
            [
                _unit(
                    "2026년 이달의 아이템",
                    source_id="dnf_monthly_item",
                    source_kind="monthly_item",
                    context_text=(
                        "# [7월 이달의 아이템]\n"
                        "해방의 열쇠 100개 상자"
                    ),
                )
            ],
            question=(
                "2026년 1월 해방의 열쇠 100개 상자는 "
                "언제 삭제됐어?"
            ),
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn("explicit_month_mismatch", result["failures"])

    def test_matching_monthly_record_passes(self) -> None:
        requirement = {
            "subject": "2026년 1월 해방의 열쇠 100개 상자",
            "relation": "deletion_at",
        }
        result = evaluate_record_identity(
            requirement,
            [
                _unit(
                    "2026년 이달의 아이템",
                    source_id="dnf_monthly_item",
                    source_kind="monthly_item",
                    context_text=(
                        "# [1월 이달의 아이템]\n"
                        "해방의 열쇠 100개 상자"
                    ),
                )
            ],
            question=(
                "2026년 1월 해방의 열쇠 100개 상자는 "
                "언제 삭제됐어?"
            ),
        )
        self.assertEqual(result["state"], "matched")

    def test_mixed_correct_and_sibling_records_fail_closed(self) -> None:
        requirement = {
            "subject": "2026 DNF 폴리스 아바타 콤보 상자",
            "relation": "included_boxes",
        }
        result = evaluate_record_identity(
            requirement,
            [
                _unit(
                    "2026 DNF 폴리스 아바타 콤보 상자",
                    parent="document-police",
                ),
                _unit(
                    "2026 나비 무도회 아바타 콤보 상자",
                    parent="document-butterfly",
                ),
            ],
            question="2026 DNF 폴리스 아바타 콤보 상자 구성품은?",
        )
        self.assertEqual(result["state"], "mismatch")

    def test_non_product_claim_is_not_affected(self) -> None:
        result = evaluate_record_identity(
            {
                "subject": "던전앤파이터 운영정책",
                "relation": "effective_at",
            },
            [_unit("던전앤파이터 운영정책")],
            question="운영정책은 언제 시행됐어?",
        )
        self.assertEqual(result["state"], "not_applicable")

    def test_product_named_guide_claim_does_not_require_a_shop_record(
        self,
    ) -> None:
        result = evaluate_record_identity(
            {
                "subject": "마스터 칼레이도 박스",
                "relation": "quality_result",
            },
            [
                _unit(
                    "칼레이도 박스",
                    source_id="dnf_game_guide",
                    source_kind="guide",
                    context_text="마스터 칼레이도 박스",
                )
            ],
            question="마스터 칼레이도 박스는 품질을 어떻게 바꿔?",
        )
        self.assertEqual(result["state"], "not_applicable")

    def test_product_subject_can_be_proven_by_the_selected_row(self) -> None:
        result = evaluate_record_identity(
            {
                "subject": "향상된 럭키 박스 3단계",
                "relation": "price",
            },
            [
                _unit(
                    "마일리지샵 2026 시즌4",
                    text="| 향상된 럭키 박스 3단계 | 150M |",
                )
            ],
            question="향상된 럭키 박스 3단계 가격은?",
        )
        self.assertEqual(result["state"], "matched")

    def test_record_year_uses_metadata_not_future_date_in_body(self) -> None:
        result = evaluate_record_identity(
            {
                "subject": "2025년 11월 시브의 보조장비 보주",
                "relation": "has_deletion_deadline",
            },
            [
                {
                    "title": "11월 이달의 아이템",
                    "context_text": (
                        "# [11월 이달의 아이템] : "
                        "시브의 보조장비 보주"
                    ),
                    "text": (
                        "시브의 보조장비 보주는 2026년 1월에 "
                        "삭제되지 않고 기간 무제한입니다."
                    ),
                    "published_at": "2025-10-30",
                    "valid_from": "2025-10-30",
                    "valid_to": "2025-11-27",
                    "parent_document_id": "document-2025-11",
                    "revision_id": "revision-2025-11",
                    "source_id": "dnf_monthly_item",
                    "source_kind": "monthly_item",
                }
            ],
            question=(
                "2025년 11월 시브의 보조장비 보주는 "
                "삭제 기한이 있었어?"
            ),
            force=True,
        )
        self.assertEqual(result["state"], "matched")

    def test_shop_record_month_falls_back_to_iso_period_metadata(self) -> None:
        result = evaluate_record_identity(
            {
                "subject": "2026년 1월 해방의 열쇠 100개 상자",
                "relation": "deletion_at",
            },
            [
                {
                    "title": "해방의 열쇠 100개 상자",
                    "context_text": "# 해방의 열쇠 100개 상자",
                    "text": (
                        "| 삭제일자 | "
                        "2026년 7월 23일 06시 일괄삭제 |"
                    ),
                    "published_at": "2026-06-25",
                    "valid_from": "2026-06-25",
                    "valid_to": "2026-07-09",
                    "parent_document_id": "document-2026-07",
                    "revision_id": "revision-2026-07",
                    "source_id": "dnf_seria_shop",
                    "source_kind": "shop_product",
                }
            ],
            question=(
                "2026년 1월에 판매한 해방의 열쇠 100개 상자는 "
                "언제 삭제됐어?"
            ),
            force=True,
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn("explicit_month_mismatch", result["failures"])

    def test_explicit_record_month_precedes_iso_period_end_month(self) -> None:
        unit = {
            "title": "1월 이달의 아이템",
            "context_text": (
                "# [1월 이달의 아이템 : 해방의 열쇠 100개 상자]"
            ),
            "text": "| 거래타입 | 교환가능 |",
            "published_at": "2025-12-31",
            "valid_from": "2026-01-01",
            "valid_to": "2026-02-05",
            "parent_document_id": "document-2026-01",
            "revision_id": "revision-2026-01",
            "source_id": "dnf_monthly_item",
            "source_kind": "monthly_item",
        }
        result = evaluate_record_identity(
            {
                "subject": "2026년 2월 해방의 열쇠 100개 상자",
                "relation": "trade_type",
            },
            [unit],
            question=(
                "2026년 2월 해방의 열쇠 100개 상자 거래 타입은?"
            ),
            force=True,
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn("explicit_month_mismatch", result["failures"])

    def test_shadow_triggers_only_when_no_matching_product_record_exists(
        self,
    ) -> None:
        requirement = {
            "subject": "2026 DNF 폴리스 아바타 콤보 상자",
            "relation": "included_boxes",
        }
        missing = assess_record_identity_sufficiency(
            requirement,
            [
                _unit(
                    "2026 나비 무도회 아바타 콤보 상자",
                    parent="document-butterfly",
                )
            ],
            question="2026 DNF 폴리스 아바타 콤보 상자 구성품은?",
        )
        present = assess_record_identity_sufficiency(
            requirement,
            [
                _unit(
                    "2026 DNF 폴리스 아바타 콤보 상자",
                    parent="document-police",
                ),
                _unit(
                    "2026 나비 무도회 아바타 콤보 상자",
                    parent="document-butterfly",
                ),
            ],
            question="2026 DNF 폴리스 아바타 콤보 상자 구성품은?",
        )
        self.assertTrue(missing["would_trigger"])
        self.assertFalse(present["would_trigger"])

    def test_constraints_include_explicit_stage_and_month(self) -> None:
        constraints = explicit_record_constraints(
            "2026년 4월 향상된 럭키 박스 3단계 가격은?",
            {
                "subject": "향상된 럭키 박스 3단계",
                "relation": "price",
            },
        )
        self.assertEqual(constraints["years"], [2026])
        self.assertEqual(constraints["months"], [4])
        self.assertEqual(constraints["ordinals"]["stage"], [3])


if __name__ == "__main__":
    unittest.main()
