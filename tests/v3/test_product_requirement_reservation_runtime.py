from src.v3.product_evidence_pack import (
    explicit_question_clauses,
    kiwi_independent_requirement_queries,
)
from src.v3.product_free_rag import (
    _atomic_reserve_for_requirement_queries,
    _runtime_requirement_queries,
)


def test_runtime_requirement_queries_fall_back_to_explicit_clauses() -> None:
    question = (
        "해방의 계약은 가격과 이용 기간이 어떻게 되고, "
        "구매하면 특별 보상으로 무엇을 한 번 받아?"
    )

    assert kiwi_independent_requirement_queries(question) == []
    assert _runtime_requirement_queries(question, None) == (
        explicit_question_clauses(question)
    )
    assert len(_runtime_requirement_queries(question, None)) == 3


def test_runtime_requirement_queries_prefer_kiwi_when_available() -> None:
    question = (
        "점검은 몇 시에 시작하고 서버는 어느 날 다시 열릴 예정이었어?"
    )
    kiwi = kiwi_independent_requirement_queries(question)

    assert len(kiwi) == 2
    assert _runtime_requirement_queries(question, None) == kiwi


def test_runtime_requirement_queries_preserve_explicit_override() -> None:
    assert _runtime_requirement_queries(
        "질문",
        [" 첫 요구 ", "첫  요구", "둘째 요구"],
    ) == ["첫 요구", "둘째 요구"]


def test_atomic_reserve_tracks_resolved_requirement_count() -> None:
    assert _atomic_reserve_for_requirement_queries([]) == 1
    assert _atomic_reserve_for_requirement_queries(["한 요구"]) == 1
    assert _atomic_reserve_for_requirement_queries(["첫 요구", "둘째 요구"]) == 3
