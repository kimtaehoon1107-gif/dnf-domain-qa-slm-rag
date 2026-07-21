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
from src.v3.build_bm25 import SearchPolicy, build_bm25_index, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "faq-title-dedup-view-v3.2-arm6.0"
REPORT_SCHEMA_VERSION = "dnf-faq-title-dedup-report-v3.2"
MANIFEST_SCHEMA_VERSION = "dnf-faq-title-dedup-manifest-v3.2"
TOP_K = 10

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/faq_title_dedup_arm6.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/evidence")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def deduplicate_faq_titles(
    chunks: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    titles = {row["document_id"]: row["title"] for row in documents}
    output = []
    changed = 0
    removed_characters = 0
    for chunk in chunks:
        updated = dict(chunk)
        if chunk["source_id"] == "dnf_faq":
            title = titles[chunk["parent_document_id"]]
            duplicate_prefix = f"{title}\n{title}\n"
            if chunk["retrieval_text"].startswith(duplicate_prefix):
                updated["retrieval_text"] = f"{title}\n{chunk['retrieval_text'][len(duplicate_prefix):]}"
                changed += 1
                removed_characters += len(title) + 1
        output.append(updated)
    return output, {
        "changed_chunk_count": changed,
        "removed_character_count": removed_characters,
    }


def _policy(row: dict[str, Any]) -> SearchPolicy:
    query_policy = row.get("query_policy", {})
    statuses = query_policy.get("allowed_statuses") or row.get("target_statuses") or ["current"]
    return SearchPolicy(
        default_exposure_only=query_policy.get("default_exposure_only", True),
        allowed_statuses=tuple(statuses),
        include_review_required=query_policy.get("include_review_required", False),
        as_of=query_policy.get("as_of") or row.get("as_of"),
        source_ids=("dnf_faq",),
    )


