from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.review_entailment_app import validate_draft_structure


TemporalMode = Literal["current", "historical", "comparison"]

TEMPORAL_SCHEMA_VERSION = "dnf_account_policy_temporal_revision_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_account_policy_temporal_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_account_policy_temporal_report_v3.1"
BUILDER_VERSION = "dnf-account-policy-temporal-builder-v3.1.0"
BUILT_AT = "2026-07-19T03:30:00+09:00"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BM25_INDEX = Path(
    "data/v3/indexes/"
    "bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
DEFAULT_CONFLICT_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_revision_conflict_packet_8c2b64e9844458503e771a8a8f5d622eccdb857ae6629c4113f1c5b4e957ce4f.jsonl"
)
DEFAULT_CONFLICT_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_revision_conflict_draft_8c2b64e9844458503e771a8a8f5d622eccdb857ae6629c4113f1c5b4e957ce4f.jsonl"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/temporal_policy.py")
DEFAULT_SEARCH_SOURCE = Path("src/v3/build_bm25.py")
DEFAULT_SCHEMA_SOURCE = Path("src/v3/schemas.py")
DEFAULT_CONTRACT = Path("docs/v3/temporal_policy.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _iso_date(value: str | None, field: str) -> date:
    if not isinstance(value, str):
        raise RuntimeError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise RuntimeError(f"Invalid {field}: {value}") from exc


def build_policy_overlay(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    policies = [row for row in documents if row["source_id"] == "dnf_account_policy"]
    if not policies:
        raise RuntimeError("No dnf_account_policy documents")
    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for row in policies:
        by_lineage.setdefault(row["lineage_id"], []).append(row)

    output = []
    for lineage_id, lineage_rows in sorted(by_lineage.items()):
        ordered = sorted(
            lineage_rows,
            key=lambda row: (
                _iso_date(row.get("valid_from"), "valid_from"),
                row["document_id"],
            ),
        )
        starts = [_iso_date(row.get("valid_from"), "valid_from") for row in ordered]
        if len(starts) != len(set(starts)):
            raise RuntimeError(f"Duplicate policy valid_from in lineage: {lineage_id}")
        for ordinal, row in enumerate(ordered):
            previous = ordered[ordinal - 1] if ordinal else None
            following = ordered[ordinal + 1] if ordinal + 1 < len(ordered) else None
            if row["supersedes_document_id"] != (
                previous["document_id"] if previous else None
            ):
                raise RuntimeError(
                    f"Broken supersedes link: {row['document_id']}"
                )
            is_current = following is None
            expected_status = "current" if is_current else "superseded"
            if row["status"] != expected_status:
                raise RuntimeError(
                    f"Unexpected policy status for {row['document_id']}: {row['status']}"
                )
            if row["default_exposure"] is not is_current:
                raise RuntimeError(
                    f"Unexpected policy default exposure: {row['document_id']}"
                )
            valid_to = (
                (starts[ordinal + 1] - timedelta(days=1)).isoformat()
                if following is not None
                else None
            )
            output.append(
                {
                    "temporal_schema_version": TEMPORAL_SCHEMA_VERSION,
                    "document_id": row["document_id"],
                    "lineage_id": lineage_id,
                    "source_id": row["source_id"],
                    "source_kind": row["source_kind"],
                    "canonical_url": row["canonical_url"],
                    "revision_id": row["revision_id"],
                    "revision_ordinal": ordinal,
                    "published_at": row["published_at"],
                    "updated_at": row["valid_from"],
                    "valid_from": starts[ordinal].isoformat(),
                    "valid_to": valid_to,
                    "status": row["status"],
                    "is_current_revision": is_current,
                    "supersedes_document_id": row["supersedes_document_id"],
                    "superseded_by": following["document_id"] if following else None,
                    "last_verified_at": row["fetched_at"],
                    "default_exposure": row["default_exposure"],
                }
            )
    return sorted(output, key=lambda row: (row["lineage_id"], row["revision_ordinal"]))


def audit_policy_overlay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_lineage.setdefault(row["lineage_id"], []).append(row)
    link_errors = 0
    interval_errors = 0
    for lineage_rows in by_lineage.values():
        ordered = sorted(lineage_rows, key=lambda row: row["revision_ordinal"])
        for ordinal, row in enumerate(ordered):
            previous = ordered[ordinal - 1] if ordinal else None
            following = ordered[ordinal + 1] if ordinal + 1 < len(ordered) else None
            link_errors += row["supersedes_document_id"] != (
                previous["document_id"] if previous else None
            )
            link_errors += row["superseded_by"] != (
                following["document_id"] if following else None
            )
            expected_valid_to = (
                (
                    _iso_date(following["valid_from"], "valid_from")
                    - timedelta(days=1)
                ).isoformat()
                if following
                else None
            )
            interval_errors += row["valid_to"] != expected_valid_to
    statuses = Counter(row["status"] for row in rows)
    gates = {
        "policy_revision_count_51": len(rows) == 51,
        "single_policy_lineage": len(by_lineage) == 1,
        "unique_document_ids": len({row["document_id"] for row in rows})
        == len(rows),
        "current_revision_count_1": sum(row["is_current_revision"] for row in rows)
        == 1,
        "default_exposure_count_1": sum(row["default_exposure"] for row in rows)
        == 1,
        "status_distribution_50_1": statuses
        == {"current": 1, "superseded": 50},
        "link_errors_0": link_errors == 0,
        "interval_errors_0": interval_errors == 0,
        "last_verified_at_present": all(row["last_verified_at"] for row in rows),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "status_counts": dict(sorted(statuses.items())),
        "link_errors": link_errors,
        "interval_errors": interval_errors,
    }


def resolve_policy_revisions(
    rows: list[dict[str, Any]],
    *,
    mode: TemporalMode,
    as_of: str | None = None,
) -> dict[str, Any]:
    if mode not in {"current", "historical", "comparison"}:
        raise RuntimeError(f"Unknown temporal mode: {mode}")
    current = [row for row in rows if row["is_current_revision"]]
    if len(current) != 1:
        raise RuntimeError("Temporal overlay must contain exactly one current revision")
    if mode == "current":
        selected = current[0]
    else:
        if as_of is None:
            raise RuntimeError(f"{mode} mode requires as_of")
        target = _iso_date(as_of, "as_of")
        active = [
            row
            for row in rows
            if _iso_date(row["valid_from"], "valid_from") <= target
            and (
                row["valid_to"] is None
                or target <= _iso_date(row["valid_to"], "valid_to")
            )
        ]
        if len(active) != 1:
            raise RuntimeError(
                f"Expected one policy revision at {target.isoformat()}, got {len(active)}"
            )
        selected = active[0]

    allowed = [selected]
    roles = {selected["document_id"]: "selected_revision"}
    if mode == "comparison" and selected["supersedes_document_id"] is not None:
        previous_by_id = {row["document_id"]: row for row in rows}
        previous = previous_by_id[selected["supersedes_document_id"]]
        allowed.append(previous)
        roles[previous["document_id"]] = "previous_revision"
    return {
        "mode": mode,
        "as_of": as_of,
        "selected_document_id": selected["document_id"],
        "selected_revision_id": selected["revision_id"],
        "selected_valid_from": selected["valid_from"],
        "is_current_revision": selected["is_current_revision"],
        "allowed_document_ids": [row["document_id"] for row in allowed],
        "document_roles": roles,
        "temporal_decision": (
            "allow_current_revision"
            if mode == "current"
            else "allow_as_of_revision"
            if mode == "historical"
            else "allow_revision_pair"
        ),
    }


def search_policy_for_resolution(
    resolution: dict[str, Any],
) -> SearchPolicy:
    return SearchPolicy(
        default_exposure_only=resolution["mode"] == "current",
        allowed_statuses=("current",)
        if resolution["mode"] == "current"
        else ("current", "superseded"),
        include_review_required=False,
        as_of=None,
        source_ids=("dnf_account_policy",),
    )


def restrict_bm25_index(
    index: dict[str, Any], allowed_document_ids: list[str] | tuple[str, ...]
) -> dict[str, Any]:
    allowed = set(allowed_document_ids)
    old_to_new: dict[int, int] = {}
    entries = []
    for entry in index["entries"]:
        if entry["parent_document_id"] not in allowed:
            continue
        new_ordinal = len(entries)
        old_to_new[entry["ordinal"]] = new_ordinal
        entries.append({**entry, "ordinal": new_ordinal})
    postings = {}
    for term, values in index["postings"].items():
        filtered = [
            [old_to_new[ordinal], frequency]
            for ordinal, frequency in values
            if ordinal in old_to_new
        ]
        if filtered:
            postings[term] = filtered
    total_length = sum(entry["document_length"] for entry in entries)
    return {
        **index,
        "document_count": len(entries),
        "average_document_length": total_length / len(entries) if entries else 0.0,
        "entries": entries,
        "postings": postings,
    }


def _audit_resolution_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    historical_errors = 0
    comparison_errors = 0
    ordered = sorted(rows, key=lambda row: row["revision_ordinal"])
    for ordinal, row in enumerate(ordered):
        historical = resolve_policy_revisions(
            rows, mode="historical", as_of=row["valid_from"]
        )
        historical_errors += historical["selected_document_id"] != row["document_id"]
        if ordinal:
            comparison = resolve_policy_revisions(
                rows, mode="comparison", as_of=row["valid_from"]
            )
            comparison_errors += comparison["allowed_document_ids"] != [
                row["document_id"],
                ordered[ordinal - 1]["document_id"],
            ]
    return {
        "historical_revision_cases": len(ordered),
        "historical_resolution_errors": historical_errors,
        "comparison_pair_cases": max(0, len(ordered) - 1),
        "comparison_pair_errors": comparison_errors,
    }


def freeze_temporal_policy(
    root: Path,
    documents_path: Path,
    chunks_path: Path,
    bm25_index_path: Path,
    conflict_packet_path: Path,
    conflict_draft_path: Path,
    builder_source_path: Path,
    search_source_path: Path,
    schema_source_path: Path,
    contract_path: Path,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    documents = read_jsonl(documents_path)
    chunks = read_jsonl(chunks_path)
    conflict_rows = read_jsonl(conflict_packet_path)
    conflict_draft_rows = read_jsonl(conflict_draft_path)
    validate_draft_structure(conflict_rows, conflict_draft_rows)
    index = json.loads(bm25_index_path.read_text(encoding="utf-8"))
    overlay = build_policy_overlay(documents)
    overlay_audit = audit_policy_overlay(overlay)
    if not overlay_audit["gate_pass"]:
        raise RuntimeError(f"Temporal overlay integrity failed: {overlay_audit}")
    resolution_coverage = _audit_resolution_coverage(overlay)
    current_resolution = resolve_policy_revisions(overlay, mode="current")
    current_policy = search_policy_for_resolution(current_resolution)
    current_index = restrict_bm25_index(
        index, current_resolution["allowed_document_ids"]
    )

    question_rows = []
    current_leaks = 0
    superseded_leaks = 0
    empty_results = 0
    origin_ids = {
        row["revision_comparison"]["origin_document_id"] for row in conflict_rows
    }
    origin_leaks = 0
    for row in conflict_rows:
        hits = search_bm25(
            current_index, row["question"], top_k=10, policy=current_policy
        )
        empty_results += not hits
        current_leaks += sum(
            hit["parent_document_id"]
            != current_resolution["selected_document_id"]
            for hit in hits
        )
        superseded_leaks += sum(hit["status"] == "superseded" for hit in hits)
        origin_leaks += sum(hit["parent_document_id"] in origin_ids for hit in hits)
        question_rows.append(
            {
                "question": row["question"],
                "result_count": len(hits),
                "result_document_ids": sorted(
                    {hit["parent_document_id"] for hit in hits}
                ),
                "superseded_result_count": sum(
                    hit["status"] == "superseded" for hit in hits
                ),
            }
        )

    temporal_dir = artifact_root / "data/v3/temporal"
    reports_dir = artifact_root / "reports/v3"
    overlay_bytes = _serialize_jsonl(
        overlay, lambda row: (row["lineage_id"], row["revision_ordinal"])
    )
    overlay_sha = _sha256_bytes(overlay_bytes)
    overlay_path = temporal_dir / f"account_policy_revisions_{overlay_sha}.jsonl"
    write_immutable(overlay_path, overlay_bytes)

    inputs = {
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_index": bm25_index_path,
        "cancelled_revision_conflict_packet": conflict_packet_path,
        "cancelled_revision_conflict_draft": conflict_draft_path,
        "builder_source": builder_source_path,
        "search_filter_source": search_source_path,
        "schema_source": schema_source_path,
        "contract": contract_path,
    }
    current_query_audit = {
        "question_count": len(conflict_rows),
        "empty_result_count": empty_results,
        "non_current_document_leaks": current_leaks,
        "superseded_document_leaks": superseded_leaks,
        "old_claim_origin_leaks": origin_leaks,
        "rows": question_rows,
    }
    cancelled_review_state = {
        "row_count": len(conflict_draft_rows),
        "reviewed_row_count": sum(
            row["review_label"] is not None for row in conflict_draft_rows
        ),
        "remaining_row_count": sum(
            row["review_label"] is None for row in conflict_draft_rows
        ),
        "label_counts": dict(
            sorted(
                Counter(
                    row["review_label"]
                    for row in conflict_draft_rows
                    if row["review_label"] is not None
                ).items()
            )
        ),
        "draft_sha256": file_sha256(conflict_draft_path),
        "preserved_immutable": True,
        "scoring_allowed": False,
    }
    gates = {
        "overlay_integrity": overlay_audit["gate_pass"],
        "historical_resolution_errors_0": resolution_coverage[
            "historical_resolution_errors"
        ]
        == 0,
        "comparison_pair_errors_0": resolution_coverage["comparison_pair_errors"]
        == 0,
        "current_questions_all_return_hits": empty_results == 0,
        "current_question_non_current_leaks_0": current_leaks == 0,
        "current_question_superseded_leaks_0": superseded_leaks == 0,
        "old_claim_origin_leaks_0": origin_leaks == 0,
    }
    decisions = {
        "account_policy_temporal_overlay": "GO" if all(gates.values()) else "NO-GO",
        "current_policy_retrieval_filter": "GO" if all(gates.values()) else "NO-GO",
        "historical_mode": "GO"
        if resolution_coverage["historical_resolution_errors"] == 0
        else "NO-GO",
        "comparison_mode": "GO"
        if resolution_coverage["comparison_pair_errors"] == 0
        else "NO-GO",
        "revision_conflict_human_review": "CANCELLED",
        "generator_entry": "NO-GO",
        "final_benchmark": "NO-GO",
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "built_at": BUILT_AT,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "overlay": {
            "path": _relative(artifact_root, overlay_path),
            "sha256": overlay_sha,
            "row_count": len(overlay),
            "audit": overlay_audit,
        },
        "resolution_coverage": resolution_coverage,
        "current_query_audit": current_query_audit,
        "cancelled_revision_conflict_packet": {
            "path": _relative(root, conflict_packet_path),
            "sha256": file_sha256(conflict_packet_path),
            "row_count": len(conflict_rows),
            "current_qa_eligible": False,
            "human_labeling_required": False,
            "preservation": "revision_comparison_research_only",
            "draft": {
                "path": _relative(root, conflict_draft_path),
                **cancelled_review_state,
            },
        },
        "gates": gates,
        "decisions": decisions,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = temporal_dir / f"account_policy_temporal_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "built_at": BUILT_AT,
        "overlay_sha256": overlay_sha,
        "manifest_sha256": manifest_sha,
        "current_revision": current_resolution,
        "overlay_audit": overlay_audit,
        "resolution_coverage": resolution_coverage,
        "current_query_audit": current_query_audit,
        "cancelled_review_state": cancelled_review_state,
        "gates": gates,
        "decisions": decisions,
        "input_row_counts": {
            "documents": len(documents),
            "chunks": len(chunks),
            "cancelled_revision_conflict_questions": len(conflict_rows),
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"account_policy_temporal_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Account-policy Temporal Policy

## Decision

- temporal overlay: **{decisions['account_policy_temporal_overlay']}**
- current policy retrieval filter: **{decisions['current_policy_retrieval_filter']}**
- historical mode: **{decisions['historical_mode']}**
- comparison mode: **{decisions['comparison_mode']}**
- six-row revision-conflict human review: **CANCELLED**
- Generator / final benchmark: **NO-GO**

## Coverage

- policy revisions: {len(overlay)}
- current revision: `{current_resolution['selected_valid_from']}`
- historical boundary cases: {resolution_coverage['historical_revision_cases']}
- historical resolution errors: {resolution_coverage['historical_resolution_errors']}
- comparison pair cases: {resolution_coverage['comparison_pair_cases']}
- comparison pair errors: {resolution_coverage['comparison_pair_errors']}
- current-mode regression questions: {len(conflict_rows)}
- empty current-mode results: {empty_results}
- superseded/current-policy leaks: {superseded_leaks}
- old claim-origin leaks: {origin_leaks}
- preserved completed labels from cancelled draft: {cancelled_review_state['reviewed_row_count']}
- remaining labels required: 0

The original DocumentV3 and ChunkV3 artifacts remain immutable. The temporal
overlay computes closed validity intervals, current-revision state,
`superseded_by`, and `last_verified_at`. Allowed parent document IDs are applied
before BM25 and dense ranking. Superseded revisions remain available only through
explicit historical or comparison modes.

The cancelled six-row packet is preserved for provenance but is not a current-QA
evaluation set and requires no further human labeling.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"account_policy_temporal_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "overlay_path": str(overlay_path),
        "overlay_sha256": overlay_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "gates": gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build and audit the v3 account-policy temporal overlay"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--bm25-index", type=Path, default=root / DEFAULT_BM25_INDEX)
    parser.add_argument(
        "--conflict-packet", type=Path, default=root / DEFAULT_CONFLICT_PACKET
    )
    parser.add_argument(
        "--conflict-draft", type=Path, default=root / DEFAULT_CONFLICT_DRAFT
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument(
        "--search-source", type=Path, default=root / DEFAULT_SEARCH_SOURCE
    )
    parser.add_argument(
        "--schema-source", type=Path, default=root / DEFAULT_SCHEMA_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = freeze_temporal_policy(
        args.root.resolve(),
        args.documents.resolve(),
        args.chunks.resolve(),
        args.bm25_index.resolve(),
        args.conflict_packet.resolve(),
        args.conflict_draft.resolve(),
        args.builder_source.resolve(),
        args.search_source.resolve(),
        args.schema_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
