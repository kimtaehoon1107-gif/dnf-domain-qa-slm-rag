from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_router_backbone_ab import _score_arm, simulate_arm
from src.v3.requirement_value_shape import VALUE_SHAPE_VERSION, apply_value_shape_veto


EVALUATOR_VERSION = "value-shape-veto-b1-ab-v3.2.0"
CASE_SCHEMA_VERSION = "value-shape-veto-b1-case-v3.2"
REPORT_SCHEMA_VERSION = "value-shape-veto-b1-report-v3.2"
MANIFEST_SCHEMA_VERSION = "value-shape-veto-b1-manifest-v3.2"

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
DEFAULT_FALSE_FULL = Path(
    "data/v3/evidence/false_full_case_audit_"
    "c2f0bee2fbcc9e0d8941c47aaa7912429fad62b23c7bf35a3baf6fcbba0d1ec0.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/value_shape_veto_b1.md")


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


def _evaluation_by_case(dev_rows: list[dict[str, Any]], canary_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = dev_rows + canary_rows
    output = {row["dev_id"]: row for row in rows}
    if len(output) != len(rows):
        raise RuntimeError("Duplicate evaluation case IDs")
    return output


def _build_arm(
    *,
    question: str,
    decisions: list[dict[str, Any]],
    chunk_to_parent: dict[str, str],
) -> dict[str, Any]:
    return simulate_arm(
        placement="arm0",
        question=question,
        assembler_decisions=decisions,
        classifier_predictions=[],
        chunk_to_parent=chunk_to_parent,
    )


def _score(
    arm: dict[str, Any],
    *,
    target: str,
    evidence_groups: list[dict[str, Any]],
    requirement_count: int,
    baseline_supported_indices: set[int],
) -> dict[str, Any]:
    return _score_arm(
        arm,
        target=target,
        evidence_groups=evidence_groups,
        expected_docs_flags=[True] * requirement_count,
        baseline_supported_indices=baseline_supported_indices,
    )


def build_case_rows(
    *,
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    backbone_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    false_full_case_ids: set[str],
) -> list[dict[str, Any]]:
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    backbones = {row["case_id"]: row for row in backbone_rows}
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    chunk_to_parent = {row["chunk_id"]: row["parent_document_id"] for row in chunks}

    if not (set(enumerations) == set(assemblers) == set(backbones) == set(evaluations)):
        raise RuntimeError("Frozen 95-case joins do not have identical case IDs")

    output = []
    for case_id in sorted(backbones):
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
        arm0 = _build_arm(
            question=evaluation["question"],
            decisions=decisions,
            chunk_to_parent=chunk_to_parent,
        )
        arm0_score = _score(
            arm0,
            target=backbone["answerability_target"],
            evidence_groups=evaluation["evidence_groups"],
            requirement_count=len(requirements),
            baseline_supported_indices=baseline_supported,
        )
        frozen_score = backbone["arm0"]["score"]
        score_keys = (
            "grounded_answer",
            "false_full_answer",
            "false_partial",
            "honest_partial",
            "answerable_overreject",
            "reject_correct",
            "realtime_safe_abstain",
            "realtime_static_exposure",
        )
        if any(arm0_score[key] != frozen_score[key] for key in score_keys):
            raise RuntimeError(f"Failed to reproduce frozen Arm0 score: {case_id}")

        b1_decisions = []
        audits = []
        for requirement, decision in zip(requirements, decisions, strict=True):
            transformed, audit = apply_value_shape_veto(requirement, decision)
            b1_decisions.append(transformed)
            audits.append(audit)
        arm_b1 = _build_arm(
            question=evaluation["question"],
            decisions=b1_decisions,
            chunk_to_parent=chunk_to_parent,
        )
        arm_b1_score = _score(
            arm_b1,
            target=backbone["answerability_target"],
            evidence_groups=evaluation["evidence_groups"],
            requirement_count=len(requirements),
            baseline_supported_indices=baseline_supported,
        )
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": backbone["dataset"],
                "answerability_target": backbone["answerability_target"],
                "baseline_false_full_audit_member": case_id in false_full_case_ids,
                "arm0": {**arm0, "score": arm0_score},
                "arm_b1": {**arm_b1, "score": arm_b1_score},
                "requirement_audits": audits,
                "question_or_gold_text_included": False,
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_veto": False,
            }
        )
    return output


