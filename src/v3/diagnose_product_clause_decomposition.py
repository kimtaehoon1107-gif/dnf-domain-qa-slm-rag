from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.answer_target_router import _base_tag, _clause_boundaries, _kiwi
from src.v3.product_evidence_pack import (
    explicit_question_clauses,
    kiwi_independent_requirement_queries,
)


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    path: Path


DATASETS = (
    DatasetSpec(
        "A6",
        Path(
            "data/v3/evaluation/product_free_rag_a6_frozen_"
            "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc"
            "689b65dc.jsonl"
        ),
    ),
    DatasetSpec(
        "USER10",
        Path(
            "data/v3/evaluation/"
            "product_pipeline_user10_v2_adaptive_20260805.jsonl"
        ),
    ),
    DatasetSpec(
        "A5",
        Path(
            "data/v3/evaluation/product_free_rag_a5_frozen_"
            "99122be1d851c2de0bac56be6c93a37bd8e30c71c311be2ee5424cf"
            "27b487fcc.jsonl"
        ),
    ),
    DatasetSpec(
        "EXISTING32",
        Path(
            "data/v3/evaluation/simple_rag_untouched32_sealed_"
            "6b2bc67087d255af1b4cfdc9076b8dfd8d0cce2b2194e2e2210af08"
            "eb8a95198.jsonl"
        ),
    ),
    DatasetSpec(
        "NEW_CLAIM32",
        Path(
            "data/v3/evaluation/typed_evidence_ref_new_claim32_sealed_"
            "b8e9f67bc3cb927168f312d3cb5dfaca154c2dffd14c7fabd8c6efb"
            "5a98ee83a.jsonl"
        ),
    ),
    DatasetSpec(
        "SEALED64",
        Path(
            "data/v3/evaluation/"
            "typed_evidence_ref_generalization_64_sealed_"
            "e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf"
            "32b85a597.jsonl"
        ),
    ),
)

DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_clause_decomposition_s1_20260805.jsonl"
)
DEFAULT_S2_OUTPUT = Path(
    "reports/v3/product_free_rag_clause_decomposition_s2_20260805.jsonl"
)
RUNNER_VERSION = "product-free-rag-clause-decomposition-s1-v1"

A6_CORRECT_SLOTS = {
    3,
    5,
    8,
    9,
    12,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    23,
    24,
    25,
    27,
    29,
    30,
    31,
}
A6_INCORRECT_SLOTS = set(range(1, 33)) - A6_CORRECT_SLOTS


def _question(row: dict[str, Any]) -> str:
    value = row.get("question_text") or row.get("question")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("evaluation row has no question text")
    return " ".join(value.split())


def _slot(row: dict[str, Any]) -> int:
    value = row.get("slot_ordinal", row.get("slot"))
    if not isinstance(value, int):
        raise RuntimeError("evaluation row has no integer slot")
    return value


def _human_judgement(
    dataset: str,
    row: dict[str, Any],
) -> str | None:
    slot = _slot(row)
    if dataset == "A6":
        if slot in A6_CORRECT_SLOTS:
            return "correct"
        if slot in A6_INCORRECT_SLOTS:
            return "incorrect"
        raise RuntimeError(f"unexpected A6 slot: {slot}")
    if dataset != "USER10":
        return None
    judgement = str(row.get("expected_judgement") or "")
    if judgement == "single_turn_gold":
        return "deferred"
    if judgement.startswith("wrong_"):
        return "incorrect"
    if judgement.startswith("correct"):
        return "correct"
    raise RuntimeError(f"unexpected USER10 judgement: {judgement!r}")


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _decision(
    *,
    total_count: int,
    gap_count: int,
    correct_count: int,
    correct_gap_count: int,
    incorrect_count: int,
    incorrect_gap_count: int,
) -> dict[str, Any]:
    overall_gap_rate = _rate(gap_count, total_count)
    correct_gap_rate = _rate(correct_gap_count, correct_count)
    incorrect_gap_rate = _rate(incorrect_gap_count, incorrect_count)
    if overall_gap_rate < 0.05:
        verdict = "gap_rare_stop"
        proceed = False
        rationale = "overall decomposition_gap rate is below 5%"
    else:
        ratio = (
            math.inf
            if correct_gap_rate == 0.0 and incorrect_gap_rate > 0.0
            else _rate(incorrect_gap_rate, correct_gap_rate)
        )
        if ratio >= 2.0:
            verdict = "error_concentrated_proceed_s2"
            proceed = True
            rationale = "incorrect gap rate is at least 2x correct gap rate"
        else:
            verdict = "no_discrimination_stop"
            proceed = False
            rationale = "gap is not concentrated in incorrect cases"
    return {
        "verdict": verdict,
        "proceed_to_s2": proceed,
        "rationale": rationale,
        "overall_gap_rate": overall_gap_rate,
        "correct_gap_rate": correct_gap_rate,
        "incorrect_gap_rate": incorrect_gap_rate,
        "incorrect_to_correct_gap_rate_ratio": (
            "infinity"
            if correct_gap_rate == 0.0 and incorrect_gap_rate > 0.0
            else _rate(incorrect_gap_rate, correct_gap_rate)
        ),
    }


