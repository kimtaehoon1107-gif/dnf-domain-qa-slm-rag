from __future__ import annotations

import unittest

from src.v3.minimal_structured_evidence import (
    annotate_prompt_with_structured_rows,
    build_structured_rows_by_coordinate,
    verify_structured_row_binding,
)


class MinimalStructuredEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunk_id = "chunk-policy"
        self.text = "\n".join(
            (
                "[게임 내 이용제한]",
                "[TABLE]",
                "| 구분 | 1차 | 2차 |",
                (
                    "| 운영자 / 직원을 사칭하는 행위 "
                    "| 100일 게임 이용제한 | 1년 게임 이용제한 |"
                ),
                (
                    "| 허위사실 유포, 제보 "
                    "| 10일 게임 이용제한 | 30일 게임 이용제한 |"
                ),
                "[/TABLE]",
                "[커뮤니티 이용제한]",
                "[TABLE]",
                "| 구분 | 1차 | 2차 |",
                (
                    "| 운영자, 직원을 사칭하고 허위사실 유포 "
                    "| 게시물100일 등록제한 | 게시물1년 등록제한 |"
                ),
                "[/TABLE]",
            )
        )
        self.rows = build_structured_rows_by_coordinate(
            [self.chunk_id],
            chunks_by_id={
                self.chunk_id: {
                    "chunk_id": self.chunk_id,
                    "display_text": self.text,
                }
            },
        )

    def _unit(self, needle: str) -> dict:
        start = self.text.index(needle)
        end = self.text.index("\n", start)
        return {
            "chunk_id": self.chunk_id,
            "start_char": start,
            "end_char": end,
            "text": self.text[start:end],
        }

    def test_correct_game_penalty_row_and_column_pass(self) -> None:
        result = verify_structured_row_binding(
            {
                "subject": "운영자·직원 사칭",
                "relation": "first_penalty",
            },
            "100일 게임 이용제한",
            [self._unit("| 운영자 / 직원을 사칭")],
            structured_rows_by_coordinate=self.rows,
            value_matches=lambda value, text: value == text,
        )
        self.assertEqual(result["state"], "matched")

    def test_same_number_from_community_column_is_blocked(self) -> None:
        result = verify_structured_row_binding(
            {
                "subject": "운영자·직원 사칭",
                "relation": "first_penalty",
            },
            "게시물100일 등록제한",
            [self._unit("| 운영자, 직원을 사칭")],
            structured_rows_by_coordinate=self.rows,
            value_matches=lambda value, text: value == text,
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn("structured_scope_mismatch", result["failures"])

    def test_wrong_row_subject_is_blocked(self) -> None:
        result = verify_structured_row_binding(
            {
                "subject": "허위사실 유포·제보",
                "relation": "first_penalty",
            },
            "100일 게임 이용제한",
            [self._unit("| 운영자 / 직원을 사칭")],
            structured_rows_by_coordinate=self.rows,
            value_matches=lambda value, text: value == text,
        )
        self.assertEqual(result["state"], "mismatch")
        self.assertIn(
            "structured_row_subject_mismatch",
            result["failures"],
        )

    def test_prompt_annotation_exposes_server_owned_structure(self) -> None:
        unit = self._unit("| 운영자 / 직원을 사칭")
        annotated = annotate_prompt_with_structured_rows(
            "E1\ttemporal_roles=none\t" + unit["text"],
            evidence_units_by_ref={"E1": unit},
            structured_rows_by_coordinate=self.rows,
        )
        self.assertIn('"scope":"game_account"', annotated)
        self.assertIn('"1차":"100일 게임 이용제한"', annotated)


if __name__ == "__main__":
    unittest.main()
