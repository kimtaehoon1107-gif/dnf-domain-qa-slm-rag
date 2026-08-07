from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable


FINALIZER_VERSION = "route-type-pilot-finalizer-v3.2.0"
REPORT_SCHEMA_VERSION = "route-type-pilot-final-report-v3.2"
MANIFEST_SCHEMA_VERSION = "route-type-pilot-final-manifest-v3.2"
CANONICAL_ROUTER_SHA256 = (
    "bc380e735d933d9781228480b5066cff11df2cff2f704bdb242f37dd0bd25a7b"
)

DEFAULT_SIGNAL_A_REPORT = Path(
    "reports/v3/route_type_signal_a_pilot_"
    "77032257a09acf3e8c3362035d593b0dfbde6632b734cb11f716b1592c5d755a.json"
)
DEFAULT_SIGNAL_A_MANIFEST = Path(
    "data/v3/router/route_type_signal_a_pilot_manifest_"
    "fc045e8fbcc3890a0201a546f43057ac1ab836a7f4bd6041971495c6c0ff1874.json"
)
DEFAULT_SIGNAL_B_REPORT = Path(
    "reports/v3/route_type_signal_b_pilot_"
    "60f7141535c3d97ac123f994a2bd7d3805947fb753bffcb7354896dddfe95e4b.json"
)
DEFAULT_SIGNAL_B_MANIFEST = Path(
    "data/v3/router/route_type_signal_b_pilot_manifest_"
    "317da1263a941d01add22f4723daedc7955645be18829e8e567e296559aa3d72.json"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_final_report(
    signal_a: dict[str, Any], signal_b: dict[str, Any], router_sha256: str
) -> dict[str, Any]:
    if signal_a["decisions"]["signal_a_prevalidation"] != "NO-GO":
        raise RuntimeError("Signal A is not a preserved NO-GO")
    if signal_b["decisions"]["signal_b_prevalidation"] != "NO-GO":
        raise RuntimeError("Signal B is not a preserved NO-GO")
    if router_sha256 != CANONICAL_ROUTER_SHA256:
        raise RuntimeError("Canonical question router was not restored")
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "cycle_decision": "NO-GO",
        "canonical_router": {
            "decision": "RETAIN_BASELINE",
            "sha256": router_sha256,
            "experimental_route_type_change_promoted": False,
        },
        "signal_a": {
            "decision": "NO-GO_DEVELOPMENT_ONLY",
            "canary_32": signal_a["signal_a_canary_32"],
            "development_63": signal_a["development_63"],
            "latency": signal_a["single_question_latency"],
        },
        "signal_b": {
            "decision": "NO-GO_DEVELOPMENT_ONLY",
            "entry_reason": "signal_a_overdecomposition_measured",
            "canary_32": signal_b["signal_b_canary_32"],
            "development_63": signal_b["development_63"],
            "latency": signal_b["single_question_latency"],
        },
        "routing_order": {
            "answerability_or_reject_first": True,
            "answer_target_analysis_after_answerability_only": True,
            "broad_search_before_answerability": False,
        },
        "scope_confirmation": {
            "new_store_expansion_implemented": False,
            "broad_search_fallback_implemented": False,
            "new_field_or_intent_keyword_rules_added": 0,
            "signal_b_promoted_to_runtime": False,
            "claim_coverage_changed": False,
            "retrieval_changed": False,
            "verify_changed": False,
            "questions_or_gold_modified": False,
            "individual_adaptive_failures_inspected": False,
            "new_canary_executed": False,
            "frozen_blind_accessed": False,
        },
        "next_gate": {
            "new_40_canary_authoring": "NO-GO",
            "new_40_canary_execution": "NO-GO",
            "reason": "Neither grammar-only Signal A nor top-chunk Signal B passed prevalidation",
            "allowed_next_research_candidate": "separate_semantic_or_llm_route_type_ab_without_training",
        },
    }


def finalize(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "signal_a_report": root / DEFAULT_SIGNAL_A_REPORT,
        "signal_a_manifest": root / DEFAULT_SIGNAL_A_MANIFEST,
        "signal_b_report": root / DEFAULT_SIGNAL_B_REPORT,
        "signal_b_manifest": root / DEFAULT_SIGNAL_B_MANIFEST,
        "canonical_question_router": root / "src/v3/question_router.py",
        "signal_a_source": root / "src/v3/answer_target_router.py",
        "signal_b_source": root / "src/v3/answer_target_coverage.py",
        "signal_a_contract": root / "docs/v3/route_type_decomposition_pilot.md",
        "signal_b_contract": root / "docs/v3/route_type_signal_b_pilot.md",
        "finalizer_source": root / "src/v3/finalize_route_type_pilot.py",
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    with input_paths["signal_a_report"].open(encoding="utf-8") as handle:
        signal_a = json.load(handle)
    with input_paths["signal_b_report"].open(encoding="utf-8") as handle:
        signal_b = json.load(handle)
    report = build_final_report(
        signal_a, signal_b, input_hashes["canonical_question_router"]
    )
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / f"route_type_pilot_final_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "report": {"path": _relative(root, report_path), "sha256": report_sha},
        "cycle_decision": report["cycle_decision"],
        "questions_or_gold_in_report": False,
        "individual_case_rows_written": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        root
        / "data/v3/router"
        / f"route_type_pilot_final_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Final pilot input changed: {name}")
    return {
        "cycle_decision": report["cycle_decision"],
        "canonical_router_sha256": input_hashes["canonical_question_router"],
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize route-type pilot decision")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(finalize(root=parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
