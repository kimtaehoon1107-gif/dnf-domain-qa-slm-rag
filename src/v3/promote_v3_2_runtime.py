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


PROMOTER_VERSION = "v3.2-development-canonical-promoter-v1.0.0"
MANIFEST_SCHEMA_VERSION = "v3.2-canonical-runtime-manifest-v1"
REPORT_SCHEMA_VERSION = "v3.2-runtime-promotion-report-v1"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/bm25_manifest_"
    "f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_DENSE_MANIFEST = Path(
    "data/v3/indexes/dense_full_manifest_"
    "51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)
DEFAULT_ASSEMBLER_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_"
    "9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json"
)
DEFAULT_TABLE_FACTS = Path(
    "data/v3/structured/table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_TABLE_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_manifest_"
    "c173c32935d25b0e3753caa65392eeacf667b01bdc991a6da7aaf5e45fb71666.json"
)
DEFAULT_TABLE_INDEX_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_index_manifest_"
    "423dfd6ae35bbfa5db1cef0ea1caa61df547ed99c508c998fd134f44f1c4f79d.json"
)
DEFAULT_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DEFAULT_DUPLICATE_OVERLAY = Path(
    "data/v3/structured/duplicate_family_overlay_v3.2_"
    "d71e7184b95a4bbdf8a4748b24daf5ce6b2d67834507660f905ffc869faaa336.jsonl"
)
DEFAULT_AB_REPORT = Path(
    "reports/v3/table_atomic_facts_arm1_ab_"
    "05ffd0f81486700a6e561ac4f35f21c15865e47315107a0d56cdf581cf47fcd8.json"
)
DEFAULT_AB_CASES = Path(
    "data/v3/evidence/table_atomic_facts_arm1_ab_cases_"
    "3645533a5f289b65f7e8a1729336876f02bc50e3f93d0e8a582bc3978db829cc.jsonl"
)
DEFAULT_CANARY_CONTRACT_MANIFEST = Path(
    "data/v3/evaluation/v3_2_promotion_canary_manifest_"
    "9373cbb9ce99834a6d48eb450ad4ebb72c961bf207b2621a07e23b40cd30ff8c.json"
)
DEFAULT_CONTRACT = Path("docs/v3/v3_2_runtime_promotion.md")
DEFAULT_SOURCE = Path("src/v3/promote_v3_2_runtime.py")
DEFAULT_RUNTIME_SOURCE = Path("src/v3/gradio_backbone_demo.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def audit_promotion_basis(
    report: dict[str, Any], cases: list[dict[str, Any]]
) -> dict[str, Any]:
    metrics = report["ab_metrics"]
    recall = report["candidate_recall"]
    integrity = report["integrity"]
    answerable = [
        row for row in cases if row.get("answerability_target") == "answerable_docs"
    ]
    response_changes = [
        row["case_id"]
        for row in cases
        if row["baseline"]["response_mode"] != row["arm1"]["response_mode"]
    ]
    score_changes = [
        row["case_id"]
        for row in cases
        if row["baseline"]["score"] != row["arm1"]["score"]
    ]
    removed_citations: dict[str, list[str]] = {}
    added_citation_count = 0
    selected_facts: list[dict[str, Any]] = []
    for row in cases:
        baseline = set(row["baseline"].get("cited_chunk_ids", []))
        arm1 = set(row["arm1"].get("cited_chunk_ids", []))
        removed = sorted(baseline - arm1)
        if removed:
            removed_citations[row["case_id"]] = removed
        added_citation_count += len(arm1 - baseline)
        for requirement in row.get("row_children", []):
            selected_facts.extend(requirement.get("selected", []))
    value_not_in_row = [
        row["fact_id"]
        for row in selected_facts
        if str(row.get("value", "")) not in str(row.get("row_text", ""))
    ]
    checks = {
        "case_count_95": len(cases) == 95,
        "answerable_count_82": len(answerable) == 82,
        "response_mode_change_zero": not response_changes,
        "score_change_zero": not score_changes,
        "grounded_73_preserved": metrics["baseline"]["grounded"]["successes"]
        == metrics["arm1"]["grounded"]["successes"]
        == 73,
        "false_full_9_preserved": metrics["baseline"]["false_full"]["successes"]
        == metrics["arm1"]["false_full"]["successes"]
        == 9,
        "new_false_full_zero": metrics["new_false_full_count"] == 0,
        "evidence_group_coverage_preserved": recall["baseline"]["evidence_groups"]
        == recall["arm1"]["evidence_groups"],
        "parent_rank_perturbation_zero": recall["parent_rank_perturbation_count"] == 0,
        "existing_citation_removed_zero": not removed_citations,
        "selected_fact_value_exact": not value_not_in_row,
        "exact_offset_100_percent": integrity["exact_offset_rate"] == 1.0
        and integrity["offset_mismatch_count"] == 0,
        "gold_content_loss_zero": integrity["gold_content_loss_count"] == 0,
        "temporal_leak_zero": integrity["temporal_leak_count"] == 0,
        "replacement_character_zero": integrity["replacement_character_count"] == 0,
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "case_count": len(cases),
        "answerable_count": len(answerable),
        "response_mode_change_ids": response_changes,
        "score_change_ids": score_changes,
        "removed_citations": removed_citations,
        "added_citation_count": added_citation_count,
        "selected_fact_count": len(selected_facts),
        "value_not_in_row_fact_ids": value_not_in_row,
        "known_false_full": {"successes": 9, "total": 82},
    }


