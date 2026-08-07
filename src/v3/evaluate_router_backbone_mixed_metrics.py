from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_router_backbone_ab import _score_arm, simulate_arm
from src.v3.grounded_answer_generator import (
    apply_table_value_shape_gate,
    extract_factual_tokens,
)
from src.v3.requirement_value_shape import VALUE_SHAPE_VERSION, apply_value_shape_veto

EVALUATOR_VERSION = "router-backbone-mixed-metrics-v3.2.0"
CASE_SCHEMA_VERSION = "router-backbone-mixed-metrics-case-v3.2"
REPORT_SCHEMA_VERSION = "router-backbone-mixed-metrics-report-v3.2"
MANIFEST_SCHEMA_VERSION = "router-backbone-mixed-metrics-manifest-v3.2"
GENERATION_AB_VERSION = "router-backbone-generation-ab-v1"

DEFAULT_GROUND_TRUTH = Path(
    "data/v3/evaluation/semantic_answerability_ground_truth_"
    "53cd8ae72ad4ee2f7c9b1d4370991ad74b5044d154e3657fd2008f45f71fe609.jsonl"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_ASSEMBLER = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_BACKBONE = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/router_backbone_mixed_metrics.md")

DOCS_PROFILE = "docs_only"
MIXED_PROFILE = "mixed"
ANSWERABLE_PROFILES = {DOCS_PROFILE, MIXED_PROFILE}


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "small_sample_limit": total < 5,
    }


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def docs_requirement_split(
    ground_truth: dict[str, Any], requirement_count: int
) -> tuple[set[int], set[int]]:
    """Split requirement indices 1..N into docs-answerable and non-docs sets.

    Only the frozen per-requirement ``answerable_from_docs`` flags are read. Indices
    outside 1..N (planner/gold enumeration drift) are ignored. For ``docs_only`` every
    requirement is docs-required; the ground-truth default fills any unlisted index.
    """

    profile = ground_truth.get("answerability_profile")
    valid = set(range(1, requirement_count + 1))
    if profile == DOCS_PROFILE:
        return set(valid), set()
    default = ground_truth.get("default_requirement_answerable_from_docs")
    explicit = {
        int(item["requirement_index"]): bool(item["answerable_from_docs"])
        for item in ground_truth.get("partial_requirements_in_question_order") or []
    }
    docs: set[int] = set()
    non_docs: set[int] = set()
    for index in valid:
        flag = explicit.get(index, default)
        if flag is True:
            docs.add(index)
        elif flag is False:
            non_docs.add(index)
    return docs, non_docs


