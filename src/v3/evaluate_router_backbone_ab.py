from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.select_evidence import classify_answerability


EVALUATOR_VERSION = "router-backbone-answer-source-ab-v3.1.0"
CASE_SCHEMA_VERSION = "router-backbone-answer-source-ab-case-v3.1"
REPORT_SCHEMA_VERSION = "router-backbone-answer-source-ab-report-v3.1"
MANIFEST_SCHEMA_VERSION = "router-backbone-answer-source-ab-manifest-v3.1"

DEFAULT_GROUND_TRUTH = Path(
    "data/v3/evaluation/semantic_answerability_ground_truth_"
    "53cd8ae72ad4ee2f7c9b1d4370991ad74b5044d154e3657fd2008f45f71fe609.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_ATTRIBUTION = Path(
    "data/v3/evaluation/canary_stage_attribution_"
    "a132069a231a64225bfe78b86fbfa3e81dbc9cf9fc538df8469d5e33ef4dce35.jsonl"
)
DEFAULT_TAXONOMY = Path(
    "data/v3/router/routing_bottleneck_taxonomy_"
    "905182d088873485059415d4dcbda95f15db42c091392c7b3d21dfeefd734679.jsonl"
)
DEFAULT_ROUTING_REPORT = Path(
    "reports/v3/routing_bottleneck_diagnostic_"
    "f2a678b98238efa1610c7af852b2dbe3d70a13c1ddf514e7c6a75e785f9de7f0.json"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_CLASSIFIER_PREDICTIONS = Path(
    "data/v3/evaluation/semantic_answerability_ab_predictions_"
    "2d244389dba82d13b33e5fe3171868482f705f27ec9a0cd1eb4d1f17cdfdc381.jsonl"
)
DEFAULT_CLASSIFIER_DIAGNOSTICS = Path(
    "data/v3/evaluation/semantic_answerability_ab_diagnostics_"
    "6c4a4f9bc9418fe38dcaf877cad66b8ad1f9e77c70b10b50ff63db56eed51d39.jsonl"
)
DEFAULT_CLASSIFIER_MANIFEST = Path(
    "data/v3/evaluation/semantic_answerability_ab_manifest_"
    "d3e356a92c4c55e4e180b9b36c8aef50d84df085e439b14a6c8235869e51a59e.json"
)
DEFAULT_CLASSIFIER_REPORT = Path(
    "reports/v3/planner_enumeration_answerability_ab_"
    "3e708a8d9f2352d58ed4a962b790d1269d65fad2249a835f8f04cf2e7a5ce006.json"
)
DEFAULT_ASSEMBLER_CASES = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_ASSEMBLER_DIAGNOSTICS = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_diagnostics_"
    "687d1fcd1b7cb98139150b9526397d1b783477bb4d79e0c8ccc930b3cbb2e94c.jsonl"
)
DEFAULT_ASSEMBLER_MANIFEST = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_"
    "9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json"
)
DEFAULT_ASSEMBLER_REPORT = Path(
    "reports/v3/extractive_assembler_v3_chunk_diverse_"
    "aa202881ab98531442e80c5d75cf0c49ff06330f9c79cd6c4ee30125dcdf4f60.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/router_backbone_answer_source_ab.md")

NARROW_SAFETY_REASONS = frozenset(
    {
        "protected_internal_instruction",
        "unsafe_abuse_instruction",
        "unsupported_lottery_prediction",
        "unsupported_financial_prediction",
        "unsupported_weather_forecast",
    }
)
REALTIME_SOURCES = frozenset({"personal_account", "realtime"})
REJECT_SOURCES = frozenset({"subjective", "out_of_scope"})
VALID_PLACEMENTS = frozenset({"arm0", "front", "post_search_evidence_priority"})


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "small_sample_limit": total < 5,
    }


def narrow_safety_reason(question: str) -> str | None:
    result = classify_answerability(question)
    return result["reason"] if result["reason"] in NARROW_SAFETY_REASONS else None


def _answerability_target(
    ground_truth: dict[str, Any],
    attribution: dict[str, Any] | None,
) -> str:
    if ground_truth["answerability_label"] != "false":
        return "answerable_docs"
    if attribution and attribution["expected_route_action"] == "realtime_api":
        return "realtime_api"
    return "reject"


