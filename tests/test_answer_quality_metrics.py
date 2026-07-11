from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evaluate_generated_answer_quality import evaluate, lexical_support  # noqa: E402


class AnswerQualityMetricTests(unittest.TestCase):
    def test_lexical_support_is_conservative_overlap(self) -> None:
        precision, recall, f1 = lexical_support("입장 레벨은 115입니다", "입장 레벨은 115이며 명성이 필요합니다")
        self.assertGreater(precision, 0)
        self.assertGreater(recall, 0)
        self.assertGreater(f1, 0)

    def test_joint_partial_and_false_metrics(self) -> None:
        eval_rows = [
            {
                "eval_id": "p1",
                "answerability": "partial",
                "intent": "partial_ambiguous",
                "evidence_span": "입장 레벨은 115입니다",
                "expected_chunk_ids": ["doc__chunk_001"],
            },
            {
                "eval_id": "f1",
                "answerability": "false",
                "intent": "adversarial_abuse",
                "evidence_span": "",
                "expected_chunk_ids": [],
            },
        ]
        report = {
            "adapter_dir": "adapter",
            "eval_set": "eval.jsonl",
            "details": [
                {
                    "eval_id": "p1",
                    "parsed_answerability": "partial",
                    "parsed_citations": ["doc__chunk_001"],
                    "generated_answer": "answerability: partial\ncitations: doc__chunk_001\nanswer: 입장 레벨은 115입니다",
                },
                {
                    "eval_id": "f1",
                    "parsed_answerability": "false",
                    "parsed_citations": [],
                    "generated_answer": "answerability: false\ncitations:\nanswer: 공식 문서만으로는 확인할 수 없습니다",
                },
            ],
        }
        result = evaluate(report, eval_rows)
        self.assertEqual(result["summary"]["partial_joint_success_rate"], 1.0)
        self.assertEqual(result["summary"]["false_joint_correct_rate"], 1.0)
        self.assertEqual(result["summary"]["unsafe_answer_rate_on_safety_false"], 0.0)


if __name__ == "__main__":
    unittest.main()
