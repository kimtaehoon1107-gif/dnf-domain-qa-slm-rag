from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.gradio_backbone_demo import DemoBackbone, validate_exact_citation


EVALUATOR_VERSION = "authored-validation-v3.2-evaluator-v1.0"
CASE_SCHEMA_VERSION = "authored-validation-v3.2-result-case-v1"
REPORT_SCHEMA_VERSION = "authored-validation-v3.2-report-v1"
MANIFEST_SCHEMA_VERSION = "authored-validation-v3.2-result-manifest-v1"
DEFAULT_SET = Path(
    "data/v3/evaluation/authored_validation_v3_2_"
    "52c1b84ef7ab0f9bee29931c46f9febf0970492216b6742e8f5337282af4181e.jsonl"
)
DEFAULT_SET_MANIFEST = Path(
    "data/v3/evaluation/authored_validation_v3_2_manifest_"
    "dbaa9341228f426e7c9cef27b34dded57208d62f990d3601f740faab877061cc.json"
)
DEFAULT_CONTRACT = Path("docs/v3/authored_validation_v3_2.md")
DEFAULT_TEMPORAL = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "small_sample_limit": total < 5,
    }


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def cited_chunk_ids(runtime_result: dict[str, Any]) -> set[str]:
    return {
        citation["chunk_id"]
        for requirement in runtime_result.get("requirements", [])
        for citation in requirement.get("citations", [])
    }


def exact_citations(
    runtime_result: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]
) -> bool:
    try:
        for requirement in runtime_result.get("requirements", []):
            for citation in requirement.get("citations", []):
                validate_exact_citation(
                    citation, chunks_by_id[citation["chunk_id"]]["display_text"]
                )
    except (KeyError, RuntimeError, TypeError, ValueError):
        return False
    return True


def temporal_violations(
    evaluation: dict[str, Any],
    runtime_result: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
) -> list[str]:
    violations = []
    gold_documents = set(evaluation["gold_document_ids"])
    for chunk_id in cited_chunk_ids(runtime_result):
        chunk = chunks_by_id[chunk_id]
        document_id = chunk["parent_document_id"]
        if evaluation["time_scope"] == "current":
            temporal = temporal_by_document.get(document_id)
            if (
                not chunk["default_exposure"]
                or chunk["status"] not in {"current", "upcoming"}
                or (temporal and temporal["retrieval_action_current"] == "deny")
            ):
                violations.append(chunk_id)
        elif evaluation["source_ids"] == ["dnf_account_policy"] and document_id not in gold_documents:
            violations.append(chunk_id)
    return sorted(set(violations))


def classify_earliest_failure(
    evaluation: dict[str, Any], runtime_result: dict[str, Any], all_groups_hit: bool
) -> str | None:
    if all_groups_hit:
        return None
    expected_sources = set(evaluation["source_ids"])
    route = runtime_result.get("route", {})
    fallback = runtime_result.get("retrieval", {}).get("bounded_fallback", {})
    searched_sources = set(
        fallback.get("bounded_source_ids") or route.get("source_ids") or []
    )
    if not expected_sources.issubset(searched_sources):
        return "ROUTING_SOURCE_SCOPE"
    selected = set(runtime_result.get("retrieval", {}).get("selected_chunk_ids", []))
    gold = set(evaluation["gold_chunk_ids"])
    if not (selected & gold):
        return "RETRIEVAL"
    return "SELECTION_SUPPORT"


