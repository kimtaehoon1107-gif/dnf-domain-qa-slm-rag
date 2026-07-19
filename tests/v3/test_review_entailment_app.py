from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.review_entailment_app import (
    DEFAULT_APP_SOURCE,
    DEFAULT_DRAFT,
    DEFAULT_PACKET,
    DEFAULT_PACKET_MANIFEST,
    DEFAULT_REVIEW_CONTRACT,
    apply_review,
    atomic_write_draft,
    finalize_reviews,
    freeze_smoke_report,
    load_session,
    review_progress,
    save_and_move_with_feedback,
    validate_draft_structure,
)


FROZEN_SMOKE_REPORT = Path(
    "reports/v3/"
    "entailment_review_ui_smoke_9413e64a1c565a42f1ba6f15f1a6c8ed144d6d2c0afc84e929b2d466897101b9.json"
)
FROZEN_SMOKE_REPORT_MD = Path(
    "reports/v3/"
    "entailment_review_ui_smoke_3adf6062448552dcabe6f2bc10616082215d29161ea3404c08fce5d655195b56.md"
)


def _completed_rows(packet: list[dict]) -> list[dict]:
    rows = copy.deepcopy(packet)
    labels = ("support", "contradiction", "insufficient")
    for ordinal, row in enumerate(rows):
        label = labels[ordinal % 3]
        row.update(
            {
                "review_label": label,
                "reviewer_type": "human",
                "reviewer_id": "fixture-reviewer",
                "reviewed_at": "2026-07-18T20:00:00+09:00",
                "decisive_excerpt": row["evidence_text"][:40]
                if label != "insufficient"
                else None,
                "review_rationale": "Every material claim was checked against the official evidence.",
                "needs_adjudication": False,
            }
        )
    return rows


class EntailmentReviewSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packet = read_jsonl(DEFAULT_PACKET)

    def test_new_session_is_read_only_until_first_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft_path = Path(temporary) / "draft.jsonl"
            packet, rows, status = load_session(DEFAULT_PACKET, draft_path)
            self.assertEqual(packet, rows)
            self.assertFalse(draft_path.exists())
            self.assertIn("새 검수 세션", status)
            self.assertEqual(review_progress(rows)["remaining"], 40)

    def test_review_save_and_reload_preserve_immutable_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft_path = Path(temporary) / "draft.jsonl"
            excerpt = self.packet[0]["evidence_text"][:40]
            rows = apply_review(
                self.packet,
                0,
                "support",
                "fixture-reviewer",
                excerpt,
                "The claim is directly supported by the copied official excerpt.",
                False,
                reviewed_at="2026-07-18T20:00:00+09:00",
            )
            validate_draft_structure(self.packet, rows)
            draft_sha = atomic_write_draft(draft_path, rows)
            _, reloaded, _ = load_session(DEFAULT_PACKET, draft_path)
            self.assertEqual(rows, reloaded)
            self.assertEqual(file_sha256(draft_path), draft_sha)
            self.assertEqual(review_progress(reloaded)["reviewed"], 1)

    def test_invalid_reviewer_rationale_and_excerpt_are_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            apply_review(
                self.packet,
                0,
                "support",
                "codex",
                "not in evidence",
                "short",
                False,
            )

    def test_ui_validation_error_preserves_form_and_explains_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft_path = Path(temporary) / "draft.jsonl"
            skip = {"skip": True}
            result = save_and_move_with_feedback(
                self.packet,
                self.packet,
                0,
                "support",
                "fixture-reviewer",
                "not present in evidence",
                "The copied excerpt should be checked against official evidence.",
                False,
                1,
                draft_path,
                skip,
            )
            self.assertEqual(len(result), 14)
            self.assertEqual(result[0], self.packet)
            self.assertEqual(result[1], 0)
            self.assertEqual(result[2:12], (skip,) * 10)
            self.assertIn("근거 문구가 evidence_text에", result[13])
            self.assertFalse(draft_path.exists())

class EntailmentReviewExportTest(unittest.TestCase):
    def test_incomplete_rows_cannot_be_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_path = root / "data/v3/evaluation/packet.jsonl"
            source_path = root / "src/v3/app.py"
            packet_path.parent.mkdir(parents=True)
            source_path.parent.mkdir(parents=True)
            packet_path.write_bytes(DEFAULT_PACKET.read_bytes())
            source_path.write_text("# fixture\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                finalize_reviews(
                    root, packet_path, read_jsonl(packet_path), source_path
                )

    def test_completed_reviews_export_content_addressed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_path = root / "data/v3/evaluation/packet.jsonl"
            source_path = root / "src/v3/app.py"
            packet_path.parent.mkdir(parents=True)
            source_path.parent.mkdir(parents=True)
            packet_path.write_bytes(DEFAULT_PACKET.read_bytes())
            source_path.write_text("# fixture\n", encoding="utf-8")
            rows = _completed_rows(read_jsonl(packet_path))
            first = finalize_reviews(root, packet_path, rows, source_path)
            second = finalize_reviews(root, packet_path, rows, source_path)
            self.assertEqual(first, second)
            review_path = Path(first["reviews_path"])
            manifest_path = Path(first["manifest_path"])
            self.assertEqual(file_sha256(review_path), first["reviews_sha256"])
            self.assertEqual(file_sha256(manifest_path), first["manifest_sha256"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["completion_audit"]["ready_for_scoring"])
            self.assertFalse(manifest["use_restrictions"]["training_allowed"])


class EntailmentReviewUISmokeTest(unittest.TestCase):
    def test_smoke_report_freezes_deterministically(self) -> None:
        first = freeze_smoke_report(
            Path.cwd(),
            DEFAULT_PACKET,
            DEFAULT_PACKET_MANIFEST,
            DEFAULT_APP_SOURCE,
            DEFAULT_REVIEW_CONTRACT,
            DEFAULT_DRAFT,
        )
        second = freeze_smoke_report(
            Path.cwd(),
            DEFAULT_PACKET,
            DEFAULT_PACKET_MANIFEST,
            DEFAULT_APP_SOURCE,
            DEFAULT_REVIEW_CONTRACT,
            DEFAULT_DRAFT,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["decision"]["ui_contract"], "GO")
        self.assertEqual(first["decision"]["human_review"], "PENDING")
        self.assertEqual(first["decision"]["generator_entry"], "NO-GO")
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_SMOKE_REPORT))
        self.assertEqual(
            first["report_markdown_sha256"], file_sha256(FROZEN_SMOKE_REPORT_MD)
        )


if __name__ == "__main__":
    unittest.main()
