from src.v3 import product_evidence_pack
from src.v3.diagnose_product_ranking_context_reeval import (
    _gate_kind,
    _target_pack_position,
    ranking_context_arm,
)


def test_ranking_context_shadow_is_full_and_restores_runtime_function() -> None:
    unit = {
        "context_text": (
            "업데이트 > 표 헤더: | 변경 전 | 변경 후 | "
            "> 표 도입: - '질풍' 스킬 개화 옵션이 변경됩니다."
        )
    }
    original = product_evidence_pack._ranking_context_text
    baseline = original(unit)

    with ranking_context_arm(include_table_introducer=True):
        assert product_evidence_pack._ranking_context_text(unit) == unit[
            "context_text"
        ]

    assert product_evidence_pack._ranking_context_text is original
    assert product_evidence_pack._ranking_context_text(unit) == baseline


def test_target_position_and_gate_kind_are_diagnostic_only() -> None:
    pack = [
        {
            "chunk_id": "other",
            "start_char": 1,
            "end_char": 2,
            "unit_kind": "sentence",
        },
        {
            "chunk_id": (
                "chunk_sha256_b85cf9c381f143cf45072d4a3738bdb2bebdba4634eb37cd"
                "962defa2798fc3f6"
            ),
            "start_char": 189,
            "end_char": 224,
            "unit_kind": "sentence",
        },
    ]

    assert _target_pack_position(pack) == 2
    assert _gate_kind("A6-17", "mold_trade_types") == "descriptive_diagnostic"
    assert _gate_kind("A6-7", "base_cooldown_change") == (
        "numeric_date_time_currency"
    )
