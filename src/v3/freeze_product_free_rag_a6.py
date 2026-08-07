from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl


FREEZER_VERSION = "product-free-rag-a6-freezer-v2"
MANIFEST_SCHEMA_VERSION = "product-free-rag-a6-freeze-manifest-v2"
EXPECTED_CANDIDATE_SCHEMA = "product-free-rag-a6-candidate-v3"
EXPECTED_EVALUATION_ROLE = (
    "product_a6_unexecuted_candidate_pending_human_review"
)
FROZEN_EVALUATION_ROLE = (
    "product_free_rag_a6_human_reviewed_first_one_shot"
)
APPROVAL_COLUMNS = (
    "question_approved",
    "answer_approved",
    "evidence_approved",
    "response_mode_approved",
)
TRUE_VALUES = {"1", "approve", "approved", "true", "y", "yes", "승인"}
MODEL_TAG = "qwen3-8b:ctx8192"
MODEL_BLOB_SHA256 = (
    "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
)

DEFAULT_CANDIDATES = Path(
    "data/v3/evaluation/product_free_rag_a6_candidate_v3_20260805.jsonl"
)
DEFAULT_PREFREEZE_MANIFEST = Path(
    "reports/v3/product_free_rag_a6_manifest_v3_20260805.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_RUNTIME_SNAPSHOT = Path(
    "data/v3/runtime/free_minimal_runtime_snapshot_v1.json"
)
DEFAULT_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/v3/evaluation")

FROZEN_CODE_PATHS = (
    Path("src/io_utils.py"),
    Path("src/v3/adjudicate_product_free_rag_a6.py"),
    Path("src/v3/build_product_free_rag_a6_candidate.py"),
    Path("src/v3/build_bm25.py"),
    Path("src/v3/build_corpus.py"),
    Path("src/v3/build_dense_pilot.py"),
    Path("src/v3/collect_details.py"),
    Path("src/v3/diagnose_product_candidate_assembly_ab.py"),
    Path("src/v3/diagnose_product_candidate_waterfall_missing32.py"),
    Path("src/v3/diagnose_product_evidence_pack_top8_ab.py"),
    Path("src/v3/diagnose_product_surface_coverage_pack.py"),
    Path("src/v3/diagnose_product_surface_retrieval_ab.py"),
    Path("src/v3/evaluate_hybrid.py"),
    Path("src/v3/evaluate_retrieval.py"),
    Path("src/v3/evaluate_retrieval_signals.py"),
    Path("src/v3/metadata_query.py"),
    Path("src/v3/product_candidate_identity.py"),
    Path("src/v3/product_evidence_pack.py"),
    Path("src/v3/product_free_rag.py"),
    Path("src/v3/product_minimal_verifier.py"),
    Path("src/v3/retrieve_v3.py"),
    Path("src/v3/run_product_free_rag_existing32.py"),
    Path("src/v3/run_product_free_rag_a6_one_shot.py"),
    Path("src/v3/schemas.py"),
    Path("src/v3/score_product_free_rag_a6.py"),
    Path("src/v3/score_evidence_reranker.py"),
    Path("src/v3/score_typed_evidence_ref_generalization.py"),
    Path("src/v3/select_evidence.py"),
    Path("src/v3/simple_evidence_refs.py"),
    Path("src/v3/simple_rag_minimal_verifier.py"),
    Path("src/v3/value_normalization.py"),
    Path("src/v3/freeze_product_free_rag_a6.py"),
    Path("tests/v3/test_freeze_product_free_rag_a6.py"),
    Path("tests/v3/test_adjudicate_product_free_rag_a6.py"),
    Path("tests/v3/test_metadata_query.py"),
    Path("tests/v3/test_product_free_rag.py"),
    Path("tests/v3/test_product_free_rag_architecture.py"),
    Path("tests/v3/test_run_product_free_rag_a6_one_shot.py"),
    Path("tests/v3/test_score_product_free_rag_a6.py"),
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def serialize_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return (
        "\n".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in sorted(rows, key=lambda item: item["slot_ordinal"])
        )
        + "\n"
    ).encode("utf-8")


