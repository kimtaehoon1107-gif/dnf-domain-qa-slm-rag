from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.v3.run_product_free_rag_a5_one_shot as runner
from src.io_utils import read_jsonl


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sealed_item(root: Path, relative_path: str) -> dict[str, str]:
    path = root / relative_path
    return {
        "path": relative_path,
        "sha256": runner.sha256_path(path),
    }


def _minimal_manifest(root: Path) -> dict:
    for relative_path in (
        "code.py",
        "snapshot.json",
        "overlay.jsonl",
        "index.bin",
        "candidate.jsonl",
        "review.csv",
        "prefreeze.json",
        "validation.json",
        "frozen.jsonl",
    ):
        _write(root / relative_path, f"{relative_path}\n")
    return {
        "manifest_schema_version": runner.EXPECTED_MANIFEST_SCHEMA,
        "status": "human_reviewed_frozen_ready_for_exactly_one_execution",
        "permissions": {
            "sealed_scoring_allowed": True,
            "execution_allowed": True,
            "training_allowed": False,
            "maximum_execution_attempts": 1,
            "rerun_after_results_opened": False,
        },
        "audit": {"gate_pass": True},
        "candidate_input": _sealed_item(root, "candidate.jsonl"),
        "human_review": {
            **_sealed_item(root, "review.csv"),
            "approved_rows": 32,
        },
        "prefreeze": {
            "manifest": _sealed_item(root, "prefreeze.json"),
            "validation": _sealed_item(root, "validation.json"),
        },
        "model": {
            "tag": runner.MODEL_TAG,
            "blob_sha256": runner.MODEL_BLOB_SHA256,
            "num_ctx": 8192,
        },
        "pipeline": {
            "name": "product_free_rag_v1",
            "runtime_snapshot": "snapshot.json",
            "candidate_augmentation": "corpus_metadata_identity_shortlist",
            "evidence_units": "explicit_question_surface E/T refs max8",
            "generation_calls": 1,
            "verifier": "product_minimal_verifier",
            "verifier_extensions": [
                "subject_evidence_binding",
                "question_surface_responsiveness",
                "redundant_same_subject_pruning",
            ],
            "generic_server_clarification": "bounded_underspecified_question_guard",
            "execution_semantics": (
                "durable_start_then_at_most_once_no_retry_after_indeterminate_interrupt"
            ),
        },
        "frozen_hashes": [
            _sealed_item(root, relative_path)
            for relative_path in (
                "code.py",
                "snapshot.json",
                "overlay.jsonl",
                "index.bin",
                "candidate.jsonl",
                "review.csv",
                "prefreeze.json",
                "validation.json",
            )
        ],
        "frozen_set": {
            **_sealed_item(root, "frozen.jsonl"),
            "row_count": 32,
        },
    }


def test_manifest_verifier_requires_every_runtime_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "FROZEN_CODE_PATHS", (Path("code.py"),))
    monkeypatch.setattr(runner, "DEFAULT_RUNTIME_SNAPSHOT", Path("snapshot.json"))
    monkeypatch.setattr(runner, "DEFAULT_TEMPORAL_OVERLAY", Path("overlay.jsonl"))
    monkeypatch.setattr(
        runner,
        "collect_runtime_artifact_paths",
        lambda root, snapshot: [root / "index.bin"],
    )
    manifest = _minimal_manifest(tmp_path)

    assert runner.verify_freeze_manifest(manifest, root=tmp_path) == (
        tmp_path / "frozen.jsonl"
    )

    manifest["frozen_hashes"] = [
        item for item in manifest["frozen_hashes"] if item["path"] != "index.bin"
    ]
    with pytest.raises(RuntimeError, match="omitted sealed inputs"):
        runner.verify_freeze_manifest(manifest, root=tmp_path)


