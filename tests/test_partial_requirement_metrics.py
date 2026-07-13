from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evaluate_partial_requirements import evaluate, normalize_match_text  # noqa: E402


def annotation() -> list[dict]:
    return [
        {
            "eval_id": "p1",
            "requirements": [
                {
                    "requirement_id": "p1_g1",
                    "type": "grounded",
                    "description": "점검 시간",
                    "required_fact_groups": [["05시 30분", "05:30"], ["10시", "10:00"]],
                    "expected_chunk_ids": ["doc__chunk_001"],
                },
                {
                    "requirement_id": "p1_u1",
                    "type": "unsupported",
                    "description": "개인 접속 시점",
                    "target_phrases": ["언제 접속", "접속 시점", "접속"],
                },
            ],
        }
    ]


def eval_rows() -> list[dict]:
    return [{"eval_id": "p1", "answerability": "partial"}]


def report(answer: str, label: str = "partial", citations: list[str] | None = None) -> dict:
    return {
        "adapter_dir": "adapter",
        "eval_set": "eval.jsonl",
        "details": [
            {
                "eval_id": "p1",
                "parsed_answerability": label,
                "parsed_answer": answer,
                "parsed_citations": citations or [],
                "retrieval_expected_hit": True,
            }
        ],
    }


class PartialRequirementMetricTests(unittest.TestCase):
    def test_normalizes_date_notation(self) -> None:
        self.assertEqual(normalize_match_text("05시 30분"), normalize_match_text("05시30분"))
        self.assertEqual(normalize_match_text("6月18日"), normalize_match_text("6월 18일"))

    def test_joint_success_requires_grounding_citation_and_targeted_abstention(self) -> None:
        result = evaluate(
            report(
                "점검은 05:30부터 10:00까지입니다. 언제 접속할지는 일정 정보가 없어 정할 수 없습니다.",
                citations=["doc__chunk_001"],
            ),
            eval_rows(),
            annotation(),
        )

        self.assertEqual(result["summary"]["grounded_slot_answer_rate"], 1.0)
        self.assertEqual(result["summary"]["unsupported_slot_abstention_rate"], 1.0)
        self.assertEqual(result["summary"]["partial_requirement_joint_success_rate"], 1.0)

    def test_generic_total_refusal_is_over_refusal_and_unsupported_omission(self) -> None:
        result = evaluate(
            report("수집된 문서만으로는 확인할 수 없습니다.", label="false"),
            eval_rows(),
            annotation(),
        )

        self.assertEqual(result["summary"]["grounded_slot_over_refusal_rate"], 1.0)
        self.assertEqual(result["summary"]["unsupported_slot_omission_rate"], 1.0)
        self.assertEqual(result["summary"]["partial_requirement_joint_success_rate"], 0.0)

    def test_unsupported_claim_without_abstention_is_over_answer(self) -> None:
        result = evaluate(
            report(
                "점검은 05:30부터 10:00까지이며 10시에 접속하면 좋습니다.",
                citations=["doc__chunk_001"],
            ),
            eval_rows(),
            annotation(),
        )

        self.assertEqual(result["summary"]["unsupported_slot_over_answer_rate"], 1.0)
        self.assertEqual(result["summary"]["partial_requirement_joint_success_rate"], 0.0)

    def test_rejects_annotation_without_both_slot_types(self) -> None:
        bad = annotation()
        bad[0]["requirements"] = bad[0]["requirements"][:1]
        with self.assertRaisesRegex(ValueError, "grounded and unsupported"):
            evaluate(report("answer"), eval_rows(), bad)


if __name__ == "__main__":
    unittest.main()
