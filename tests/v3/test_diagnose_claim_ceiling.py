from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.io_utils import read_jsonl
from src.v3.collect_details import write_immutable
from src.v3.diagnose_claim_ceiling import (
    DEFAULT_CANARY,
    DEFAULT_CANARY_CASES,
    DEFAULT_CHUNKS,
    _canonical_json_bytes,
    _is_ollama_base_url,
    _judge_prompt,
    _ollama_api_url,
    decide_path,
    judge_runtime_metadata,
    prepare_diagnostic_rows,
    run_and_freeze,
    score_judgment,
    validate_judge_output,
)


def _fixture_input() -> dict:
    return {
        "case_id": "case-1",
        "question": "상품의 가격과 삭제일은?",
        "baseline_claim_complete": False,
        "condition_a": {
            "chunks": [
                {
                    "chunk_id": "c1",
                    "display_text": "상품 가격은 100M입니다.",
                }
            ]
        },
        "condition_b": {
            "chunks": [
                {
                    "chunk_id": "c1",
                    "display_text": "상품 가격은 100M입니다.",
                },
                {
                    "chunk_id": "c2",
                    "display_text": "상품은 8월 1일 삭제됩니다.",
                },
            ]
        },
        "scoring_only": {
            "groups": [
                {
                    "group_id": "g1",
                    "acceptable_chunk_ids": ["c1"],
                    "evidence_span": "상품 가격은 100M입니다.",
                },
                {
                    "group_id": "g2",
                    "acceptable_chunk_ids": ["c2"],
                    "evidence_span": "상품은 8월 1일 삭제됩니다.",
                },
            ],
            "expected_fully_supported_group_ids": {"A": ["g1"], "B": ["g1", "g2"]},
        },
    }


def _output(include_delete: bool = True) -> dict:
    requirements = [
        {
            "requirement_index": 1,
            "entity": "상품",
            "attribute": "가격",
            "value_type": "금액",
            "qualifiers": [],
            "verdict": "fully_supported",
            "evidence_spans": [
                {"chunk_id": "c1", "span_text": "상품 가격은 100M입니다."}
            ],
        }
    ]
    if include_delete:
        requirements.append(
            {
                "requirement_index": 2,
                "entity": "상품",
                "attribute": "삭제일",
                "value_type": "날짜",
                "qualifiers": [],
                "verdict": "fully_supported",
                "evidence_spans": [
                    {"chunk_id": "c2", "span_text": "상품은 8월 1일 삭제됩니다."}
                ],
            }
        )
    return {"requirements": requirements}


