from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.collect_details import _serialize_jsonl
from src.v3.prepare_evidence_adjudication import (
    DEFAULT_CASES,
    DEFAULT_CHUNKS,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_REPORT,
    REVIEW_FIELDS,
    apply_review,
    build_evidence_adjudication_packet,
    build_overlay,
    finalize_evidence_adjudication,
    review_text_corruption_fields,
    validate_review_row,
    validate_review_structure,
)
from src.v3.review_evidence_adjudication_app import review_progress


class EvidenceAdjudicationPacketTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def setUp(self) -> None:
        self.report_path = self.ROOT / DEFAULT_REPORT
        self.report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.packet = build_evidence_adjudication_packet(
            read_jsonl(self.ROOT / DEFAULT_DEV_SET),
            read_jsonl(self.ROOT / DEFAULT_CASES),
            read_jsonl(self.ROOT / DEFAULT_CHUNKS),
            read_jsonl(self.ROOT / DEFAULT_DOCUMENTS),
            self.report,
            hashlib.sha256(self.report_path.read_bytes()).hexdigest(),
        )

    def test_packet_contains_all_three_canonical_mismatches(self) -> None:
        self.assertEqual(len(self.packet), 3)
        self.assertEqual(
            {row["question"] for row in self.packet},
            {
                "비인가 프로그램 사용 주의사항은 뭐야?",
                "서약 / 결정 사용 방법은 뭐야?",
                "세라샵 아이템 청약철회는 구입 후 며칠 안에 문의해야 하고, 언제 불가능해?",
            },
        )
        for row in self.packet:
            self.assertTrue(all(row[field] is None for field in REVIEW_FIELDS))
            self.assertIn(
                " ".join(row["candidate_preferred_quote"].split()),
                " ".join(row["candidate_evidence_text"].split()),
            )

    def test_review_decisions_map_to_evaluation_overlay(self) -> None:
        rows = apply_review(
            self.packet,
            0,
            "confirm_search_failure",
            "human-reviewer",
            "",
            "acceptable gold가 후보에 없으므로 검색 실패를 유지합니다.",
            reviewed_at="2026-07-19T20:00:00+09:00",
        )
        rows = apply_review(
            rows,
            1,
            "accept_alternative",
            "human-reviewer",
            rows[1]["candidate_preferred_quote"],
            "후보 문장이 사용 방법을 완전하고 직접적으로 설명합니다.",
            reviewed_at="2026-07-19T20:01:00+09:00",
        )
        rows = apply_review(
            rows,
            2,
            "reject_alternative",
            "human-reviewer",
            "",
            "후보는 문의 기한과 불가 조건의 직접 연결이 부족합니다.",
            reviewed_at="2026-07-19T20:02:00+09:00",
        )
        overlay = build_overlay(rows)
        self.assertFalse(overlay[0]["approved"])
        self.assertTrue(overlay[0]["search_failure_confirmed"])
        self.assertTrue(overlay[1]["acceptable_sibling_addition"])
        self.assertFalse(overlay[2]["approved"])
        validate_review_structure(self.packet, rows)

    def test_immutable_field_change_is_rejected(self) -> None:
        changed = copy.deepcopy(self.packet)
        changed[0]["candidate_chunk_id"] = "changed"
        with self.assertRaisesRegex(RuntimeError, "Immutable field changed"):
            validate_review_structure(self.packet, changed)

    def test_question_mark_corruption_is_rejected_and_remains_pending(self) -> None:
        rows = apply_review(
            self.packet,
            1,
            "accept_alternative",
            "human-reviewer",
            self.packet[1]["candidate_preferred_quote"],
            "후보 문장이 사용 방법을 완전하고 직접적으로 설명합니다.",
            reviewed_at="2026-07-19T20:01:00+09:00",
        )
        rows[1]["review_rationale"] = "?? ?????? ?? ??? ??????."

        self.assertEqual(
            review_text_corruption_fields(rows[1]), ["review_rationale"]
        )
        with self.assertRaisesRegex(RuntimeError, "인코딩 손상"):
            validate_review_row(rows[1], complete=True)

        progress = review_progress(rows)
        self.assertEqual(progress["reviewed"], 0)
        self.assertEqual(progress["remaining"], 3)
        self.assertEqual(progress["invalid"], 1)

    def test_finalize_is_content_addressed_and_reproducible(self) -> None:
        rows = copy.deepcopy(self.packet)
        for index, row in enumerate(rows):
            decision = (
                "confirm_search_failure"
                if row["mismatch_reason"] == "acceptable_chunk_not_in_routed_candidates"
                else "accept_alternative"
            )
            rows = apply_review(
                rows,
                index,
                decision,
                "human-reviewer",
                row["candidate_preferred_quote"]
                if decision == "accept_alternative"
                else "",
                "후보 공식 문장이 질문에 필요한 내용을 직접 지지합니다.",
                reviewed_at=f"2026-07-19T20:0{index}:00+09:00",
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_path = root / "data/v3/evaluation/packet.jsonl"
            builder_path = root / "src/v3/builder.py"
            app_path = root / "src/v3/app.py"
            contract_path = root / "docs/v3/contract.md"
            packet_path.parent.mkdir(parents=True)
            builder_path.parent.mkdir(parents=True)
            app_path.parent.mkdir(parents=True, exist_ok=True)
            contract_path.parent.mkdir(parents=True)
            packet_path.write_bytes(
                _serialize_jsonl(self.packet, lambda row: row["item_ordinal"])
            )
            builder_path.write_text("# builder\n", encoding="utf-8")
            app_path.write_text("# app\n", encoding="utf-8")
            contract_path.write_text("# contract\n", encoding="utf-8")
            first = finalize_evidence_adjudication(
                root, packet_path, rows, builder_path, app_path, contract_path
            )
            second = finalize_evidence_adjudication(
                root, packet_path, rows, builder_path, app_path, contract_path
            )
            self.assertEqual(first, second)
            self.assertEqual(
                hashlib.sha256(Path(first["overlay_path"]).read_bytes()).hexdigest(),
                first["overlay_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