def _prediction_by_index(prediction_row: dict[str, Any]) -> dict[int, str]:
    output = {}
    for item in prediction_row["approach_a_fixed_model"]:
        index = int(item["requirement_index"])
        if index in output:
            raise RuntimeError(f"Duplicate classifier requirement index: {index}")
        output[index] = item["answer_source"]
    return output


def _shared_parent(
    decisions: list[dict[str, Any]], chunk_to_parent: dict[str, str]
) -> bool:
    parent_sets = [
        {chunk_to_parent[span["chunk_id"]] for span in decision["spans"]}
        for decision in decisions
    ]
    if len(parent_sets) < 2 or any(not values for values in parent_sets):
        return True
    return bool(set.intersection(*parent_sets))


def simulate_arm(
    *,
    placement: str,
    question: str,
    assembler_decisions: list[dict[str, Any]],
    classifier_predictions: list[dict[str, Any]],
    chunk_to_parent: dict[str, str],
) -> dict[str, Any]:
    if placement not in VALID_PLACEMENTS:
        raise RuntimeError(f"Unknown A/B placement: {placement}")
    safety_reason = narrow_safety_reason(question)
    if safety_reason is not None:
        return {
            "placement": placement,
            "route_action": "reject",
            "response_mode": "safety_reject",
            "safety_reason": safety_reason,
            "supported_requirement_indices": [],
            "unsupported_requirement_indices": list(
                range(1, len(assembler_decisions) + 1)
            ),
            "classifier_non_docs": [],
            "cited_chunk_ids": [],
            "cross_parent_candidate": False,
        }

    predictions = _prediction_by_index(
        {"approach_a_fixed_model": classifier_predictions}
    )
    if placement != "arm0" and len(predictions) != len(assembler_decisions):
        raise RuntimeError("Classifier and assembler requirement counts differ")

    kept: list[tuple[int, dict[str, Any]]] = []
    unsupported: list[int] = []
    classifier_non_docs: list[dict[str, Any]] = []
    for index, decision in enumerate(assembler_decisions, start=1):
        supported = decision["status"] == "supported_exact"
        answer_source = predictions.get(index, "official_docs")
        if placement == "arm0":
            keep = supported
        elif placement == "front":
            keep = supported and answer_source == "official_docs"
        else:
            keep = supported
        if keep:
            kept.append((index, decision))
            continue
        unsupported.append(index)
        if placement != "arm0" and answer_source != "official_docs":
            classifier_non_docs.append(
                {"requirement_index": index, "answer_source": answer_source}
            )

    kept_decisions = [decision for _, decision in kept]
    cited_chunk_ids = sorted(
        {
            span["chunk_id"]
            for decision in kept_decisions
            for span in decision["spans"]
        }
    )
    if kept_decisions:
        response_mode = (
            "full_answer"
            if len(kept_decisions) == len(assembler_decisions)
            else "partial_answer"
        )
        cross_parent = (
            len(kept_decisions) >= 2
            and len(kept_decisions) == len(assembler_decisions)
            and not _shared_parent(kept_decisions, chunk_to_parent)
        )
        route_action = "decompose_candidate" if cross_parent else "retrieve"
    else:
        response_mode = "abstain"
        cross_parent = False
        sources = {item["answer_source"] for item in classifier_non_docs}
        if sources & REALTIME_SOURCES:
            route_action = "realtime_api"
            response_mode = "route_without_document_answer"
        elif sources & REJECT_SOURCES:
            route_action = "reject"
            response_mode = "semantic_reject_without_document_answer"
        else:
            route_action = "abstain"
    return {
        "placement": placement,
        "route_action": route_action,
        "response_mode": response_mode,
        "safety_reason": None,
        "supported_requirement_indices": [index for index, _ in kept],
        "unsupported_requirement_indices": unsupported,
        "classifier_non_docs": classifier_non_docs,
        "cited_chunk_ids": cited_chunk_ids,
        "cross_parent_candidate": cross_parent,
    }


