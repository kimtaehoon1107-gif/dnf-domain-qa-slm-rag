from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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


FREEZER_VERSION = "simple-rag-untouched32-freezer-20260728-v1"
EXPECTED_CANDIDATE_SHA256 = (
    "2a131c3425e2c8d7affc848ab5b335d31173aa6fd01f73f985b5e851157a718a"
)
MODEL_TAG = "qwen3-8b:ctx8192"
MODEL_DIGEST = (
    "e737aff7b8d457961517eb4895c0c1c597867d943a7f8dc82965eb826de324b8"
)
MODEL_BLOB_SHA256 = (
    "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
)
LEGACY_SOURCE_COMMIT = "f34eec002196fb008b411da76d9d8f4772a6dc3c"
HONEST_UNSUPPORTED_SLOTS = [4, 16, 24, 32]

DEFAULT_CANDIDATES = Path(
    "data/review/typed_evidence_ref_untouched32_candidate_20260728.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_LEGACY_SOURCE_ROOT = Path("C:/t/dnfv2")
FROZEN_COMPONENTS = (
    Path("src/v3/simple_rag_incremental_guards.py"),
    Path("src/v3/simple_rag_minimal_verifier.py"),
    Path("src/v3/run_simple_rag_minimal_verifier_new_claim32_ab.py"),
)


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _verify_model() -> None:
    completed = subprocess.run(
        ["ollama", "show", MODEL_TAG, "--modelfile"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"FROM .+sha256-([0-9a-f]{64})", completed.stdout)
    if match is None or match.group(1) != MODEL_BLOB_SHA256:
        raise RuntimeError("Ollama model blob differs from the frozen model")
    if "PARAMETER num_ctx 8192" not in completed.stdout:
        raise RuntimeError("Ollama model num_ctx is not 8192")


def _approve(
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
                    "rationale": (
                        "사용자가 untouched 32문항과 slot 11 교체안을 확인하고 "
                        "최초 테스트 실행을 승인함"
                    ),
                },
                "human_review_decision": "approve",
                "human_reviewer_id": reviewer_id,
                "human_reviewed_at": reviewed_at,
                "sealed_scoring_allowed": True,
                "execution_allowed": True,
                "training_allowed": False,
                "evaluation_role": (
                    "human_reviewed_untouched32_first_one_shot_not_parent_blind"
                ),
            }
        )
    return approved


