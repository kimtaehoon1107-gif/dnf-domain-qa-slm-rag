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


BUILDER_VERSION = "v3.2-promotion-canary-contract-v1.0.0"
SLOT_SCHEMA_VERSION = "v3.2-promotion-canary-slot-v1"
MANIFEST_SCHEMA_VERSION = "v3.2-promotion-canary-manifest-v1"
REPORT_SCHEMA_VERSION = "v3.2-promotion-canary-contract-report-v1"

DEFAULT_CONTRACT = Path("docs/v3/v3_2_promotion_canary_contract.md")
DEFAULT_SOURCE = Path("src/v3/freeze_v3_2_promotion_canary_contract.py")
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/bm25_manifest_"
    "f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_DENSE_MANIFEST = Path(
    "data/v3/indexes/dense_full_manifest_"
    "51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)
DEFAULT_ASSEMBLER_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_"
    "9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json"
)
DEFAULT_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DEFAULT_DUPLICATE_OVERLAY = Path(
    "data/v3/structured/duplicate_family_overlay_v3.2_"
    "d71e7184b95a4bbdf8a4748b24daf5ce6b2d67834507660f905ffc869faaa336.jsonl"
)
DEFAULT_TABLE_FACTS = Path(
    "data/v3/structured/table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_TABLE_INDEX_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_index_manifest_"
    "423dfd6ae35bbfa5db1cef0ea1caa61df547ed99c508c998fd134f44f1c4f79d.json"
)
DEFAULT_DEMO_SOURCE = Path("src/v3/gradio_backbone_demo.py")
DEFAULT_TABLE_ASSEMBLER_SOURCE = Path("src/v3/assemble_table_group_answers.py")
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_ADAPTIVE_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)

PLANNER_MODEL = "qwen3:8b"
PLANNER_MODEL_BLOB_SHA256 = "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
PLANNER_PROMPT_SHA256 = "01ddcf34498276b4896f5c628f53fa874047e8a989b3a5df3e405bd43c87d948"

SOURCE_BLUEPRINTS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "dnf_notice": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("long_lived_current", "current", "full", "global_temporal"),
        ("historical_control", "historical", "full", "global_temporal"),
        ("duplicate_family", "current", "full", "duplicate_family"),
    ),
    "dnf_update": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("live_revision", "current", "full", "global_temporal"),
        ("preview_control", "preview", "full", "global_temporal"),
        ("duplicate_family", "current", "full", "duplicate_family"),
    ),
    "dnf_event": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("active_window", "current", "full", "global_temporal"),
        ("expired_control", "historical", "full", "global_temporal"),
        ("duplicate_family", "current", "full", "duplicate_family"),
    ),
    "dnf_game_guide": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("table_row_values", "current", "full", "table_atomic"),
        ("non_table_regression", "current", "full", "backbone_nonregression"),
        ("cross_parent_control", "current", "gold_defined", "backbone_nonregression"),
    ),
    "dnf_faq": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("duplicate_title", "current", "full", "backbone_nonregression"),
        ("long_lived_current", "current", "full", "global_temporal"),
        ("unsupported_personal", "current", "abstain", "safety_control"),
    ),
    "dnf_account_policy": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("current_revision", "current", "full", "global_temporal"),
        ("historical_revision", "historical", "full", "global_temporal"),
        ("comparison", "mixed", "full", "global_temporal"),
    ),
    "dnf_seria_shop": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("table_row_values", "current", "full", "table_atomic"),
        ("expired_control", "historical", "full", "global_temporal"),
        ("duplicate_family", "current", "full", "duplicate_family"),
    ),
    "dnf_monthly_item": (
        ("current_fact", "current", "full", "backbone_nonregression"),
        ("multi_field", "current", "full", "backbone_nonregression"),
        ("table_row_values", "current", "full", "table_atomic"),
        ("expired_control", "historical", "full", "global_temporal"),
        ("duplicate_family", "current", "full", "duplicate_family"),
    ),
}

