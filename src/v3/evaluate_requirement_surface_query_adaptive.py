from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3 import evaluate_requirement_surface_query_canary as canary
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


EVALUATOR_VERSION = "requirement-surface-query-adaptive-rerun-v1.0.0"
EVALUATION_ROLE = "adaptive_validation_after_sealed_failure_inspection_not_sealed"
DEFAULT_BASELINE_CASES = Path(
    "data/v3/evidence/requirement_surface_query_canary_ab_cases_"
    "deaaef651ea4110bf9883a32123742564cb0022ed7745a1cfdadc5d3ec463003.jsonl"
)
DEFAULT_BASELINE_REPORT = Path(
    "reports/v3/requirement_surface_query_canary_ab_"
    "bd8f2a122201710b9e15b1255e43563694b910fa61039fa60fd4956cf95e6fd2.json"
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _successes(summary: dict[str, Any], metric: str) -> int:
    return int(summary["metrics"][metric]["successes"])


def compare_summaries(
    baseline: dict[str, Any], adaptive: dict[str, Any]
) -> dict[str, Any]:
    metrics = (
        "arm1_candidate_all_required_coverage",
        "arm1_all_required_evidence",
        "arm1_all_literal_spans",
        "positive_application",
        "control_bypass",
    )
    return {
        name: {
            "before": _successes(baseline, name),
            "after": _successes(adaptive, name),
            "delta": _successes(adaptive, name) - _successes(baseline, name),
        }
        for name in metrics
    } | {
        "false_full": {
            "before": len(baseline["metrics"]["arm1_false_full_case_ids"]),
            "after": len(adaptive["metrics"]["arm1_false_full_case_ids"]),
            "delta": len(adaptive["metrics"]["arm1_false_full_case_ids"])
            - len(baseline["metrics"]["arm1_false_full_case_ids"]),
        },
        "runtime_requirement_count_mismatch": {
            "before": len(
                baseline["metrics"]["runtime_requirement_count_mismatch_case_ids"]
            ),
            "after": len(
                adaptive["metrics"]["runtime_requirement_count_mismatch_case_ids"]
            ),
            "delta": len(
                adaptive["metrics"]["runtime_requirement_count_mismatch_case_ids"]
            )
            - len(
                baseline["metrics"]["runtime_requirement_count_mismatch_case_ids"]
            ),
        },
    }


def _prior_run_exists(root: Path, run_key: str) -> bool:
    for path in (root / "data/v3/evaluation").glob(
        "requirement_surface_query_adaptive_execution_*.json"
    ):
        if _load_json(path).get("run_key") == run_key:
            return True
    return False


def close_aborted_run(root: Path, run_key: str) -> dict[str, Any]:
    matching = []
    completed = []
    for path in (root / "data/v3/evaluation").glob(
        "requirement_surface_query_adaptive_execution_*.json"
    ):
        row = _load_json(path)
        if row.get("run_key") != run_key:
            continue
        matching.append(row)
        if str(row.get("status") or "").startswith("COMPLETED"):
            completed.append(row)
    if not matching:
        raise RuntimeError("Superseded adaptive run key does not exist")
    if completed:
        raise RuntimeError("A completed adaptive run cannot be superseded")
    closure = {
        "status": "ABORTED_NO_RESULTS",
        "evaluation_role": EVALUATION_ROLE,
        "run_key": run_key,
        "reason": "executor_timeout_after_start_no_result_artifact",
        "completed_rows": "unknown",
        "results_observed": False,
        "sealed_claim_allowed": False,
        "runtime_or_canonical_promoted": False,
    }
    payload = _canonical_json_bytes(closure)
    sha = _sha256_bytes(payload)
    path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_adaptive_execution_{sha}.json"
    )
    write_immutable(path, payload)
    return {"path": path.relative_to(root).as_posix(), "sha256": sha}


