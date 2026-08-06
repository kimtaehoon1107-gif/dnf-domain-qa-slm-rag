from __future__ import annotations

import unittest

from src.v3.minimal_atomic_proof import verify_atomic_claim_proof


def _subject_matches(
    requirement: dict,
    semantic_text: str,
    title: str,
) -> bool:
    return "큐브 조각" in f"{semantic_text}\n{title}"


def _relation_matches(
    requirement: dict,
    semantic_text: str,
    title: str,
) -> bool:
    return "부여" in f"{semantic_text}\n{title}"


def _value_matches(value: object, text: str) -> bool:
    return str(value) in text


def _unit(
    evidence_ref: str,
    text: str,
    *,
    context_text: str = "",
    source_id: str = "dnf_game_guide",
) -> dict:
    return {
        "evidence_ref": evidence_ref,
        "chunk_id": "chunk-1",
        "start_char": 0,
        "end_char": len(text),
        "source_id": source_id,
        "source_kind": "game_guide",
        "title": "큐브의 계약",
        "context_text": context_text,
        "text": text,
    }


class MinimalAtomicProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requirement = {
            "subject": "흑색 큐브 조각",
            "relation": "granted_attribute",
            "value_type": "enum",
        }

    def test_same_line_subject_relation_and_value_passes(self) -> None:
        result = verify_atomic_claim_proof(
            self.requirement,
            "암속성",
            [
                _unit(
                    "E1",
                    "- 흑색 큐브 조각: 무기에 암속성 부여",
                )
            ],
            structured_rows_by_coordinate={},
            subject_matches=_subject_matches,
            relation_matches=_relation_matches,
            value_matches=_value_matches,
        )
        self.assertEqual(result["state"], "matched")

    def test_sibling_line_with_real_value_is_blocked(self) -> None:
        result = verify_atomic_claim_proof(
            self.requirement,
            "명속성",
            [
                _unit(
                    "E1",
                    "- 흰색 큐브 조각: 무기에 명속성 부여",
                )
            ],
            structured_rows_by_coordinate={},
            subject_matches=_subject_matches,
            relation_matches=_relation_matches,
            value_matches=_value_matches,
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn(
            "atomic_subject_relation_value_not_colocated",
            result["failures"],
        )
        self.assertTrue(result["facts"][0]["subject_matched"])
        self.assertEqual(
            result["facts"][0]["subject_discriminator_state"],
            "conflict",
        )
        self.assertFalse(
            result["facts"][0]["subject_discriminator_matched"]
        )

    def test_unobserved_platform_marker_does_not_activate_guard(self) -> None:
        result = verify_atomic_claim_proof(
            {
                "subject": "네오플OTP 에러 코드 22 안드로이드",
                "relation": "time_sync_setting",
                "value_type": "text",
            },
            "시간 동기화",
            [
                _unit(
                    "E1",
                    (
                        "⑥ (재설치 후) OTP 실행 → 좌측 상단 버튼 "
                        "누른 후 시간설정 → 시간 동기화"
                    ),
                )
            ],
            structured_rows_by_coordinate={},
            subject_matches=lambda requirement, text, title: True,
            relation_matches=lambda requirement, text, title: True,
            value_matches=_value_matches,
        )
        self.assertEqual(result["state"], "not_applicable")

    def test_linked_heading_and_body_are_one_proof_unit(self) -> None:
        result = verify_atomic_claim_proof(
            self.requirement,
            "암속성",
            [
                _unit(
                    "E1",
                    "무기에 암속성 부여",
                    context_text="흑색 큐브 조각",
                )
            ],
            structured_rows_by_coordinate={},
            subject_matches=_subject_matches,
            relation_matches=_relation_matches,
            value_matches=_value_matches,
        )
        self.assertEqual(result["state"], "matched")

    def test_product_record_is_left_to_record_identity_contract(self) -> None:
        result = verify_atomic_claim_proof(
            self.requirement,
            "암속성",
            [
                _unit(
                    "E1",
                    "흑색 큐브 조각: 암속성 부여",
                    source_id="dnf_seria_shop",
                )
            ],
            structured_rows_by_coordinate={},
            subject_matches=_subject_matches,
            relation_matches=_relation_matches,
            value_matches=_value_matches,
        )
        self.assertEqual(result["state"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