def summarize(case_rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    docs = [row for row in case_rows if row["answerability_target"] == "answerable_docs"]
    reject = [row for row in case_rows if row["answerability_target"] == "reject"]
    realtime = [row for row in case_rows if row["answerability_target"] == "realtime_api"]
    return {
        "question_count": len(case_rows),
        "answerable": {
            "grounded_answer": _ratio(sum(row[arm]["score"]["grounded_answer"] for row in docs), len(docs)),
            "false_full_answer": _ratio(sum(row[arm]["score"]["false_full_answer"] for row in docs), len(docs)),
            "honest_partial": _ratio(sum(row[arm]["score"]["honest_partial"] for row in docs), len(docs)),
            "false_partial": _ratio(sum(row[arm]["score"]["false_partial"] for row in docs), len(docs)),
            "overreject": _ratio(sum(row[arm]["score"]["answerable_overreject"] for row in docs), len(docs)),
        },
        "reject_correct": _ratio(sum(row[arm]["score"]["reject_correct"] for row in reject), len(reject)),
        "realtime_safe_abstain": _ratio(sum(row[arm]["score"]["realtime_safe_abstain"] for row in realtime), len(realtime)),
        "realtime_static_exposure": _ratio(sum(row[arm]["score"]["realtime_static_exposure"] for row in realtime), len(realtime)),
    }


def evaluate_gate(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    arm0 = summarize(case_rows, "arm0")
    b1 = summarize(case_rows, "arm_b1")
    grounded_regressions = sorted(
        row["case_id"]
        for row in case_rows
        if row["arm0"]["score"]["grounded_answer"]
        and not row["arm_b1"]["score"]["grounded_answer"]
    )
    new_false_partial = sorted(
        row["case_id"]
        for row in case_rows
        if not row["arm0"]["score"]["false_partial"]
        and row["arm_b1"]["score"]["false_partial"]
    )
    vetoed = [row for row in case_rows if any(audit["vetoed"] for audit in row["requirement_audits"])]
    vetoed_false_full = [row for row in vetoed if row["arm0"]["score"]["false_full_answer"]]
    resolved_false_full = sorted(
        row["case_id"]
        for row in case_rows
        if row["arm0"]["score"]["false_full_answer"]
        and not row["arm_b1"]["score"]["false_full_answer"]
    )
    checks = {
        "frozen_baseline_reproduced_73_grounded": arm0["answerable"]["grounded_answer"]["successes"] == 73,
        "frozen_baseline_reproduced_9_false_full": arm0["answerable"]["false_full_answer"]["successes"] == 9,
        "grounded_73_maintained": b1["answerable"]["grounded_answer"]["successes"] >= 73,
        "false_full_below_9": b1["answerable"]["false_full_answer"]["successes"] < 9,
        "grounded_to_non_grounded_regression_zero": not grounded_regressions,
        "new_false_partial_zero": not new_false_partial,
        "reject_11_of_11_maintained": b1["reject_correct"]["successes"] == 11,
        "realtime_safe_abstain_2_of_2_maintained": b1["realtime_safe_abstain"]["successes"] == 2,
        "realtime_static_exposure_zero": b1["realtime_static_exposure"]["successes"] == 0,
    }
    return {
        "pass": all(checks.values()),
        "decision": "GO_B1_DEV_AB_ONLY_B2_ALLOWED_NOT_PROMOTED" if all(checks.values()) else "NO_GO_B1_KEEP_CURRENT_RUNTIME",
        "checks": checks,
        "grounded_regression_case_ids": grounded_regressions,
        "new_false_partial_case_ids": new_false_partial,
        "resolved_false_full_case_ids": resolved_false_full,
        "veto_precision_against_observed_false_full": _ratio(len(vetoed_false_full), len(vetoed)),
        "vetoed_question_count": len(vetoed),
        "vetoed_requirement_count": sum(
            audit["vetoed"] for row in case_rows for audit in row["requirement_audits"]
        ),
    }


def summarize_veto_kinds(case_rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    aggregate: dict[str, Counter[str]] = defaultdict(Counter)
    for row in case_rows:
        baseline = row["arm0"]["score"]
        candidate = row["arm_b1"]["score"]
        vetoed_kinds = {
            audit["expected_kind"]
            for audit in row["requirement_audits"]
            if audit["vetoed"]
        }
        for kind in vetoed_kinds:
            values = aggregate[str(kind)]
            values["vetoed_questions"] += 1
            values["vetoed_requirements"] += sum(
                audit["vetoed"] and audit["expected_kind"] == kind
                for audit in row["requirement_audits"]
            )
            values["baseline_grounded_questions"] += baseline["grounded_answer"]
            values["grounded_regressions"] += (
                baseline["grounded_answer"] and not candidate["grounded_answer"]
            )
            values["baseline_false_full_questions"] += baseline["false_full_answer"]
            values["resolved_false_full_questions"] += (
                baseline["false_full_answer"]
                and not candidate["false_full_answer"]
            )
            values["new_false_partial_questions"] += (
                not baseline["false_partial"] and candidate["false_partial"]
            )
    return {
        kind: dict(sorted(values.items()))
        for kind, values in sorted(aggregate.items())
    }


def _render_markdown(report: dict[str, Any]) -> bytes:
    a = report["arms"]["arm0"]
    b = report["arms"]["arm_b1"]
    gate = report["gate"]
    lines = [
        "# Value-shape veto B1 development A/B",
        "",
        "This is an absence-only safety veto. A matching value shape does not prove semantic support.",
        "No runtime/canonical promotion, retrieval expansion, model inference, or training occurred.",
        "",
        "| Metric | Arm0 | ArmB1 |",
        "|---|---:|---:|",
        f"| Grounded answer | {a['answerable']['grounded_answer']['successes']}/82 | {b['answerable']['grounded_answer']['successes']}/82 |",
        f"| False full | {a['answerable']['false_full_answer']['successes']}/82 | {b['answerable']['false_full_answer']['successes']}/82 |",
        f"| Honest partial | {a['answerable']['honest_partial']['successes']}/82 | {b['answerable']['honest_partial']['successes']}/82 |",
        f"| False partial | {a['answerable']['false_partial']['successes']}/82 | {b['answerable']['false_partial']['successes']}/82 |",
        f"| Reject correct | {a['reject_correct']['successes']}/11 | {b['reject_correct']['successes']}/11 |",
        f"| Realtime safe abstain | {a['realtime_safe_abstain']['successes']}/2 | {b['realtime_safe_abstain']['successes']}/2 |",
        "",
        f"Decision: **{gate['decision']}**.",
        f"Vetoed requirements: {gate['vetoed_requirement_count']}; vetoed questions: {gate['vetoed_question_count']}.",
        "Observed false-full precision among vetoed questions: "
        f"{gate['veto_precision_against_observed_false_full']['successes']}/{gate['veto_precision_against_observed_false_full']['total']}.",
        f"Resolved false-full IDs: {', '.join(gate['resolved_false_full_case_ids']) or 'none'}.",
        "",
        "## Aggregate diagnostic by typed shape",
        "",
        "A question can appear under more than one kind when multiple requirements were vetoed.",
        "",
        "| Kind | Vetoed reqs | Vetoed questions | False-full resolved | Grounded regressions | New false-partials |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, values in report["veto_kind_diagnostic"].items():
        lines.append(
            f"| {kind} | {values['vetoed_requirements']} | {values['vetoed_questions']} | "
            f"{values['resolved_false_full_questions']} | {values['grounded_regressions']} | "
            f"{values['new_false_partial_questions']} |"
        )
    lines.extend(
        [
        "",
        "B2 selective retrieval expansion is allowed only if this report passes; it is not implemented or run here.",
        "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": root / DEFAULT_ASSEMBLER,
        "backbone_cases": root / DEFAULT_BACKBONE,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "chunks": root / DEFAULT_CHUNKS,
        "false_full_audit": root / DEFAULT_FALSE_FULL,
        "contract": root / DEFAULT_CONTRACT,
        "value_shape_source": root / "src/v3/requirement_value_shape.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    dev_rows = read_jsonl(inputs["adaptive_dev"])
    canary_rows = read_jsonl(inputs["downgraded_canary"])
    case_rows = build_case_rows(
        enumeration_rows=read_jsonl(inputs["enumeration"]),
        assembler_rows=read_jsonl(inputs["assembler_cases"]),
        backbone_rows=read_jsonl(inputs["backbone_cases"]),
        evaluation_rows=dev_rows + canary_rows,
        chunks=read_jsonl(inputs["chunks"]),
        false_full_case_ids={row["case_id"] for row in read_jsonl(inputs["false_full_audit"])},
    )
    arms = {arm: summarize(case_rows, arm) for arm in ("arm0", "arm_b1")}
    gate = evaluate_gate(case_rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "value_shape_version": VALUE_SHAPE_VERSION,
        "evaluation_role": "development_only_absence_veto_ab_no_promotion",
        "arms": arms,
        "gate": gate,
        "veto_kind_diagnostic": summarize_veto_kinds(case_rows),
        "constraints": {
            "search_changed": False,
            "router_changed": False,
            "planner_changed": False,
            "assembler_selection_changed": False,
            "model_inference_calls": 0,
            "question_or_gold_used_by_veto": False,
            "matching_shape_treated_as_positive_support": False,
            "runtime_or_canonical_promoted": False,
            "b2_executed": False,
        },
        "inputs": {name: {"path": path.resolve().relative_to(root).as_posix(), "sha256": before[name]} for name, path in inputs.items()},
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = _serialize_jsonl(case_rows, sort_key=lambda row: row["case_id"])
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"value_shape_veto_b1_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)

    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"value_shape_veto_b1_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _render_markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"value_shape_veto_b1_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    after = {name: file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("A frozen B1 input changed during evaluation")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "decision": gate["decision"],
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
    manifest_path = evidence_dir / f"value_shape_veto_b1_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "decision": gate["decision"],
        "cases": str(cases_path),
        "report": str(report_path),
        "report_markdown": str(markdown_path),
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "metrics": arms,
        "gate": gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the development-only value-shape veto B1 A/B")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(evaluate_and_freeze(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
