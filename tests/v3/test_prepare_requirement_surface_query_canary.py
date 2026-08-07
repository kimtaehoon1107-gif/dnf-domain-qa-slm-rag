from __future__ import annotations

import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.answer_target_router import _kiwi
from src.v3.korean_particles import validate_particle_tokens
from src.v3.prepare_requirement_surface_query_canary import (
    BASES,
    DEFAULT_CHUNKS,
    DEFAULT_PREVIOUS_PACKET,
    PROTECTED_APPROVED_FIELDS,
    REVIEW_REJECTED_SLOT_ORDINALS,
    _build_requirement,
    _duplicate_scan_unit,
    _question_for,
    _resolve_table_atomic_fact,
)
from src.v3.requirement_surface_query import extract_entity_coordinated_surfaces


class PrepareRequirementSurfaceQueryCanaryTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    REFROZEN_PACKET = ROOT / (
        "data/v3/evaluation/requirement_surface_query_canary_candidate_"
        "8c2db240572c315c72724a3c05fc83dcd23c718dabaffd1b76e530924b486d95.jsonl"
    )

    def test_refrozen_packet_enforces_review_invariants(self) -> None:
        rows = read_jsonl(self.REFROZEN_PACKET)
        previous = {
            row["slot_ordinal"]: row
            for row in read_jsonl(self.ROOT / DEFAULT_PREVIOUS_PACKET)
        }
        chunks = {
            row["chunk_id"]: row for row in read_jsonl(self.ROOT / DEFAULT_CHUNKS)
        }
        changed = set()
        for row in rows:
            slot = row["slot_ordinal"]
            if any(row[key] != previous[slot][key] for key in PROTECTED_APPROVED_FIELDS):
                changed.add(slot)
            if len(row["requirements"]) > 1:
                self.assertEqual(
                    len({group["evidence_span"] for group in row["evidence_groups"]}),
                    len(row["requirements"]),
                )
            validate_particle_tokens(_kiwi().tokenize(row["question_text"]))
            self.assertEqual(
                row["expected_surface_query_action"],
                row["actual_surface_query_action_from_authored_requirements"],
            )
            self.assertIn("duplicate_current_evidence", row)
            for group in row["evidence_groups"]:
                locator = group.get("evidence_locator")
                if not locator:
                    continue
                display_text = chunks[locator["source_chunk_id"]]["display_text"]
                self.assertEqual(
                    display_text[locator["start_offset"] : locator["end_offset"]],
                    group["evidence_span"],
                )
        self.assertEqual(changed, REVIEW_REJECTED_SLOT_ORDINALS)
        for row in rows:
            if row["slot_ordinal"] in REVIEW_REJECTED_SLOT_ORDINALS:
                continue
            old = previous[row["slot_ordinal"]]
            for key in PROTECTED_APPROVED_FIELDS:
                self.assertEqual(row[key], old[key])

        ordinal_12 = next(row for row in rows if row["slot_ordinal"] == 12)
        evidence_3 = ordinal_12["evidence_groups"][2]
        self.assertEqual(
            evidence_3["acceptable_chunk_ids"],
            ["chunk_sha256_8bacceaaf7f9215dd9837f65d63dc4491d3b53429fe963e5c66c1bc1322473c2"],
        )
        self.assertEqual(len(evidence_3["evidence_span"]), 170)
        self.assertEqual(
            evidence_3["evidence_locator"],
            {
                "kind": "chunk_exact_slice",
                "source_chunk_id": "chunk_sha256_8bacceaaf7f9215dd9837f65d63dc4491d3b53429fe963e5c66c1bc1322473c2",
                "start_offset": 65,
                "end_offset": 235,
            },
        )
        self.assertFalse(ordinal_12["sibling_review_required"])
        self.assertEqual(
            ordinal_12["duplicate_resolution"],
            "previous_special_gift_match_rejected_not_equivalent_unrelated_event_boilerplate",
        )

    def test_short_duplicate_span_uses_field_context(self) -> None:
        display_text = "상점판매가\n4,000만 골드\n거래타입\n교환가능\n삭제기일"
        self.assertEqual(
            _duplicate_scan_unit("교환가능", display_text),
            "거래타입\n교환가능",
        )
        sentence = "최후의 조율자 - 간헐적으로 조율의 천칭이 파괴되지 않는 현상이 수정됩니다."
        self.assertEqual(_duplicate_scan_unit(sentence, sentence), sentence)

    def test_review_rejected_questions_are_corrected_only_as_scoped(self) -> None:
        self.assertEqual(
            BASES["dnf_notice"]["a"]["positive_question"],
            "3/26 패치에서 최후의 조율자의 천칭 파괴 오류 처리와 Y축 피격 판정 조정은 어떻게 됐어?",
        )
        self.assertEqual(
            _question_for(BASES["dnf_notice"]["a"], "single_requirement_control"),
            "3/26 패치에서 최후의 조율자의 천칭 파괴 오류 처리만 알려줘.",
        )
        expected = {
            "dnf_notice": "네이버 로그인 계정의 접속 주소, 계정 종류, 로그인 방법을 모두 알려줘.",
            "dnf_event": "트로피컬 바캉스 패키지의 판매 기간, 첫 구매 혜택, 혜택 삭제 시각을 모두 알려줘.",
            "dnf_seria_shop": "계약&기간제의 가브리엘/배니부 3일 가격, 거래 타입, 적용 시점을 모두 알려줘.",
            "dnf_monthly_item": "이달의 아이템의 거래 타입, 삭제 시각, 사용 시 획득 구성을 모두 알려줘.",
        }
        for source_id, question in expected.items():
            with self.subTest(source_id=source_id):
                self.assertEqual(
                    _question_for(BASES[source_id]["b"], "three_requirement_control"),
                    question,
                )

    def test_shop_atomic_fact_resolution_is_value_cell_exact(self) -> None:
        configured = BASES["dnf_seria_shop"]["a"]["facts"][0]
        table_fact = {
            "parent_document_id": "document_1",
            "row_text": configured["table_row_text"],
            "attribute": configured["table_atomic_attribute"],
            "value": configured["evidence_span"],
        }
        self.assertIs(
            _resolve_table_atomic_fact(configured, "document_1", [table_fact]),
            table_fact,
        )
        self.assertEqual(configured["evidence_span"], "100,000 골드")
        self.assertNotEqual(
            BASES["dnf_seria_shop"]["a"]["facts"][0]["evidence_span"],
            BASES["dnf_seria_shop"]["a"]["facts"][1]["evidence_span"],
        )

    def test_all_authored_positive_shapes_apply(self) -> None:
        for source_id, bases in BASES.items():
            for base_key in ("a", "b"):
                base = bases[base_key]
                requirements = [
                    _build_requirement(fact, base["entity"], ordinal)
                    for ordinal, fact in enumerate(base["facts"][:2], 1)
                ]
                with self.subTest(source_id=source_id, base=base_key):
                    self.assertIsNotNone(
                        extract_entity_coordinated_surfaces(
                            base["positive_question"], requirements
                        )
                    )

    def test_single_and_three_requirement_controls_bypass(self) -> None:
        for source_id, bases in BASES.items():
            single = bases["a"]
            single_requirements = [
                _build_requirement(single["facts"][0], single["entity"], 1)
            ]
            triple = bases["b"]
            triple_requirements = [
                _build_requirement(fact, triple["entity"], ordinal)
                for ordinal, fact in enumerate(triple["facts"][:3], 1)
            ]
            with self.subTest(source_id=source_id):
                self.assertIsNone(
                    extract_entity_coordinated_surfaces(
                        _question_for(single, "single_requirement_control"),
                        single_requirements,
                    )
                )
                self.assertIsNone(
                    extract_entity_coordinated_surfaces(
                        _question_for(triple, "three_requirement_control"),
                        triple_requirements,
                    )
                )


if __name__ == "__main__":
    unittest.main()
