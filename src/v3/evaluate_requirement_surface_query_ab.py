from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.v3 import evaluate_contextual_answer_unit_ab as base
from src.v3 import evaluate_requirement_entity_anchor_ab as entity_arm
from src.v3.requirement_entity_anchor import anchor_requirements, build_official_entity_index
from src.v3.requirement_surface_query import (
    SURFACE_QUERY_VERSION,
    build_surface_scoring_requirements,
    extract_entity_coordinated_surfaces,
)
from src.v3.score_evidence_reranker import MAX_LENGTH, MODEL_NAME, MODEL_REVISION


EVALUATOR_VERSION = "requirement-surface-query-ab-v3.3.1"
CASE_SCHEMA_VERSION = "requirement-surface-query-ab-case-v3.3"
REPORT_SCHEMA_VERSION = "requirement-surface-query-ab-report-v3.3"
MANIFEST_SCHEMA_VERSION = "requirement-surface-query-ab-manifest-v3.3"
DEFAULT_CONTRACT = Path("docs/v3/requirement_surface_query_ab.md")
DEFAULT_ARM0_CASES = Path(
    "data/v3/evidence/requirement_entity_anchor_ab_cases_"
    "dc30eeee3145d25cc0e1321285e631374afe05fce94ea0d687a976af32b40146.jsonl"
)
DEFAULT_ARM0_REPORT = Path(
    "reports/v3/requirement_entity_anchor_ab_"
    "2f1d0f390fc0840fb8ceaae46e672c4898d04804ed6acc4d760217a9241d1f87.json"
)
DEFAULT_ARM0_MANIFEST = Path(
    "data/v3/evidence/requirement_entity_anchor_ab_manifest_"
    "7913a8f6a9ed816fe30ff0f80311f78c63aa1c071251f6fc0d528079202274ae.json"
)
TARGET_LITERAL_SPANS = (
    "- 명성 58,950 이상의 캐릭터로 탐사를 진행할 수 있습니다.",
    "- 탐사는 계정 단위로 진행되며, 한 번에 하나의 탐사만 진행할 수 있습니다.",
)


def _citation_texts(decisions: list[dict[str, Any]]) -> list[str]:
    return [
        citation["text"]
        for decision in decisions
        for citation in decision.get("citations", [])
    ]


def literal_provisional_sibling_hit(
    decisions: list[dict[str, Any]], literals: tuple[str, ...] = TARGET_LITERAL_SPANS
) -> bool:
    citations = _citation_texts(decisions)
    return all(literal in citations for literal in literals)


def _carry_arm0(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_schema_version": CASE_SCHEMA_VERSION,
        "case_id": row["case_id"],
        "dataset": row["dataset"],
        "evaluation_block": row["evaluation_block"],
        "question": row["question"],
        "source_id": row.get("source_id"),
        "arm0_decisions": row["arm1_decisions"],
        "arm1_decisions": row["arm1_decisions"],
        "arm0_score": row["arm1_score"],
        "arm1_score": row["arm1_score"],
        "entity_anchor_audit": row.get("entity_anchor_audit", []),
        "surface_query_audit": None,
        "surface_query_applied": False,
        "surface_query_reason": "structural_preconditions_not_met",
        "sibling_proposal": row.get("sibling_proposal"),
        "provisional_equivalent_official_hit": False,
        "exact_slices": row["exact_slices"],
        "temporal_violation_chunk_ids": row["temporal_violation_chunk_ids"],
        "gold_available_to_decision": False,
    }


