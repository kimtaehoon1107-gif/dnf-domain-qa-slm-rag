from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "global-temporal-overlay-v3.2-arm3.0"
OVERLAY_SCHEMA_VERSION = "dnf-global-temporal-overlay-v3.2"
REPORT_SCHEMA_VERSION = "dnf-global-temporal-overlay-report-v3.2"
MANIFEST_SCHEMA_VERSION = "dnf-global-temporal-overlay-manifest-v3.2"
DEFAULT_AS_OF = "2026-07-18"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_POLICY_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_ROUTER_CASES = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/global_temporal_overlay_arm3.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/temporal")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _day(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _window_state(document: dict[str, Any], as_of: date) -> str | None:
    start = _day(document.get("valid_from"))
    end = _day(document.get("valid_to"))
    if start is None and end is None:
        return None
    if start is not None and as_of < start:
        return "upcoming"
    if end is not None and as_of > end:
        return "expired"
    return "active"


def classify_document_temporally(
    document: dict[str, Any],
    *,
    policy_by_document: dict[str, dict[str, Any]],
    review_required_chunk_count: int,
    as_of: date,
) -> dict[str, Any]:
    document_id = document["document_id"]
    policy = policy_by_document.get(document_id)
    if policy is not None:
        current = bool(policy["is_current_revision"])
        return {
            "validity_state": "current_revision" if current else "superseded_revision",
            "validity_reason": "official policy revision lineage and effective-date interval",
            "validity_evidence": ["policy_revision_selector", "valid_from", "revision_lineage"],
            "retrieval_action_current": "allow" if current else "deny",
            "is_current_revision": current,
            "superseded_by": policy["superseded_by"],
            "last_verified_at": policy["last_verified_at"],
            "verified_by": "dnf_account_policy_temporal_builder_v3.1",
            "reverify_after": None,
        }

    source_kind = document["source_kind"]
    status = document["status"]
    window_state = _window_state(document, as_of)
    if source_kind == "preview_patch":
        state, reason, action = "preview", "preview-patch source kind", "deny"
        verified = document["fetched_at"]
        evidence = ["source_kind", "default_exposure"]
    elif status == "superseded":
        state, reason, action = "superseded", "official normalized status", "deny"
        verified = document["fetched_at"]
        evidence = ["status", "default_exposure"]
    elif status == "expired" or window_state == "expired":
        state, reason, action = "expired", "official status or explicit validity window", "deny"
        verified = document["fetched_at"]
        evidence = ["status", "valid_to"]
    elif window_state == "upcoming":
        state, reason, action = "upcoming", "explicit validity window starts after as-of", "deny"
        verified = document["fetched_at"]
        evidence = ["valid_from"]
    elif not document["default_exposure"]:
        state, reason, action = "hidden_or_review_required", "official exposure flag is false", "deny"
        verified = None
        evidence = ["default_exposure"]
    elif window_state == "active":
        state, reason, action = "active_window", "as-of is inside explicit official validity window", "allow"
        verified = document["fetched_at"]
        evidence = ["valid_from", "valid_to", "status"]
    else:
        state = "current_unverified"
        reason = "official document is exposed but has no explicit validity end or revision proof"
        action = "allow_with_warning"
        verified = None
        evidence = ["status", "default_exposure", "snapshot_observed_at"]

    return {
        "validity_state": state,
        "validity_reason": reason,
        "validity_evidence": evidence,
        "retrieval_action_current": action,
        "is_current_revision": None,
        "superseded_by": None,
        "last_verified_at": verified,
        "verified_by": "official_explicit_temporal_metadata" if verified else None,
        "reverify_after": document.get("valid_to") if state == "active_window" else None,
        "review_required_chunk_count": review_required_chunk_count,
    }


