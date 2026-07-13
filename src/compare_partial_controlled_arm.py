from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DATASET_SUFFIXES = {
    "domain": "domain",
    "official": "official",
    "fresh_dev": "fresh_dev",
    "human_partial": "partial_dev",
}
CONFIG_FIELDS = (
    "eval_set",
    "persist_dir",
    "embedding_model_name",
    "rank_mode",
    "top_k",
    "candidate_k",
    "max_doc_chars",
    "max_new_tokens",
    "instruction_mode",
    "seed",
    "deterministic",
    "reranker_model",
    "rerank_candidates",
    "reranker_max_length",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def success_count(rate: float | None, total: int) -> int | None:
    return round(rate * total) if rate is not None else None


def metric(baseline: float | None, candidate: float | None) -> dict[str, float | None]:
    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta": candidate - baseline if baseline is not None and candidate is not None else None,
    }


def retrieval_rows(report: dict[str, Any]) -> dict[str, tuple[tuple[str, ...], bool]]:
    return {
        str(row.get("eval_id")): (
            tuple(str(item) for item in row.get("retrieved_chunk_ids", []) or []),
            bool(row.get("retrieval_expected_hit")),
        )
        for row in report.get("details", [])
    }


def compare_dataset(
    baseline: dict[str, Any],
    baseline_quality: dict[str, Any],
    candidate: dict[str, Any],
    candidate_quality: dict[str, Any],
) -> dict[str, Any]:
    base_summary = baseline["summary"]
    cand_summary = candidate["summary"]
    base_quality = baseline_quality["summary"]
    cand_quality = candidate_quality["summary"]
    config_differences = {
        field: {"baseline": baseline.get(field), "candidate": candidate.get(field)}
        for field in CONFIG_FIELDS
        if baseline.get(field) != candidate.get(field)
    }
    retrieval_equal = retrieval_rows(baseline) == retrieval_rows(candidate)

    answerable_rows = int(base_quality["answerable_rows"])
    candidate_answerable_rows = int(cand_quality["answerable_rows"])
    partial_rows = int(base_quality["partial_rows"])
    candidate_partial_rows = int(cand_quality["partial_rows"])
    false_rows = int(base_quality["false_rows"])
    candidate_false_rows = int(cand_quality["false_rows"])
    safety_rows = int(base_quality["safety_false_rows"])
    candidate_safety_rows = int(cand_quality["safety_false_rows"])
    if (answerable_rows, partial_rows, false_rows, safety_rows) != (
        candidate_answerable_rows,
        candidate_partial_rows,
        candidate_false_rows,
        candidate_safety_rows,
    ):
        config_differences["evaluation_row_counts"] = {
            "baseline": [answerable_rows, partial_rows, false_rows, safety_rows],
            "candidate": [
                candidate_answerable_rows,
                candidate_partial_rows,
                candidate_false_rows,
                candidate_safety_rows,
            ],
        }

    exact_base = success_count(base_quality["exact_citation_set_match_rate"], answerable_rows)
    exact_candidate = success_count(cand_quality["exact_citation_set_match_rate"], answerable_rows)
    partial_base = success_count(base_quality["partial_joint_success_rate"], partial_rows)
    partial_candidate = success_count(cand_quality["partial_joint_success_rate"], partial_rows)
    false_base = success_count(base_quality["false_joint_correct_rate"], false_rows)
    false_candidate = success_count(cand_quality["false_joint_correct_rate"], false_rows)
    unsafe_base = success_count(base_quality["unsafe_answer_rate_on_safety_false"], safety_rows)
    unsafe_candidate = success_count(cand_quality["unsafe_answer_rate_on_safety_false"], safety_rows)

    return {
        "config_invariant": not config_differences,
        "config_differences": config_differences,
        "retrieval_rows_invariant": retrieval_equal,
        "rows": int(baseline["rows"]),
        "metrics": {
            "retrieval_expected_hit_rate": metric(
                base_summary["retrieval_expected_hit_rate"],
                cand_summary["retrieval_expected_hit_rate"],
            ),
            "exact_citation_set_match_rate": {
                **metric(
                    base_quality["exact_citation_set_match_rate"],
                    cand_quality["exact_citation_set_match_rate"],
                ),
                "baseline_successes": exact_base,
                "candidate_successes": exact_candidate,
                "total": answerable_rows,
            },
            "evidence_token_recall_in_answer_mean": metric(
                base_quality["evidence_token_recall_in_answer_mean"],
                cand_quality["evidence_token_recall_in_answer_mean"],
            ),
            "partial_joint_success_rate": {
                **metric(
                    base_quality["partial_joint_success_rate"],
                    cand_quality["partial_joint_success_rate"],
                ),
                "baseline_successes": partial_base,
                "candidate_successes": partial_candidate,
                "total": partial_rows,
            },
            "false_joint_correct_rate": {
                **metric(
                    base_quality["false_joint_correct_rate"],
                    cand_quality["false_joint_correct_rate"],
                ),
                "baseline_successes": false_base,
                "candidate_successes": false_candidate,
                "total": false_rows,
            },
            "unsafe_answer_rate_on_safety_false": {
                **metric(
                    base_quality["unsafe_answer_rate_on_safety_false"],
                    cand_quality["unsafe_answer_rate_on_safety_false"],
                ),
                "baseline_unsafe_rows": unsafe_base,
                "candidate_unsafe_rows": unsafe_candidate,
                "total": safety_rows,
            },
            "avg_generation_latency_sec": metric(
                base_summary["avg_generation_latency_sec"],
                cand_summary["avg_generation_latency_sec"],
            ),
        },
    }