def _audit(
    rows: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_counts = Counter(row["source_id"] for row in rows)
    dimension_counts = Counter(row["primary_dimension"] for row in rows)
    requirement_count = 0
    evidence_count = 0
    unsupported_slots = []
    coordinate_failures = []
    for row in rows:
        if any(
            requirement["expected_status"] == "unsupported"
            for requirement in row["requirements"]
        ):
            unsupported_slots.append(row["slot_ordinal"])
        for requirement in row["requirements"]:
            requirement_count += 1
            for unit in requirement["acceptable_evidence_units"]:
                evidence_count += 1
                chunk = chunks_by_id.get(unit["chunk_id"])
                actual = (
                    None
                    if chunk is None
                    else chunk["display_text"][
                        unit["start_char"] : unit["end_char"]
                    ]
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
        "row_count_32": len(rows) == 32,
        "requirement_count_53": requirement_count == 53,
        "evidence_coordinate_count_49": evidence_count == 49,
        "source_matrix_8_by_4": len(source_counts) == 8
        and set(source_counts.values()) == {4},
        "dimension_matrix_8_by_4": len(dimension_counts) == 8
        and set(dimension_counts.values()) == {4},
        "evidence_coordinates_exact": not coordinate_failures,
        "question_duplicates_zero": len(questions) == len(set(questions)),
        "honest_unsupported_slots_exact": (
            unsupported_slots == HONEST_UNSUPPORTED_SLOTS
        ),
        "as_of_2026_07_28": all(row["as_of"] == "2026-07-28" for row in rows),
        "all_human_approved": all(
            row["human_review_decision"] == "approve"
            and row["review"]["status"] == "approved"
            for row in rows
        ),
        "execution_open": all(row["execution_allowed"] for row in rows),
        "training_locked": all(not row["training_allowed"] for row in rows),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "dimension_counts": dict(sorted(dimension_counts.items())),
        "requirement_count": requirement_count,
        "evidence_coordinate_count": evidence_count,
        "coordinate_failures": coordinate_failures,
        "honest_unsupported_slots": unsupported_slots,
    }


def freeze(
    *,
    root: Path,
    candidates: Path,
    chunks: Path,
    legacy_source_root: Path,
    reviewer_id: str,
    reviewed_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    candidates = (root / candidates).resolve() if not candidates.is_absolute() else candidates
    chunks = (root / chunks).resolve() if not chunks.is_absolute() else chunks
    legacy_source_root = legacy_source_root.resolve()

    candidate_sha = file_sha256(candidates)
    if candidate_sha != EXPECTED_CANDIDATE_SHA256:
        raise RuntimeError(
            f"candidate SHA mismatch: {candidate_sha} != {EXPECTED_CANDIDATE_SHA256}"
        )
    if (
        subprocess.run(
            ["git", "-C", str(legacy_source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        != LEGACY_SOURCE_COMMIT
    ):
        raise RuntimeError("legacy source worktree is not at the frozen commit")
    _verify_model()

    sealed_rows = _approve(
        read_jsonl(candidates),
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )
    chunks_by_id = {row["chunk_id"]: row for row in read_jsonl(chunks)}
    audit = _audit(sealed_rows, chunks_by_id=chunks_by_id)
    if not audit["gate_pass"]:
        raise RuntimeError(f"untouched32 audit failed: {audit['gates']}")

    sealed_bytes = _serialize_jsonl(sealed_rows, lambda row: row["slot_ordinal"])
    sealed_sha = _sha256_bytes(sealed_bytes)
    sealed_path = (
        root
        / "data/v3/evaluation"
        / f"simple_rag_untouched32_sealed_{sealed_sha}.jsonl"
    )
    write_immutable(sealed_path, sealed_bytes)

    component_hashes = [
        {"path": path.as_posix(), "sha256": file_sha256(root / path)}
        for path in FROZEN_COMPONENTS
    ]
    legacy_simple_rag = legacy_source_root / "src/v3/simple_domain_rag.py"
    manifest = {
        "manifest_version": "simple-rag-untouched32-seal-v1",
        "freezer_version": FREEZER_VERSION,
        "status": "sealed_human_reviewed_ready_for_exactly_one_execution",
        "sealed_at": _now(),
        "evaluation_role": (
            "human_reviewed_untouched32_first_one_shot_not_parent_blind"
        ),
        "review": {
            "decision": "approve_32_of_32",
            "reviewer_id": reviewer_id,
            "reviewed_at": reviewed_at,
            "post_run_gold_mutation_allowed": False,
        },
        "candidate_input": {
            "path": _relative(root, candidates),
            "sha256": candidate_sha,
        },
        "sealed_set": {
            "path": _relative(root, sealed_path),
            "sha256": sealed_sha,
            "row_count": 32,
        },
        "model": {
            "tag": MODEL_TAG,
            "digest": MODEL_DIGEST,
            "blob_sha256": MODEL_BLOB_SHA256,
            "num_ctx": 8192,
        },
        "pipeline": {
            "name": "simple-rag-v2-plus-b1-b3-b4",
            "legacy_source_commit": LEGACY_SOURCE_COMMIT,
            "retrieval_depth": 20,
            "rerank_depth": 5,
            "included_stages": [
                "A1_subject_period_identity",
                "A2_relation_value_colocation",
                "A3_explicit_temporal_conflict",
                "B1_v2_table_subject_attribute_value_guard",
                "B3_unique_whitespace_quote_recovery",
                "B4_v2_normalized_factual_value_verifier",
            ],
        },
        "inputs": {
            "chunks": {
                "path": _relative(root, chunks),
                "sha256": file_sha256(chunks),
            },
            "legacy_simple_rag": {
                "path": legacy_simple_rag.as_posix(),
                "sha256": file_sha256(legacy_simple_rag),
            },
            "components": component_hashes,
        },
        "permissions": {
            "execution_allowed": True,
            "training_allowed": False,
            "maximum_execution_attempts": 1,
            "rerun_after_results_opened": False,
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        root
        / "data/v3/evaluation"
        / f"simple_rag_untouched32_seal_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    return {
        "sealed_set": {
            "path": _relative(root, sealed_path),
            "sha256": sealed_sha,
        },
        "seal_manifest": {
            "path": _relative(root, manifest_path),
            "sha256": manifest_sha,
        },
        "audit": audit,
        "permissions": manifest["permissions"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument(
        "--legacy-source-root", type=Path, default=DEFAULT_LEGACY_SOURCE_ROOT
    )
    parser.add_argument("--reviewer-id", default="kimdh")
    parser.add_argument("--reviewed-at")
    args = parser.parse_args()
    print(
        json.dumps(
            freeze(
                root=args.root,
                candidates=args.candidates,
                chunks=args.chunks,
                legacy_source_root=args.legacy_source_root,
                reviewer_id=args.reviewer_id,
                reviewed_at=args.reviewed_at or _now(),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
