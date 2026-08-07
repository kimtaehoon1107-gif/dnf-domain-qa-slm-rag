from src.v3.run_free_simple_rag_top3_generation_ab import (
    _score_result,
)


def test_score_accepts_normalized_korean_date() -> None:
    score = _score_result(
        {
            "required_values": ["2026-06-04"],
            "forbidden_values": ["2026-06-02"],
        },
        {
            "response_mode": "full_answer",
            "rendered_answer": "적용일은 6/4입니다.",
            "requirements": [],
        },
    )

    assert score["correct_full"] is True
    assert score["false_full"] is False


def test_score_marks_wrong_full_answer_as_false_full() -> None:
    score = _score_result(
        {
            "required_values": ["2026-06-04"],
            "forbidden_values": ["2026-06-02"],
        },
        {
            "response_mode": "full_answer",
            "rendered_answer": "적용일은 2026.06.02입니다.",
            "requirements": [],
        },
    )

    assert score["correct_full"] is False
    assert score["false_full"] is True