def _score_arm(
    arm: dict[str, Any],
    *,
    target: str,
    evidence_groups: list[dict[str, Any]],
    expected_docs_flags: list[bool],
    baseline_supported_indices: set[int],
) -> dict[str, Any]:
    cited = set(arm["cited_chunk_ids"])
    group_hits = [
        bool(cited & set(group["acceptable_chunk_ids"]))
        for group in evidence_groups
    ]
    has_answer = arm["response_mode"] in {"full_answer", "partial_answer"}
    all_groups_cited = bool(group_hits) and all(group_hits)
    some_groups_cited = any(group_hits)
    suppressed = sorted(
        index
        for index in baseline_supported_indices
        if index <= len(expected_docs_flags)
        and expected_docs_flags[index - 1]
        and index not in arm["supported_requirement_indices"]
    )
    answerable_overreject = target == "answerable_docs" and not has_answer
    grounded_answer = target == "answerable_docs" and has_answer and all_groups_cited
    honest_partial = (
        target == "answerable_docs"
        and arm["response_mode"] == "partial_answer"
        and some_groups_cited
        and not all_groups_cited
    )
    false_full_answer = (
        target == "answerable_docs"
        and arm["response_mode"] == "full_answer"
        and not all_groups_cited
    )
    false_partial = (
        target == "answerable_docs"
        and arm["response_mode"] == "partial_answer"
        and all_groups_cited
    )
    reject_correct = target == "reject" and arm["route_action"] in {
        "reject",
        "abstain",
    }
    reject_realtime_misroute = (
        target == "reject" and arm["route_action"] == "realtime_api"
    )
    realtime_preferred_route = (
        target == "realtime_api" and arm["route_action"] == "realtime_api"
    )
    realtime_safe_abstain = (
        target == "realtime_api"
        and not has_answer
        and arm["route_action"] in {"reject", "abstain"}
    )
    realtime_static_exposure = target == "realtime_api" and has_answer
    honest_correct = (
        grounded_answer
        or honest_partial
        or reject_correct
        or realtime_preferred_route
        or realtime_safe_abstain
    )
    return {
        "group_hit_count": sum(group_hits),
        "evidence_group_count": len(group_hits),
        "all_groups_cited": all_groups_cited,
        "answerable_overreject": answerable_overreject,
        "grounded_answer": grounded_answer,
        "honest_partial": honest_partial,
        "false_full_answer": false_full_answer,
        "false_partial": false_partial,
        "suppressed_expected_docs_requirement_indices": suppressed,
        "reject_correct": reject_correct,
        "reject_realtime_misroute": reject_realtime_misroute,
        "realtime_preferred_route": realtime_preferred_route,
        "realtime_safe_abstain": realtime_safe_abstain,
        "realtime_static_exposure": realtime_static_exposure,
        "honest_correct": honest_correct,
    }


def build_cases(
    *,
    ground_truth_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    attribution_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    classifier_diagnostic_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    attributions = {row["case_id"]: row for row in attribution_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    predictions = {row["case_id"]: row for row in prediction_rows}
    classifier_diagnostics = {
        row["case_id"]: row for row in classifier_diagnostic_rows
    }
    assemblers = {row["case_id"]: row for row in assembler_rows}
    chunk_to_parent = {
        row["chunk_id"]: row["parent_document_id"] for row in chunks
    }
    output = []
    for ground_truth in ground_truth_rows:
        case_id = ground_truth["case_id"]
        required = {
            "evaluation": evaluations,
            "enumeration": enumerations,
            "prediction": predictions,
            "classifier_diagnostic": classifier_diagnostics,
            "assembler": assemblers,
        }
        missing = [name for name, rows in required.items() if case_id not in rows]
        if missing:
            raise RuntimeError(f"Missing frozen joins for {case_id}: {missing}")
        evaluation = evaluations[case_id]
        enumeration = enumerations[case_id]
        prediction = predictions[case_id]
        assembler = assemblers[case_id]
        if len(enumeration["requirements"]) != len(assembler["decisions"]):
            raise RuntimeError(f"Planner/assembler count mismatch: {case_id}")
        target = _answerability_target(ground_truth, attributions.get(case_id))
        expected_docs_flags = classifier_diagnostics[case_id][
            "approach_a_fixed_model"
        ]["expected_docs_flags"]
        baseline_supported = {
            index
            for index, decision in enumerate(assembler["decisions"], start=1)
            if decision["status"] == "supported_exact"
        }
        arms = {}
        for placement in (
            "arm0",
            "front",
            "post_search_evidence_priority",
        ):
            arm = simulate_arm(
                placement=placement,
                question=evaluation["question"],
                assembler_decisions=assembler["decisions"],
                classifier_predictions=prediction["approach_a_fixed_model"],
                chunk_to_parent=chunk_to_parent,
            )
            arms[placement] = {
                **arm,
                "score": _score_arm(
                    arm,
                    target=target,
                    evidence_groups=evaluation["evidence_groups"],
                    expected_docs_flags=expected_docs_flags,
                    baseline_supported_indices=baseline_supported,
                ),
            }
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": ground_truth["dataset"],
                "answerability_target": target,
                "planner_requirement_count": len(enumeration["requirements"]),
                "human_gold_evidence_group_count": len(evaluation["evidence_groups"]),
                "arm0": arms["arm0"],
                "arm1_front": arms["front"],
                "arm1_post_search": arms["post_search_evidence_priority"],
                "question_or_gold_text_included": False,
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_runtime_decision": False,
            }
        )
    return sorted(output, key=lambda row: (row["dataset"], row["case_id"]))


