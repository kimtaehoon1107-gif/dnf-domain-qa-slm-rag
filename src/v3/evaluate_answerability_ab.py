from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_planner_answerability_fix import _expected_flags
from src.v3.evaluate_semantic_requirement_planner import (
    PLANNER_SYSTEM_PROMPT,
    _fixed_prompt_hash,
    call_structured,
    runtime_metadata,
)


EVALUATOR_VERSION = "planner-enumeration-answerability-ab-v3.0"
ENUMERATION_SCHEMA_VERSION = "semantic-requirement-enumeration-v3.0"
PREDICTION_SCHEMA_VERSION = "semantic-answer-source-ab-prediction-v3.0"
DIAGNOSTIC_SCHEMA_VERSION = "semantic-answer-source-ab-diagnostic-v3.0"
REPORT_SCHEMA_VERSION = "semantic-answer-source-ab-report-v3.0"
MANIFEST_SCHEMA_VERSION = "semantic-answer-source-ab-manifest-v3.0"

DEFAULT_PLANNER_OUTPUT = Path(
    "data/v3/evaluation/semantic_requirement_planner_outputs_"
    "e82122d0d473f9f956f03911690eebba5a35d474e40e58f2b769d9866dfc9c1c.jsonl"
)
DEFAULT_GROUND_TRUTH = Path(
    "data/v3/evaluation/semantic_answerability_ground_truth_"
    "53cd8ae72ad4ee2f7c9b1d4370991ad74b5044d154e3657fd2008f45f71fe609.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/planner_enumeration_answerability_separation.md")
DEFAULT_MODEL = "qwen3:8b"

ENUMERATION_PROMPT_SHA256 = (
    "01ddcf34498276b4896f5c628f53fa874047e8a989b3a5df3e405bd43c87d948"
)
ANSWER_SOURCES = (
    "official_docs",
    "personal_account",
    "realtime",
    "subjective",
    "out_of_scope",
    "ambiguous",
)
AnswerSource = Literal[
    "official_docs",
    "personal_account",
    "realtime",
    "subjective",
    "out_of_scope",
    "ambiguous",
]


ANSWERABILITY_MODEL_PROMPT = """You are a fixed answer-source classifier.
The atomic requirements have already been enumerated and MUST NOT be added,
removed, merged, split, renamed, or reordered. For every requirement, choose
exactly one answer_source using the question context and that requirement:

- official_docs: a stable or published fact that official DNF documents can
  state, even when the current corpus is missing it or retrieval may fail.
- personal_account: a value that requires private user/account/character/
  inventory/build/history state or a personalized decision based on it.
- realtime: a changing live value that requires a live service or API, such as
  a current auction-market value.
- subjective: a recommendation, benefit judgment, ranking, opinion, or future
  prediction rather than a published official fact.
- out_of_scope: unrelated external information, hidden system/evaluation data,
  or a request that official DNF documents are not an evidence source for.
- ambiguous: only when the requirement's boundary genuinely cannot be assigned
  without adjudication. Do not use ambiguous merely because evidence is absent.

Mixed questions may have different classes per requirement. Preserve the
requirement_index exactly. Classification only: do not retrieve, cite, answer,
explain, or generate prose. Return only the structured labels."""


class AnswerSourceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_index: int = Field(ge=1, le=8)
    answer_source: AnswerSource


class AnswerSourceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    decisions: list[AnswerSourceDecision] = Field(min_length=1, max_length=8)


class AnswerSourceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[AnswerSourceCase] = Field(min_length=1, max_length=8)


