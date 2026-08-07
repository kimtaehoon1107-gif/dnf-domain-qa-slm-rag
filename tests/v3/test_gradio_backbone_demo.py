from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.v3.gradio_backbone_demo import (
    EXAMPLE_QUESTIONS,
    DemoBackbone,
    EXPECTED_DIRTY_CHUNKS_SHA256,
    HONEST_BANNER,
    TABLE_INDEX_MANIFEST,
    _route_only_result,
    build_duplicate_family_member_index,
    bounded_candidate_sources,
    enrich_citation_metadata,
    filter_hits_by_global_temporal,
    render_result,
    summarize_grounded_decisions,
    shape_audit,
    validate_exact_citation,
)


class GradioBackboneDemoTest(unittest.TestCase):
    def test_bounded_sources_use_only_first_two_route_candidates(self) -> None:
        route = {
            "source_ids": ["dnf_game_guide"],
            "routing_signals": {
                "candidate_sources": ["dnf_faq", "dnf_notice", "dnf_event"]
            },
        }
        self.assertEqual(
            bounded_candidate_sources(route),
            ("dnf_game_guide", "dnf_faq", "dnf_notice"),
        )

    def test_shape_audit_is_a_trigger_not_positive_entailment(self) -> None:
        requirements = [
            {
                "requirement_id": "requirement_1",
                "subject": "상품",
                "relation": "price",
                "value_type": "amount",
            }
        ]
        missing = shape_audit(
            requirements,
            [{"status": "supported_exact", "spans": [{"text": "상품 가격 안내"}]}],
        )
        present = shape_audit(
            requirements,
            [{"status": "supported_exact", "spans": [{"text": "9,800 세라"}]}],
        )
        self.assertEqual(missing["veto_count"], 1)
        self.assertEqual(missing["supported_after_veto"], 0)
        self.assertEqual(present["veto_count"], 0)
        self.assertEqual(present["supported_after_veto"], 1)

    def test_reject_question_skips_planner(self) -> None:
        demo = DemoBackbone.__new__(DemoBackbone)
        demo._lock = threading.Lock()
        demo._artifacts = SimpleNamespace(documents_by_id={})
        demo._overlay_rows = []
        demo._source_entity_index = {}
        demo._planner_runtime = {}
        demo._initialize = lambda: None
        demo._plan = Mock(side_effect=AssertionError("planner must be skipped"))
        route = {
            "route_action": "reject",
            "intent": "unanswerable",
            "source_ids": [],
        }

        with patch(
            "src.v3.gradio_backbone_demo.classify_answerability",
            return_value={"label": "false", "reason": "requires_current_weather"},
        ), patch(
            "src.v3.gradio_backbone_demo.route_question",
            return_value=route,
        ):
            result = demo.answer("내일 서울 비 와?")

        demo._plan.assert_not_called()
        self.assertEqual(result["response_mode"], "reject")
        self.assertEqual(result["planner"]["call"]["reason"], "answerability_gate")

    def test_grounded_decision_summary_has_no_evaluation_dependency(self) -> None:
        full = summarize_grounded_decisions(
            [
                {
                    "status": "supported_exact",
                    "spans": [{"chunk_id": "chunk_a"}],
                },
                {
                    "status": "supported_exact",
                    "spans": [{"chunk_id": "chunk_b"}],
                },
            ],
            {"chunk_a": "parent_a", "chunk_b": "parent_b"},
        )
        partial = summarize_grounded_decisions(
            [
                {
                    "status": "supported_exact",
                    "spans": [{"chunk_id": "chunk_a"}],
                },
                {"status": "unsupported", "spans": []},
            ],
            {"chunk_a": "parent_a"},
        )
        abstain = summarize_grounded_decisions(
            [{"status": "unsupported", "spans": []}], {}
        )

        self.assertEqual(full["response_mode"], "full_answer")
        self.assertEqual(full["route_action"], "decompose_candidate")
        self.assertEqual(partial["response_mode"], "partial_answer")
        self.assertEqual(partial["route_action"], "retrieve")
        self.assertEqual(abstain["response_mode"], "abstain")
        self.assertEqual(abstain["route_action"], "abstain")

    def test_demo_uses_reviewed_table_candidate_lineage(self) -> None:
        manifest = json.loads(TABLE_INDEX_MANIFEST.read_text(encoding="utf-8"))
        self.assertIn(
            "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a",
            manifest["dense"]["metadata_path"],
        )
        self.assertIn(
            "423dfd6ae35bbfa5db1cef0ea1caa61df547ed99c508c998fd134f44f1c4f79d",
            TABLE_INDEX_MANIFEST.name,
        )

    def test_banner_is_explicit_about_development_ceiling(self) -> None:
        self.assertIn("개발 데모", HONEST_BANNER)
        self.assertIn("9/82 false-full", HONEST_BANNER)
        self.assertIn("미승격", HONEST_BANNER)
        self.assertIn("추출 인용", HONEST_BANNER)
        self.assertIn("의미 정답 보장", HONEST_BANNER)
        self.assertEqual(len(EXAMPLE_QUESTIONS), 6)
        self.assertIn("초월 가격", EXAMPLE_QUESTIONS[0])

    def test_exact_citation_accepts_only_verbatim_slice(self) -> None:
        source = "가격은 1,000세라입니다. 거래 타입은 계정귀속입니다."
        start = source.index("1,000세라")
        span = {
            "span_id": "span_test",
            "start_char": start,
            "end_char": start + len("1,000세라"),
            "text": "1,000세라",
        }
        validate_exact_citation(span, source)
        with self.assertRaisesRegex(RuntimeError, "exact source slice"):
            validate_exact_citation({**span, "text": "1000 세라"}, source)

    def test_realtime_route_becomes_honest_abstain(self) -> None:
        requirement = {
            "requirement_id": "requirement_1",
            "subject": "내 계정",
            "relation": "현재 제재 상태",
            "value_type": "state",
            "subject_group": "내 계정",
        }
        result = _route_only_result(
            question="내 계정 제재 상태 지금 확인해봐.",
            requirements=[requirement],
            route={"route_action": "realtime_api", "intent": "realtime_api"},
            planner_log={},
            planner_runtime={},
        )
        self.assertEqual(result["response_mode"], "abstain")
        self.assertEqual(result["requirements"][0]["citations"], [])
        self.assertIn("정적 공식 문서", result["message"])

    def test_reject_route_has_no_evidence(self) -> None:
        result = _route_only_result(
            question="내일 서울 비 와?",
            requirements=[],
            route={"route_action": "reject", "intent": "unanswerable"},
            planner_log={},
            planner_runtime={},
        )
        self.assertEqual(result["response_mode"], "reject")
        self.assertEqual(result["requirements"], [])

    def test_render_result_exposes_exact_quote_and_source(self) -> None:
        result = {
            "demo_version": "test",
            "route": {"route_action": "retrieve", "backbone_action": "retrieve"},
            "response_mode": "full_answer",
            "message": "exact",
            "requirements": [
                {
                    "requirement": {"subject": "골드 코인", "relation": "가격"},
                    "status": "supported",
                    "message": None,
                    "citations": [
                        {
                            "text": "10개 1,000세라",
                            "canonical_url": "https://df.nexon.com/example",
                            "title": "공식 상품 안내",
                            "source_id": "dnf_shop",
                            "updated_at": "2026-07-01",
                            "published_at": None,
                            "revision_id": "rev_1",
                            "chunk_id": "chunk_1",
                        }
                    ],
                }
            ],
            "provenance": {
                "dirty_canonical_chunks_sha256": EXPECTED_DIRTY_CHUNKS_SHA256
            },
        }
        status, rows, citations, technical = render_result(result)
        self.assertIn("retrieve", status)
        self.assertEqual(rows[0][2], "supported")
        self.assertIn("10개 1,000세라", citations)
        self.assertIn("공식 상품 안내", citations)
        self.assertEqual(
            technical["provenance"]["dirty_canonical_chunks_sha256"],
            EXPECTED_DIRTY_CHUNKS_SHA256,
        )

    def test_finalize_result_runs_generator_only_when_enabled(self) -> None:
        requests = []
        demo = DemoBackbone.__new__(DemoBackbone)
        demo.enable_generation = True
        demo.generator_model = "qwen3:8b"
        demo._answer_generator = lambda request: requests.append(request) or (
            "\uac00\uaca9\uc740 100,000\uace8\ub4dc\uc785\ub2c8\ub2e4."
        )
        demo.timeout = 10.0
        result = {
            "question": "\uac00\uaca9\uc740?",
            "requirements": [
                {
                    "requirement": {
                        "requirement_id": "requirement_1",
                        "subject": "\uc544\uc774\ud15c",
                        "relation": "price",
                        "value_type": "amount",
                    },
                    "status": "supported",
                    "citations": [
                        {
                            "text": (
                                "\uc544\uc774\ud15c \uac00\uaca9: "
                                "100,000\uace8\ub4dc"
                            )
                        }
                    ],
                    "table_views": [],
                }
            ],
        }

        finalized = demo._finalize_result(result, started=0.0)

        self.assertEqual(len(requests), 1)
        self.assertEqual(finalized["generation"]["mode"], "generated")
        self.assertTrue(finalized["generation"]["used_generated_text"])

        disabled = DemoBackbone.__new__(DemoBackbone)
        disabled.enable_generation = False
        disabled.generator_model = "qwen3:8b"
        disabled_result = disabled._finalize_result(
            {"question": "\uac00\uaca9\uc740?", "requirements": []},
            started=0.0,
        )
        self.assertEqual(disabled_result["generation"]["mode"], "disabled")

    def test_render_result_exposes_verified_generated_answer(self) -> None:
        result = {
            "demo_version": "test",
            "route": {"route_action": "retrieve", "backbone_action": "retrieve"},
            "response_mode": "full_answer",
            "message": "extractive",
            "requirements": [],
            "provenance": {},
            "generation": {
                "enabled": True,
                "model": "qwen3:8b",
                "mode": "generated",
                "answer_text": "\uac00\uaca9\uc740 100,000\uace8\ub4dc\uc785\ub2c8\ub2e4.",
                "used_generated_text": True,
                "verification": {"verified": True},
            },
        }

        status, _, _, technical = render_result(result)

        self.assertIn("\uac00\uaca9\uc740 100,000\uace8\ub4dc\uc785\ub2c8\ub2e4.", status)
        self.assertEqual(technical["generation"]["mode"], "generated")

    def test_global_temporal_filter_blocks_only_current_denials(self) -> None:
        hits = [
            {"chunk_id": "current", "parent_document_id": "doc_current"},
            {"chunk_id": "expired", "parent_document_id": "doc_expired"},
        ]
        overlay = {
            "doc_current": {"retrieval_action_current": "allow_with_warning"},
            "doc_expired": {"retrieval_action_current": "deny"},
        }

        current, denied = filter_hits_by_global_temporal(
            hits, time_scope="current", temporal_by_document=overlay
        )
        historical, historical_denied = filter_hits_by_global_temporal(
            hits, time_scope="historical", temporal_by_document=overlay
        )

        self.assertEqual([row["chunk_id"] for row in current], ["current"])
        self.assertEqual([row["chunk_id"] for row in denied], ["expired"])
        self.assertEqual(historical, hits)
        self.assertEqual(historical_denied, [])

    def test_temporal_and_duplicate_metadata_are_visible_without_merging(self) -> None:
        family_index = build_duplicate_family_member_index(
            [
                {
                    "duplicate_family_id": "family_1",
                    "relation_kind": "same_official_entity_candidate",
                    "review_status": "requires_semantic_confirmation",
                    "preferred_source_by_attribute": {"price": "dnf_seria_shop"},
                    "members": [
                        {
                            "parent_document_id": "doc_shop",
                            "source_role": "commerce_price_components_trade_deletion",
                        },
                        {
                            "parent_document_id": "doc_event",
                            "source_role": "event_terms_eligibility_rewards",
                        },
                    ],
                }
            ]
        )
        base = {"parent_document_id": "doc_shop", "text": "가격 1,000 세라"}
        enriched = enrich_citation_metadata(
            base,
            temporal_by_document={
                "doc_shop": {
                    "validity_state": "current_unverified",
                    "validity_reason": "no explicit end",
                    "retrieval_action_current": "allow_with_warning",
                    "last_verified_at": None,
                }
            },
            family_by_document=family_index,
        )

        self.assertEqual(enriched["duplicate_family_id"], "family_1")
        self.assertEqual(
            enriched["source_role"], "commerce_price_components_trade_deletion"
        )
        self.assertEqual(enriched["validity_state"], "current_unverified")
        self.assertIn("명시적 유효기간", enriched["temporal_warning"])

    def test_render_result_includes_complete_table_candidate(self) -> None:
        result = {
            "demo_version": "test",
            "route": {"route_action": "retrieve", "backbone_action": "retrieve"},
            "response_mode": "full_answer",
            "message": "exact",
            "requirements": [
                {
                    "requirement": {"subject": "초월", "relation": "가격"},
                    "status": "supported",
                    "message": None,
                    "citations": [],
                    "table_views": [
                        {"rendered_markdown": "| 구분 | 가격 |\n| --- | --- |\n| 유니크 | 25개 |\n"}
                    ],
                }
            ],
            "provenance": {},
        }

        _, _, citations, _ = render_result(result)

        self.assertIn("구조화 표 1", citations)
        self.assertIn("유니크", citations)
        self.assertIn("25개", citations)


if __name__ == "__main__":
    unittest.main()
