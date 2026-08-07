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


BUILDER_VERSION = "replacement-sealed-canary-contract-v3.1.0"
SLOT_SCHEMA_VERSION = "replacement-sealed-canary-slot-v3.1"
MANIFEST_SCHEMA_VERSION = "replacement-sealed-canary-manifest-v3.1"
REPORT_SCHEMA_VERSION = "replacement-sealed-canary-contract-report-v3.1"

DEFAULT_CONTRACT = Path("docs/v3/replacement_sealed_canary_contract.md")
DEFAULT_SOURCE = Path("src/v3/freeze_replacement_canary_contract.py")
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_ADAPTIVE_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_ATTRIBUTION_MANIFEST = Path(
    "data/v3/evaluation/canary_stage_attribution_manifest_"
    "9e25fe54e91bfd133febc44de355b5df7beab370153769196cc9cc905bb3251c.json"
)
DEFAULT_ATTRIBUTION_REPORT = Path(
    "reports/v3/canary_stage_attribution_"
    "aea9decd7b8df794e9e04100d74d25ca571893fb47f6b746e0327cc19edf820a.json"
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

BASE_BLUEPRINTS = (
    ("single_current", "single", "current", "retrieve", "true"),
    (
        "compound_without_surface_keywords",
        "multi",
        "current",
        "decompose",
        "true",
    ),
    ("partial", "partial", "current", "retrieve", "partial"),
    ("ambiguous_route", "single", "current", "retrieve", "true"),
)

SAFETY_BLUEPRINTS = {
    "dnf_notice": ("historical", "historical", "retrieve", "true"),
    "dnf_update": ("preview", "preview", "retrieve", "true"),
    "dnf_event": ("historical", "historical", "retrieve", "true"),
    "dnf_game_guide": ("realtime", "current", "realtime_api", "false"),
    "dnf_faq": ("false", "current", "reject", "false"),
    "dnf_account_policy": ("comparison", "mixed", "decompose", "true"),
    "dnf_seria_shop": ("historical", "historical", "retrieve", "true"),
    "dnf_monthly_item": ("historical", "historical", "retrieve", "true"),
}

PREREGISTERED_GATES = {
    "route_action_exact_min": 0.85,
    "route_action_drop_from_frozen_development_max": 0.05,
    "retrieval_all_required_evidence_recall_min": 0.90,
    "selected_evidence_group_hit_min": 0.85,
    "cited_evidence_group_hit_min": 0.85,
    "claim_completeness_min": 0.90,
    "strict_regression_count_max": 0,
    "strict_improvement_count_min": 1,
    "minimum_source_retrieval_recall_min": 0.66,
    "zero_hit_source_count_max": 0,
    "temporal_revision_violation_count_max": 0,
    "false_realtime_evidence_exposure_count_max": 0,
    "partial_disclaimer_required": "8_of_8",
    "confidence_interval": "wilson_95_percent",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _disjointness(
    source_id: str, time_scope: str, route_action: str
) -> dict[str, Any]:
    if route_action in {"reject", "realtime_api"}:
        return {
            "dev_parent_disjoint_required": False,
            "adaptive_parent_disjoint_required": False,
            "parent_disjointness_exception_reason": "zero_evidence_control",
        }
    if source_id == "dnf_account_policy" and time_scope in {"current", "mixed"}:
        return {
            "dev_parent_disjoint_required": False,
            "adaptive_parent_disjoint_required": False,
            "parent_disjointness_exception_reason": "current_policy_revision_required",
        }
    if source_id == "dnf_monthly_item" and time_scope == "current":
        return {
            "dev_parent_disjoint_required": False,
            "adaptive_parent_disjoint_required": False,
            "parent_disjointness_exception_reason": "single_current_monthly_parent",
        }
    return {
        "dev_parent_disjoint_required": True,
        "adaptive_parent_disjoint_required": True,
        "parent_disjointness_exception_reason": None,
    }


def build_replacement_slots() -> list[dict[str, Any]]:
    rows = []
    ordinal = 1
    for source_id in SOURCE_IDS:
        safety_kind, safety_scope, safety_route, safety_answerability = (
            SAFETY_BLUEPRINTS[source_id]
        )
        blueprints = (*BASE_BLUEPRINTS, (
            "source_safety",
            safety_kind,
            safety_scope,
            safety_route,
            safety_answerability,
        ))
        for stratum, query_kind, time_scope, route_action, answerability in blueprints:
            identity = _canonical_json_bytes(
                {
                    "source_id": source_id,
                    "stratum": stratum,
                    "query_kind": query_kind,
                    "time_scope": time_scope,
                    "route_action": route_action,
                    "ordinal": ordinal,
                }
            )
            rows.append(
                {
                    "slot_schema_version": SLOT_SCHEMA_VERSION,
                    "slot_id": f"replacement_canary_slot_sha256_{_sha256_bytes(identity)}",
                    "slot_ordinal": ordinal,
                    "source_id": source_id,
                    "stratum": stratum,
                    "query_kind": query_kind,
                    "time_scope": time_scope,
                    "expected_route_action": route_action,
                    "intended_answerability": answerability,
                    "question_text": None,
                    "gold_answer": None,
                    "evidence_groups": None,
                    "forbidden_surface_tokens": ["각각", "비교", "함께"]
                    if stratum == "compound_without_surface_keywords"
                    else [],
                    "question_pattern_disjoint_from_dev_required": True,
                    "question_pattern_disjoint_from_adaptive_canary_required": True,
                    "atomic_claim_disjoint_from_dev_required": route_action
                    not in {"reject", "realtime_api"},
                    "atomic_claim_disjoint_from_adaptive_canary_required": route_action
                    not in {"reject", "realtime_api"},
                    "chunk_disjoint_from_dev_required": route_action
                    not in {"reject", "realtime_api"},
                    "chunk_disjoint_from_adaptive_canary_required": route_action
                    not in {"reject", "realtime_api"},
                    **_disjointness(source_id, time_scope, route_action),
                    "author_must_not_view_retrieval_results": True,
                    "author_must_not_view_adaptive_case_artifact": True,
                    "runtime_and_input_hashes_required_before_authoring": True,
                    "independent_human_review_required": True,
                    "evaluation_role": "separately_authored_human_reviewed_canary",
                    "training_allowed": False,
                    "final_benchmark_eligible": False,
                }
            )
            ordinal += 1
    return rows


def audit_replacement_slots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = Counter(row["source_id"] for row in rows)
    stratum_counts = Counter(row["stratum"] for row in rows)
    safety_counts = Counter(
        row["query_kind"] for row in rows if row["stratum"] == "source_safety"
    )
    exception_counts = Counter(
        row["parent_disjointness_exception_reason"]
        for row in rows
        if row["parent_disjointness_exception_reason"]
    )
    gates = {
        "row_count_40": len(rows) == 40,
        "source_count_8": len(source_counts) == 8,
        "each_source_count_5": set(source_counts.values()) == {5},
        "each_stratum_count_8": set(stratum_counts.values()) == {8}
        and len(stratum_counts) == 5,
        "partial_count_8": sum(
            row["intended_answerability"] == "partial" for row in rows
        )
        == 8,
        "safety_balance": dict(sorted(safety_counts.items()))
        == {
            "comparison": 1,
            "false": 1,
            "historical": 4,
            "preview": 1,
            "realtime": 1,
        },
        "questions_and_gold_unwritten": all(
            row["question_text"] is None
            and row["gold_answer"] is None
            and row["evidence_groups"] is None
            for row in rows
        ),
        "compound_surface_tokens_prohibited": all(
            row["forbidden_surface_tokens"] == ["각각", "비교", "함께"]
            for row in rows
            if row["stratum"] == "compound_without_surface_keywords"
        ),
        "adaptive_case_hidden_from_authors": all(
            row["author_must_not_view_adaptive_case_artifact"] for row in rows
        ),
        "independent_human_review_required": all(
            row["independent_human_review_required"] for row in rows
        ),
        "parent_exceptions_preregistered": dict(sorted(exception_counts.items()))
        == {
            "current_policy_revision_required": 5,
            "single_current_monthly_parent": 4,
            "zero_evidence_control": 2,
        },
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "stratum_counts": dict(sorted(stratum_counts.items())),
        "source_safety_query_kind_counts": dict(sorted(safety_counts.items())),
        "parent_disjointness_exception_counts": dict(
            sorted(exception_counts.items())
        ),
    }


def freeze_replacement_contract(
    *,
    root: Path,
    contract_path: Path = DEFAULT_CONTRACT,
    source_path: Path = DEFAULT_SOURCE,
    dev_set_path: Path = DEFAULT_DEV_SET,
    adaptive_canary_path: Path = DEFAULT_ADAPTIVE_CANARY,
    attribution_manifest_path: Path = DEFAULT_ATTRIBUTION_MANIFEST,
    attribution_report_path: Path = DEFAULT_ATTRIBUTION_REPORT,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    input_paths = {
        "contract": resolve(contract_path),
        "builder_source": resolve(source_path),
        "adaptive_dev_for_disjointness": resolve(dev_set_path),
        "downgraded_adaptive_canary_for_disjointness": resolve(adaptive_canary_path),
        "stage_attribution_manifest": resolve(attribution_manifest_path),
        "stage_attribution_report": resolve(attribution_report_path),
    }
    with input_paths["stage_attribution_report"].open(encoding="utf-8") as handle:
        stage_report = json.load(handle)
    if stage_report["dominance"]["required_first_approach"] != "ROBUST_ROUTING":
        raise RuntimeError("Replacement contract requires ROUTING-dominant attribution")
    if stage_report["new_dev_fit_rules_added"] != 0:
        raise RuntimeError("Stage attribution introduced a dev-fit rule")

    rows = build_replacement_slots()
    audit = audit_replacement_slots(rows)
    if not audit["gate_pass"]:
        raise RuntimeError(f"Replacement canary slot audit failed: {audit['gates']}")
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    rows_bytes = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = evaluation_dir / f"replacement_sealed_canary_plan_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "plan": {
            "path": _relative(root, rows_path),
            "sha256": rows_sha,
            "row_count": len(rows),
        },
        "stage_decision": {
            "dominant_bucket": "ROUTING",
            "first_allowed_approach": "uncertainty_aware_multi_store_or_confidence_gated_broad_fallback",
            "downstream_changes_before_routing_gate": "PROHIBITED",
            "new_dev_fit_rules_added": 0,
        },
        "independence": {
            "current_level": "contract_and_empty_slots_only",
            "question_and_gold_authored": False,
            "independent_holdout_claim_allowed": False,
            "separate_author_required": True,
            "independent_human_review_required": True,
            "frozen_blind_accessed": False,
        },
        "preregistered_gates": PREREGISTERED_GATES,
        "slot_audit": audit,
        "downgrade_policy": {
            "if_results_opened_and_approach_changed": "adaptive_validation",
            "sealed_reuse_after_adaptation": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"replacement_sealed_canary_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "plan_sha256": rows_sha,
        "manifest_sha256": manifest_sha,
        "slot_audit": audit,
        "preregistered_gates": PREREGISTERED_GATES,
        "decisions": {
            "replacement_canary_contract": "GO",
            "robust_routing_approach_implementation": "PENDING",
            "question_and_gold_authoring": "NO-GO_UNTIL_RUNTIME_HASH_FREEZE",
            "sealed_execution": "NO-GO_UNTIL_AUTHORING_AND_HUMAN_REVIEW",
            "downstream_claim_or_verify_changes": "NO-GO_BEFORE_ROUTING_GATE",
            "final_blind": "NO-GO",
        },
        "new_dev_fit_rules_added": 0,
        "not_performed": [
            "runtime_routing_change",
            "question_authoring",
            "gold_authoring",
            "retrieval_execution",
            "frozen_blind_access",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"replacement_sealed_canary_contract_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed while freezing replacement contract: {name}")
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
    parser = argparse.ArgumentParser(description="Freeze the replacement v3 canary contract")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            freeze_replacement_contract(root=parse_args().root),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
