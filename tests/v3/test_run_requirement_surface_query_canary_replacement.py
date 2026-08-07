from __future__ import annotations

from pathlib import Path

import pytest

from src.v3 import run_requirement_surface_query_canary_replacement as replacement


def test_missing_environment_fails_before_any_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_BASE_URL"):
        replacement.run_replacement(
            root=tmp_path,
            reviewed_path=tmp_path / "reviewed.jsonl",
            reviewed_manifest_path=tmp_path / "reviewed_manifest.json",
            superseded_authorization_path=tmp_path / "old_authorization.json",
            started_ledger_path=tmp_path / "started.json",
            approved_by="human",
            planner_model="qwen3:8b",
        )

    assert list(tmp_path.rglob("*.json")) == []


def test_replacement_metadata_is_preregistered() -> None:
    assert replacement.ABORT_REASON == (
        "aborted_before_first_question_missing_openai_env"
    )
    assert replacement.EXPECTED_REVIEWED_SHA256.startswith("533a4b03")
    assert replacement.EXPECTED_EVALUATOR_SHA256.startswith("9515a489")
    assert replacement.SUPERSEDED_AUTHORIZATION_SHA256.startswith("4285b641")
    assert replacement.SUPERSEDED_STARTED_LEDGER_SHA256.startswith("8506e75a")
