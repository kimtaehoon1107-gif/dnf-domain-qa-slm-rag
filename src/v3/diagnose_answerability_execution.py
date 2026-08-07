from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.select_evidence import classify_answerability


DIAGNOSTIC_VERSION = "answerability-execution-diagnostic-v3.1.0"
ROW_SCHEMA_VERSION = "answerability-execution-case-v3.1"
REPORT_SCHEMA_VERSION = "answerability-execution-diagnostic-report-v3.1"
MANIFEST_SCHEMA_VERSION = "answerability-execution-diagnostic-manifest-v3.1"

DEFAULT_GROUND_TRUTH = Path(
    "data/v3/evaluation/semantic_answerability_ground_truth_"
    "53cd8ae72ad4ee2f7c9b1d4370991ad74b5044d154e3657fd2008f45f71fe609.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_ATTRIBUTION = Path(
    "data/v3/evaluation/canary_stage_attribution_"
    "a132069a231a64225bfe78b86fbfa3e81dbc9cf9fc538df8469d5e33ef4dce35.jsonl"
)
DEFAULT_TAXONOMY = Path(
    "data/v3/router/routing_bottleneck_taxonomy_"
    "905182d088873485059415d4dcbda95f15db42c091392c7b3d21dfeefd734679.jsonl"
)
DEFAULT_TAXONOMY_MANIFEST = Path(
    "data/v3/router/routing_bottleneck_manifest_"
    "2095d9db0ddc2da1e4fe198987855db7200da8ff4264cc5c4dc65d519d468f24.json"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_RESULTS = Path(
    "data/v3/evidence/requirement_reranker_ab_results_"
    "db7dbd2281687c07aebf88dc43a07bd90cf280e690188c06a79cf9e3a2b04913.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BEHAVIORAL = Path(
    "data/v3/router/behavioral_coverage_canary_diagnostics_"
    "51a572984f3239108986929af8543ec4b5d8a5c00446eb8cbb07661211084aba.jsonl"
)
DEFAULT_BEHAVIORAL_MANIFEST = Path(
    "data/v3/router/behavioral_coverage_pilot_manifest_"
    "7e3dffe32dd0e9bcb8b54c3b74976fe1614edcac4028b1e284c1c69ea2738750.json"
)
DEFAULT_DECOMPOSITION_REPORT = Path(
    "reports/v3/question_decomposition_"
    "5f8c7d2f5b3eb777227225aa5e2d206a9e9d7c641441111b9556d78483cc3d07.json"
)
DEFAULT_ANSWERABILITY_AB_REPORT = Path(
    "reports/v3/planner_enumeration_answerability_ab_"
    "3e708a8d9f2352d58ed4a962b790d1269d65fad2249a835f8f04cf2e7a5ce006.json"
)
DEFAULT_ANSWERABILITY_AB_MANIFEST = Path(
    "data/v3/evaluation/semantic_answerability_ab_manifest_"
    "d3e356a92c4c55e4e180b9b36c8aef50d84df085e439b14a6c8235869e51a59e.json"
)
DEFAULT_PLANNER_REPORT = Path(
    "reports/v3/semantic_requirement_planner_"
    "a7d7515bea352feb60f5789aaa0e3afa354fb6bce74dcea893256386c1e4f8e3.json"
)
DEFAULT_ROUTE_REPORT = Path(
    "reports/v3/route_type_pilot_final_"
    "78870cd8f5c4ef4ea56b0c77872f7d3a196f6a6c7e35316492b72fc9ff5f0f0f.json"
)
DEFAULT_ROUTE_MANIFEST = Path(
    "data/v3/router/route_type_pilot_final_manifest_"
    "d1276658d963842660e89aeb431279c3b5517d269ef3a5665a90027f247b281b.json"
)
DEFAULT_CONTRACT = Path("docs/v3/answerability_execution_diagnostic.md")

FEATURE_NAMES = (
    "candidate_count",
    "requirement_count",
    "distinct_top_chunk_count",
    "min_top_score",
    "max_top_score",
    "mean_top_score",
    "min_margin",
    "mean_margin",
)
PARENT_SCORE_THRESHOLDS = (
    0.0,
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.2,
    0.35,
    0.5,
    0.65,
    0.8,
    0.9,
    0.95,
)


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


def extract_mechanical_features(score_row: dict[str, Any]) -> dict[str, Any]:
    requirements = score_row["requirements"]
    candidate_ids: set[str] = set()
    top_chunk_ids: list[str] = []
    top_scores: list[float] = []
    margins: list[float] = []
    for requirement in requirements:
        candidates = requirement["candidates"]
        candidate_ids.update(candidate["chunk_id"] for candidate in candidates)
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -float(candidate["reranker_score"]),
                candidate["chunk_id"],
            ),
        )
        if not ranked:
            top_scores.append(-1.0)
            margins.append(-1.0)
            continue
        top_chunk_ids.append(ranked[0]["chunk_id"])
        top_score = float(ranked[0]["reranker_score"])
        second_score = (
            float(ranked[1]["reranker_score"]) if len(ranked) > 1 else 0.0
        )
        top_scores.append(top_score)
        margins.append(top_score - second_score)
    if not requirements:
        raise RuntimeError(f"No planner requirements: {score_row['case_id']}")
    return {
        "candidate_count": len(candidate_ids),
        "requirement_count": len(requirements),
        "distinct_top_chunk_count": len(set(top_chunk_ids)),
        "min_top_score": round(min(top_scores), 8),
        "max_top_score": round(max(top_scores), 8),
        "mean_top_score": round(mean(top_scores), 8),
        "min_margin": round(min(margins), 8),
        "mean_margin": round(mean(margins), 8),
    }