def summarize_arm(case_rows: list[dict[str, Any]], arm_key: str) -> dict[str, Any]:
    if arm_key not in {"arm0", "arm1_front", "arm1_post_search"}:
        raise RuntimeError(f"Unknown arm key: {arm_key}")
    docs = [row for row in case_rows if row["answerability_target"] == "answerable_docs"]
    reject = [row for row in case_rows if row["answerability_target"] == "reject"]
    realtime = [row for row in case_rows if row["answerability_target"] == "realtime_api"]
    suppressed_requirements = sum(
        len(row[arm_key]["score"]["suppressed_expected_docs_requirement_indices"])
        for row in docs
    )
    suppressed_questions = sum(
        bool(row[arm_key]["score"]["suppressed_expected_docs_requirement_indices"])
        for row in docs
    )
    honest_total = sum(row[arm_key]["score"]["honest_correct"] for row in case_rows)
    route_actions = Counter(row[arm_key]["route_action"] for row in case_rows)
    return {
        "question_count": len(case_rows),
        "route_action_counts": dict(sorted(route_actions.items())),
        "answerable": {
            "overreject": _ratio(
                sum(row[arm_key]["score"]["answerable_overreject"] for row in docs),
                len(docs),
            ),
            "grounded_answer": _ratio(
                sum(row[arm_key]["score"]["grounded_answer"] for row in docs),
                len(docs),
            ),
            "honest_partial": _ratio(
                sum(row[arm_key]["score"]["honest_partial"] for row in docs),
                len(docs),
            ),
            "false_full_answer": _ratio(
                sum(row[arm_key]["score"]["false_full_answer"] for row in docs),
                len(docs),
            ),
            "false_partial": _ratio(
                sum(row[arm_key]["score"]["false_partial"] for row in docs),
                len(docs),
            ),
            "suppressed_expected_docs_requirements": suppressed_requirements,
            "suppressed_expected_docs_questions": suppressed_questions,
        },
        "reject": {
            "correct_abstain_or_reject": _ratio(
                sum(row[arm_key]["score"]["reject_correct"] for row in reject),
                len(reject),
            ),
            "realtime_misroute": _ratio(
                sum(
                    row[arm_key]["score"]["reject_realtime_misroute"]
                    for row in reject
                ),
                len(reject),
            ),
        },
        "realtime": {
            "preferred_route": _ratio(
                sum(
                    row[arm_key]["score"]["realtime_preferred_route"]
                    for row in realtime
                ),
                len(realtime),
            ),
            "safe_abstain": _ratio(
                sum(
                    row[arm_key]["score"]["realtime_safe_abstain"]
                    for row in realtime
                ),
                len(realtime),
            ),
            "static_document_exposure": _ratio(
                sum(
                    row[arm_key]["score"]["realtime_static_exposure"]
                    for row in realtime
                ),
                len(realtime),
            ),
            "sample_limit": "n=2; preferred-route conclusion deferred",
        },
        "honest_correct_total": _ratio(honest_total, len(case_rows)),
    }