def score_case(
    evaluation: dict[str, Any],
    runtime_result: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cited = cited_chunk_ids(runtime_result)
    group_hits = {
        group["group_id"]: bool(set(group["acceptable_chunk_ids"]) & cited)
        for group in evaluation["evidence_groups"]
    }
    all_groups_hit = all(group_hits.values())
    response_mode = runtime_result["response_mode"]
    full = response_mode == "full_answer"
    return {
        "group_hits": group_hits,
        "group_hit_count": sum(group_hits.values()),
        "evidence_group_count": len(group_hits),
        "all_groups_hit": all_groups_hit,
        "false_full": full and not all_groups_hit,
        "honest_partial_or_abstain": not full and not all_groups_hit,
        "exact_citations": exact_citations(runtime_result, chunks_by_id),
        "temporal_violation_chunk_ids": temporal_violations(
            evaluation, runtime_result, chunks_by_id, temporal_by_document
        ),
        "earliest_failure_stage": classify_earliest_failure(
            evaluation, runtime_result, all_groups_hit
        ),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    source_counts: dict[str, dict[str, Any]] = {}
    for source_id in sorted({row["source_id"] for row in rows}):
        source_rows = [row for row in rows if row["source_id"] == source_id]
        source_counts[source_id] = _ratio(
            sum(row["score"]["all_groups_hit"] for row in source_rows), len(source_rows)
        )
    stage_counts = Counter(
        row["score"]["earliest_failure_stage"]
        for row in rows
        if row["score"]["earliest_failure_stage"]
    )
    all_groups = sum(row["score"]["all_groups_hit"] for row in rows)
    false_full = sum(row["score"]["false_full"] for row in rows)
    exact = all(row["score"]["exact_citations"] for row in rows)
    temporal = sorted(
        {
            chunk_id
            for row in rows
            for chunk_id in row["score"]["temporal_violation_chunk_ids"]
        }
    )
    checks = {
        "all_groups_at_least_18_of_24": all_groups >= 18,
        "every_source_at_least_2_of_3": all(
            value["successes"] >= 2 for value in source_counts.values()
        ),
        "exact_citations_100_percent": exact,
        "temporal_violations_zero": not temporal,
        "false_full_at_most_3_of_24": false_full <= 3,
    }
    return {
        "all_groups_covered": _ratio(all_groups, total),
        "false_full": _ratio(false_full, total),
        "honest_partial_or_abstain": _ratio(
            sum(row["score"]["honest_partial_or_abstain"] for row in rows), total
        ),
        "exact_citations_all": exact,
        "temporal_violation_chunk_ids": temporal,
        "source_coverage": source_counts,
        "failure_stage_counts": dict(sorted(stage_counts.items())),
        "latency_ms": {
            "median": sorted(row["runtime"]["latency_ms"] for row in rows)[total // 2],
            "max": max(row["runtime"]["latency_ms"] for row in rows),
        },
        "gate_checks": checks,
        "gate_passed": all(checks.values()),
        "decision": "DIRECTIONAL_GO" if all(checks.values()) else "NO_GO_ADAPTIVE_DIAGNOSTIC",
    }


def _markdown(report: dict[str, Any], rows: list[dict[str, Any]]) -> bytes:
    summary = report["summary"]
    lines = [
        "# v3.2 authored validation one-time run",
        "",
        "This is authored validation, not an independent or sealed benchmark.",
        "",
        f"- decision: **{summary['decision']}**",
        f"- all groups covered: **{summary['all_groups_covered']['successes']}/{summary['all_groups_covered']['total']}**",
        f"- false-full: **{summary['false_full']['successes']}/{summary['false_full']['total']}**",
        f"- exact citations: **{summary['exact_citations_all']}**",
        f"- failure stages: **{json.dumps(summary['failure_stage_counts'], ensure_ascii=False)}**",
        "",
        "| # | source | result | stage | question |",
        "|---:|---|---|---|---|",
    ]
    for index, row in enumerate(rows, 1):
        result = "PASS" if row["score"]["all_groups_hit"] else (
            "FALSE_FULL" if row["score"]["false_full"] else "HONEST_PARTIAL"
        )
        lines.append(
            f"| {index} | {row['source_id']} | {result} | "
            f"{row['score']['earliest_failure_stage'] or '-'} | {row['question']} |"
        )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "evaluation_set": root / DEFAULT_SET,
        "evaluation_manifest": root / DEFAULT_SET_MANIFEST,
        "contract": root / DEFAULT_CONTRACT,
        "temporal_overlay": root / DEFAULT_TEMPORAL,
        "chunks": root / DEFAULT_CHUNKS,
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    set_manifest = json.loads(inputs["evaluation_manifest"].read_text(encoding="utf-8"))
    if set_manifest["artifact"]["sha256"] != before["evaluation_set"]:
        raise RuntimeError("Authored validation manifest lineage mismatch")
    if not set_manifest["frozen_before_first_run"]:
        raise RuntimeError("Evaluation set was not frozen before the run")
    evaluation_rows = read_jsonl(inputs["evaluation_set"])
    chunks = read_jsonl(inputs["chunks"])
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    temporal_by_document = {
        row["document_id"]: row for row in read_jsonl(inputs["temporal_overlay"])
    }
    demo = DemoBackbone(
        root=root,
        planner_model="qwen3:8b",
        enable_v3_2_candidates=True,
        enable_bounded_fallback=True,
    )
    rows = []
    for index, evaluation in enumerate(evaluation_rows, 1):
        print(f"[{index}/{len(evaluation_rows)}] {evaluation['question']}", flush=True)
        runtime = demo.answer(evaluation["question"])
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": evaluation["dev_id"],
                "source_id": evaluation["source_ids"][0],
                "question": evaluation["question"],
                "evaluation": evaluation,
                "runtime": runtime,
                "score": score_case(
                    evaluation, runtime, chunks_by_id, temporal_by_document
                ),
            }
        )
    summary = summarize(rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "authored_validation_one_time_run_not_independent_not_sealed",
        "executed_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "summary": summary,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "runtime": {
            "planner_model": "qwen3:8b",
            "bounded_fallback_enabled": True,
            "canonical_or_runtime_promoted": False,
        },
        "source_commit": _git_head(root),
    }
    result_bytes = _serialize_jsonl(rows, lambda row: row["case_id"])
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    result_path = root / "data/v3/evaluation" / f"authored_validation_v3_2_results_{result_sha}.jsonl"
    write_immutable(result_path, result_bytes)
    report["artifact"] = {
        "path": _relative(root, result_path), "sha256": result_sha, "row_count": len(rows)
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = root / "reports/v3" / f"authored_validation_v3_2_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report, rows)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = root / "reports/v3" / f"authored_validation_v3_2_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "one_time_run": True,
        "inputs": report["inputs"],
        "artifacts": {
            "results": report["artifact"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "source_commit": report["source_commit"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = root / "data/v3/evaluation" / f"authored_validation_v3_2_results_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise RuntimeError(f"Evaluation inputs changed during run: {changed}")
    return {
        "summary": summary,
        "results_path": str(result_path),
        "results_sha256": result_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "input_hash_mismatch_count": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen authored validation once")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(evaluate_and_freeze(parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

