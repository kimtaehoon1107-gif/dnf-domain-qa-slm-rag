from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


EVALUATOR_VERSION = "requirement-surface-query-canary-ab-v1.0.0"
AUTHORIZATION_SCHEMA_VERSION = "requirement-surface-query-canary-run-authorization-v1"
CASE_SCHEMA_VERSION = "requirement-surface-query-canary-ab-case-v1"
REPORT_SCHEMA_VERSION = "requirement-surface-query-canary-ab-report-v1"
LEDGER_SCHEMA_VERSION = "requirement-surface-query-canary-execution-ledger-v1"

EXPECTED_ROWS = 32
EXPECTED_SOURCES = (
    "dnf_notice",
    "dnf_update",
    "dnf_event",
    "dnf_game_guide",
    "dnf_faq",
    "dnf_account_policy",
    "dnf_seria_shop",
    "dnf_monthly_item",
)
POSITIVE_STRATA = frozenset({"positive_coordination_a", "positive_coordination_b"})
CONTROL_STRATA = frozenset({"single_requirement_control", "three_requirement_control"})
DECISION_INPUT_FIELDS = ("candidate_id", "question_text")

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_REVIEWED_MANIFEST_GLOB = (
    "data/v3/evaluation/requirement_surface_query_canary_reviewed_manifest_*.json"
)


class PairRunner(Protocol):
    def run_pair(self, decision_input: dict[str, str]) -> dict[str, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 6) if total else None,
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_reviewed_export(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    reviewed_sha256: str,
) -> None:
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"Reviewed packet must contain exactly {EXPECTED_ROWS} rows")
    if [row.get("slot_ordinal") for row in rows] != list(range(1, EXPECTED_ROWS + 1)):
        raise RuntimeError("Reviewed packet slot ordinals must be exactly 1..32")
    if len({row.get("candidate_id") for row in rows}) != EXPECTED_ROWS:
        raise RuntimeError("Reviewed packet candidate IDs must be unique")
    for row in rows:
        if row.get("human_review_decision") != "approve":
            raise RuntimeError("Every reviewed row must be approved")
        if not row.get("human_reviewer_id") or not row.get("human_reviewed_at"):
            raise RuntimeError("Every reviewed row needs reviewer ID and review timestamp")
        if row.get("review_status") != "user_full_review_approved":
            raise RuntimeError("Reviewed row is missing immutable approval status")
        for field in (
            "sealed_scoring_allowed",
            "final_benchmark_eligible",
            "independent_holdout_claim_allowed",
            "training_allowed",
        ):
            if row.get(field) is not False:
                raise RuntimeError(f"Reviewed export must retain {field}=false")

    counts = Counter((row["source_id"], row["stratum"]) for row in rows)
    expected = {
        (source, stratum): 1
        for source in EXPECTED_SOURCES
        for stratum in sorted(POSITIVE_STRATA | CONTROL_STRATA)
    }
    if counts != expected:
        raise RuntimeError("Reviewed packet is not the preregistered 8-source x 4-stratum layout")

    review = manifest.get("review") or {}
    execution = manifest.get("execution") or {}
    exported = manifest.get("reviewed_export") or {}
    if exported.get("sha256") != reviewed_sha256 or exported.get("row_count") != EXPECTED_ROWS:
        raise RuntimeError("Reviewed manifest does not identify this reviewed packet")
    if review.get("progress") != {"approved": 32, "rejected": 0, "pending": 0}:
        raise RuntimeError("Reviewed manifest does not record 32 approvals")
    if execution.get("sealed_run_count_allowed") != 0:
        raise RuntimeError("Reviewed export alone must not authorize a scoring run")
    if execution.get("sealed_scoring_allowed") is not False:
        raise RuntimeError("Reviewed export must keep scoring blocked")