class ClaimCeilingDiagnosticTest(unittest.TestCase):
    def test_ollama_base_url_and_model_digest_are_recorded(self) -> None:
        tags = {
            "models": [
                {
                    "name": "qwen2.5:7b-instruct",
                    "digest": "abc123",
                    "details": {"parameter_size": "7.6B"},
                }
            ]
        }
        with patch.dict(
            "os.environ",
            {"OPENAI_BASE_URL": "http://localhost:11434/v1"},
        ), patch(
            "src.v3.diagnose_claim_ceiling._read_json_url",
            side_effect=[{"version": "0.32.1"}, tags],
        ), patch(
            "src.v3.diagnose_claim_ceiling._post_json_url",
            return_value={
                "parameters": "num_ctx 32768\ntemperature 0",
                "details": {"parent_model": "qwen2.5:7b-instruct"},
                "model_info": {"qwen2.context_length": 32768},
            },
        ):
            metadata = judge_runtime_metadata(
                model="qwen2.5:7b-instruct", timeout_seconds=1
            )

        self.assertEqual(metadata["provider"], "ollama_openai_compatible")
        self.assertEqual(metadata["model_sha256"], "abc123")
        self.assertEqual(metadata["temperature"], 0)
        self.assertFalse(metadata["reasoning_effort_sent"])
        self.assertEqual(metadata["configured_num_ctx"], 32768)
        self.assertTrue(_is_ollama_base_url(metadata["base_url"]))
        self.assertEqual(
            _ollama_api_url(metadata["base_url"], "/api/tags"),
            "http://localhost:11434/api/tags",
        )

    def test_missing_ollama_model_fails_before_run(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENAI_BASE_URL": "http://localhost:11434/v1"},
        ), patch(
            "src.v3.diagnose_claim_ceiling._read_json_url",
            side_effect=[{"version": "0.32.1"}, {"models": []}],
        ):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                judge_runtime_metadata(
                    model="qwen2.5:7b-instruct", timeout_seconds=1
                )

    def test_small_ollama_context_fails_before_run(self) -> None:
        tags = {"models": [{"name": "qwen2.5:7b-instruct", "digest": "abc"}]}
        with patch.dict(
            "os.environ",
            {"OPENAI_BASE_URL": "http://localhost:11434/v1"},
        ), patch(
            "src.v3.diagnose_claim_ceiling._read_json_url",
            side_effect=[{"version": "0.32.1"}, tags],
        ), patch(
            "src.v3.diagnose_claim_ceiling._post_json_url",
            return_value={"parameters": "num_ctx 4096"},
        ):
            with self.assertRaisesRegex(RuntimeError, "num_ctx"):
                judge_runtime_metadata(
                    model="qwen2.5:7b-instruct", timeout_seconds=1
                )

    def test_missing_api_key_does_not_freeze_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"OPENAI_API_KEY": ""}
        ):
            root = Path(temp_dir)

            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                run_and_freeze(
                    root=root,
                    evaluated_at="2026-07-20T00:00:00+09:00",
                )

            self.assertEqual(list(root.rglob("claim_ceiling_*")), [])

    def test_canonical_population_is_15_with_three_controls(self) -> None:
        root = Path(__file__).resolve().parents[2]
        rows = prepare_diagnostic_rows(
            read_jsonl(root / DEFAULT_CANARY),
            read_jsonl(root / DEFAULT_CANARY_CASES),
            read_jsonl(root / DEFAULT_CHUNKS),
        )

        self.assertEqual(len(rows), 15)
        self.assertEqual(sum(row["baseline_claim_complete"] for row in rows), 3)
        self.assertTrue(all(len(row["condition_a"]["chunks"]) <= 10 for row in rows))
        self.assertTrue(
            all(
                all(
                    chunk["parent_document_id"] == row["common_parent_document_id"]
                    for chunk in row["condition_b"]["chunks"]
                )
                for row in rows
            )
        )

    def test_prompt_excludes_gold_and_other_condition(self) -> None:
        row = _fixture_input()

        prompt = _judge_prompt(row, "A")

        self.assertIn("상품 가격은 100M입니다.", prompt)
        self.assertNotIn("8월 1일", prompt)
        self.assertNotIn("acceptable_chunk_ids", prompt)
        self.assertNotIn("evidence_span", prompt)
        self.assertNotIn("group_id", prompt)

    def test_exact_span_validation_rejects_hallucinated_quote(self) -> None:
        row = _fixture_input()
        bad = _output(include_delete=False)
        bad["requirements"][0]["evidence_spans"][0]["span_text"] = "가격은 200M"

        with self.assertRaisesRegex(RuntimeError, "exact contiguous"):
            validate_judge_output(bad, row["condition_a"]["chunks"])

    def test_scoring_separates_a_and_b_ceiling(self) -> None:
        row = _fixture_input()
        a_output = validate_judge_output(
            _output(include_delete=False), row["condition_a"]["chunks"]
        )
        b_output = validate_judge_output(
            _output(include_delete=True), row["condition_b"]["chunks"]
        )

        a = score_judgment(row, "A", a_output)
        b = score_judgment(row, "B", b_output)

        self.assertFalse(a["claim_complete"])
        self.assertEqual(a["support_decision_correct"], 2)
        self.assertTrue(b["claim_complete"])
        self.assertEqual(b["support_decision_correct"], 2)
        self.assertEqual(b["false_support_count"], 0)

    def test_false_support_is_not_silently_accepted(self) -> None:
        row = _fixture_input()
        output = _output(include_delete=False)
        output["requirements"].append(
            {
                "requirement_index": 2,
                "entity": "상품",
                "attribute": "보너스",
                "value_type": "텍스트",
                "qualifiers": [],
                "verdict": "fully_supported",
                "evidence_spans": [
                    {"chunk_id": "c1", "span_text": "상품 가격은 100M입니다."}
                ],
            }
        )
        validated = validate_judge_output(output, row["condition_a"]["chunks"])

        scored = score_judgment(row, "A", validated)

        self.assertEqual(scored["false_support_count"], 1)
        self.assertEqual(scored["recovered_group_count"], 1)

    def test_precommitted_path_decision(self) -> None:
        self.assertEqual(
            decide_path(
                recovered_failures_a=10,
                recovered_failures_b=12,
                false_support_count=0,
            ),
            "PATH_1_SEMANTIC_BUILD",
        )
        self.assertEqual(
            decide_path(
                recovered_failures_a=9,
                recovered_failures_b=10,
                false_support_count=0,
            ),
            "RETRIEVAL_REDIRECT",
        )
        self.assertEqual(
            decide_path(
                recovered_failures_a=9,
                recovered_failures_b=9,
                false_support_count=0,
            ),
            "PATH_2_STOP_SEMANTIC_BUILD",
        )
        self.assertEqual(
            decide_path(
                recovered_failures_a=12,
                recovered_failures_b=12,
                false_support_count=1,
            ),
            "INCONCLUSIVE_HUMAN_CONFIRM_FALSE_SUPPORT",
        )

    def test_immutable_content_is_reusable_but_collision_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            payload = _canonical_json_bytes({"a": 1})
            write_immutable(path, payload)
            write_immutable(path, payload)

            with self.assertRaisesRegex(RuntimeError, "collision"):
                write_immutable(path, _canonical_json_bytes({"a": 2}))


if __name__ == "__main__":
    unittest.main()
