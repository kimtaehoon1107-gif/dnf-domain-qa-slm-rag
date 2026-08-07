from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORRECTION = (
    ROOT / "reports/v3/product_free_rag_a6_slot6_readjudication_20260806.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_slot6_readjudication_is_append_only_and_preserves_frozen_set() -> None:
    report = json.loads(CORRECTION.read_text(encoding="utf-8"))
    frozen = report["source_artifacts"]["frozen_set"]
    frozen_path = ROOT / frozen["path"]

    assert frozen["modified"] is False
    assert frozen["sha256_before"] == frozen["sha256_after"]
    assert _sha256(frozen_path) == frozen["sha256_after"]
    assert report["correction_kind"] == "append_only_human_adjudication_layer"


def test_slot6_readjudication_updates_only_the_human_aggregate() -> None:
    report = json.loads(CORRECTION.read_text(encoding="utf-8"))

    assert report["slot_correction"]["slot_ordinal"] == 6
    assert report["slot_correction"]["before"]["human_semantic_correct"] is False
    assert report["slot_correction"]["after"]["human_semantic_correct"] is True
    assert report["slot_correction"]["after"]["human_false_full"] is False
    assert report["aggregate_before"]["semantic_correct"] == 19
    assert report["aggregate_after"]["semantic_correct"] == 20
    assert report["aggregate_after"]["semantic_accuracy"] == 0.625
    assert report["aggregate_after"]["false_full_slots"] == []
    assert report["aggregate_after"]["unsupported_overclaim_slots"] == [22]
    assert report["aggregate_after"]["gold_error_count"] == 1


def test_slot6_readjudication_preserves_one_shot_output() -> None:
    report = json.loads(CORRECTION.read_text(encoding="utf-8"))
    one_shot = report["source_artifacts"]["one_shot_output"]

    assert _sha256(ROOT / one_shot["path"]) == one_shot["sha256"]