def _runtime_provenance(root: Path, planner_model: str) -> dict[str, Any]:
    from src.v3.gradio_backbone_demo import (
        ASSEMBLER_MANIFEST,
        CANONICAL_RUNTIME_POINTER,
        GLOBAL_TEMPORAL_OVERLAY,
        TABLE_INDEX_MANIFEST,
    )
    from src.v3.score_evidence_reranker import MAX_LENGTH, MODEL_NAME, MODEL_REVISION
    from src.v3.retrieve_v3 import DEFAULT_BM25_MANIFEST, DEFAULT_DENSE_MANIFEST

    runtime_pointer_path = root / CANONICAL_RUNTIME_POINTER
    runtime_pointer = _load_json(runtime_pointer_path)
    runtime_manifest_path = root / runtime_pointer["manifest"]["path"]
    bm25_manifest_path = root / DEFAULT_BM25_MANIFEST
    dense_manifest_path = root / DEFAULT_DENSE_MANIFEST
    bm25_manifest = _load_json(bm25_manifest_path)
    dense_manifest = _load_json(dense_manifest_path)
    table_manifest_path = root / TABLE_INDEX_MANIFEST
    table_manifest = _load_json(table_manifest_path)

    paths = {
        "evaluator_source": Path(__file__).resolve(),
        "surface_query_source": root / "src/v3/requirement_surface_query.py",
        "entity_anchor_source": root / "src/v3/requirement_entity_anchor.py",
        "demo_runtime_source": root / "src/v3/gradio_backbone_demo.py",
        "planner_source": root / "src/v3/evaluate_semantic_requirement_planner.py",
        "chunks": root / DEFAULT_CHUNKS,
        "documents": root / DEFAULT_DOCUMENTS,
        "assembler_manifest": root / ASSEMBLER_MANIFEST,
        "canonical_runtime_pointer": runtime_pointer_path,
        "canonical_runtime_manifest": runtime_manifest_path,
        "temporal_overlay": root / GLOBAL_TEMPORAL_OVERLAY,
        "bm25_manifest": bm25_manifest_path,
        "bm25_index": root / bm25_manifest["index"]["path"],
        "dense_manifest": dense_manifest_path,
        "dense_embeddings": root / dense_manifest["embeddings"]["path"],
        "dense_metadata": root / dense_manifest["metadata"]["path"],
        "table_index_manifest": table_manifest_path,
        "table_bm25_index": root / table_manifest["bm25"]["path"],
        "table_dense_embeddings": root / table_manifest["dense"]["path"],
        "table_dense_metadata": root / table_manifest["dense"]["metadata_path"],
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise RuntimeError(f"Runtime provenance input missing: {missing}")
    return {
        "files": {
            name: {
                "path": path.relative_to(root).as_posix()
                if path.is_relative_to(root)
                else str(path),
                "sha256": file_sha256(path),
            }
            for name, path in paths.items()
        },
        "planner": {
            "tag": planner_model,
            "identity_scope": "ollama_tag_only_not_binary_digest",
            "temperature": 0,
        },
        "reranker": {
            "model": MODEL_NAME,
            "revision": MODEL_REVISION,
            "max_length": MAX_LENGTH,
        },
        "embedding_model": dense_manifest["model"],
        "source_commit": _git_head(root),
    }


def create_run_authorization(
    *,
    root: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    approved_by: str,
    planner_model: str,
) -> dict[str, Any]:
    root = root.resolve()
    reviewed_path = reviewed_path.resolve()
    reviewed_manifest_path = reviewed_manifest_path.resolve()
    approved_by = approved_by.strip()
    if not approved_by:
        raise RuntimeError("approved_by is required")
    rows = read_jsonl(reviewed_path)
    manifest = _load_json(reviewed_manifest_path)
    reviewed_sha = file_sha256(reviewed_path)
    validate_reviewed_export(rows, manifest, reviewed_sha256=reviewed_sha)
    provenance = _runtime_provenance(root, planner_model)
    authorization = {
        "authorization_schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "status": "authorized_for_exactly_one_canary_run",
        "authorized_at": _utc_now(),
        "authorized_by": approved_by,
        "allowed_run_count": 1,
        "reviewed_packet": {
            "path": reviewed_path.relative_to(root).as_posix(),
            "sha256": reviewed_sha,
        },
        "reviewed_manifest": {
            "path": reviewed_manifest_path.relative_to(root).as_posix(),
            "sha256": file_sha256(reviewed_manifest_path),
        },
        "runtime_provenance": provenance,
        "constraints": {
            "off_on_same_process": True,
            "gold_available_to_decision": False,
            "case_specific_literals_allowed": False,
            "automatic_runtime_or_canonical_promotion": False,
            "training_allowed": False,
        },
    }
    payload = _canonical_json_bytes(authorization)
    sha = _sha256_bytes(payload)
    path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_run_authorization_{sha}.json"
    )
    write_immutable(path, payload)
    return {"path": str(path), "sha256": sha, "authorization": authorization}