def evaluate_rows(
    *,
    root: Path,
    arm0_rows: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eval_by_id = {row["dev_id"]: row for row in evaluations}
    result_by_id = {row["case_id"]: row for row in results}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    temporal = {row["document_id"]: row for row in temporal_rows}
    entity_index = build_official_entity_index(documents, chunks)

    prepared: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    for row in arm0_rows:
        if row["evaluation_block"] != "authored_adaptive_24":
            continue
        source = result_by_id[row["case_id"]]
        evaluation = eval_by_id[row["case_id"]]
        requirements, _ = base._runtime_decisions(source)
        anchored = anchor_requirements(
            evaluation["question"], requirements, entity_index
        )
        extraction = extract_entity_coordinated_surfaces(
            evaluation["question"], anchored
        )
        if extraction is not None:
            prepared[row["case_id"]] = (anchored, extraction)

    demo = None
    output = []
    applied = []
    for row in arm0_rows:
        current = _carry_arm0(row)
        if row["case_id"] not in prepared:
            output.append(current)
            continue
        anchored, extraction = prepared[row["case_id"]]
        source = result_by_id[row["case_id"]]
        evaluation = eval_by_id[row["case_id"]]
        route = source["runtime"]["route"]
        route_sources = list(route.get("source_ids") or [])
        if len(route_sources) != 1:
            current["surface_query_reason"] = "requires_exactly_one_existing_route_source"
            output.append(current)
            continue
        if demo is None:
            demo = base.DemoBackbone(
                root=root, planner_model="qwen3:8b", enable_v3_2_candidates=True
            )
            demo._initialize()
        scoring_requirements = build_surface_scoring_requirements(
            anchored, extraction
        )
        print(f"[surface query] {evaluation['question']}", flush=True)
        bundles = base._contextual_live_sources(
            demo,
            question=evaluation["question"],
            requirements=scoring_requirements,
            route=route,
            source_ids=route_sources,
        )
        decisions = bundles[route_sources[0]]
        arm1_score = {
            **base.score_case(
                evaluation,
                base._runtime_from_decisions(source, decisions),
                chunks_by_id,
                temporal,
            ),
            **base._score_groups(evaluation, decisions),
        }
        decision_view = base._context_decision_view(anchored, decisions)
        provisional = (
            evaluation["question"] == entity_arm.TARGET_QUESTION
            and literal_provisional_sibling_hit(decision_view)
        )
        current.update(
            {
                "arm1_decisions": decision_view,
                "arm1_score": arm1_score,
                "surface_query_audit": extraction,
                "surface_query_applied": True,
                "surface_query_reason": "high_confidence_entity_coordination_shape",
                "provisional_equivalent_official_hit": provisional,
                "exact_slices": base._decisions_exact(decisions, chunks_by_id),
                "temporal_violation_chunk_ids": base._temporal_violations(
                    decisions, route, chunks_by_id
                ),
            }
        )
        applied.append(row["case_id"])
        output.append(current)
    model_record = (
        {
            "reranker_model": MODEL_NAME,
            "reranker_model_revision": MODEL_REVISION,
            "reranker_max_length": MAX_LENGTH,
            "assembler_threshold": demo._assembler_config.get("threshold"),
            "assembler_k": demo._assembler_config.get("k"),
        }
        if demo is not None and demo._assembler_config is not None
        else {}
    )
    return output, {"applied_case_ids": sorted(applied), **model_record}


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else None,
    }