# Approach B is deliberately limited to the structural marker families fixed in
# the cycle contract. These are not used by the planner or reranker.
_OUT_OF_SCOPE_MARKERS = (
    "날씨",
    "비트코인",
    "로또",
    "시스템 프롬프트",
    "시스템프롬프트",
    "내부 평가",
)
_REALTIME_MARKERS = (
    "실시간",
    "경매장 시세",
    "현재 시세",
    "current_auction_price",
)
_SUBJECTIVE_MARKERS = (
    "추천",
    "이득",
    "좋을지",
    "최선",
    "순위",
    "예측",
    "recommendation",
    "recommended",
)
_OWNERSHIP_MARKERS = ("내 ", "내_", "내가", "제 ", "제가", "사용자")
_PERSONAL_TARGET_MARKERS = (
    "계정",
    "캐릭터",
    "세팅",
    "인벤토리",
    "잔액",
    "마일리지",
    "피로도",
    "사용량",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _latency(logs: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(float(row["latency_ms"]) for row in logs)
    return {
        "call_count": len(values),
        "median_ms": round(statistics.median(values), 3) if values else None,
        "p95_ms": (
            round(values[min(len(values) - 1, int(len(values) * 0.95))], 3)
            if values
            else None
        ),
        "total_ms": round(sum(values), 3) if values else None,
    }


def build_enumeration_rows(
    planner_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _fixed_prompt_hash(PLANNER_SYSTEM_PROMPT) != ENUMERATION_PROMPT_SHA256:
        raise RuntimeError("The frozen enumeration prompt SHA changed")
    output = []
    for row in planner_rows:
        requirements = []
        for index, requirement in enumerate(row["requirements"], 1):
            requirements.append(
                {
                    "requirement_id": requirement.get(
                        "requirement_id", f"requirement_{index}"
                    ),
                    "subject": requirement["subject"],
                    "relation": requirement["relation"],
                    "value_type": requirement["value_type"],
                    "subject_group": requirement["subject_group"],
                }
            )
        output.append(
            {
                "enumeration_schema_version": ENUMERATION_SCHEMA_VERSION,
                "case_id": row["case_id"],
                "requirements": requirements,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def answerability_prompt(
    truth_batch: list[dict[str, Any]],
    enumeration_by_id: dict[str, dict[str, Any]],
) -> str:
    payload = []
    for index, truth in enumerate(truth_batch, 1):
        requirements = []
        for requirement_index, requirement in enumerate(
            enumeration_by_id[truth["case_id"]]["requirements"], 1
        ):
            requirements.append(
                {
                    "requirement_index": requirement_index,
                    "subject": requirement["subject"],
                    "relation": requirement["relation"],
                    "value_type": requirement["value_type"],
                    "subject_group": requirement["subject_group"],
                }
            )
        payload.append(
            {
                "case_id": f"case_{index}",
                "question": truth["question"],
                "requirements": requirements,
                "expected_decision_count": len(requirements),
            }
        )
    return "Classify the answer source for each atomic requirement:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def run_model_classifier(
    truth_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    *,
    model: str,
    batch_size: int,
    timeout: float,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enumeration_by_id = {row["case_id"]: row for row in enumeration_rows}
    output = []
    call_logs = []
    for start in range(0, len(truth_rows), batch_size):
        batch = truth_rows[start : start + batch_size]
        parsed, call_log = caller(
            model=model,
            system_prompt=ANSWERABILITY_MODEL_PROMPT,
            user_prompt=answerability_prompt(batch, enumeration_by_id),
            output_type=AnswerSourceBatch,
            timeout=timeout,
        )
        cases = {case.case_id: case.model_dump() for case in parsed.cases}
        expected_case_ids = {f"case_{index}" for index in range(1, len(batch) + 1)}
        if set(cases) != expected_case_ids:
            raise RuntimeError("Model classifier returned missing/unexpected case ids")
        for case_index, truth in enumerate(batch, 1):
            decisions = cases[f"case_{case_index}"]["decisions"]
            decision_by_index = {
                decision["requirement_index"]: decision for decision in decisions
            }
            requirement_count = len(
                enumeration_by_id[truth["case_id"]]["requirements"]
            )
            expected_indices = set(range(1, requirement_count + 1))
            if set(decision_by_index) != expected_indices or len(decisions) != len(
                expected_indices
            ):
                raise RuntimeError(
                    f"Incomplete model decisions: {truth['case_id']}"
                )
            output.append(
                {
                    "case_id": truth["case_id"],
                    "decisions": [
                        decision_by_index[index] for index in sorted(expected_indices)
                    ],
                }
            )
        call_logs.append(call_log)
    return sorted(output, key=lambda row: row["case_id"]), call_logs


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def classify_structural(
    question: str,
    requirement: dict[str, Any],
    *,
    requirement_count: int,
) -> tuple[AnswerSource, str]:
    local = " ".join(
        str(requirement.get(key, ""))
        for key in ("subject", "relation", "subject_group")
    )
    if _contains_any(question, _OUT_OF_SCOPE_MARKERS):
        return "out_of_scope", "out_of_scope_marker"
    if _contains_any(local, _REALTIME_MARKERS) or (
        requirement_count == 1 and _contains_any(question, _REALTIME_MARKERS)
    ):
        return "realtime", "realtime_marker"
    if _contains_any(local, _SUBJECTIVE_MARKERS):
        return "subjective", "subjective_requirement_marker"
    if _contains_any(local, _OWNERSHIP_MARKERS) and _contains_any(
        local, _PERSONAL_TARGET_MARKERS
    ):
        return "personal_account", "owned_personal_target"
    if _contains_any(question, _OWNERSHIP_MARKERS) and _contains_any(
        local, _PERSONAL_TARGET_MARKERS
    ):
        return "personal_account", "question_ownership_plus_personal_target"
    if requirement_count == 1 and _contains_any(
        question, _SUBJECTIVE_MARKERS
    ):
        return "subjective", "single_requirement_subjective_question"
    if requirement_count == 1 and _contains_any(
        question, _OWNERSHIP_MARKERS
    ) and _contains_any(question, _PERSONAL_TARGET_MARKERS):
        return "personal_account", "single_requirement_personal_question"
    if requirement_count > 1 and (
        _contains_any(question, _SUBJECTIVE_MARKERS)
        or _contains_any(question, _OWNERSHIP_MARKERS)
    ):
        return "ambiguous", "mixed_question_scope_not_preserved_in_requirement"
    return "official_docs", "no_non_document_structure"


def run_structural_gate(
    truth_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    truth_by_id = {row["case_id"]: row for row in truth_rows}
    output = []
    for row in enumeration_rows:
        truth = truth_by_id[row["case_id"]]
        requirement_count = len(row["requirements"])
        decisions = []
        for index, requirement in enumerate(row["requirements"], 1):
            answer_source, rule_id = classify_structural(
                truth["question"],
                requirement,
                requirement_count=requirement_count,
            )
            decisions.append(
                {
                    "requirement_index": index,
                    "answer_source": answer_source,
                    "rule_id": rule_id,
                }
            )
        output.append({"case_id": row["case_id"], "decisions": decisions})
    return sorted(output, key=lambda row: row["case_id"])


def score_predictions(
    predictions: list[dict[str, Any]],
    truth_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    truth_by_id = {row["case_id"]: row for row in truth_rows}
    diagnostics = []
    for row in sorted(predictions, key=lambda item: item["case_id"]):
        truth = truth_by_id[row["case_id"]]
        sources = [decision["answer_source"] for decision in row["decisions"]]
        expected = _expected_flags(truth, len(sources))
        aligned = min(len(sources), len(expected))
        false_positives = []
        false_negatives = []
        ambiguous = []
        for index in range(aligned):
            source = sources[index]
            if source == "ambiguous":
                ambiguous.append(index + 1)
            elif source == "official_docs" and not expected[index]:
                false_positives.append(index + 1)
            elif source != "official_docs" and expected[index]:
                false_negatives.append(index + 1)
        diagnostics.append(
            {
                "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                "case_id": row["case_id"],
                "dataset": truth["dataset"],
                "source_ids": truth["source_ids"],
                "answerability_profile": truth["answerability_profile"],
                "predicted_sources": sources,
                "expected_docs_flags": expected,
                "docs_false_positive_indices": false_positives,
                "docs_false_negative_indices": false_negatives,
                "ambiguous_indices": ambiguous,
                "ambiguous_expected_docs_count": sum(
                    expected[index - 1] for index in ambiguous
                ),
                "ambiguous_expected_non_docs_count": sum(
                    not expected[index - 1] for index in ambiguous
                ),
                "missing_expected_requirement_count": max(
                    0, len(expected) - len(sources)
                ),
                "extra_unaligned_prediction_count": max(0, len(sources) - len(expected)),
            }
        )

    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        predicted_count = sum(len(row["predicted_sources"]) for row in rows)
        aligned_count = sum(
            min(len(row["predicted_sources"]), len(row["expected_docs_flags"]))
            for row in rows
        )
        ambiguous_count = sum(len(row["ambiguous_indices"]) for row in rows)
        clear_count = aligned_count - ambiguous_count
        class_counts = {
            source: sum(
                item == source for row in rows for item in row["predicted_sources"]
            )
            for source in ANSWER_SOURCES
        }
        false_positive_count = sum(
            len(row["docs_false_positive_indices"]) for row in rows
        )
        false_negative_count = sum(
            len(row["docs_false_negative_indices"]) for row in rows
        )
        return {
            "question_count": len(rows),
            "predicted_requirement_count": predicted_count,
            "aligned_requirement_count": aligned_count,
            "clear_requirement_count": clear_count,
            "clear_coverage": round(clear_count / aligned_count, 6)
            if aligned_count
            else None,
            "docs_false_positive_count": false_positive_count,
            "docs_false_positive_question_count": sum(
                bool(row["docs_false_positive_indices"]) for row in rows
            ),
            "docs_false_negative_count": false_negative_count,
            "docs_false_negative_question_count": sum(
                bool(row["docs_false_negative_indices"]) for row in rows
            ),
            "ambiguous_count": ambiguous_count,
            "ambiguous_question_count": sum(
                bool(row["ambiguous_indices"]) for row in rows
            ),
            "ambiguous_expected_docs_count": sum(
                row["ambiguous_expected_docs_count"] for row in rows
            ),
            "ambiguous_expected_non_docs_count": sum(
                row["ambiguous_expected_non_docs_count"] for row in rows
            ),
            "missing_expected_requirement_count": sum(
                row["missing_expected_requirement_count"] for row in rows
            ),
            "extra_unaligned_prediction_count": sum(
                row["extra_unaligned_prediction_count"] for row in rows
            ),
            "clear_accuracy": round(
                (clear_count - false_positive_count - false_negative_count)
                / clear_count,
                6,
            )
            if clear_count
            else None,
            "class_counts": class_counts,
        }

    metrics: dict[str, Any] = {"overall": aggregate(diagnostics)}
    for dataset in ("downgraded_canary_32", "adaptive_dev_63"):
        metrics[dataset] = aggregate(
            [row for row in diagnostics if row["dataset"] == dataset]
        )
    source_ids = sorted(
        {source for row in diagnostics for source in row["source_ids"]}
    )
    metrics["by_source"] = {
        source: aggregate(
            [row for row in diagnostics if source in row["source_ids"]]
        )
        for source in source_ids
    }
    return diagnostics, metrics


def choose_approach(metrics_by_approach: dict[str, Any]) -> dict[str, Any]:
    qualified = []
    for name, metrics in metrics_by_approach.items():
        overall = metrics["overall"]
        passes = (
            overall["docs_false_positive_count"] == 0
            and overall["clear_coverage"] is not None
            and overall["clear_coverage"] >= 0.80
        )
        if passes:
            qualified.append(
                (
                    overall["docs_false_negative_count"],
                    overall["ambiguous_count"],
                    name,
                )
            )
    if not qualified:
        return {
            "decision": "NO_GO_ANSWERABILITY_AB",
            "selected_approach": None,
            "selection_rule": "FP=0 and clear_coverage>=0.80, then minimum FN, then ambiguity",
        }
    _, ambiguous_count, name = min(qualified)
    return {
        "decision": (
            "ANSWERABILITY_DEVELOPMENT_CANDIDATE_PENDING_ADJUDICATION"
            if ambiguous_count
            else "ANSWERABILITY_COMPONENT_GO"
        ),
        "selected_approach": name,
        "selection_rule": "FP=0 and clear_coverage>=0.80, then minimum FN, then ambiguity",
    }


def _markdown(report: dict[str, Any]) -> bytes:
    lines = [
        "# Planner enumeration / answerability separation",
        "",
        "- Planner enumeration: **GO** (user-confirmed strong rematching; not rerun here)",
        f"- Answerability decision: **{report['answerability_selection']['decision']}**",
        f"- Selected approach: `{report['answerability_selection']['selected_approach']}`",
        "",
        "## A/B metrics",
        "",
    ]
    for name in ("approach_a_fixed_model", "approach_b_structural_gate"):
        metric = report["metrics"][name]["overall"]
        lines.extend(
            [
                f"### {name}",
                "",
                f"- docs false positive: {metric['docs_false_positive_count']}",
                f"- docs false negative: {metric['docs_false_negative_count']}",
                f"- ambiguous: {metric['ambiguous_count']}",
                f"- clear coverage: {metric['clear_coverage']}",
                "",
            ]
        )
    lines.extend(
        [
            "Ambiguous rows remain an adjudication queue and are not silently",
            "converted to official_docs. No answerability arm is promoted to runtime",
            "by this development-only A/B evaluation.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    model: str = DEFAULT_MODEL,
    batch_size: int = 5,
    timeout: float = 240.0,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "planner_output": root / DEFAULT_PLANNER_OUTPUT,
        "answerability_ground_truth": root / DEFAULT_GROUND_TRUTH,
        "contract": root / DEFAULT_CONTRACT,
        "planner_source": root / "src/v3/evaluate_semantic_requirement_planner.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    planner_rows = read_jsonl(input_paths["planner_output"])
    truth_rows = read_jsonl(input_paths["answerability_ground_truth"])
    if len(planner_rows) != 95 or len(truth_rows) != 95:
        raise RuntimeError("The frozen A/B population must contain exactly 95 cases")
    if {row["case_id"] for row in planner_rows} != {
        row["case_id"] for row in truth_rows
    }:
        raise RuntimeError("Planner and answerability truth case ids differ")

    enumeration_rows = build_enumeration_rows(planner_rows)
    enumeration_bytes = _serialize_jsonl(
        enumeration_rows, lambda row: row["case_id"]
    )
    enumeration_sha = _sha256_bytes(enumeration_bytes)
    enumeration_path = root / "data/v3/evaluation" / (
        f"semantic_requirement_enumeration_{enumeration_sha}.jsonl"
    )
    write_immutable(enumeration_path, enumeration_bytes)

    model_meta = runtime_metadata(model, timeout)
    approach_a, call_logs = run_model_classifier(
        truth_rows,
        enumeration_rows,
        model=model,
        batch_size=batch_size,
        timeout=timeout,
    )
    approach_b = run_structural_gate(truth_rows, enumeration_rows)
    a_by_id = {row["case_id"]: row for row in approach_a}
    b_by_id = {row["case_id"]: row for row in approach_b}
    prediction_rows = [
        {
            "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
            "case_id": case_id,
            "approach_a_fixed_model": a_by_id[case_id]["decisions"],
            "approach_b_structural_gate": b_by_id[case_id]["decisions"],
        }
        for case_id in sorted(a_by_id)
    ]
    prediction_bytes = _serialize_jsonl(
        prediction_rows, lambda row: row["case_id"]
    )
    prediction_sha = _sha256_bytes(prediction_bytes)
    prediction_path = root / "data/v3/evaluation" / (
        f"semantic_answerability_ab_predictions_{prediction_sha}.jsonl"
    )
    write_immutable(prediction_path, prediction_bytes)

    a_diagnostics, a_metrics = score_predictions(approach_a, truth_rows)
    b_diagnostics, b_metrics = score_predictions(approach_b, truth_rows)
    a_diag_by_id = {row["case_id"]: row for row in a_diagnostics}
    b_diag_by_id = {row["case_id"]: row for row in b_diagnostics}
    diagnostic_rows = [
        {
            "case_id": case_id,
            "approach_a_fixed_model": a_diag_by_id[case_id],
            "approach_b_structural_gate": b_diag_by_id[case_id],
        }
        for case_id in sorted(a_diag_by_id)
    ]
    diagnostic_bytes = _serialize_jsonl(
        diagnostic_rows, lambda row: row["case_id"]
    )
    diagnostic_sha = _sha256_bytes(diagnostic_bytes)
    diagnostic_path = root / "data/v3/evaluation" / (
        f"semantic_answerability_ab_diagnostics_{diagnostic_sha}.jsonl"
    )
    write_immutable(diagnostic_path, diagnostic_bytes)

    selection = choose_approach(
        {
            "approach_a_fixed_model": a_metrics,
            "approach_b_structural_gate": b_metrics,
        }
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_answerability_ab",
        "planner_enumeration": {
            "decision": "GO_TO_RERANKER_INPUT",
            "evidence_status": "user_confirmed_strong_rematching_directional_not_rerun_this_cycle",
            "downgraded_canary_32_recall_approximate": 0.90,
            "adaptive_dev_63_recall_approximate": 0.98,
            "prompt_sha256": ENUMERATION_PROMPT_SHA256,
            "answerable_from_docs_in_enumeration_artifact": False,
            "promotion_gate_uses_answerability": False,
        },
        "answerability_selection": selection,
        "gates": {
            "planner_enumeration_go": True,
            "approach_a_clear_docs_false_positive_zero": a_metrics["overall"][
                "docs_false_positive_count"
            ]
            == 0,
            "approach_b_clear_docs_false_positive_zero": b_metrics["overall"][
                "docs_false_positive_count"
            ]
            == 0,
            "answerability_has_qualified_candidate": selection[
                "selected_approach"
            ]
            is not None,
        },
        "metrics": {
            "approach_a_fixed_model": a_metrics,
            "approach_b_structural_gate": b_metrics,
        },
        "answerability_ground_truth": {
            "path": _relative(root, input_paths["answerability_ground_truth"]),
            "sha256": input_hashes["answerability_ground_truth"],
            "row_count": len(truth_rows),
            "independence": "frozen_before_this_A_B_run_not_4B_gold",
            "ambiguous_policy": "separate_class_requires_independent_human_or_strong_judge_adjudication",
        },
        "approach_a": {
            "model": model_meta,
            "prompt_sha256": _fixed_prompt_hash(ANSWERABILITY_MODEL_PROMPT),
            "latency": _latency(call_logs),
        },
        "approach_b": {
            "implementation": "fixed_structural_marker_gate",
            "model": None,
            "prompt_sha256": None,
            "marker_contract_sha256": _sha256_bytes(
                _canonical_json_bytes(
                    {
                        "out_of_scope": _OUT_OF_SCOPE_MARKERS,
                        "realtime": _REALTIME_MARKERS,
                        "subjective": _SUBJECTIVE_MARKERS,
                        "ownership": _OWNERSHIP_MARKERS,
                        "personal_target": _PERSONAL_TARGET_MARKERS,
                    }
                )
            ),
        },
        "scope": {
            "planner_enumeration_prompt_tuned": False,
            "planner_answerability_gate_removed": True,
            "reranker_implemented": False,
            "entailment_judge_implemented": False,
            "answer_generation_implemented": False,
            "training": False,
            "freeform_generation": False,
            "new_canary": False,
            "runtime_or_canonical_answerability_promotion": False,
            "frozen_blind_accessed": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / (
        f"planner_enumeration_answerability_ab_{report_sha}.json"
    )
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = root / "reports/v3" / (
        f"planner_enumeration_answerability_ab_{markdown_sha}.md"
    )
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "planner_enumeration_prompt_sha256": ENUMERATION_PROMPT_SHA256,
        "answerability_model_prompt_sha256": _fixed_prompt_hash(
            ANSWERABILITY_MODEL_PROMPT
        ),
        "model": model_meta,
        "artifacts": {
            "enumeration": {
                "path": _relative(root, enumeration_path),
                "sha256": enumeration_sha,
                "row_count": len(enumeration_rows),
            },
            "predictions": {
                "path": _relative(root, prediction_path),
                "sha256": prediction_sha,
                "row_count": len(prediction_rows),
            },
            "diagnostics": {
                "path": _relative(root, diagnostic_path),
                "sha256": diagnostic_sha,
                "row_count": len(diagnostic_rows),
            },
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "planner_enumeration_decision": "GO_TO_RERANKER_INPUT",
        "answerability_decision": selection["decision"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / (
        f"semantic_answerability_ab_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during answerability A/B: {name}")
    return {
        "planner_enumeration_decision": "GO_TO_RERANKER_INPUT",
        "answerability_selection": selection,
        "approach_a_overall": a_metrics["overall"],
        "approach_b_overall": b_metrics["overall"],
        "enumeration": str(enumeration_path),
        "enumeration_sha256": enumeration_sha,
        "predictions": str(prediction_path),
        "predictions_sha256": prediction_sha,
        "diagnostics": str(diagnostic_path),
        "diagnostics_sha256": diagnostic_sha,
        "report": str(report_path),
        "report_sha256": report_sha,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze planner enumeration and evaluate separated answerability A/B"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        model=args.model,
        batch_size=args.batch_size,
        timeout=args.timeout,
        evaluated_at=args.evaluated_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
