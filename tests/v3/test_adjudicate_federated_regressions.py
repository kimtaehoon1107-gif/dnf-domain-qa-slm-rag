from __future__ import annotations

import json
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.adjudicate_federated_regressions import (
    CLASSIFICATIONS,
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_FEDERATED_CASES,
    DEFAULT_FEDERATED_REPORT,
    MECHANICAL_CLASSIFICATIONS,
    PROPOSALS,
    build_adjudication_rows,
    regression_case_ids,
    summarize,
)
from src.v3.collect_details import _serialize_jsonl


ROOT = Path(__file__).resolve().parents[2]


def _inputs():
    report = json.loads((ROOT / DEFAULT_FEDERATED_REPORT).read_text(encoding="utf-8"))
    rows = build_adjudication_rows(
        report=report,
        evaluation_rows=read_jsonl(ROOT / DEFAULT_DEV) + read_jsonl(ROOT / DEFAULT_CANARY),
        enumeration_rows=read_jsonl(ROOT / DEFAULT_ENUMERATION),
        federated_rows=read_jsonl(ROOT / DEFAULT_FEDERATED_CASES),
        chunks=read_jsonl(ROOT / DEFAULT_CHUNKS),
    )
    return report, rows


def test_frozen_regression_set_and_proposals_are_complete():
    report, rows = _inputs()
    assert regression_case_ids(report) == set(PROPOSALS)
    assert len(rows) == 17
    assert {row["classification"] for row in rows} <= CLASSIFICATIONS
    assert all(not row["original_gold_changed"] for row in rows)
    assert all(not row["sibling_proposal_applied"] for row in rows)
    assert all(not row["weak_4b_semantic_judge_used"] for row in rows)


def test_sibling_proposals_are_cited_equivalent_only_and_not_applied():
    _, rows = _inputs()
    for row in rows:
        cited = {item["chunk_id"] for item in row["federated_quota_citations"]}
        proposed = set(row["proposed_acceptable_sibling_chunk_ids"])
        assert proposed <= cited
        assert bool(proposed) == (row["classification"] == "EQUIVALENT_OFFICIAL")
        expected_status = (
            "confirmed_mechanical"
            if row["classification"] in MECHANICAL_CLASSIFICATIONS
            else "provisional_requires_human_or_strong_judge"
        )
        assert row["classification_status"] == expected_status


def test_strict_and_provisional_metrics_remain_separate():
    report, rows = _inputs()
    summary = summarize(report, rows)
    assert summary["classification_counts"] == {
        "EQUIVALENT_OFFICIAL": 9,
        "NAVIGATION_CONTAMINATION": 3,
        "PARTIAL_SUPPORT": 1,
        "PERSONAL_SUBJECTIVE_LABEL": 1,
        "REAL_WRONG": 3,
    }
    assert summary["strict"] == {
        "baseline_grounded": 73,
        "quota_grounded": 63,
        "quota_false_full": 19,
        "new_false_full_regressions": 17,
        "baseline_grounded_gross_regressions": 17,
        "original_acceptable_set_net_grounded_loss": 10,
    }
    assert summary["provisional_if_all_equivalent_candidates_are_confirmed"] == {
        "equivalent_candidate_count": 9,
        "quota_grounded": 72,
        "quota_false_full": 10,
        "new_false_full_regressions": 8,
    }
    assert summary["sibling_proposal_applied_count"] == 0


def test_review_sheet_serialization_is_deterministic():
    _, rows = _inputs()
    first = _serialize_jsonl(rows, lambda row: row["case_id"])
    second = _serialize_jsonl(list(reversed(rows)), lambda row: row["case_id"])
    assert first == second