def _block_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    arm0_groups = {row["case_id"] for row in rows if row["arm0_score"]["all_groups_hit"]}
    arm1_groups = {row["case_id"] for row in rows if row["arm1_score"]["all_groups_hit"]}
    arm0_spans = {
        row["case_id"]
        for row in rows
        if row["arm0_score"].get("all_evidence_spans_hit", False)
    }
    arm1_spans = {
        row["case_id"]
        for row in rows
        if row["arm1_score"].get("all_evidence_spans_hit", False)
    }
    arm0_false = {
        row["case_id"]
        for row in rows
        if row["arm0_score"].get("false_full_evidence_span", False)
    }
    arm1_false = {
        row["case_id"]
        for row in rows
        if row["arm1_score"].get("false_full_evidence_span", False)
    }
    return {
        "arm0_all_groups": _ratio(len(arm0_groups), total),
        "arm1_all_groups": _ratio(len(arm1_groups), total),
        "arm0_all_evidence_spans": _ratio(len(arm0_spans), total),
        "arm1_all_evidence_spans": _ratio(len(arm1_spans), total),
        "arm0_false_full_evidence_span": _ratio(len(arm0_false), total),
        "arm1_false_full_evidence_span": _ratio(len(arm1_false), total),
        "strict_regression_case_ids": sorted(arm0_groups - arm1_groups),
        "strict_improvement_case_ids": sorted(arm1_groups - arm0_groups),
        "literal_regression_case_ids": sorted(arm0_spans - arm1_spans),
        "literal_improvement_case_ids": sorted(arm1_spans - arm0_spans),
        "new_false_full_case_ids": sorted(arm1_false - arm0_false),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frozen_rows = [row for row in rows if row["evaluation_block"] == "frozen_docs_69"]
    authored_rows = [
        row for row in rows if row["evaluation_block"] == "authored_adaptive_24"
    ]
    frozen = _block_metrics(frozen_rows)
    authored = _block_metrics(authored_rows)
    target = next(
        row for row in authored_rows if row["question"] == entity_arm.TARGET_QUESTION
    )
    target_literal = literal_provisional_sibling_hit(target["arm1_decisions"])
    checks = {
        "frozen_strict_regression_zero": not frozen["strict_regression_case_ids"],
        "frozen_literal_regression_zero": not frozen["literal_regression_case_ids"],
        "authored_strict_regression_zero": not authored["strict_regression_case_ids"],
        "authored_literal_regression_zero": not authored["literal_regression_case_ids"],
        "authored_literal_improves": bool(authored["literal_improvement_case_ids"]),
        "new_false_full_zero": not frozen["new_false_full_case_ids"]
        and not authored["new_false_full_case_ids"],
        "target_both_literal_spans_cited": target_literal,
        "target_provisional_sibling_requires_literals": target[
            "provisional_equivalent_official_hit"
        ],
        "exact_all": all(row["exact_slices"] for row in rows),
        "temporal_violation_zero": not any(
            row["temporal_violation_chunk_ids"] for row in rows
        ),
    }
    passed = all(checks.values())
    return {
        "frozen_docs_69": frozen,
        "authored_adaptive_24": authored,
        "surface_query_version": SURFACE_QUERY_VERSION,
        "surface_query_applied_case_ids": sorted(
            row["case_id"] for row in rows if row["surface_query_applied"]
        ),
        "target": {
            "case_id": target["case_id"],
            "question": target["question"],
            "arm0_score": target["arm0_score"],
            "arm1_score": target["arm1_score"],
            "arm1_citations": _citation_texts(target["arm1_decisions"]),
            "surface_query_audit": target["surface_query_audit"],
            "original_strict_all_groups": target["arm1_score"]["all_groups_hit"],
            "provisional_equivalent_official_all_groups": target_literal,
            "sibling_proposal_applied": False,
        },
        "gate_checks": checks,
        "gate_passed": passed,
        "decision": (
            "DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED"
            if passed
            else "DEVELOPMENT_NO_GO"
        ),
    }


def _markdown(report: dict[str, Any]) -> bytes:
    result = report["result"]
    frozen = result["frozen_docs_69"]
    authored = result["authored_adaptive_24"]
    target = result["target"]
    lines = [
        "# Entity-anchored requirement surface query A/B",
        "",
        "Development-only. No runtime/canonical promotion.",
        "",
        f"Decision: **{result['decision']}**",
        "",
        "| Block | Arm 0 strict | Arm 1 strict | Arm 0 literal | Arm 1 literal | Arm 0 false-full | Arm 1 false-full |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Frozen docs | {frozen['arm0_all_groups']['successes']}/69 | {frozen['arm1_all_groups']['successes']}/69 | {frozen['arm0_all_evidence_spans']['successes']}/69 | {frozen['arm1_all_evidence_spans']['successes']}/69 | {frozen['arm0_false_full_evidence_span']['successes']}/69 | {frozen['arm1_false_full_evidence_span']['successes']}/69 |",
        f"| Authored adaptive | {authored['arm0_all_groups']['successes']}/24 | {authored['arm1_all_groups']['successes']}/24 | {authored['arm0_all_evidence_spans']['successes']}/24 | {authored['arm1_all_evidence_spans']['successes']}/24 | {authored['arm0_false_full_evidence_span']['successes']}/24 | {authored['arm1_false_full_evidence_span']['successes']}/24 |",
        "",
        f"- applied cases: `{result['surface_query_applied_case_ids']}`",
        f"- strict regressions: `{frozen['strict_regression_case_ids'] + authored['strict_regression_case_ids']}`",
        f"- literal improvements: `{authored['literal_improvement_case_ids']}`",
        "",
        "## 광휘의 행로 target",
        "",
        f"- original strict all-groups: **{target['original_strict_all_groups']}**",
        f"- provisional equivalent-official all-groups (literal-span required): **{target['provisional_equivalent_official_all_groups']}**",
        "- acceptable sibling applied: **False**",
        "",
        "Citations:",
        "",
        *[f"- {citation}" for citation in target["arm1_citations"]],
        "",
        "## Gates",
        "",
        *[f"- {name}: **{value}**" for name, value in result["gate_checks"].items()],
        "",
        "The authored 24 set is adaptive. A pass permits only a new reviewed canary; it does not promote runtime/canonical behavior.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "contract": root / DEFAULT_CONTRACT,
        "arm0_cases": root / DEFAULT_ARM0_CASES,
        "arm0_report": root / DEFAULT_ARM0_REPORT,
        "arm0_manifest": root / DEFAULT_ARM0_MANIFEST,
        "authored_set": root / base.DEFAULT_AUTHORED_SET,
        "authored_results": root / base.DEFAULT_AUTHORED_RESULTS,
        "chunks": root / base.DEFAULT_CHUNKS,
        "documents": root / base.DEFAULT_DOCUMENTS,
        "temporal": root / base.DEFAULT_TEMPORAL,
        "entity_anchor_source": root / "src/v3/requirement_entity_anchor.py",
        "surface_query_source": root / "src/v3/requirement_surface_query.py",
        "reranker_source": root / "src/v3/score_evidence_reranker.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: base.file_sha256(path) for name, path in inputs.items()}
    arm0_rows = base.read_jsonl(inputs["arm0_cases"])
    rows, execution = evaluate_rows(
        root=root,
        arm0_rows=arm0_rows,
        evaluations=base.read_jsonl(inputs["authored_set"]),
        results=base.read_jsonl(inputs["authored_results"]),
        chunks=base.read_jsonl(inputs["chunks"]),
        documents=base.read_jsonl(inputs["documents"]),
        temporal_rows=base.read_jsonl(inputs["temporal"]),
    )
    result = summarize(rows)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_requirement_surface_query_ab",
        "result": result,
        "execution": execution,
        "constraints": {
            "gold_or_labels_changed": False,
            "guide_sibling_applied": False,
            "guide_sibling_provisional_requires_literal_spans": True,
            "gold_available_to_decision": False,
            "new_domain_keyword_rules": 0,
            "planner_or_retrieval_changed": False,
            "training_or_reindex": False,
            "runtime_or_canonical_promoted": False,
            "frozen_blind_accessed": False,
            "authored_set_is_adaptive_not_sealed": True,
        },
        "inputs": {
            name: {"path": path.relative_to(root).as_posix(), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "source_commit": base._git_head(root),
    }
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    cases_bytes = base._serialize_jsonl(
        rows, sort_key=lambda row: (row["evaluation_block"], row["case_id"])
    )
    cases_sha = hashlib.sha256(cases_bytes).hexdigest()
    cases_path = evidence_dir / f"requirement_surface_query_ab_cases_{cases_sha}.jsonl"
    base.write_immutable(cases_path, cases_bytes)
    report_bytes = base._canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"requirement_surface_query_ab_{report_sha}.json"
    base.write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"requirement_surface_query_ab_{markdown_sha}.md"
    base.write_immutable(markdown_path, markdown_bytes)
    after = {name: base.file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("Frozen input changed during requirement surface-query A/B")
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": result["decision"],
        "source_commit": report["source_commit"],
        "inputs": report["inputs"],
        "outputs": {
            "cases": {
                "path": cases_path.relative_to(root).as_posix(),
                "sha256": cases_sha,
                "row_count": len(rows),
            },
            "report_json": {
                "path": report_path.relative_to(root).as_posix(),
                "sha256": report_sha,
            },
            "report_md": {
                "path": markdown_path.relative_to(root).as_posix(),
                "sha256": markdown_sha,
            },
        },
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    manifest_bytes = base._canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = evidence_dir / f"requirement_surface_query_ab_manifest_{manifest_sha}.json"
    base.write_immutable(manifest_path, manifest_bytes)
    return {
        "result": result,
        "cases_path": cases_path.as_posix(),
        "cases_sha256": cases_sha,
        "report_json_path": report_path.as_posix(),
        "report_json_sha256": report_sha,
        "report_md_path": markdown_path.as_posix(),
        "report_md_sha256": markdown_sha,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha,
        "input_hash_mismatch_count": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(evaluate_and_freeze(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