def build_global_overlay(
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    policy_rows: list[dict[str, Any]],
    *,
    as_of: str = DEFAULT_AS_OF,
) -> list[dict[str, Any]]:
    target = _day(as_of)
    if target is None:
        raise RuntimeError("as_of is required")
    policy_by_document = {row["document_id"]: row for row in policy_rows}
    review_counts = Counter(
        row["parent_document_id"] for row in chunks if row["review_required"]
    )
    output = []
    for document in documents:
        classification = classify_document_temporally(
            document,
            policy_by_document=policy_by_document,
            review_required_chunk_count=review_counts[document["document_id"]],
            as_of=target,
        )
        output.append(
            {
                "temporal_overlay_schema_version": OVERLAY_SCHEMA_VERSION,
                "document_id": document["document_id"],
                "source_id": document["source_id"],
                "source_kind": document["source_kind"],
                "canonical_url": document["canonical_url"],
                "revision_id": document["revision_id"],
                "published_at": document.get("published_at"),
                "updated_at": document.get("updated_at"),
                "valid_from": document.get("valid_from"),
                "valid_to": document.get("valid_to"),
                "status": document["status"],
                "default_exposure": document["default_exposure"],
                "supersedes_document_id": document.get("supersedes_document_id"),
                "snapshot_observed_at": document["fetched_at"],
                "as_of": as_of,
                **classification,
            }
        )
    return sorted(output, key=lambda row: row["document_id"])


