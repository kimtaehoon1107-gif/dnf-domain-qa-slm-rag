from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.score_typed_evidence_ref_generalization import (
    NORMALIZATION_CONTRACT,
    SCORER_VERSION,
)


FREEZER_VERSION = "typed-evidence-ref-generalization-freezer-v1"
MANIFEST_SCHEMA_VERSION = "typed-evidence-ref-generalization-seal-manifest-v1"
DEFAULT_CANDIDATES = Path(
    "data/review/typed_evidence_ref_generalization_candidate_64.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BASELINE_MANIFEST = Path(
    "reports/v3/typed_evidence_ref_baseline_freeze_manifest.json"
)
DEFAULT_INSTRUCTION = Path("docs/v3/generalization_64_seal_and_run.md")
HONEST_UNSUPPORTED_SLOTS = [7, 15, 23, 31, 39, 47, 55, 63]
NEW_CODE_PATHS = (
    Path("src/v3/score_typed_evidence_ref_generalization.py"),
    Path("src/v3/run_typed_evidence_ref_generalization_one_shot.py"),
    Path("src/v3/freeze_typed_evidence_ref_generalization.py"),
    Path("tools/typed_review_workbook/build.mjs"),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def approve_for_seal(
    rows: list[dict[str, Any]],
    *,
    reviewer_id: str,
    reviewed_at: str,
) -> list[dict[str, Any]]:
    approved = []
    for row in rows:
        if row["execution_allowed"] or row["training_allowed"]:
            raise RuntimeError("candidate permissions were opened before sealing")
        approved.append(
            {
                **row,
                "author_status": "human_review_approved_sealed",
                "review": {
                    "status": "approved",
                    "reviewer_id": reviewer_id,
                    "reviewed_at": reviewed_at,
                    "rationale": "사용자가 64문항 전체 감수 완료 및 one-shot 봉인을 승인함",
                },
                "human_review_decision": "approve",
                "human_reviewer_id": reviewer_id,
                "human_reviewed_at": reviewed_at,
                "sealed_scoring_allowed": True,
                "execution_allowed": True,
                "training_allowed": False,
                "evaluation_role": (
                    "independent_human_reviewed_holdout_first_one_shot"
                ),
            }
        )
    return approved


def audit_rows(
    rows: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_counts = Counter(row["source_id"] for row in rows)
    dimension_counts = Counter(row["primary_dimension"] for row in rows)
    evidence_count = 0
    coordinate_failures = []
    unsupported_slots = []
    for row in rows:
        if any(
            requirement["expected_status"] == "unsupported"
            for requirement in row["requirements"]
        ):
            unsupported_slots.append(row["slot_ordinal"])
        for requirement in row["requirements"]:
            for unit in requirement["acceptable_evidence_units"]:
                evidence_count += 1
                chunk = chunks_by_id.get(unit["chunk_id"])
                actual = (
                    None
                    if chunk is None
                    else chunk["display_text"][unit["start_char"] : unit["end_char"]]
                )
                if actual != unit["text"]:
                    coordinate_failures.append(
                        {
                            "slot_ordinal": row["slot_ordinal"],
                            "chunk_id": unit["chunk_id"],
                            "start_char": unit["start_char"],
                            "end_char": unit["end_char"],
                        }
                    )
    questions = [" ".join(row["question_text"].split()).casefold() for row in rows]
    gates = {
        "row_count_64": len(rows) == 64,
        "source_matrix_8_by_8": len(source_counts) == 8
        and set(source_counts.values()) == {8},
        "dimension_matrix_8_by_8": len(dimension_counts) == 8
        and set(dimension_counts.values()) == {8},
        "evidence_coordinate_count_90": evidence_count == 90,
        "evidence_coordinates_exact": not coordinate_failures,
        "question_duplicates_zero": len(questions) == len(set(questions)),
        "honest_unsupported_slots_exact": unsupported_slots
        == HONEST_UNSUPPORTED_SLOTS,
        "all_human_approved": all(
            row["human_review_decision"] == "approve"
            and row["review"]["status"] == "approved"
            for row in rows
        ),
        "scoring_and_execution_open": all(
            row["sealed_scoring_allowed"] and row["execution_allowed"]
            for row in rows
        ),
        "training_locked": all(not row["training_allowed"] for row in rows),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "dimension_counts": dict(sorted(dimension_counts.items())),
        "evidence_coordinate_count": evidence_count,
        "coordinate_failures": coordinate_failures,
        "honest_unsupported_slots": unsupported_slots,
    }


def freeze_generalization_set(
    *,
    root: Path,
    candidate_path: Path,
    chunks_path: Path,
    baseline_manifest_path: Path,
    instruction_path: Path,
    reviewer_id: str,
    reviewed_at: str,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    candidate_path = resolve(candidate_path)
    chunks_path = resolve(chunks_path)
    baseline_manifest_path = resolve(baseline_manifest_path)
    instruction_path = resolve(instruction_path)
    candidate_sha = file_sha256(candidate_path)
    baseline_manifest_sha = file_sha256(baseline_manifest_path)
    baseline_manifest = json.loads(
        baseline_manifest_path.read_text(encoding="utf-8")
    )

    baseline_code_hashes = baseline_manifest["code_files"]
    code_mismatches = []
    for row in baseline_code_hashes:
        actual = file_sha256(root / row["path"])
        if actual != row["sha256"]:
            code_mismatches.append(
                {"path": row["path"], "expected": row["sha256"], "actual": actual}
            )
    if code_mismatches:
        raise RuntimeError(f"baseline code differs before seal: {code_mismatches}")

    candidates = read_jsonl(candidate_path)
    sealed_rows = approve_for_seal(
        candidates,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )
    chunks = {row["chunk_id"]: row for row in read_jsonl(chunks_path)}
    audit = audit_rows(sealed_rows, chunks_by_id=chunks)
    if not audit["gate_pass"]:
        raise RuntimeError(f"sealed row audit failed: {audit['gates']}")

    sealed_bytes = _serialize_jsonl(sealed_rows, lambda row: row["slot_ordinal"])
    sealed_sha = _sha256_bytes(sealed_bytes)
    sealed_path = (
        root
        / "data/v3/evaluation"
        / f"typed_evidence_ref_generalization_64_sealed_{sealed_sha}.jsonl"
    )
    write_immutable(sealed_path, sealed_bytes)

    new_code_hashes = [
        {"path": path.as_posix(), "sha256": file_sha256(root / path)}
        for path in NEW_CODE_PATHS
    ]
    frozen_hashes_by_path = {
        row["path"]: row
        for row in [
            *baseline_code_hashes,
            *baseline_manifest["corpus_and_index_inputs"],
            *new_code_hashes,
            {
                "path": _relative(root, instruction_path),
                "sha256": file_sha256(instruction_path),
            },
            {
                "path": _relative(root, baseline_manifest_path),
                "sha256": baseline_manifest_sha,
            },
        ]
    }
    arm_inputs = {
        "chunks": next(
            row
            for row in baseline_manifest["corpus_and_index_inputs"]
            if row["path"].endswith(".jsonl") and "chunks_dnf_official_v3.1_" in row["path"]
        ),
        "documents": next(
            row
            for row in baseline_manifest["corpus_and_index_inputs"]
            if "documents_dnf_official_detail" in row["path"]
        ),
        "temporal": next(
            row
            for row in baseline_manifest["corpus_and_index_inputs"]
            if "global_temporal_overlay" in row["path"]
        ),
        "table_facts": next(
            row
            for row in baseline_manifest["corpus_and_index_inputs"]
            if "table_atomic_facts" in row["path"]
        ),
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "freezer_version": FREEZER_VERSION,
        "status": "sealed_human_reviewed_ready_for_exactly_one_execution",
        "sealed_at": _now(),
        "review": {
            "decision": "approve_64_of_64",
            "reviewer_id": reviewer_id,
            "reviewed_at": reviewed_at,
            "human_rejudication_after_run_allowed": "separate_addendum_only",
        },
        "candidate_input": {
            "path": _relative(root, candidate_path),
            "sha256": candidate_sha,
        },
        "sealed_set": {
            "path": _relative(root, sealed_path),
            "sha256": sealed_sha,
            "row_count": len(sealed_rows),
            "source_by_dimension_matrix": "8_sources_x_8_dimensions",
            "honest_unsupported_count": len(HONEST_UNSUPPORTED_SLOTS),
            "honest_unsupported_slots": HONEST_UNSUPPORTED_SLOTS,
            "evidence_coordinate_count": audit["evidence_coordinate_count"],
        },
        "corpus": {
            "path": _relative(root, chunks_path),
            "sha256": file_sha256(chunks_path),
        },
        "baseline_freeze_manifest": {
            "path": _relative(root, baseline_manifest_path),
            "sha256": baseline_manifest_sha,
        },
        "model": {
            "requested_tag": "qwen3-8b:ctx8192",
            "ollama_blob_sha256": baseline_manifest["model"][
                "ollama_blob_sha256"
            ],
            "num_ctx": 8192,
        },
        "pipeline": baseline_manifest["arm"],
        "arm_inputs": arm_inputs,
        "scoring": {
            "scorer_version": SCORER_VERSION,
            "normalization_contract": NORMALIZATION_CONTRACT,
            "headline_metric": "automatic_gold_value_complete_fixed_denominator",
            "secondary_metric": "automatic_all_evidence_spans_hit_fixed_denominator",
            "manual_credit_may_not_override_headline": True,
            "preregistered_gates": {
                "generation_error_count": 0,
                "honest_unsupported_false_full_count": 0,
                "gold_value_complete_target": "report_observed_value_without_posthoc_lowering",
            },
        },
        "permissions": {
            "sealed_scoring_allowed": True,
            "execution_allowed": True,
            "training_allowed": False,
            "maximum_execution_attempts": 1,
            "rerun_after_results_opened": False,
        },
        "audit": audit,
        "frozen_hashes": [
            frozen_hashes_by_path[path] for path in sorted(frozen_hashes_by_path)
        ],
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        root
        / "data/v3/evaluation"
        / f"typed_evidence_ref_generalization_64_seal_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    if file_sha256(candidate_path) != candidate_sha:
        raise RuntimeError("candidate changed during sealing")
    if file_sha256(sealed_path) != sealed_sha:
        raise RuntimeError("sealed set changed during sealing")
    return {
        "sealed_set": {
            "path": _relative(root, sealed_path),
            "sha256": sealed_sha,
        },
        "seal_manifest": {
            "path": _relative(root, manifest_path),
            "sha256": manifest_sha,
        },
        "candidate_sha256": candidate_sha,
        "audit": audit,
        "permissions": manifest["permissions"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Approve and seal the typed evidence-ref 64-question holdout"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument(
        "--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST
    )
    parser.add_argument("--instruction", type=Path, default=DEFAULT_INSTRUCTION)
    parser.add_argument("--reviewer-id", default="kimdh")
    parser.add_argument("--reviewed-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(
        json.dumps(
            freeze_generalization_set(
                root=args.root,
                candidate_path=args.candidates,
                chunks_path=args.chunks,
                baseline_manifest_path=args.baseline_manifest,
                instruction_path=args.instruction,
                reviewer_id=args.reviewer_id,
                reviewed_at=args.reviewed_at or _now(),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
