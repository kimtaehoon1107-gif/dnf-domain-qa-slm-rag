from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_question_partial_fallback_ab import DEFAULT_GROUND_TRUTH
from src.v3.evaluate_router_backbone_mixed_metrics import DEFAULT_CANARY, DEFAULT_DEV
from src.v3.mixed_answerability_structure import (
    analyze_first_person_clause,
    classify_answerability_v3_2,
)

ROOT = Path(__file__).resolve().parents[2]


def test_structural_signal_detects_unplanned_personal_calculation_clause():
    question = (
        "마일리지샵 시즌7에서 마일리지 소멸 시점과 일일 획득 한도를 "
        "알려주고, 내 마일리지가 몇 남을지 계산해줘."
    )
    result = classify_answerability_v3_2(question)

    assert result["label"] == "partial"
    assert result["reason"] == "official_fact_plus_structural_first_person_clause"
    assert result["structure"]["detected"] is True
    assert result["structure"]["domain_keyword_rule_count"] == 0


def test_single_official_or_single_personal_clause_is_not_promoted_to_partial():
    assert analyze_first_person_clause("마일리지 소멸 시점을 알려줘.")["detected"] is False
    assert analyze_first_person_clause("내 마일리지가 몇 남았어?")["detected"] is False


def test_frozen_95_has_full_mixed_recall_and_zero_docs_false_partial():
    truth = {row["case_id"]: row for row in read_jsonl(ROOT / DEFAULT_GROUND_TRUTH)}
    questions = {
        row["dev_id"]: row["question"]
        for row in read_jsonl(ROOT / DEFAULT_DEV) + read_jsonl(ROOT / DEFAULT_CANARY)
    }
    predicted_partial = {
        case_id
        for case_id, question in questions.items()
        if classify_answerability_v3_2(question)["label"] == "partial"
    }
    mixed = {
        case_id
        for case_id, row in truth.items()
        if row["answerability_profile"] == "mixed"
    }
    docs = {
        case_id
        for case_id, row in truth.items()
        if row["answerability_profile"] == "docs_only"
    }

    assert len(mixed) == 13
    assert mixed <= predicted_partial
    assert not (docs & predicted_partial)
