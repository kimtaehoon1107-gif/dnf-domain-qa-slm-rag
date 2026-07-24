from __future__ import annotations

import unittest

from src.v3.evaluate_grounded_llm_replay import (
    build_table_rows_by_chunk,
    run_fixed_requirement_replay,
    run_replay,
    score_verified_output,
    summarize_replay,
)


def _reviewed() -> dict:
    return {
        "candidate_id": "case1",
        "question_text": "상품의 가격과 거래 타입은?",
        "time_scope": "current",
        "requirements": [{"requirement_id": "r1"}, {"requirement_id": "r2"}],
        "evidence_groups": [
            {
                "group_id": "g1",
                "acceptable_chunk_ids": ["c1"],
                "evidence_span": "가격은 100 세라",
            },
            {
                "group_id": "g2",
                "acceptable_chunk_ids": ["c1"],
                "evidence_span": "거래 타입은 계정귀속",
            },
        ],
    }


def _artifacts() -> tuple[list[dict], list[dict], list[dict]]:
    chunks = [
        {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": "가격은 100 세라이고 거래 타입은 계정귀속입니다.",
            "default_exposure": True,
            "status": "current",
        }
    ]
    documents = [
        {
            "document_id": "d1",
            "source_id": "dnf_shop",
            "title": "상품",
            "published_at": "2026-07-01",
            "revision_id": "rev1",
            "status": "current",
            "default_exposure": True,
            "valid_from": None,
            "valid_to": None,
        }
    ]
    temporal = [
        {
            "document_id": "d1",
            "revision_id": "rev1",
            "validity_state": "current_unverified",
            "retrieval_action_current": "allow_with_warning",
        }
    ]
    return chunks, documents, temporal


