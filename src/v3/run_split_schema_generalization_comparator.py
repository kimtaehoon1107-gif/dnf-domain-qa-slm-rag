from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.evaluate_grounded_llm_replay import run_fixed_requirement_replay
from src.v3.score_typed_evidence_ref_generalization import (
    score_generalization_cases,
)


RUNNER_VERSION = "split-schema-generalization-comparator-v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _verify_hashes(root: Path, rows: list[dict[str, Any]]) -> None:
    mismatches = []
    for row in rows:
        path = root / row["path"]
        actual = file_sha256(path)
        if actual != row["sha256"]:
            mismatches.append(
                {"path": row["path"], "expected": row["sha256"], "actual": actual}
            )
    if mismatches:
        raise RuntimeError(f"comparator input/code hashes changed: {mismatches}")


def _verify_model(model: dict[str, Any]) -> None:
    tag = model["requested_tag"]
    completed = subprocess.run(
        ["ollama", "show", tag, "--modelfile"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"FROM .+sha256-([0-9a-f]{64})", completed.stdout)
    if match is None or match.group(1) != model["ollama_blob_sha256"]:
        raise RuntimeError("Ollama model blob differs from comparator contract")
    if f"PARAMETER num_ctx {model['num_ctx']}" not in completed.stdout:
        raise RuntimeError("Ollama model num_ctx differs from comparator contract")
    with urlopen("http://localhost:11434/api/tags", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if tag not in {row["name"] for row in payload.get("models", [])}:
        raise RuntimeError("Ollama HTTP service does not expose the comparator model")


def _compatible_reviewed(row: dict[str, Any]) -> dict[str, Any]:
    evidence_groups = []
    for index, requirement in enumerate(row["requirements"], 1):
        units = requirement["acceptable_evidence_units"]
        evidence_groups.append(
            {
                "group_id": f"evidence_{index}",
                "requirement_id": requirement["requirement_id"],
                "acceptable_chunk_ids": list(
                    dict.fromkeys(unit["chunk_id"] for unit in units)
                ),
                "document_ids": list(
                    dict.fromkeys(unit["document_id"] for unit in units)
                ),
                "evidence_span": units[0]["text"] if units else "__UNSUPPORTED__",
                "expected_evidence": units,
            }
        )
    return {
        **row,
        "evidence_groups": evidence_groups,
        "expected_requirement_count": len(row["requirements"]),
    }


def build_replay_inputs(
    sealed_rows: list[dict[str, Any]],
    typed_case_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    typed_by_id = {row["candidate_id"]: row for row in typed_case_rows}
    sealed_ids = {row["candidate_id"] for row in sealed_rows}
    if set(typed_by_id) != sealed_ids:
        raise RuntimeError("sealed and typed candidate snapshot IDs differ")

    reviewed_rows = []
    baseline_rows = []
    pool_rows = []
    for sealed in sealed_rows:
        typed = typed_by_id[sealed["candidate_id"]]
        retrieval = typed["retrieval"]
        baseline_ids = list(retrieval["baseline_candidate_ids"])
        arm_ids = list(retrieval["subject_arm_full_candidate_ids"])
        requirement_pools = typed["requirement_candidate_chunk_ids"]
        if len(requirement_pools) != len(sealed["requirements"]):
            raise RuntimeError("typed candidate snapshot requirement count differs")
        if any(list(pool) != arm_ids for pool in requirement_pools):
            raise RuntimeError("typed candidate snapshot differs across requirements")

        reviewed_rows.append(_compatible_reviewed(sealed))
        baseline_rows.append(
            {
                "candidate_id": sealed["candidate_id"],
                "arm0": {"candidate_chunk_ids": baseline_ids},
                "arm0_score": typed["baseline_score"],
            }
        )
        pool_rows.append(
            {
                "candidate_id": sealed["candidate_id"],
                "slot_ordinal": sealed["slot_ordinal"],
                "question_text": sealed["question_text"],
                "requirement_candidate_pools": [
                    {
                        "requirement_id": requirement["requirement_id"],
                        "query": requirement["relation"],
                        "subject_arm_full": {"candidate_chunk_ids": arm_ids},
                    }
                    for requirement in sealed["requirements"]
                ],
            }
        )
    return reviewed_rows, baseline_rows, pool_rows


def run_comparator(*, root: Path, contract_path: Path) -> dict[str, Any]:
    root = root.resolve()
    contract_path = contract_path.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract["runner_version"] != RUNNER_VERSION:
        raise RuntimeError("comparator runner version differs from contract")
    if contract["execution"]["maximum_attempts"] != 1:
        raise RuntimeError("comparator contract does not enforce one attempt")
    _verify_hashes(root, contract["frozen_hashes"])
    _verify_model(contract["model"])

    sealed_path = root / contract["sealed_set"]["path"]
    typed_cases_path = root / contract["candidate_snapshot"]["path"]
    sealed_rows = read_jsonl(sealed_path)
    typed_case_rows = read_jsonl(typed_cases_path)
    if len(sealed_rows) != 64 or len(typed_case_rows) != 64:
        raise RuntimeError("comparator requires exactly 64 sealed and typed rows")

    reviewed_rows, baseline_rows, pool_rows = build_replay_inputs(
        sealed_rows,
        typed_case_rows,
    )
    seal_sha = contract["sealed_set"]["sha256"]
    snapshot_sha = contract["candidate_snapshot"]["sha256"]
    output_dir = (
        root
        / "outputs/v3"
        / f"split_schema_generalization_64_comparator_{seal_sha[:16]}_{snapshot_sha[:16]}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    prior_markers = sorted(output_dir.glob("attempt_started_*.json"))
    if prior_markers:
        raise RuntimeError(f"comparator attempt already exists: {prior_markers}")

    started_at = _now()
    attempt = {
        "attempt_schema_version": "split-schema-generalization-comparator-attempt-v1",
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "posthoc_frozen_arm_comparator",
        "sealed_set_sha256": seal_sha,
        "candidate_snapshot_sha256": snapshot_sha,
        "contract_sha256": file_sha256(contract_path),
        "attempt_number": 1,
        "started_at": started_at,
        "status": "started_before_generation",
        "rerun_allowed": False,
    }
    attempt_bytes = _canonical_json_bytes(attempt)
    attempt_sha = _sha256_bytes(attempt_bytes)
    attempt_path = output_dir / f"attempt_started_{attempt_sha}.json"
    write_immutable(attempt_path, attempt_bytes)

    chunks = read_jsonl(root / contract["arm_inputs"]["chunks"]["path"])
    documents = read_jsonl(root / contract["arm_inputs"]["documents"]["path"])
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    typed_by_id = {row["candidate_id"]: row for row in typed_case_rows}
    checkpoint_path = output_dir / "generation_checkpoint_in_progress.jsonl"
    checkpoint_rows: list[dict[str, Any]] = []

    def checkpoint(row: dict[str, Any], current: int, total: int) -> None:
        checkpoint_rows.append(row)
        write_jsonl(checkpoint_path, checkpoint_rows)
        print(
            json.dumps(
                {"stage": "generation", "progress": f"{current}/{total}"},
                ensure_ascii=False,
            ),
            flush=True,
        )

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    started = time.perf_counter()
    generated_rows = run_fixed_requirement_replay(
        reviewed_rows=reviewed_rows,
        baseline_rows=baseline_rows,
        chunks=chunks,
        documents=documents,
        temporal_rows=read_jsonl(
            root / contract["arm_inputs"]["temporal"]["path"]
        ),
        table_facts=read_jsonl(
            root / contract["arm_inputs"]["table_facts"]["path"]
        ),
        model=contract["model"]["requested_tag"],
        as_of=contract["pipeline"]["as_of"],
        reasoning_effort="high",
        timeout_seconds=contract["model"]["timeout_seconds"],
        split_evidence_schema=True,
        batch_requirements=True,
        typed_evidence_refs=False,
        result_callback=checkpoint,
        candidate_pool_rows=pool_rows,
        candidate_pool_arm="subject_arm_full",
    )
    enriched_rows = [
        {
            **row,
            "slot_ordinal": sealed_rows[index]["slot_ordinal"],
            "source_id": sealed_rows[index]["source_id"],
            "primary_dimension": sealed_rows[index]["primary_dimension"],
            "retrieval": typed_by_id[row["candidate_id"]]["retrieval"],
        }
        for index, row in enumerate(generated_rows)
    ]
    scored_rows, score_summary = score_generalization_cases(
        sealed_rows,
        enriched_rows,
        chunks_by_id=chunks_by_id,
    )
    ended_at = _now()

    cases_bytes = _serialize_jsonl(scored_rows, lambda row: row["slot_ordinal"])
    cases_sha = _sha256_bytes(cases_bytes)
    cases_path = output_dir / f"split_schema_generalization_64_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    summary = {
        "summary_schema_version": "split-schema-generalization-comparator-summary-v1",
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "posthoc_frozen_arm_comparator_after_typed_results_opened",
        "blind_first_execution": False,
        "sealed_set_sha256": seal_sha,
        "candidate_snapshot_sha256": snapshot_sha,
        "attempt_sha256": attempt_sha,
        "started_at": started_at,
        "ended_at": ended_at,
        "wall_clock_ms": round((time.perf_counter() - started) * 1000, 3),
        "model": contract["model"]["requested_tag"],
        "pipeline": contract["pipeline"]["steps"],
        "automatic_scoring": score_summary,
        "cases": {
            "path": _relative(root, cases_path),
            "sha256": cases_sha,
        },
        "human_rejudication": {
            "performed": False,
            "headline_overridden": False,
            "additional_credits": 0,
        },
    }
    summary_bytes = _canonical_json_bytes(summary)
    summary_sha = _sha256_bytes(summary_bytes)
    summary_path = (
        output_dir / f"split_schema_generalization_64_summary_{summary_sha}.json"
    )
    write_immutable(summary_path, summary_bytes)

    _verify_hashes(root, contract["frozen_hashes"])
    completion = {
        "execution_manifest_schema_version": (
            "split-schema-generalization-comparator-execution-v1"
        ),
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "posthoc_frozen_arm_comparator",
        "execution_count": 1,
        "rerun_allowed": False,
        "code_and_inputs_unchanged_during_run": True,
        "contract": {
            "path": _relative(root, contract_path),
            "sha256": file_sha256(contract_path),
        },
        "attempt": {
            "path": _relative(root, attempt_path),
            "sha256": attempt_sha,
        },
        "sealed_set": contract["sealed_set"],
        "candidate_snapshot": contract["candidate_snapshot"],
        "cases": summary["cases"],
        "summary": {
            "path": _relative(root, summary_path),
            "sha256": summary_sha,
        },
    }
    completion_bytes = _canonical_json_bytes(completion)
    completion_sha = _sha256_bytes(completion_bytes)
    completion_path = output_dir / f"execution_manifest_{completion_sha}.json"
    write_immutable(completion_path, completion_bytes)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    contract_path = args.contract
    if not contract_path.is_absolute():
        contract_path = root / contract_path
    run_comparator(root=root, contract_path=contract_path)


if __name__ == "__main__":
    main()
