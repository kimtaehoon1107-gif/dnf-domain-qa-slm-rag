from src.v3.run_product_latency_l1 import summarize_cases


def _case(*, repeat: int, slot: int, wall_ms: float) -> dict:
    return {
        "repeat": repeat,
        "slot": slot,
        "wall_ms": wall_ms,
        "qwen_called": True,
        "error": None,
        "sequence": (repeat - 1) * 2 + slot,
        "question": f"question-{slot}",
        "started_at": "2026-08-05T00:00:00+09:00",
        "finished_at": "2026-08-05T00:00:01+09:00",
        "latency": {"total_ms": wall_ms},
    }


def test_summary_preserves_round_slot_and_outlier_views() -> None:
    cases = [
        _case(repeat=1, slot=1, wall_ms=10_000),
        _case(repeat=1, slot=2, wall_ms=31_000),
        _case(repeat=2, slot=1, wall_ms=12_000),
        _case(repeat=2, slot=2, wall_ms=20_000),
    ]

    summary = summarize_cases(cases, repeats=2)

    assert summary["overall"]["over_30s_count"] == 1
    assert summary["outliers_by_slot"] == {2: 1}
    assert summary["rounds"][0]["max_ms"] == 31_000
    assert summary["slots"][0]["wall_ms_by_repeat"] == {
        "1": 10_000,
        "2": 12_000,
    }
    assert summary["qwen_call_count"] == 4
    assert summary["diagnostics_hook_enabled"] is False