def evaluate_ab(
    baseline_chunks: list[dict[str, Any]],
    arm_chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> dict[str, Any]:
    faq_rows = [row for row in evaluations if "dnf_faq" in row.get("source_ids", [])]
    baseline_index = build_bm25_index(baseline_chunks, documents)
    arm_index = build_bm25_index(arm_chunks, documents)
    baseline_group_hits = 0
    arm_group_hits = 0
    baseline_question_hits = 0
    arm_question_hits = 0
    group_count = 0
    regressions = []
    improvements = []
    for evaluation in faq_rows:
        policy = _policy(evaluation)
        baseline_ids = {
            result["chunk_id"]
            for result in search_bm25(
                baseline_index, evaluation["question"], top_k=TOP_K, policy=policy
            )
        }
        arm_ids = {
            result["chunk_id"]
            for result in search_bm25(
                arm_index, evaluation["question"], top_k=TOP_K, policy=policy
            )
        }
        baseline_hits = []
        arm_hits = []
        for group in evaluation["evidence_groups"]:
            group_count += 1
            acceptable = set(group.get("acceptable_chunk_ids", []))
            baseline_hit = bool(baseline_ids & acceptable)
            arm_hit = bool(arm_ids & acceptable)
            baseline_hits.append(baseline_hit)
            arm_hits.append(arm_hit)
            baseline_group_hits += baseline_hit
            arm_group_hits += arm_hit
            identity = {"case_id": evaluation["dev_id"], "group_id": group["group_id"]}
            if baseline_hit and not arm_hit:
                regressions.append(identity)
            elif arm_hit and not baseline_hit:
                improvements.append(identity)
        baseline_question_hits += all(baseline_hits)
        arm_question_hits += all(arm_hits)
    return {
        "top_k": TOP_K,
        "faq_question_count": len(faq_rows),
        "evidence_group_count": group_count,
        "baseline": {"evidence_groups_hit": baseline_group_hits, "all_groups_covered_questions": baseline_question_hits},
        "arm6": {"evidence_groups_hit": arm_group_hits, "all_groups_covered_questions": arm_question_hits},
        "improvements": improvements,
        "regressions": regressions,
    }


def _non_retrieval_hash(row: dict[str, Any]) -> str:
    return _sha256_bytes(
        _canonical_json_bytes({key: value for key, value in row.items() if key != "retrieval_text"})
    )


def _markdown(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    return "\n".join(
        [
            "# v3.2 Arm 6 — FAQ title deduplication A/B",
            "",
            f"Decision: **{report['decision']}**. Runtime/canonical was not promoted.",
            "",
            "| Measure | Baseline | Deduplicated view |",
            "|---|---:|---:|",
            f"| FAQ chunks with redundant title removed | 0 | {report['cleaning']['changed_chunk_count']} |",
            f"| Evidence groups hit at {evaluation['top_k']} | {evaluation['baseline']['evidence_groups_hit']} | {evaluation['arm6']['evidence_groups_hit']} |",
            f"| All-groups questions | {evaluation['baseline']['all_groups_covered_questions']} | {evaluation['arm6']['all_groups_covered_questions']} |",
            f"| Strict regressions | 0 | {len(evaluation['regressions'])} |",
            "",
            "Shorter retrieval text alone is not sufficient for adoption; measured retrieval must improve.",
        ]
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and A/B FAQ title-deduplicated retrieval view")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    documents = read_jsonl(root / DEFAULT_DOCUMENTS)
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    evaluations = read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV)
    cleaned, cleaning = deduplicate_faq_titles(chunks, documents)
    evaluation = evaluate_ab(chunks, cleaned, documents, evaluations)
    non_retrieval_mismatches = sum(
        _non_retrieval_hash(before) != _non_retrieval_hash(after)
        for before, after in zip(chunks, cleaned, strict=True)
    )
    non_faq_changes = sum(
        before["retrieval_text"] != after["retrieval_text"] and before["source_id"] != "dnf_faq"
        for before, after in zip(chunks, cleaned, strict=True)
    )
    gates = {
        "all_279_exact_duplicate_titles_removed": cleaning["changed_chunk_count"] == 279,
        "non_retrieval_fields_unchanged": non_retrieval_mismatches == 0,
        "non_faq_retrieval_text_unchanged": non_faq_changes == 0,
        "evidence_group_recall_improved": evaluation["arm6"]["evidence_groups_hit"] > evaluation["baseline"]["evidence_groups_hit"],
        "all_groups_question_recall_not_lower": evaluation["arm6"]["all_groups_covered_questions"] >= evaluation["baseline"]["all_groups_covered_questions"],
        "strict_regression_zero": not evaluation["regressions"],
    }
    decision = "GO_ARM6_FAQ_TITLE_DEDUP_CANDIDATE_NOT_PROMOTED" if all(gates.values()) else "NO_GO"
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": "development_only_not_promoted",
        "cleaning": cleaning,
        "evaluation": evaluation,
        "integrity": {"non_retrieval_mismatch_count": non_retrieval_mismatches, "non_faq_change_count": non_faq_changes},
        "gates": gates,
        "decision": decision,
        "scope": {"display_text_changed": False, "chunk_ids_changed": False, "gold_changed": False, "runtime_changed": False, "promoted": False},
    }
    output_dir = root / args.output_dir
    view_bytes = _serialize_jsonl(cleaned, lambda row: row["chunk_id"])
    view_sha = _sha256_bytes(view_bytes)
    view_path = output_dir / f"faq_title_dedup_view_v3.2_{view_sha}.jsonl"
    write_immutable(view_path, view_bytes)
    report_dir = root / args.report_dir
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"faq_title_dedup_arm6_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"faq_title_dedup_arm6_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    inputs = {"documents": DEFAULT_DOCUMENTS, "chunks": DEFAULT_CHUNKS, "adaptive_dev": DEFAULT_DEV, "downgraded_canary": DEFAULT_CANARY, "contract": DEFAULT_CONTRACT, "builder_source": Path(__file__).resolve().relative_to(root)}
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {name: {"path": path.as_posix(), "sha256": file_sha256(root / path)} for name, path in inputs.items()},
        "artifacts": {"view": {"path": view_path.relative_to(root).as_posix(), "sha256": view_sha, "row_count": len(cleaned)}, "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha}, "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha}},
        "gate": {"pass": all(gates.values()), "checks": gates, "decision": decision, "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"faq_title_dedup_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"view": view_path.relative_to(root).as_posix(), "manifest": manifest_path.relative_to(root).as_posix(), "report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), "cleaning": cleaning, "evaluation": evaluation, "gates": gates, "decision": decision}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
