from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.review_requirement_surface_query_canary_app import (
    apply_review,
    atomic_write_draft,
    finalize_review,
    render_row,
    review_export_ready,
    review_progress,
    validate_draft_structure,
)


class ReviewRequirementSurfaceQueryCanaryAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {
            "candidate_id": "candidate_1",
            "slot_ordinal": 1,
            "question_text": "question",
            "human_review_decision": None,
            "human_reviewer_id": None,
            "human_reviewed_at": None,
            "human_review_rationale": None,
        }

    def test_only_review_fields_may_change(self) -> None:
        updated = apply_review(
            [self.row],
            0,
            decision="approve",
            reviewer_id="human_reviewer",
            rationale="checked",
        )
        validate_draft_structure([self.row], updated)
        self.assertEqual(review_progress(updated), {"approved": 1, "rejected": 0, "pending": 0})

        corrupted = copy.deepcopy(updated)
        corrupted[0]["question_text"] = "changed"
        with self.assertRaises(RuntimeError):
            validate_draft_structure([self.row], corrupted)

    def test_reject_requires_rationale_and_atomic_write_is_deterministic(self) -> None:
        with self.assertRaises(RuntimeError):
            apply_review(
                [self.row],
                0,
                decision="reject",
                reviewer_id="human_reviewer",
                rationale="",
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.jsonl"
            first = atomic_write_draft(path, [self.row])
            second = atomic_write_draft(path, [self.row])
            self.assertEqual(first, second)

    def test_export_requires_exactly_32_approvals_and_keeps_scoring_blocked(self) -> None:
        rows = []
        for ordinal in range(1, 33):
            row = copy.deepcopy(self.row)
            row.update(
                {
                    "candidate_id": f"candidate_{ordinal}",
                    "slot_ordinal": ordinal,
                    "human_review_decision": "approve",
                    "human_reviewer_id": "human_reviewer",
                    "human_reviewed_at": "2026-07-22T12:00:00+09:00",
                    "human_review_rationale": "checked",
                    "sealed_scoring_allowed": False,
                    "final_benchmark_eligible": False,
                    "independent_holdout_claim_allowed": False,
                    "training_allowed": False,
                }
            )
            rows.append(row)

        self.assertTrue(review_export_ready(rows))
        pending = copy.deepcopy(rows)
        pending[-1]["human_review_decision"] = None
        self.assertFalse(review_export_ready(pending))
        rejected = copy.deepcopy(rows)
        rejected[-1]["human_review_decision"] = "reject"
        self.assertFalse(review_export_ready(rejected))
        self.assertFalse(review_export_ready(rows[:-1]))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / "data/v3/evaluation/candidate.jsonl"
            atomic_write_draft(packet, rows)
            result = finalize_review(root=root, packet_path=packet, rows=rows)
            reviewed = read_jsonl(Path(result["reviewed_path"]))
            self.assertEqual(len(reviewed), 32)
            for row in reviewed:
                self.assertFalse(row["sealed_scoring_allowed"])
                self.assertFalse(row["final_benchmark_eligible"])
                self.assertFalse(row["independent_holdout_claim_allowed"])
                self.assertFalse(row["training_allowed"])

    def test_exact_chunk_slice_locator_renders_for_human_review(self) -> None:
        root = Path(__file__).resolve().parents[2]
        packet = root / (
            "data/v3/evaluation/requirement_surface_query_canary_candidate_"
            "8c2db240572c315c72724a3c05fc83dcd23c718dabaffd1b76e530924b486d95.jsonl"
        )
        ordinal_12 = next(
            row for row in read_jsonl(packet) if row["slot_ordinal"] == 12
        )
        rendered = render_row(ordinal_12)
        self.assertIn("exact chunk slice", rendered)
        self.assertIn("65:235", rendered)
        self.assertIn("previous_special_gift_match_rejected", rendered)


if __name__ == "__main__":
    unittest.main()
