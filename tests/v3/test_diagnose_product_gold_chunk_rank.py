from src.v3.diagnose_product_gold_chunk_rank import (
    _primary_decision,
    _rank,
    _rank_bucket,
    _spearman,
)


def test_rank_and_bucket_cover_top200_and_missing() -> None:
    assert _rank(["a", "b", "c"], {"b", "z"}) == 2
    assert _rank(["a"], {"z"}) is None
    assert [_rank_bucket(value) for value in (1, 20, 21, 40, 41, 200, None)] == [
        "1_20",
        "1_20",
        "21_40",
        "21_40",
        "41_200",
        "41_200",
        "null",
    ]


def test_spearman_handles_monotonic_values_and_ties() -> None:
    assert _spearman([1, 2, 3], [10, 20, 30]) == 1.0
    assert _spearman([1, 2, 3], [30, 20, 10]) == -1.0
    assert _spearman([1, 1, 1], [10, 20, 30]) is None


def test_primary_decision_uses_largest_failed_requirement_bucket() -> None:
    rows = [
        {"hybrid_union_rank": 25},
        {"hybrid_union_rank": 30},
        {"hybrid_union_rank": 80},
    ]

    assert _primary_decision(rows)["decision"] == "A_expand_retrieval_depth"
