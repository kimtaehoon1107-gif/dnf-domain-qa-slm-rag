from __future__ import annotations

import pytest

from src.v3.run_free_simple_rag_temporal_label_ab import (
    _fixed_candidate_seed,
)


def test_fixed_candidate_seed_uses_top5_temporal_case() -> None:
    seed = _fixed_candidate_seed(
        [
            {
                "arm": "top3",
                "case": {"case_id": "cpu_smoke_09"},
            },
            {
                "arm": "top5",
                "case": {"case_id": "cpu_smoke_09"},
                "result": {"candidates": [{"chunk_id": "c1"}]},
            },
        ]
    )

    assert seed["arm"] == "top5"
    assert seed["result"]["candidates"][0]["chunk_id"] == "c1"


def test_fixed_candidate_seed_requires_expected_arm_and_case() -> None:
    with pytest.raises(RuntimeError, match="missing top5 seed"):
        _fixed_candidate_seed(
            [
                {
                    "arm": "top5",
                    "case": {"case_id": "other"},
                }
            ]
        )
