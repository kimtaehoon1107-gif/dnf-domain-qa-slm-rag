from __future__ import annotations

import unittest

from src.v3.typed_evidence_ref import (
    build_evidence_units,
    build_typed_evidence_prompt,
    verify_typed_requirement_selection,
)


def _artifacts(
    text: str,
    *,
    title: str,
) -> tuple[dict, dict, dict]:
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": text,
            "default_exposure": True,
            "status": "current",
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_test",
            "title": title,
            "published_at": "2026-07-01",
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }
    temporal = {
        "d1": {
            "document_id": "d1",
            "revision_id": "r1",
            "validity_state": "current",
            "retrieval_action_current": "allow",
        }
    }
    return chunks, documents, temporal


def _units(
    text: str,
    *,
    title: str,
) -> tuple[dict, dict[str, dict], dict, dict]:
    chunks, documents, temporal = _artifacts(text, title=title)
    units = build_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    return (
        chunks,
        {unit["evidence_ref"]: unit for unit in units},
        documents,
        temporal,
    )


def _ref_containing(
    units_by_ref: dict[str, dict],
    needle: str,
) -> str:
    return next(
        evidence_ref
        for evidence_ref, unit in units_by_ref.items()
        if unit["text"] == needle
    )


class TypedEvidenceRefTemporalValueTypeContractTest(unittest.TestCase):
    def test_prompt_exposes_relation_canonical_value_types(self) -> None:
        text = (
            "던파ON 출석체크는 매일 06시에 초기화됩니다.\n"
            "정기점검 시간은 04:30 ~ 10:00입니다."
        )
        chunks, documents, temporal = _artifacts(
            text,
            title="운영 시간 안내",
        )

        prompt, _ = build_typed_evidence_prompt(
            question="초기화 시각과 점검 시간은 언제야?",
            requirements=[
                {
                    "requirement_id": "reset",
                    "subject": "던파ON 출석체크",
                    "relation": "daily_reset_time",
                    "value_type": "enum",
                },
                {
                    "requirement_id": "maintenance",
                    "subject": "정기점검",
                    "relation": "maintenance_time",
                    "value_type": "date_range",
                },
            ],
            question_time_scope="current",
            as_of="2026-07-22",
            candidate_chunk_ids=["c1"],
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document=temporal,
        )

        self.assertIn(
            '"requirement_id":"reset","subject":"던파ON 출석체크",'
            '"relation":"daily_reset_time","value_type":"time"',
            prompt,
        )
        self.assertIn(
            '"requirement_id":"maintenance","subject":"정기점검",'
            '"relation":"maintenance_time","value_type":"time_range"',
            prompt,
        )

    def test_daily_reset_legacy_enum_with_one_time_is_coerced(
        self,
    ) -> None:
        text = "던파ON 출석체크는 매일 06시에 초기화됩니다."
        chunks, units, _, _ = _units(
            text,
            title="던파ON 출석체크",
        )
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "reset",
                "status": "supported",
                "value_type": "enum",
                "value": "매일 06시",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "reset",
                "subject": "던파ON 출석체크",
                "relation": "daily_reset_time",
                "value_type": "enum",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "supported_exact", audit)
        self.assertEqual(decision["answer"], "6시")
        self.assertEqual(audit["value_type"], "time")
        self.assertEqual(
            audit["value_shape_repair"],
            "legacy_relation_time",
        )

    def test_maintenance_legacy_types_with_two_times_are_coerced(
        self,
    ) -> None:
        text = "정기점검 시간은 04:30 ~ 10:00입니다."
        chunks, units, _, _ = _units(text, title="정기점검")
        evidence_ref = _ref_containing(units, text)
        requirement = {
            "requirement_id": "maintenance",
            "subject": "정기점검",
            "relation": "maintenance_time",
            "value_type": "date_range",
        }

        for legacy_type, value in (
            ("date_range", "04:30/10:00"),
            ("enum", "04:30 ~ 10:00"),
            ("text", "점검 시간은 04:30부터 10:00까지"),
        ):
            with self.subTest(legacy_type=legacy_type):
                decision, audit = verify_typed_requirement_selection(
                    {
                        "requirement_id": "maintenance",
                        "status": "supported",
                        "value_type": legacy_type,
                        "value": value,
                        "evidence_refs": [evidence_ref],
                    },
                    requirement=requirement,
                    question_time_scope="current",
                    evidence_units_by_ref=units,
                    chunks_by_id=chunks,
                    as_of="2026-07-22",
                )

                self.assertEqual(
                    decision["status"],
                    "supported_exact",
                    audit,
                )
                self.assertEqual(
                    decision["answer"],
                    "4시 30분 ~ 10시",
                )
                self.assertEqual(audit["value_type"], "time_range")
                self.assertEqual(
                    audit["value_shape_repair"],
                    "legacy_relation_time_range",
                )

    def test_legacy_coercion_requires_exact_time_count(self) -> None:
        reset_text = "던파ON 출석체크는 매일 06시에 초기화됩니다."
        reset_chunks, reset_units, _, _ = _units(
            reset_text,
            title="던파ON 출석체크",
        )
        reset_ref = _ref_containing(reset_units, reset_text)
        maintenance_text = "정기점검 시간은 04:30 ~ 10:00입니다."
        maintenance_chunks, maintenance_units, _, _ = _units(
            maintenance_text,
            title="정기점검",
        )
        maintenance_ref = _ref_containing(
            maintenance_units,
            maintenance_text,
        )

        cases = [
            (
                {
                    "requirement_id": "reset",
                    "subject": "던파ON 출석체크",
                    "relation": "daily_reset_time",
                    "value_type": "enum",
                },
                {
                    "requirement_id": "reset",
                    "status": "supported",
                    "value_type": "enum",
                    "value": "06:00/07:00",
                    "evidence_refs": [reset_ref],
                },
                reset_units,
                reset_chunks,
            ),
            (
                {
                    "requirement_id": "maintenance",
                    "subject": "정기점검",
                    "relation": "maintenance_time",
                    "value_type": "date_range",
                },
                {
                    "requirement_id": "maintenance",
                    "status": "supported",
                    "value_type": "enum",
                    "value": "04:30",
                    "evidence_refs": [maintenance_ref],
                },
                maintenance_units,
                maintenance_chunks,
            ),
        ]
        for requirement, output, units, chunks in cases:
            with self.subTest(requirement_id=requirement["requirement_id"]):
                decision, audit = verify_typed_requirement_selection(
                    output,
                    requirement=requirement,
                    question_time_scope="current",
                    evidence_units_by_ref=units,
                    chunks_by_id=chunks,
                    as_of="2026-07-22",
                )

                self.assertEqual(decision["status"], "unsupported")
                self.assertIn(
                    "value_type_mismatch",
                    audit["failure_reasons"],
                )

    def test_date_only_maintenance_output_remains_blocked(self) -> None:
        text = (
            "2026년 4월 2일 정기점검 시간은 "
            "04:30 ~ 10:00입니다."
        )
        chunks, units, _, _ = _units(text, title="정기점검")
        evidence_ref = _ref_containing(units, text)

        decision, audit = verify_typed_requirement_selection(
            {
                "requirement_id": "maintenance",
                "status": "supported",
                "value_type": "date_range",
                "value": "2026-04-02/2026-04-02",
                "evidence_refs": [evidence_ref],
            },
            requirement={
                "requirement_id": "maintenance",
                "subject": "정기점검",
                "relation": "maintenance_time",
                "value_type": "date_range",
            },
            question_time_scope="current",
            evidence_units_by_ref=units,
            chunks_by_id=chunks,
            as_of="2026-07-22",
        )

        self.assertEqual(decision["status"], "unsupported")
        self.assertIn("value_type_mismatch", audit["failure_reasons"])
        self.assertNotEqual(
            audit["value_shape_repair"],
            "legacy_relation_time_range",
        )


if __name__ == "__main__":
    unittest.main()