def evaluate_numeric_rule(
    rows: list[dict[str, Any]],
    *,
    target: str,
    feature: str,
    operator: str,
    threshold: float,
) -> dict[str, Any]:
    if feature not in FEATURE_NAMES:
        raise RuntimeError(f"Unsupported mechanical feature: {feature}")
    if operator not in {"le", "ge"}:
        raise RuntimeError(f"Unsupported operator: {operator}")
    predicate: Callable[[float], bool]
    if operator == "le":
        predicate = lambda value: value <= threshold
    else:
        predicate = lambda value: value >= threshold
    selected = [row for row in rows if predicate(float(row["features"][feature]))]
    counts = Counter(row["answerability_target"] for row in selected)
    totals = Counter(row["answerability_target"] for row in rows)
    return {
        "feature": feature,
        "operator": operator,
        "threshold": threshold,
        "target": target,
        "target_recall": _ratio(counts[target], totals[target]),
        "answerable_false_positive": _ratio(
            counts["answerable_docs"], totals["answerable_docs"]
        ),
        "other_non_docs_selected": {
            label: counts[label]
            for label in ("reject", "realtime_api")
            if label != target
        },
        "selected_count": len(selected),
    }


def sweep_numeric_rules(
    rows: list[dict[str, Any]], target: str
) -> list[dict[str, Any]]:
    rules = []
    for feature in FEATURE_NAMES:
        values = sorted({float(row["features"][feature]) for row in rows})
        for operator in ("le", "ge"):
            for threshold in values:
                rules.append(
                    evaluate_numeric_rule(
                        rows,
                        target=target,
                        feature=feature,
                        operator=operator,
                        threshold=threshold,
                    )
                )
    return rules


def _best_rule(
    rules: list[dict[str, Any]],
    *,
    minimum_target_hits: int = 0,
    maximum_answerable_fp: int | None = None,
) -> dict[str, Any] | None:
    eligible = [
        rule
        for rule in rules
        if rule["target_recall"]["successes"] >= minimum_target_hits
        and (
            maximum_answerable_fp is None
            or rule["answerable_false_positive"]["successes"]
            <= maximum_answerable_fp
        )
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda rule: (
            rule["answerable_false_positive"]["successes"],
            -rule["target_recall"]["successes"],
            sum(rule["other_non_docs_selected"].values()),
            rule["selected_count"],
            rule["feature"],
            rule["operator"],
            rule["threshold"],
        ),
    )


