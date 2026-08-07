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
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "duplicate-family-overlay-v3.2-arm4.1"
OVERLAY_SCHEMA_VERSION = "dnf-duplicate-family-overlay-v3.2"
REPORT_SCHEMA_VERSION = "dnf-duplicate-family-overlay-report-v3.2"
MANIFEST_SCHEMA_VERSION = "dnf-duplicate-family-overlay-manifest-v3.2"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_RELATIONS = Path(
    "data/v3/chunks/duplicate_parent_relations_"
    "295da995ec734e9b3210940040dc2cb4a6fc4b9202187e2e7b116eb5e80dcf66.jsonl"
)
DEFAULT_RERANKER_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/duplicate_family_overlay_arm4.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/structured")
DEFAULT_REPORT_DIR = Path("reports/v3")


SOURCE_ROLES = {
    "dnf_event": "event_terms_eligibility_rewards",
    "dnf_seria_shop": "commerce_price_components_trade_deletion",
    "dnf_monthly_item": "monthly_price_trade_deletion",
}

EVENT_ATTRIBUTES = ("event_period", "eligibility", "reward", "claim_method")
COMMERCE_ATTRIBUTES = (
    "price",
    "currency",
    "sale_period",
    "sale_status",
    "components",
    "trade_type",
    "deletion_at",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _family_id(normalized_title_key: str, document_ids: list[str]) -> str:
    payload = _canonical_json_bytes(
        {"normalized_title_key": normalized_title_key, "document_ids": sorted(document_ids)}
    )
    return f"duplicate_family_sha256_{_sha256_bytes(payload)}"


def _preferred_sources(source_ids: set[str]) -> dict[str, str | None]:
    event_source = "dnf_event" if "dnf_event" in source_ids else None
    if "dnf_monthly_item" in source_ids:
        commerce_source = "dnf_monthly_item"
    elif "dnf_seria_shop" in source_ids:
        commerce_source = "dnf_seria_shop"
    else:
        commerce_source = None
    return {
        **{attribute: event_source for attribute in EVENT_ATTRIBUTES},
        **{attribute: commerce_source for attribute in COMMERCE_ATTRIBUTES},
    }


def build_duplicate_families(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families = []
    for relation in relations:
        members = relation["parent_documents"]
        document_ids = [member["parent_document_id"] for member in members]
        source_ids = {member["source_id"] for member in members}
        families.append(
            {
                "duplicate_family_schema_version": OVERLAY_SCHEMA_VERSION,
                "duplicate_family_id": _family_id(
                    relation["normalized_title_key"], document_ids
                ),
                "relation_kind": "same_official_entity_candidate",
                "relation_basis": "cross_source_exact_normalized_title",
                "review_status": "requires_semantic_confirmation",
                "normalized_title_key": relation["normalized_title_key"],
                "members": [
                    {
                        **member,
                        "source_role": SOURCE_ROLES[member["source_id"]],
                    }
                    for member in sorted(members, key=lambda row: row["parent_document_id"])
                ],
                "preferred_source_by_attribute": _preferred_sources(source_ids),
                "used_for_document_merge": False,
                "used_for_retrieval_deduplication": False,
                "used_for_runtime_ranking": False,
            }
        )
    return sorted(families, key=lambda row: row["duplicate_family_id"])


def evaluate_overlay(
    families: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    document_by_id = {row["document_id"]: row for row in documents}
    family_by_document: dict[str, str] = {}
    for family in families:
        for member in family["members"]:
            family_by_document[member["parent_document_id"]] = family["duplicate_family_id"]
    chunk_to_document = {
        row["chunk_id"]: row["parent_document_id"] for row in chunks
    }

    cases_with_family_candidate: set[str] = set()
    requirements_with_family_candidate = 0
    requirements_with_multiple_family_members = 0
    for score_row in score_rows:
        for requirement in score_row["requirements"]:
            member_documents = {
                chunk_to_document[candidate["chunk_id"]]
                for candidate in requirement["candidates"]
                if chunk_to_document.get(candidate["chunk_id"]) in family_by_document
            }
            if member_documents:
                cases_with_family_candidate.add(score_row["case_id"])
                requirements_with_family_candidate += 1
            family_counts = Counter(
                family_by_document[document_id] for document_id in member_documents
            )
            if any(count > 1 for count in family_counts.values()):
                requirements_with_multiple_family_members += 1

    member_rows = [member for family in families for member in family["members"]]
    member_ids = {member["parent_document_id"] for member in member_rows}
    gold_document_ids = {
        document_id
        for row in evaluation_rows
        for group in row.get("evidence_groups", [])
        for document_id in group.get("document_ids", [])
    }
    all_preference_maps = [
        family["preferred_source_by_attribute"] for family in families
    ]
    all_preferences = [
        preferred
        for preference_map in all_preference_maps
        for preferred in preference_map.values()
    ]
    gates = {
        "seven_candidate_families_preserved": len(families) == 7,
        "all_fourteen_members_preserved": len(member_rows) == 14 and len(member_ids) == 14,
        "all_members_exist_unchanged": all(
            member["parent_document_id"] in document_by_id
            and document_by_id[member["parent_document_id"]]["content_hash"]
            == member["content_hash"]
            for member in member_rows
        ),
        "all_members_have_source_roles": all(member.get("source_role") for member in member_rows),
        "every_family_is_cross_source": all(
            len({member["source_id"] for member in family["members"]}) >= 2
            for family in families
        ),
        "attribute_preference_contract_complete": all(
            set(preference_map) == set(EVENT_ATTRIBUTES) | set(COMMERCE_ATTRIBUTES)
            for preference_map in all_preference_maps
        ),
        "preferred_sources_are_family_members": all(
            preferred is None
            or preferred in {member["source_id"] for member in family["members"]}
            for family in families
            for preferred in family["preferred_source_by_attribute"].values()
        ),
        "candidate_status_not_overclaimed": all(
            family["review_status"] == "requires_semantic_confirmation"
            and family["relation_kind"] == "same_official_entity_candidate"
            for family in families
        ),
        "no_merge_or_runtime_dedup": all(
            not family["used_for_document_merge"]
            and not family["used_for_retrieval_deduplication"]
            and not family["used_for_runtime_ranking"]
            for family in families
        ),
        "gold_document_loss_zero": gold_document_ids <= set(document_by_id),
    }
    return {
        "baseline": {
            "raw_relation_candidate_count": len(families),
            "structured_family_count": 0,
            "members_with_source_role": 0,
            "attribute_preference_entries": 0,
            "runtime_changed": False,
        },
        "arm4": {
            "structured_family_count": len(families),
            "family_member_count": len(member_rows),
            "members_with_source_role": sum(bool(member.get("source_role")) for member in member_rows),
            "attribute_preference_entries": len(all_preferences),
            "resolved_attribute_preference_entries": sum(
                preferred is not None for preferred in all_preferences
            ),
            "candidate_cases_observed": len(cases_with_family_candidate),
            "candidate_requirements_observed": requirements_with_family_candidate,
            "requirements_with_multiple_family_members": requirements_with_multiple_family_members,
            "gold_document_loss_count": len(gold_document_ids - set(document_by_id)),
            "document_rows_changed": 0,
            "chunk_rows_changed": 0,
            "runtime_changed": False,
        },
        "gates": gates,
        "gate_pass": all(gates.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    before = report["evaluation"]["baseline"]
    after = report["evaluation"]["arm4"]
    return "\n".join(
        [
            "# v3.2 Arm 4 — duplicate-family overlay A/B",
            "",
            f"Decision: **{report['decision']}**. Runtime/canonical was not promoted.",
            "",
            "| Measure | Before | Arm 4 |",
            "|---|---:|---:|",
            f"| Structured families | {before['structured_family_count']} | {after['structured_family_count']} |",
            f"| Members with source role | {before['members_with_source_role']} | {after['members_with_source_role']} |",
            f"| Attribute preference entries | {before['attribute_preference_entries']} | {after['attribute_preference_entries']} |",
            f"| Gold document loss | 0 | {after['gold_document_loss_count']} |",
            f"| Runtime behavior changed | {before['runtime_changed']} | {after['runtime_changed']} |",
            "",
            f"The frozen candidate pools contain family members in {after['candidate_cases_observed']} cases and {after['candidate_requirements_observed']} requirements; {after['requirements_with_multiple_family_members']} requirements contain multiple members of one family.",
            "",
            "This arm improves relationship provenance only. It deliberately does not claim that title equality proves semantic identity, and it does not deduplicate or rerank candidates.",
        ]
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and audit duplicate-family metadata")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    documents = read_jsonl(root / DEFAULT_DOCUMENTS)
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    relations = read_jsonl(root / DEFAULT_RELATIONS)
    scores = read_jsonl(root / DEFAULT_RERANKER_SCORES)
    evaluations = read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV)
    families = build_duplicate_families(relations)
    evaluation = evaluate_overlay(families, documents, chunks, scores, evaluations)
    decision = (
        "GO_ARM4_ADDITIVE_METADATA_CANDIDATE_NOT_RUNTIME_APPLIED"
        if evaluation["gate_pass"]
        else "NO_GO"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": "development_only_not_promoted",
        "evaluation": evaluation,
        "decision": decision,
        "scope": {
            "documents_changed": False,
            "chunks_changed": False,
            "retrieval_changed": False,
            "gold_changed": False,
            "promoted": False,
        },
    }

    output_dir = root / args.output_dir
    family_bytes = _serialize_jsonl(families, lambda row: row["duplicate_family_id"])
    family_sha = _sha256_bytes(family_bytes)
    family_path = output_dir / f"duplicate_family_overlay_v3.2_{family_sha}.jsonl"
    write_immutable(family_path, family_bytes)

    report_dir = root / args.report_dir
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"duplicate_family_overlay_arm4_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"duplicate_family_overlay_arm4_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    inputs = {
        "documents": DEFAULT_DOCUMENTS,
        "chunks": DEFAULT_CHUNKS,
        "candidate_relations": DEFAULT_RELATIONS,
        "reranker_scores": DEFAULT_RERANKER_SCORES,
        "adaptive_dev": DEFAULT_DEV,
        "downgraded_canary": DEFAULT_CANARY,
        "contract": DEFAULT_CONTRACT,
        "builder_source": Path(__file__).resolve().relative_to(root),
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {
            name: {"path": path.as_posix(), "sha256": file_sha256(root / path)}
            for name, path in inputs.items()
        },
        "artifacts": {
            "overlay": {"path": family_path.relative_to(root).as_posix(), "sha256": family_sha, "row_count": len(families)},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "gate": {"pass": evaluation["gate_pass"], "checks": evaluation["gates"], "decision": decision, "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"duplicate_family_overlay_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(
        json.dumps(
            {
                "overlay": family_path.relative_to(root).as_posix(),
                "manifest": manifest_path.relative_to(root).as_posix(),
                "report": report_path.relative_to(root).as_posix(),
                "report_markdown": markdown_path.relative_to(root).as_posix(),
                "evaluation": evaluation,
                "decision": decision,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
