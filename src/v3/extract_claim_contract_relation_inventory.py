from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.claim_contract_relation_registry import (
    family_type_validation_state,
    relation_contract,
)
from src.v3.diagnose_typed_evidence_ref_generalization_64_precision_fix import (
    DEFAULT_CHUNKS,
    DEFAULT_CLAIM_TARGET_CORRECTIONS,
    DEFAULT_DOCUMENTS,
    DEFAULT_SEALED,
    apply_reviewed_claim_target_corrections,
)
from src.v3.typed_evidence_ref import relation_contract_state


DEFAULT_OUTPUT = Path(
    "reports/v3/typed_evidence_ref_relation_family_registry_96_20260727.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/typed_evidence_ref_relation_family_registry_96_20260727.json"
)
DEFAULT_REPORT = Path(
    "reports/v3/typed_evidence_ref_relation_family_registry_96_20260727.md"
)


def reviewed_relation_family(requirement: dict[str, Any]) -> str:
    """Return the reviewed registry family for one requirement."""

    contract = relation_contract(requirement)
    return contract.family if contract is not None else "unregistered"


def build_relation_inventory(
    sealed_rows: list[dict[str, Any]],
    corrected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_requirements = {
        (row["slot_ordinal"], requirement["requirement_id"]): requirement
        for row in sealed_rows
        for requirement in row["requirements"]
    }
    inventory = []
    for row in corrected_rows:
        for requirement in row["requirements"]:
            key = (row["slot_ordinal"], requirement["requirement_id"])
            original = raw_requirements[key]
            state = relation_contract_state(requirement)
            family_contract = relation_contract(requirement)
            acceptable_units = requirement.get(
                "acceptable_evidence_units"
            ) or []
            inventory.append(
                {
                    "slot_ordinal": row["slot_ordinal"],
                    "candidate_id": row["candidate_id"],
                    "question_text": row["question_text"],
                    "requirement_id": requirement["requirement_id"],
                    "subject": requirement.get("subject"),
                    "relation": requirement.get("relation"),
                    "sealed_relation": original.get("relation"),
                    "claim_target_corrected": (
                        requirement.get("relation")
                        != original.get("relation")
                        or requirement.get("required_values")
                        != original.get("required_values")
                    ),
                    "relation_family": reviewed_relation_family(requirement),
                    "parent_relation": (
                        family_contract.parent_relation
                        if family_contract is not None
                        else None
                    ),
                    "family_validation_mode": (
                        family_contract.validation_mode
                        if family_contract is not None
                        else None
                    ),
                    "family_type_validation_state": (
                        family_type_validation_state(requirement)
                    ),
                    "allowed_value_types": (
                        sorted(family_contract.allowed_value_types)
                        if family_contract is not None
                        else []
                    ),
                    "value_type": requirement.get("value_type"),
                    "expected_status": requirement.get("expected_status"),
                    "temporal_roles": requirement.get("temporal_roles") or [],
                    "cardinality": requirement.get("cardinality"),
                    "expected_count": requirement.get("expected_count"),
                    "relation_contract_state": state,
                    "fail_open_if_exposed": state == "unvalidated",
                    "primary_document_id": row.get(
                        "primary_document_id"
                    ),
                    "acceptable_parent_document_ids": sorted(
                        {
                            unit["document_id"]
                            for unit in acceptable_units
                            if unit.get("document_id")
                        }
                    ),
                    "acceptable_source_ids": sorted(
                        {
                            unit["source_id"]
                            for unit in acceptable_units
                            if unit.get("source_id")
                        }
                    ),
                }
            )
    if len(inventory) != 96:
        raise RuntimeError(
            f"relation inventory requires 96 requirements, got {len(inventory)}"
        )
    return inventory


def _markdown_report(
    inventory: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inventory:
        by_relation[str(row["relation"])].append(row)

    lines = [
        "# Typed evidence-ref relation family registry (96 requirements)",
        "",
        "Date: 2026-07-27",
        "",
        "This registry is built over a diagnostic copy of the sealed set. The "
        "sealed artifact is unchanged. Structured families enforce their "
        "allowed typed-value contract; natural-language families remain "
        "audit-only.",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Requirements | {summary['requirement_count']} |",
        f"| Unique relations | {summary['unique_relation_count']} |",
        f"| Unique parent relations | {summary['unique_parent_relation_count']} |",
        f"| Registered requirements | {summary['registered_requirement_count']} |",
        f"| Explicit alias | {summary['contract_states'].get('explicit_alias', 0)} |",
        f"| Surface fallback | {summary['contract_states'].get('surface_fallback', 0)} |",
        f"| Unvalidated | {summary['contract_states'].get('unvalidated', 0)} |",
        f"| Claim-target corrections | {summary['claim_target_correction_count']} |",
        "",
        "## Reviewed family counts",
        "",
        "| Family | Requirements |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{family}` | {count} |"
        for family, count in summary["family_counts"].items()
    )
    lines.extend(
        [
            "",
            "## Unique relation list",
            "",
            "| Relation | Count | Parent | Family | Contract states | Slots |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for relation, rows in sorted(by_relation.items()):
        families = sorted({row["relation_family"] for row in rows})
        states = sorted({row["relation_contract_state"] for row in rows})
        parents = sorted(
            {
                str(row["parent_relation"])
                for row in rows
                if row["parent_relation"] is not None
            }
        )
        slots = sorted({row["slot_ordinal"] for row in rows})
        lines.append(
            f"| `{relation}` | {len(rows)} | "
            f"`{', '.join(parents)}` | `{', '.join(families)}` | "
            f"`{', '.join(states)}` | "
            f"`{', '.join(map(str, slots))}` |"
        )
    lines.extend(
        [
            "",
            "## Requirement-level inventory",
            "",
            "| Slot | Requirement | Relation | Parent | Family | Type | Family mode | Relation state | Corrected |",
            "|---:|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in inventory:
        lines.append(
            f"| {row['slot_ordinal']} | `{row['requirement_id']}` | "
            f"`{row['relation']}` | `{row['parent_relation']}` | "
            f"`{row['relation_family']}` | `{row['value_type']}` | "
            f"`{row['family_validation_mode']}` | "
            f"`{row['relation_contract_state']}` | "
            f"{'yes' if row['claim_target_corrected'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `explicit_alias`: a verifier relation rule exists.",
            "- `surface_fallback`: only a literal relation surface is available.",
            "- `unvalidated`: no relation proof is enforced; exposure currently "
            "fails open with an audit marker.",
            "- `typed_family`: value type and normalization are enforced, but "
            "this alone is not proof of the child relation.",
            "- `audit_only`: natural-language semantics still require a "
            "reviewed relation contract or a stronger semantic verifier.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the 96-requirement claim relation inventory."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument(
        "--claim-target-corrections",
        type=Path,
        default=DEFAULT_CLAIM_TARGET_CORRECTIONS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    report_path = resolved(args.report)
    if any(path.exists() for path in (output_path, summary_path, report_path)):
        raise RuntimeError("relation inventory output already exists")

    sealed_path = resolved(args.sealed)
    chunks_path = resolved(args.chunks)
    documents_path = resolved(args.documents)
    corrections_path = resolved(args.claim_target_corrections)
    sealed_rows = read_jsonl(sealed_path)
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    corrected_rows, correction_audit = (
        apply_reviewed_claim_target_corrections(
            sealed_rows,
            read_jsonl(corrections_path),
            chunks_by_id={row["chunk_id"]: row for row in chunks},
            documents_by_id={
                row["document_id"]: row for row in documents
            },
            sealed_sha256=file_sha256(sealed_path),
            corpus_chunks_sha256=file_sha256(chunks_path),
        )
    )
    inventory = build_relation_inventory(sealed_rows, corrected_rows)
    state_counts = Counter(
        row["relation_contract_state"] for row in inventory
    )
    family_counts = Counter(row["relation_family"] for row in inventory)
    family_mode_counts = Counter(
        str(row["family_validation_mode"]) for row in inventory
    )
    family_type_state_counts = Counter(
        row["family_type_validation_state"] for row in inventory
    )
    summary = {
        "evaluation_role": (
            "claim_contract_relation_family_registry_not_a_model_score"
        ),
        "sealed_artifact_changed": False,
        "requirement_count": len(inventory),
        "unique_relation_count": len(
            {row["relation"] for row in inventory}
        ),
        "contract_states": dict(sorted(state_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "family_validation_modes": dict(sorted(family_mode_counts.items())),
        "family_type_validation_states": dict(
            sorted(family_type_state_counts.items())
        ),
        "unique_parent_relation_count": len(
            {row["parent_relation"] for row in inventory}
        ),
        "registered_requirement_count": sum(
            row["family_type_validation_state"] != "unregistered"
            for row in inventory
        ),
        "supported_requirements_with_acceptable_parent": sum(
            row["expected_status"] == "supported"
            and bool(row["acceptable_parent_document_ids"])
            for row in inventory
        ),
        "claim_target_correction_count": correction_audit["applied_count"],
        "inputs": {
            "sealed": {
                "path": args.sealed.as_posix(),
                "sha256": file_sha256(sealed_path),
            },
            "claim_target_corrections": {
                "path": args.claim_target_corrections.as_posix(),
                "sha256": file_sha256(corrections_path),
            },
        },
        "output": args.output.as_posix(),
        "report": args.report.as_posix(),
    }
    write_jsonl(output_path, inventory)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        _markdown_report(inventory, summary),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