def write_immutable(path: Path, value: bytes) -> None:
    if path.exists():
        if path.read_bytes() == value:
            return
        raise RuntimeError(f"immutable output already exists with different content: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _declared_artifacts(value: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        path = value.get("path")
        sha256 = value.get("sha256")
        if isinstance(path, str) and re.fullmatch(r"[0-9a-f]{64}", str(sha256)):
            found.append((path, str(sha256)))
        for child in value.values():
            found.extend(_declared_artifacts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_declared_artifacts(child))
    return found


def collect_runtime_artifact_paths(
    root: Path,
    runtime_snapshot_path: Path,
) -> list[Path]:
    snapshot = json.loads(runtime_snapshot_path.read_text(encoding="utf-8"))
    selected: dict[str, Path] = {}
    for item in snapshot.get("artifacts", []):
        path = _resolve(root, Path(item["path"]))
        expected_sha256 = str(item["sha256"])
        if not path.is_file() or sha256_path(path) != expected_sha256:
            raise RuntimeError(f"runtime snapshot artifact differs: {item['path']}")
        selected[_relative(root, path)] = path
        if item.get("role") not in {"bm25_manifest", "dense_manifest"}:
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for declared_path, declared_sha256 in _declared_artifacts(manifest):
            dependency = _resolve(root, Path(declared_path))
            if not dependency.is_file() or sha256_path(dependency) != declared_sha256:
                raise RuntimeError(
                    f"retrieval artifact differs from manifest: {declared_path}"
                )
            selected[_relative(root, dependency)] = dependency
    return [selected[key] for key in sorted(selected)]


def _approved(value: Any) -> bool:
    return str(value or "").strip().casefold() in TRUE_VALUES


def verify_model() -> None:
    completed = subprocess.run(
        ["ollama", "show", MODEL_TAG, "--modelfile"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"FROM .+sha256-([0-9a-f]{64})", completed.stdout)
    if match is None or match.group(1) != MODEL_BLOB_SHA256:
        raise RuntimeError("Ollama model blob differs from the Product A6 seal")
    if "PARAMETER num_ctx 8192" not in completed.stdout:
        raise RuntimeError("Product A6 requires Ollama num_ctx 8192")


def _validated_datetime(value: str, *, slot: int) -> str:
    text = value.strip()
    if not text:
        raise RuntimeError(f"slot {slot}: reviewed_at is required")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RuntimeError(f"slot {slot}: reviewed_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"slot {slot}: reviewed_at must include a timezone")
    return text


def load_review_decisions(
    path: Path,
    *,
    candidates: list[dict[str, Any]],
) -> dict[int, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 32:
        raise RuntimeError(f"review CSV must contain 32 rows, got {len(rows)}")
    by_slot: dict[int, dict[str, str]] = {}
    candidates_by_slot = {int(row["slot_ordinal"]): row for row in candidates}
    for raw in rows:
        try:
            slot = int(raw.get("slot_ordinal") or 0)
        except ValueError as exc:
            raise RuntimeError("review CSV has an invalid slot_ordinal") from exc
        if slot in by_slot or slot not in candidates_by_slot:
            raise RuntimeError(f"review CSV has an invalid or duplicate slot: {slot}")
        candidate = candidates_by_slot[slot]
        if raw.get("source_id") != candidate["source_id"]:
            raise RuntimeError(f"slot {slot}: source_id differs from candidate")
        if raw.get("question_text") != candidate["question_text"]:
            raise RuntimeError(f"slot {slot}: question_text differs from candidate")
        for column in APPROVAL_COLUMNS:
            if not _approved(raw.get(column)):
                raise RuntimeError(f"slot {slot}: {column} is not approved")
        if str(raw.get("review_decision") or "").strip().casefold() not in {
            "approve",
            "approved",
            "승인",
        }:
            raise RuntimeError(f"slot {slot}: review_decision is not approve")
        reviewer_id = str(raw.get("reviewer_id") or "").strip()
        rationale = str(raw.get("review_rationale") or "").strip()
        if not reviewer_id:
            raise RuntimeError(f"slot {slot}: reviewer_id is required")
        if not rationale:
            raise RuntimeError(f"slot {slot}: review_rationale is required")
        by_slot[slot] = {
            "reviewer_id": reviewer_id,
            "reviewed_at": _validated_datetime(
                str(raw.get("reviewed_at") or ""),
                slot=slot,
            ),
            "rationale": rationale,
        }
    if set(by_slot) != set(range(1, 33)):
        raise RuntimeError("review CSV must cover slots 1 through 32 exactly")
    return by_slot


def apply_human_reviews(
    candidates: list[dict[str, Any]],
    reviews: dict[int, dict[str, str]],
) -> list[dict[str, Any]]:
    frozen = []
    for row in candidates:
        slot = int(row["slot_ordinal"])
        if row.get("packet_schema_version") != EXPECTED_CANDIDATE_SCHEMA:
            raise RuntimeError(f"slot {slot}: unexpected candidate schema")
        if row.get("evaluation_role") != EXPECTED_EVALUATION_ROLE:
            raise RuntimeError(f"slot {slot}: unexpected evaluation role")
        if row.get("review", {}).get("status") != "pending":
            raise RuntimeError(f"slot {slot}: candidate review is not pending")
        if row.get("execution_allowed") or row.get("training_allowed"):
            raise RuntimeError(f"slot {slot}: candidate permissions were opened")
        review = reviews[slot]
        frozen.append(
            {
                **row,
                "author_status": "human_review_approved_frozen",
                "review": {
                    "status": "approved",
                    **review,
                },
                "human_review_decision": "approve",
                "sealed_scoring_allowed": True,
                "execution_allowed": True,
                "training_allowed": False,
                "evaluation_role": FROZEN_EVALUATION_ROLE,
            }
        )
    return frozen


def validate_prefreeze_manifest(
    prefreeze_manifest: dict[str, Any],
    *,
    candidate_sha256: str,
) -> dict[str, Any]:
    validation = prefreeze_manifest.get("validation") or {}
    if prefreeze_manifest.get("builder_version") != "product-free-rag-a6-candidate-builder-v3":
        raise RuntimeError("unexpected Product A6 candidate builder version")
    if prefreeze_manifest.get("packet_schema_version") != EXPECTED_CANDIDATE_SCHEMA:
        raise RuntimeError("unexpected Product A6 candidate manifest schema")
    if prefreeze_manifest.get("status") != "candidate_pending_human_review_execution_locked":
        raise RuntimeError("Product A6 candidate manifest is not review-pending")
    if prefreeze_manifest.get("outputs", {}).get("candidate", {}).get("sha256") != candidate_sha256:
        raise RuntimeError("candidate SHA differs from the prefreeze manifest")
    if validation.get("gate_pass") is not True:
        raise RuntimeError("prefreeze validation is not a clean pass")
    required_prefreeze_gates = {
        "rows_32",
        "sources_8_by_4",
        "questions_unique",
        "candidate_ids_unique",
        "exact_prior_question_overlap_zero",
        "exact_prior_evidence_overlap_zero",
        "citation_coordinates_exact",
        "execution_locked",
        "training_locked",
        "unsupported_requirements_4",
    }
    gates = validation.get("gates") or {}
    if not all(gates.get(name) is True for name in required_prefreeze_gates):
        raise RuntimeError("prefreeze validation gates are incomplete")
    if validation.get("prior_set_row_count") != 160:
        raise RuntimeError("prefreeze novelty baseline must contain 160 rows")
    permissions = prefreeze_manifest.get("permissions") or {}
    if not (
        permissions.get("execution_allowed") is False
        and permissions.get("training_allowed") is False
        and permissions.get("human_review_required_before_freeze") is True
    ):
        raise RuntimeError("prefreeze permissions are invalid")
    return validation


def audit_frozen_rows(
    rows: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_counts = Counter(row["source_id"] for row in rows)
    coverage_counts = Counter(
        tag for row in rows for tag in row.get("coverage_tags", [])
    )
    coordinate_failures = []
    evidence_count = 0
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
                    else str(chunk["display_text"])[
                        unit["start_char"] : unit["end_char"]
                    ]
                )
                if actual != unit["text"]:
                    coordinate_failures.append(
                        {
                            "slot_ordinal": row["slot_ordinal"],
                            "chunk_id": unit["chunk_id"],
                        }
                    )
    gates = {
        "row_count_32": len(rows) == 32,
        "slot_ordinals_exact": sorted(row["slot_ordinal"] for row in rows)
        == list(range(1, 33)),
        "candidate_ids_unique": len({row["candidate_id"] for row in rows}) == 32,
        "questions_unique": len({row["question_text"] for row in rows}) == 32,
        "source_matrix_8_by_4": len(source_counts) == 8
        and set(source_counts.values()) == {4},
        "requirements_61": sum(len(row["requirements"]) for row in rows) == 61,
        "evidence_units_62": evidence_count == 62,
        "evidence_coordinates_exact": not coordinate_failures,
        "unsupported_slots_exact": unsupported_slots == [6, 22, 29, 32],
        "metadata_answers_0": sum(
            row["expected_query_mode"] == "metadata"
            and row["expected_response_mode"] != "clarification"
            for row in rows
        )
        == 0,
        "clarification_0": coverage_counts["clarification"] == 0,
        "server_tables_0": sum(
            row["expected_server_rendered_table_count"] for row in rows
        )
        == 0,
        "all_human_approved": all(
            row["review"]["status"] == "approved"
            and row["human_review_decision"] == "approve"
            for row in rows
        ),
        "execution_open_once_frozen": all(
            row["sealed_scoring_allowed"] and row["execution_allowed"]
            for row in rows
        ),
        "training_locked": all(not row["training_allowed"] for row in rows),
    }
    return {
        "gate_pass": all(gates.values()),
        "gates": gates,
        "source_counts": dict(sorted(source_counts.items())),
        "coverage_counts": dict(sorted(coverage_counts.items())),
        "evidence_coordinate_failures": coordinate_failures,
    }


def freeze_a6(
    *,
    root: Path,
    candidates_path: Path,
    review_csv_path: Path,
    prefreeze_manifest_path: Path,
    chunks_path: Path,
    runtime_snapshot_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = root.resolve()
    candidates_path = _resolve(root, candidates_path)
    review_csv_path = _resolve(root, review_csv_path)
    prefreeze_manifest_path = _resolve(root, prefreeze_manifest_path)
    chunks_path = _resolve(root, chunks_path)
    runtime_snapshot_path = _resolve(root, runtime_snapshot_path)
    output_dir = _resolve(root, output_dir)
    if _relative(root, chunks_path) != DEFAULT_CHUNKS.as_posix():
        raise RuntimeError("Product A6 freeze requires the canonical chunk corpus")
    if _relative(root, runtime_snapshot_path) != DEFAULT_RUNTIME_SNAPSHOT.as_posix():
        raise RuntimeError("Product A6 freeze requires the canonical runtime snapshot")

    candidate_sha256 = sha256_path(candidates_path)
    prefreeze_manifest = json.loads(
        prefreeze_manifest_path.read_text(encoding="utf-8")
    )
    validate_prefreeze_manifest(
        prefreeze_manifest,
        candidate_sha256=candidate_sha256,
    )

    candidates = list(read_jsonl(candidates_path))
    reviews = load_review_decisions(review_csv_path, candidates=candidates)
    frozen_rows = apply_human_reviews(candidates, reviews)
    chunks_by_id = {row["chunk_id"]: row for row in read_jsonl(chunks_path)}
    audit = audit_frozen_rows(frozen_rows, chunks_by_id=chunks_by_id)
    if not audit["gate_pass"]:
        raise RuntimeError(f"frozen row audit failed: {audit['gates']}")

    runtime_snapshot = json.loads(
        runtime_snapshot_path.read_text(encoding="utf-8")
    )
    artifact_paths = collect_runtime_artifact_paths(root, runtime_snapshot_path)
    temporal_overlay_path = _resolve(root, DEFAULT_TEMPORAL_OVERLAY)
    if not temporal_overlay_path.is_file():
        raise RuntimeError(f"missing temporal overlay: {DEFAULT_TEMPORAL_OVERLAY}")
    sealed_paths = {
        _relative(root, path): path
        for path in (
            *(_resolve(root, path) for path in FROZEN_CODE_PATHS),
            candidates_path,
            review_csv_path,
            prefreeze_manifest_path,
            runtime_snapshot_path,
            temporal_overlay_path,
            *artifact_paths,
        )
    }
    frozen_hashes = [
        {
            "path": relative_path,
            "sha256": sha256_path(path),
        }
        for relative_path, path in sorted(sealed_paths.items())
    ]

    verify_model()
    frozen_bytes = serialize_jsonl(frozen_rows)
    frozen_sha256 = hashlib.sha256(frozen_bytes).hexdigest()
    frozen_path = output_dir / f"product_free_rag_a6_frozen_{frozen_sha256}.jsonl"
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "freezer_version": FREEZER_VERSION,
        "status": "human_reviewed_frozen_ready_for_exactly_one_execution",
        "candidate_input": {
            "path": _relative(root, candidates_path),
            "sha256": candidate_sha256,
        },
        "human_review": {
            "path": _relative(root, review_csv_path),
            "sha256": sha256_path(review_csv_path),
            "approved_rows": 32,
            "reviewer_ids": sorted(
                {review["reviewer_id"] for review in reviews.values()}
            ),
        },
        "prefreeze": {
            "manifest": {
                "path": _relative(root, prefreeze_manifest_path),
                "sha256": sha256_path(prefreeze_manifest_path),
            },
        },
        "frozen_set": {
            "path": _relative(root, frozen_path),
            "sha256": frozen_sha256,
            "row_count": 32,
        },
        "model": {
            "tag": MODEL_TAG,
            "blob_sha256": MODEL_BLOB_SHA256,
            "num_ctx": 8192,
        },
        "pipeline": {
            "name": "product_free_rag_v1",
            "runtime_snapshot": _relative(root, runtime_snapshot_path),
            "retrieval": "BM25 top20 plus BGE-M3 top20 union",
            "candidate_augmentation": "corpus_metadata_identity_shortlist",
            "reranker": "BGE reranker top8 parent_max2",
            "evidence_units": "explicit_question_surface E/T refs max8",
            "generation_calls": 1,
            "verifier": "product_minimal_verifier",
            "verifier_extensions": [
                "subject_evidence_binding",
                "question_surface_responsiveness",
                "redundant_same_subject_pruning",
            ],
            "generic_server_clarification": "bounded_underspecified_question_guard",
            "execution_semantics": (
                "durable_start_then_at_most_once_no_retry_after_indeterminate_interrupt"
            ),
        },
        "permissions": {
            "sealed_scoring_allowed": True,
            "execution_allowed": True,
            "training_allowed": False,
            "maximum_execution_attempts": 1,
            "rerun_after_results_opened": False,
        },
        "audit": audit,
        "frozen_hashes": sorted(frozen_hashes, key=lambda item: item["path"]),
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output_dir / f"product_free_rag_a6_freeze_manifest_{manifest_sha256}.json"
    write_immutable(frozen_path, frozen_bytes)
    write_immutable(manifest_path, manifest_bytes)
    if sha256_path(candidates_path) != candidate_sha256:
        raise RuntimeError("candidate changed during freeze")
    if sha256_path(frozen_path) != frozen_sha256:
        raise RuntimeError("frozen set changed during freeze")
    return {
        "frozen_set": {
            "path": _relative(root, frozen_path),
            "sha256": frozen_sha256,
        },
        "freeze_manifest": {
            "path": _relative(root, manifest_path),
            "sha256": manifest_sha256,
        },
        "permissions": manifest["permissions"],
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the independently reviewed Product Free RAG A6 set"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--prefreeze-manifest", type=Path, default=DEFAULT_PREFREEZE_MANIFEST)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--runtime-snapshot", type=Path, default=DEFAULT_RUNTIME_SNAPSHOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(
        json.dumps(
            freeze_a6(
                root=args.root,
                candidates_path=args.candidates,
                review_csv_path=args.review_csv,
                prefreeze_manifest_path=args.prefreeze_manifest,
                chunks_path=args.chunks,
                runtime_snapshot_path=args.runtime_snapshot,
                output_dir=args.output_dir,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
