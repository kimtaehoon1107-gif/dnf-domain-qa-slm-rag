from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.v3.adjudicate_product_free_rag_a5 import (
    finalize_review,
    render_review_template,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _artifacts(tmp_path: Path) -> tuple[Path, Path]:
    frozen_rows = []
    records = []
    for slot in range(1, 33):
        candidate_id = f"candidate-{slot}"
        expected_response_mode = "clarification" if slot == 10 else "full_answer"
        expected_mode = "clarification" if slot == 10 else "answer"
        frozen_rows.append(
            {
                "slot_ordinal": slot,
                "candidate_id": candidate_id,
                "question_text": f"synthetic question {slot}",
                "expected_response_mode": expected_response_mode,
            }
        )
        records.append(
            {
                "type": "case",
                "slot_ordinal": slot,
                "candidate_id": candidate_id,
                "question": f"synthetic question {slot}",
                "expected_mode": expected_mode,
                "actual_mode": expected_mode,
                "meaning_complete": True,
                "false_full_candidate": False,
                "unsupported_overclaim_candidate": False,
                "citation_policy_restored": True,
                "requirement_scores": [],
                "result": {
                    "rendered_answer": f"synthetic answer {slot}",
                    "claims": [],
                },
            }
        )
    records.append(
        {
            "type": "summary",
            "status": "provisional_awaiting_human_semantic_review",
            "human_semantic_review_required": True,
            "go": None,
            "gates": {
                "completed_32": True,
                "clear_semantic_accuracy_at_least_80pct": True,
                "false_full_zero": True,
                "unsupported_overclaim_zero": True,
                "citation_policy_restoration_32_of_32": True,
                "generation_errors_zero": True,
                "qwen_call_contract_all_match": True,
                "regression_tests_passed": True,
                "average_input_tokens_at_most_2000": True,
                "p50_at_most_15_seconds": True,
                "p95_at_most_30_seconds": True,
            },
        }
    )
    frozen_path = tmp_path / "frozen.jsonl"
    output_path = tmp_path / "one_shot.jsonl"
    _write_jsonl(frozen_path, frozen_rows)
    _write_jsonl(output_path, records)
    return frozen_path, output_path


def _approve_template(template: Path, reviewed: Path) -> None:
    with template.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    for row in rows:
        row.update(
            {
                "human_semantic_correct": "yes",
                "human_false_full": "no",
                "human_unsupported_overclaim": "no",
                "adjudication_complete": "yes",
                "reviewer_id": "human-reviewer",
                "reviewed_at": "2026-07-31T20:00:00+09:00",
                "review_rationale": "질문과 답변의 의미를 확인함",
            }
        )
    with reviewed.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_final_go_requires_completed_human_semantic_adjudication(
    tmp_path: Path,
) -> None:
    frozen, one_shot = _artifacts(tmp_path)
    template = tmp_path / "template.csv"
    reviewed = tmp_path / "reviewed.csv"
    final = tmp_path / "final.json"
    render_review_template(
        one_shot_output=one_shot,
        frozen_set=frozen,
        output=template,
    )
    _approve_template(template, reviewed)

    result = finalize_review(
        one_shot_output=one_shot,
        frozen_set=frozen,
        review_csv=reviewed,
        output=final,
    )

    assert result["go"] is True
    report = json.loads(final.read_text(encoding="utf-8"))
    assert report["human_review"]["reviewed_rows"] == 32
    assert report["human_review"]["semantic_accuracy"] == 1.0


def test_adjudication_rejects_a_changed_protected_question(tmp_path: Path) -> None:
    frozen, one_shot = _artifacts(tmp_path)
    template = tmp_path / "template.csv"
    reviewed = tmp_path / "reviewed.csv"
    render_review_template(
        one_shot_output=one_shot,
        frozen_set=frozen,
        output=template,
    )
    _approve_template(template, reviewed)
    with reviewed.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    rows[0]["question_text"] = "changed question"
    with reviewed.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(RuntimeError, match="protected field changed"):
        finalize_review(
            one_shot_output=one_shot,
            frozen_set=frozen,
            review_csv=reviewed,
            output=tmp_path / "final.json",
        )
