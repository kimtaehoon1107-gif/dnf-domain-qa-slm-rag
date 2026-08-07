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

from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)


BUILDER_VERSION = "early-generalization-canary-contract-v3.1.2"
SLOT_SCHEMA_VERSION = "early-generalization-canary-slot-v3.1.2"
MANIFEST_SCHEMA_VERSION = "early-generalization-canary-manifest-v3.1"
REPORT_SCHEMA_VERSION = "early-generalization-canary-contract-report-v3.1"

DEFAULT_CONTRACT = Path("docs/v3/early_generalization_canary.md")
DEFAULT_SOURCE = Path("src/v3/freeze_canary_contract.py")
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)

SOURCE_BLUEPRINTS = {
    "dnf_notice": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("partial", "current", "retrieve"),
        ("false", "current", "reject"),
    ),
    "dnf_update": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("preview", "preview", "retrieve"),
        ("partial", "current", "retrieve"),
    ),
    "dnf_event": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("historical", "historical", "retrieve"),
        ("partial", "current", "retrieve"),
    ),
    "dnf_game_guide": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("partial", "current", "retrieve"),
        ("realtime", "current", "realtime_api"),
    ),
    "dnf_faq": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("false", "current", "reject"),
        ("partial", "current", "retrieve"),
    ),
    "dnf_account_policy": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("historical", "historical", "retrieve"),
        ("comparison", "mixed", "decompose"),
    ),
    "dnf_seria_shop": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("historical", "historical", "retrieve"),
        ("realtime", "current", "realtime_api"),
    ),
    "dnf_monthly_item": (
        ("single", "current", "retrieve"),
        ("multi", "current", "decompose"),
        ("historical", "historical", "retrieve"),
        ("false", "current", "reject"),
    ),
}