def _front_action(question: str) -> tuple[str, str]:
    answerability = classify_answerability(question)
    if answerability["label"] != "false":
        return "answerable_docs", answerability["reason"]
    if answerability["reason"] in {
        "requires_private_account_state",
        "requires_realtime_auction_api",
    }:
        return "realtime_api", answerability["reason"]
    return "reject", answerability["reason"]


def _common_parent(parent_sets: list[set[str]]) -> bool:
    if not parent_sets or any(not values for values in parent_sets):
        return False
    return bool(set.intersection(*parent_sets))


def selected_parent_coverable(
    result_row: dict[str, Any], chunk_to_parent: dict[str, str]
) -> bool:
    parent_sets = []
    for requirement in result_row["requirement_aware"]["requirement_selections"]:
        parent_sets.append(
            {
                chunk_to_parent[chunk_id]
                for chunk_id in requirement["selected_chunk_ids"]
            }
        )
    return _common_parent(parent_sets)


def score_parent_coverable(
    score_row: dict[str, Any],
    chunk_to_parent: dict[str, str],
    *,
    threshold: float,
) -> bool:
    parent_sets = []
    for requirement in score_row["requirements"]:
        parent_sets.append(
            {
                chunk_to_parent[candidate["chunk_id"]]
                for candidate in requirement["candidates"]
                if float(candidate["reranker_score"]) >= threshold
            }
        )
    return _common_parent(parent_sets)


