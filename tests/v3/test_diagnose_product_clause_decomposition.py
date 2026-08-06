from src.v3.diagnose_product_clause_decomposition import (
    _decision,
    _grammar_structure,
    _human_judgement,
)


def test_human_judgement_uses_fixed_a6_and_user10_labels() -> None:
    assert _human_judgement("A6", {"slot_ordinal": 3}) == "correct"
    assert _human_judgement("A6", {"slot_ordinal": 22}) == "incorrect"
    assert (
        _human_judgement(
            "USER10",
            {"slot": 4, "expected_judgement": "wrong_before_w1"},
        )
        == "incorrect"
    )
    assert (
        _human_judgement(
            "USER10",
            {"slot": 5, "expected_judgement": "single_turn_gold"},
        )
        == "deferred"
    )


def test_decision_stops_when_gap_is_rare() -> None:
    result = _decision(
        total_count=202,
        gap_count=9,
        correct_count=26,
        correct_gap_count=1,
        incorrect_count=15,
        incorrect_gap_count=8,
    )
    assert result["verdict"] == "gap_rare_stop"
    assert result["proceed_to_s2"] is False


def test_decision_proceeds_only_at_two_x_error_concentration() -> None:
    result = _decision(
        total_count=100,
        gap_count=10,
        correct_count=20,
        correct_gap_count=2,
        incorrect_count=20,
        incorrect_gap_count=4,
    )
    assert result["verdict"] == "error_concentrated_proceed_s2"
    assert result["proceed_to_s2"] is True


def test_decision_stops_without_discrimination() -> None:
    result = _decision(
        total_count=100,
        gap_count=20,
        correct_count=20,
        correct_gap_count=4,
        incorrect_count=20,
        incorrect_gap_count=7,
    )
    assert result["verdict"] == "no_discrimination_stop"
    assert result["proceed_to_s2"] is False


def test_grammar_structure_distinguishes_nominal_and_shadowed_go() -> None:
    nominal = _grammar_structure(
        "퀵계좌이체의 결제 한도와 하루 결제 횟수 제한을 알려줘."
    )
    assert (
        nominal["grammar_structure"]
        == "nominal_coordination_without_predicate_clause"
    )

    shadowed = _grammar_structure(
        "버그를 발견하면 어디에 제보해야 하고, 답변 기한은 며칠이야?"
    )
    assert (
        shadowed["grammar_structure"]
        == "predicate_go_shadowed_by_prior_ec_boundary"
    )