def validate_run_authorization(
    *,
    root: Path,
    authorization_path: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    planner_model: str,
) -> dict[str, Any]:
    authorization = _load_json(authorization_path)
    if authorization.get("authorization_schema_version") != AUTHORIZATION_SCHEMA_VERSION:
        raise RuntimeError("Unsupported run authorization schema")
    if authorization.get("allowed_run_count") != 1:
        raise RuntimeError("Authorization must permit exactly one run")
    if authorization.get("status") != "authorized_for_exactly_one_canary_run":
        raise RuntimeError("Authorization is not active")
    if authorization["reviewed_packet"]["sha256"] != file_sha256(reviewed_path):
        raise RuntimeError("Authorization reviewed packet hash mismatch")
    if authorization["reviewed_manifest"]["sha256"] != file_sha256(reviewed_manifest_path):
        raise RuntimeError("Authorization reviewed manifest hash mismatch")
    current = _runtime_provenance(root, planner_model)
    if authorization.get("runtime_provenance") != current:
        raise RuntimeError("Runtime/model/index/evaluator provenance changed after authorization")
    if authorization.get("constraints") != {
        "off_on_same_process": True,
        "gold_available_to_decision": False,
        "case_specific_literals_allowed": False,
        "automatic_runtime_or_canonical_promotion": False,
        "training_allowed": False,
    }:
        raise RuntimeError("Authorization constraints changed")
    return authorization


def _citation_key(requirement_index: int, citation: dict[str, Any]) -> tuple[Any, ...]:
    return (
        requirement_index,
        citation.get("chunk_id"),
        citation.get("start_char"),
        citation.get("end_char"),
        citation.get("text"),
    )