def scan_s1(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in DATASETS:
        source = root / spec.path
        if not source.exists():
            raise RuntimeError(f"missing S1 input: {source}")
        for source_row in read_jsonl(source):
            question = _question(source_row)
            explicit = explicit_question_clauses(question)
            kiwi = kiwi_independent_requirement_queries(question)
            judgement = _human_judgement(spec.name, source_row)
            rows.append(
                {
                    "type": "case",
                    "dataset": spec.name,
                    "case_ref": f"{spec.name}-{_slot(source_row)}",
                    "slot_ordinal": _slot(source_row),
                    "question": question,
                    "explicit_question_clauses": explicit,
                    "kiwi_requirement_queries": kiwi,
                    "explicit_n": len(explicit),
                    "kiwi_n": len(kiwi),
                    "requirement_n": (
                        len(source_row["requirements"])
                        if isinstance(source_row.get("requirements"), list)
                        else None
                    ),
                    "decomposition_gap": len(explicit) >= 2 and not kiwi,
                    "human_judgement": judgement,
                    "source_path": spec.path.as_posix(),
                }
            )

    per_dataset: dict[str, dict[str, Any]] = {}
    for spec in DATASETS:
        subset = [row for row in rows if row["dataset"] == spec.name]
        labelled = [
            row
            for row in subset
            if row["human_judgement"] in {"correct", "incorrect"}
        ]
        counts = Counter(row["human_judgement"] for row in labelled)
        per_dataset[spec.name] = {
            "case_count": len(subset),
            "gap_count": sum(row["decomposition_gap"] for row in subset),
            "gap_rate": _rate(
                sum(row["decomposition_gap"] for row in subset),
                len(subset),
            ),
            "labelled_count": len(labelled),
            "correct_count": counts["correct"],
            "incorrect_count": counts["incorrect"],
            "deferred_count": sum(
                row["human_judgement"] == "deferred" for row in subset
            ),
            "correct_gap_count": sum(
                row["decomposition_gap"]
                and row["human_judgement"] == "correct"
                for row in subset
            ),
            "incorrect_gap_count": sum(
                row["decomposition_gap"]
                and row["human_judgement"] == "incorrect"
                for row in subset
            ),
        }

    labelled = [
        row
        for row in rows
        if row["human_judgement"] in {"correct", "incorrect"}
    ]
    correct = [row for row in labelled if row["human_judgement"] == "correct"]
    incorrect = [
        row for row in labelled if row["human_judgement"] == "incorrect"
    ]
    gap_count = sum(row["decomposition_gap"] for row in rows)
    correct_gap_count = sum(row["decomposition_gap"] for row in correct)
    incorrect_gap_count = sum(row["decomposition_gap"] for row in incorrect)
    decision = _decision(
        total_count=len(rows),
        gap_count=gap_count,
        correct_count=len(correct),
        correct_gap_count=correct_gap_count,
        incorrect_count=len(incorrect),
        incorrect_gap_count=incorrect_gap_count,
    )
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "diagnostic_only": True,
        "runtime_modified": False,
        "qwen_calls": 0,
        "case_count": len(rows),
        "gap_count": gap_count,
        "gap_rate": _rate(gap_count, len(rows)),
        "labelled_count": len(labelled),
        "deferred_count": sum(
            row["human_judgement"] == "deferred" for row in rows
        ),
        "contingency_table": {
            "gap_correct": correct_gap_count,
            "gap_incorrect": incorrect_gap_count,
            "no_gap_correct": len(correct) - correct_gap_count,
            "no_gap_incorrect": len(incorrect) - incorrect_gap_count,
        },
        "per_dataset": per_dataset,
        "decision": decision,
        "next_stage": "S2" if decision["proceed_to_s2"] else "STOP_S1",
    }
    return rows, summary


