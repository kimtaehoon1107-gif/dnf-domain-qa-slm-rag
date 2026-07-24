from __future__ import annotations

import unittest

from src.v3.score_typed_evidence_ref_generalization import (
    NORMALIZATION_CONTRACT,
    score_generalization_cases,
    value_present,
)


class TypedEvidenceRefGeneralizationScorerTest(unittest.TestCase):
    def test_preregistered_time_date_and_currency_equivalence(self) -> None:
        self.assertTrue(value_present("06:00", "enum", "매일 6시에 갱신", as_of="2026-07-17"))
        self.assertTrue(
            value_present(
                "2026-08-13T06:00:00+09:00",
                "datetime",
                "2026년 08월 13일 6시 일괄삭제",
                as_of="2026-07-17",
            )
        )
        self.assertTrue(
            value_present(
                {"amount": 40_000_000, "unit": "골드"},
                "currency",
                "4,000만 골드",
                as_of="2026-07-17",
            )
        )
        self.assertTrue(
            value_present(
                {"amount": 120, "unit": "광휘의 잔영"},
                "currency",
                "광휘의 잔영 120개",
                as_of="2026-07-17",
            )
        )

    def test_no_unregistered_semantic_paraphrase_credit(self) -> None:
        self.assertFalse(
            value_present(
                "계정귀속",
                "enum",
                "다른 계정과 거래할 수 없습니다.",
                as_of="2026-07-17",
            )
        )
        self.assertIn(
            "No semantic paraphrase credit is added beyond the typed normalizations above.",
            NORMALIZATION_CONTRACT["rules"],
        )

    def test_fixed_denominator_and_unsupported_false_full(self) -> None:
        chunk_id = "chunk_1"
        chunk_text = "가격은 4,000만 골드입니다."
        chunks = {
            chunk_id: {
                "chunk_id": chunk_id,
                "display_text": chunk_text,
            }
        }
        sealed = [
            {
                "candidate_id": "case_1",
                "slot_ordinal": 1,
                "as_of": "2026-07-17",
                "requirements": [
                    {
                        "requirement_id": "price",
                        "value_type": "currency",
                        "required_values": [{"amount": 40_000_000, "unit": "골드"}],
                        "expected_status": "supported",
                        "acceptable_evidence_units": [
                            {
                                "chunk_id": chunk_id,
                                "start_char": 0,
                                "end_char": len(chunk_text),
                                "text": chunk_text,
                            }
                        ],
                    },
                    {
                        "requirement_id": "stock",
                        "value_type": "number",
                        "required_values": [],
                        "expected_status": "unsupported",
                        "acceptable_evidence_units": [],
                    },
                ],
            }
        ]
        citation = {
            "chunk_id": chunk_id,
            "start_char": 0,
            "end_char": len(chunk_text),
            "text": chunk_text,
        }
        run = [
            {
                "candidate_id": "case_1",
                "requirement_candidate_chunk_ids": [[chunk_id], [chunk_id]],
                "model_call": {"latency_ms": 10, "usage": {}},
                "verified_output": {
                    "requirements": [
                        {
                            "requirement_id": "price",
                            "status": "supported_exact",
                            "answer": "40,000,000 골드",
                            "citations": [citation],
                        },
                        {
                            "requirement_id": "stock",
                            "status": "unsupported",
                            "answer": "",
                            "citations": [],
                        },
                    ],
                    "verification": {
                        "requirements": [
                            {
                                "requirement_id": "price",
                                "model_status": "supported",
                                "failure_reasons": [],
                            },
                            {
                                "requirement_id": "stock",
                                "model_status": "unsupported",
                                "failure_reasons": [],
                            },
                        ]
                    },
                },
            }
        ]
        scored, summary = score_generalization_cases(sealed, run, chunks_by_id=chunks)

        self.assertTrue(scored[0]["holdout_score"]["gold_value_complete"])
        self.assertTrue(scored[0]["holdout_score"]["all_evidence_spans_hit"])
        self.assertEqual(summary["fixed_denominator"], 1)
        self.assertEqual(summary["outcomes"], {"correct": 1, "incorrect": 0, "no_response": 0})
        self.assertEqual(summary["honest_unsupported"]["false_full"], 0)

    def test_human_approved_text_evidence_is_canonical_without_fuzzy_similarity(self) -> None:
        text = "운영정책을 변경할 경우 게임 홈페이지 공지를 통해 알려드립니다."
        chunks = {"chunk_1": {"chunk_id": "chunk_1", "display_text": text}}
        sealed = [
            {
                "candidate_id": "case_1",
                "slot_ordinal": 1,
                "as_of": "2026-07-17",
                "requirements": [
                    {
                        "requirement_id": "notice",
                        "value_type": "text",
                        "required_values": ["공지를 통해 안내"],
                        "expected_status": "supported",
                        "acceptable_evidence_units": [
                            {
                                "chunk_id": "chunk_1",
                                "start_char": 0,
                                "end_char": len(text),
                                "text": text,
                            }
                        ],
                    }
                ],
            }
        ]
        run = [
            {
                "candidate_id": "case_1",
                "requirement_candidate_chunk_ids": [["chunk_1"]],
                "model_call": {"latency_ms": 1, "usage": {}},
                "verified_output": {
                    "requirements": [
                        {
                            "requirement_id": "notice",
                            "status": "supported_exact",
                            "answer": text,
                            "citations": [
                                {
                                    "chunk_id": "chunk_1",
                                    "start_char": 0,
                                    "end_char": len(text),
                                    "text": text,
                                }
                            ],
                        }
                    ],
                    "verification": {
                        "requirements": [
                            {
                                "requirement_id": "notice",
                                "model_status": "supported",
                                "failure_reasons": [],
                            }
                        ]
                    },
                },
            }
        ]

        scored, _ = score_generalization_cases(sealed, run, chunks_by_id=chunks)

        self.assertTrue(scored[0]["holdout_score"]["gold_value_complete"])
        self.assertTrue(scored[0]["holdout_score"]["all_evidence_spans_hit"])


if __name__ == "__main__":
    unittest.main()
