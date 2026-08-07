from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.freeze_product_free_rag_a5 import (
    DEFAULT_RUNTIME_SNAPSHOT,
    DEFAULT_TEMPORAL_OVERLAY,
    FROZEN_CODE_PATHS,
    MODEL_BLOB_SHA256,
    MODEL_TAG,
    collect_runtime_artifact_paths,
    verify_model,
)
from src.v3.product_free_rag import ProductFreeRAG
from src.v3.score_product_free_rag_a5 import score_case, summarize


RUNNER_VERSION = "product-free-rag-a5-one-shot-runner-v2"
EXPECTED_MANIFEST_SCHEMA = "product-free-rag-a5-freeze-manifest-v2"
EXPECTED_EVALUATION_ROLE = (
    "product_free_rag_a5_human_reviewed_first_one_shot"
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def verify_freeze_manifest(
    manifest: dict[str, Any],
    *,
    root: Path,
) -> Path:
    if manifest.get("manifest_schema_version") != EXPECTED_MANIFEST_SCHEMA:
        raise RuntimeError("unexpected Product A5 freeze manifest schema")
    if manifest.get("status") != "human_reviewed_frozen_ready_for_exactly_one_execution":
        raise RuntimeError("Product A5 freeze manifest is not execution-ready")
    permissions = manifest.get("permissions") or {}
    if not (
        permissions.get("sealed_scoring_allowed") is True
        and permissions.get("execution_allowed") is True
        and permissions.get("training_allowed") is False
        and permissions.get("maximum_execution_attempts") == 1
        and permissions.get("rerun_after_results_opened") is False
    ):
        raise RuntimeError("Product A5 freeze permissions are invalid")
    if manifest.get("audit", {}).get("gate_pass") is not True:
        raise RuntimeError("Product A5 frozen-row audit is not a clean pass")
    if manifest.get("human_review", {}).get("approved_rows") != 32:
        raise RuntimeError("Product A5 human review is not 32/32")
    if manifest.get("model") != {
        "tag": MODEL_TAG,
        "blob_sha256": MODEL_BLOB_SHA256,
        "num_ctx": 8192,
    }:
        raise RuntimeError("Product A5 model seal is invalid")
    pipeline = manifest.get("pipeline") or {}
    if not (
        pipeline.get("name") == "product_free_rag_v1"
        and pipeline.get("runtime_snapshot") == DEFAULT_RUNTIME_SNAPSHOT.as_posix()
        and pipeline.get("candidate_augmentation")
        == "corpus_metadata_identity_shortlist"
        and pipeline.get("evidence_units")
        == "explicit_question_surface E/T refs max8"
        and pipeline.get("generation_calls") == 1
        and pipeline.get("verifier") == "product_minimal_verifier"
        and pipeline.get("verifier_extensions")
        == [
            "subject_evidence_binding",
            "question_surface_responsiveness",
            "redundant_same_subject_pruning",
        ]
        and pipeline.get("generic_server_clarification")
        == "bounded_underspecified_question_guard"
        and pipeline.get("execution_semantics")
        == "durable_start_then_at_most_once_no_retry_after_indeterminate_interrupt"
    ):
        raise RuntimeError("Product A5 pipeline seal is invalid")

    frozen_hashes = manifest.get("frozen_hashes") or []
    sealed_paths: set[str] = set()
    sealed_sha256_by_path: dict[str, str] = {}
    for item in frozen_hashes:
        relative_path = str(item.get("path") or "")
        if not relative_path or relative_path in sealed_paths:
            raise RuntimeError("Product A5 frozen hashes contain a missing or duplicate path")
        sealed_paths.add(relative_path)
        sealed_sha256_by_path[relative_path] = str(item.get("sha256") or "")
        path = _resolve(root, Path(item["path"]))
        try:
            _relative(root, path)
        except ValueError as exc:
            raise RuntimeError(f"frozen path escapes repository: {item['path']}") from exc
        if not path.exists() or sha256_path(path) != item["sha256"]:
            raise RuntimeError(f"frozen input changed: {item['path']}")
    required_paths = {
        *(path.as_posix() for path in FROZEN_CODE_PATHS),
        DEFAULT_RUNTIME_SNAPSHOT.as_posix(),
        DEFAULT_TEMPORAL_OVERLAY.as_posix(),
        *(
            _relative(root, path)
            for path in collect_runtime_artifact_paths(
                root,
                root / DEFAULT_RUNTIME_SNAPSHOT,
            )
        ),
    }
    missing_paths = sorted(required_paths - sealed_paths)
    if missing_paths:
        raise RuntimeError(f"Product A5 freeze manifest omitted sealed inputs: {missing_paths}")
    bound_inputs = {
        "candidate_input": manifest.get("candidate_input") or {},
        "human_review": manifest.get("human_review") or {},
        "prefreeze_manifest": manifest.get("prefreeze", {}).get("manifest") or {},
        "prefreeze_validation": manifest.get("prefreeze", {}).get("validation") or {},
    }
    for label, item in bound_inputs.items():
        relative_path = str(item.get("path") or "")
        if (
            not relative_path
            or sealed_sha256_by_path.get(relative_path) != item.get("sha256")
        ):
            raise RuntimeError(f"Product A5 {label} is not included in the sealed inputs")

    frozen_set = manifest.get("frozen_set") or {}
    if frozen_set.get("row_count") != 32:
        raise RuntimeError("Product A5 frozen set row count is not 32")
    frozen_path = _resolve(root, Path(frozen_set["path"]))
    try:
        _relative(root, frozen_path)
    except ValueError as exc:
        raise RuntimeError("Product A5 frozen set escapes repository") from exc
    if sha256_path(frozen_path) != frozen_set.get("sha256"):
        raise RuntimeError("frozen A5 set SHA mismatch")
    return frozen_path


def run_regression_preflight(root: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/v3/test_product_free_rag.py",
        "tests/v3/test_metadata_query.py",
        "tests/v3/test_freeze_product_free_rag_a5.py",
        "tests/v3/test_score_product_free_rag_a5.py",
        "tests/v3/test_run_product_free_rag_a5_one_shot.py",
        "tests/v3/test_adjudicate_product_free_rag_a5.py",
        "tests/v3/test_product_free_rag_architecture.py",
        "-q",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "passed": completed.returncode == 0,
    }
    if not result["passed"]:
        raise RuntimeError("Product/metadata regression preflight failed")
    return result


def _write_attempt_marker(
    path: Path,
    *,
    manifest_path: Path,
    manifest_sha256: str,
    journal_path: Path,
) -> None:
    value = {
        "runner_version": RUNNER_VERSION,
        "status": "one_shot_started",
        "started_at": _now(),
        "freeze_manifest": {
            "path": manifest_path.as_posix(),
            "sha256": manifest_sha256,
        },
        "execution_journal": journal_path.as_posix(),
        "maximum_execution_attempts": 1,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _append_execution_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _load_execution_journal(
    path: Path,
    *,
    manifest_sha256: str,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = list(read_jsonl(path))
    started: set[str] = set()
    for event in events:
        if event.get("freeze_manifest_sha256") != manifest_sha256:
            raise RuntimeError("execution journal belongs to another freeze manifest")
        if event.get("event") == "started":
            candidate_id = str(event.get("candidate_id") or "")
            if not candidate_id or candidate_id in started:
                raise RuntimeError("execution journal contains a duplicate or missing start")
            started.add(candidate_id)
    return events


def _started_without_result(
    events: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> set[str]:
    started = {
        str(event["candidate_id"])
        for event in events
        if event.get("event") == "started"
    }
    recorded = {
        str(record["candidate_id"])
        for record in records
        if record.get("type") in {"case", "error"}
    }
    return started - recorded


@contextmanager
def _exclusive_run_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another Product A5 one-shot process is active") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _run_one_shot_locked(
    *,
    root: Path,
    freeze_manifest_path: Path,
    device: str | None,
    timeout: float,
    resume: bool,
) -> dict[str, Any]:
    root = root.resolve()
    freeze_manifest_path = _resolve(root, freeze_manifest_path)
    manifest_sha256 = sha256_path(freeze_manifest_path)
    manifest = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    frozen_path = verify_freeze_manifest(manifest, root=root)
    regression = run_regression_preflight(root)
    verify_model()

    result_stem = f"product_free_rag_a5_one_shot_{manifest_sha256}"
    output_path = root / "reports/v3" / f"{result_stem}.jsonl"
    marker_path = root / "data/v3/evaluation" / f"{result_stem}_attempt.json"
    journal_path = root / "data/v3/evaluation" / f"{result_stem}_journal.jsonl"

    records: list[dict[str, Any]] = []
    if marker_path.exists():
        if not resume:
            raise RuntimeError(
                "Product A5 one-shot was already started; use --resume only for an interrupted run"
            )
        records = list(read_jsonl(output_path)) if output_path.exists() else []
        if any(row.get("type") == "summary" for row in records):
            raise RuntimeError("Product A5 results are already open; rerun is forbidden")
    else:
        if resume:
            raise RuntimeError("--resume requires an existing one-shot attempt")
        if output_path.exists():
            raise RuntimeError("one-shot output exists without an attempt marker")
        if journal_path.exists():
            raise RuntimeError("execution journal exists without an attempt marker")
        _write_attempt_marker(
            marker_path,
            manifest_path=freeze_manifest_path,
            manifest_sha256=manifest_sha256,
            journal_path=journal_path,
        )

    frozen_rows = list(read_jsonl(frozen_path))
    if len(frozen_rows) != 32:
        raise RuntimeError(f"expected 32 frozen rows, got {len(frozen_rows)}")
    if any(
        row.get("evaluation_role") != EXPECTED_EVALUATION_ROLE
        or row.get("execution_allowed") is not True
        or row.get("training_allowed") is not False
        for row in frozen_rows
    ):
        raise RuntimeError("frozen A5 row permissions or role are invalid")

    frozen_by_id = {row["candidate_id"]: row for row in frozen_rows}
    if len(frozen_by_id) != 32:
        raise RuntimeError("frozen A5 candidate IDs are not unique")
    recorded_ids = [
        str(row["candidate_id"])
        for row in records
        if row.get("type") in {"case", "error"}
    ]
    if len(recorded_ids) != len(set(recorded_ids)):
        raise RuntimeError("one-shot output contains a duplicate candidate")
    completed_ids = set(recorded_ids)
    if not completed_ids <= set(frozen_by_id):
        raise RuntimeError("one-shot output contains an unknown candidate")
    journal_events = _load_execution_journal(
        journal_path,
        manifest_sha256=manifest_sha256,
    )
    journal_candidate_ids = {
        str(event.get("candidate_id") or "")
        for event in journal_events
        if event.get("candidate_id") is not None
    }
    if not journal_candidate_ids <= set(frozen_by_id):
        raise RuntimeError("execution journal contains an unknown candidate")
    if resume:
        for candidate_id in sorted(
            _started_without_result(journal_events, records),
            key=lambda value: frozen_by_id[value]["slot_ordinal"],
        ):
            frozen = frozen_by_id[candidate_id]
            record = {
                "type": "error",
                "runner_version": RUNNER_VERSION,
                "freeze_manifest_sha256": manifest_sha256,
                "slot_ordinal": frozen["slot_ordinal"],
                "candidate_id": candidate_id,
                "question": frozen["question_text"],
                "error_type": "InterruptedExecution",
                "error": (
                    "the prior process stopped after this slot was durably marked started; "
                    "the slot was not called again to preserve at-most-once execution"
                ),
            }
            records.append(record)
            _write_jsonl_atomic(output_path, records)
            _append_execution_event(
                journal_path,
                {
                    "event": "recovered_as_indeterminate",
                    "recorded_at": _now(),
                    "freeze_manifest_sha256": manifest_sha256,
                    "slot_ordinal": frozen["slot_ordinal"],
                    "candidate_id": candidate_id,
                },
            )
            completed_ids.add(candidate_id)

    rag = ProductFreeRAG(
        root=root,
        model=MODEL_TAG,
        device=device,
        timeout=timeout,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
        handoff_cuda_to_generation=True,
    )
    for frozen in frozen_rows:
        if frozen["candidate_id"] in completed_ids:
            continue
        _append_execution_event(
            journal_path,
            {
                "event": "started",
                "started_at": _now(),
                "freeze_manifest_sha256": manifest_sha256,
                "slot_ordinal": frozen["slot_ordinal"],
                "candidate_id": frozen["candidate_id"],
            },
        )
        try:
            result = rag.answer(
                frozen["question_text"],
                metadata_as_of=frozen["as_of"],
            )
            scored = score_case(
                frozen,
                result,
                chunks_by_id=(
                    rag._artifacts.chunks_by_id
                    if rag._artifacts is not None
                    else {}
                ),
            )
            record = {
                "type": "case",
                "runner_version": RUNNER_VERSION,
                "freeze_manifest_sha256": manifest_sha256,
                **scored,
            }
        except Exception as exc:
            record = {
                "type": "error",
                "runner_version": RUNNER_VERSION,
                "freeze_manifest_sha256": manifest_sha256,
                "slot_ordinal": frozen["slot_ordinal"],
                "candidate_id": frozen["candidate_id"],
                "question": frozen["question_text"],
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        records.append(record)
        _write_jsonl_atomic(output_path, records)
        _append_execution_event(
            journal_path,
            {
                "event": "recorded",
                "recorded_at": _now(),
                "freeze_manifest_sha256": manifest_sha256,
                "slot_ordinal": frozen["slot_ordinal"],
                "candidate_id": frozen["candidate_id"],
                "record_type": record["type"],
            },
        )
        completed_ids.add(frozen["candidate_id"])
        print(
            json.dumps(
                {
                    "slot": frozen["slot_ordinal"],
                    "type": record["type"],
                    "mode": record.get("actual_mode"),
                    "meaning_complete": record.get("meaning_complete"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    case_records = [row for row in records if row.get("type") == "case"]
    error_records = [row for row in records if row.get("type") == "error"]
    if len(case_records) + len(error_records) != 32:
        raise RuntimeError("one-shot ended without one record per frozen row")
    if any(row["candidate_id"] not in frozen_by_id for row in records):
        raise RuntimeError("one-shot output contains an unknown candidate")
    summary = {
        **summarize(
            case_records,
            expected_count=32,
            error_count=len(error_records),
            regression_passed=regression["passed"],
        ),
        "runner_version": RUNNER_VERSION,
        "evaluation_role": EXPECTED_EVALUATION_ROLE,
        "freeze_manifest": {
            "path": freeze_manifest_path.as_posix(),
            "sha256": manifest_sha256,
        },
        "frozen_set": manifest["frozen_set"],
        "query_inputs": "question_only_no_gold_queries_or_subjects",
        "experimental_profile": {
            "identity_shortlist": True,
            "compact_evidence_pack": True,
            "device": rag.device,
        },
        "regression_preflight": regression,
        "execution_journal": {
            "path": journal_path.as_posix(),
            "sha256_before_summary": sha256_path(journal_path),
            "policy": "durable_start_then_at_most_once_no_retry_after_indeterminate_interrupt",
        },
        "errors": error_records,
    }
    _write_jsonl_atomic(output_path, [*records, summary])
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return {
        "output": {
            "path": output_path.as_posix(),
            "sha256": sha256_path(output_path),
        },
        "attempt_marker": marker_path.as_posix(),
        "execution_journal": {
            "path": journal_path.as_posix(),
            "sha256": sha256_path(journal_path),
        },
        "summary": summary,
    }


def run_one_shot(
    *,
    root: Path,
    freeze_manifest_path: Path,
    device: str | None,
    timeout: float,
    resume: bool,
) -> dict[str, Any]:
    root = root.resolve()
    freeze_manifest_path = _resolve(root, freeze_manifest_path)
    manifest_sha256 = sha256_path(freeze_manifest_path)
    lock_path = (
        root
        / "data/v3/evaluation"
        / f"product_free_rag_a5_one_shot_{manifest_sha256}.lock"
    )
    with _exclusive_run_lock(lock_path):
        return _run_one_shot_locked(
            root=root,
            freeze_manifest_path=freeze_manifest_path,
            device=device,
            timeout=timeout,
            resume=resume,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen Product Free RAG A5 set exactly once"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--device")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(
        json.dumps(
            run_one_shot(
                root=args.root,
                freeze_manifest_path=args.freeze_manifest,
                device=args.device,
                timeout=args.timeout,
                resume=args.resume,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