def _grammar_structure(question: str) -> dict[str, Any]:
    tokens = list(_kiwi().tokenize(question))
    boundary_indexes = set(_clause_boundaries(tokens))
    go_indexes = [
        index
        for index, token in enumerate(tokens)
        if _base_tag(token) == "EC" and str(token.form) == "고"
    ]
    missed_go = [index for index in go_indexes if index not in boundary_indexes]
    if missed_go:
        first_missed = min(missed_go)
        if any(index < first_missed for index in boundary_indexes):
            category = "predicate_go_shadowed_by_prior_ec_boundary"
        else:
            category = "predicate_go_failed_independence_test"
    elif any(_base_tag(token) == "JC" for token in tokens):
        category = "nominal_coordination_without_predicate_clause"
    elif re.search(r"[?？]\s+\S", question):
        category = "separate_surface_questions_without_kiwi_clause"
    elif "," in question:
        category = "comma_surface_split_without_kiwi_clause"
    else:
        category = "other_surface_separator_without_kiwi_clause"
    return {
        "grammar_structure": category,
        "ec_tokens": [
            str(token.form)
            for token in tokens
            if _base_tag(token) == "EC"
        ],
        "clause_boundary_tokens": [
            str(tokens[index].form) for index in sorted(boundary_indexes)
        ],
        "go_ec_count": len(go_indexes),
        "missed_go_ec_count": len(missed_go),
        "jc_tokens": [
            str(token.form)
            for token in tokens
            if _base_tag(token) == "JC"
        ],
    }


def scan_s2(
    root: Path,
    s1_input: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = s1_input if s1_input.is_absolute() else root / s1_input
    if not source.exists():
        raise RuntimeError(f"missing S1 output: {source}")
    s1_rows = read_jsonl(source)
    s1_summary = next(
        (row for row in s1_rows if row.get("type") == "summary"),
        None,
    )
    if not s1_summary or not s1_summary.get("decision", {}).get(
        "proceed_to_s2"
    ):
        raise RuntimeError("S1 did not authorize S2")
    rows = []
    for s1_row in s1_rows:
        if s1_row.get("type") != "case" or not s1_row.get(
            "decomposition_gap"
        ):
            continue
        rows.append(
            {
                **s1_row,
                **_grammar_structure(str(s1_row["question"])),
                "type": "case",
                "stage": "S2",
            }
        )
    category_counts = Counter(row["grammar_structure"] for row in rows)
    examples = {
        category: [
            row["case_ref"]
            for row in rows
            if row["grammar_structure"] == category
        ][:5]
        for category in category_counts
    }
    summary = {
        "type": "summary",
        "stage": "S2",
        "runner_version": RUNNER_VERSION,
        "diagnostic_only": True,
        "runtime_modified": False,
        "qwen_calls": 0,
        "gap_case_count": len(rows),
        "grammar_structure_counts": dict(category_counts.most_common()),
        "examples": examples,
        "a6_slot2_control": _grammar_structure(
            next(
                row["question"]
                for row in s1_rows
                if row.get("case_ref") == "A6-2"
            )
        ),
        "next_stage": "S3",
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan clause-decomposition gaps without calling Qwen"
    )
    parser.add_argument("--stage", choices=("s1", "s2"), default="s1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--s1-input", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    default_output = DEFAULT_OUTPUT if args.stage == "s1" else DEFAULT_S2_OUTPUT
    requested_output = args.output or default_output
    output = (
        requested_output
        if requested_output.is_absolute()
        else root / requested_output
    )
    if output.exists():
        raise RuntimeError(f"{args.stage.upper()} output already exists: {output}")
    if args.stage == "s1":
        rows, summary = scan_s1(root)
    else:
        rows, summary = scan_s2(root, args.s1_input)
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
