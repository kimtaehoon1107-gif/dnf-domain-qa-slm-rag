from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeze_blind_test import freeze_rows, training_context_exposure  # noqa: E402


def row(eval_id: str, label: str, chunk_id: str = "") -> dict:
    return {
        "eval_id": eval_id,
        "question": f"question {eval_id}",
        "answerability": label,
        "review_status": "approved",
        "expected_doc_id": chunk_id.split("__chunk_")[0] if chunk_id else "",
        "expected_chunk_id": chunk_id,
        "expected_chunk_ids": [chunk_id] if chunk_id else [],
        "evidence_span": f"evidence {eval_id}" if chunk_id else "",
    }


class FreezeBlindTestTests(unittest.TestCase):
    def test_freezes_only_approved_rows_with_exact_evidence(self) -> None:
        reviewed = [row("true", "true", "doc_a__chunk_001"), row("false", "false")]
        rejected = row("rejected", "partial", "doc_x__chunk_001")
        rejected["review_status"] = "rejected"
        reviewed.append(rejected)
        replacements = [row("partial", "partial", "doc_b__chunk_001")]
        chunks = [
            {"doc_id": "doc_a__chunk_001", "text": "prefix evidence true suffix"},
            {"doc_id": "doc_b__chunk_001", "text": "prefix evidence partial suffix"},
        ]

        output, report = freeze_rows(
            reviewed,
            replacements,
            chunks,
            blocked_rows=[],
            expected_counts={"true": 1, "partial": 1, "false": 1},
        )

        self.assertEqual(len(output), 3)
        self.assertTrue(all(item["evaluation_role"] == "final_blind_test_v1" for item in output))
        self.assertEqual(report["evidence_span_mismatches"], 0)

    def test_rejects_span_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "span_mismatches"):
            freeze_rows(
                [row("true", "true", "doc_a__chunk_001")],
                [],
                [{"doc_id": "doc_a__chunk_001", "text": "different text"}],
                blocked_rows=[],
                expected_counts={"true": 1},
            )

    def test_reports_historical_distractor_exposure(self) -> None:
        final = [row("true", "true", "doc_a__chunk_001")]
        training = [
            {
                "documents": [
                    {"doc_id": "doc_a__chunk_001", "role": "distractor"},
                    {"doc_id": "doc_b__chunk_001", "role": "gold"},
                ]
            }
        ]

        report = training_context_exposure(final, training)

        self.assertEqual(report["unique_parent_overlap"], 1)
        self.assertEqual(report["unique_exact_chunk_overlap"], 1)
        self.assertEqual(report["distractor_occurrences"], 1)
        self.assertEqual(report["gold_occurrences"], 0)


if __name__ == "__main__":
    unittest.main()