def _markdown(report: dict[str, Any]) -> str:
    audit = report["promotion_basis_audit"]
    return "\n".join(
        [
            "# DNF RAG v3.2 development canonical promotion",
            "",
            f"Decision: **{report['decision']}**",
            "",
            "The v3.2 additive table, temporal, and duplicate-family view is now the default development canonical runtime.",
            "This is an explicit user-authorized promotion based on the existing 95-case A/B; the new sealed canary was not run.",
            "",
            "| Check | Result |",
            "|---|---:|",
            f"| Existing cases | {audit['case_count']} |",
            "| Grounded | 73/82 -> 73/82 |",
            "| False-full | 9/82 -> 9/82 |",
            f"| Added citations | {audit['added_citation_count']} |",
            f"| Selected atomic facts | {audit['selected_fact_count']} |",
            "| Removed citations | 0 |",
            "| Response-mode changes | 0 |",
            "| Exact offset mismatches | 0 |",
            "| Temporal leaks | 0 |",
            "",
            "Known limitation: 9/82 false-full remains. This promotion does not claim production readiness or final-benchmark completion.",
        ]
    ) + "\n"


def promote(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    paths = {
        "documents": DEFAULT_DOCUMENTS,
        "chunks": DEFAULT_CHUNKS,
        "bm25_manifest": DEFAULT_BM25_MANIFEST,
        "dense_manifest": DEFAULT_DENSE_MANIFEST,
        "assembler_manifest": DEFAULT_ASSEMBLER_MANIFEST,
        "table_atomic_facts": DEFAULT_TABLE_FACTS,
        "table_atomic_facts_manifest": DEFAULT_TABLE_MANIFEST,
        "table_index_manifest": DEFAULT_TABLE_INDEX_MANIFEST,
        "global_temporal_overlay": DEFAULT_TEMPORAL_OVERLAY,
        "duplicate_family_overlay": DEFAULT_DUPLICATE_OVERLAY,
        "ab_report": DEFAULT_AB_REPORT,
        "ab_cases": DEFAULT_AB_CASES,
        "unexecuted_canary_contract_manifest": DEFAULT_CANARY_CONTRACT_MANIFEST,
        "promotion_contract": DEFAULT_CONTRACT,
        "promoter_source": DEFAULT_SOURCE,
        "runtime_source": DEFAULT_RUNTIME_SOURCE,
    }
    resolved = {name: root / path for name, path in paths.items()}
    missing = [name for name, path in resolved.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing v3.2 promotion inputs: {missing}")
    before = {name: file_sha256(path) for name, path in resolved.items()}
    report = json.loads(resolved["ab_report"].read_text(encoding="utf-8"))
    cases = read_jsonl(resolved["ab_cases"])
    audit = audit_promotion_basis(report, cases)
    if not audit["pass"]:
        raise RuntimeError(f"v3.2 promotion basis failed: {audit['checks']}")

    promotion_report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "promoter_version": PROMOTER_VERSION,
        "decision": "PROMOTED_V3_2_DEVELOPMENT_CANONICAL_BY_EXPLICIT_USER_AUTHORIZATION",
        "promotion_scope": "default_v3_development_runtime_and_canonical_retrieval_view",
        "production_ready": False,
        "final_benchmark_complete": False,
        "promotion_basis_audit": audit,
        "known_limitations": {
            "false_full": {"successes": 9, "total": 82},
            "new_sealed_canary_run": False,
            "semantic_correctness_guaranteed_by_exact_slice": False,
        },
        "gate_override": {
            "reason": "explicit_user_authorization_after_existing_95_case_nonregression_review",
            "sealed_canary_contract_frozen": True,
            "sealed_canary_executed": False,
            "waiver_scope": "development_default_only_not_production",
        },
        "preservation": {
            "dirty_base_changed": False,
            "prior_artifacts_deleted": False,
            "failed_experiments_deleted": False,
        },
    }
    reports_dir = root / "reports/v3"
    report_bytes = _canonical_json_bytes(promotion_report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"v3_2_runtime_promotion_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(promotion_report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"v3_2_runtime_promotion_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "promoter_version": PROMOTER_VERSION,
        "status": "canonical_v3_2_development_default_promoted",
        "promotion_scope": promotion_report["promotion_scope"],
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in resolved.items()
        },
        "canonical_runtime": {
            "base_documents": DEFAULT_DOCUMENTS.as_posix(),
            "base_chunks": DEFAULT_CHUNKS.as_posix(),
            "table_atomic_facts": DEFAULT_TABLE_FACTS.as_posix(),
            "table_index_manifest": DEFAULT_TABLE_INDEX_MANIFEST.as_posix(),
            "global_temporal_overlay": DEFAULT_TEMPORAL_OVERLAY.as_posix(),
            "duplicate_family_overlay": DEFAULT_DUPLICATE_OVERLAY.as_posix(),
            "v3_2_additive_features_default_enabled": True,
            "diagnostic_baseline_disable_switch_preserved": True,
        },
        "evidence": {
            "promotion_report": {"path": _relative(root, report_path), "sha256": report_sha},
            "promotion_report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
            "basis_audit": audit,
        },
        "authorization": {
            "kind": "explicit_user_request",
            "sealed_canary_waived_for_this_development_promotion": True,
        },
        "production_ready": False,
        "final_benchmark_complete": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/runtime" / f"canonical_runtime_v3_2_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in resolved.items():
        if file_sha256(path) != before[name]:
            raise RuntimeError(f"Promotion input changed during freeze: {name}")
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": promotion_report["decision"],
        "promotion_basis_audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote the reviewed v3.2 additive development runtime"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(promote(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

