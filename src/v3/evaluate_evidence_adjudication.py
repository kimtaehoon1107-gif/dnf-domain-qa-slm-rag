from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable


EVALUATOR_VERSION = "evidence-adjudication-evaluator-v3.1.0"
REPORT_SCHEMA_VERSION = "evidence-adjudication-evaluation-report-v3.1"
MANIFEST_SCHEMA_VERSION = "evidence-adjudication-evaluation-manifest-v3.1"

DEFAULT_CANONICAL_CASES = Path(
    "data/v3/evidence/claim_reranker_cases_"
    "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a.jsonl"
)
DEFAULT_CANONICAL_REPORT = Path(
    "reports/v3/claim_reranker_runtime_"
    "f37db5f17f3d20553d14922471c5bf7415ff942b12746dfad6d831a6a0ef1df9.json"
)
DEFAULT_SOURCE = Path("src/v3/evaluate_evidence_adjudication.py")
DEFAULT_CONTRACT = Path("docs/v3/evidence_adjudication.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def evaluate_adjudication(
    canonical_report: dict[str, Any],
    canonical_cases: list[dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = canonical_report["metrics"]
    if metrics["reranked_cited_group_hits"] != 56:
        raise RuntimeError("Adjudication must use the canonical 56/59 report")
    mismatches = canonical_report["strict_mismatches"]
    mismatch_by_case = {row["case_id"]: row for row in mismatches}
    cases_by_id = {row["case_id"]: row for row in canonical_cases}
    overlay_by_case = {row["case_id"]: row for row in overlay_rows}
    if len(mismatch_by_case) != 3 or len(overlay_by_case) != len(overlay_rows):
        raise RuntimeError("Expected three unique canonical mismatch decisions")
    if set(overlay_by_case) != set(mismatch_by_case):
        raise RuntimeError("Adjudication overlay does not cover canonical mismatches exactly")

    accepted_siblings = 0
    unresolved = 0
    item_results = []
    for case_id in sorted(mismatch_by_case):
        mismatch = mismatch_by_case[case_id]
        overlay = overlay_by_case[case_id]
        case = cases_by_id[case_id]
        chosen_ids = set(case["response"]["citation_chunk_ids"])
        if overlay["candidate_chunk_id"] not in chosen_ids:
            raise RuntimeError("Adjudication candidate differs from canonical selected evidence")
        if overlay.get("reviewer_type") != "human":
            raise RuntimeError("Evidence adjudication must be human-reviewed")
        if overlay.get("training_allowed") is not False:
            raise RuntimeError("Evidence adjudication cannot be training data")
        if overlay.get("final_benchmark_eligible") is not False:
            raise RuntimeError("Adaptive adjudication cannot be final benchmark data")
        decision = overlay["decision"]
        if mismatch["reason"] == "acceptable_chunk_not_in_routed_candidates":
            if decision != "confirm_search_failure":
                raise RuntimeError("Canonical retrieval failure cannot be hidden by gold expansion")
            resolved = False
        elif decision == "accept_alternative":
            if not overlay.get("acceptable_sibling_addition"):
                raise RuntimeError("Accepted alternative must be an acceptable sibling")
            if not overlay.get("alternative_evidence_span"):
                raise RuntimeError("Accepted alternative needs a reviewed evidence span")
            accepted_siblings += 1
            resolved = True
        elif decision == "reject_alternative":
            resolved = False
        else:
            raise RuntimeError(f"Invalid strict adjudication decision: {decision}")
        unresolved += not resolved
        item_results.append(
            {
                "case_id": case_id,
                "question": mismatch["question"],
                "canonical_reason": mismatch["reason"],
                "candidate_chunk_id": overlay["candidate_chunk_id"],
                "decision": decision,
                "counts_as_adjudicated_semantic_hit": resolved,
                "original_strict_hit": False,
                "gold_replaced": False,
            }
        )

    original_hits = metrics["reranked_cited_group_hits"]
    expected_groups = metrics["expected_evidence_groups"]
    adjudicated_hits = original_hits + accepted_siblings
    return {
        "original_strict_citation": {
            "hits": original_hits,
            "expected_evidence_groups": expected_groups,
            "rate": round(original_hits / expected_groups, 8),
        },
        "adjudicated_semantic_citation": {
            "hits": adjudicated_hits,
            "expected_evidence_groups": expected_groups,
            "rate": round(adjudicated_hits / expected_groups, 8),
        },
        "canonical_strict_mismatch_count": len(mismatches),
        "adjudicated_unresolved_count": unresolved,
        "acceptable_sibling_additions": accepted_siblings,
        "gold_replacement_count": 0,
        "search_failure_count": sum(
            row["decision"] == "confirm_search_failure" for row in overlay_rows
        ),
        "decision_counts": dict(
            sorted(Counter(row["decision"] for row in overlay_rows).items())
        ),
        "items": item_results,
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    original = metrics["original_strict_citation"]
    adjudicated = metrics["adjudicated_semantic_citation"]
    return "\n".join(
        [
            "# DNF RAG v3 strict evidence adjudication",
            "",
            f"- original strict citation: {original['hits']}/{original['expected_evidence_groups']}",
            f"- adjudicated semantic citation: {adjudicated['hits']}/{adjudicated['expected_evidence_groups']}",
            f"- acceptable sibling additions: {metrics['acceptable_sibling_additions']}",
            f"- gold replacements: {metrics['gold_replacement_count']}",
            f"- confirmed search failures: {metrics['search_failure_count']}",
            "",
            "Original strict와 사람 판정 후 semantic 지표를 분리했다. 사람 판정은",
            "canonical gold를 교체하지 않으며 final benchmark 또는 학습 데이터가 아니다.",
            "",
        ]
    )


def freeze_adjudication_evaluation(
    root: Path,
    canonical_cases_path: Path,
    canonical_report_path: Path,
    overlay_path: Path,
    source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    canonical_report = json.loads(canonical_report_path.read_text(encoding="utf-8"))
    canonical_cases = read_jsonl(canonical_cases_path)
    overlay_rows = read_jsonl(overlay_path)
    metrics = evaluate_adjudication(canonical_report, canonical_cases, overlay_rows)
    inputs = {
        "canonical_cases": canonical_cases_path,
        "canonical_report": canonical_report_path,
        "human_adjudication_overlay": overlay_path,
        "evaluator_source": source_path,
        "contract": contract_path,
    }
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "adaptive_dev_adjudication_not_final_benchmark",
        "metrics": metrics,
        "decisions": {
            "canonical_56_of_59": "GO",
            "canonical_retrieval_failure_preserved": "GO",
            "gold_replacement": "PROHIBITED",
            "early_generalization_canary": "PENDING",
            "production_evidence_selector": "NO-GO",
            "final_benchmark": "NO-GO",
        },
    }
    reports_dir = root / "reports/v3"
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"evidence_adjudication_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"evidence_adjudication_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "report": {
            "path": _relative(root, report_path),
            "sha256": report_sha,
        },
        "report_markdown": {
            "path": _relative(root, markdown_path),
            "sha256": markdown_sha,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / f"evidence_adjudication_evaluation_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "metrics": metrics,
        "decisions": report["decisions"],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Evaluate v3 evidence adjudication")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--canonical-cases", type=Path, default=root / DEFAULT_CANONICAL_CASES)
    parser.add_argument("--canonical-report", type=Path, default=root / DEFAULT_CANONICAL_REPORT)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=root / DEFAULT_SOURCE)
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    result = freeze_adjudication_evaluation(
        root,
        args.canonical_cases.resolve(),
        args.canonical_report.resolve(),
        args.overlay.resolve(),
        args.source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
