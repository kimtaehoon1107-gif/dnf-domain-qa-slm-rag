from pathlib import Path

from src.v3.rederive_product_free_rag_failure_attribution import build_rows


ROOT = Path(__file__).resolve().parents[2]


def test_r5_attribution_is_complete_and_uses_no_runtime_generation() -> None:
    rows = build_rows(ROOT)
    requirements = [
        row for row in rows if row["type"] == "requirement_attribution"
    ]
    summary = rows[-1]

    assert len(requirements) == 21
    assert summary["stage_counts"] == {
        "S1": 1,
        "S2": 5,
        "S3": 3,
        "S4": 4,
        "S5": 1,
        "S?": 7,
    }
    assert summary["actual_failed_supported_requirement_count"] == 14
    assert summary["qwen_calls"] == 0
    assert summary["runtime_modified"] is False


def test_r5_corrects_known_overlap_misattributions() -> None:
    rows = {
        (row["slot_ordinal"], row["requirement_id"]): row
        for row in build_rows(ROOT)
        if row["type"] == "requirement_attribution"
    }

    assert rows[(1, "transfer_limits")]["attribution_stage"] == "S2"
    assert rows[(7, "base_cooldown_change")]["attribution_stage"] == "S2"
    assert rows[(26, "contract_price_duration")]["attribution_stage"] == "S2"
    assert rows[(22, "bug_reporting_channel")]["attribution_stage"] == "S1"


def test_r5_separates_strict_and_descriptive_value_presence() -> None:
    summary = build_rows(ROOT)[-1]

    assert summary["value_presence_by_group"] == {
        "descriptive": {
            "boolean_excluded": 1,
            "value_present_full": 3,
            "value_present_none": 2,
        },
        "numeric_date_time_currency": {
            "value_present_full": 11,
            "value_present_none": 1,
            "value_present_partial": 3,
        },
    }