def test_started_without_result_is_never_selected_for_a_second_call() -> None:
    events = [
        {"event": "started", "candidate_id": "candidate-1"},
        {"event": "started", "candidate_id": "candidate-2"},
    ]
    records = [{"type": "case", "candidate_id": "candidate-1"}]

    assert runner._started_without_result(events, records) == {"candidate-2"}


def test_one_shot_lock_rejects_a_concurrent_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "one-shot.lock"

    with runner._exclusive_run_lock(lock_path):
        with pytest.raises(RuntimeError, match="another Product A5"):
            with runner._exclusive_run_lock(lock_path):
                pass


def test_resume_records_indeterminate_slot_without_calling_it_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_path = tmp_path / "frozen.jsonl"
    frozen_rows = [
        {
            "slot_ordinal": slot,
            "candidate_id": f"candidate-{slot}",
            "question_text": f"synthetic question {slot}",
            "as_of": "2026-07-31",
            "evaluation_role": runner.EXPECTED_EVALUATION_ROLE,
            "execution_allowed": True,
            "training_allowed": False,
        }
        for slot in range(1, 33)
    ]
    runner._write_jsonl_atomic(frozen_path, frozen_rows)
    manifest_path = tmp_path / "freeze.json"
    _write(
        manifest_path,
        json.dumps(
            {
                "frozen_set": {
                    "path": frozen_path.as_posix(),
                    "sha256": runner.sha256_path(frozen_path),
                    "row_count": 32,
                }
            }
        )
        + "\n",
    )
    manifest_sha256 = runner.sha256_path(manifest_path)
    stem = f"product_free_rag_a5_one_shot_{manifest_sha256}"
    marker_path = tmp_path / "data/v3/evaluation" / f"{stem}_attempt.json"
    journal_path = tmp_path / "data/v3/evaluation" / f"{stem}_journal.jsonl"
    _write(marker_path, "{}\n")
    runner._append_execution_event(
        journal_path,
        {
            "event": "started",
            "freeze_manifest_sha256": manifest_sha256,
            "slot_ordinal": 1,
            "candidate_id": "candidate-1",
        },
    )

    calls: list[str] = []

    class FakeProductFreeRAG:
        def __init__(self, **kwargs) -> None:
            self.device = "cpu"
            self._artifacts = None

        def answer(self, question: str, *, metadata_as_of: str) -> dict:
            calls.append(question)
            return {
                "mode": "answer",
                "latency": {"total_ms": 1},
                "generation": {"usage": {"input_tokens": 1}},
            }

    monkeypatch.setattr(runner, "verify_freeze_manifest", lambda manifest, root: frozen_path)
    monkeypatch.setattr(runner, "run_regression_preflight", lambda root: {"passed": True})
    monkeypatch.setattr(runner, "verify_model", lambda: None)
    monkeypatch.setattr(runner, "ProductFreeRAG", FakeProductFreeRAG)
    monkeypatch.setattr(
        runner,
        "score_case",
        lambda frozen, result, chunks_by_id: {
            "slot_ordinal": frozen["slot_ordinal"],
            "candidate_id": frozen["candidate_id"],
            "question": frozen["question_text"],
            "expected_mode": "answer",
            "actual_mode": "answer",
            "meaning_complete": True,
            "false_full_candidate": False,
            "citation_policy_restored": True,
            "qwen_call_match": True,
            "result": result,
        },
    )
    monkeypatch.setattr(
        runner,
        "summarize",
        lambda rows, **kwargs: {"type": "summary", "go": False},
    )

    result = runner.run_one_shot(
        root=tmp_path,
        freeze_manifest_path=manifest_path,
        device=None,
        timeout=1,
        resume=True,
    )

    assert len(calls) == 31
    assert "synthetic question 1" not in calls
    output_rows = read_jsonl(Path(result["output"]["path"]))
    assert output_rows[0]["candidate_id"] == "candidate-1"
    assert output_rows[0]["error_type"] == "InterruptedExecution"
    assert output_rows[-1]["type"] == "summary"
