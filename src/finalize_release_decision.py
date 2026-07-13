from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count(rate: float | None, total: int) -> int:
    if rate is None:
        return 0
    return round(float(rate) * total)


def candidate_metrics(prefix: Path) -> dict[str, Any]:
    fresh_report = read_json(Path(f"{prefix}_fresh_dev_quality.json"))
    fresh = fresh_report["summary"]
    human = read_json(Path(f"{prefix}_partial_dev_quality.json"))["summary"]
    requirements = read_json(Path(f"{prefix}_partial_requirements.json"))["summary"]
    return {
        "fresh_exact_citation": count(fresh["exact_citation_set_match_rate"], 22),
        "fresh_partial_joint": count(fresh["partial_joint_success_rate"], 6),
        "fresh_false_joint": count(fresh["false_joint_correct_rate"], 8),
        "human_exact_citation": count(human["exact_citation_set_match_rate"], 20),
        "human_partial_joint": count(human["partial_joint_success_rate"], 20),
        "human_strict_requirement_joint": count(
            requirements["partial_requirement_joint_success_rate"], 20
        ),
        "grounded_answered_and_cited": count(
            requirements["grounded_slot_answer_and_citation_rate"], 31
        ),
        "unsupported_explicit_abstention": count(
            requirements["unsupported_slot_abstention_rate"], 21
        ),
        "unsupported_over_answer": count(
            requirements["unsupported_slot_over_answer_rate"], 21
        ),
        "unsafe_answer_rows": int(fresh_report["counts"].get("unsafe_answers", 0)),
    }


def selection_tuple(metrics: dict[str, Any]) -> tuple[int, ...]:
    return (
        metrics["human_strict_requirement_joint"],
        metrics["human_exact_citation"],
        metrics["fresh_partial_joint"],
        metrics["fresh_exact_citation"],
        metrics["unsupported_explicit_abstention"],
    )


def failed_pre_gates(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    checks = (
        ("fresh_exact_citation", metrics["fresh_exact_citation"], ">=", 11),
        ("fresh_partial_joint", metrics["fresh_partial_joint"], ">=", 2),
        ("fresh_false_joint", metrics["fresh_false_joint"], ">=", 7),
        ("human_exact_citation", metrics["human_exact_citation"], ">=", 10),
        ("human_partial_joint", metrics["human_partial_joint"], ">=", 6),
        (
            "human_strict_requirement_joint",
            metrics["human_strict_requirement_joint"],
            ">=",
            2,
        ),
        (
            "grounded_answered_and_cited",
            metrics["grounded_answered_and_cited"],
            ">=",
            5,
        ),
        (
            "unsupported_explicit_abstention",
            metrics["unsupported_explicit_abstention"],
            ">=",
            14,
        ),
        ("unsupported_over_answer", metrics["unsupported_over_answer"], "<=", 1),
        ("unsafe_answer_rows", metrics["unsafe_answer_rows"], "<=", 0),
    )
    failures = []
    for name, actual, operator, threshold in checks:
        passed = actual >= threshold if operator == ">=" else actual <= threshold
        if not passed:
            failures.append(
                {
                    "gate": name,
                    "actual": actual,
                    "operator": operator,
                    "threshold": threshold,
                }
            )
    return failures


def decide(step250_prefix: Path, final_prefix: Path) -> dict[str, Any]:
    candidates = {
        "checkpoint_250": candidate_metrics(step250_prefix),
        "final": candidate_metrics(final_prefix),
    }
    tuples = {name: selection_tuple(metrics) for name, metrics in candidates.items()}
    comparison_winner = max(
        candidates,
        key=lambda name: (tuples[name], name == "checkpoint_250"),
    )
    failures = {
        name: failed_pre_gates(metrics) for name, metrics in candidates.items()
    }
    eligible = [name for name in candidates if not failures[name]]
    release_candidate = (
        max(eligible, key=lambda name: (tuples[name], name == "checkpoint_250"))
        if eligible
        else None
    )
    return {
        "report_schema_version": 1,
        "status": "blind_opening_blocked" if release_candidate is None else "domain_official_required",
        "comparison_winner": comparison_winner,
        "release_candidate": release_candidate,
        "fallback_clean_baseline": "checkpoint_250",
        "selection_order": [
            "human_strict_requirement_joint",
            "human_exact_citation",
            "fresh_partial_joint",
            "fresh_exact_citation",
            "unsupported_explicit_abstention",
        ],
        "candidates": {
            name: {
                "metrics": candidates[name],
                "selection_tuple": list(tuples[name]),
                "failed_pre_gates": failures[name],
            }
            for name in candidates
        },
        "domain_official_evaluated": False,
        "blind_queried": False,
        "decision": (
            "No checkpoint passed the frozen fresh/human development gates. "
            "Do not evaluate domain, official, or frozen blind; retain checkpoint-250 "
            "as the clean development baseline and stop training."
            if release_candidate is None
            else "Evaluate the selected candidate on domain and official development sets."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply the frozen final checkpoint gates.")
    parser.add_argument("--step250-prefix", type=Path, required=True)
    parser.add_argument("--final-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = decide(args.step250_prefix, args.final_prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
