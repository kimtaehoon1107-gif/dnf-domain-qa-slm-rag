from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.prepare_entailment_adjudication import (
    audit_adjudication_reviews,
    build_adjudication_packet,
    merge_adjudicated_reviews,
    prepare_adjudication,
    review_text_corruption_fields,
)
from src.v3.prepare_entailment_review import REVIEW_FIELDS
from src.v3.review_entailment_app import item_view


FROZEN_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_packet_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl"
)


def _primary_rows() -> tuple[list[dict], list[dict]]:
    packet = copy.deepcopy(read_jsonl(FROZEN_PACKET)[:4])
    rows = copy.deepcopy(packet)
    labels = ("support", "insufficient", "support", "insufficient")
    for ordinal, (row, label) in enumerate(zip(rows, labels, strict=True)):
        row.update(
            {
                "review_label": label,
                "reviewer_type": "human",
                "reviewer_id": "primary-reviewer",
                "reviewed_at": "2026-07-18T20:00:00+09:00",
                "decisive_excerpt": row["evidence_text"][:20]
                if label == "support"
                else None,
                "review_rationale": "Primary human review checked every material claim.",
                "needs_adjudication": ordinal in {0, 2},
            }
        )
    rows[1]["review_rationale"] = "??? ??? ??? ??? human review text"
    return packet, rows


def _completed_adjudication(packet: list[dict]) -> list[dict]:
    rows = copy.deepcopy(packet)
    for row in rows:
        row.update(
            {
                "review_label": "support",
                "reviewer_type": "human",
                "reviewer_id": "adjudicator",
                "reviewed_at": "2026-07-18T21:00:00+09:00",
                "decisive_excerpt": row["evidence_text"][:20],
                "review_rationale": "Second human pass resolved the flagged ambiguity.",
                "needs_adjudication": False,
            }
        )
    return rows


class EntailmentAdjudicationTest(unittest.TestCase):
    def test_packet_contains_only_pending_rows_and_resets_review_fields(self) -> None:
        _, primary = _primary_rows()
        packet = build_adjudication_packet(primary, "a" * 64)
        self.assertEqual(len(packet), 3)
        self.assertEqual(
            {row["adjudication_of_item_id"] for row in packet},
            {row["item_id"] for row in primary[:3]},
        )
        for row in packet:
            self.assertEqual(row["primary_review"]["reviewer_id"], "primary-reviewer")
            self.assertTrue(all(row[field] is None for field in REVIEW_FIELDS))
        corrupted = next(
            row for row in packet if "primary_review_text_corrupted" in row["adjudication_reasons"]
        )
        self.assertEqual(
            review_text_corruption_fields(corrupted["primary_review"] | {
                "review_rationale": corrupted["primary_review"]["rationale"]
            }),
            ["review_rationale"],
        )
        self.assertIn("primary_review", item_view(packet, 0)[3])

    def test_adjudication_audit_does_not_require_all_three_labels(self) -> None:
        _, primary = _primary_rows()
        packet = build_adjudication_packet(primary, "b" * 64)
        reviewed = _completed_adjudication(packet)
        audit = audit_adjudication_reviews(packet, reviewed)
        self.assertTrue(audit["ready_for_merge"])
        self.assertEqual(audit["label_counts"], {"support": 3})

    def test_merge_replaces_only_flagged_review_fields(self) -> None:
        _, primary = _primary_rows()
        packet = build_adjudication_packet(primary, "c" * 64)
        reviewed = _completed_adjudication(packet)
        merged = merge_adjudicated_reviews(primary, packet, reviewed)
        by_id = {row["item_id"]: row for row in merged}
        untouched = primary[3]
        self.assertEqual(by_id[untouched["item_id"]], untouched)
        for row in primary:
            if row["item_id"] != untouched["item_id"]:
                self.assertEqual(by_id[row["item_id"]]["reviewer_id"], "adjudicator")
                self.assertFalse(by_id[row["item_id"]]["needs_adjudication"])

    def test_prepare_freezes_deterministically_without_mutating_primary(self) -> None:
        packet, primary = _primary_rows()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_path = root / "data/v3/evaluation/packet.jsonl"
            draft_path = root / "outputs/v3/annotation/draft.jsonl"
            source_path = root / "src/v3/builder.py"
            contract_path = root / "docs/v3/contract.md"
            packet_path.parent.mkdir(parents=True)
            draft_path.parent.mkdir(parents=True)
            source_path.parent.mkdir(parents=True)
            contract_path.parent.mkdir(parents=True)
            from src.v3.collect_details import _serialize_jsonl

            packet_path.write_bytes(_serialize_jsonl(packet, lambda row: row["item_ordinal"]))
            draft_path.write_bytes(_serialize_jsonl(primary, lambda row: row["item_ordinal"]))
            source_path.write_text("# fixture\n", encoding="utf-8")
            contract_path.write_text("# fixture\n", encoding="utf-8")
            before = file_sha256(draft_path)
            first = prepare_adjudication(
                root, packet_path, draft_path, source_path, contract_path
            )
            second = prepare_adjudication(
                root, packet_path, draft_path, source_path, contract_path
            )
            self.assertEqual(first, second)
            self.assertEqual(file_sha256(draft_path), before)
            self.assertEqual(file_sha256(Path(first["primary_reviews_path"])), before)
            self.assertEqual(
                file_sha256(Path(first["adjudication_packet_path"])),
                first["adjudication_packet_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
