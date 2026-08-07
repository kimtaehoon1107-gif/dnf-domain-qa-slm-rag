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
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "requirement-surface-query-canary-contract-v1.0.0"
SLOT_SCHEMA_VERSION = "requirement-surface-query-canary-slot-v1"
MANIFEST_SCHEMA_VERSION = "requirement-surface-query-canary-manifest-v1"

DEFAULT_CONTRACT = Path("docs/v3/requirement_surface_query_canary_contract.md")
DEFAULT_SOURCE = Path("src/v3/freeze_requirement_surface_query_canary_contract.py")
DEFAULT_FEATURE_SOURCE = Path("src/v3/requirement_surface_query.py")
DEFAULT_EVALUATOR_SOURCE = Path("src/v3/evaluate_requirement_surface_query_ab.py")
DEFAULT_FEATURE_MANIFEST = Path(
    "data/v3/evidence/requirement_surface_query_ab_manifest_"
    "de7990f351fac0fe33df2af42b863b0dc66dbf8c84cd71c29ac08357d73f82d0.json"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_DOWNGRADED_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_AUTHORED_VALIDATION = Path(
    "data/v3/evaluation/authored_validation_v3_2_"
    "52c1b84ef7ab0f9bee29931c46f9febf0970492216b6742e8f5337282af4181e.jsonl"
)

SOURCE_IDS = (
    "dnf_notice",
    "dnf_update",
    "dnf_event",
    "dnf_game_guide",
    "dnf_faq",
    "dnf_account_policy",
    "dnf_seria_shop",
    "dnf_monthly_item",
)
BLUEPRINTS = (
    ("positive_coordination_a", "apply", 2),
    ("positive_coordination_b", "apply", 2),
    ("single_requirement_control", "bypass", 1),
    ("three_requirement_control", "bypass", 3),
)

PREREGISTERED_GATES: dict[str, Any] = {
    "candidate_all_required_coverage_vs_baseline": "non_decreasing",
    "strict_question_regression_count_max": 0,
    "literal_evidence_span_regression_count_max": 0,
    "strict_or_literal_improvement_count_min": 1,
    "expected_apply_count": 16,
    "expected_bypass_count": 16,
    "bypass_output_mutation_count_max": 0,
    "false_full_count_max": 0,
    "exact_citation_slice_rate_min": 1.0,
    "new_irrelevant_or_surplus_citation_count_max": 0,
    "requirement_citation_precision_vs_baseline": "non_decreasing",
    "temporal_revision_preview_expired_violation_count_max": 0,
    "zero_hit_source_count_max": 0,
    "minimum_source_positive_all_required_coverage_min": 0.5,
    "sealed_run_count_allowed": 1,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_slots() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordinal = 1
    for source_id in SOURCE_IDS:
        for stratum, expected_action, requirement_count in BLUEPRINTS:
            identity = _canonical_json_bytes(
                {
                    "schema": SLOT_SCHEMA_VERSION,
                    "source_id": source_id,
                    "stratum": stratum,
                    "ordinal": ordinal,
                }
            )
            rows.append(
                {
                    "slot_schema_version": SLOT_SCHEMA_VERSION,
                    "slot_id": f"requirement_surface_slot_sha256_{_sha256_bytes(identity)}",
                    "slot_ordinal": ordinal,
                    "source_id": source_id,
                    "stratum": stratum,
                    "expected_surface_query_action": expected_action,
                    "expected_requirement_count": requirement_count,
                    "question_text": None,
                    "requirements": None,
                    "evidence_groups": None,
                    "gold_answer": None,
                    "paired_metamorphic_feature_canary": True,
                    "user_full_review_required": True,
                    "independent_holdout_claim_allowed": False,
                    "training_allowed": False,
                    "final_benchmark_eligible": False,
                    "sealed_scoring_allowed": False,
                }
            )
            ordinal += 1
    return rows


def audit_slots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sources = Counter(row["source_id"] for row in rows)
    actions = Counter(row["expected_surface_query_action"] for row in rows)
    strata = Counter(row["stratum"] for row in rows)
    gates = {
        "row_count_32": len(rows) == 32,
        "source_count_8": len(sources) == 8,
        "source_balance_4_each": set(sources.values()) == {4},
        "apply_count_16": actions == {"apply": 16, "bypass": 16},
        "stratum_balance_8_each": set(strata.values()) == {8},
        "questions_and_gold_empty": all(
            row["question_text"] is None
            and row["requirements"] is None
            and row["evidence_groups"] is None
            and row["gold_answer"] is None
            for row in rows
        ),
        "review_required_32": all(row["user_full_review_required"] for row in rows),
        "sealed_scoring_blocked_32": all(
            not row["sealed_scoring_allowed"] for row in rows
        ),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(sources.items())),
        "action_counts": dict(sorted(actions.items())),
        "stratum_counts": dict(sorted(strata.items())),
    }


def freeze_contract(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "contract": DEFAULT_CONTRACT,
        "builder_source": DEFAULT_SOURCE,
        "feature_source": DEFAULT_FEATURE_SOURCE,
        "evaluator_source": DEFAULT_EVALUATOR_SOURCE,
        "feature_manifest": DEFAULT_FEATURE_MANIFEST,
        "documents": DEFAULT_DOCUMENTS,
        "chunks": DEFAULT_CHUNKS,
        "adaptive_dev_for_disjointness": DEFAULT_DEV,
        "downgraded_canary_for_disjointness": DEFAULT_DOWNGRADED_CANARY,
        "authored_validation_for_disjointness": DEFAULT_AUTHORED_VALIDATION,
    }
    resolved = {name: root / path for name, path in input_paths.items()}
    missing = [name for name, path in resolved.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing surface canary inputs: {missing}")
    before = {name: file_sha256(path) for name, path in resolved.items()}

    rows = build_slots()
    audit = audit_slots(rows)
    if not audit["gate_pass"]:
        raise RuntimeError(f"Surface canary slot audit failed: {audit['gates']}")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    rows_bytes = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = evaluation_dir / f"requirement_surface_query_canary_plan_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in resolved.items()
        },
        "plan": {
            "path": _relative(root, rows_path),
            "sha256": rows_sha,
            "row_count": len(rows),
        },
        "preregistered_gates": PREREGISTERED_GATES,
        "slot_audit": audit,
        "independence": {
            "level": "contract_and_empty_slots_only",
            "authorship_after_contract": "codex_authored_user_full_review_required",
            "independent_holdout_claim_allowed": False,
            "frozen_blind_accessed": False,
        },
        "execution": {
            "reviewed_immutable_export_ready": False,
            "sealed_run_allowed_now": False,
            "canonical_promotion_allowed_now": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / (
        f"requirement_surface_query_canary_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": "requirement-surface-query-canary-contract-report-v1",
        "builder_version": BUILDER_VERSION,
        "plan_sha256": rows_sha,
        "manifest_sha256": manifest_sha,
        "slot_audit": audit,
        "preregistered_gates": PREREGISTERED_GATES,
        "decisions": {
            "contract_and_empty_slots": "GO",
            "candidate_authoring": "READY",
            "user_full_review": "PENDING",
            "sealed_execution": "NO_GO",
            "canonical_promotion": "NO_GO",
        },
        "new_measurement_performed": False,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"requirement_surface_query_canary_contract_{report_sha}.json"
    write_immutable(report_path, report_bytes)

    for name, path in resolved.items():
        if file_sha256(path) != before[name]:
            raise RuntimeError(f"Input changed while freezing surface canary: {name}")
    return {
        "plan_path": str(rows_path),
        "plan_sha256": rows_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "slot_audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> None:
    print(json.dumps(freeze_contract(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
