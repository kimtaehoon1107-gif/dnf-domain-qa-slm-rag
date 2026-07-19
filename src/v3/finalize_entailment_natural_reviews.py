from __future__ import annotations

import argparse
import copy
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
from src.v3.prepare_entailment_adjudication import (
    audit_adjudication_reviews,
    review_text_corruption_fields,
)
from src.v3.prepare_entailment_review import LABELS, REVIEW_FIELDS
from src.v3.review_entailment_app import validate_draft_structure


FINALIZER_VERSION = "entailment-natural-review-finalizer-v3.1.1"
RESOLVED_SCHEMA_VERSION = "entailment-natural-resolved-review-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-natural-resolved-manifest-v3.1"
REPORT_SCHEMA_VERSION = "entailment-natural-resolved-report-v3.1"

DEFAULT_PRIMARY = Path(
    "data/v3/evaluation/"
    "entailment_natural_primary_reviews_3ddc3f2b1dd80231d0fd820e82991ed9fecd4980b2fe55707bc9e2d67f3b0222.jsonl"
)
DEFAULT_ADJUDICATION = Path(
    "data/v3/evaluation/"
    "entailment_natural_adjudication_reviews_860774601c888e8ea6df72ac221abdadc3dd8918d8391a6cf9e3a0bb8ed9262d.jsonl"
)
DEFAULT_REPAIR_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_claim_repair_packet_4ab7ded1cc83ea7c1ffa658874ae2f5f2e6b642f321988dc73f789e018ed1a2b.jsonl"
)
DEFAULT_REPAIR_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_claim_repair_draft_4ab7ded1cc83ea7c1ffa658874ae2f5f2e6b642f321988dc73f789e018ed1a2b.jsonl"
)
DEFAULT_FOLLOWUP_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_claim_repair_followup_packet_6968e3f619ab1124fe1575975d7a9c935215adae96d2d553ec0d4a58f9cb51bf.jsonl"
)
DEFAULT_FOLLOWUP_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_claim_repair_followup_draft_6968e3f619ab1124fe1575975d7a9c935215adae96d2d553ec0d4a58f9cb51bf.jsonl"
)
DEFAULT_SAMPLING_LEDGER = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)
DEFAULT_CORRECTIONS = Path(
    "data/v3/evaluation/"
    "entailment_claim_corrections_a019f22ec3f2fbb8ace3637bbd961a6eace23c5899dbc4e1b76211982d15aad9.jsonl"
)
DEFAULT_ISSUES = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_issues_9ad7c4e8d4d220d40e58b2aff2f9a00f9bcce0b9d72b9094f6b11c6acbf4ad31.jsonl"
)
DEFAULT_FINALIZER_SOURCE = Path("src/v3/finalize_entailment_natural_reviews.py")
DEFAULT_CONTRACT = Path("docs/v3/entailment_claim_repair.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def audit_repair_reviews(
    packet_rows: list[dict[str, Any]], reviewed_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    validate_draft_structure(packet_rows, reviewed_rows)
    audit = audit_adjudication_reviews(packet_rows, reviewed_rows)
    corruption = [
        {"item_id": row["item_id"], "fields": review_text_corruption_fields(row)}
        for row in reviewed_rows
        if review_text_corruption_fields(row)
    ]
    gates = {
        **audit["gates"],
        "text_corruption_0": not corruption,
    }
    return {
        "gates": gates,
        "ready_for_merge": all(gates.values()),
        "label_counts": audit["label_counts"],
        "errors": audit["errors"],
        "text_corruption": corruption,
    }


def audit_claim_repair_coverage(
    sampling_rows: list[dict[str, Any]],
    correction_rows: list[dict[str, Any]],
    repair_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    corrected_dev_ids = {row["dev_id"] for row in correction_rows}
    if len(corrected_dev_ids) != len(correction_rows):
        raise RuntimeError("Duplicate claim correction dev_id")
    expected_primary_ids = {
        row["item_id"]
        for row in sampling_rows
        if row["dev_id"] in corrected_dev_ids
    }
    actual_primary_ids = {row["repair_of_primary_item_id"] for row in repair_rows}
    if len(actual_primary_ids) != len(repair_rows):
        raise RuntimeError("Duplicate claim-repair primary link")
    missing = sorted(expected_primary_ids - actual_primary_ids)
    unexpected = sorted(actual_primary_ids - expected_primary_ids)
    return {
        "corrected_dev_count": len(corrected_dev_ids),
        "expected_relationship_count": len(expected_primary_ids),
        "reviewed_relationship_count": len(actual_primary_ids),
        "missing_primary_item_ids": missing,
        "unexpected_primary_item_ids": unexpected,
        "complete": not missing and not unexpected,
    }
def build_resolved_reviews(
    primary_rows: list[dict[str, Any]],
    adjudication_rows: list[dict[str, Any]],
    repair_rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
    sampling_rows: list[dict[str, Any]],
    correction_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    primary_by_id = {row["item_id"]: row for row in primary_rows}
    if len(primary_by_id) != len(primary_rows):
        raise RuntimeError("Duplicate primary item_id")
    adjudication_by_primary = {
        row["adjudication_of_item_id"]: row for row in adjudication_rows
    }
    repair_by_primary = {row["repair_of_primary_item_id"]: row for row in repair_rows}
    if len(adjudication_by_primary) != len(adjudication_rows):
        raise RuntimeError("Duplicate adjudication primary link")
    if len(repair_by_primary) != len(repair_rows):
        raise RuntimeError("Duplicate claim-repair primary link")
    if not set(adjudication_by_primary).issubset(primary_by_id):
        raise RuntimeError("Adjudication references unknown primary rows")
    if not set(repair_by_primary).issubset(primary_by_id):
        raise RuntimeError("Claim repair references unknown primary rows")

    claim_issue_ids = {
        row["primary_item_id"]
        for row in issue_rows
        if "claim_error" in row["issue_types"]
    }
    evidence_issue_ids = {
        row["primary_item_id"]
        for row in issue_rows
        if "evidence_error" in row["issue_types"]
    }
    unresolved_issue_ids = {
        row["primary_item_id"]
        for row in issue_rows
        if "unresolved_adjudication" in row["issue_types"]
    }
    if not claim_issue_ids.issubset(repair_by_primary):
        raise RuntimeError("Every claim issue must have a repaired relationship")
    coverage = audit_claim_repair_coverage(
        sampling_rows, correction_rows, repair_rows
    )
    if not coverage["complete"]:
        raise RuntimeError(f"Claim repair relationship coverage failed: {coverage}")
    if unresolved_issue_ids:
        raise RuntimeError("Unresolved adjudication issues remain")

    output = []
    for ordinal, primary in enumerate(
        sorted(primary_rows, key=lambda row: row["item_ordinal"]), 1
    ):
        row = copy.deepcopy(primary)
        adjudication = adjudication_by_primary.get(primary["item_id"])
        repair = repair_by_primary.get(primary["item_id"])
        if adjudication is not None:
            for field in REVIEW_FIELDS:
                row[field] = adjudication[field]
        if repair is not None:
            row["claim_text"] = repair["claim_text"]
            for field in REVIEW_FIELDS:
                row[field] = repair[field]
        row["needs_adjudication"] = False

        exclusions = []
        if primary["item_id"] in evidence_issue_ids:
            exclusions.append("human_confirmed_evidence_provenance_error")
        lineage = {
            "primary_item_id": primary["item_id"],
            "adjudication_item_id": adjudication["item_id"] if adjudication else None,
            "claim_repair_item_id": repair["item_id"] if repair else None,
            "claim_correction_id": (
                repair["claim_repair"]["claim_correction_id"] if repair else None
            ),
        }
        identity = {
            "lineage": lineage,
            "claim_text": row["claim_text"],
            "evidence_chunk_id": row["evidence_chunk_id"],
            "review_label": row["review_label"],
            "reviewer_id": row["reviewer_id"],
            "reviewed_at": row["reviewed_at"],
        }
        row.update(
            {
                "review_item_schema_version": RESOLVED_SCHEMA_VERSION,
                "item_id": f"entailment_resolved_sha256_{_sha256_bytes(_canonical_json_bytes(identity))}",
                "item_ordinal": ordinal,
                "review_lineage": lineage,
                "claim_revision_status": "corrected" if repair else "original",
                "natural_evaluation_eligible": not exclusions,
                "evaluation_exclusion_reasons": exclusions,
            }
        )
        output.append(row)
    return output


def audit_resolved_reviews(
    rows: list[dict[str, Any]], expected_claim_repair_count: int = 5
) -> dict[str, Any]:
    labels = Counter(row.get("review_label") for row in rows)
    invalid_labels = sorted(label for label in labels if label not in LABELS)
    corruption = [
        {"item_id": row["item_id"], "fields": review_text_corruption_fields(row)}
        for row in rows
        if review_text_corruption_fields(row)
    ]
    eligible = [row for row in rows if row["natural_evaluation_eligible"]]
    eligible_labels = Counter(row["review_label"] for row in eligible)
    gates = {
        "row_count_40": len(rows) == 40,
        "unique_item_ids": len({row["item_id"] for row in rows}) == len(rows),
        "valid_labels": not invalid_labels,
        "adjudication_pending_0": not any(row["needs_adjudication"] for row in rows),
        "text_corruption_0": not corruption,
        f"claim_repair_count_{expected_claim_repair_count}": sum(
            row["claim_revision_status"] == "corrected" for row in rows
        )
        == expected_claim_repair_count,
        "evidence_exclusion_count_2": sum(
            not row["natural_evaluation_eligible"] for row in rows
        )
        == 2,
        "all_three_labels_present": set(eligible_labels) == set(LABELS),
    }
    integrity_gates = {k: v for k, v in gates.items() if k != "all_three_labels_present"}
    return {
        "gates": gates,
        "integrity_ready": all(integrity_gates.values()),
        "ready_for_three_class_scoring": all(gates.values()),
        "row_count": len(rows),
        "label_counts": dict(sorted(labels.items())),
        "eligible_row_count": len(eligible),
        "eligible_label_counts": dict(sorted(eligible_labels.items())),
        "excluded_row_count": len(rows) - len(eligible),
        "invalid_labels": invalid_labels,
        "text_corruption": corruption,
    }


def finalize_natural_reviews(
    root: Path,
    primary_path: Path,
    adjudication_path: Path,
    repair_packet_path: Path,
    repair_draft_path: Path,
    followup_packet_path: Path,
    followup_draft_path: Path,
    issues_path: Path,
    sampling_ledger_path: Path,
    corrections_path: Path,
    finalizer_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    primary_rows = read_jsonl(primary_path)
    adjudication_rows = read_jsonl(adjudication_path)
    repair_packet = read_jsonl(repair_packet_path)
    repair_rows = read_jsonl(repair_draft_path)
    followup_packet = read_jsonl(followup_packet_path)
    followup_rows = read_jsonl(followup_draft_path)
    issue_rows = read_jsonl(issues_path)
    sampling_rows = read_jsonl(sampling_ledger_path)
    correction_rows = read_jsonl(corrections_path)
    repair_audit = audit_repair_reviews(repair_packet, repair_rows)
    if not repair_audit["ready_for_merge"]:
        raise RuntimeError(f"Claim repair review is not merge-ready: {repair_audit}")
    followup_audit = audit_repair_reviews(followup_packet, followup_rows)
    if not followup_audit["ready_for_merge"]:
        raise RuntimeError(
            f"Claim repair follow-up is not merge-ready: {followup_audit}"
        )
    combined_repair_rows = repair_rows + followup_rows
    coverage_audit = audit_claim_repair_coverage(
        sampling_rows, correction_rows, combined_repair_rows
    )
    if not coverage_audit["complete"]:
        raise RuntimeError(f"Claim repair relationship coverage failed: {coverage_audit}")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    followup_bytes = _serialize_jsonl(followup_rows, lambda row: row["item_ordinal"])
    followup_sha = _sha256_bytes(followup_bytes)
    frozen_followup_path = (
        evaluation_dir
        / f"entailment_claim_repair_followup_reviews_{followup_sha}.jsonl"
    )
    write_immutable(frozen_followup_path, followup_bytes)
    combined_repair_bytes = _serialize_jsonl(
        combined_repair_rows, lambda row: row["repair_of_primary_item_id"]
    )
    combined_repair_sha = _sha256_bytes(combined_repair_bytes)
    combined_repair_path = (
        evaluation_dir
        / f"entailment_claim_repair_combined_reviews_{combined_repair_sha}.jsonl"
    )
    write_immutable(combined_repair_path, combined_repair_bytes)

    resolved_rows = build_resolved_reviews(
        primary_rows,
        adjudication_rows,
        combined_repair_rows,
        issue_rows,
        sampling_rows,
        correction_rows,
    )
    resolved_audit = audit_resolved_reviews(
        resolved_rows, coverage_audit["expected_relationship_count"]
    )
    if not resolved_audit["integrity_ready"]:
        raise RuntimeError(f"Resolved review integrity failed: {resolved_audit}")
    resolved_bytes = _serialize_jsonl(resolved_rows, lambda row: row["item_ordinal"])
    resolved_sha = _sha256_bytes(resolved_bytes)
    resolved_path = evaluation_dir / f"entailment_natural_resolved_reviews_{resolved_sha}.jsonl"
    write_immutable(resolved_path, resolved_bytes)

    eligible_rows = [row for row in resolved_rows if row["natural_evaluation_eligible"]]
    eligible_bytes = _serialize_jsonl(eligible_rows, lambda row: row["item_ordinal"])
    eligible_sha = _sha256_bytes(eligible_bytes)
    eligible_path = evaluation_dir / f"entailment_natural_evaluation_view_{eligible_sha}.jsonl"
    write_immutable(eligible_path, eligible_bytes)

    inputs = {
        "primary_reviews": primary_path,
        "adjudication_reviews": adjudication_path,
        "claim_repair_packet": repair_packet_path,
        "claim_repair_draft": repair_draft_path,
        "claim_repair_followup_packet": followup_packet_path,
        "claim_repair_followup_draft": followup_draft_path,
        "issue_ledger": issues_path,
        "sampling_ledger": sampling_ledger_path,
        "claim_corrections": corrections_path,
        "finalizer_source": finalizer_source_path,
        "claim_repair_contract": contract_path,
    }
    decisions = {
        "claim_repair_human_review": "GO",
        "resolved_review_integrity": "GO",
        "evidence_error_exclusion": "GO",
        "three_class_natural_verifier_evaluation": (
            "GO" if resolved_audit["ready_for_three_class_scoring"] else "NO-GO"
        ),
        "contradiction_supplement": (
            "NOT-REQUIRED"
            if resolved_audit["ready_for_three_class_scoring"]
            else "REQUIRED"
        ),
        "generator_entry": "NO-GO",
        "final_benchmark": "NO-GO",
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "claim_repair_reviews": {
            "initial": {
                "path": _relative(root, repair_draft_path),
                "sha256": file_sha256(repair_draft_path),
                "row_count": len(repair_rows),
                "audit": repair_audit,
            },
            "followup": {
                "path": _relative(root, frozen_followup_path),
                "sha256": followup_sha,
                "row_count": len(followup_rows),
                "audit": followup_audit,
            },
            "combined": {
                "path": _relative(root, combined_repair_path),
                "sha256": combined_repair_sha,
                "row_count": len(combined_repair_rows),
                "coverage_audit": coverage_audit,
            },
        },
        "resolved_reviews": {
            "path": _relative(root, resolved_path),
            "sha256": resolved_sha,
            "row_count": len(resolved_rows),
            "audit": resolved_audit,
        },
        "natural_evaluation_view": {
            "path": _relative(root, eligible_path),
            "sha256": eligible_sha,
            "row_count": len(eligible_rows),
        },
        "decisions": decisions,
        "supersedes": {
            "manifest_sha256": "458b2877e66266c2a95ea8607241820a7f7e3bcbb7d02ec8c930ecfbb473e2d6",
            "reason": "predecessor covered 4 of 5 corrected-claim relationships",
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "natural_distribution_prevalence_claim": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"entailment_natural_resolved_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "decisions": decisions,
        "claim_repair_followup_reviews_sha256": followup_sha,
        "claim_repair_combined_reviews_sha256": combined_repair_sha,
        "claim_repair_coverage_audit": coverage_audit,
        "resolved_reviews_sha256": resolved_sha,
        "natural_evaluation_view_sha256": eligible_sha,
        "manifest_sha256": manifest_sha,
        "resolved_audit": resolved_audit,
        "next_required_cycle": "human_reviewed_natural_contradiction_supplement",
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_natural_resolved_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Resolved Natural Entailment Reviews

## Decision

- Claim repair human review: **GO**
- Resolved 40-row integrity: **GO**
- Evidence-error exclusions: **GO**
- Three-class natural Verifier evaluation: **{decisions['three_class_natural_verifier_evaluation']}**
- Contradiction supplement: **{decisions['contradiction_supplement']}**
- Generator / final benchmark: **NO-GO**

## Final review view

- resolved rows: {resolved_audit['row_count']}
- evaluation-eligible rows: {resolved_audit['eligible_row_count']}
- excluded evidence-provenance rows: {resolved_audit['excluded_row_count']}
- labels before exclusion: {json.dumps(resolved_audit['label_counts'], ensure_ascii=False)}
- eligible labels: {json.dumps(resolved_audit['eligible_label_counts'], ensure_ascii=False)}

Five claim relationships now use content-addressed corrected revisions, covering every sampled relationship for the two corrected dev claims. Two human-confirmed parent/body provenance errors remain preserved in the resolved artifact but are excluded from the evaluation view. No contradiction is present, so three-class scoring remains blocked and a separate naturally mined contradiction supplement requires blind human review.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_natural_resolved_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "claim_repair_followup_reviews_path": str(frozen_followup_path),
        "claim_repair_followup_reviews_sha256": followup_sha,
        "claim_repair_combined_reviews_path": str(combined_repair_path),
        "claim_repair_combined_reviews_sha256": combined_repair_sha,
        "resolved_reviews_path": str(resolved_path),
        "resolved_reviews_sha256": resolved_sha,
        "natural_evaluation_view_path": str(eligible_path),
        "natural_evaluation_view_sha256": eligible_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "resolved_audit": resolved_audit,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Finalize resolved v3 natural reviews")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--primary", type=Path, default=root / DEFAULT_PRIMARY)
    parser.add_argument(
        "--adjudication", type=Path, default=root / DEFAULT_ADJUDICATION
    )
    parser.add_argument(
        "--repair-packet", type=Path, default=root / DEFAULT_REPAIR_PACKET
    )
    parser.add_argument(
        "--repair-draft", type=Path, default=root / DEFAULT_REPAIR_DRAFT
    )
    parser.add_argument(
        "--followup-packet", type=Path, default=root / DEFAULT_FOLLOWUP_PACKET
    )
    parser.add_argument(
        "--followup-draft", type=Path, default=root / DEFAULT_FOLLOWUP_DRAFT
    )
    parser.add_argument("--issues", type=Path, default=root / DEFAULT_ISSUES)
    parser.add_argument(
        "--sampling-ledger", type=Path, default=root / DEFAULT_SAMPLING_LEDGER
    )
    parser.add_argument(
        "--corrections", type=Path, default=root / DEFAULT_CORRECTIONS
    )
    parser.add_argument(
        "--finalizer-source", type=Path, default=root / DEFAULT_FINALIZER_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = finalize_natural_reviews(
        args.root.resolve(),
        args.primary.resolve(),
        args.adjudication.resolve(),
        args.repair_packet.resolve(),
        args.repair_draft.resolve(),
        args.followup_packet.resolve(),
        args.followup_draft.resolve(),
        args.issues.resolve(),
        args.sampling_ledger.resolve(),
        args.corrections.resolve(),
        args.finalizer_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