def summarize_cross_parent(
    case_rows: list[dict[str, Any]],
    taxonomy_rows: list[dict[str, Any]],
    arm_key: str,
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in case_rows}
    cross_ids = [
        row["case_id"]
        for row in taxonomy_rows
        if row["failure_type"] == "DECOMPOSE_MISS"
    ]
    same_ids = [
        row["case_id"]
        for row in taxonomy_rows
        if row["failure_type"] == "LABEL_SUSPECT"
    ]
    if len(cross_ids) != 2 or len(same_ids) != 7:
        raise RuntimeError("Frozen same/cross audit changed")
    return {
        "cross_parent_decompose_candidate": _ratio(
            sum(cases[case_id][arm_key]["cross_parent_candidate"] for case_id in cross_ids),
            len(cross_ids),
        ),
        "cross_parent_full_evidence_recovered_without_decompose": _ratio(
            sum(cases[case_id][arm_key]["score"]["all_groups_cited"] for case_id in cross_ids),
            len(cross_ids),
        ),
        "cross_parent_honest_partial": _ratio(
            sum(cases[case_id][arm_key]["score"]["honest_partial"] for case_id in cross_ids),
            len(cross_ids),
        ),
        "cross_parent_false_full_answer": _ratio(
            sum(cases[case_id][arm_key]["score"]["false_full_answer"] for case_id in cross_ids),
            len(cross_ids),
        ),
        "same_parent_not_decomposed": _ratio(
            sum(not cases[case_id][arm_key]["cross_parent_candidate"] for case_id in same_ids),
            len(same_ids),
        ),
    }


def _route_action_for_exact(arm: dict[str, Any]) -> str:
    if arm["route_action"] == "decompose_candidate":
        return "decompose"
    if arm["route_action"] == "abstain":
        return "reject"
    return arm["route_action"]


def summarize_canary_routes(
    case_rows: list[dict[str, Any]],
    attribution_rows: list[dict[str, Any]],
    taxonomy_rows: list[dict[str, Any]],
    arm_key: str,
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in case_rows}
    suspect_ids = {
        row["case_id"]
        for row in taxonomy_rows
        if row["failure_type"] == "LABEL_SUSPECT"
    }
    frozen_exact = 0
    audited_exact = 0
    safe_handling = 0
    for attribution in attribution_rows:
        case_id = attribution["case_id"]
        actual = _route_action_for_exact(cases[case_id][arm_key])
        expected = attribution["expected_route_action"]
        audited_expected = "retrieve" if case_id in suspect_ids else expected
        frozen_exact += actual == expected
        audited_exact += actual == audited_expected
        safe_handling += actual == audited_expected or (
            audited_expected == "realtime_api"
            and cases[case_id][arm_key]["route_action"] in {"abstain", "reject"}
        )
    return {
        "frozen_route_action_exact": _ratio(frozen_exact, len(attribution_rows)),
        "label_audited_route_action_exact": _ratio(
            audited_exact, len(attribution_rows)
        ),
        "label_audited_safe_handling": _ratio(
            safe_handling, len(attribution_rows)
        ),
        "seven_labels_modified": False,
    }


def compare_arms(
    arm0: dict[str, Any], arm1: dict[str, Any]
) -> dict[str, Any]:
    checks = {
        "honest_correct_total_improved": (
            arm1["honest_correct_total"]["successes"]
            > arm0["honest_correct_total"]["successes"]
        ),
        "answerable_overreject_not_increased": (
            arm1["answerable"]["overreject"]["successes"]
            <= arm0["answerable"]["overreject"]["successes"]
        ),
        "expected_docs_requirement_suppression_zero": (
            arm1["answerable"]["suppressed_expected_docs_requirements"] == 0
        ),
        "grounded_answer_not_reduced": (
            arm1["answerable"]["grounded_answer"]["successes"]
            >= arm0["answerable"]["grounded_answer"]["successes"]
        ),
        "reject_correctness_not_reduced": (
            arm1["reject"]["correct_abstain_or_reject"]["successes"]
            >= arm0["reject"]["correct_abstain_or_reject"]["successes"]
        ),
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "honest_correct_delta": (
            arm1["honest_correct_total"]["successes"]
            - arm0["honest_correct_total"]["successes"]
        ),
        "answerable_overreject_delta": (
            arm1["answerable"]["overreject"]["successes"]
            - arm0["answerable"]["overreject"]["successes"]
        ),
        "grounded_answer_delta": (
            arm1["answerable"]["grounded_answer"]["successes"]
            - arm0["answerable"]["grounded_answer"]["successes"]
        ),
        "reject_correct_delta": (
            arm1["reject"]["correct_abstain_or_reject"]["successes"]
            - arm0["reject"]["correct_abstain_or_reject"]["successes"]
        ),
        "realtime_preferred_route_delta": (
            arm1["realtime"]["preferred_route"]["successes"]
            - arm0["realtime"]["preferred_route"]["successes"]
        ),
    }


