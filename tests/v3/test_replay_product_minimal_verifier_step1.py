from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.replay_product_minimal_verifier_step1 import (
    DEFAULT_INPUTS,
    DEFAULT_SUPPLEMENTS,
    legacy_required_factual_value_present,
    replay_reports,
)
from src.v3.product_minimal_verifier import (
    _required_factual_value_present,
)


def test_step1_replay_only_relaxes_matching_non_numeric_clause():
    question = "가격은 얼마였고 변환 뒤 어떤 옵션이 유지됐어?"

    assert not legacy_required_factual_value_present(
        question,
        "강화와 마법부여 옵션이 유지됩니다.",
    )
    assert _required_factual_value_present(
        question,
        "강화와 마법부여 옵션이 유지됩니다.",
    )
    assert not legacy_required_factual_value_present(
        question,
        "가격을 확인할 수 있습니다.",
    )
    assert not _required_factual_value_present(
        question,
        "가격을 확인할 수 있습니다.",
    )


def test_step1_replay_does_not_change_non_numeric_false_full_surface():
    question = "상점판매가격과 계정당 구매 제한을 알려줘."
    claim = "계정당 구매 제한이 있으며 교환가능 아이템입니다."

    assert legacy_required_factual_value_present(question, claim)
    assert _required_factual_value_present(question, claim)


def test_saved_output_replay_changes_only_a5_target_claims():
    summary = replay_reports(DEFAULT_INPUTS, DEFAULT_SUPPLEMENTS)[-1]

    assert summary["effective_unavailable_cases"] == []
    assert summary["changed_claim_count"] == 5
    assert summary["tightened_claims"] == []
    assert summary["new_false_full_claims"] == []
    assert {
        (row["dataset"], row["slot_ordinal"])
        for row in summary["loosened_claims"]
    } == {
        ("a5_adaptive", 3),
        ("a5_adaptive", 7),
        ("a5_adaptive", 8),
    }
    assert summary["unchanged_false_full_slots"] == [
        ("a5_adaptive", 4),
        ("a5_adaptive", 12),
        ("new_claim32", 32),
    ]


def test_step3_fixture_registers_slot32_positive_and_negative_pairs():
    root = Path(__file__).resolve().parents[2]
    cases = read_jsonl(
        root
        / "data/v3/evaluation/"
        "product_minimal_verifier_semantic_shadow_registered_cases_20260804.jsonl"
    )
    slot32 = next(row for row in cases if row["slot_ordinal"] == 32)

    assert slot32["relation_query"] == "계정당 구매 제한"
    assert [pair["expected_support"] for pair in slot32["pairs"]] == [
        False,
        False,
        True,
    ]
    assert slot32["full_corpus_shadow_required_before_gate"] is True
