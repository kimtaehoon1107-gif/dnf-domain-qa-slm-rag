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

from kiwipiepy import Kiwi

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_ASSEMBLER,
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
)
from src.v3.gradio_backbone_demo import (
    CANONICAL_RUNTIME_POINTER,
    TABLE_INDEX_MANIFEST,
    DemoBackbone,
)
from src.v3.grounded_answer_generator import (
    _attribute_markers,
    _numeric_qualifiers,
    _surface_key,
    _surface_match_score,
    apply_table_value_shape_gate,
    table_value_spans,
)


INVESTIGATION_VERSION = "table-binding-zero-selection-investigation-v1"
DEFAULT_OBSERVED_CASES = Path(
    "outputs/v3/router_backbone_generation_ab_cases_"
    "deae90daddfb95167e29ea781104fd1991a964c90557b4588190e0a9366a2264.jsonl"
)


def _qualified(score: tuple[int, int]) -> bool:
    return score[0] >= 2 or score[1] >= 2


def _best(
    scored: list[tuple[tuple[int, int], str]],
) -> tuple[tuple[int, int] | None, str | None]:
    if not scored:
        return None, None
    best_score = max(score for score, _ in scored)
    return next((score, value) for score, value in scored if score == best_score)


def _kiwi_content_surface(kiwi: Kiwi, value: Any) -> str:
    return " ".join(
        token.form
        for token in kiwi.tokenize(str(value or ""))
        if not token.tag.startswith("J")
    )