def _score_arm(
    row: dict[str, Any],
    arm: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    decisions = arm["decisions"]
    groups = row["evidence_groups"]
    if len(groups) != len(row["requirements"]):
        raise RuntimeError(f"Evidence-group count differs from requirements: {row['candidate_id']}")

    requirement_count_mismatch = len(decisions) != len(row["requirements"])
    padded_decisions = list(decisions[: len(row["requirements"])])
    while len(padded_decisions) < len(row["requirements"]):
        padded_decisions.append({"status": "unsupported", "citations": []})

    group_scores = []
    exact_ok = True
    relevant_citations = 0
    total_citations = 0
    surplus_keys = []
    for index, (group, decision) in enumerate(
        zip(groups, padded_decisions, strict=True), 1
    ):
        citations = decision.get("citations") or []
        acceptable = set(group["acceptable_chunk_ids"])
        evidence_span = group["evidence_span"]
        group_hit = any(citation.get("chunk_id") in acceptable for citation in citations)
        literal_hit = any(
            citation.get("chunk_id") in acceptable
            and evidence_span in str(citation.get("text") or "")
            for citation in citations
        )
        for citation in citations:
            total_citations += 1
            chunk = chunks_by_id.get(citation.get("chunk_id"))
            start = citation.get("start_char")
            end = citation.get("end_char")
            citation_exact = (
                chunk is not None
                and isinstance(start, int)
                and isinstance(end, int)
                and chunk["display_text"][start:end] == citation.get("text")
            )
            exact_ok = exact_ok and citation_exact
            relevant = (
                citation.get("chunk_id") in acceptable
                and evidence_span in str(citation.get("text") or "")
            )
            if relevant:
                relevant_citations += 1
            else:
                surplus_keys.append(_citation_key(index, citation))
        group_scores.append(
            {
                "group_id": group["group_id"],
                "requirement_id": group["requirement_id"],
                "group_hit": group_hit,
                "literal_span_hit": literal_hit,
                "supported": decision.get("status") in {"supported", "supported_exact"},
            }
        )

    all_groups = all(score["group_hit"] for score in group_scores)
    all_spans = all(score["literal_span_hit"] for score in group_scores)
    full_answer = all(score["supported"] for score in group_scores)
    candidate_ids = set(arm.get("candidate_chunk_ids") or [])
    candidate_all_groups = all(
        bool(candidate_ids & set(group["acceptable_chunk_ids"])) for group in groups
    )
    return {
        "groups": group_scores,
        "runtime_requirement_count": len(decisions),
        "reviewed_requirement_count": len(row["requirements"]),
        "requirement_count_mismatch": requirement_count_mismatch,
        "candidate_all_groups_covered": candidate_all_groups,
        "all_groups_hit": all_groups,
        "all_evidence_spans_hit": all_spans,
        "full_answer": full_answer,
        "false_full": full_answer and not all_spans,
        "exact_citation_slices": exact_ok,
        "relevant_citation_count": relevant_citations,
        "citation_count": total_citations,
        "citation_precision": (
            round(relevant_citations / total_citations, 6) if total_citations else 1.0
        ),
        "surplus_citation_keys": surplus_keys,
        "temporal_violation_chunk_ids": sorted(
            set(arm.get("temporal_violation_chunk_ids") or [])
        ),
    }


def evaluate_pair_outputs(
    reviewed_rows: list[dict[str, Any]],
    pair_outputs: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output_by_id = {row["candidate_id"]: row for row in pair_outputs}
    if set(output_by_id) != {row["candidate_id"] for row in reviewed_rows}:
        raise RuntimeError("Pair outputs do not exactly match reviewed packet candidate IDs")
    evaluated = []
    for row in reviewed_rows:
        pair = output_by_id[row["candidate_id"]]
        if pair.get("gold_available_to_decision") is not False:
            raise RuntimeError("Gold isolation marker is missing")
        if pair.get("decision_input_fields") != list(DECISION_INPUT_FIELDS):
            raise RuntimeError("Decision path received fields outside the gold-free allowlist")
        arm0_score = _score_arm(row, pair["arm0"], chunks_by_id=chunks_by_id)
        arm1_score = _score_arm(row, pair["arm1"], chunks_by_id=chunks_by_id)
        arm0_surplus = set(map(tuple, arm0_score["surplus_citation_keys"]))
        arm1_surplus = set(map(tuple, arm1_score["surplus_citation_keys"]))
        evaluated.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "candidate_id": row["candidate_id"],
                "slot_ordinal": row["slot_ordinal"],
                "source_id": row["source_id"],
                "stratum": row["stratum"],
                "question_text": row["question_text"],
                "expected_surface_query_action": row["expected_surface_query_action"],
                "actual_surface_query_action": (
                    "apply" if pair["surface_query_applied"] else "bypass"
                ),
                "surface_query_audit": pair.get("surface_query_audit"),
                "arm0": pair["arm0"],
                "arm1": pair["arm1"],
                "arm0_score": arm0_score,
                "arm1_score": arm1_score,
                "new_surplus_citation_keys": sorted(arm1_surplus - arm0_surplus),
                "gold_available_to_decision": False,
                "decision_input_fields": list(DECISION_INPUT_FIELDS),
            }
        )
    return evaluated


