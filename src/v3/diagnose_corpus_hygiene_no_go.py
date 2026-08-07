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
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable


DIAGNOSTIC_VERSION = "retrieval-corpus-hygiene-no-go-diagnostic-v3.1.0"
REPORT_SCHEMA_VERSION = "retrieval-corpus-hygiene-no-go-report-v3.1"
MANIFEST_SCHEMA_VERSION = "retrieval-corpus-hygiene-no-go-manifest-v3.1"

NEW_FALSE_FULL_CASE_ID = (
    "retrieval_dev_sha256_64d1cca28aa1cff2106d80948722fd600fc754bc741f900c508878fa8dcc68b6"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _by(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in rows}


def diagnose(
    *,
    p2_report: dict[str, Any],
    dev_rows: list[dict[str, Any]],
    dirty_candidates: list[dict[str, Any]],
    clean_candidates: list[dict[str, Any]],
    clean_signal_rows: list[dict[str, Any]],
    dirty_chunks: list[dict[str, Any]],
    clean_chunks: list[dict[str, Any]],
    p1_rows: list[dict[str, Any]],
    federated_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    dev = _by(dev_rows, "dev_id")[NEW_FALSE_FULL_CASE_ID]
    dirty_candidate = _by(dirty_candidates, "dev_id")[NEW_FALSE_FULL_CASE_ID]
    clean_candidate = _by(clean_candidates, "dev_id")[NEW_FALSE_FULL_CASE_ID]
    signal = _by(clean_signal_rows, "dev_id")[NEW_FALSE_FULL_CASE_ID]
    dirty_chunk_by_id = _by(dirty_chunks, "chunk_id")
    clean_chunk_by_id = _by(clean_chunks, "chunk_id")
    gold_ids = {
        chunk_id
        for group in dev["evidence_groups"]
        for chunk_id in group["acceptable_chunk_ids"]
    }

    def candidate_rank(row: dict[str, Any]) -> int | None:
        return next(
            (
                int(candidate.get("retrieval_rank", candidate.get("selected_rank")))
                for candidate in row["candidates"]
                if candidate["chunk_id"] in gold_ids
            ),
            None,
        )

    clean_signal_rank = signal["configurations"][
        "dense_75_bm25_25_structured_parent_lead_guard"
    ]["metrics"]["group_first_ranks"][0]
    gold_text_unchanged = all(
        dirty_chunk_by_id[chunk_id]["retrieval_text"]
        == clean_chunk_by_id[chunk_id]["retrieval_text"]
        for chunk_id in gold_ids
    )

    federated = _by(federated_rows, "case_id")
    navigation = []
    for p1 in sorted(
        (row for row in p1_rows if row["classification"] == "NAVIGATION_CONTAMINATION"),
        key=lambda row: row["case_id"],
    ):
        row = federated[p1["case_id"]]
        arms = {}
        for arm in ("federated_quota", "federated_global"):
            cited = row[arm]["cited_chunk_ids"]
            display_only_contaminants = []
            for chunk_id in cited:
                dirty = dirty_chunk_by_id[chunk_id]
                clean = clean_chunk_by_id[chunk_id]
                display_has_nav = "텍스트복사\n목록" in clean["display_text"]
                retrieval_has_nav = "텍스트복사\n목록" in clean["retrieval_text"]
                if display_has_nav and not retrieval_has_nav:
                    display_only_contaminants.append(chunk_id)
            arms[arm] = {
                "false_full_after_cleaning": row[arm]["score"]["false_full_answer"],
                "cited_chunk_ids": cited,
                "display_only_contaminant_chunk_ids": display_only_contaminants,
            }
        navigation.append(
            {
                "case_id": p1["case_id"],
                "question": p1["question"],
                "p1_rationale": p1["rationale"],
                "arms": arms,
            }
        )

    remaining_nav = sum(
        row["arms"]["federated_quota"]["false_full_after_cleaning"]
        for row in navigation
    )
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "evaluation_role": "development_only_no_go_root_cause",
        "decision": "NO_GO_CONFIRMED",
        "hard_route_regression": {
            "case_id": NEW_FALSE_FULL_CASE_ID,
            "question": dev["question"],
            "gold_chunk_ids": sorted(gold_ids),
            "gold_retrieval_text_unchanged": gold_text_unchanged,
            "dirty_candidate_rank": candidate_rank(dirty_candidate),
            "clean_top10_candidate_rank": candidate_rank(clean_candidate),
            "clean_signal_group_first_rank": clean_signal_rank,
            "root_cause": "candidate_depth_boundary_after_global_score_distribution_shift",
            "interpretation": "the unchanged gold chunk moved from the dirty top-10 boundary to clean rank 20 and therefore never reached the frozen reranker or assembler",
        },
        "p1_navigation_recheck": {
            "case_count": len(navigation),
            "resolved_in_quota": len(navigation) - remaining_nav,
            "remaining_false_full_in_quota": remaining_nav,
            "cases": navigation,
            "root_cause": "retrieval_text_is_clean_but_the_frozen_assembler_segments_preserved_display_text",
        },
        "pipeline_boundary": {
            "retrieval_contamination_removed": True,
            "citation_display_contamination_removed": False,
            "reason": "display_text and offsets were intentionally preserved, while the existing assembler segments display_text rather than retrieval_text",
            "next_levers_not_executed": [
                "offset-preserving segment eligibility mask for boilerplate ranges",
                "separate sanitized evidence_text view with original display offsets",
                "aggregate candidate-depth recall experiment rather than a case-specific top-k patch",
            ],
        },
        "frozen_metrics": {
            "grounded_before": p2_report["backbone"]["dirty"]["answerable"][
                "grounded_answer"
            ]["successes"],
            "grounded_after": p2_report["backbone"]["clean"]["answerable"][
                "grounded_answer"
            ]["successes"],
            "false_full_before": p2_report["backbone"]["dirty"]["answerable"][
                "false_full_answer"
            ]["successes"],
            "false_full_after": p2_report["backbone"]["clean"]["answerable"][
                "false_full_answer"
            ]["successes"],
            "exact_span_invalid": p2_report["assembler"]["exact_span_validity"][
                "invalid"
            ],
            "federated_temporal_violations": p2_report["safety"][
                "federated_temporal_revision_preview_violations"
            ],
        },
        "scope": {
            "model_run": False,
            "code_or_corpus_modified": False,
            "gold_label_or_question_changed": False,
            "canonical_or_runtime_promoted": False,
            "frozen_blind_accessed": False,
        },
    }


def build_and_freeze(root: Path, *, report_path: Path, signal_path: Path) -> dict[str, Any]:
    root = root.resolve()
    report_path = report_path if report_path.is_absolute() else root / report_path
    signal_path = signal_path if signal_path.is_absolute() else root / signal_path
    inputs = {
        "p2_report": report_path,
        "adaptive_dev": root
        / "data/v3/evaluation/retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl",
        "dirty_candidates": root
        / "data/v3/evidence/evidence_reranker_scores_ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl",
        "clean_candidates": root
        / "data/v3/evidence/evidence_reranker_scores_ec8155c90be580b183723682598649a6750720a93b7fa5bbd075ffbe8975e973.jsonl",
        "clean_signal_results": signal_path,
        "dirty_chunks": root
        / "data/v3/chunks/chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl",
        "clean_chunks": root
        / "data/v3/chunks/chunks_dnf_official_retrieval_clean_v3.1_61d858ef5b7df3a3c157e65dba9dd6991f1daa74bbd2067f17b2438e1c01b5b8.jsonl",
        "p1_adjudication": root
        / "data/v3/evaluation/federated_quota_regression_adjudication_e977562162a361f33decbcfc7f38ac136b53252bef81ad7a22de394a1eab4fcd.jsonl",
        "federated_cases": root
        / json.loads(report_path.read_text(encoding="utf-8"))["artifacts"][
            "federated_cases"
        ]["path"],
        "diagnostic_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    report = diagnose(
        p2_report=json.loads(inputs["p2_report"].read_text(encoding="utf-8")),
        dev_rows=read_jsonl(inputs["adaptive_dev"]),
        dirty_candidates=read_jsonl(inputs["dirty_candidates"]),
        clean_candidates=read_jsonl(inputs["clean_candidates"]),
        clean_signal_rows=read_jsonl(inputs["clean_signal_results"]),
        dirty_chunks=read_jsonl(inputs["dirty_chunks"]),
        clean_chunks=read_jsonl(inputs["clean_chunks"]),
        p1_rows=read_jsonl(inputs["p1_adjudication"]),
        federated_rows=read_jsonl(inputs["federated_cases"]),
    )
    reports_dir = root / "reports/v3"
    payload = _canonical_json_bytes(report)
    sha = _sha256_bytes(payload)
    output_path = reports_dir / f"corpus_hygiene_no_go_diagnostic_{sha}.json"
    write_immutable(output_path, payload)
    regression = report["hard_route_regression"]
    nav = report["p1_navigation_recheck"]
    metrics = report["frozen_metrics"]
    markdown = "\n".join(
        [
            "# Corpus hygiene NO-GO diagnostic",
            "",
            "## Result",
            "",
            f"- Grounded: {metrics['grounded_before']}/82 -> {metrics['grounded_after']}/82",
            f"- False full: {metrics['false_full_before']}/82 -> {metrics['false_full_after']}/82",
            f"- New regression: `{regression['case_id']}`; unchanged gold moved from rank {regression['dirty_candidate_rank']} to {regression['clean_signal_group_first_rank']} (outside top 10).",
            f"- P1 navigation cases resolved: {nav['resolved_in_quota']}/{nav['case_count']}; {nav['remaining_false_full_in_quota']} remain because the assembler segments preserved `display_text`.",
            f"- Exact invalid spans: {metrics['exact_span_invalid']}; federated temporal violations: {metrics['federated_temporal_violations']}",
            "",
            "The clean corpus is not promoted. Removing boilerplate from retrieval_text alone is insufficient while citation segmentation still consumes unchanged display_text.",
            "",
        ]
    ).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown)
    markdown_path = reports_dir / f"corpus_hygiene_no_go_diagnostic_{markdown_sha}.md"
    write_immutable(markdown_path, markdown)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "decision": report["decision"],
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "artifacts": {
            "report": {"path": _relative(root, output_path), "sha256": sha},
            "markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "scope": report["scope"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/chunks" / f"corpus_hygiene_no_go_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    changed = [name for name, path in inputs.items() if file_sha256(path) != before[name]]
    if changed:
        raise RuntimeError(f"Inputs changed during no-go diagnosis: {changed}")
    return {
        "report_path": str(output_path),
        "report_sha256": sha,
        "markdown_path": str(markdown_path),
        "markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "decision": report["decision"],
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Diagnose the corpus hygiene NO-GO")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--clean-signal-results", type=Path, required=True)
    args = parser.parse_args()
    result = build_and_freeze(
        args.root, report_path=args.report, signal_path=args.clean_signal_results
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
