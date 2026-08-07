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
from src.v3.prepare_entailment_review import REVIEW_FIELDS


BUILDER_VERSION = "entailment-claim-repair-followup-builder-v3.1.0"
PACKET_SCHEMA_VERSION = "entailment-natural-claim-repair-followup-item-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-claim-repair-followup-manifest-v3.1"
REPORT_SCHEMA_VERSION = "entailment-claim-repair-followup-report-v3.1"

DEFAULT_PRIMARY = Path(
    "data/v3/evaluation/"
    "entailment_natural_primary_reviews_3ddc3f2b1dd80231d0fd820e82991ed9fecd4980b2fe55707bc9e2d67f3b0222.jsonl"
)
DEFAULT_SAMPLING_LEDGER = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)
DEFAULT_CORRECTIONS = Path(
    "data/v3/evaluation/"
    "entailment_claim_corrections_a019f22ec3f2fbb8ace3637bbd961a6eace23c5899dbc4e1b76211982d15aad9.jsonl"
)
DEFAULT_PRIOR_REPAIRS = Path(
    "data/v3/evaluation/"
    "entailment_claim_repair_reviews_b36c096b6e8d7608971328dc28da02c083a5be3a7284ac8f646f5c0be4160abe.jsonl"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/prepare_entailment_claim_repair_followup.py")
DEFAULT_CONTRACT = Path("docs/v3/entailment_claim_repair.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def find_missing_repair_relationships(
    primary_rows: list[dict[str, Any]],
    sampling_rows: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    prior_repairs: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    primary_by_id = {row["item_id"]: row for row in primary_rows}
    correction_by_dev = {row["dev_id"]: row for row in corrections}
    repaired_primary_ids = {row["repair_of_primary_item_id"] for row in prior_repairs}
    missing = []
    for provenance in sampling_rows:
        correction = correction_by_dev.get(provenance["dev_id"])
        if correction is None or provenance["item_id"] in repaired_primary_ids:
            continue
        primary = primary_by_id.get(provenance["item_id"])
        if primary is None:
            raise RuntimeError(f"Sampling ledger references unknown primary row: {provenance['item_id']}")
        missing.append((primary, correction, provenance["stratum"]))
    return sorted(missing, key=lambda item: item[0]["item_id"])


def build_followup_packet(
    missing: list[tuple[dict[str, Any], dict[str, Any], str]]
) -> list[dict[str, Any]]:
    packet = []
    for ordinal, (primary, correction, stratum) in enumerate(missing, 1):
        row = copy.deepcopy(primary)
        identity = {
            "repair_of_primary_item_id": primary["item_id"],
            "claim_correction_id": correction["claim_correction_id"],
            "evidence_chunk_id": primary["evidence_chunk_id"],
        }
        row.update(
            {
                "review_item_schema_version": PACKET_SCHEMA_VERSION,
                "item_id": f"entailment_claim_repair_followup_sha256_{_sha256_bytes(_canonical_json_bytes(identity))}",
                "item_ordinal": ordinal,
                "claim_text": correction["proposed_claim_text"],
                "repair_of_primary_item_id": primary["item_id"],
                "claim_repair": {
                    "claim_correction_id": correction["claim_correction_id"],
                    "original_claim_text": correction["original_claim_text"],
                    "proposed_claim_text": correction["proposed_claim_text"],
                    "derivation": correction["derivation"],
                    "prior_primary_label": primary["review_label"],
                    "prior_human_rationale": primary["review_rationale"],
                    "sampling_stratum": stratum,
                    "coverage_reason": "same_dev_id_relationship_missing_from_initial_repair_packet",
                },
            }
        )
        for field in REVIEW_FIELDS:
            row[field] = None
        packet.append(row)
    return packet


def prepare_followup(
    root: Path,
    primary_path: Path,
    sampling_ledger_path: Path,
    corrections_path: Path,
    prior_repairs_path: Path,
    builder_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    primary_rows = read_jsonl(primary_path)
    sampling_rows = read_jsonl(sampling_ledger_path)
    corrections = read_jsonl(corrections_path)
    prior_repairs = read_jsonl(prior_repairs_path)
    missing = find_missing_repair_relationships(
        primary_rows, sampling_rows, corrections, prior_repairs
    )
    if len(missing) != 1:
        raise RuntimeError(f"Expected exactly one missing repair relationship, got {len(missing)}")
    packet_rows = build_followup_packet(missing)

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    packet_bytes = _serialize_jsonl(packet_rows, lambda row: row["item_ordinal"])
    packet_sha = _sha256_bytes(packet_bytes)
    packet_path = evaluation_dir / f"entailment_claim_repair_followup_packet_{packet_sha}.jsonl"
    write_immutable(packet_path, packet_bytes)
    draft_path = (
        root
        / "outputs/v3/annotation"
        / f"entailment_claim_repair_followup_draft_{packet_sha}.jsonl"
    )

    inputs = {
        "primary_reviews": primary_path,
        "sampling_ledger": sampling_ledger_path,
        "claim_corrections": corrections_path,
        "prior_claim_repair_reviews": prior_repairs_path,
        "builder_source": builder_source_path,
        "claim_repair_contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "coverage_audit": {
            "corrected_dev_count": len(corrections),
            "prior_repaired_relationship_count": len(prior_repairs),
            "missing_relationship_count": len(missing),
            "complete_after_followup": True,
        },
        "followup_packet": {
            "path": _relative(root, packet_path),
            "sha256": packet_sha,
            "row_count": len(packet_rows),
            "draft_path": _relative(root, draft_path),
        },
        "decisions": {
            "initial_claim_repair_coverage": "NO-GO",
            "followup_packet_integrity": "GO",
            "resolved_review_promotion": "PENDING",
            "contradiction_supplement": "DEFERRED",
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"entailment_claim_repair_followup_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    next_command = (
        "python src/v3/review_entailment_app.py "
        f"--packet {_relative(root, packet_path)} "
        f"--draft {_relative(root, draft_path)}"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "decisions": manifest["decisions"],
        "missing_relationship_count": len(missing),
        "packet_sha256": packet_sha,
        "manifest_sha256": manifest_sha,
        "next_command": next_command,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_claim_repair_followup_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Claim Repair Coverage Follow-up

## Decision

- Initial claim-repair relationship coverage: **NO-GO**
- Missing same-dev relationship: **1**
- Follow-up packet integrity: **GO**
- Resolved review promotion: **PENDING**

The four completed claim-repair reviews are preserved. One additional hard-candidate relationship shares the corrected external-payment `dev_id` but was not included in the initial repair packet. Only this relationship requires a follow-up human label.

Run:

`{next_command}`
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_claim_repair_followup_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha,
        "draft_path": str(draft_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Prepare missing claim-repair relationship")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--primary", type=Path, default=root / DEFAULT_PRIMARY)
    parser.add_argument(
        "--sampling-ledger", type=Path, default=root / DEFAULT_SAMPLING_LEDGER
    )
    parser.add_argument(
        "--corrections", type=Path, default=root / DEFAULT_CORRECTIONS
    )
    parser.add_argument(
        "--prior-repairs", type=Path, default=root / DEFAULT_PRIOR_REPAIRS
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = prepare_followup(
        args.root.resolve(),
        args.primary.resolve(),
        args.sampling_ledger.resolve(),
        args.corrections.resolve(),
        args.prior_repairs.resolve(),
        args.builder_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