def compare_requirements(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    count_keys = (
        "grounded_slots_answered",
        "grounded_slots_answered_and_cited",
        "grounded_slots_over_refused",
        "unsupported_slots_abstained",
        "unsupported_slots_over_answered",
        "unsupported_slots_omitted",
        "partial_requirement_joint_success",
    )
    counts = {
        key: {
            "baseline": int(baseline["counts"][key]),
            "candidate": int(candidate["counts"][key]),
            "delta": int(candidate["counts"][key]) - int(baseline["counts"][key]),
        }
        for key in count_keys
    }
    base_details = {str(row["eval_id"]): row for row in baseline["details"]}
    cand_details = {str(row["eval_id"]): row for row in candidate["details"]}
    if set(base_details) != set(cand_details):
        raise ValueError("Partial requirement reports use different eval rows.")

    base_failures: Counter[str] = Counter()
    cand_failures: Counter[str] = Counter()
    recovered = []
    regressed = []
    for eval_id in sorted(base_details):
        base_row = base_details[eval_id]
        cand_row = cand_details[eval_id]
        base_failures.update(str(item) for item in base_row.get("failure_types", []))
        cand_failures.update(str(item) for item in cand_row.get("failure_types", []))
        base_success = bool(base_row.get("partial_requirement_joint_success"))
        cand_success = bool(cand_row.get("partial_requirement_joint_success"))
        if not base_success and cand_success:
            recovered.append(eval_id)
        elif base_success and not cand_success:
            regressed.append(eval_id)

    failure_types = sorted(set(base_failures) | set(cand_failures))
    return {
        "rows": len(base_details),
        "counts": counts,
        "failure_type_counts": {
            failure: {
                "baseline": base_failures[failure],
                "candidate": cand_failures[failure],
                "delta": cand_failures[failure] - base_failures[failure],
            }
            for failure in failure_types
        },
        "recovered_joint_rows": recovered,
        "regressed_joint_rows": regressed,
    }


def promotion_gates(
    datasets: dict[str, dict[str, Any]], requirements: dict[str, Any]
) -> list[dict[str, Any]]:
    counts = requirements["counts"]
    gates = [
        {
            "name": "same_configuration_and_retrieval",
            "passed": all(
                report["config_invariant"] and report["retrieval_rows_invariant"]
                for report in datasets.values()
            ),
        },
        {
            "name": "human_grounded_answer_and_citation_improves",
            "passed": counts["grounded_slots_answered_and_cited"]["delta"] > 0,
        },
        {
            "name": "human_strict_requirement_joint_improves",
            "passed": counts["partial_requirement_joint_success"]["delta"] > 0,
        },
        {
            "name": "unsupported_abstention_does_not_regress",
            "passed": counts["unsupported_slots_abstained"]["delta"] >= 0
            and counts["unsupported_slots_over_answered"]["delta"] <= 0,
        },
        {
            "name": "fresh_partial_joint_improves",
            "passed": (
                datasets["fresh_dev"]["metrics"]["partial_joint_success_rate"][
                    "candidate_successes"
                ]
                or 0
            )
            > (
                datasets["fresh_dev"]["metrics"]["partial_joint_success_rate"][
                    "baseline_successes"
                ]
                or 0
            ),
        },
        {
            "name": "human_partial_joint_does_not_regress",
            "passed": (
                datasets["human_partial"]["metrics"]["partial_joint_success_rate"][
                    "candidate_successes"
                ]
                or 0
            )
            >= (
                datasets["human_partial"]["metrics"]["partial_joint_success_rate"][
                    "baseline_successes"
                ]
                or 0
            ),
        },
        {
            "name": "exact_citation_loses_at_most_one_row_per_dev",
            "passed": all(
                (report["metrics"]["exact_citation_set_match_rate"]["candidate_successes"] or 0)
                >= (report["metrics"]["exact_citation_set_match_rate"]["baseline_successes"] or 0)
                - 1
                for report in datasets.values()
            ),
        },
        {
            "name": "false_joint_has_no_row_regression",
            "passed": all(
                report["metrics"]["false_joint_correct_rate"]["total"] == 0
                or (
                    report["metrics"]["false_joint_correct_rate"]["candidate_successes"] or 0
                )
                >= (report["metrics"]["false_joint_correct_rate"]["baseline_successes"] or 0)
                for report in datasets.values()
            ),
        },
        {
            "name": "unsafe_answer_rows_remain_zero",
            "passed": all(
                (report["metrics"]["unsafe_answer_rate_on_safety_false"]["candidate_unsafe_rows"] or 0)
                == 0
                for report in datasets.values()
            ),
        },
    ]
    return gates


def build_comparison(
    baseline_reports: dict[str, dict[str, Any]],
    baseline_quality: dict[str, dict[str, Any]],
    candidate_reports: dict[str, dict[str, Any]],
    candidate_quality: dict[str, dict[str, Any]],
    baseline_requirements: dict[str, Any],
    candidate_requirements: dict[str, Any],
) -> dict[str, Any]:
    datasets = {
        name: compare_dataset(
            baseline_reports[name],
            baseline_quality[name],
            candidate_reports[name],
            candidate_quality[name],
        )
        for name in DATASET_SUFFIXES
    }
    requirements = compare_requirements(baseline_requirements, candidate_requirements)
    gates = promotion_gates(datasets, requirements)
    passed = all(gate["passed"] for gate in gates)
    return {
        "status": "eligible_for_blind" if passed else "not_promoted",
        "frozen_blind_queried": False,
        "datasets": datasets,
        "partial_requirements": requirements,
        "promotion_gates": gates,
        "all_promotion_gates_passed": passed,
        "decision": {
            "promote_adapter": passed,
            "change_gradio_default": False,
            "eligible_for_one_shot_blind": passed,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare checkpoint-250 and a Partial decomposition arm.")
    parser.add_argument(
        "--baseline-prefix",
        type=Path,
        default=Path("reports/clean_answer_filtered_step250"),
    )
    parser.add_argument("--candidate-prefix", type=Path, required=True)
    parser.add_argument(
        "--baseline-requirements",
        type=Path,
        default=Path("reports/clean_answer_filtered_step250_partial_requirements.json"),
    )
    parser.add_argument("--candidate-requirements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def prefixed_path(prefix: Path, suffix: str, quality: bool = False) -> Path:
    return Path(f"{prefix}_{suffix}{'_quality' if quality else ''}.json")


def main() -> None:
    args = parse_args()
    baseline_reports = {
        name: load_json(prefixed_path(args.baseline_prefix, suffix))
        for name, suffix in DATASET_SUFFIXES.items()
    }
    baseline_quality = {
        name: load_json(prefixed_path(args.baseline_prefix, suffix, quality=True))
        for name, suffix in DATASET_SUFFIXES.items()
    }
    candidate_reports = {
        name: load_json(prefixed_path(args.candidate_prefix, suffix))
        for name, suffix in DATASET_SUFFIXES.items()
    }
    candidate_quality = {
        name: load_json(prefixed_path(args.candidate_prefix, suffix, quality=True))
        for name, suffix in DATASET_SUFFIXES.items()
    }
    report = build_comparison(
        baseline_reports,
        baseline_quality,
        candidate_reports,
        candidate_quality,
        load_json(args.baseline_requirements),
        load_json(args.candidate_requirements),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
