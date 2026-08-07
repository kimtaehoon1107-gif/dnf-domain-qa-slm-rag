from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _serialize_jsonl, write_immutable
from src.v3.prepare_authored_canary import (
    DEFAULT_APP_SOURCE,
    DEFAULT_CHUNKS,
    DEFAULT_CONTRACT,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_PLAN,
    DEFAULT_SOURCE,
    _build_evaluation_dataset,
    apply_review,
    audit_authored_candidates,
    build_authored_candidates,
    carry_forward_approved_reviews,
    finalize_independent_review,
    validate_review_structure,
)
from src.v3.review_authored_canary_app import (
    atomic_write_canary_draft,
    load_session,
    next_review_index,
)


ROOT = Path(__file__).resolve().parents[2]


def _build_candidates() -> list[dict]:
    plan_path = ROOT / DEFAULT_PLAN
    return build_authored_candidates(
        read_jsonl(plan_path),
        read_jsonl(ROOT / DEFAULT_CHUNKS),
        read_jsonl(ROOT / DEFAULT_DOCUMENTS),
        file_sha256(plan_path),
    )


class PrepareAuthoredCanaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidates = _build_candidates()
        cls.dev_rows = read_jsonl(ROOT / DEFAULT_DEV_SET)
        cls.chunks = read_jsonl(ROOT / DEFAULT_CHUNKS)

    def test_candidate_audit_passes_preregistered_constraints(self) -> None:
        audit = audit_authored_candidates(
            self.candidates, self.dev_rows, self.chunks
        )

        self.assertTrue(audit["gate_pass"])
        self.assertEqual(len(self.candidates), 32)
        self.assertEqual(set(audit["source_counts"].values()), {4})
        self.assertLess(
            audit["max_dev_question_token_jaccard"]["score"], 0.50
        )
        self.assertEqual(audit["normalized_exact_question_overlap_count"], 0)
        self.assertEqual(audit["partial_disclaimer_count"], 5)
        self.assertEqual(audit["false_realtime_evidence_exposure"], [])

    def test_evaluation_dataset_has_stable_zero_based_query_order(self) -> None:
        reviewed = copy.deepcopy(self.candidates)
        for row in reviewed:
            row.update(
                {
                    "independent_review_decision": "approve",
                    "independent_reviewer_type": "human",
                    "independent_reviewer_id": "independent_human",
                    "independent_reviewed_at": "2026-07-19T12:00:00+09:00",
                    "independent_review_rationale": "질문과 근거를 독립적으로 확인했습니다.",
                }
            )

        dataset = _build_evaluation_dataset(reviewed)

        self.assertEqual(
            [row["query_ordinal"] for row in dataset], list(range(32))
        )

    def test_review_cannot_mutate_question_or_gold(self) -> None:
        reviewed = copy.deepcopy(self.candidates)
        reviewed[0]["question_text"] += " 변경"

        with self.assertRaisesRegex(RuntimeError, "Immutable authored canary field"):
            validate_review_structure(self.candidates, reviewed)

    def test_review_rejects_author_and_corrupted_rationale(self) -> None:
        with self.assertRaises(RuntimeError):
            apply_review(
                self.candidates,
                0,
                "approve",
                self.candidates[0]["author_id"],
                "작성자가 자기 질문을 승인하면 안 됩니다.",
            )
        with self.assertRaises(RuntimeError):
            apply_review(
                self.candidates,
                0,
                "approve",
                "independent_human",
                "??????????",
            )

    def test_only_identical_approved_candidates_are_carried_forward(self) -> None:
        prior = copy.deepcopy(self.candidates)
        for row in prior:
            row.update(
                {
                    "independent_review_decision": "approve",
                    "independent_reviewer_type": "human",
                    "independent_reviewer_id": "independent_human",
                    "independent_reviewed_at": "2026-07-19T12:00:00+09:00",
                    "independent_review_rationale": "질문과 근거를 독립적으로 확인했습니다.",
                }
            )
        revised = copy.deepcopy(self.candidates)
        revised[0]["candidate_id"] += "_revised"
        revised[0]["question_text"] += " 수정"

        carried, audit = carry_forward_approved_reviews(revised, prior)

        self.assertEqual(audit["carried_approved_count"], 31)
        self.assertEqual(audit["pending_review_count"], 1)
        self.assertIsNone(carried[0]["independent_review_decision"])
        self.assertTrue(
            all(row["independent_review_decision"] == "approve" for row in carried[1:])
        )

    def test_all_approved_review_freeze_is_content_reproducible(self) -> None:
        reviewed = copy.deepcopy(self.candidates)
        for row in reviewed:
            row.update(
                {
                    "independent_review_decision": "approve",
                    "independent_reviewer_type": "human",
                    "independent_reviewer_id": "independent_human",
                    "independent_reviewed_at": "2026-07-19T12:00:00+09:00",
                    "independent_review_rationale": (
                        "질문과 정답 및 인용 근거를 독립적으로 확인했습니다."
                    ),
                }
            )

        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet = root / "data/v3/evaluation/candidate.jsonl"
                source = root / DEFAULT_SOURCE
                app_source = root / DEFAULT_APP_SOURCE
                contract = root / DEFAULT_CONTRACT
                write_immutable(
                    packet,
                    _serialize_jsonl(self.candidates, lambda row: row["slot_ordinal"]),
                )
                for original, target in (
                    (ROOT / DEFAULT_SOURCE, source),
                    (ROOT / DEFAULT_APP_SOURCE, app_source),
                    (ROOT / DEFAULT_CONTRACT, contract),
                ):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, target)
                results.append(
                    finalize_independent_review(
                        root, packet, reviewed, source, app_source, contract
                    )
                )

        self.assertEqual(results[0]["reviews_sha256"], results[1]["reviews_sha256"])
        self.assertEqual(results[0]["dataset_sha256"], results[1]["dataset_sha256"])
        self.assertEqual(results[0]["manifest_sha256"], results[1]["manifest_sha256"])
        self.assertEqual(results[0]["report_sha256"], results[1]["report_sha256"])
        self.assertEqual(results[0]["rejected_count"], 0)

    def test_canary_draft_uses_slot_ordinal_and_round_trips(self) -> None:
        rows = apply_review(
            self.candidates,
            0,
            "approve",
            "independent_human",
            "질문과 근거를 독립적으로 확인했습니다.",
            reviewed_at="2026-07-19T12:00:00+09:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "packet.jsonl"
            draft_path = Path(directory) / "draft.jsonl"
            write_immutable(
                packet_path,
                _serialize_jsonl(
                    self.candidates, lambda row: row["slot_ordinal"]
                ),
            )
            draft_sha = atomic_write_canary_draft(draft_path, rows)
            _, reloaded, _ = load_session(packet_path, draft_path)
            self.assertEqual(file_sha256(draft_path), draft_sha)

        self.assertEqual(reloaded, rows)

    def test_navigation_skips_carried_approved_rows(self) -> None:
        rows = copy.deepcopy(self.candidates)
        for index, row in enumerate(rows):
            if index not in {1, 5, 6}:
                row["independent_review_decision"] = "approve"

        self.assertEqual(next_review_index(rows, 1, 1), 5)
        self.assertEqual(next_review_index(rows, 6, -1), 5)


if __name__ == "__main__":
    unittest.main()
