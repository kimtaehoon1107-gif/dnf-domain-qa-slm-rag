from __future__ import annotations

import unittest

from src.v3.score_typed_evidence_ref_generalization import (
    NORMALIZATION_CONTRACT,
    _citation_supports_unit,
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

    def test_registered_location_equivalence_is_relation_scoped(self) -> None:
        self.assertTrue(
            value_present(
                "게임 내",
                "enum",
                "게임 내 보안 메뉴",
                as_of="2026-07-17",
                relation="registration_location",
            )
        )
        self.assertTrue(
            value_present(
                "게임",
                "entity_list",
                "게임 내 보안 메뉴, 홈페이지",
                as_of="2026-07-17",
                relation="deletion_location",
            )
        )
        self.assertTrue(
            value_present(
                "웹",
                "entity_list",
                "게임 내 보안 메뉴, 홈페이지",
                as_of="2026-07-17",
                relation="deletion_location",
            )
        )
        self.assertFalse(
            value_present(
                "고객센터",
                "text",
                "게임 홈페이지",
                as_of="2026-07-17",
                relation="processing_channel",
            )
        )
        self.assertTrue(
            value_present(
                "고객센터",
                "text",
                "이용제한 재조사를 위해 1:1문의를 접수",
                as_of="2026-07-17",
                relation="appeal_channel",
            )
        )
        self.assertFalse(
            value_present(
                "고객센터",
                "text",
                "게임 홈페이지",
                as_of="2026-07-17",
                relation="appeal_channel",
            )
        )

    def test_duration_range_does_not_collapse_to_one_endpoint(self) -> None:
        self.assertTrue(
            value_present(
                "3일/5일",
                "duration_range",
                "유형에 따라 3~5일 정도 소요될 수 있습니다.",
                as_of="2026-07-17",
                relation="processing_days",
            )
        )
        self.assertFalse(
            value_present(
                5,
                "number",
                "유형에 따라 3~5일 정도 소요될 수 있습니다.",
                as_of="2026-07-17",
                relation="processing_days",
            )
        )

    def test_partial_overlap_does_not_count_as_citing_the_approved_unit(
        self,
    ) -> None:
        unit = {
            "chunk_id": "chunk_1",
            "start_char": 0,
            "end_char": len("거래타입\n교환가능"),
            "text": "거래타입\n교환가능",
        }
        label_only = {
            "chunk_id": "chunk_1",
            "start_char": 0,
            "end_char": len("거래타입"),
            "text": "거래타입",
        }
        complete = {
            **unit,
        }

        self.assertFalse(
            _citation_supports_unit(
                label_only,
                unit,
                expected="교환가능",
                value_type="enum",
                as_of="2026-07-22",
            )
        )
        self.assertTrue(
            _citation_supports_unit(
                complete,
                unit,
                expected="교환가능",
                value_type="enum",
                as_of="2026-07-22",
            )
        )

    def test_value_only_citation_does_not_cover_text_evidence_unit(self) -> None:
        unit = {
            "chunk_id": "chunk_1",
            "start_char": 0,
            "end_char": len("거래타입\n교환가능"),
            "text": "거래타입\n교환가능",
        }
        value_only = {
            "chunk_id": "chunk_1",
            "start_char": len("거래타입\n"),
            "end_char": len("거래타입\n교환가능"),
            "text": "교환가능",
        }

        self.assertFalse(
            _citation_supports_unit(
                value_only,
                unit,
                expected="교환가능",
                value_type="enum",
                as_of="2026-07-22",
            )
        )

    def test_strict_value_requires_approved_coordinate_overlap(self) -> None:
        unit = {
            "chunk_id": "chunk_1",
            "start_char": 0,
            "end_char": 13,
            "text": "가격은 100 세라",
        }
        same_value_elsewhere = {
            "chunk_id": "chunk_1",
            "start_char": 20,
            "end_char": 33,
            "text": "가격은 100 세라",
        }
        value_start = unit["text"].index("100")
        overlapping_slice = {
            "chunk_id": "chunk_1",
            "start_char": value_start,
            "end_char": 13,
            "text": unit["text"][value_start:],
        }

        self.assertFalse(
            _citation_supports_unit(
                same_value_elsewhere,
                unit,
                expected={"amount": 100, "unit": "세라"},
                value_type="currency",
                as_of="2026-07-22",
            )
        )
        self.assertTrue(
            _citation_supports_unit(
                overlapping_slice,
                unit,
                expected={"amount": 100, "unit": "세라"},
                value_type="currency",
                as_of="2026-07-22",
            )
        )

    def test_strict_value_rejects_one_character_boundary_overlap(self) -> None:
        unit = {
            "chunk_id": "chunk_1",
            "start_char": 10,
            "end_char": 23,
            "text": "가격은 100 세라",
        }
        one_character_overlap = {
            "chunk_id": "chunk_1",
            "start_char": 22,
            "end_char": 30,
            "text": "라 unrelated",
        }

        self.assertFalse(
            _citation_supports_unit(
                one_character_overlap,
                unit,
                expected={"amount": 100, "unit": "세라"},
                value_type="currency",
                as_of="2026-07-22",
            )
        )

    def test_shared_currency_and_boolean_normalization(self) -> None:
        self.assertTrue(
            value_present(
                {"amount": 120, "unit": "광휘의 잔영"},
                "currency",
                "광휘의 잔영 120개",
                as_of="2026-07-17",
            )
        )
        self.assertTrue(
            value_present(
                True,
                "boolean",
                "다른 계정으로 이동하면 교환불가 타입으로 변경",
                as_of="2026-07-17",
            )
        )
        self.assertFalse(
            value_present(
                True,
                "boolean",
                "교환불가 상태로 변경되지 않습니다",
                as_of="2026-07-17",
            )
        )

    def test_entity_number_identity_has_digit_boundaries(self) -> None:
        self.assertTrue(
            value_present(
                "110",
                "entity",
                "110레벨 장비",
                as_of="2026-07-22",
            )
        )
        self.assertFalse(
            value_present(
                "110",
                "entity",
                "1100레벨 장비",
                as_of="2026-07-22",
            )
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

    def test_typed_case_with_false_full_is_not_correct(self) -> None:
        chunk_text = "가격은 100 세라입니다."
        chunks = {
            "chunk_1": {
                "chunk_id": "chunk_1",
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
                        "required_values": [{"amount": 100, "unit": "세라"}],
                        "expected_status": "supported",
                        "acceptable_evidence_units": [
                            {
                                "chunk_id": "chunk_1",
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
            "chunk_id": "chunk_1",
            "start_char": 0,
            "end_char": len(chunk_text),
            "text": chunk_text,
        }
        run = [
            {
                "candidate_id": "case_1",
                "requirement_candidate_chunk_ids": [
                    ["chunk_1"],
                    ["chunk_1"],
                ],
                "model_call": {"latency_ms": 1, "usage": {}},
                "verified_output": {
                    "response_mode": "full_answer",
                    "requirements": [
                        {
                            "requirement_id": "price",
                            "status": "supported_exact",
                            "answer": "100 세라",
                            "citations": [citation],
                        },
                        {
                            "requirement_id": "stock",
                            "status": "supported_exact",
                            "answer": "1",
                            "citations": [citation],
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
                                "model_status": "supported",
                                "failure_reasons": [],
                            },
                        ]
                    },
                },
            }
        ]

        scored, summary = score_generalization_cases(
            sealed,
            run,
            chunks_by_id=chunks,
        )

        holdout = scored[0]["holdout_score"]
        self.assertTrue(holdout["false_full"])
        self.assertFalse(holdout["typed_claim_complete"])
        self.assertEqual(holdout["typed_outcome"], "incorrect")
        self.assertEqual(
            summary["typed_outcomes"],
            {"correct": 0, "incorrect": 1, "no_response": 0},
        )

    def test_candidate_coverage_requires_every_required_value_group(
        self,
    ) -> None:
        chunks = {
            "chunk_1": {
                "chunk_id": "chunk_1",
                "display_text": "넥슨 라이브",
            },
            "chunk_2": {
                "chunk_id": "chunk_2",
                "display_text": "던파TV",
            },
        }
        sealed = [
            {
                "candidate_id": "case_1",
                "slot_ordinal": 1,
                "as_of": "2026-07-17",
                "requirements": [
                    {
                        "requirement_id": "channels",
                        "value_type": "entity_list",
                        "required_values": ["넥슨 라이브", "던파TV"],
                        "expected_status": "supported",
                        "acceptable_evidence_units": [
                            {
                                "chunk_id": "chunk_1",
                                "start_char": 0,
                                "end_char": len("넥슨 라이브"),
                                "text": "넥슨 라이브",
                            },
                            {
                                "chunk_id": "chunk_2",
                                "start_char": 0,
                                "end_char": len("던파TV"),
                                "text": "던파TV",
                            },
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
                    "response_mode": "abstain",
                    "requirements": [
                        {
                            "requirement_id": "channels",
                            "status": "unsupported",
                            "answer": "",
                            "citations": [],
                        }
                    ],
                    "verification": {
                        "requirements": [
                            {
                                "requirement_id": "channels",
                                "model_status": "unsupported",
                                "failure_reasons": [],
                            }
                        ]
                    },
                },
            }
        ]

        scored, _ = score_generalization_cases(
            sealed,
            run,
            chunks_by_id=chunks,
        )

        self.assertFalse(
            scored[0]["holdout_score"]["candidate_all_gold_covered"]
        )

    def test_legacy_evidence_credit_does_not_hide_typed_answer_mismatch(
        self,
    ) -> None:
        text = (
            "신청은 게임 홈페이지에서 가능하며 고객센터에서도 "
            "접수할 수 있습니다."
        )
        chunks = {"chunk_1": {"chunk_id": "chunk_1", "display_text": text}}
        sealed = [
            {
                "candidate_id": "case_1",
                "slot_ordinal": 1,
                "as_of": "2026-07-17",
                "requirements": [
                    {
                        "requirement_id": "channel",
                        "value_type": "text",
                        "required_values": ["고객센터"],
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
                    "response_mode": "full_answer",
                    "requirements": [
                        {
                            "requirement_id": "channel",
                            "status": "supported_exact",
                            "answer": "게임 홈페이지",
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
                                "requirement_id": "channel",
                                "model_status": "supported",
                                "failure_reasons": [],
                            }
                        ]
                    },
                },
            }
        ]

        scored, summary = score_generalization_cases(
            sealed,
            run,
            chunks_by_id=chunks,
        )

        holdout = scored[0]["holdout_score"]
        self.assertTrue(holdout["gold_value_complete"])
        self.assertFalse(holdout["typed_answer_value_complete"])
        self.assertFalse(holdout["typed_claim_complete"])
        self.assertEqual(holdout["outcome"], "correct")
        self.assertEqual(holdout["typed_outcome"], "incorrect")
        self.assertTrue(holdout["automatic_semantic_false_full"])
        self.assertEqual(
            summary["typed_answer_value_complete"],
            {"successes": 0, "total": 1},
        )
        self.assertEqual(
            summary["typed_claim_complete"],
            {"successes": 0, "total": 1},
        )
        self.assertEqual(
            summary["typed_outcomes"],
            {"correct": 0, "incorrect": 1, "no_response": 0},
        )

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

    def test_automatic_semantic_false_full_is_separate_from_unsupported(
        self,
    ) -> None:
        text = "상의 클론 가격은 2,600 세라이고 다른 상품은 15 골드 코인입니다."
        chunks = {"chunk_1": {"chunk_id": "chunk_1", "display_text": text}}
        sealed = [
            {
                "candidate_id": "case_1",
                "slot_ordinal": 1,
                "as_of": "2026-07-17",
                "requirements": [
                    {
                        "requirement_id": "price",
                        "value_type": "currency",
                        "required_values": [
                            {"amount": 2600, "unit": "세라"}
                        ],
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
                    "response_mode": "full_answer",
                    "requirements": [
                        {
                            "requirement_id": "price",
                            "status": "supported_exact",
                            "answer": "15 골드 코인",
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
                                "requirement_id": "price",
                                "model_status": "supported",
                                "failure_reasons": [],
                            }
                        ]
                    },
                },
            }
        ]

        scored, summary = score_generalization_cases(
            sealed,
            run,
            chunks_by_id=chunks,
        )

        holdout = scored[0]["holdout_score"]
        self.assertFalse(holdout["false_full"])
        self.assertTrue(holdout["automatic_semantic_false_full"])
        self.assertEqual(
            summary["automatic_semantic_false_full"],
            {"count": 1, "slots": [1]},
        )


if __name__ == "__main__":
    unittest.main()
