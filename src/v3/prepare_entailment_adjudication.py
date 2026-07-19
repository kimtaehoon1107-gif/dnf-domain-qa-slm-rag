from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.prepare_entailment_review import (
    REVIEW_FIELDS,
    audit_completed_reviews,
)
from src.v3.review_entailment_app import validate_draft_structure


BUILDER_VERSION = "entailment-natural-adjudication-builder-v3.1.0"
PACKET_SCHEMA_VERSION = "entailment-natural-adjudication-item-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-natural-adjudication-manifest-v3.1"
REPORT_SCHEMA_VERSION = "entailment-natural-adjudication-report-v3.1"

DEFAULT_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_packet_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl"
)
DEFAULT_PRIMARY_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_natural_review_draft_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/prepare_entailment_adjudication.py")
DEFAULT_REVIEW_CONTRACT = Path("docs/v3/entailment_adjudication.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _empty_review_fields(row: dict[str, Any]) -> None:
    for field in REVIEW_FIELDS:
        row[field] = None


def review_text_corruption_fields(row: dict[str, Any]) -> list[str]:
    corrupted = []
    for field in ("review_rationale", "decisive_excerpt"):
        value = row.get(field)
        if isinstance(value, str) and value.count("?") >= 5:
            corrupted.append(field)
    return corrupted


def adjudication_reasons(row: dict[str, Any]) -> list[str]:
    reasons = []
    if row["needs_adjudication"] is True:
        reasons.append("primary_needs_adjudication")
    if review_text_corruption_fields(row):
        reasons.append("primary_review_text_corrupted")
    return reasons


def build_adjudication_packet(
    primary_rows: list[dict[str, Any]], primary_reviews_sha256: str
) -> list[dict[str, Any]]:
    pending = sorted(
        (row for row in primary_rows if adjudication_reasons(row)),
        key=lambda row: row["item_id"],
    )
    packet = []
    for ordinal, primary in enumerate(pending, 1):
        row = copy.deepcopy(primary)
        primary_item_id = primary["item_id"]
        primary_review = {
            "label": primary["review_label"],
            "reviewer_id": primary["reviewer_id"],
            "reviewed_at": primary["reviewed_at"],
            "decisive_excerpt": primary["decisive_excerpt"],
            "rationale": primary["review_rationale"],
        }
        identity = _canonical_json_bytes(
            {
                "primary_item_id": primary_item_id,
                "primary_reviews_sha256": primary_reviews_sha256,
                "primary_review": primary_review,
                "adjudication_reasons": adjudication_reasons(primary),
            }
        )
        row.update(
            {
                "review_item_schema_version": PACKET_SCHEMA_VERSION,
                "item_id": f"entailment_adjudication_sha256_{_sha256_bytes(identity)}",
                "item_ordinal": ordinal,
                "adjudication_of_item_id": primary_item_id,
                "primary_reviews_sha256": primary_reviews_sha256,
                "primary_review": primary_review,
                "adjudication_reasons": adjudication_reasons(primary),
            }
        )
        _empty_review_fields(row)
        packet.append(row)
    return packet


def audit_adjudication_reviews(
    packet_rows: list[dict[str, Any]], reviewed_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    audit = audit_completed_reviews(packet_rows, reviewed_rows)
    gates = {
        "row_count_matches_packet": audit["gates"]["row_count_matches_packet"],
        "validation_errors_0": audit["gates"]["validation_errors_0"],
        "adjudication_pending_0": audit["gates"]["adjudication_pending_0"],
        "all_rows_reviewed": sum(audit["label_counts"].values()) == len(packet_rows),
    }
    return {
        "gates": gates,
        "ready_for_merge": all(gates.values()),
        "label_counts": audit["label_counts"],
        "adjudication_pending_count": audit["adjudication_pending_count"],
        "errors": audit["errors"],
    }


def merge_adjudicated_reviews(
    primary_rows: list[dict[str, Any]],
    adjudication_packet: list[dict[str, Any]],
    adjudicated_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    validate_draft_structure(adjudication_packet, adjudicated_rows)
    audit = audit_adjudication_reviews(adjudication_packet, adjudicated_rows)
    if not audit["ready_for_merge"]:
        raise RuntimeError(f"Adjudication is not ready for merge: {audit}")

    replacements = {
        row["adjudication_of_item_id"]: row for row in adjudicated_rows
    }
    expected = {
        row["item_id"] for row in primary_rows if adjudication_reasons(row)
    }
    if set(replacements) != expected:
        raise RuntimeError("Adjudication rows do not match primary pending item IDs")

    merged = copy.deepcopy(primary_rows)
    for row in merged:
        replacement = replacements.get(row["item_id"])
        if replacement is None:
            continue
        for field in REVIEW_FIELDS:
            row[field] = replacement[field]
        row["needs_adjudication"] = False
    return merged


def prepare_adjudication(
    root: Path,
    packet_path: Path,
    primary_draft_path: Path,
    builder_source_path: Path,
    review_contract_path: Path,
) -> dict[str, Any]:
    packet_rows = read_jsonl(packet_path)
    primary_rows = read_jsonl(primary_draft_path)
    validate_draft_structure(packet_rows, primary_rows)
    primary_audit = audit_completed_reviews(packet_rows, primary_rows)
    if not primary_audit["primary_review_complete"]:
        raise RuntimeError(f"Primary review is incomplete: {primary_audit}")
    if not any(adjudication_reasons(row) for row in primary_rows):
        raise RuntimeError("Primary review has no pending adjudication or repair rows")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"

    primary_bytes = _serialize_jsonl(primary_rows, lambda row: row["item_ordinal"])
    primary_sha = _sha256_bytes(primary_bytes)
    primary_path = evaluation_dir / f"entailment_natural_primary_reviews_{primary_sha}.jsonl"
    write_immutable(primary_path, primary_bytes)

    adjudication_rows = build_adjudication_packet(primary_rows, primary_sha)
    adjudication_bytes = _serialize_jsonl(
        adjudication_rows, lambda row: row["item_ordinal"]
    )
    adjudication_sha = _sha256_bytes(adjudication_bytes)
    adjudication_path = (
        evaluation_dir
        / f"entailment_natural_adjudication_packet_{adjudication_sha}.jsonl"
    )
    write_immutable(adjudication_path, adjudication_bytes)
    adjudication_draft_path = (
        root
        / "outputs/v3/annotation"
        / f"entailment_natural_adjudication_draft_{adjudication_sha}.jsonl"
    )

    inputs = {
        "primary_packet": packet_path,
        "primary_draft": primary_draft_path,
        "builder_source": builder_source_path,
        "review_contract": review_contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "primary_review_checkpoint": {
            "path": _relative(root, primary_path),
            "sha256": primary_sha,
            "row_count": len(primary_rows),
            "completion_audit": primary_audit,
        },
        "adjudication_packet": {
            "path": _relative(root, adjudication_path),
            "sha256": adjudication_sha,
            "row_count": len(adjudication_rows),
            "source_item_ids": sorted(
                row["adjudication_of_item_id"] for row in adjudication_rows
            ),
            "reason_counts": {
                reason: sum(
                    reason in row["adjudication_reasons"] for row in adjudication_rows
                )
                for reason in (
                    "primary_needs_adjudication",
                    "primary_review_text_corrupted",
                )
            },
        },
        "runtime": {
            "draft_path": _relative(root, adjudication_draft_path),
            "draft_is_mutable": True,
            "primary_draft_is_not_modified": True,
            "model_predictions_loaded": False,
            "sampling_ledger_loaded": False,
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "scoring_allowed_before_merge": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        evaluation_dir
        / f"entailment_natural_adjudication_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "decision": {
            "primary_review": "GO",
            "adjudication": "PENDING",
            "natural_verifier_evaluation": "NO-GO",
            "generator_entry": "NO-GO",
        },
        "primary_label_counts": primary_audit["label_counts"],
        "adjudication_count": len(adjudication_rows),
        "review_text_corruption_count": sum(
            bool(review_text_corruption_fields(row)) for row in primary_rows
        ),
        "primary_reviews_sha256": primary_sha,
        "adjudication_packet_sha256": adjudication_sha,
        "adjudication_manifest_sha256": manifest_sha,
        "next_command": (
            "python src/v3/review_entailment_app.py "
            f"--packet {_relative(root, adjudication_path)} "
            f"--draft {_relative(root, adjudication_draft_path)}"
        ),
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_adjudication_setup_{report_sha}.json"
    write_immutable(report_path, report_bytes)

    markdown = f"""# DNF RAG v3 Entailment Adjudication Setup

## Decision

- Primary review: **GO** ({len(primary_rows)}/{len(primary_rows)})
- Pending adjudication or text repair: **{len(adjudication_rows)}**
- Natural Verifier evaluation: **NO-GO**
- Generator entry: **NO-GO**

The completed primary draft was frozen without modification. Rows explicitly marked `needs_adjudication=true` and rows whose saved rationale or excerpt contains clear question-mark encoding corruption were copied into the separate reviewer packet. The packet contains the primary decision for context but starts with empty adjudication review fields. No model prediction or sampling stratum is loaded.

Run:

`{report['next_command']}`
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_adjudication_setup_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    return {
        "primary_reviews_path": str(primary_path),
        "primary_reviews_sha256": primary_sha,
        "adjudication_packet_path": str(adjudication_path),
        "adjudication_packet_sha256": adjudication_sha,
        "adjudication_draft_path": str(adjudication_draft_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "primary_audit": primary_audit,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Prepare v3 natural entailment adjudication")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--packet", type=Path, default=root / DEFAULT_PACKET)
    parser.add_argument(
        "--primary-draft", type=Path, default=root / DEFAULT_PRIMARY_DRAFT
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument(
        "--review-contract", type=Path, default=root / DEFAULT_REVIEW_CONTRACT
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = prepare_adjudication(
        args.root.resolve(),
        args.packet.resolve(),
        args.primary_draft.resolve(),
        args.builder_source.resolve(),
        args.review_contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