PREREGISTERED_GATES = {
    "retrieval_all_required_evidence_recall_min": 0.90,
    "selected_evidence_group_hit_min": 0.85,
    "cited_evidence_group_hit_min": 0.85,
    "claim_completeness_min": 0.90,
    "strict_regression_count_max": 0,
    "strict_improvement_count_min_for_promotion": 1,
    "minimum_source_retrieval_recall_min": 0.66,
    "zero_hit_source_count_max": 0,
    "temporal_revision_violation_count_max": 0,
    "false_realtime_evidence_exposure_count_max": 0,
    "partial_disclaimer_required": "5_of_5",
    "confidence_interval": "wilson_95_percent",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def disjointness_requirements(
    source_id: str, query_kind: str, time_scope: str, route_action: str
) -> dict[str, Any]:
    if route_action in {"reject", "realtime_api"}:
        return {
            "dev_parent_disjoint_required": False,
            "dev_chunk_disjoint_required": False,
            "dev_claim_disjoint_required": False,
            "question_composition_disjoint_required": True,
            "disjointness_exception_reason": None,
        }
    if source_id == "dnf_account_policy" and time_scope in {"current", "mixed"}:
        return {
            "dev_parent_disjoint_required": False,
            "dev_chunk_disjoint_required": True,
            "dev_claim_disjoint_required": True,
            "question_composition_disjoint_required": True,
            "disjointness_exception_reason": "single_current_policy_revision_parent",
        }
    if source_id == "dnf_monthly_item" and time_scope == "current":
        claim_disjoint = query_kind == "single"
        return {
            "dev_parent_disjoint_required": False,
            "dev_chunk_disjoint_required": False,
            "dev_claim_disjoint_required": claim_disjoint,
            "question_composition_disjoint_required": True,
            "disjointness_exception_reason": (
                "single_current_monthly_document_and_chunk"
                if claim_disjoint
                else "single_current_monthly_document_and_chunk_all_facts_in_dev"
            ),
        }
    return {
        "dev_parent_disjoint_required": True,
        "dev_chunk_disjoint_required": True,
        "dev_claim_disjoint_required": True,
        "question_composition_disjoint_required": True,
        "disjointness_exception_reason": None,
    }


def build_canary_slots() -> list[dict[str, Any]]:
    rows = []
    ordinal = 1
    for source_id, blueprints in SOURCE_BLUEPRINTS.items():
        for query_kind, time_scope, route_action in blueprints:
            disjointness = disjointness_requirements(
                source_id, query_kind, time_scope, route_action
            )
            identity = _canonical_json_bytes(
                {
                    "source_id": source_id,
                    "query_kind": query_kind,
                    "time_scope": time_scope,
                    "route_action": route_action,
                    "source_slot": ordinal,
                }
            )
            rows.append(
                {
                    "canary_slot_schema_version": SLOT_SCHEMA_VERSION,
                    "slot_id": f"canary_slot_sha256_{_sha256_bytes(identity)}",
                    "slot_ordinal": ordinal,
                    "source_id": source_id,
                    "query_kind": query_kind,
                    "time_scope": time_scope,
                    "expected_route_action": route_action,
                    "question_text": None,
                    "gold_answer": None,
                    "evidence_groups": None,
                    "question_pattern_disjoint_required": True,
                    **disjointness,
                    "forbidden_surface_tokens": ["각각", "비교", "함께"]
                    if query_kind in {"multi", "comparison"}
                    else [],
                    "question_author_must_not_view_retrieval": True,
                    "independent_gold_review_required": True,
                    "evaluation_role_before_independent_review": "authored_canary",
                    "training_allowed": False,
                    "final_benchmark_eligible": False,
                }
            )
            ordinal += 1
    return rows


def audit_slots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = Counter(row["source_id"] for row in rows)
    kind_counts = Counter(row["query_kind"] for row in rows)
    route_counts = Counter(row["expected_route_action"] for row in rows)
    time_counts = Counter(row["time_scope"] for row in rows)
    exception_counts = Counter(
        row["disjointness_exception_reason"]
        for row in rows
        if row["disjointness_exception_reason"]
    )
    gates = {
        "row_count_32": len(rows) == 32,
        "source_count_8": len(source_counts) == 8,
        "each_source_count_4": set(source_counts.values()) == {4},
        "single_count_8": kind_counts["single"] == 8,
        "multi_count_8": kind_counts["multi"] == 8,
        "partial_count_5": kind_counts["partial"] == 5,
        "false_count_3": kind_counts["false"] == 3,
        "historical_count_4": kind_counts["historical"] == 4,
        "preview_count_1": kind_counts["preview"] == 1,
        "realtime_count_2": kind_counts["realtime"] == 2,
        "comparison_count_1": kind_counts["comparison"] == 1,
        "questions_and_gold_unwritten": all(
            row["question_text"] is None
            and row["gold_answer"] is None
            and row["evidence_groups"] is None
            for row in rows
        ),
        "multi_trigger_tokens_prohibited": all(
            row["forbidden_surface_tokens"] == ["각각", "비교", "함께"]
            for row in rows
            if row["query_kind"] in {"multi", "comparison"}
        ),
        "independent_review_required": all(
            row["independent_gold_review_required"] for row in rows
        ),
        "disjointness_exceptions_preregistered": dict(exception_counts)
        == {
            "single_current_monthly_document_and_chunk": 1,
            "single_current_monthly_document_and_chunk_all_facts_in_dev": 1,
            "single_current_policy_revision_parent": 3,
        },
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "query_kind_counts": dict(sorted(kind_counts.items())),
        "route_action_counts": dict(sorted(route_counts.items())),
        "time_scope_counts": dict(sorted(time_counts.items())),
        "disjointness_exception_counts": dict(sorted(exception_counts.items())),
    }


def freeze_canary_contract(
    root: Path, contract_path: Path, source_path: Path, dev_set_path: Path
) -> dict[str, Any]:
    rows = build_canary_slots()
    audit = audit_slots(rows)
    if not audit["gate_pass"]:
        raise RuntimeError(f"Canary contract slot audit failed: {audit['gates']}")
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    rows_bytes = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = evaluation_dir / f"early_generalization_canary_plan_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)
    inputs = {
        "contract": contract_path,
        "builder_source": source_path,
        "adaptive_dev_for_future_disjointness_audit": dev_set_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "plan": {
            "path": _relative(root, rows_path),
            "sha256": rows_sha,
            "row_count": len(rows),
        },
        "independence": {
            "current_level": "authored_canary_contract_only",
            "question_and_gold_authored": False,
            "independent_holdout_claim_allowed": False,
            "independent_human_review_required_before_execution": True,
            "frozen_blind_accessed": False,
        },
        "preregistered_gates": PREREGISTERED_GATES,
        "slot_audit": audit,
        "downgrade_policy": {
            "if_failure_cases_opened_and_rules_changed": "adaptive_validation",
            "sealed_benchmark_reuse_after_adaptation": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"early_generalization_canary_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "plan_sha256": rows_sha,
        "manifest_sha256": manifest_sha,
        "slot_audit": audit,
        "preregistered_gates": PREREGISTERED_GATES,
        "decisions": {
            "canary_contract": "GO",
            "canary_question_authoring": "PENDING_INDEPENDENT_REVIEW",
            "canary_execution": "NO-GO",
            "temporal_nli_generator_expansion": "NO-GO_BEFORE_CANARY",
            "final_benchmark": "NO-GO",
        },
        "not_performed": [
            "question_authoring",
            "gold_authoring",
            "retrieval_execution",
            "failure_case_inspection",
            "frozen_blind_access",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"early_generalization_canary_contract_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    return {
        "plan_path": str(rows_path),
        "plan_sha256": rows_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "slot_audit": audit,
        "decisions": report["decisions"],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Freeze v3 canary contract")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    parser.add_argument("--source", type=Path, default=root / DEFAULT_SOURCE)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    result = freeze_canary_contract(
        root, args.contract.resolve(), args.source.resolve(), args.dev_set.resolve()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
