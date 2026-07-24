from __future__ import annotations

import argparse
import gc
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
from src.v3.requirement_entity_anchor import build_official_entity_index
from src.v3.score_typed_evidence_ref_generalization import (
    score_generalization_cases,
)
from src.v3.simple_domain_rag import SimpleDomainRAG
from src.v3.subject_anchored_retrieval import (
    extract_subject_anchored_queries,
    merge_subject_anchored_candidates,
    subject_supported_hits,
)


RUNNER_VERSION = "typed-evidence-ref-generalization-one-shot-v1"
GENERATION_AS_OF = "2026-07-22"
MODEL_TAG = "qwen3-8b:ctx8192"
TIMEOUT_SECONDS = 180.0
HONEST_UNSUPPORTED_SLOTS = [7, 15, 23, 31, 39, 47, 55, 63]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _verify_model_blob(expected_sha256: str) -> None:
    completed = subprocess.run(
        ["ollama", "show", MODEL_TAG, "--modelfile"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"FROM .+sha256-([0-9a-f]{64})", completed.stdout)
    if match is None or match.group(1) != expected_sha256:
        raise RuntimeError("Ollama model blob differs from the sealed manifest")
    if "PARAMETER num_ctx 8192" not in completed.stdout:
        raise RuntimeError("Ollama model num_ctx is not 8192")
    with urlopen("http://localhost:11434/api/tags", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if MODEL_TAG not in {row["name"] for row in payload.get("models", [])}:
        raise RuntimeError("Ollama HTTP service does not expose the sealed model tag")


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
        raise RuntimeError(f"sealed input/code hashes changed: {mismatches}")


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


def _baseline_row(row: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    return {
        "candidate_id": row["candidate_id"],
        "arm0": {"candidate_chunk_ids": candidate_ids},
        "arm0_score": {
            "all_groups_hit": False,
            "all_evidence_spans_hit": False,
            "relevant_citation_count": 0,
            "citation_count": 0,
        },
    }


def _candidate_pool_row(
    row: dict[str, Any],
    candidate_ids: list[str],
) -> dict[str, Any]:
    return {
        "candidate_id": row["candidate_id"],
        "slot_ordinal": row["slot_ordinal"],
        "question_text": row["question_text"],
        "requirement_candidate_pools": [
            {
                "requirement_id": requirement["requirement_id"],
                "query": requirement["relation"],
                "subject_arm_full": {"candidate_chunk_ids": candidate_ids},
            }
            for requirement in row["requirements"]
        ],
    }


def run_one_shot(*, root: Path, seal_manifest_path: Path) -> dict[str, Any]:
    root = root.resolve()
    seal_manifest_path = seal_manifest_path.resolve()
    seal_manifest = json.loads(seal_manifest_path.read_text(encoding="utf-8"))
    if not seal_manifest["permissions"]["sealed_scoring_allowed"]:
        raise RuntimeError("sealed scoring is not allowed")
    if seal_manifest["permissions"]["maximum_execution_attempts"] != 1:
        raise RuntimeError("seal manifest does not enforce a single attempt")

    sealed_path = root / seal_manifest["sealed_set"]["path"]
    if file_sha256(sealed_path) != seal_manifest["sealed_set"]["sha256"]:
        raise RuntimeError("sealed set SHA mismatch")
    sealed_rows = read_jsonl(sealed_path)
    if len(sealed_rows) != 64:
        raise RuntimeError("sealed set must contain 64 rows")
    if not all(
        row["execution_allowed"]
        and row["sealed_scoring_allowed"]
        and not row["training_allowed"]
        for row in sealed_rows
    ):
        raise RuntimeError("sealed row execution/training permissions are invalid")
    unsupported_slots = [
        row["slot_ordinal"]
        for row in sealed_rows
        if any(
            requirement["expected_status"] == "unsupported"
            for requirement in row["requirements"]
        )
    ]
    if unsupported_slots != HONEST_UNSUPPORTED_SLOTS:
        raise RuntimeError(f"unexpected honest-unsupported slots: {unsupported_slots}")

    _verify_hashes(root, seal_manifest["frozen_hashes"])
    _verify_model_blob(seal_manifest["model"]["ollama_blob_sha256"])

    seal_sha = seal_manifest["sealed_set"]["sha256"]
    output_dir = root / "outputs/v3" / f"typed_evidence_ref_generalization_64_one_shot_{seal_sha[:16]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    prior_markers = sorted(output_dir.glob("attempt_started_*.json"))
    if prior_markers:
        raise RuntimeError(
            f"one-shot attempt already exists; rerun prohibited: {prior_markers}"
        )

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    rag = SimpleDomainRAG(
        root=root,
        model=MODEL_TAG,
        device="cuda",
        retrieval_depth=20,
        rerank_depth=5,
        timeout=TIMEOUT_SECONDS,
    )
    rag._initialize()
    assert rag._artifacts is not None
    chunks_by_id = rag._artifacts.chunks_by_id
    documents_by_id = rag._artifacts.documents_by_id
    entity_index = build_official_entity_index(
        list(documents_by_id.values()),
        list(chunks_by_id.values()),
    )

    started_at = _now()
    attempt = {
        "attempt_schema_version": "typed-evidence-ref-generalization-attempt-v1",
        "runner_version": RUNNER_VERSION,
        "sealed_set_sha256": seal_sha,
        "seal_manifest_sha256": file_sha256(seal_manifest_path),
        "attempt_number": 1,
        "started_at": started_at,
        "status": "started_before_retrieval_or_generation",
        "rerun_allowed": False,
    }
    attempt_bytes = _canonical_json_bytes(attempt)
    attempt_sha = _sha256_bytes(attempt_bytes)
    attempt_path = output_dir / f"attempt_started_{attempt_sha}.json"
    write_immutable(attempt_path, attempt_bytes)

    started = time.perf_counter()
    reviewed_rows = []
    baseline_rows = []
    pool_rows = []
    retrieval_rows = []
    for index, sealed in enumerate(sealed_rows, 1):
        _, baseline_hits = rag._retrieve_and_rerank(sealed["question_text"])
        baseline_ids = [row["chunk_id"] for row in baseline_hits]
        plan = extract_subject_anchored_queries(
            sealed["question_text"],
            entity_index,
        )
        anchored_groups = []
        if plan is not None:
            for query in plan["queries"]:
                _, hits = rag._retrieve_and_rerank(query)
                anchored_groups.append(
                    subject_supported_hits(
                        plan["subject"],
                        hits,
                        chunks_by_id=chunks_by_id,
                        documents_by_id=documents_by_id,
                    )
                )
            arm_hits = merge_subject_anchored_candidates(
                baseline_hits,
                anchored_groups,
                subject=plan["subject"],
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
            )
        else:
            arm_hits = baseline_hits
        arm_ids = [row["chunk_id"] for row in arm_hits]
        reviewed_rows.append(_compatible_reviewed(sealed))
        baseline_rows.append(_baseline_row(sealed, baseline_ids))
        pool_rows.append(_candidate_pool_row(sealed, arm_ids))
        retrieval_rows.append(
            {
                "slot_ordinal": sealed["slot_ordinal"],
                "candidate_id": sealed["candidate_id"],
                "plan": plan,
                "baseline_candidate_ids": baseline_ids,
                "anchored_group_candidate_ids": [
                    [row["chunk_id"] for row in group] for group in anchored_groups
                ],
                "subject_arm_full_candidate_ids": arm_ids,
            }
        )
        print(
            json.dumps(
                {
                    "stage": "retrieval",
                    "progress": f"{index}/64",
                    "slot": sealed["slot_ordinal"],
                    "subject_plan": plan is not None,
                    "candidate_count": len(arm_ids),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    rag._embedder = None
    rag._reranker = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass

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

    generated_rows = run_fixed_requirement_replay(
        reviewed_rows=reviewed_rows,
        baseline_rows=baseline_rows,
        chunks=list(chunks_by_id.values()),
        documents=list(documents_by_id.values()),
        temporal_rows=read_jsonl(root / seal_manifest["arm_inputs"]["temporal"]["path"]),
        table_facts=read_jsonl(root / seal_manifest["arm_inputs"]["table_facts"]["path"]),
        model=MODEL_TAG,
        as_of=GENERATION_AS_OF,
        reasoning_effort="high",
        timeout_seconds=TIMEOUT_SECONDS,
        split_evidence_schema=True,
        batch_requirements=True,
        typed_evidence_refs=True,
        result_callback=checkpoint,
        candidate_pool_rows=pool_rows,
        candidate_pool_arm="subject_arm_full",
    )
    retrieval_by_id = {row["candidate_id"]: row for row in retrieval_rows}
    enriched_rows = [
        {
            **row,
            "slot_ordinal": sealed_rows[index]["slot_ordinal"],
            "source_id": sealed_rows[index]["source_id"],
            "primary_dimension": sealed_rows[index]["primary_dimension"],
            "retrieval": retrieval_by_id[row["candidate_id"]],
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
    cases_path = output_dir / f"typed_evidence_ref_generalization_64_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)

    summary = {
        "summary_schema_version": "typed-evidence-ref-generalization-one-shot-summary-v1",
        "runner_version": RUNNER_VERSION,
        "evaluation_role": "first_independent_human_reviewed_holdout_one_shot",
        "sealed_set_sha256": seal_sha,
        "attempt_sha256": attempt_sha,
        "execution_count": 1,
        "started_at": started_at,
        "ended_at": ended_at,
        "wall_clock_ms": round((time.perf_counter() - started) * 1000, 3),
        "model": MODEL_TAG,
        "generation_as_of": GENERATION_AS_OF,
        "pipeline": [
            "subject-anchored retrieval",
            "question-level batched fixed requirements",
            "typed value plus evidence_ref for non-table evidence",
            "table-row branch for table evidence",
            "relation, temporal-role and boolean verification",
        ],
        "automatic_scoring": score_summary,
        "human_rejudication": {
            "performed": False,
            "additional_credits": 0,
            "headline_overridden": False,
        },
        "cases": {"path": _relative(root, cases_path), "sha256": cases_sha},
    }
    summary_bytes = _canonical_json_bytes(summary, indent=2)
    summary_sha = _sha256_bytes(summary_bytes)
    summary_path = output_dir / f"typed_evidence_ref_generalization_64_summary_{summary_sha}.json"
    write_immutable(summary_path, summary_bytes)

    _verify_hashes(root, seal_manifest["frozen_hashes"])
    if file_sha256(sealed_path) != seal_sha:
        raise RuntimeError("sealed set changed during execution")
    completion = {
        "execution_manifest_schema_version": "typed-evidence-ref-generalization-execution-v1",
        "runner_version": RUNNER_VERSION,
        "seal_manifest": {
            "path": _relative(root, seal_manifest_path),
            "sha256": file_sha256(seal_manifest_path),
        },
        "sealed_set": {"path": _relative(root, sealed_path), "sha256": seal_sha},
        "attempt": {"path": _relative(root, attempt_path), "sha256": attempt_sha},
        "cases": {"path": _relative(root, cases_path), "sha256": cases_sha},
        "summary": {"path": _relative(root, summary_path), "sha256": summary_sha},
        "execution_count": 1,
        "rerun_allowed": False,
        "code_and_inputs_unchanged_after_seal": True,
    }
    completion_bytes = _canonical_json_bytes(completion, indent=2)
    completion_sha = _sha256_bytes(completion_bytes)
    completion_path = output_dir / f"execution_manifest_{completion_sha}.json"
    write_immutable(completion_path, completion_bytes)
    return {
        **completion,
        "execution_manifest": {
            "path": _relative(root, completion_path),
            "sha256": completion_sha,
        },
        "automatic_scoring": score_summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the sealed typed evidence-ref 64-question holdout exactly once"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--seal-manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    manifest = (
        args.seal_manifest
        if args.seal_manifest.is_absolute()
        else root / args.seal_manifest
    )
    print(
        json.dumps(
            run_one_shot(root=root, seal_manifest_path=manifest),
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