class GroundedLlmReplayTest(unittest.TestCase):
    def test_table_rows_are_exact_deduplicated_candidate_slices(self) -> None:
        chunks, _, _ = _artifacts()
        row_text = chunks[0]["display_text"]
        facts = [
            {
                "source_chunk_id": "c1",
                "row_id": "row1",
                "start_offset": 0,
                "end_offset": len(row_text),
                "row_text": row_text,
                "attribute": "가격",
                "value": "100 세라",
                "unit": "세라",
            },
            {
                "source_chunk_id": "c1",
                "row_id": "row1",
                "start_offset": 0,
                "end_offset": len(row_text),
                "row_text": row_text,
                "attribute": "거래 타입",
                "value": "계정귀속",
                "unit": None,
            },
        ]

        rows = build_table_rows_by_chunk(facts, chunks_by_id={"c1": chunks[0]})

        self.assertEqual(len(rows["c1"]), 1)
        self.assertEqual(len(rows["c1"][0]["facts"]), 2)
        self.assertEqual(rows["c1"][0]["row_text"], row_text)

    def test_score_catches_missing_requirement_as_false_full(self) -> None:
        chunks, _, _ = _artifacts()
        text = chunks[0]["display_text"]
        quote = "가격은 100 세라"
        verified = {
            "question_time_scope": "current",
            "response_mode": "full_answer",
            "requirements": [
                {
                    "status": "supported_exact",
                    "citations": [
                        {
                            "chunk_id": "c1",
                            "start_char": text.index(quote),
                            "end_char": text.index(quote) + len(quote),
                            "text": quote,
                        }
                    ],
                }
            ],
            "verification": {"all_exposed_citations_verified": True},
        }

        score = score_verified_output(
            _reviewed(),
            candidate_chunk_ids=["c1"],
            verified=verified,
            chunks_by_id={"c1": chunks[0]},
        )

        self.assertTrue(score["false_full"])
        self.assertFalse(score["requirement_count_match"])
        self.assertFalse(score["all_evidence_spans_hit"])

    def test_extra_requirement_citation_is_counted_as_surplus(self) -> None:
        chunks, _, _ = _artifacts()
        text = chunks[0]["display_text"]
        quote = "가격은 100 세라"
        citation = {
            "chunk_id": "c1",
            "start_char": text.index(quote),
            "end_char": text.index(quote) + len(quote),
            "text": quote,
        }
        verified = {
            "question_time_scope": "current",
            "response_mode": "full_answer",
            "requirements": [
                {"status": "supported_exact", "citations": [citation]},
                {"status": "unsupported", "citations": []},
                {"status": "supported_exact", "citations": [citation]},
            ],
            "verification": {"all_exposed_citations_verified": True},
        }

        score = score_verified_output(
            _reviewed(),
            candidate_chunk_ids=["c1"],
            verified=verified,
            chunks_by_id={"c1": chunks[0]},
        )

        self.assertEqual(score["surplus_citation_count"], 1)
        self.assertFalse(score["requirement_count_match"])

    def test_run_replay_keeps_gold_out_of_generator(self) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }
        seen_prompt = []

        def fake_generator(**kwargs):
            seen_prompt.append(kwargs["prompt"])
            return {
                "output": {
                    "question_time_scope": "current",
                    "response_mode": "full_answer",
                    "requirements": [
                        {
                            "question_part": "가격",
                            "status": "supported",
                            "answer": "100 세라",
                            "evidence": [
                                {"candidate_ref": "1", "quote": "가격은 100 세라"}
                            ],
                        },
                        {
                            "question_part": "거래 타입",
                            "status": "supported",
                            "answer": "계정귀속",
                            "evidence": [
                                {"candidate_ref": "1", "quote": "거래 타입은 계정귀속"}
                            ],
                        },
                    ],
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            generator=fake_generator,
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["llm_score"]["all_evidence_spans_hit"])
        self.assertNotIn("acceptable_chunk_ids", seen_prompt[0])
        self.assertNotIn("evidence_span", seen_prompt[0])
        self.assertFalse(rows[0]["gold_available_to_generator"])

    def test_fixed_requirement_replay_binds_count_and_time_server_side(self) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }
        calls = []

        def fake_generator(**kwargs):
            calls.append(kwargs["prompt"])
            quote = "가격은 100 세라" if len(calls) == 1 else "거래 타입은 계정귀속"
            answer = "100 세라" if len(calls) == 1 else "계정귀속"
            return {
                "output": {
                    "status": "supported",
                    "answer": answer,
                    "evidence": [{"candidate_ref": "1", "quote": quote}],
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            generator=fake_generator,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(rows[0]["verified_output"]["question_time_scope"], "current")
        self.assertTrue(rows[0]["llm_score"]["requirement_count_match"])
        self.assertTrue(rows[0]["llm_score"]["all_evidence_spans_hit"])
        self.assertFalse(rows[0]["gold_answer_or_evidence_available_to_generator"])
        self.assertTrue(rows[0]["frozen_requirement_semantics_available_to_generator"])

    def test_fixed_requirement_replay_uses_requirement_candidate_pools(self) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": []},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }
        pool_row = {
            "candidate_id": "case1",
            "requirement_candidate_pools": [
                {"stage3": {"candidate_chunk_ids": ["c1"]}},
                {"stage3": {"candidate_chunk_ids": ["c1"]}},
            ],
        }
        calls = []

        def fake_generator(**kwargs):
            calls.append(kwargs["prompt"])
            quote = "가격은 100 세라" if len(calls) == 1 else "거래 타입은 계정귀속"
            answer = "100 세라" if len(calls) == 1 else "계정귀속"
            return {
                "output": {
                    "status": "supported",
                    "answer": answer,
                    "evidence": [{"candidate_ref": "1", "quote": quote}],
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            generator=fake_generator,
            candidate_pool_rows=[pool_row],
            candidate_pool_arm="stage3",
        )

        self.assertEqual(rows[0]["requirement_candidate_chunk_ids"], [["c1"], ["c1"]])
        self.assertTrue(rows[0]["llm_score"]["candidate_all_groups_covered"])
        self.assertTrue(rows[0]["llm_score"]["all_evidence_spans_hit"])

    def test_split_schema_routes_non_table_requirements_to_quote_only_generator(
        self,
    ) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }
        calls = []

        def forbidden_shared_generator(**kwargs):
            raise AssertionError("non-table requirements used the shared schema")

        def quote_only_generator(**kwargs):
            calls.append(kwargs["prompt"])
            quote = "가격은 100 세라" if len(calls) == 1 else "거래 타입은 계정귀속"
            answer = "100 세라" if len(calls) == 1 else "계정귀속"
            return {
                "output": {
                    "status": "supported",
                    "answer": answer,
                    "evidence": [{"candidate_ref": "1", "quote": quote}],
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            generator=forbidden_shared_generator,
            non_table_generator=quote_only_generator,
            split_evidence_schema=True,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            rows[0]["requirement_evidence_modes"], ["non_table", "non_table"]
        )
        self.assertTrue(rows[0]["llm_score"]["all_evidence_spans_hit"])

    def test_split_schema_batches_same_question_requirements_into_one_call(
        self,
    ) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }
        calls = []

        def forbidden_per_requirement_generator(**kwargs):
            raise AssertionError("batched arm used the per-requirement generator")

        def batch_quote_only_generator(**kwargs):
            calls.append(kwargs["prompt"])
            return {
                "output": {
                    "requirements": [
                        {
                            "requirement_id": "r1",
                            "status": "supported",
                            "answer": "100 세라",
                            "evidence": [
                                {
                                    "candidate_ref": "1",
                                    "quote": "가격은 100 세라",
                                }
                            ],
                        },
                        {
                            "requirement_id": "r2",
                            "status": "supported",
                            "answer": "계정귀속",
                            "evidence": [
                                {
                                    "candidate_ref": "1",
                                    "quote": "거래 타입은 계정귀속",
                                }
                            ],
                        },
                    ]
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            non_table_generator=forbidden_per_requirement_generator,
            non_table_batch_generator=batch_quote_only_generator,
            split_evidence_schema=True,
            batch_requirements=True,
        )

        self.assertEqual(len(calls), 1)
        self.assertIn('"requirement_id": "r1"', calls[0])
        self.assertIn('"requirement_id": "r2"', calls[0])
        self.assertEqual(rows[0]["model_call"]["call_count"], 1)
        self.assertTrue(rows[0]["batch_requirements"])
        self.assertTrue(rows[0]["llm_score"]["all_evidence_spans_hit"])

    def test_batched_requirement_id_mismatch_fails_closed(self) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }

        def incomplete_batch_generator(**kwargs):
            return {
                "output": {
                    "requirements": [
                        {
                            "requirement_id": "r1",
                            "status": "supported",
                            "answer": "100 세라",
                            "evidence": [
                                {
                                    "candidate_ref": "1",
                                    "quote": "가격은 100 세라",
                                }
                            ],
                        }
                    ]
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            non_table_batch_generator=incomplete_batch_generator,
            split_evidence_schema=True,
            batch_requirements=True,
        )

        self.assertEqual(rows[0]["verified_output"]["response_mode"], "abstain")
        self.assertIn(
            "batched requirement IDs differ",
            rows[0]["model_call"]["calls"][0]["error"],
        )

    def test_batched_ordinal_requirement_ids_map_to_fixed_ids(self) -> None:
        chunks, documents, temporal = _artifacts()
        baseline = {
            "candidate_id": "case1",
            "arm0": {"candidate_chunk_ids": ["c1"]},
            "arm0_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
        }

        def ordinal_batch_generator(**kwargs):
            return {
                "output": {
                    "requirements": [
                        {
                            "requirement_id": "1",
                            "status": "supported",
                            "answer": "100 세라",
                            "evidence": [
                                {
                                    "candidate_ref": "1",
                                    "quote": "가격은 100 세라",
                                }
                            ],
                        },
                        {
                            "requirement_id": "2",
                            "status": "supported",
                            "answer": "계정귀속",
                            "evidence": [
                                {
                                    "candidate_ref": "1",
                                    "quote": "거래 타입은 계정귀속",
                                }
                            ],
                        },
                    ]
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[_reviewed()],
            baseline_rows=[baseline],
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            non_table_batch_generator=ordinal_batch_generator,
            split_evidence_schema=True,
            batch_requirements=True,
        )

        self.assertEqual(rows[0]["verified_output"]["response_mode"], "full_answer")
        self.assertEqual(
            rows[0]["model_call"]["calls"][0]["requirement_id_normalization"],
            "ordinal_to_fixed",
        )

    def test_partial_candidate_pools_fall_back_to_baseline_per_case(self) -> None:
        chunks, documents, temporal = _artifacts()
        reviewed_one = _reviewed()
        reviewed_two = {**_reviewed(), "candidate_id": "case2"}
        baseline_score = {
            "all_groups_hit": False,
            "all_evidence_spans_hit": False,
            "relevant_citation_count": 0,
            "citation_count": 0,
        }
        baselines = [
            {
                "candidate_id": "case1",
                "arm0": {"candidate_chunk_ids": ["c1"]},
                "arm0_score": baseline_score,
            },
            {
                "candidate_id": "case2",
                "arm0": {"candidate_chunk_ids": ["c1"]},
                "arm0_score": baseline_score,
            },
        ]
        pool_row = {
            "candidate_id": "case1",
            "requirement_candidate_pools": [
                {"subject_top_3": {"candidate_chunk_ids": ["c1"]}},
                {"subject_top_3": {"candidate_chunk_ids": ["c1"]}},
            ],
        }
        calls = []
        callbacks = []

        def quote_only_generator(**kwargs):
            calls.append(kwargs["prompt"])
            first_requirement = len(calls) % 2 == 1
            return {
                "output": {
                    "status": "supported",
                    "answer": "100 세라" if first_requirement else "계정귀속",
                    "evidence": [
                        {
                            "candidate_ref": "1",
                            "quote": (
                                "가격은 100 세라"
                                if first_requirement
                                else "거래 타입은 계정귀속"
                            ),
                        }
                    ],
                },
                "latency_ms": 1,
                "usage": {"total_tokens": 1},
            }

        rows = run_fixed_requirement_replay(
            reviewed_rows=[reviewed_one, reviewed_two],
            baseline_rows=baselines,
            chunks=chunks,
            documents=documents,
            temporal_rows=temporal,
            table_facts=[],
            model="fake",
            as_of="2026-07-22",
            reasoning_effort="high",
            timeout_seconds=1,
            non_table_generator=quote_only_generator,
            split_evidence_schema=True,
            candidate_pool_rows=[pool_row],
            candidate_pool_arm="subject_top_3",
            allow_partial_candidate_pools=True,
            result_callback=lambda row, current, total: callbacks.append(
                (row["candidate_id"], current, total)
            ),
        )

        self.assertEqual(rows[0]["candidate_pool_arm"], "subject_top_3")
        self.assertEqual(rows[1]["candidate_pool_arm"], "baseline_fallback")
        self.assertEqual(callbacks, [("case1", 1, 2), ("case2", 2, 2)])

    def test_partial_smoke_summary_cannot_pass_full_gate(self) -> None:
        row = {
            "candidate_id": "case1",
            "baseline_score": {
                "all_groups_hit": False,
                "all_evidence_spans_hit": False,
                "relevant_citation_count": 0,
                "citation_count": 0,
            },
            "llm_score": {
                "candidate_all_groups_covered": True,
                "all_groups_hit": True,
                "all_evidence_spans_hit": True,
                "false_full": False,
                "requirement_count_match": True,
                "question_time_scope_match": True,
                "generation_error": None,
                "exact_citation_slices": True,
                "safe_to_expose": True,
                "relevant_citation_count": 1,
                "citation_count": 1,
                "surplus_citation_count": 0,
            },
            "model_call": {"latency_ms": 1, "usage": {"total_tokens": 1}},
        }

        summary = summarize_replay([row])

        self.assertEqual(summary["decision"], "NO_GO")
        self.assertFalse(summary["gates"]["full_32_question_run"])


if __name__ == "__main__":
    unittest.main()