def _evaluate_overlay(
    overlay: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    router_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_document = {row["document_id"]: row for row in overlay}
    chunk_to_document = {row["chunk_id"]: row["parent_document_id"] for row in chunks}
    current_evaluations = {
        row["dev_id"]: row for row in evaluation_rows if row.get("time_scope") == "current"
    }
    denied_gold_groups = []
    for evaluation in current_evaluations.values():
        for group in evaluation.get("evidence_groups", []):
            actions = {
                by_document[document_id]["retrieval_action_current"]
                for document_id in group.get("document_ids", [])
            }
            if actions and actions <= {"deny"}:
                denied_gold_groups.append(
                    {"case_id": evaluation["dev_id"], "group_id": group["group_id"]}
                )
    denied_frozen_citations = []
    for row in router_rows:
        if row["case_id"] not in current_evaluations:
            continue
        for chunk_id in row["arm0"]["cited_chunk_ids"]:
            document_id = chunk_to_document[chunk_id]
            if by_document[document_id]["retrieval_action_current"] == "deny":
                denied_frozen_citations.append(
                    {"case_id": row["case_id"], "chunk_id": chunk_id, "document_id": document_id}
                )
    states = Counter(row["validity_state"] for row in overlay)
    actions = Counter(row["retrieval_action_current"] for row in overlay)
    unverified = [row for row in overlay if row["validity_state"] == "current_unverified"]
    notices = [row for row in overlay if row["source_id"] == "dnf_notice"]
    policy = [row for row in overlay if row["source_id"] == "dnf_account_policy"]
    determinate_noncurrent = [
        row
        for row in overlay
        if row["validity_state"] in {"expired", "superseded", "superseded_revision", "preview", "upcoming", "hidden_or_review_required"}
    ]
    gates = {
        "overlay_covers_all_980_documents": len(overlay) == 980 and len(by_document) == 980,
        "uniform_required_fields_present": all(
            all(
                key in row
                for key in (
                    "validity_state",
                    "validity_reason",
                    "validity_evidence",
                    "verified_by",
                    "reverify_after",
                    "last_verified_at",
                    "retrieval_action_current",
                )
            )
            for row in overlay
        ),
        "determinate_noncurrent_denied": all(
            row["retrieval_action_current"] == "deny" for row in determinate_noncurrent
        ),
        "unverified_last_verified_not_fabricated": all(
            row["last_verified_at"] is None and row["verified_by"] is None
            for row in unverified
        ),
        "old_notices_not_denied_by_age": all(
            row["retrieval_action_current"] == "allow_with_warning" for row in notices
        ),
        "single_current_policy_revision": sum(
            row["validity_state"] == "current_revision" for row in policy
        )
        == 1,
        "current_eval_gold_denials_zero": not denied_gold_groups,
        "frozen_current_citation_denials_zero": not denied_frozen_citations,
    }
    return {
        "state_counts": dict(sorted(states.items())),
        "action_counts": dict(sorted(actions.items())),
        "current_evaluation_question_count": len(current_evaluations),
        "denied_gold_groups": denied_gold_groups,
        "denied_frozen_citations": denied_frozen_citations,
        "unverified_document_count": len(unverified),
        "determinate_noncurrent_document_count": len(determinate_noncurrent),
        "gates": gates,
        "gate_pass": all(gates.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    lines = [
        "# v3.2 Arm 3 — Global temporal overlay A/B",
        "",
        f"Decision: **{report['decision']}**. This is an additive metadata candidate; runtime/canonical was not promoted.",
        "",
        "| Measure | Before | Arm 3 |",
        "|---|---:|---:|",
        f"| Documents with a uniform validity contract | 51 policy revisions | {report['overlay_row_count']} documents |",
        f"| Current-eval gold groups denied | n/a | {len(evaluation['denied_gold_groups'])} |",
        f"| Frozen current citations denied | n/a | {len(evaluation['denied_frozen_citations'])} |",
        f"| Unverified documents with fabricated last_verified_at | n/a | {report['unverified_last_verified_fabrication_count']} |",
        "",
        "## Validity states",
        "",
    ]
    for state, count in evaluation["state_counts"].items():
        lines.append(f"- `{state}`: {count}")
    lines.extend(
        [
            "",
            "`current_unverified` is not treated as recently verified. It remains searchable with a warning so old but still authoritative security notices are not removed merely because of publication age.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and A/B audit the global temporal overlay")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    documents = read_jsonl(root / DEFAULT_DOCUMENTS)
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    policy = read_jsonl(root / DEFAULT_POLICY_OVERLAY)
    evaluations = read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV)
    router = read_jsonl(root / DEFAULT_ROUTER_CASES)
    overlay = build_global_overlay(documents, chunks, policy, as_of=args.as_of)
    evaluation = _evaluate_overlay(overlay, chunks, evaluations, router)
    decision = "GO_ARM3_ADDITIVE_METADATA_CANDIDATE_NOT_PROMOTED" if evaluation["gate_pass"] else "NO_GO"
    unverified_fabrications = sum(
        row["validity_state"] == "current_unverified" and row["last_verified_at"] is not None
        for row in overlay
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": "development_only_not_promoted",
        "as_of": args.as_of,
        "overlay_row_count": len(overlay),
        "baseline_uniform_contract_document_count": len(policy),
        "evaluation": evaluation,
        "unverified_last_verified_fabrication_count": unverified_fabrications,
        "decision": decision,
        "scope": {
            "normalized_documents_changed": False,
            "chunks_changed": False,
            "retrieval_behavior_changed": False,
            "gold_changed": False,
            "training": False,
            "promoted": False,
        },
    }
    output_dir = root / args.output_dir
    overlay_bytes = _serialize_jsonl(overlay, lambda row: row["document_id"])
    overlay_sha = _sha256_bytes(overlay_bytes)
    overlay_path = output_dir / f"global_temporal_overlay_v3.2_{overlay_sha}.jsonl"
    write_immutable(overlay_path, overlay_bytes)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_dir = root / args.report_dir
    report_path = report_dir / f"global_temporal_overlay_arm3_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"global_temporal_overlay_arm3_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {
            "documents": {"path": DEFAULT_DOCUMENTS.as_posix(), "sha256": file_sha256(root / DEFAULT_DOCUMENTS)},
            "chunks": {"path": DEFAULT_CHUNKS.as_posix(), "sha256": file_sha256(root / DEFAULT_CHUNKS)},
            "policy_overlay": {"path": DEFAULT_POLICY_OVERLAY.as_posix(), "sha256": file_sha256(root / DEFAULT_POLICY_OVERLAY)},
            "contract": {"path": DEFAULT_CONTRACT.as_posix(), "sha256": file_sha256(root / DEFAULT_CONTRACT)},
            "builder_source": {"path": Path(__file__).resolve().relative_to(root).as_posix(), "sha256": file_sha256(Path(__file__).resolve())},
        },
        "artifacts": {
            "overlay": {"path": overlay_path.relative_to(root).as_posix(), "sha256": overlay_sha, "row_count": len(overlay)},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "gate": {"pass": evaluation["gate_pass"], "checks": evaluation["gates"], "decision": decision, "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"global_temporal_overlay_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"overlay": overlay_path.relative_to(root).as_posix(), "manifest": manifest_path.relative_to(root).as_posix(), "report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), "evaluation": evaluation, "decision": decision}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