def _docs_value_complete(
    docs_required: set[int],
    supported: set[int],
    requirements: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> bool:
    """True when every supported docs requirement also passes the value-shape check.

    A requirement without a high-precision value shape is never disproven, so it passes.
    A requirement whose cited spans miss the required %/amount/date/duration is vetoed and
    fails, folding the B1 span-level axis into docs completeness.
    """

    for index in sorted(docs_required):
        if index not in supported:
            continue
        _, audit = apply_value_shape_veto(requirements[index - 1], decisions[index - 1])
        if audit["vetoed"]:
            return False
    return True


def score_mixed_case(
    *,
    profile: str,
    docs_required: set[int],
    non_docs_required: set[int],
    supported: set[int],
    response_mode: str,
    all_groups_cited: bool,
    docs_value_complete: bool,
) -> dict[str, Any]:
    docs_all_supported = docs_required <= supported
    no_non_docs_claimed = not (non_docs_required & supported)
    has_answer = response_mode in {"full_answer", "partial_answer"}

    correct_mixed_partial = (
        response_mode == "partial_answer"
        and docs_all_supported
        and no_non_docs_claimed
        and all_groups_cited
    )
    labels = {
        "profile": profile,
        "docs_required_count": len(docs_required),
        "non_docs_required_count": len(non_docs_required),
        "docs_all_supported": docs_all_supported,
        "no_non_docs_claimed": no_non_docs_claimed,
        "correct_mixed_partial": correct_mixed_partial,
        "correct_mixed_partial_span_strict": correct_mixed_partial and docs_value_complete,
        "mixed_overclaim": bool(non_docs_required & supported),
        "mixed_overreject": bool(docs_required) and not docs_all_supported,
        "mixed_missing_evidence": (
            docs_all_supported
            and no_non_docs_claimed
            and has_answer
            and not all_groups_cited
        ),
    }
    if labels["mixed_overclaim"]:
        primary = "mixed_overclaim"
    elif correct_mixed_partial:
        primary = "correct_mixed_partial"
    elif labels["mixed_overreject"]:
        primary = "mixed_overreject"
    elif labels["mixed_missing_evidence"]:
        primary = "mixed_missing_evidence"
    else:
        primary = "mixed_other"
    labels["primary_mixed_label"] = primary
    return labels


def build_case_rows(
    *,
    ground_truth_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    backbone_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ground_truth = {row["case_id"]: row for row in ground_truth_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    backbones = {row["case_id"]: row for row in backbone_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunk_to_parent = {row["chunk_id"]: row["parent_document_id"] for row in chunks}

    if not (
        set(ground_truth)
        == set(enumerations)
        == set(assemblers)
        == set(backbones)
        == set(evaluations)
    ):
        raise RuntimeError("Frozen 95-case joins do not have identical case IDs")

    frozen_keys = (
        "grounded_answer",
        "false_full_answer",
        "false_partial",
        "honest_partial",
        "answerable_overreject",
        "reject_correct",
        "realtime_safe_abstain",
        "realtime_static_exposure",
    )
    output = []
    for case_id in sorted(backbones):
        gt = ground_truth[case_id]
        enumeration = enumerations[case_id]
        assembler = assemblers[case_id]
        backbone = backbones[case_id]
        evaluation = evaluations[case_id]
        requirements = enumeration["requirements"]
        decisions = assembler["decisions"]
        if len(requirements) != len(decisions):
            raise RuntimeError(f"Planner/assembler count mismatch: {case_id}")

        baseline_supported = {
            index
            for index, decision in enumerate(decisions, start=1)
            if decision["status"] == "supported_exact"
        }
        arm0 = simulate_arm(
            placement="arm0",
            question=evaluation["question"],
            assembler_decisions=decisions,
            classifier_predictions=[],
            chunk_to_parent=chunk_to_parent,
        )
        arm0_score = _score_arm(
            arm0,
            target=backbone["answerability_target"],
            evidence_groups=evaluation["evidence_groups"],
            expected_docs_flags=[True] * len(requirements),
            baseline_supported_indices=baseline_supported,
        )
        frozen_score = backbone["arm0"]["score"]
        if any(arm0_score[key] != frozen_score[key] for key in frozen_keys):
            raise RuntimeError(f"Failed to reproduce frozen Arm0 score: {case_id}")

        supported = set(arm0["supported_requirement_indices"])
        profile = gt["answerability_profile"]
        docs_required, non_docs_required = docs_requirement_split(gt, len(requirements))
        docs_value_complete = _docs_value_complete(
            docs_required, supported, requirements, decisions
        )
        mixed = score_mixed_case(
            profile=profile,
            docs_required=docs_required,
            non_docs_required=non_docs_required,
            supported=supported,
            response_mode=arm0["response_mode"],
            all_groups_cited=arm0_score["all_groups_cited"],
            docs_value_complete=docs_value_complete,
        )
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": backbone["dataset"],
                "answerability_profile": profile,
                "answerability_target": backbone["answerability_target"],
                "arm0": arm0,
                "arm0_score": arm0_score,
                "docs_value_complete": docs_value_complete,
                "mixed_metrics": mixed,
                "question_or_gold_text_included": False,
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_runtime_decision": False,
            }
        )
    return output


def _compact(value: Any) -> str:
    return "".join(str(value or "").split())


def build_fixed_backbone_generation_rows(
    *,
    ground_truth_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    backbone_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    table_view_provider: Any,
    generation_runner: Any,
) -> list[dict[str, Any]]:
    """Run generation OFF/ON on one frozen backbone result per case.

    Search, planner requirements, assembler decisions and citation slices are fixed.
    The ON arm receives a deep copy of the OFF public result and may only compose text.
    """

    ground_truth = {row["case_id"]: row for row in ground_truth_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    backbones = {row["case_id"]: row for row in backbone_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    chunk_to_parent = {
        chunk_id: row["parent_document_id"] for chunk_id, row in chunks_by_id.items()
    }

    if not (
        set(ground_truth)
        == set(enumerations)
        == set(assemblers)
        == set(backbones)
        == set(evaluations)
    ):
        raise RuntimeError("Frozen 95-case generation joins do not have identical case IDs")

    output = []
    for case_id in sorted(backbones):
        gt = ground_truth[case_id]
        enumeration = enumerations[case_id]
        assembler = assemblers[case_id]
        backbone = backbones[case_id]
        evaluation = evaluations[case_id]
        requirements = enumeration["requirements"]
        decisions = assembler["decisions"]
        if len(requirements) != len(decisions):
            raise RuntimeError(f"Planner/assembler count mismatch: {case_id}")

        gated_decisions = []
        public_requirements = []
        table_view_count = 0
        table_row_count = 0
        value_shape_veto_count = 0
        cost_relation_veto_count = 0
        for requirement, decision in zip(requirements, decisions, strict=True):
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
            table_views = (
                table_view_provider(
                    requirement,
                    source_ids=source_ids,
                    allowed_parent_document_ids=parent_ids,
                    time_scope=str(evaluation.get("time_scope") or "current"),
                )
                if decision.get("status") == "supported_exact"
                else []
            )
            checked, value_shape_audit = apply_table_value_shape_gate(
                requirement,
                decision,
                table_views,
            )
            value_shape_veto_count += bool(value_shape_audit.get("vetoed"))
            cost_relation_veto_count += bool(
                value_shape_audit.get("cost_relation_vetoed")
            )
            supported = checked.get("status") == "supported_exact"
            gated_decisions.append(checked)
            visible_table_views = table_views if supported else []
            table_view_count += len(visible_table_views)
            table_row_count += sum(
                int(view.get("row_count") or len(view.get("rows", [])))
                for view in visible_table_views
            )
            public_requirements.append(
                {
                    "requirement": dict(requirement),
                    "status": "supported" if supported else "unsupported",
                    "message": None if supported else "not_confirmable_from_documents",
                    "citations": citations if supported else [],
                    "table_views": visible_table_views,
                    "value_shape_audit": value_shape_audit,
                }
            )

        baseline_supported = {
            index
            for index, decision in enumerate(decisions, start=1)
            if decision["status"] == "supported_exact"
        }
        off_arm = simulate_arm(
            placement="arm0",
            question=evaluation["question"],
            assembler_decisions=gated_decisions,
            classifier_predictions=[],
            chunk_to_parent=chunk_to_parent,
        )
        off_score = _score_arm(
            off_arm,
            target=backbone["answerability_target"],
            evidence_groups=evaluation["evidence_groups"],
            expected_docs_flags=[True] * len(requirements),
            baseline_supported_indices=baseline_supported,
        )
        supported = set(off_arm["supported_requirement_indices"])
        profile = gt["answerability_profile"]
        docs_required, non_docs_required = docs_requirement_split(
            gt,
            len(requirements),
        )
        docs_value_complete = _docs_value_complete(
            docs_required,
            supported,
            requirements,
            gated_decisions,
        )
        mixed = score_mixed_case(
            profile=profile,
            docs_required=docs_required,
            non_docs_required=non_docs_required,
            supported=supported,
            response_mode=off_arm["response_mode"],
            all_groups_cited=off_score["all_groups_cited"],
            docs_value_complete=docs_value_complete,
        )
        public_result = {
            "question": evaluation["question"],
            "response_mode": off_arm["response_mode"],
            "requirements": public_requirements,
        }
        generation = generation_runner(copy.deepcopy(public_result))
        answer_text = str(generation.get("answer_text") or "")
        gold_tokens = []
        seen_gold_tokens = set()
        for group in evaluation["evidence_groups"]:
            for token in extract_factual_tokens(str(group.get("evidence_span") or "")):
                key = _compact(token)
                if key and key not in seen_gold_tokens:
                    seen_gold_tokens.add(key)
                    gold_tokens.append(token)
        gold_value_complete = bool(gold_tokens) and all(
            _compact(token) in _compact(answer_text) for token in gold_tokens
        )
        selected_table_value_count = sum(
            int(entry.get("table_value_span_count") or 0)
            for entry in generation.get("generatable", [])
        )
        output.append(
            {
                "generation_ab_version": GENERATION_AB_VERSION,
                "case_id": case_id,
                "dataset": backbone["dataset"],
                "answerability_profile": profile,
                "answerability_target": backbone["answerability_target"],
                "off": {
                    "arm": off_arm,
                    "score": off_score,
                    "docs_value_complete": docs_value_complete,
                    "mixed_metrics": mixed,
                    "table_view_count": table_view_count,
                    "table_row_count": table_row_count,
                    "value_shape_veto_count": value_shape_veto_count,
                    "cost_relation_veto_count": cost_relation_veto_count,
                },
                "on": {
                    "generation": generation,
                    "axes_unchanged_from_off": True,
                    "gold_factual_tokens": gold_tokens,
                    "gold_value_scoreable": bool(gold_tokens),
                    "gold_value_complete": gold_value_complete,
                    "selected_table_value_count": selected_table_value_count,
                },
                "fixed_inputs": {
                    "search_changed": False,
                    "planner_changed": False,
                    "assembler_decisions_changed": False,
                    "public_backbone_result_shared": True,
                },
            }
        )
    return output


def _generation_rows_for_two_axis(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "answerability_profile": row["answerability_profile"],
            "answerability_target": row["answerability_target"],
            "arm0": row["off"]["arm"],
            "arm0_score": row["off"]["score"],
            "docs_value_complete": row["off"]["docs_value_complete"],
            "mixed_metrics": row["off"]["mixed_metrics"],
        }
        for row in rows
    ]


def summarize_generation_ab(rows: list[dict[str, Any]]) -> dict[str, Any]:
    two_axis = summarize_two_axis(_generation_rows_for_two_axis(rows))
    model_called = [
        row
        for row in rows
        if row["on"]["generation"].get("mode")
        in {"generated", "extractive_fallback", "generation_error"}
    ]
    generated = [
        row for row in rows if row["on"]["generation"].get("used_generated_text")
    ]
    fallback = [
        row
        for row in rows
        if row["on"]["generation"].get("mode") == "extractive_fallback"
    ]
    errors = [
        row
        for row in rows
        if row["on"]["generation"].get("mode") == "generation_error"
    ]
    abstained = [
        row for row in rows if row["on"]["generation"].get("mode") == "abstain"
    ]
    table_rows = [
        row for row in rows if row["on"]["selected_table_value_count"] > 0
    ]
    scoreable = [row for row in generated if row["on"]["gold_value_scoreable"]]
    grounded_generated = [
        row for row in generated if row["off"]["score"]["grounded_answer"]
    ]
    false_full_generated = [
        row for row in generated if row["off"]["score"]["false_full_answer"]
    ]
    cost_relation_veto_rows = [
        row for row in rows if row["off"]["cost_relation_veto_count"]
    ]
    return {
        "question_count": len(rows),
        "generation_off": two_axis,
        "generation_on": {
            "two_axis": two_axis,
            "axes_identical_to_off_by_construction": all(
                row["on"]["axes_unchanged_from_off"] for row in rows
            ),
            "model_called": _ratio(len(model_called), len(rows)),
            "verified_generated": _ratio(len(generated), len(rows)),
            "extractive_fallback": _ratio(len(fallback), len(rows)),
            "generation_error": _ratio(len(errors), len(rows)),
            "mechanical_abstain_without_model": _ratio(len(abstained), len(rows)),
            "grounded_and_generated": _ratio(len(grounded_generated), len(rows)),
            "false_full_and_generated": _ratio(
                len(false_full_generated),
                len(rows),
            ),
            "cost_relation_vetoed_requirements": sum(
                row["off"]["cost_relation_veto_count"] for row in rows
            ),
            "cost_relation_vetoed_case_ids": [
                row["case_id"] for row in cost_relation_veto_rows
            ],
            "gold_value_complete_when_scoreable": _ratio(
                sum(row["on"]["gold_value_complete"] for row in scoreable),
                len(scoreable),
            ),
            "table": {
                "question_count": len(table_rows),
                "verified_generated": _ratio(
                    sum(
                        bool(row["on"]["generation"].get("used_generated_text"))
                        for row in table_rows
                    ),
                    len(table_rows),
                ),
                "gold_value_complete_when_scoreable": _ratio(
                    sum(
                        row["on"]["gold_value_complete"]
                        for row in table_rows
                        if row["on"]["gold_value_scoreable"]
                    ),
                    sum(
                        row["on"]["gold_value_scoreable"] for row in table_rows
                    ),
                ),
            },
            "generated_case_ids": [row["case_id"] for row in generated],
            "fallback_case_ids": [row["case_id"] for row in fallback],
            "generation_error_case_ids": [row["case_id"] for row in errors],
            "false_full_generated_case_ids": [
                row["case_id"] for row in false_full_generated
            ],
        },
        "interpretation_limit": (
            "Verification proves selected numeric/date/table tokens are grounded. "
            "It does not semantically judge unrestricted text paraphrases."
        ),
    }


def summarize_two_axis(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    docs = [r for r in case_rows if r["answerability_profile"] == DOCS_PROFILE]
    mixed = [r for r in case_rows if r["answerability_profile"] == MIXED_PROFILE]
    reject = [r for r in case_rows if r["answerability_target"] == "reject"]
    realtime = [r for r in case_rows if r["answerability_target"] == "realtime_api"]

    def s(rows: list[dict[str, Any]], picker) -> int:
        return sum(1 for r in rows if picker(r))

    docs_metrics = {
        "docs_only_grounded": _ratio(s(docs, lambda r: r["arm0_score"]["grounded_answer"]), len(docs)),
        "docs_only_grounded_span_strict": _ratio(
            s(docs, lambda r: r["arm0_score"]["grounded_answer"] and r["docs_value_complete"]),
            len(docs),
        ),
        "docs_only_false_partial": _ratio(s(docs, lambda r: r["arm0_score"]["false_partial"]), len(docs)),
        "docs_only_false_full": _ratio(s(docs, lambda r: r["arm0_score"]["false_full_answer"]), len(docs)),
        "docs_only_honest_partial": _ratio(s(docs, lambda r: r["arm0_score"]["honest_partial"]), len(docs)),
        "docs_only_overreject": _ratio(s(docs, lambda r: r["arm0_score"]["answerable_overreject"]), len(docs)),
    }
    mixed_metrics = {
        "correct_mixed_partial": _ratio(s(mixed, lambda r: r["mixed_metrics"]["correct_mixed_partial"]), len(mixed)),
        "correct_mixed_partial_span_strict": _ratio(
            s(mixed, lambda r: r["mixed_metrics"]["correct_mixed_partial_span_strict"]), len(mixed)
        ),
        "mixed_overclaim": _ratio(s(mixed, lambda r: r["mixed_metrics"]["mixed_overclaim"]), len(mixed)),
        "mixed_overreject": _ratio(s(mixed, lambda r: r["mixed_metrics"]["mixed_overreject"]), len(mixed)),
        "mixed_missing_evidence": _ratio(s(mixed, lambda r: r["mixed_metrics"]["mixed_missing_evidence"]), len(mixed)),
        "primary_label_counts": dict(
            sorted(Counter(r["mixed_metrics"]["primary_mixed_label"] for r in mixed).items())
        ),
    }
    return {
        "profile_counts": dict(
            sorted(Counter(r["answerability_profile"] for r in case_rows).items())
        ),
        "docs_only": {"question_count": len(docs), **docs_metrics},
        "mixed": {"question_count": len(mixed), **mixed_metrics},
        "reject_correct": _ratio(s(reject, lambda r: r["arm0_score"]["reject_correct"]), len(reject)),
        "realtime_safe_abstain": _ratio(s(realtime, lambda r: r["arm0_score"]["realtime_safe_abstain"]), len(realtime)),
    }


def legacy_proxy(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The collapsed answerable_docs=82 view, reproduced unchanged for continuity."""
    docs = [r for r in case_rows if r["answerability_target"] == "answerable_docs"]
    reject = [r for r in case_rows if r["answerability_target"] == "reject"]
    realtime = [r for r in case_rows if r["answerability_target"] == "realtime_api"]
    return {
        "answerable_docs_question_count": len(docs),
        "grounded_answer": _ratio(sum(r["arm0_score"]["grounded_answer"] for r in docs), len(docs)),
        "false_full_answer": _ratio(sum(r["arm0_score"]["false_full_answer"] for r in docs), len(docs)),
        "false_partial": _ratio(sum(r["arm0_score"]["false_partial"] for r in docs), len(docs)),
        "honest_partial": _ratio(sum(r["arm0_score"]["honest_partial"] for r in docs), len(docs)),
        "reject_correct": _ratio(sum(r["arm0_score"]["reject_correct"] for r in reject), len(reject)),
        "realtime_safe_abstain": _ratio(sum(r["arm0_score"]["realtime_safe_abstain"] for r in realtime), len(realtime)),
    }


def _render_markdown(report: dict[str, Any]) -> bytes:
    legacy = report["legacy_proxy"]
    two = report["two_axis"]
    docs = two["docs_only"]
    mixed = two["mixed"]
    lines = [
        "# Router backbone mixed-answerability metrics (v3.2)",
        "",
        "Development-only re-scoring of the frozen 95 questions on two axes. No runtime, gold,",
        "or frozen report changed. Legacy collapsed metrics are preserved as `legacy_proxy`.",
        "",
        "## Legacy proxy (collapsed answerable_docs = 82, unchanged)",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Grounded | {legacy['grounded_answer']['successes']}/82 |",
        f"| False full | {legacy['false_full_answer']['successes']}/82 |",
        f"| False partial | {legacy['false_partial']['successes']}/82 |",
        f"| Honest partial | {legacy['honest_partial']['successes']}/82 |",
        "",
        "## Two-axis corrected view",
        "",
        f"Profile counts: {two['profile_counts']}.",
        "",
        f"### docs_only ({docs['question_count']})",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Grounded (chunk) | {docs['docs_only_grounded']['successes']}/{docs['question_count']} |",
        f"| Grounded (span-value strict) | {docs['docs_only_grounded_span_strict']['successes']}/{docs['question_count']} |",
        f"| False partial | {docs['docs_only_false_partial']['successes']}/{docs['question_count']} |",
        f"| False full | {docs['docs_only_false_full']['successes']}/{docs['question_count']} |",
        "",
        f"### mixed ({mixed['question_count']})",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Correct mixed-partial | {mixed['correct_mixed_partial']['successes']}/{mixed['question_count']} |",
        f"| Correct mixed-partial (span strict) | {mixed['correct_mixed_partial_span_strict']['successes']}/{mixed['question_count']} |",
        f"| Mixed over-claim (safety) | {mixed['mixed_overclaim']['successes']}/{mixed['question_count']} |",
        f"| Mixed over-reject | {mixed['mixed_overreject']['successes']}/{mixed['question_count']} |",
        f"| Mixed missing evidence | {mixed['mixed_missing_evidence']['successes']}/{mixed['question_count']} |",
        f"| Primary label counts | {mixed['primary_label_counts']} |",
        "",
        f"Reject correct: {two['reject_correct']['successes']}/{two['reject_correct']['total']}. "
        f"Realtime safe abstain: {two['realtime_safe_abstain']['successes']}/{two['realtime_safe_abstain']['total']}.",
        "",
        "Legacy grounded counts mixed over-claims as correct and correct mixed-partials as",
        "false_partial. The two-axis view separates them; it re-scores existing behavior and",
        "promotes nothing.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": root / DEFAULT_ASSEMBLER,
        "backbone_cases": root / DEFAULT_BACKBONE,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "value_shape_source": root / "src/v3/requirement_value_shape.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    case_rows = build_case_rows(
        ground_truth_rows=read_jsonl(inputs["answerability_ground_truth"]),
        enumeration_rows=read_jsonl(inputs["enumeration"]),
        assembler_rows=read_jsonl(inputs["assembler_cases"]),
        backbone_rows=read_jsonl(inputs["backbone_cases"]),
        evaluation_rows=read_jsonl(inputs["adaptive_dev"]) + read_jsonl(inputs["downgraded_canary"]),
        chunks=read_jsonl(inputs["chunks"]),
    )
    legacy = legacy_proxy(case_rows)
    two_axis = summarize_two_axis(case_rows)
    if legacy["grounded_answer"]["successes"] != 73 or legacy["false_partial"]["successes"] != 2:
        raise RuntimeError(f"Legacy proxy did not reproduce frozen 73/2: {legacy}")
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "value_shape_version": VALUE_SHAPE_VERSION,
        "evaluation_role": "development_only_two_axis_rescore_no_promotion",
        "legacy_proxy": legacy,
        "two_axis": two_axis,
        "constraints": {
            "search_changed": False,
            "router_changed": False,
            "planner_changed": False,
            "assembler_selection_changed": False,
            "gold_or_labels_changed": False,
            "model_inference_calls": 0,
            "runtime_or_canonical_promoted": False,
        },
        "inputs": {
            name: {"path": path.resolve().relative_to(root).as_posix(), "sha256": before[name]}
            for name, path in inputs.items()
        },
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(case_rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"router_backbone_mixed_metrics_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)

    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"router_backbone_mixed_metrics_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _render_markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"router_backbone_mixed_metrics_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("A frozen input changed during evaluation")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": report["inputs"],
        "artifacts": {
            "cases": {"path": cases_path.relative_to(root).as_posix(), "sha256": cases_sha, "row_count": len(case_rows)},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"router_backbone_mixed_metrics_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "cases": str(cases_path),
        "report": str(report_path),
        "report_markdown": str(markdown_path),
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "legacy_proxy": legacy,
        "two_axis": two_axis,
    }


def evaluate_generation_ab(
    root: Path,
    *,
    generator_model: str = "qwen3:8b",
    device: str | None = None,
    timeout: float = 180.0,
    assembler_cases: Path | None = None,
    generation_evidence_scope: str = "chunk",
) -> dict[str, Any]:
    """Measure only the answer-composition delta on the frozen 95-case backbone.

    ``assembler_cases`` swaps in a different span-selection run. The reference two-axis
    numbers always come from the frozen assembler, so the reported delta stays anchored
    to the same baseline no matter which selection is under test.
    """

    from src.v3.gradio_backbone_demo import DemoBackbone

    root = root.resolve()
    inputs = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": (root / assembler_cases) if assembler_cases else (root / DEFAULT_ASSEMBLER),
        "reference_assembler_cases": root / DEFAULT_ASSEMBLER,
        "backbone_cases": root / DEFAULT_BACKBONE,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "chunks": root / DEFAULT_CHUNKS,
        "generator_source": root / "src/v3/grounded_answer_generator.py",
        "demo_source": root / "src/v3/gradio_backbone_demo.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    ground_truth_rows = read_jsonl(inputs["answerability_ground_truth"])
    enumeration_rows = read_jsonl(inputs["enumeration"])
    assembler_rows = read_jsonl(inputs["assembler_cases"])
    reference_assembler_rows = read_jsonl(inputs["reference_assembler_cases"])
    backbone_rows = read_jsonl(inputs["backbone_cases"])
    evaluation_rows = read_jsonl(inputs["adaptive_dev"]) + read_jsonl(
        inputs["downgraded_canary"]
    )
    chunks = read_jsonl(inputs["chunks"])

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    runtime = DemoBackbone(
        root=root,
        planner_model="qwen3:8b",
        device=device,
        timeout=timeout,
        enable_v3_2_candidates=True,
        enable_generation=True,
        generator_model=generator_model,
        generation_evidence_scope=generation_evidence_scope,
    )
    runtime._initialize()
    table_parent_ids = {
        str(row["parent_document_id"]) for row in runtime._table_facts
    }

    def table_view_provider(
        requirement: dict[str, Any],
        *,
        source_ids: tuple[str, ...],
        allowed_parent_document_ids: tuple[str, ...],
        time_scope: str,
    ) -> list[dict[str, Any]]:
        if not (
            set(allowed_parent_document_ids) & table_parent_ids
        ):
            return []
        return runtime._table_views(
            requirement,
            source_ids=source_ids,
            allowed_parent_document_ids=allowed_parent_document_ids,
            time_scope=time_scope,
        )

    def generation_runner(public_result: dict[str, Any]) -> dict[str, Any]:
        finalized = runtime._finalize_result(
            public_result,
            started=time.perf_counter(),
        )
        return finalized["generation"]

    rows = build_fixed_backbone_generation_rows(
        ground_truth_rows=ground_truth_rows,
        enumeration_rows=enumeration_rows,
        assembler_rows=assembler_rows,
        backbone_rows=backbone_rows,
        evaluation_rows=evaluation_rows,
        chunks=chunks,
        table_view_provider=table_view_provider,
        generation_runner=generation_runner,
    )
    reference_rows = build_case_rows(
        ground_truth_rows=ground_truth_rows,
        enumeration_rows=enumeration_rows,
        assembler_rows=reference_assembler_rows,
        backbone_rows=backbone_rows,
        evaluation_rows=evaluation_rows,
        chunks=chunks,
    )
    summary = summarize_generation_ab(rows)
    reference_two_axis = summarize_two_axis(reference_rows)

    def delta(path: tuple[str, ...]) -> int:
        reference: Any = reference_two_axis
        current: Any = summary["generation_off"]
        for key in path:
            reference = reference[key]
            current = current[key]
        return int(current["successes"]) - int(reference["successes"])

    report = {
        "report_schema_version": "router-backbone-generation-ab-report-v1",
        "evaluator_version": GENERATION_AB_VERSION,
        "evaluation_role": "development_only_fixed_backbone_generation_ab",
        "generator_model": generator_model,
        "reference_frozen_two_axis": reference_two_axis,
        "generation_ab": summary,
        "gate_and_table_wiring_delta_vs_frozen_reference": {
            "docs_only_grounded": delta(
                ("docs_only", "docs_only_grounded")
            ),
            "docs_only_grounded_span_strict": delta(
                ("docs_only", "docs_only_grounded_span_strict")
            ),
            "docs_only_false_full": delta(
                ("docs_only", "docs_only_false_full")
            ),
            "mixed_overclaim": delta(("mixed", "mixed_overclaim")),
        },
        "constraints": {
            "search_changed": False,
            "planner_changed": False,
            "assembler_decisions_changed": assembler_cases is not None,
            "same_public_backbone_result_for_off_and_on": True,
            "generation_path": (
                "DemoBackbone._finalize_result -> compose_backbone_answer"
            ),
            "table_scope": "already_cited_parent_documents_only",
            "generation_evidence_scope": generation_evidence_scope,
            "model_inference_calls": summary["generation_on"]["model_called"][
                "successes"
            ],
            "runtime_or_canonical_promoted": False,
        },
        "inputs": {
            name: {
                "path": path.resolve().relative_to(root).as_posix(),
                "sha256": before[name],
            }
            for name, path in inputs.items()
        },
    }

    cases_bytes = _serialize_jsonl(rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = (
        root
        / "outputs/v3"
        / f"router_backbone_generation_ab_cases_{cases_sha}.jsonl"
    )
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = (
        root / "reports/v3" / f"router_backbone_generation_ab_{report_sha}.json"
    )
    write_immutable(report_path, report_bytes)

    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("A fixed generation A/B input changed during evaluation")
    return {
        "cases": cases_path.relative_to(root).as_posix(),
        "report": report_path.relative_to(root).as_posix(),
        **report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Two-axis mixed-answerability re-scoring (development only)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--generation-ab", action="store_true")
    parser.add_argument("--generator-model", default="qwen3:8b")
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--assembler-cases",
        type=Path,
        help="Repo-relative assembler decisions to test instead of the frozen ones",
    )
    parser.add_argument(
        "--generation-evidence-scope",
        choices=("span", "chunk"),
        default="chunk",
        help="What the generator sees: the selected spans, or their whole parent chunks",
    )
    args = parser.parse_args()
    result = (
        evaluate_generation_ab(
            args.root,
            generator_model=args.generator_model,
            device=args.device,
            assembler_cases=args.assembler_cases,
            generation_evidence_scope=args.generation_evidence_scope,
            timeout=args.timeout,
        )
        if args.generation_ab
        else evaluate_and_freeze(args.root)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