def _audit_binding(
    requirement: dict[str, Any],
    table_views: list[dict[str, Any]],
    *,
    kiwi: Kiwi,
) -> dict[str, Any]:
    subject = str(requirement.get("subject") or "")
    relation = str(requirement.get("relation") or "")
    selection_surface = f"{subject} {relation}".strip()

    table_scores = [
        (_surface_match_score(subject, view.get("table_subject")), str(view.get("table_subject") or ""))
        for view in table_views
    ]
    s1_best_score, s1_table_subject = _best(table_scores)

    row_entries: list[dict[str, Any]] = []
    for view in table_views:
        table_score = _surface_match_score(subject, view.get("table_subject"))
        for row in view.get("rows", []):
            row_subject = str(row.get("subject") or "")
            current_score = _surface_match_score(selection_surface, row_subject)
            subject_score = _surface_match_score(subject, row_subject)
            relation_score = _surface_match_score(relation, row_subject)
            kiwi_score = _surface_match_score(
                _kiwi_content_surface(kiwi, selection_surface),
                _kiwi_content_surface(kiwi, row_subject),
            )
            row_entries.append(
                {
                    "view": view,
                    "row": row,
                    "row_subject": row_subject,
                    "table_score": table_score,
                    "current_score": current_score,
                    "subject_score": subject_score,
                    "relation_score": relation_score,
                    "kiwi_score": kiwi_score,
                    "combined_score": (*current_score, *table_score),
                }
            )

    s2_best_score, s2_best_row_subject = _best(
        [(entry["current_score"], entry["row_subject"]) for entry in row_entries]
    )
    s2_subject_only_best_score, s2_subject_only_best_row = _best(
        [(entry["subject_score"], entry["row_subject"]) for entry in row_entries]
    )
    s2_relation_only_best_score, s2_relation_only_best_row = _best(
        [(entry["relation_score"], entry["row_subject"]) for entry in row_entries]
    )
    s2_kiwi_best_score, s2_kiwi_best_row = _best(
        [(entry["kiwi_score"], entry["row_subject"]) for entry in row_entries]
    )

    base = {
        "subject": subject,
        "relation": relation,
        "table_view_count": len(table_views),
        "table_row_count": sum(len(view.get("rows", [])) for view in table_views),
        "s1_best_score": list(s1_best_score) if s1_best_score is not None else None,
        "s1_table_subject": s1_table_subject,
        "s1_is_runtime_veto": False,
        "s2_best_score": list(s2_best_score) if s2_best_score is not None else None,
        "s2_best_row_subject": s2_best_row_subject,
        "s2_subject_only_best_score": (
            list(s2_subject_only_best_score)
            if s2_subject_only_best_score is not None
            else None
        ),
        "s2_subject_only_best_row_subject": s2_subject_only_best_row,
        "s2_relation_only_best_score": (
            list(s2_relation_only_best_score)
            if s2_relation_only_best_score is not None
            else None
        ),
        "s2_relation_only_best_row_subject": s2_relation_only_best_row,
        "s2_kiwi_best_score": (
            list(s2_kiwi_best_score) if s2_kiwi_best_score is not None else None
        ),
        "s2_kiwi_best_row_subject": s2_kiwi_best_row,
        "s2_candidate_count": 0,
        "numeric_qualifiers": sorted(_numeric_qualifiers(relation)),
        "s3_survivors": 0,
        "s4_best_score": None,
        "s4_best_attribute": None,
        "s4_selection_mode": None,
        "selected_attribute_count": 0,
        "selected_table_value_count": 0,
    }
    if not table_views:
        return {**base, "failed_stage": "S1"}

    candidates = [
        entry
        for entry in row_entries
        if _qualified(entry["current_score"])
        and entry["combined_score"] > (0, 0, 0, 0)
    ]
    base["s2_candidate_count"] = len(candidates)
    if not candidates:
        return {**base, "failed_stage": "S2"}

    qualifiers = _numeric_qualifiers(relation)
    qualified_candidates = (
        [
            entry
            for entry in candidates
            if qualifiers <= _numeric_qualifiers(entry["row"].get("subject"))
        ]
        if qualifiers
        else candidates
    )
    base["s3_survivors"] = len(qualified_candidates)
    if not qualified_candidates:
        return {**base, "failed_stage": "S3"}

    best_combined_score = max(entry["combined_score"] for entry in qualified_candidates)
    selected = next(
        entry
        for entry in qualified_candidates
        if entry["combined_score"] == best_combined_score
    )
    view = selected["view"]
    row = selected["row"]
    values = row.get("values") or {}
    attributes = [
        attribute
        for attribute in view.get("attributes", values.keys())
        if values.get(attribute) is not None
    ]
    attribute_scores = {
        attribute: _surface_match_score(relation, attribute)
        for attribute in attributes
    }
    s4_best_score = max(attribute_scores.values(), default=(0, 0))
    s4_best_attributes = [
        attribute
        for attribute in attributes
        if attribute_scores[attribute] == s4_best_score
    ]
    base["s4_best_score"] = list(s4_best_score)
    base["s4_best_attribute"] = s4_best_attributes[0] if s4_best_attributes else None

    if s4_best_score[0] > 0:
        selected_attributes = s4_best_attributes
        selection_mode = "surface_match"
    else:
        markers = _attribute_markers(relation)
        explicit_cost_attribute = any(
            any(
                _surface_key(marker) in _surface_key(attribute)
                for marker in ("price", "cost", "가격", "비용")
            )
            for attribute in attributes
        )
        cost_bundle = bool(
            markers
            and markers[0] == "price"
            and not explicit_cost_attribute
            and any(
                _surface_key(marker)
                in _surface_key(
                    f"{view.get('table_subject') or ''} {view.get('caption') or ''}"
                )
                for marker in ("price", "cost", "가격", "비용")
            )
        )
        marked = [
            attribute
            for attribute in attributes
            if any(
                _surface_key(marker) in _surface_key(attribute)
                for marker in markers
            )
        ]
        if cost_bundle:
            selected_attributes = attributes
            selection_mode = "cost_bundle"
        elif marked:
            selected_attributes = marked
            selection_mode = "attribute_marker"
        else:
            return {
                **base,
                "failed_stage": "S4",
                "s4_selection_mode": "no_attribute_match",
            }

    actual_spans = table_value_spans(requirement, table_views)
    if len(actual_spans) != len(selected_attributes):
        raise RuntimeError(
            "Diagnostic reproduction differs from table_value_spans: "
            f"{requirement.get('requirement_id')}"
        )
    base["s4_selection_mode"] = selection_mode
    base["selected_attribute_count"] = len(selected_attributes)
    base["selected_table_value_count"] = len(actual_spans)
    return {
        **base,
        "failed_stage": None if actual_spans else "PASS_EMPTY",
    }


