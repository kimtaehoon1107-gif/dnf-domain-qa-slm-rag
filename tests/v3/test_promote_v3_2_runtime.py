from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.v3.build_corpus import file_sha256
from src.v3.promote_v3_2_runtime import audit_promotion_basis


def _report() -> dict:
    return {
        "ab_metrics": {
            "baseline": {"grounded": {"successes": 73}, "false_full": {"successes": 9}},
            "arm1": {"grounded": {"successes": 73}, "false_full": {"successes": 9}},
            "new_false_full_count": 0,
        },
        "candidate_recall": {
            "baseline": {"evidence_groups": {"successes": 96, "total": 109}},
            "arm1": {"evidence_groups": {"successes": 96, "total": 109}},
            "parent_rank_perturbation_count": 0,
        },
        "integrity": {
            "exact_offset_rate": 1.0,
            "offset_mismatch_count": 0,
            "gold_content_loss_count": 0,
            "temporal_leak_count": 0,
            "replacement_character_count": 0,
        },
    }


def _cases() -> list[dict]:
    rows = []
    for index in range(95):
        answerable = index < 82
        score = {
            "grounded_answer": index < 73,
            "false_full_answer": 73 <= index < 82,
        }
        rows.append(
            {
                "case_id": f"case_{index}",
                "answerability_target": "answerable_docs" if answerable else "reject",
                "baseline": {
                    "response_mode": "full_answer" if answerable else "reject",
                    "score": score,
                    "cited_chunk_ids": ["chunk_base"] if answerable else [],
                },
                "arm1": {
                    "response_mode": "full_answer" if answerable else "reject",
                    "score": score,
                    "cited_chunk_ids": ["chunk_base", "chunk_added"] if answerable else [],
                },
                "row_children": [
                    {
                        "selected": [
                            {
                                "fact_id": f"fact_{index}",
                                "value": "25개",
                                "row_text": "| 유니크 | 25개 |",
                            }
                        ]
                    }
                ]
                if answerable
                else [],
            }
        )
    return rows


class PromoteV32RuntimeTest(unittest.TestCase):
    def test_canonical_pointer_resolves_to_immutable_manifest(self) -> None:
        root = Path(__file__).resolve().parents[2]
        pointer = json.loads(
            (root / "data/v3/runtime/canonical_runtime_v3_2.json").read_text(
                encoding="utf-8"
            )
        )
        manifest_path = root / pointer["manifest"]["path"]

        self.assertEqual(
            pointer["status"], "canonical_v3_2_development_default_promoted"
        )
        self.assertEqual(file_sha256(manifest_path), pointer["manifest"]["sha256"])
        self.assertFalse(pointer["production_ready"])

    def test_audit_accepts_additive_nonregression(self) -> None:
        audit = audit_promotion_basis(_report(), _cases())

        self.assertTrue(audit["pass"])
        self.assertEqual(audit["added_citation_count"], 82)
        self.assertEqual(audit["selected_fact_count"], 82)

    def test_audit_rejects_removed_citation_or_changed_response(self) -> None:
        cases = _cases()
        cases[0]["arm1"]["response_mode"] = "partial_answer"
        cases[0]["arm1"]["cited_chunk_ids"] = []

        audit = audit_promotion_basis(_report(), cases)

        self.assertFalse(audit["pass"])
        self.assertFalse(audit["checks"]["response_mode_change_zero"])
        self.assertFalse(audit["checks"]["existing_citation_removed_zero"])


if __name__ == "__main__":
    unittest.main()
