from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.assemble_table_group_answers import assemble_table_group_answers
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable
from src.v3.gradio_backbone_demo import (
    DUPLICATE_FAMILY_OVERLAY,
    GLOBAL_TEMPORAL_OVERLAY,
    TABLE_INDEX_MANIFEST,
    build_duplicate_family_member_index,
    enrich_citation_metadata,
    filter_hits_by_global_temporal,
)


EVALUATOR_VERSION = "gradio-v3.2-candidate-integration-ab-v1"
REPORT_SCHEMA_VERSION = "dnf-gradio-v3.2-candidate-integration-report-v1"
MANIFEST_SCHEMA_VERSION = "dnf-gradio-v3.2-candidate-integration-manifest-v1"

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_TABLE_REPORT = Path(
    "reports/v3/table_atomic_facts_arm1_ab_"
    "05ffd0f81486700a6e561ac4f35f21c15865e47315107a0d56cdf581cf47fcd8.json"
)
DEFAULT_CONTRACT = Path("docs/v3/gradio_v3_2_candidate_integration.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/runtime")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def evaluate_wiring(
    *,
    chunks: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    selected_fact_ids: list[str],
    temporal_rows: list[dict[str, Any]],
    families: list[dict[str, Any]],
) -> dict[str, Any]:
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    facts_by_id = {row["fact_id"]: row for row in facts}
    seeds = [facts_by_id[fact_id] for fact_id in selected_fact_ids]
    table_views = assemble_table_group_answers(
        query="초월 가격",
        ranked_seed_facts=seeds,
        all_facts=facts,
        chunks_by_id=chunks_by_id,
    )
    table_labels = {
        row["label"]
        for view in table_views
        for row in view["rows"]
    }
    exact_mismatches = sum(
        view["exact_offset_mismatch_count"] for view in table_views
    )

    temporal_by_document = {row["document_id"]: row for row in temporal_rows}
    old_notice = next(
        row
        for row in temporal_rows
        if row["source_id"] == "dnf_notice"
        and row["validity_state"] == "current_unverified"
    )
    denied = next(
        row
        for row in temporal_rows
        if row["retrieval_action_current"] == "deny"
    )
    allowed_hits, denied_hits = filter_hits_by_global_temporal(
        [
            {"chunk_id": "old_notice", "parent_document_id": old_notice["document_id"]},
            {"chunk_id": "denied", "parent_document_id": denied["document_id"]},
        ],
        time_scope="current",
        temporal_by_document=temporal_by_document,
    )
    old_notice_metadata = enrich_citation_metadata(
        {"parent_document_id": old_notice["document_id"]},
        temporal_by_document=temporal_by_document,
        family_by_document={},
    )

    family_index = build_duplicate_family_member_index(families)
    family_document_id = sorted(family_index)[0]
    family_metadata = enrich_citation_metadata(
        {"parent_document_id": family_document_id},
        temporal_by_document=temporal_by_document,
        family_by_document=family_index,
    )
    source_roles = {
        value["source_role"] for value in family_index.values()
    }
    checks = {
        "table_views_added_vs_off": len(table_views) > 0,
        "transcendence_rarities_visible": {"유니크", "레전더리", "에픽", "태초"} <= table_labels,
        "table_exact_offsets_100_percent": exact_mismatches == 0,
        "current_denied_hit_filtered": len(denied_hits) == 1 and denied_hits[0]["chunk_id"] == "denied",
        "old_notice_retained_with_warning": len(allowed_hits) == 1
        and allowed_hits[0]["chunk_id"] == "old_notice"
        and bool(old_notice_metadata.get("temporal_warning"))
        and old_notice_metadata.get("last_verified_at") is None,
        "duplicate_family_metadata_visible": bool(family_metadata.get("duplicate_family_id")),
        "duplicate_source_roles_preserved": {
            "event_terms_eligibility_rewards",
            "commerce_price_components_trade_deletion",
        } <= source_roles,
    }
    return {
        "off": {
            "complete_table_views": 0,
            "temporal_metadata_visible": 0,
            "duplicate_family_metadata_visible": 0,
        },
        "on": {
            "complete_table_views": len(table_views),
            "complete_table_captions": [view["caption"] for view in table_views],
            "table_row_count": sum(view["row_count"] for view in table_views),
            "exact_offset_mismatch_count": exact_mismatches,
            "current_denied_hits": len(denied_hits),
            "old_notice_validity_state": old_notice_metadata["validity_state"],
            "old_notice_warning_visible": bool(old_notice_metadata.get("temporal_warning")),
            "duplicate_family_id": family_metadata["duplicate_family_id"],
            "duplicate_source_role": family_metadata["source_role"],
        },
        "checks": checks,
        "pass": all(checks.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    ab = report["ab"]
    return "\n".join(
        [
            "# Gradio v3.2 GO-candidate integration A/B",
            "",
            f"Decision: **{report['decision']}**. This remains a development demo; canonical/runtime promotion is false.",
            "",
            "| Output capability | OFF | ON |",
            "|---|---:|---:|",
            f"| Complete table views | {ab['off']['complete_table_views']} | {ab['on']['complete_table_views']} |",
            f"| Temporal metadata visible | {ab['off']['temporal_metadata_visible']} | 1 |",
            f"| Duplicate-family metadata visible | {ab['off']['duplicate_family_metadata_visible']} | 1 |",
            f"| Exact table offset mismatches | 0 | {ab['on']['exact_offset_mismatch_count']} |",
            "",
            "ON keeps old current-unverified notices visible with a warning, filters explicit current-mode denials, and labels duplicate-family source roles without merging documents.",
        ]
    ) + "\n"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    table_index_manifest = json.loads(
        (root / TABLE_INDEX_MANIFEST).read_text(encoding="utf-8")
    )
    table_facts = Path(table_index_manifest["dense"]["metadata_path"])
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    facts = read_jsonl(root / table_facts)
    temporal_rows = read_jsonl(root / GLOBAL_TEMPORAL_OVERLAY)
    families = read_jsonl(root / DUPLICATE_FAMILY_OVERLAY)
    table_report = json.loads((root / DEFAULT_TABLE_REPORT).read_text(encoding="utf-8"))
    generic_probe = next(
        row
        for row in table_report["transcendence_probe"]["probes"]
        if row["probe_id"] == "transcendence_generic"
    )
    ab = evaluate_wiring(
        chunks=chunks,
        facts=facts,
        selected_fact_ids=generic_probe["selected_fact_ids"],
        temporal_rows=temporal_rows,
        families=families,
    )
    decision = (
        "GO_DEVELOPMENT_DEMO_V3_2_CANDIDATE_WIRING_NOT_PROMOTED"
        if ab["pass"]
        else "NO_GO"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "status": "development_only_not_promoted",
        "ab": ab,
        "decision": decision,
        "scope": {
            "dirty_canonical_changed": False,
            "planner_changed": False,
            "retrieval_model_changed": False,
            "gold_changed": False,
            "sealed_canary_run": False,
            "promoted": False,
        },
    }
    report_dir = root / DEFAULT_REPORT_DIR
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"gradio_v3_2_candidate_integration_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"gradio_v3_2_candidate_integration_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    inputs = {
        "chunks": DEFAULT_CHUNKS,
        "documents": DEFAULT_DOCUMENTS,
        "table_facts": table_facts,
        "table_index_manifest": TABLE_INDEX_MANIFEST,
        "table_report": DEFAULT_TABLE_REPORT,
        "global_temporal_overlay": GLOBAL_TEMPORAL_OVERLAY,
        "duplicate_family_overlay": DUPLICATE_FAMILY_OVERLAY,
        "contract": DEFAULT_CONTRACT,
        "demo_source": Path("src/v3/gradio_backbone_demo.py"),
        "evaluator_source": Path(__file__).resolve().relative_to(root),
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {
            name: {"path": path.as_posix(), "sha256": file_sha256(root / path)}
            for name, path in inputs.items()
        },
        "artifacts": {
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "gate": {"pass": ab["pass"], "checks": ab["checks"], "decision": decision, "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / DEFAULT_OUTPUT_DIR / f"gradio_v3_2_candidate_integration_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"manifest": manifest_path.relative_to(root).as_posix(), "report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), **report}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