def build_case_rows(
    ground_truth_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
    attribution_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    scores = {row["case_id"]: row for row in score_rows}
    results = {row["case_id"]: row for row in result_rows}
    attributions = {row["case_id"]: row for row in attribution_rows}
    chunk_to_parent = {
        row["chunk_id"]: row["parent_document_id"] for row in chunks
    }
    output = []
    for ground_truth in ground_truth_rows:
        case_id = ground_truth["case_id"]
        if case_id not in enumerations or case_id not in scores or case_id not in results:
            raise RuntimeError(f"Missing frozen reranker row: {case_id}")
        if ground_truth["answerability_label"] != "false":
            target = "answerable_docs"
        elif (
            case_id in attributions
            and attributions[case_id]["expected_route_action"] == "realtime_api"
        ):
            target = "realtime_api"
        else:
            target = "reject"
        current_action, current_reason = _front_action(ground_truth["question"])
        features = extract_mechanical_features(scores[case_id])
        output.append(
            {
                "row_schema_version": ROW_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": ground_truth["dataset"],
                "answerability_target": target,
                "answerability_profile": ground_truth["answerability_profile"],
                "current_front_action": current_action,
                "current_front_reason": current_reason,
                "features": features,
                "value_type_signature": sorted(
                    requirement["value_type"]
                    for requirement in enumerations[case_id]["requirements"]
                ),
                "post_search_reject_candidate_count_lt_2": (
                    features["candidate_count"] < 2
                ),
                "selected_candidates_single_parent_coverable": (
                    selected_parent_coverable(results[case_id], chunk_to_parent)
                ),
                "score_0_005_single_parent_coverable": score_parent_coverable(
                    scores[case_id], chunk_to_parent, threshold=0.005
                ),
                "question_text_included": False,
                "gold_text_included": False,
                "gold_identifiers_used_for_runtime_decision": False,
            }
        )
    return sorted(output, key=lambda row: (row["dataset"], row["case_id"]))


def summarize_value_type_structure(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter(row["answerability_target"] for row in case_rows)
    signatures = sorted(
        {tuple(row["value_type_signature"]) for row in case_rows}
    )
    rules = []
    for signature in signatures:
        selected = [
            row
            for row in case_rows
            if tuple(row["value_type_signature"]) == signature
        ]
        counts = Counter(row["answerability_target"] for row in selected)
        rules.append(
            {
                "value_type_signature": list(signature),
                "realtime_recall": _ratio(
                    counts["realtime_api"], totals["realtime_api"]
                ),
                "answerable_false_positive": _ratio(
                    counts["answerable_docs"], totals["answerable_docs"]
                ),
                "reject_selected": counts["reject"],
            }
        )
    safe_rules = [
        rule
        for rule in rules
        if rule["answerable_false_positive"]["successes"] == 0
    ]
    safe = (
        min(
            safe_rules,
            key=lambda rule: (
                -rule["realtime_recall"]["successes"],
                rule["reject_selected"],
                rule["value_type_signature"],
            ),
        )
        if safe_rules
        else {
            "value_type_signature": None,
            "realtime_recall": _ratio(0, totals["realtime_api"]),
            "answerable_false_positive": _ratio(0, totals["answerable_docs"]),
            "reject_selected": 0,
            "nonempty_zero_fp_rule_exists": False,
        }
    )
    safe["nonempty_zero_fp_rule_exists"] = bool(safe_rules)
    one = min(
        (rule for rule in rules if rule["realtime_recall"]["successes"] >= 1),
        key=lambda rule: (
            rule["answerable_false_positive"]["successes"],
            rule["reject_selected"],
            rule["value_type_signature"],
        ),
    )
    realtime_signatures = {
        tuple(row["value_type_signature"])
        for row in case_rows
        if row["answerability_target"] == "realtime_api"
    }
    union_counts = Counter(
        row["answerability_target"]
        for row in case_rows
        if tuple(row["value_type_signature"]) in realtime_signatures
    )
    return {
        "planner_schema_has_typed_answer_source": False,
        "planner_schema_has_freshness_or_personal_state_type": False,
        "measured_field": "value_type_signature",
        "best_zero_answerable_fp_signature": safe,
        "best_signature_recovering_at_least_one": one,
        "observed_realtime_signature_union_upper_bound": {
            "signatures": [list(signature) for signature in sorted(realtime_signatures)],
            "realtime_recall": _ratio(
                union_counts["realtime_api"], totals["realtime_api"]
            ),
            "answerable_false_positive": _ratio(
                union_counts["answerable_docs"], totals["answerable_docs"]
            ),
            "uses_target_labels_for_diagnostic_only": True,
        },
        "free_text_subject_relation_or_group_not_matched": True,
        "conclusion": (
            "Existing value_type structure does not safely encode personal or "
            "realtime answer source. Reading free-text fields would require semantic "
            "classification or forbidden lexical rules."
        ),
    }


def summarize_answerability(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter(row["answerability_target"] for row in case_rows)
    if totals != Counter(
        {"answerable_docs": 82, "reject": 11, "realtime_api": 2}
    ):
        raise RuntimeError(f"Unexpected frozen answerability population: {totals}")
    confusion = Counter(
        (row["answerability_target"], row["current_front_action"])
        for row in case_rows
    )
    reject_rules = sweep_numeric_rules(case_rows, "reject")
    realtime_rules = sweep_numeric_rules(case_rows, "realtime_api")
    fixed_reject = evaluate_numeric_rule(
        case_rows,
        target="reject",
        feature="candidate_count",
        operator="le",
        threshold=1.0,
    )
    reject_safe = _best_rule(reject_rules, maximum_answerable_fp=0)
    reject_full = _best_rule(
        reject_rules, minimum_target_hits=totals["reject"]
    )
    realtime_safe = _best_rule(
        realtime_rules, maximum_answerable_fp=0
    )
    realtime_one = _best_rule(realtime_rules, minimum_target_hits=1)
    realtime_full = _best_rule(
        realtime_rules, minimum_target_hits=totals["realtime_api"]
    )
    return {
        "population": {
            "answerable_docs": totals["answerable_docs"],
            "reject": totals["reject"],
            "realtime_api": totals["realtime_api"],
            "total": len(case_rows),
        },
        "current_front_gate": {
            "confusion_matrix": [
                {"expected": expected, "actual": actual, "count": count}
                for (expected, actual), count in sorted(confusion.items())
            ],
            "reject_exact_recall": _ratio(
                confusion[("reject", "reject")], totals["reject"]
            ),
            "reject_any_non_docs_recall": _ratio(
                confusion[("reject", "reject")]
                + confusion[("reject", "realtime_api")],
                totals["reject"],
            ),
            "realtime_exact_recall": _ratio(
                confusion[("realtime_api", "realtime_api")],
                totals["realtime_api"],
            ),
            "answerable_overreject": _ratio(
                sum(
                    count
                    for (expected, actual), count in confusion.items()
                    if expected == "answerable_docs" and actual != "answerable_docs"
                ),
                totals["answerable_docs"],
            ),
        },
        "post_search_reject": {
            "zero_candidate_safe_rule": reject_safe,
            "candidate_count_lt_2_tradeoff": fixed_reject,
            "best_full_recall_rule": reject_full,
            "conclusion": (
                "PARTIAL_MECHANICAL_YES: zero candidates catches 8/11 at "
                "0/82 answerable false rejects; candidate_count < 2 catches "
                "9/11 but falsely rejects 2/82 answerable questions"
            ),
            "threshold_is_diagnostic_not_promoted": True,
        },
        "realtime": {
            "best_zero_answerable_fp_rule": realtime_safe,
            "best_rule_recovering_at_least_one": realtime_one,
            "best_full_recall_rule": realtime_full,
            "conclusion": (
                "NO_SAFE_MECHANICAL_SEPARATION_ON_CURRENT_GENERIC_SIGNALS; "
                "typed semantic answer-source classification is required"
            ),
        },
        "planner_structural_signal": summarize_value_type_structure(case_rows),
    }


def summarize_parent_coverage(
    case_rows: list[dict[str, Any]],
    taxonomy_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    behavioral_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    cases = {row["case_id"]: row for row in case_rows}
    scores = {row["case_id"]: row for row in score_rows}
    behavioral = {row["case_id"]: row for row in behavioral_rows}
    chunk_to_parent = {
        row["chunk_id"]: row["parent_document_id"] for row in chunks
    }
    same_ids = sorted(
        row["case_id"]
        for row in taxonomy_rows
        if row["failure_type"] == "LABEL_SUSPECT"
    )
    cross_ids = sorted(
        row["case_id"]
        for row in taxonomy_rows
        if row["failure_type"] == "DECOMPOSE_MISS"
    )
    if len(same_ids) != 7 or len(cross_ids) != 2:
        raise RuntimeError("Frozen same/cross parent audit changed")

    def evaluate(get_coverable: Callable[[str], bool]) -> dict[str, Any]:
        return {
            "cross_parent_triggered": _ratio(
                sum(not get_coverable(case_id) for case_id in cross_ids),
                len(cross_ids),
            ),
            "same_parent_preserved": _ratio(
                sum(get_coverable(case_id) for case_id in same_ids),
                len(same_ids),
            ),
        }

    selected = evaluate(
        lambda case_id: cases[case_id][
            "selected_candidates_single_parent_coverable"
        ]
    )
    grid = []
    for threshold in PARENT_SCORE_THRESHOLDS:
        metrics = evaluate(
            lambda case_id, threshold=threshold: score_parent_coverable(
                scores[case_id], chunk_to_parent, threshold=threshold
            )
        )
        grid.append({"threshold": threshold, **metrics})
    preserving = [
        row
        for row in grid
        if row["same_parent_preserved"]["successes"] == len(same_ids)
    ]
    best_preserving = max(
        preserving,
        key=lambda row: (
            row["cross_parent_triggered"]["successes"],
            -row["threshold"],
        ),
    )
    perfect = [
        row
        for row in grid
        if row["same_parent_preserved"]["successes"] == len(same_ids)
        and row["cross_parent_triggered"]["successes"] == len(cross_ids)
    ]
    cross_behavior = [behavioral[case_id] for case_id in cross_ids]
    return {
        "selected_requirement_candidates": selected,
        "score_threshold_grid": grid,
        "best_without_same_parent_regression": best_preserving,
        "perfect_threshold_exists": bool(perfect),
        "existing_behavioral_decomposition": {
            "signal_a_candidates": _ratio(
                sum(bool(row["signal_a_candidate"]) for row in cross_behavior),
                len(cross_behavior),
            ),
            "decomposition_committed": _ratio(
                sum(bool(row["commit_decomposition"]) for row in cross_behavior),
                len(cross_behavior),
            ),
            "decomposition_status_counts": dict(
                sorted(Counter(row["decomposition_status"] for row in cross_behavior).items())
            ),
            "actual_cross_parent_recovered": _ratio(
                sum(row["final_route_action"] == "decompose" for row in cross_behavior),
                len(cross_behavior),
            ),
        },
        "interpretation": (
            "Parent membership alone confuses shared distractor parents with semantic "
            "requirement coverage. No tested threshold recovers both cross-parent cases "
            "while preserving all seven same-parent cases."
        ),
        "trigger_promoted": False,
    }


def _markdown(report: dict[str, Any]) -> bytes:
    answerability = report["answerability"]
    current = answerability["current_front_gate"]
    reject_safe = answerability["post_search_reject"]["zero_candidate_safe_rule"]
    reject_lt_2 = answerability["post_search_reject"][
        "candidate_count_lt_2_tradeoff"
    ]
    realtime = answerability["realtime"]
    structural = answerability["planner_structural_signal"]
    coverage = report["coverage_trigger"]
    best = coverage["best_without_same_parent_regression"]
    cost = report["planner_cost"]
    lines = [
        "# Answerability execution diagnostic",
        "",
        f"- decision: **{report['decision']}**",
        f"- population: docs 82 / reject 11 / realtime 2",
        f"- current front reject exact: {current['reject_exact_recall']['successes']}/11",
        f"- current front realtime exact: {current['realtime_exact_recall']['successes']}/2",
        f"- post-search zero-candidate reject: {reject_safe['target_recall']['successes']}/11; answerable false reject {reject_safe['answerable_false_positive']['successes']}/82",
        f"- candidate_count < 2 tradeoff: reject {reject_lt_2['target_recall']['successes']}/11; answerable false reject {reject_lt_2['answerable_false_positive']['successes']}/82",
        f"- realtime at zero answerable FP: {realtime['best_zero_answerable_fp_rule']['target_recall']['successes']}/2",
        f"- planner value_type at zero answerable FP: {structural['best_zero_answerable_fp_signature']['realtime_recall']['successes']}/2",
        f"- selected-parent trigger: cross {coverage['selected_requirement_candidates']['cross_parent_triggered']['successes']}/2; same preserved {coverage['selected_requirement_candidates']['same_parent_preserved']['successes']}/7",
        f"- best threshold without same-parent regression: {best['threshold']} -> cross {best['cross_parent_triggered']['successes']}/2, same {best['same_parent_preserved']['successes']}/7",
        f"- existing downstream cross-parent recovery: {coverage['existing_behavioral_decomposition']['actual_cross_parent_recovered']['successes']}/2",
        f"- planner invocations gated/always-on: {cost['gated_invocations']}/{cost['always_on_invocations']} (+{cost['additional_invocations']})",
        "",
        "Conclusion: post-search evidence availability can safely catch most reject cases, but current generic mechanical signals cannot safely identify realtime/personal requests. Parent membership is also insufficient as semantic requirement coverage.",
        "",
        "No routing, answerability, planner, retrieval, decomposition, reranker, assembler, label, or runtime artifact was changed or promoted.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def diagnose_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / DEFAULT_DEV,
        "canary_stage_attribution": root / DEFAULT_ATTRIBUTION,
        "routing_bottleneck_taxonomy": root / DEFAULT_TAXONOMY,
        "routing_bottleneck_manifest": root / DEFAULT_TAXONOMY_MANIFEST,
        "planner_enumeration": root / DEFAULT_ENUMERATION,
        "requirement_reranker_scores": root / DEFAULT_SCORES,
        "requirement_reranker_results": root / DEFAULT_RESULTS,
        "chunks": root / DEFAULT_CHUNKS,
        "behavioral_canary_diagnostics": root / DEFAULT_BEHAVIORAL,
        "behavioral_manifest": root / DEFAULT_BEHAVIORAL_MANIFEST,
        "decomposition_report": root / DEFAULT_DECOMPOSITION_REPORT,
        "answerability_ab_report": root / DEFAULT_ANSWERABILITY_AB_REPORT,
        "answerability_ab_manifest": root / DEFAULT_ANSWERABILITY_AB_MANIFEST,
        "planner_report": root / DEFAULT_PLANNER_REPORT,
        "route_type_report": root / DEFAULT_ROUTE_REPORT,
        "route_type_manifest": root / DEFAULT_ROUTE_MANIFEST,
        "question_router_source": root / "src/v3/question_router.py",
        "answerability_source": root / "src/v3/select_evidence.py",
        "contract": root / DEFAULT_CONTRACT,
        "diagnostic_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    route_report = json.loads(
        input_paths["route_type_report"].read_text(encoding="utf-8")
    )
    if route_report["canonical_router"]["sha256"] != input_hashes[
        "question_router_source"
    ]:
        raise RuntimeError("Current router differs from retained canonical router")

    ground_truth = read_jsonl(input_paths["answerability_ground_truth"])
    enumerations = read_jsonl(input_paths["planner_enumeration"])
    scores = read_jsonl(input_paths["requirement_reranker_scores"])
    results = read_jsonl(input_paths["requirement_reranker_results"])
    attributions = read_jsonl(input_paths["canary_stage_attribution"])
    chunks = read_jsonl(input_paths["chunks"])
    taxonomy = read_jsonl(input_paths["routing_bottleneck_taxonomy"])
    behavioral = read_jsonl(input_paths["behavioral_canary_diagnostics"])
    cases = build_case_rows(
        ground_truth, enumerations, scores, results, attributions, chunks
    )
    if any(row["question_text_included"] or row["gold_text_included"] for row in cases):
        raise RuntimeError("Text-bearing diagnostic output is forbidden")
    answerability = summarize_answerability(cases)
    coverage = summarize_parent_coverage(
        cases, taxonomy, scores, chunks, behavioral
    )

    answerability_ab = json.loads(
        input_paths["answerability_ab_report"].read_text(encoding="utf-8")
    )
    prior_fixed = answerability_ab["metrics"]["approach_a_fixed_model"]["overall"]
    planner_report = json.loads(
        input_paths["planner_report"].read_text(encoding="utf-8")
    )
    planner_total_ms = float(planner_report["latency"]["planner_a"]["total_ms"])
    route_signal = route_report["signal_a"]
    gated_invocations = (
        route_signal["development_63"]["answer_target_analyzer_calls"]
        + route_signal["canary_32"]["answer_target_analyzer_calls"]
    )
    always_on = len(cases)
    mean_planner_ms = planner_total_ms / always_on
    planner_cost = {
        "gated_invocations": gated_invocations,
        "always_on_invocations": always_on,
        "additional_invocations": always_on - gated_invocations,
        "invocation_increase_rate": round(
            (always_on - gated_invocations) / gated_invocations, 8
        ),
        "frozen_semantic_planner_stage_wall_clock_ms": planner_total_ms,
        "approximate_mean_ms_per_question": round(mean_planner_ms, 4),
        "projected_gated_total_ms": round(mean_planner_ms * gated_invocations, 4),
        "projected_always_on_total_ms": round(mean_planner_ms * always_on, 4),
        "projected_additional_total_ms": round(
            mean_planner_ms * (always_on - gated_invocations), 4
        ),
        "estimate_only_not_new_latency_benchmark": True,
        "signal_a_latency_context": route_signal["latency"],
    }
    decomposition_report = json.loads(
        input_paths["decomposition_report"].read_text(encoding="utf-8")
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "evaluation_role": "development_only_measurement_no_fix",
        "decision": (
            "DIAGNOSTIC_COMPLETE_MECHANICAL_REJECT_PARTIAL_"
            "SEMANTIC_REALTIME_REQUIRED"
        ),
        "artifact_lineage": {
            "supersedes_preliminary_report_sha256": (
                "4c1972d5154a1754127d38315641c8169a08feba5d2ac0e92764817eb92eb040"
            ),
            "supersedes_preliminary_manifest_sha256": (
                "609f435e49d20fdc6263c52e24891deef6271d37dd02fb8a534bcf26c81002e0"
            ),
            "reason": (
                "This final diagnostic adds the requested existing-planner structural "
                "signal measurement. Earlier artifacts remain preserved; the original "
                "preliminary narrative error is recorded in its superseding report."
            ),
            "preliminary_artifacts_deleted": False,
        },
        "answerability": answerability,
        "gate_position_risk": {
            "current_lexical_front_answerable_overreject": answerability[
                "current_front_gate"
            ]["answerable_overreject"],
            "prior_fixed_model_front_docs_false_negative_requirements": prior_fixed[
                "docs_false_negative_count"
            ],
            "prior_fixed_model_front_docs_false_negative_questions": prior_fixed[
                "docs_false_negative_question_count"
            ],
            "prior_fixed_model_docs_false_positive_requirements": prior_fixed[
                "docs_false_positive_count"
            ],
            "post_search_safe_reject_answerable_false_positive": answerability[
                "post_search_reject"
            ]["zero_candidate_safe_rule"]["answerable_false_positive"],
            "interpretation": (
                "Moving reject behind retrieval supports a high-precision abstention floor. "
                "The prior fixed semantic gate would reintroduce 24 requirement-level "
                "false negatives across 15 questions if placed unconditionally in front."
            ),
        },
        "coverage_trigger": coverage,
        "decomposition_context": {
            "adaptive_dev_child_bm25_evidence_hits": _ratio(
                decomposition_report["metrics"]["evidence_group_hits_at_10"],
                decomposition_report["metrics"]["evidence_group_count"],
            ),
            "child_hybrid_retrieval_decision": decomposition_report["decisions"][
                "child_hybrid_retrieval"
            ],
            "note": (
                "The 8/8 adaptive-dev BM25 result is downstream context, not evidence "
                "that the two canary cross-parent cases were recovered."
            ),
        },
        "planner_cost": planner_cost,
        "boundary_conclusion": {
            "mechanically_feasible_now": (
                "post-search zero-candidate evidence availability identifies 8/11 reject cases at "
                "0/82 answerable false rejects"
            ),
            "not_mechanically_resolved": [
                "3/11 residual reject cases at the zero-FP operating point",
                "2/2 realtime/personal route cases",
                "semantic requirement-to-parent support for exact cross-parent triggering",
            ],
            "next_fix_direction_not_implemented": (
                "Run planner first; place high-precision reject after retrieval; use a "
                "separate fixed semantic or typed answer-source/freshness decision for "
                "personal and realtime requirements; treat parent coverage as semantic "
                "support, not raw parent membership."
            ),
            "semantic_classification_unavoidable_for_realtime_on_current_features": True,
        },
        "scope": {
            "router_changed": False,
            "answerability_changed": False,
            "planner_changed": False,
            "retrieval_changed": False,
            "decomposition_changed": False,
            "reranker_changed": False,
            "assembler_changed": False,
            "runtime_or_canonical_promoted": False,
            "classifier_trained_or_promoted": False,
            "keyword_rules_added": 0,
            "questions_gold_or_labels_changed": False,
            "model_embedding_or_search_run": False,
            "new_canary_run": False,
            "frozen_blind_accessed": False,
        },
    }

    router_dir = root / "data/v3/router"
    reports_dir = root / "reports/v3"
    case_bytes = _serialize_jsonl(cases, lambda row: (row["dataset"], row["case_id"]))
    case_sha = _sha256_bytes(case_bytes)
    case_path = router_dir / f"answerability_execution_cases_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"answerability_execution_diagnostic_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"answerability_execution_diagnostic_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
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
        "decision": report["decision"],
        "supersedes_preliminary_manifest_sha256": (
            report["artifact_lineage"]["supersedes_preliminary_manifest_sha256"]
        ),
        "fix_implemented": False,
        "runtime_or_canonical_promoted": False,
        "new_canary_run": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = router_dir / f"answerability_execution_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during diagnostic: {name}")
    return {
        "decision": report["decision"],
        "answerability": answerability,
        "coverage_trigger": coverage,
        "planner_cost": planner_cost,
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
        description="Measure mechanical answerability and parent coverage without fixes"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            diagnose_and_freeze(parse_args().root),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
