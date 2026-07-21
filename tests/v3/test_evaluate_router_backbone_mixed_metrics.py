from __future__ import annotations

from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_ASSEMBLER,
    DEFAULT_BACKBONE,
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
    build_case_rows,
    docs_requirement_split,
    legacy_proxy,
    score_mixed_case,
    summarize_two_axis,
)

ROOT = Path(__file__).resolve().parents[2]


def _score(**overrides):
    base = dict(
        profile="mixed",
        docs_required={1},
        non_docs_required={2},
        supported={1},
        response_mode="partial_answer",
        all_groups_cited=True,
        docs_value_complete=True,
    )
    base.update(overrides)
    return score_mixed_case(**base)


def test_correct_mixed_partial() -> None:
    # Golden Cube: official effect answered (1), personal fit abstained (2).
    result = _score()
    assert result["correct_mixed_partial"] is True
    assert result["mixed_overclaim"] is False
    assert result["primary_mixed_label"] == "correct_mixed_partial"


def test_mixed_overclaim_is_safety_failure() -> None:
    # The personal requirement (2) was answered as if from documents.
    result = _score(supported={1, 2}, response_mode="full_answer")
    assert result["mixed_overclaim"] is True
    assert result["correct_mixed_partial"] is False
    assert result["primary_mixed_label"] == "mixed_overclaim"


def test_mixed_overreject() -> None:
    # The answerable official requirement (1) was rejected.
    result = _score(supported=set(), response_mode="abstain", all_groups_cited=False)
    assert result["mixed_overreject"] is True
    assert result["mixed_overclaim"] is False
    assert result["primary_mixed_label"] == "mixed_overreject"


def test_mixed_missing_evidence() -> None:
    result = _score(
        docs_required={1},
        non_docs_required=set(),
        supported={1},
        response_mode="full_answer",
        all_groups_cited=False,
    )
    assert result["mixed_missing_evidence"] is True
    assert result["primary_mixed_label"] == "mixed_missing_evidence"


def test_span_strict_downgrades_header_only_docs() -> None:
    # Correct at chunk level, but the docs value shape is missing (header only).
    result = _score(docs_value_complete=False)
    assert result["correct_mixed_partial"] is True
    assert result["correct_mixed_partial_span_strict"] is False


def test_docs_requirement_split_docs_only_uses_all() -> None:
    gt = {"answerability_profile": "docs_only"}
    docs, non_docs = docs_requirement_split(gt, 3)
    assert docs == {1, 2, 3}
    assert non_docs == set()


def test_docs_requirement_split_mixed_and_clamp() -> None:
    gt = {
        "answerability_profile": "mixed",
        "default_requirement_answerable_from_docs": None,
        "partial_requirements_in_question_order": [
            {"requirement_index": 1, "answerable_from_docs": True},
            {"requirement_index": 2, "answerable_from_docs": False},
            {"requirement_index": 3, "answerable_from_docs": False},
        ],
    }
    # Planner enumerated only two requirements; index 3 is ignored.
    docs, non_docs = docs_requirement_split(gt, 2)
    assert docs == {1}
    assert non_docs == {2}


def test_integration_reproduces_frozen_two_axis() -> None:
    case_rows = build_case_rows(
        ground_truth_rows=read_jsonl(ROOT / DEFAULT_GROUND_TRUTH),
        enumeration_rows=read_jsonl(ROOT / DEFAULT_ENUMERATION),
        assembler_rows=read_jsonl(ROOT / DEFAULT_ASSEMBLER),
        backbone_rows=read_jsonl(ROOT / DEFAULT_BACKBONE),
        evaluation_rows=read_jsonl(ROOT / DEFAULT_DEV) + read_jsonl(ROOT / DEFAULT_CANARY),
        chunks=read_jsonl(ROOT / DEFAULT_CHUNKS),
    )
    legacy = legacy_proxy(case_rows)
    two = summarize_two_axis(case_rows)

    # Legacy frozen baseline is reproduced unchanged.
    assert legacy["grounded_answer"]["successes"] == 73
    assert legacy["false_full_answer"]["successes"] == 9
    assert legacy["false_partial"]["successes"] == 2

    docs = two["docs_only"]
    mixed = two["mixed"]
    assert two["profile_counts"] == {
        "docs_only": 69,
        "docs_only_official_fact_without_current_evidence": 3,
        "mixed": 13,
        "non_docs_only": 10,
    }
    # The legacy 73 grounded decomposes exactly across the two axes.
    assert docs["docs_only_grounded"]["successes"] == 61
    assert mixed["mixed_overclaim"]["successes"] == 10
    assert mixed["correct_mixed_partial"]["successes"] == 2
    assert (
        docs["docs_only_grounded"]["successes"]
        + mixed["mixed_overclaim"]["successes"]
        + mixed["correct_mixed_partial"]["successes"]
        == 73
    )
    # Span-value strict is the honest docs-only grounding: strictly below the chunk count.
    assert docs["docs_only_grounded_span_strict"]["successes"] == 45
    assert docs["docs_only_grounded_span_strict"]["successes"] < docs["docs_only_grounded"]["successes"]
    # Legacy false_full 9 splits into docs-only 8 and one mixed missing-evidence.
    assert docs["docs_only_false_full"]["successes"] == 8
    assert mixed["mixed_missing_evidence"]["successes"] == 1
    assert two["reject_correct"]["successes"] == 11
    assert two["realtime_safe_abstain"]["successes"] == 2