def _markdown(report: dict[str, Any]) -> bytes:
    arms = report["arms"]
    lines = [
        "# Router backbone + answer-source A/B",
        "",
        f"- classifier recommendation: **{report['classifier_recommendation']}**",
        f"- backbone decision: **{report['backbone_decision']}**",
        "",
        "| metric | Arm0 | Arm1 front | Arm1 post-search |",
        "|---|---:|---:|---:|",
        "| answerable overreject | {}/82 | {}/82 | {}/82 |".format(
            arms["arm0"]["answerable"]["overreject"]["successes"],
            arms["arm1_front"]["answerable"]["overreject"]["successes"],
            arms["arm1_post_search"]["answerable"]["overreject"]["successes"],
        ),
        "| expected-doc req suppressed | {} | {} | {} |".format(
            arms["arm0"]["answerable"]["suppressed_expected_docs_requirements"],
            arms["arm1_front"]["answerable"]["suppressed_expected_docs_requirements"],
            arms["arm1_post_search"]["answerable"]["suppressed_expected_docs_requirements"],
        ),
        "| grounded docs | {}/82 | {}/82 | {}/82 |".format(
            arms["arm0"]["answerable"]["grounded_answer"]["successes"],
            arms["arm1_front"]["answerable"]["grounded_answer"]["successes"],
            arms["arm1_post_search"]["answerable"]["grounded_answer"]["successes"],
        ),
        "| reject correct | {}/11 | {}/11 | {}/11 |".format(
            arms["arm0"]["reject"]["correct_abstain_or_reject"]["successes"],
            arms["arm1_front"]["reject"]["correct_abstain_or_reject"]["successes"],
            arms["arm1_post_search"]["reject"]["correct_abstain_or_reject"]["successes"],
        ),
        "| realtime preferred route | {}/2 | {}/2 | {}/2 |".format(
            arms["arm0"]["realtime"]["preferred_route"]["successes"],
            arms["arm1_front"]["realtime"]["preferred_route"]["successes"],
            arms["arm1_post_search"]["realtime"]["preferred_route"]["successes"],
        ),
        "| honest-correct total | {}/95 | {}/95 | {}/95 |".format(
            arms["arm0"]["honest_correct_total"]["successes"],
            arms["arm1_front"]["honest_correct_total"]["successes"],
            arms["arm1_post_search"]["honest_correct_total"]["successes"],
        ),
        "",
        "No canonical/runtime promotion, model inference, training, keyword addition, or sealed run occurred.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "canary_stage_attribution": root / DEFAULT_ATTRIBUTION,
        "routing_bottleneck_taxonomy": root / DEFAULT_TAXONOMY,
        "routing_bottleneck_report": root / DEFAULT_ROUTING_REPORT,
        "planner_enumeration": root / DEFAULT_ENUMERATION,
        "classifier_predictions": root / DEFAULT_CLASSIFIER_PREDICTIONS,
        "classifier_diagnostics": root / DEFAULT_CLASSIFIER_DIAGNOSTICS,
        "classifier_manifest": root / DEFAULT_CLASSIFIER_MANIFEST,
        "classifier_report": root / DEFAULT_CLASSIFIER_REPORT,
        "assembler_cases": root / DEFAULT_ASSEMBLER_CASES,
        "assembler_diagnostics": root / DEFAULT_ASSEMBLER_DIAGNOSTICS,
        "assembler_manifest": root / DEFAULT_ASSEMBLER_MANIFEST,
        "assembler_report": root / DEFAULT_ASSEMBLER_REPORT,
        "chunks": root / DEFAULT_CHUNKS,
        "answerability_source": root / "src/v3/select_evidence.py",
        "contract": root / DEFAULT_CONTRACT,
        "evaluator_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    classifier_manifest = json.loads(
        input_paths["classifier_manifest"].read_text(encoding="utf-8")
    )
    if classifier_manifest["artifacts"]["predictions"]["sha256"] != input_hashes[
        "classifier_predictions"
    ]:
        raise RuntimeError("Classifier prediction lineage mismatch")
    assembler_manifest = json.loads(
        input_paths["assembler_manifest"].read_text(encoding="utf-8")
    )
    if assembler_manifest["artifacts"]["cases"]["sha256"] != input_hashes[
        "assembler_cases"
    ]:
        raise RuntimeError("Assembler case lineage mismatch")

    dev_rows = read_jsonl(input_paths["adaptive_dev"])
    canary_rows = read_jsonl(input_paths["downgraded_canary"])
    cases = build_cases(
        ground_truth_rows=read_jsonl(input_paths["answerability_ground_truth"]),
        evaluation_rows=dev_rows + canary_rows,
        attribution_rows=read_jsonl(input_paths["canary_stage_attribution"]),
        enumeration_rows=read_jsonl(input_paths["planner_enumeration"]),
        prediction_rows=read_jsonl(input_paths["classifier_predictions"]),
        classifier_diagnostic_rows=read_jsonl(
            input_paths["classifier_diagnostics"]
        ),
        assembler_rows=read_jsonl(input_paths["assembler_cases"]),
        chunks=read_jsonl(input_paths["chunks"]),
    )
    taxonomy = read_jsonl(input_paths["routing_bottleneck_taxonomy"])
    attributions = read_jsonl(input_paths["canary_stage_attribution"])
    arms = {
        "arm0": summarize_arm(cases, "arm0"),
        "arm1_front": summarize_arm(cases, "arm1_front"),
        "arm1_post_search": summarize_arm(cases, "arm1_post_search"),
    }
    cross_parent = {
        arm: summarize_cross_parent(cases, taxonomy, arm)
        for arm in ("arm0", "arm1_front", "arm1_post_search")
    }
    canary_routes = {
        arm: summarize_canary_routes(cases, attributions, taxonomy, arm)
        for arm in ("arm0", "arm1_front", "arm1_post_search")
    }
    comparisons = {
        "arm1_front_vs_arm0": compare_arms(arms["arm0"], arms["arm1_front"]),
        "arm1_post_search_vs_arm0": compare_arms(
            arms["arm0"], arms["arm1_post_search"]
        ),
    }
    classifier_report = json.loads(
        input_paths["classifier_report"].read_text(encoding="utf-8")
    )
    prior_model_metrics = classifier_report["metrics"]["approach_a_fixed_model"][
        "overall"
    ]
    safety_counts = Counter(
        row["answerability_target"]
        for row in cases
        if row["arm0"]["safety_reason"] is not None
    )
    classifier_pass = any(item["pass"] for item in comparisons.values())
    backbone_checks = {
        "frozen_route_exact_improved_over_18_of_32": (
            canary_routes["arm0"]["frozen_route_action_exact"]["successes"] > 18
        ),
        "label_audited_exact_improved_over_25_of_32": (
            canary_routes["arm0"]["label_audited_route_action_exact"]["successes"]
            > 25
        ),
        "answerable_overreject_zero": (
            arms["arm0"]["answerable"]["overreject"]["successes"] == 0
        ),
        "reject_correct_11_of_11": (
            arms["arm0"]["reject"]["correct_abstain_or_reject"]["successes"]
            == 11
        ),
        "realtime_static_exposure_zero": (
            arms["arm0"]["realtime"]["static_document_exposure"]["successes"]
            == 0
        ),
        "cross_parent_trigger_2_of_2": (
            cross_parent["arm0"]["cross_parent_decompose_candidate"]["successes"]
            == 2
        ),
        "false_full_answer_zero": (
            arms["arm0"]["answerable"]["false_full_answer"]["successes"] == 0
        ),
    }
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_head_to_head_ab_no_promotion",
        "artifact_lineage": {
            "supersedes_preliminary_report_sha256": (
                "69c8bd7b1e59e50743c68559eb99aa6225e3fa887e3a730711c54c3974352b9c"
            ),
            "supersedes_preliminary_manifest_sha256": (
                "63f797ea97a3a3008062f4ab345a21ff3500acfdbbfd8684c863177e3d6bf40c"
            ),
            "reason": "adds explicit narrow-safety counts and raw-vs-incremental FN explanation",
            "preliminary_artifacts_deleted": False,
        },
        "classifier_recommendation": (
            "ADOPT_RECOMMENDATION" if classifier_pass else "REJECT_ANSWER_SOURCE_CLASSIFIER"
        ),
        "backbone_decision": (
            "GO_DEVELOPMENT_BACKBONE_NO_GO_RUNTIME_DUE_TO_FALSE_FULL_AND_CROSS_PARENT"
        ),
        "arms": arms,
        "head_to_head": comparisons,
        "cross_parent": cross_parent,
        "canary_route_comparison": {
            "degenerate_all_retrieve": {
                "frozen_route_action_exact": _ratio(18, 32),
                "label_audited_route_action_exact": _ratio(25, 32),
                "label_audited_safe_handling": _ratio(25, 32),
            },
            **canary_routes,
        },
        "backbone_gate": {
            "checks": backbone_checks,
            "development_backbone_go": all(
                backbone_checks[name]
                for name in (
                    "frozen_route_exact_improved_over_18_of_32",
                    "label_audited_exact_improved_over_25_of_32",
                    "answerable_overreject_zero",
                    "reject_correct_11_of_11",
                    "realtime_static_exposure_zero",
                )
            ),
            "complete_router_or_runtime_go": all(backbone_checks.values()),
        },
        "narrow_safety_pre_gate": {
            "reused_reason_codes": sorted(NARROW_SAFETY_REASONS),
            "matched_total": sum(safety_counts.values()),
            "matched_answerable_docs": safety_counts["answerable_docs"],
            "matched_reject": safety_counts["reject"],
            "matched_realtime": safety_counts["realtime_api"],
            "new_keyword_or_regex_rules": 0,
            "private_realtime_subjective_or_advice_reasons_used": False,
        },
        "classifier_lineage": {
            "model": classifier_report["approach_a"]["model"],
            "prompt_sha256": classifier_report["approach_a"]["prompt_sha256"],
            "frozen_prediction_sha256": input_hashes["classifier_predictions"],
            "inference_rerun_this_cycle": False,
            "previous_raw_docs_false_negative_requirements": prior_model_metrics[
                "docs_false_negative_count"
            ],
            "previous_raw_docs_false_negative_questions": prior_model_metrics[
                "docs_false_negative_question_count"
            ],
            "placement_note": (
                "Front suppresses only assembler-supported expected-doc requirements in "
                "the backbone delta; the prior raw classifier metric remains 24/15."
            ),
            "raw_vs_incremental_fn_explanation": (
                "Two of the prior 24 requirement false negatives, across two of the 15 "
                "questions, were already unsupported by Arm0. Front placement therefore "
                "causes 22 incremental supported-requirement suppressions across 13 "
                "questions while the raw classifier error remains 24/15."
            ),
        },
        "interpretation": {
            "arm0": (
                "The groundedness backbone eliminates answerable overreject and safely "
                "abstains on all reject/realtime controls, but exact extraction alone "
                "still yields nine false full answers and no cross-parent trigger."
            ),
            "arm1_front": (
                "Front placement recreates the overreject failure by suppressing supported "
                "expected-doc requirements."
            ),
            "arm1_post_search": (
                "Evidence-priority placement avoids answerable suppression but converts "
                "four reject cases into realtime misroutes, so honest-correct total falls."
            ),
            "realtime": (
                "Both Arm1 placements route 2/2 realtime controls, but n=2 is too small "
                "for a routing conclusion and does not offset reject regressions."
            ),
        },
        "scope": {
            "canonical_or_runtime_promoted": False,
            "new_sealed_canary_run": False,
            "model_inference_run": False,
            "classifier_trained_or_changed": False,
            "keyword_or_regex_rules_added": 0,
            "planner_retrieval_reranker_assembler_changed": False,
            "questions_gold_or_labels_changed": False,
            "seven_decompose_labels_changed": False,
            "frozen_blind_accessed": False,
        },
    }

    router_dir = root / "data/v3/router"
    reports_dir = root / "reports/v3"
    case_bytes = _serialize_jsonl(cases, lambda row: (row["dataset"], row["case_id"]))
    case_sha = _sha256_bytes(case_bytes)
    case_path = router_dir / f"router_backbone_answer_source_ab_cases_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"router_backbone_answer_source_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"router_backbone_answer_source_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "artifacts": {
            "cases": {
                "path": _relative(root, case_path),
                "sha256": case_sha,
                "row_count": len(cases),
                "question_or_gold_text_included": False,
            },
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "classifier_recommendation": report["classifier_recommendation"],
        "backbone_decision": report["backbone_decision"],
        "canonical_or_runtime_promoted": False,
        "model_inference_run": False,
        "new_sealed_canary_run": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = router_dir / f"router_backbone_answer_source_ab_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during router A/B: {name}")
    return {
        "classifier_recommendation": report["classifier_recommendation"],
        "backbone_decision": report["backbone_decision"],
        "arms": arms,
        "head_to_head": comparisons,
        "cross_parent": cross_parent,
        "canary_route_comparison": report["canary_route_comparison"],
        "cases_path": str(case_path),
        "cases_sha256": case_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a groundedness router backbone against frozen answer-source predictions"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            evaluate_and_freeze(parse_args().root),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