PREREGISTERED_GATES = {
    "candidate_all_required_coverage_vs_baseline": "non_decreasing",
    "strict_question_regression_count_max": 0,
    "strict_improvement_count_min": 1,
    "false_full_count_max": 0,
    "exact_citation_slice_rate_min": 1.0,
    "table_row_subject_attribute_value_complete_rate_min": 1.0,
    "temporal_revision_preview_expired_violation_count_max": 0,
    "current_denied_revision_citation_count_max": 0,
    "unsafe_control_evidence_exposure_count_max": 0,
    "duplicate_family_provenance_missing_count_max": 0,
    "zero_hit_source_count_max": 0,
    "minimum_source_all_required_coverage_min": 0.8,
    "confidence_interval": "wilson_95_percent",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_slots() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordinal = 1
    for source_id, blueprints in SOURCE_BLUEPRINTS.items():
        for stratum, time_scope, expected_response, feature_focus in blueprints:
            identity = _canonical_json_bytes(
                {
                    "source_id": source_id,
                    "stratum": stratum,
                    "ordinal": ordinal,
                    "contract": SLOT_SCHEMA_VERSION,
                }
            )
            rows.append(
                {
                    "slot_schema_version": SLOT_SCHEMA_VERSION,
                    "slot_id": f"v3_2_promotion_slot_sha256_{_sha256_bytes(identity)}",
                    "slot_ordinal": ordinal,
                    "source_id": source_id,
                    "stratum": stratum,
                    "time_scope": time_scope,
                    "expected_response": expected_response,
                    "feature_focus": feature_focus,
                    "question_text": None,
                    "requirements": None,
                    "gold_answer": None,
                    "evidence_groups": None,
                    "allowed_document_ids": None,
                    "forbidden_document_ids": None,
                    "question_pattern_disjoint_from_dev_required": True,
                    "question_pattern_disjoint_from_adaptive_canary_required": True,
                    "atomic_claim_disjoint_from_dev_required": True,
                    "atomic_claim_disjoint_from_adaptive_canary_required": True,
                    "parent_disjoint_required_when_available": True,
                    "author_must_not_view_retrieval_results": True,
                    "author_must_not_view_adaptive_case_artifact": True,
                    "independent_human_review_required": True,
                    "evaluation_role": "separately_authored_human_reviewed_canary",
                    "training_allowed": False,
                    "final_benchmark_eligible": False,
                }
            )
            ordinal += 1
    return rows


def audit_slots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = Counter(row["source_id"] for row in rows)
    feature_counts = Counter(row["feature_focus"] for row in rows)
    time_counts = Counter(row["time_scope"] for row in rows)
    gates = {
        "row_count_40": len(rows) == 40,
        "source_count_8": len(source_counts) == 8,
        "each_source_count_5": set(source_counts.values()) == {5},
        "table_atomic_slots_3": feature_counts["table_atomic"] == 3,
        "global_temporal_slots_at_least_10": feature_counts["global_temporal"] >= 10,
        "duplicate_family_slots_at_least_5": feature_counts["duplicate_family"] >= 5,
        "non_current_controls_at_least_6": sum(
            count for scope, count in time_counts.items() if scope != "current"
        )
        >= 6,
        "questions_and_gold_unwritten": all(
            row["question_text"] is None
            and row["requirements"] is None
            and row["gold_answer"] is None
            and row["evidence_groups"] is None
            for row in rows
        ),
        "independent_human_review_required": all(
            row["independent_human_review_required"] for row in rows
        ),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "feature_counts": dict(sorted(feature_counts.items())),
        "time_scope_counts": dict(sorted(time_counts.items())),
    }


def freeze_contract(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "contract": DEFAULT_CONTRACT,
        "builder_source": DEFAULT_SOURCE,
        "documents": DEFAULT_DOCUMENTS,
        "chunks": DEFAULT_CHUNKS,
        "bm25_manifest": DEFAULT_BM25_MANIFEST,
        "dense_manifest": DEFAULT_DENSE_MANIFEST,
        "assembler_manifest": DEFAULT_ASSEMBLER_MANIFEST,
        "global_temporal_overlay": DEFAULT_TEMPORAL_OVERLAY,
        "duplicate_family_overlay": DEFAULT_DUPLICATE_OVERLAY,
        "table_atomic_facts": DEFAULT_TABLE_FACTS,
        "table_index_manifest": DEFAULT_TABLE_INDEX_MANIFEST,
        "demo_source": DEFAULT_DEMO_SOURCE,
        "table_assembler_source": DEFAULT_TABLE_ASSEMBLER_SOURCE,
        "adaptive_dev_for_disjointness": DEFAULT_DEV_SET,
        "downgraded_canary_for_disjointness": DEFAULT_ADAPTIVE_CANARY,
    }
    resolved = {name: root / path for name, path in input_paths.items()}
    missing = [name for name, path in resolved.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing promotion canary inputs: {missing}")
    input_hashes = {name: file_sha256(path) for name, path in resolved.items()}

    rows = build_slots()
    audit = audit_slots(rows)
    if not audit["gate_pass"]:
        raise RuntimeError(f"Promotion canary slot audit failed: {audit['gates']}")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    rows_bytes = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = evaluation_dir / f"v3_2_promotion_canary_plan_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in resolved.items()
        },
        "runtime": {
            "baseline_arm": "dirty_canonical_v3_2_candidates_off",
            "candidate_arm": "dirty_canonical_v3_2_candidates_on",
            "planner_model": PLANNER_MODEL,
            "planner_model_blob_sha256": PLANNER_MODEL_BLOB_SHA256,
            "planner_prompt_sha256": PLANNER_PROMPT_SHA256,
            "temperature": 0,
            "sealed_run_count_allowed": 1,
        },
        "plan": {
            "path": _relative(root, rows_path),
            "sha256": rows_sha,
            "row_count": len(rows),
        },
        "preregistered_gates": PREREGISTERED_GATES,
        "slot_audit": audit,
        "independence": {
            "current_level": "contract_runtime_hashes_and_empty_slots_only",
            "question_and_gold_authored": False,
            "separate_author_required": True,
            "independent_human_review_required": True,
            "independent_holdout_claim_allowed": False,
            "frozen_blind_accessed": False,
        },
        "downgrade_policy": {
            "if_results_opened_and_any_component_changed": "adaptive_validation",
            "sealed_reuse_after_adaptation": False,
        },
        "promotion": {"eligible_now": False, "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"v3_2_promotion_canary_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "plan_sha256": rows_sha,
        "manifest_sha256": manifest_sha,
        "slot_audit": audit,
        "preregistered_gates": PREREGISTERED_GATES,
        "decisions": {
            "contract_and_runtime_hash_freeze": "GO",
            "question_and_gold_authoring": "READY_FOR_SEPARATE_AUTHOR",
            "independent_human_review": "PENDING",
            "sealed_execution": "NO_GO_BEFORE_REVIEWED_IMMUTABLE_EXPORT",
            "canonical_promotion": "NO_GO",
            "frozen_blind": "NO_GO",
        },
        "not_performed": [
            "question_authoring",
            "gold_authoring",
            "canary_scoring",
            "canonical_promotion",
            "frozen_blind_access",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"v3_2_promotion_canary_contract_{report_sha}.json"
    write_immutable(report_path, report_bytes)

    for name, path in resolved.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed while freezing contract: {name}")
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
    parser = argparse.ArgumentParser(description="Freeze the v3.2 promotion canary contract")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(freeze_contract(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