def summarize_cases(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    arm0_strict = {row["candidate_id"] for row in rows if row["arm0_score"]["all_groups_hit"]}
    arm1_strict = {row["candidate_id"] for row in rows if row["arm1_score"]["all_groups_hit"]}
    arm0_literal = {
        row["candidate_id"] for row in rows if row["arm0_score"]["all_evidence_spans_hit"]
    }
    arm1_literal = {
        row["candidate_id"] for row in rows if row["arm1_score"]["all_evidence_spans_hit"]
    }
    positives = [row for row in rows if row["stratum"] in POSITIVE_STRATA]
    controls = [row for row in rows if row["stratum"] in CONTROL_STRATA]
    bypass_mutations = [
        row["candidate_id"]
        for row in controls
        if _canonical(row["arm0"]["decisions"]) != _canonical(row["arm1"]["decisions"])
    ]
    arm0_relevant = sum(row["arm0_score"]["relevant_citation_count"] for row in rows)
    arm0_total = sum(row["arm0_score"]["citation_count"] for row in rows)
    arm1_relevant = sum(row["arm1_score"]["relevant_citation_count"] for row in rows)
    arm1_total = sum(row["arm1_score"]["citation_count"] for row in rows)
    arm0_precision = arm0_relevant / arm0_total if arm0_total else 1.0
    arm1_precision = arm1_relevant / arm1_total if arm1_total else 1.0

    per_source = {}
    for source in EXPECTED_SOURCES:
        source_rows = [row for row in positives if row["source_id"] == source]
        successes = sum(row["arm1_score"]["all_groups_hit"] for row in source_rows)
        per_source[source] = _ratio(successes, len(source_rows))

    metrics = {
        "arm0_candidate_all_required_coverage": _ratio(
            sum(row["arm0_score"]["candidate_all_groups_covered"] for row in rows), total
        ),
        "arm1_candidate_all_required_coverage": _ratio(
            sum(row["arm1_score"]["candidate_all_groups_covered"] for row in rows), total
        ),
        "arm0_all_required_evidence": _ratio(len(arm0_strict), total),
        "arm1_all_required_evidence": _ratio(len(arm1_strict), total),
        "arm0_all_literal_spans": _ratio(len(arm0_literal), total),
        "arm1_all_literal_spans": _ratio(len(arm1_literal), total),
        "strict_regression_case_ids": sorted(arm0_strict - arm1_strict),
        "strict_improvement_case_ids": sorted(arm1_strict - arm0_strict),
        "literal_regression_case_ids": sorted(arm0_literal - arm1_literal),
        "literal_improvement_case_ids": sorted(arm1_literal - arm0_literal),
        "positive_application": _ratio(
            sum(row["actual_surface_query_action"] == "apply" for row in positives),
            len(positives),
        ),
        "control_bypass": _ratio(
            sum(row["actual_surface_query_action"] == "bypass" for row in controls),
            len(controls),
        ),
        "bypass_output_mutation_case_ids": bypass_mutations,
        "arm1_false_full_case_ids": sorted(
            row["candidate_id"] for row in rows if row["arm1_score"]["false_full"]
        ),
        "all_exact_citation_slices": all(
            row["arm1_score"]["exact_citation_slices"] for row in rows
        ),
        "new_surplus_citation_case_ids": sorted(
            row["candidate_id"] for row in rows if row["new_surplus_citation_keys"]
        ),
        "arm0_requirement_citation_precision": round(arm0_precision, 6),
        "arm1_requirement_citation_precision": round(arm1_precision, 6),
        "temporal_violation_chunk_ids": sorted(
            {
                chunk_id
                for row in rows
                for chunk_id in row["arm1_score"]["temporal_violation_chunk_ids"]
            }
        ),
        "positive_coverage_by_source": per_source,
        "runtime_requirement_count_mismatch_case_ids": sorted(
            row["candidate_id"]
            for row in rows
            if row["arm0_score"]["requirement_count_mismatch"]
            or row["arm1_score"]["requirement_count_mismatch"]
        ),
    }
    gates = {
        "candidate_coverage_non_decreasing": metrics[
            "arm1_candidate_all_required_coverage"
        ]["successes"]
        >= metrics["arm0_candidate_all_required_coverage"]["successes"],
        "strict_question_regression_zero": not metrics["strict_regression_case_ids"],
        "literal_span_regression_zero": not metrics["literal_regression_case_ids"],
        "strict_or_literal_improvement_at_least_one": bool(
            metrics["strict_improvement_case_ids"]
            or metrics["literal_improvement_case_ids"]
        ),
        "positive_application_16_of_16": metrics["positive_application"]["successes"]
        == 16,
        "control_bypass_16_of_16": metrics["control_bypass"]["successes"] == 16,
        "bypass_output_mutation_zero": not metrics["bypass_output_mutation_case_ids"],
        "false_full_zero": not metrics["arm1_false_full_case_ids"],
        "exact_citation_slice_100_percent": metrics["all_exact_citation_slices"],
        "new_irrelevant_or_surplus_citation_zero": not metrics[
            "new_surplus_citation_case_ids"
        ],
        "citation_precision_non_decreasing": arm1_precision >= arm0_precision,
        "temporal_revision_preview_expired_leak_zero": not metrics[
            "temporal_violation_chunk_ids"
        ],
        "each_source_positive_coverage_at_least_1_of_2": all(
            value["successes"] >= 1 for value in per_source.values()
        ),
        "zero_hit_positive_source_zero": all(
            value["successes"] > 0 for value in per_source.values()
        ),
        "runtime_requirement_count_match_all": not metrics[
            "runtime_requirement_count_mismatch_case_ids"
        ],
    }
    return {
        "metrics": metrics,
        "preregistered_gate_checks": gates,
        "decision": "DEVELOPMENT_CANARY_GO" if all(gates.values()) else "DEVELOPMENT_NO_GO",
        "automatic_runtime_or_canonical_promotion": False,
        "small_sample_limitation": "32 authored feature-canary rows; not an independent benchmark",
    }


class LivePairRunner:
    """One initialized runtime; each question shares planner, route, retrieval and candidates."""

    def __init__(self, *, root: Path, planner_model: str) -> None:
        from src.v3 import evaluate_contextual_answer_unit_ab as contextual
        from src.v3.gradio_backbone_demo import DemoBackbone
        from src.v3.requirement_entity_anchor import build_official_entity_index

        self.root = root
        self.contextual = contextual
        self.demo = DemoBackbone(
            root=root, planner_model=planner_model, enable_v3_2_candidates=True
        )
        self.demo._initialize()
        assert self.demo._artifacts is not None
        self.entity_index = build_official_entity_index(
            list(self.demo._artifacts.documents_by_id.values()),
            list(self.demo._artifacts.chunks_by_id.values()),
        )

    def run_pair(self, decision_input: dict[str, str]) -> dict[str, Any]:
        from src.v3.gradio_backbone_demo import (
            DEFAULT_AS_OF,
            TOP_K,
            filter_hits_by_global_temporal,
        )
        from src.v3.question_router import route_and_retrieve_with_embedding
        from src.v3.requirement_entity_anchor import anchor_requirements
        from src.v3.requirement_surface_query import (
            build_surface_scoring_requirements,
            extract_entity_coordinated_surfaces,
        )

        question = decision_input["question_text"]
        assert self.demo._artifacts is not None
        assert self.demo._overlay_rows is not None
        assert self.demo._source_entity_index is not None
        planned, planner_log = self.demo._plan(question)
        anchored = anchor_requirements(question, planned, self.entity_index)
        extraction = extract_entity_coordinated_surfaces(question, anchored)
        scoring_requirements = (
            build_surface_scoring_requirements(anchored, extraction)
            if extraction is not None
            else anchored
        )

        embedding = self.demo._encode(question)
        routed = route_and_retrieve_with_embedding(
            question,
            embedding,
            self.demo._artifacts,
            self.demo._overlay_rows,
            top_k=TOP_K,
            current_as_of=DEFAULT_AS_OF,
            source_entity_index=self.demo._source_entity_index,
        )
        route = routed["route"]
        if route["route_action"] != "retrieve":
            raise RuntimeError(
                f"Canary row did not enter retrieve route: {decision_input['candidate_id']}"
            )
        hits, _ = filter_hits_by_global_temporal(
            routed["hits"],
            time_scope=route["time_scope"],
            temporal_by_document=self.demo._global_temporal_by_document,
        )
        selected = self.demo._rerank_chunks(question, hits)
        arm0_raw = self.contextual.assemble_contextual_answer_units(
            self.demo,
            anchored,
            selected,
            documents_by_id=self.demo._artifacts.documents_by_id,
        )
        arm1_raw = (
            self.contextual.assemble_contextual_answer_units(
                self.demo,
                scoring_requirements,
                selected,
                documents_by_id=self.demo._artifacts.documents_by_id,
            )
            if extraction is not None
            else arm0_raw
        )
        selected_ids = [row["chunk_id"] for row in selected]
        arm0_view = self.contextual._context_decision_view(anchored, arm0_raw)
        arm1_view = self.contextual._context_decision_view(anchored, arm1_raw)
        temporal_violations = []
        for decision in arm0_raw + arm1_raw:
            for span in decision.get("spans", []):
                chunk = self.demo._artifacts.chunks_by_id[span["chunk_id"]]
                overlay = self.demo._global_temporal_by_document.get(
                    chunk["parent_document_id"], {}
                )
                if (
                    not chunk.get("default_exposure")
                    or chunk.get("status") not in set(route["allowed_statuses"])
                    or overlay.get("retrieval_action_current") == "deny"
                    or overlay.get("validity_state")
                    in {"expired", "historical", "preview", "superseded"}
                    or overlay.get("is_current_revision") is False
                ):
                    temporal_violations.append(span["chunk_id"])
        temporal_violations = sorted(set(temporal_violations))
        return {
            "candidate_id": decision_input["candidate_id"],
            "surface_query_applied": extraction is not None,
            "surface_query_audit": extraction,
            "arm0": {
                "decisions": arm0_view,
                "candidate_chunk_ids": selected_ids,
                "temporal_violation_chunk_ids": temporal_violations,
            },
            "arm1": {
                "decisions": arm1_view,
                "candidate_chunk_ids": selected_ids,
                "temporal_violation_chunk_ids": temporal_violations,
            },
            "shared_runtime": {
                "planner_call": planner_log,
                "route": route,
                "selected_chunk_ids": selected_ids,
                "off_on_same_process": True,
                "shared_planner_output": True,
                "shared_route_and_candidates": True,
                "only_surface_query_scoring_requirements_differ": True,
            },
            "gold_available_to_decision": False,
            "decision_input_fields": list(DECISION_INPUT_FIELDS),
        }


def collect_pair_outputs(
    reviewed_rows: list[dict[str, Any]], runner: PairRunner
) -> list[dict[str, Any]]:
    outputs = []
    for index, row in enumerate(reviewed_rows, 1):
        decision_input = {field: str(row[field]) for field in DECISION_INPUT_FIELDS}
        print(f"[canary {index}/{len(reviewed_rows)}] {decision_input['question_text']}", flush=True)
        pair = runner.run_pair(decision_input)
        if pair.get("candidate_id") != row["candidate_id"]:
            raise RuntimeError("Pair runner changed candidate identity")
        outputs.append(pair)
    return outputs


def _prior_run_exists(root: Path, authorization_sha: str) -> bool:
    patterns = (
        "requirement_surface_query_canary_execution_started_*.json",
        "requirement_surface_query_canary_execution_ledger_*.json",
    )
    for pattern in patterns:
        for path in (root / "data/v3/evaluation").glob(pattern):
            row = _load_json(path)
            if row.get("authorization_sha256") == authorization_sha:
                return True
    return False


def execute_once(
    *,
    root: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    authorization_path: Path,
    planner_model: str,
    runner: PairRunner | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    reviewed_path = reviewed_path.resolve()
    reviewed_manifest_path = reviewed_manifest_path.resolve()
    authorization_path = authorization_path.resolve()
    rows = read_jsonl(reviewed_path)
    reviewed_manifest = _load_json(reviewed_manifest_path)
    reviewed_sha = file_sha256(reviewed_path)
    validate_reviewed_export(rows, reviewed_manifest, reviewed_sha256=reviewed_sha)
    authorization = validate_run_authorization(
        root=root,
        authorization_path=authorization_path,
        reviewed_path=reviewed_path,
        reviewed_manifest_path=reviewed_manifest_path,
        planner_model=planner_model,
    )
    authorization_sha = file_sha256(authorization_path)
    if _prior_run_exists(root, authorization_sha):
        raise RuntimeError("This one-run authorization has already been consumed")

    started = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "status": "STARTED_AUTHORIZATION_CONSUMED",
        "started_at": _utc_now(),
        "authorization_sha256": authorization_sha,
        "reviewed_packet_sha256": reviewed_sha,
        "evaluator_sha256": file_sha256(Path(__file__).resolve()),
        "automatic_runtime_or_canonical_promotion": False,
    }
    started_bytes = _canonical_json_bytes(started)
    started_sha = _sha256_bytes(started_bytes)
    started_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_execution_started_{started_sha}.json"
    )
    write_immutable(started_path, started_bytes)

    chunks_path = root / DEFAULT_CHUNKS
    before_hashes = {
        "reviewed": reviewed_sha,
        "reviewed_manifest": file_sha256(reviewed_manifest_path),
        "authorization": authorization_sha,
        "chunks": file_sha256(chunks_path),
        "documents": file_sha256(root / DEFAULT_DOCUMENTS),
    }
    active_runner = runner or LivePairRunner(root=root, planner_model=planner_model)
    pair_outputs = collect_pair_outputs(rows, active_runner)
    chunks_by_id = {row["chunk_id"]: row for row in read_jsonl(chunks_path)}
    cases = evaluate_pair_outputs(rows, pair_outputs, chunks_by_id=chunks_by_id)
    summary = summarize_cases(cases)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "authored_feature_canary_single_run_not_independent_holdout",
        "summary": summary,
        "authorization": {
            "sha256": authorization_sha,
            "authorized_by": authorization["authorized_by"],
        },
        "constraints": {
            "gold_available_to_decision": False,
            "decision_input_fields": list(DECISION_INPUT_FIELDS),
            "case_specific_literals": 0,
            "automatic_runtime_or_canonical_promotion": False,
            "result_does_not_change_runtime": True,
        },
        "runtime_provenance": authorization["runtime_provenance"],
    }
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(cases, lambda row: row["slot_ordinal"])
    cases_sha = _sha256_bytes(cases_bytes)
    cases_path = evidence_dir / f"requirement_surface_query_canary_ab_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"requirement_surface_query_canary_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    manifest = {
        "manifest_schema_version": "requirement-surface-query-canary-ab-manifest-v1",
        "evaluator_version": EVALUATOR_VERSION,
        "decision": summary["decision"],
        "inputs": before_hashes,
        "outputs": {
            "cases": {"path": cases_path.relative_to(root).as_posix(), "sha256": cases_sha},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
        },
        "automatic_runtime_or_canonical_promotion": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / (
        f"requirement_surface_query_canary_ab_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    after_hashes = {
        "reviewed": file_sha256(reviewed_path),
        "reviewed_manifest": file_sha256(reviewed_manifest_path),
        "authorization": file_sha256(authorization_path),
        "chunks": file_sha256(chunks_path),
        "documents": file_sha256(root / DEFAULT_DOCUMENTS),
    }
    if before_hashes != after_hashes:
        raise RuntimeError("Canary input changed during the one-run execution")
    ledger = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "status": "COMPLETED_NO_AUTOMATIC_PROMOTION",
        "completed_at": _utc_now(),
        "authorization_sha256": authorization_sha,
        "started_ledger": {"path": started_path.relative_to(root).as_posix(), "sha256": started_sha},
        "result": {
            "decision": summary["decision"],
            "cases_sha256": cases_sha,
            "report_sha256": report_sha,
            "manifest_sha256": manifest_sha,
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    ledger_bytes = _canonical_json_bytes(ledger)
    ledger_sha = _sha256_bytes(ledger_bytes)
    ledger_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_execution_ledger_{ledger_sha}.json"
    )
    write_immutable(ledger_path, ledger_bytes)
    return {
        "decision": summary["decision"],
        "cases_path": str(cases_path),
        "report_path": str(report_path),
        "manifest_path": str(manifest_path),
        "ledger_path": str(ledger_path),
        "runtime_or_canonical_promoted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("authorize", "run"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--reviewed-manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--approved-by")
    parser.add_argument("--planner-model", default="qwen3:8b")
    args = parser.parse_args()
    root = args.root.resolve()
    reviewed = args.reviewed if args.reviewed.is_absolute() else root / args.reviewed
    reviewed_manifest = (
        args.reviewed_manifest
        if args.reviewed_manifest.is_absolute()
        else root / args.reviewed_manifest
    )
    if args.command == "authorize":
        if args.authorization is not None:
            raise RuntimeError("--authorization is only valid for run")
        result = create_run_authorization(
            root=root,
            reviewed_path=reviewed,
            reviewed_manifest_path=reviewed_manifest,
            approved_by=args.approved_by or "",
            planner_model=args.planner_model,
        )
    else:
        if args.authorization is None:
            raise RuntimeError("run requires --authorization")
        authorization = (
            args.authorization
            if args.authorization.is_absolute()
            else root / args.authorization
        )
        result = execute_once(
            root=root,
            reviewed_path=reviewed,
            reviewed_manifest_path=reviewed_manifest,
            authorization_path=authorization,
            planner_model=args.planner_model,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
