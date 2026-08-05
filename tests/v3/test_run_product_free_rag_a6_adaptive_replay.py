from pathlib import Path

import pytest

from src.io_utils import write_jsonl
from src.v3.run_product_free_rag_a6_adaptive_replay import (
    EVALUATION_ROLE,
    _case_record,
    _load_records,
)


def test_load_records_refuses_overwrite_without_resume(tmp_path: Path) -> None:
    output = tmp_path / "adaptive.jsonl"
    write_jsonl(output, [{"type": "case", "candidate_id": "A6-1"}])

    with pytest.raises(RuntimeError, match="already exists"):
        _load_records(output, resume=False)


def test_load_records_refuses_completed_replay(tmp_path: Path) -> None:
    output = tmp_path / "adaptive.jsonl"
    write_jsonl(output, [{"type": "summary"}])

    with pytest.raises(RuntimeError, match="cannot be rerun"):
        _load_records(output, resume=True)


def test_case_record_is_explicitly_adaptive(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.v3.run_product_free_rag_a6_adaptive_replay.score_case",
        lambda frozen, result, chunks_by_id: {"result": result},
    )

    record = _case_record({}, {"mode": "answer"}, chunks_by_id={})

    assert record["evaluation_role"] == EVALUATION_ROLE
    assert record["adaptive_replay"] is True
    assert record["blind"] is False
    assert record["official_a6_eligible"] is False