def _hypothesis_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    h1_rows = [
        row
        for row in rows
        if not _qualified(tuple(row["s2_subject_only_best_score"] or (0, 0)))
        and _qualified(tuple(row["s2_relation_only_best_score"] or (0, 0)))
    ]
    h1_s4_rows = [row for row in h1_rows if row["failed_stage"] == "S4"]

    overlong_rows = [
        row
        for row in rows
        if (row["s2_subject_only_best_score"] or [0, 0])[0] == 2
        and len(_surface_key(row["subject"]))
        > len(_surface_key(row["s2_subject_only_best_row_subject"]))
    ]
    overlong_s2_failures = [
        row for row in overlong_rows if row["failed_stage"] == "S2"
    ]

    kiwi_rescues = [
        row
        for row in rows
        if row["failed_stage"] == "S2"
        and _qualified(tuple(row["s2_kiwi_best_score"] or (0, 0)))
    ]
    s4_rows = [row for row in rows if row["failed_stage"] == "S4"]
    return {
        "H1_subject_row_layer_mismatch": {
            "verdict": (
                "surface_pattern_partially_supported"
                if h1_rows
                else "not_supported_on_observed_rows"
            ),
            "operational_definition": (
                "subject-only cannot qualify any row while relation-only can"
            ),
            "evidence_requirement_count": len(h1_rows),
            "of_which_failed_at_s4": len(h1_s4_rows),
            "case_count": len({row["case_id"] for row in h1_rows}),
        },
        "H2_overlong_subject": {
            "verdict": (
                "supported_as_direct_s2_cause"
                if overlong_s2_failures
                else "not_supported_as_direct_s2_cause"
            ),
            "operational_definition": (
                "row subject is a strict substring of planner subject; current "
                "containment score is then checked for an S2 failure"
            ),
            "overlong_containment_requirement_count": len(overlong_rows),
            "s2_failure_count": len(overlong_s2_failures),
            "case_count": len({row["case_id"] for row in overlong_rows}),
        },
        "H3_korean_particles_or_morphology": {
            "verdict": (
                "surface_rescue_observed_semantic_validity_unproven"
                if kiwi_rescues
                else "not_supported_on_observed_rows"
            ),
            "operational_definition": (
                "current S2 failure becomes qualifying after Kiwi removes J* particles"
            ),
            "kiwi_rescued_requirement_count": len(kiwi_rescues),
            "case_count": len({row["case_id"] for row in kiwi_rescues}),
        },
        "H4_attribute_name_mismatch": {
            "verdict": "supported" if s4_rows else "not_supported",
            "operational_definition": (
                "row survives S2/S3 but relation matches neither an attribute nor "
                "the existing marker/cost fallback"
            ),
            "evidence_requirement_count": len(s4_rows),
            "case_count": len({row["case_id"] for row in s4_rows}),
        },
    }