def execute_adaptive(
    *,
    root: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    planner_model: str,
    baseline_cases_path: Path = DEFAULT_BASELINE_CASES,
    baseline_report_path: Path = DEFAULT_BASELINE_REPORT,
    runner: canary.PairRunner | None = None,
    supersedes_run_key: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()

    def absolute(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    reviewed_path = absolute(reviewed_path)
    reviewed_manifest_path = absolute(reviewed_manifest_path)
    baseline_cases_path = absolute(baseline_cases_path)
    baseline_report_path = absolute(baseline_report_path)
    rows = read_jsonl(reviewed_path)
    reviewed_manifest = _load_json(reviewed_manifest_path)
    reviewed_sha = file_sha256(reviewed_path)
    canary.validate_reviewed_export(
        rows, reviewed_manifest, reviewed_sha256=reviewed_sha
    )

    tracked_inputs = {
        "reviewed": reviewed_path,
        "reviewed_manifest": reviewed_manifest_path,
        "baseline_cases": baseline_cases_path,
        "baseline_report": baseline_report_path,
        "chunks": root / canary.DEFAULT_CHUNKS,
        "documents": root / canary.DEFAULT_DOCUMENTS,
        "sealed_evaluator_source": root
        / "src/v3/evaluate_requirement_surface_query_canary.py",
        "adaptive_evaluator_source": Path(__file__).resolve(),
        "surface_query_source": root / "src/v3/requirement_surface_query.py",
        "entity_anchor_source": root / "src/v3/requirement_entity_anchor.py",
    }
    before_hashes = {name: file_sha256(path) for name, path in tracked_inputs.items()}
    run_key = _sha256_bytes(
        _canonical_json_bytes(
            {
                "evaluation_role": EVALUATION_ROLE,
                "planner_model": planner_model,
                "inputs": before_hashes,
                "supersedes_run_key": supersedes_run_key,
            }
        )
    )
    if _prior_run_exists(root, run_key):
        raise RuntimeError("This exact adaptive rerun has already been consumed")

    superseded = (
        close_aborted_run(root, supersedes_run_key)
        if supersedes_run_key is not None
        else None
    )

    active_runner = runner or canary.LivePairRunner(
        root=root, planner_model=planner_model
    )
    started = {
        "status": "STARTED_ADAPTIVE_RUN_CONSUMED",
        "evaluation_role": EVALUATION_ROLE,
        "run_key": run_key,
        "supersedes": superseded,
        "sealed_claim_allowed": False,
        "automatic_runtime_or_canonical_promotion": False,
    }
    started_bytes = _canonical_json_bytes(started)
    started_sha = _sha256_bytes(started_bytes)
    started_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_adaptive_execution_{started_sha}.json"
    )
    write_immutable(started_path, started_bytes)

    pair_outputs = canary.collect_pair_outputs(rows, active_runner)
    chunks_by_id = {
        row["chunk_id"]: row for row in read_jsonl(root / canary.DEFAULT_CHUNKS)
    }
    cases = canary.evaluate_pair_outputs(rows, pair_outputs, chunks_by_id=chunks_by_id)
    summary = canary.summarize_cases(cases)
    baseline_summary = _load_json(baseline_report_path)["summary"]
    report = {
        "report_schema_version": "requirement-surface-query-adaptive-report-v1",
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": EVALUATION_ROLE,
        "canary_status": "downgraded_to_adaptive_validation",
        "summary": summary,
        "comparison_to_original_sealed_run": compare_summaries(
            baseline_summary, summary
        ),
        "constraints": {
            "gold_available_to_decision": False,
            "decision_input_fields": list(canary.DECISION_INPUT_FIELDS),
            "sealed_claim_allowed": False,
            "automatic_runtime_or_canonical_promotion": False,
            "result_does_not_change_runtime": True,
        },
        "inputs": before_hashes,
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(cases, lambda row: row["slot_ordinal"])
    cases_sha = _sha256_bytes(cases_bytes)
    cases_path = evidence_dir / (
        f"requirement_surface_query_adaptive_cases_{cases_sha}.jsonl"
    )
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / (
        f"requirement_surface_query_adaptive_{report_sha}.json"
    )
    write_immutable(report_path, report_bytes)
    manifest = {
        "manifest_schema_version": "requirement-surface-query-adaptive-manifest-v1",
        "evaluation_role": EVALUATION_ROLE,
        "run_key": run_key,
        "supersedes": superseded,
        "decision": summary["decision"],
        "inputs": before_hashes,
        "outputs": {
            "cases": {
                "path": cases_path.relative_to(root).as_posix(),
                "sha256": cases_sha,
            },
            "report": {
                "path": report_path.relative_to(root).as_posix(),
                "sha256": report_sha,
            },
        },
        "sealed_claim_allowed": False,
        "automatic_runtime_or_canonical_promotion": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / (
        f"requirement_surface_query_adaptive_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    after_hashes = {name: file_sha256(path) for name, path in tracked_inputs.items()}
    if before_hashes != after_hashes:
        raise RuntimeError("Adaptive rerun input changed during execution")
    completed = {
        "status": "COMPLETED_ADAPTIVE_NO_AUTOMATIC_PROMOTION",
        "evaluation_role": EVALUATION_ROLE,
        "run_key": run_key,
        "started": {
            "path": started_path.relative_to(root).as_posix(),
            "sha256": started_sha,
        },
        "result": {
            "decision": summary["decision"],
            "cases_sha256": cases_sha,
            "report_sha256": report_sha,
            "manifest_sha256": manifest_sha,
        },
        "input_hashes_unchanged": True,
        "sealed_claim_allowed": False,
        "runtime_or_canonical_promoted": False,
    }
    completed_bytes = _canonical_json_bytes(completed)
    completed_sha = _sha256_bytes(completed_bytes)
    completed_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_adaptive_execution_{completed_sha}.json"
    )
    write_immutable(completed_path, completed_bytes)
    return {
        "decision": summary["decision"],
        "cases_path": str(cases_path),
        "report_path": str(report_path),
        "manifest_path": str(manifest_path),
        "ledger_path": str(completed_path),
        "comparison": report["comparison_to_original_sealed_run"],
        "runtime_or_canonical_promoted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--reviewed-manifest", type=Path, required=True)
    parser.add_argument("--planner-model", default="qwen3:8b")
    parser.add_argument("--supersedes-run-key")
    args = parser.parse_args()
    print(
        json.dumps(
            execute_adaptive(
                root=args.root,
                reviewed_path=args.reviewed,
                reviewed_manifest_path=args.reviewed_manifest,
                planner_model=args.planner_model,
                supersedes_run_key=args.supersedes_run_key,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
