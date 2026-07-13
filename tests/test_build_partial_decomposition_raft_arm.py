from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from build_partial_decomposition_raft_arm import build_controlled_raft  # noqa: E402


def raft(source_id: str, source_type: str = "official_fact_chunk") -> dict:
    return {
        "raft_id": "old",
        "source_qa_id": source_id,
        "answerability": "partial" if source_type == "partial_decomposition_train" else "true",
        "source_eval_type": source_type,
        "documents": [{"doc_id": f"{source_id}_doc"}],
    }


class BuildPartialDecompositionRaftArmTests(unittest.TestCase):
    def test_preserves_baseline_and_appends_only_reviewed_rows(self) -> None:
        baseline = [raft("base_1")]
        generated = [raft("base_1"), raft("partial_1", "partial_decomposition_train")]
        reviewed = [{"qa_id": "partial_1"}]
        combined, summary = build_controlled_raft(baseline, generated, reviewed)
        self.assertEqual(combined[0]["documents"], baseline[0]["documents"])
        self.assertEqual([row["source_qa_id"] for row in combined], ["base_1", "partial_1"])
        self.assertEqual(summary["reviewed_rows_appended"], 1)

    def test_rejects_unreviewed_addition(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not match reviewed"):
            build_controlled_raft(
                [raft("base_1")],
                [raft("base_1"), raft("extra", "partial_decomposition_train")],
                [{"qa_id": "partial_1"}],
            )

    def test_rejects_missing_baseline_row(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing baseline"):
            build_controlled_raft([raft("base_1")], [], [])

    def test_rejects_wrong_new_source_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "wrong source type"):
            build_controlled_raft(
                [raft("base_1")],
                [raft("base_1"), raft("partial_1")],
                [{"qa_id": "partial_1"}],
            )


if __name__ == "__main__":
    unittest.main()