def _structural_findings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    s2_rows = [row for row in rows if row["failed_stage"] == "S2"]
    lengths = sorted(len(str(row["s2_best_row_subject"] or "")) for row in s2_rows)
    s1_scored_rows = [row for row in rows if row["s1_best_score"] is not None]
    return {
        "dominant_failed_stage": "S2",
        "s2_failure_count": len(s2_rows),
        "s2_best_score_distribution": dict(
            sorted(
                Counter(
                    "/".join(str(value) for value in row["s2_best_score"])
                    for row in s2_rows
                ).items()
            )
        ),
        "s2_best_row_subject_length": {
            "median_characters": lengths[len(lengths) // 2] if lengths else 0,
            "over_40_characters": sum(length > 40 for length in lengths),
            "over_80_characters": sum(length > 80 for length in lengths),
        },
        "nonempty_view_requirements_with_zero_s1_surface_score": sum(
            row["s1_best_score"] == [0, 0] for row in s1_scored_rows
        ),
        "interpretation": (
            "The dominant observable incompatibility is between planner surfaces and "
            "the table view's table_subject/row.subject fields. This is a structural "
            "surface diagnosis only; semantic correctness was not judged with gold."
        ),
    }


def run(root: Path, *, observed_cases: Path, device: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    observed_cases = (
        observed_cases.resolve()
        if observed_cases.is_absolute()
        else (root / observed_cases).resolve()
    )
    paths = {
        "observed_generation_ab_cases": observed_cases,
        "enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": root / DEFAULT_ASSEMBLER,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "chunks": root / DEFAULT_CHUNKS,
        "canonical_runtime_pointer": root / CANONICAL_RUNTIME_POINTER,
        "table_index_manifest": root / TABLE_INDEX_MANIFEST,
        "binding_source": root / "src/v3/grounded_answer_generator.py",
        "demo_source": root / "src/v3/gradio_backbone_demo.py",
        "investigation_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in paths.items()}

    observed = read_jsonl(observed_cases)
    target_observed = {
        row["case_id"]: row
        for row in observed
        if int(row["off"].get("table_view_count") or 0) > 0
        and int(row["on"].get("selected_table_value_count") or 0) == 0
    }
    if len(target_observed) != 17:
        raise RuntimeError(f"Expected 17 zero-selection cases, got {len(target_observed)}")

    enumerations = {row["case_id"]: row for row in read_jsonl(paths["enumeration"])}
    assemblers = {row["case_id"]: row for row in read_jsonl(paths["assembler_cases"])}
    evaluations = {
        row["dev_id"]: {
            "question": row["question"],
            "time_scope": str(row.get("time_scope") or "current"),
        }
        for row in read_jsonl(paths["adaptive_dev"]) + read_jsonl(paths["downgraded_canary"])
    }
    chunks_by_id = {row["chunk_id"]: row for row in read_jsonl(paths["chunks"])}

    runtime = DemoBackbone(
        root=root,
        planner_model="qwen3:8b",
        device=device,
        enable_v3_2_candidates=True,
        enable_generation=False,
    )
    runtime._initialize()
    table_parent_ids = {
        str(row["parent_document_id"]) for row in runtime._table_facts
    }
    kiwi = Kiwi()

    rows: list[dict[str, Any]] = []
    reconstructed_visible_by_case: dict[str, dict[str, int]] = {}
    for case_id in sorted(target_observed):
        requirements = enumerations[case_id]["requirements"]
        decisions = assemblers[case_id]["decisions"]
        if len(requirements) != len(decisions):
            raise RuntimeError(f"Planner/assembler count mismatch: {case_id}")
        visible_view_count = 0
        visible_row_count = 0
        for requirement_index, (requirement, decision) in enumerate(
            zip(requirements, decisions, strict=True),
            1,
        ):
            citations = [dict(span) for span in decision.get("spans", [])]
            cited_chunks = [
                chunks_by_id[span["chunk_id"]]
                for span in citations
                if span.get("chunk_id") in chunks_by_id
            ]
            parent_ids = tuple(
                sorted({row["parent_document_id"] for row in cited_chunks})
            )
            source_ids = tuple(sorted({row["source_id"] for row in cited_chunks}))
            raw_views = []
            if (
                decision.get("status") == "supported_exact"
                and set(parent_ids) & table_parent_ids
            ):
                raw_views = runtime._table_views(
                    requirement,
                    source_ids=source_ids,
                    allowed_parent_document_ids=parent_ids,
                    time_scope=evaluations[case_id]["time_scope"],
                )
            checked, gate_audit = apply_table_value_shape_gate(
                requirement,
                decision,
                raw_views,
            )
            visible_views = (
                raw_views if checked.get("status") == "supported_exact" else []
            )
            visible_view_count += len(visible_views)
            visible_row_count += sum(
                int(view.get("row_count") or len(view.get("rows", [])))
                for view in visible_views
            )
            binding = _audit_binding(requirement, raw_views, kiwi=kiwi)
            rows.append(
                {
                    "case_id": case_id,
                    "requirement_index": requirement_index,
                    "requirement_id": requirement.get("requirement_id"),
                    **binding,
                    "raw_table_view_count": binding["table_view_count"],
                    "raw_table_row_count": binding["table_row_count"],
                    "visible_after_value_shape_gate": bool(visible_views),
                    "visible_table_view_count": len(visible_views),
                    "visible_table_row_count": sum(
                        int(view.get("row_count") or len(view.get("rows", [])))
                        for view in visible_views
                    ),
                    "value_shape_gate_vetoed": bool(gate_audit.get("vetoed")),
                }
            )
        reconstructed_visible_by_case[case_id] = {
            "table_view_count": visible_view_count,
            "table_row_count": visible_row_count,
        }

    if len(rows) != 33:
        raise RuntimeError(f"Expected 33 requirement audits, got {len(rows)}")
    reproduction_mismatches = []
    for case_id, counts in reconstructed_visible_by_case.items():
        observed_row = target_observed[case_id]
        expected = {
            "table_view_count": int(observed_row["off"].get("table_view_count") or 0),
            "table_row_count": int(observed_row["off"].get("table_row_count") or 0),
        }
        if counts != expected:
            reproduction_mismatches.append(
                {"case_id": case_id, "observed": expected, "reconstructed": counts}
            )
    stage_counts = Counter(
        row["failed_stage"] or "PASSED_WITH_VALUES" for row in rows
    )
    cases_bytes = _serialize_jsonl(
        rows,
        sort_key=lambda row: (row["case_id"], row["requirement_index"]),
    )
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = (
        root
        / "data/v3/evidence"
        / f"table_binding_zero_selection_audit_{cases_sha}.jsonl"
    )
    write_immutable(cases_path, cases_bytes)

    report = {
        "report_schema_version": "table-binding-zero-selection-report-v1",
        "investigation_version": INVESTIGATION_VERSION,
        "evaluation_role": "development_only_table_binding_root_cause_no_fix",
        "target": {
            "selection_rule": (
                "off.table_view_count > 0 and on.selected_table_value_count == 0"
            ),
            "case_count": len(target_observed),
            "requirement_count": len(rows),
            "observed_visible_table_view_count": sum(
                int(row["off"].get("table_view_count") or 0)
                for row in target_observed.values()
            ),
            "observed_visible_table_row_count": sum(
                int(row["off"].get("table_row_count") or 0)
                for row in target_observed.values()
            ),
        },
        "stage_distribution": {
            "S1": stage_counts["S1"],
            "S2": stage_counts["S2"],
            "S3": stage_counts["S3"],
            "S4": stage_counts["S4"],
            "passed_but_empty": stage_counts["PASS_EMPTY"],
            "passed_with_values": stage_counts["PASSED_WITH_VALUES"],
        },
        "runtime_control_flow_findings": {
            "s1_surface_score_is_an_actual_veto": False,
            "s2_runtime_left_surface": "subject + relation",
            "s2_documented_left_surface": "subject",
            "s2_difference_recorded_separately": True,
        },
        "structural_findings": _structural_findings(rows),
        "hypotheses": _hypothesis_report(rows),
        "reproduction": {
            "raw_table_views_replayed_from_frozen_sidecar": True,
            "visible_counts_match_frozen_artifact_per_case": not reproduction_mismatches,
            "visible_count_mismatch_scope": (
                "post_binding_value_shape_gate_only"
                if reproduction_mismatches
                else None
            ),
            "mismatch_count": len(reproduction_mismatches),
            "mismatches": reproduction_mismatches,
        },
        "constraints": {
            "binding_logic_changed": False,
            "search_changed": False,
            "routing_changed": False,
            "planner_changed": False,
            "frozen_artifact_regenerated": False,
            "llm_inference_calls": 0,
            "table_sidecar_embedding_and_reranker_replay": True,
            "gold_fields_read": False,
            "gold_in_output": False,
            "gold_used_for_judgment": False,
            "post_binding_gate_drift_used_for_stage_judgment": False,
        },
        "inputs": {
            name: {
                "path": path.resolve().relative_to(root).as_posix(),
                "sha256": before[name],
            }
            for name, path in paths.items()
        },
        "artifacts": {
            "requirement_audit": {
                "path": cases_path.relative_to(root).as_posix(),
                "sha256": cases_sha,
                "row_count": len(rows),
            }
        },
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = (
        root
        / "reports/v3"
        / f"table_binding_zero_selection_investigation_{report_sha}.json"
    )
    write_immutable(report_path, report_bytes)

    after = {name: file_sha256(path) for name, path in paths.items()}
    if before != after:
        raise RuntimeError("An investigation input changed during measurement")
    return {
        "cases": str(cases_path),
        "report": str(report_path),
        "stage_distribution": report["stage_distribution"],
        "hypotheses": report["hypotheses"],
        "input_hashes_unchanged": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--observed-cases", type=Path, default=DEFAULT_OBSERVED_CASES)
    parser.add_argument("--device")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.root,
                observed_cases=args.observed_cases,
                device=args.device,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
