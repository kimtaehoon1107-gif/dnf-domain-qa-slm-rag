from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.v3 import evaluate_contextual_answer_unit_ab as base
from src.v3.requirement_entity_anchor import (
    ENTITY_ANCHOR_VERSION,
    anchor_requirements,
    build_official_entity_index,
)


EVALUATOR_VERSION = "requirement-entity-anchor-ab-v3.3.0"
CASE_SCHEMA_VERSION = "requirement-entity-anchor-ab-case-v3.3"
REPORT_SCHEMA_VERSION = "requirement-entity-anchor-ab-report-v3.3"
MANIFEST_SCHEMA_VERSION = "requirement-entity-anchor-ab-manifest-v3.3"
DEFAULT_CONTRACT = Path("docs/v3/requirement_entity_anchor_ab.md")
DEFAULT_ARM0_CASES = Path(
    "data/v3/evidence/contextual_answer_unit_ab_cases_"
    "6488e8af285246b3f72452572994a11ffb2244129a54c6cac97f07b251446207.jsonl"
)
DEFAULT_ARM0_REPORT = Path(
    "reports/v3/contextual_answer_unit_ab_"
    "6a3884c3e920e17bf3cb84bc1411d5396b1130f00cf439b2cae8b8745250ec9f.json"
)
DEFAULT_ARM0_MANIFEST = Path(
    "data/v3/evidence/contextual_answer_unit_ab_manifest_"
    "871d455ef01c817dc7fe03ba7c68dacbbffaf6694c6ff16e11f28763e821699c.json"
)
TARGET_QUESTION = (
    "광휘의 행로 탐사에 필요한 최소 명성과 동시에 진행할 수 있는 탐사 수는 어떻게 돼?"
)
QUICK_QUESTION = "퀵계좌이체의 1회·1일·1개월 결제 한도와 하루 횟수 제한을 정리해줘."
GUIDE_DOCUMENT_ID = (
    "document_sha256_e73cf51dad5c8d0378ad907a290b61dfabeb3e55e9b38f041fcad091b8f1e9df"
)
GUIDE_CHUNK_ID = (
    "chunk_sha256_96aad618428b25d25835e640f79d23f936d4d5404ccaf27781d1b619456cd270"
)


def _anchored_requirements_by_case(
    assembler: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    entity_index: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    questions = {row["dev_id"]: row["question"] for row in evaluations}
    return {
        row["case_id"]: anchor_requirements(
            questions[row["case_id"]], row["requirements"], entity_index
        )
        for row in assembler
    }


def _anchored_frozen_inputs(
    assembler: list[dict[str, Any]],
    segment_scores: list[dict[str, Any]],
    requirements_by_case: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    anchored_cases = [
        {**row, "requirements": requirements_by_case[row["case_id"]]}
        for row in assembler
    ]
    anchored_scores = []
    for row in segment_scores:
        if row["retrieval_arm"] != "federated_global":
            anchored_scores.append(row)
            continue
        requirements = requirements_by_case[row["case_id"]]
        anchored_scores.append(
            {
                **row,
                "requirements": [
                    {
                        **score_requirement,
                        "query": base.requirement_text(requirement),
                    }
                    for score_requirement, requirement in zip(
                        row["requirements"], requirements, strict=True
                    )
                ],
            }
        )
    return anchored_cases, anchored_scores


def _anchor_audit(
    original: list[dict[str, Any]], anchored: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": after["requirement_id"],
            "planner_subject": before.get("subject"),
            "anchored_subject": after.get("subject"),
            "changed": before.get("subject") != after.get("subject"),
            "entity_anchor": after.get("entity_anchor"),
        }
        for before, after in zip(original, anchored, strict=True)
    ]


def propose_equivalent_guide_sibling(
    evaluation: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = copy.deepcopy(evaluation)
    guide_text = chunks_by_id[GUIDE_CHUNK_ID]["display_text"]
    missing_spans = [
        group["evidence_span"]
        for group in output["evidence_groups"]
        if group["evidence_span"] not in guide_text
    ]
    if missing_spans:
        raise RuntimeError("Guide sibling does not contain every target evidence span")
    for group in output["evidence_groups"]:
        group["acceptable_chunk_ids"] = sorted(
            set(group["acceptable_chunk_ids"]) | {GUIDE_CHUNK_ID}
        )
        group["document_ids"] = sorted(
            set(group.get("document_ids") or []) | {GUIDE_DOCUMENT_ID}
        )
    return output, {
        "classification": "EQUIVALENT_OFFICIAL_PROPOSED_NOT_APPLIED",
        "canonical_url": "https://df.nexon.com/guide?no=1538",
        "document_id": GUIDE_DOCUMENT_ID,
        "chunk_id": GUIDE_CHUNK_ID,
        "evidence_span_count": len(output["evidence_groups"]),
        "human_review_required": True,
        "gold_changed": False,
    }


def evaluate_frozen(
    *,
    demo: base.DemoBackbone,
    ground_truth: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    assembler: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    segment_scores: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    entity_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    truth = {row["case_id"]: row for row in ground_truth}
    eval_by_id = {row["dev_id"]: row for row in evaluations}
    assembler_by_id = {row["case_id"]: row for row in assembler}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    raw_baseline = base._q4_baseline_decisions(assembler, fallback_rows)
    source_bundles = base._build_isolated_frozen_bundles(
        assembler_cases=assembler,
        segment_score_rows=segment_scores,
        routes=routes,
        chunks=chunks,
        baseline_decisions=raw_baseline,
    )
    control_contextual = base._contextual_frozen_bundles(
        demo=demo,
        assembler_cases=assembler,
        segment_score_rows=segment_scores,
        routes=routes,
        chunks=chunks,
        documents=documents,
    )
    anchored_by_case = _anchored_requirements_by_case(
        assembler, evaluations, entity_index
    )
    anchored_cases, anchored_scores = _anchored_frozen_inputs(
        assembler, segment_scores, anchored_by_case
    )
    anchored_contextual = base._contextual_frozen_bundles(
        demo=demo,
        assembler_cases=anchored_cases,
        segment_score_rows=anchored_scores,
        routes=routes,
        chunks=chunks,
        documents=documents,
    )
    rows = []
    for case_id in sorted(truth):
        if truth[case_id]["answerability_profile"] != "docs_only":
            continue
        requirements = assembler_by_id[case_id]["requirements"]
        anchored = anchored_by_case[case_id]
        route = routes[case_id]
        eligible = (
            base.baseline_allows_corrective_retrieval(raw_baseline[case_id])
            and route["time_scope"] == "current"
            and "dnf_account_policy" not in route["source_ids"]
        )
        source_alternatives = (
            {
                source_id: decisions
                for source_id, decisions in source_bundles[case_id].items()
                if source_id not in set(route["source_ids"])
            }
            if eligible
            else {}
        )
        isolated, _ = base.choose_isolated_decisions(
            requirements,
            raw_baseline[case_id],
            source_alternatives,
            chunks_by_id,
        )
        arm0, _ = base.choose_contextual_decisions(
            requirements,
            isolated,
            control_contextual[case_id] if eligible else {},
            chunks_by_id,
        )
        arm1, audit = base.choose_contextual_decisions(
            anchored,
            arm0,
            anchored_contextual[case_id] if eligible else {},
            chunks_by_id,
        )
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": truth[case_id]["dataset"],
                "evaluation_block": "frozen_docs_69",
                "question": eval_by_id[case_id]["question"],
                "source_id": None,
                "arm0_decisions": base._context_decision_view(requirements, arm0),
                "arm1_decisions": base._context_decision_view(anchored, arm1),
                "entity_anchor_audit": _anchor_audit(requirements, anchored),
                "replacement_audit": audit,
                "arm0_score": base._score_groups(eval_by_id[case_id], arm0),
                "arm1_score": base._score_groups(eval_by_id[case_id], arm1),
                "arm1_adjudicated_score": base._score_groups(
                    eval_by_id[case_id], arm1
                ),
                "sibling_proposal": None,
                "exact_slices": base._decisions_exact(arm1, chunks_by_id),
                "temporal_violation_chunk_ids": base._temporal_violations(
                    arm1, route, chunks_by_id
                ),
                "gold_available_to_decision": False,
            }
        )
    return rows


def evaluate_authored(
    *,
    demo: base.DemoBackbone,
    evaluations: list[dict[str, Any]],
    results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]],
    entity_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    eval_by_id = {row["dev_id"]: row for row in evaluations}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    temporal = {row["document_id"]: row for row in temporal_rows}
    rows = []
    for index, source in enumerate(sorted(results, key=lambda row: row["case_id"]), 1):
        case_id = source["case_id"]
        evaluation = eval_by_id[case_id]
        requirements, raw_baseline = base._runtime_decisions(source)
        anchored = anchor_requirements(
            evaluation["question"], requirements, entity_index
        )
        route = source["runtime"]["route"]
        eligible = (
            base.baseline_allows_corrective_retrieval(raw_baseline)
            and route["time_scope"] == "current"
            and "dnf_account_policy" not in route["source_ids"]
        )
        sources = base.candidate_sources(route)
        print(f"[entity anchor {index}/{len(results)}] {evaluation['question']}", flush=True)
        source_bundles = (
            base._live_source_decisions(
                demo,
                question=evaluation["question"],
                requirements=requirements,
                route=route,
                source_ids=[
                    source_id
                    for source_id in sources
                    if source_id not in set(route["source_ids"])
                ],
            )
            if eligible
            else {}
        )
        isolated, _ = base.choose_isolated_decisions(
            requirements, raw_baseline, source_bundles, chunks_by_id
        )
        control_contextual = (
            base._contextual_live_sources(
                demo,
                question=evaluation["question"],
                requirements=requirements,
                route=route,
                source_ids=sources,
            )
            if eligible
            else {}
        )
        arm0, _ = base.choose_contextual_decisions(
            requirements, isolated, control_contextual, chunks_by_id
        )
        anchored_contextual = (
            base._contextual_live_sources(
                demo,
                question=evaluation["question"],
                requirements=anchored,
                route=route,
                source_ids=sources,
            )
            if eligible
            else {}
        )
        arm1, audit = base.choose_contextual_decisions(
            anchored, arm0, anchored_contextual, chunks_by_id
        )
        arm0_score = {
            **base.score_case(
                evaluation,
                base._runtime_from_decisions(source, arm0),
                chunks_by_id,
                temporal,
            ),
            **base._score_groups(evaluation, arm0),
        }
        arm1_score = {
            **base.score_case(
                evaluation,
                base._runtime_from_decisions(source, arm1),
                chunks_by_id,
                temporal,
            ),
            **base._score_groups(evaluation, arm1),
        }
        adjudicated_evaluation = evaluation
        sibling_proposal = None
        if evaluation["question"] == TARGET_QUESTION:
            adjudicated_evaluation, sibling_proposal = propose_equivalent_guide_sibling(
                evaluation, chunks_by_id
            )
        adjudicated_score = {
            **arm1_score,
            **base._score_groups(adjudicated_evaluation, arm1),
        }
        rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": "authored_validation_v3_2_adaptive",
                "evaluation_block": "authored_adaptive_24",
                "question": evaluation["question"],
                "source_id": evaluation["source_ids"][0],
                "arm0_decisions": base._context_decision_view(requirements, arm0),
                "arm1_decisions": base._context_decision_view(anchored, arm1),
                "entity_anchor_audit": _anchor_audit(requirements, anchored),
                "replacement_audit": audit,
                "arm0_score": arm0_score,
                "arm1_score": arm1_score,
                "arm1_adjudicated_score": adjudicated_score,
                "sibling_proposal": sibling_proposal,
                "exact_slices": base._decisions_exact(arm1, chunks_by_id),
                "temporal_violation_chunk_ids": arm1_score[
                    "temporal_violation_chunk_ids"
                ],
                "gold_available_to_decision": False,
            }
        )
    return rows


def summarize(
    frozen_rows: list[dict[str, Any]], authored_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    strict = base.summarize(frozen_rows, authored_rows)
    target = next(row for row in authored_rows if row["question"] == TARGET_QUESTION)
    quick = next(row for row in authored_rows if row["question"] == QUICK_QUESTION)
    target_citations = [
        citation["text"]
        for decision in target["arm1_decisions"]
        for citation in decision["citations"]
    ]
    target_chunk_ids = {
        citation["chunk_id"]
        for decision in target["arm1_decisions"]
        for citation in decision["citations"]
    }
    authored_adjudicated_hits = sum(
        row["arm1_adjudicated_score"]["all_groups_hit"] for row in authored_rows
    )
    anchored_questions = sum(
        any(audit["changed"] for audit in row["entity_anchor_audit"])
        for row in frozen_rows + authored_rows
    )
    checks = {
        "base_strict_gate_passed": strict["strict_gate_passed"],
        "target_both_literal_spans_cited": all(
            expected in target_citations
            for expected in (
                "- 명성 58,950 이상의 캐릭터로 탐사를 진행할 수 있습니다.",
                "- 탐사는 계정 단위로 진행되며, 한 번에 하나의 탐사만 진행할 수 있습니다.",
            )
        ),
        "target_guide_chunk_cited": GUIDE_CHUNK_ID in target_chunk_ids,
        "target_sibling_collision_zero": not any(
            "광휘의 잔영" in text for text in target_citations
        ),
        "quick_four_literal_spans_preserved": quick["arm1_score"][
            "all_evidence_spans_hit"
        ],
        "exact_all": all(row["exact_slices"] for row in frozen_rows + authored_rows),
        "temporal_violation_zero": not any(
            row["temporal_violation_chunk_ids"]
            for row in frozen_rows + authored_rows
        ),
    }
    passed = all(checks.values())
    return {
        "strict": strict,
        "entity_anchor_version": ENTITY_ANCHOR_VERSION,
        "anchored_question_count": anchored_questions,
        "target": {
            "question": TARGET_QUESTION,
            "arm0_score": target["arm0_score"],
            "arm1_original_strict_score": target["arm1_score"],
            "arm1_provisional_adjudicated_score": target[
                "arm1_adjudicated_score"
            ],
            "sibling_proposal": target["sibling_proposal"],
            "citations": target_citations,
        },
        "authored_provisional_adjudicated_all_groups": base._ratio(
            authored_adjudicated_hits, len(authored_rows)
        ),
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
    strict = result["strict"]
    target = result["target"]
    lines = [
        "# Requirement entity-anchor A/B",
        "",
        f"Decision: **{result['decision']}**",
        "",
        "## Aggregate",
        "",
        f"- anchored questions: **{result['anchored_question_count']}**",
        f"- frozen all-groups: **{strict['frozen_docs_69']['arm0_all_groups']['successes']}/69 → {strict['frozen_docs_69']['arm1_all_groups']['successes']}/69**",
        f"- authored all-groups strict: **{strict['authored_adaptive_24']['arm0_all_groups']['successes']}/24 → {strict['authored_adaptive_24']['arm1_all_groups']['successes']}/24**",
        f"- authored literal spans: **{strict['authored_adaptive_24']['arm0_all_evidence_spans']['successes']}/24 → {strict['authored_adaptive_24']['arm1_all_evidence_spans']['successes']}/24**",
        f"- authored provisional adjudicated all-groups: **{result['authored_provisional_adjudicated_all_groups']['successes']}/24**",
        "",
        "## Target",
        "",
        f"Question: {target['question']}",
        "",
        f"- original strict all-groups: **{target['arm1_original_strict_score']['all_groups_hit']}**",
        f"- provisional adjudicated all-groups: **{target['arm1_provisional_adjudicated_score']['all_groups_hit']}**",
        f"- sibling classification: **{target['sibling_proposal']['classification']}**",
        "",
        "Citations:",
        "",
        *[f"- {citation}" for citation in target["citations"]],
        "",
        "## Gates",
        "",
        *[f"- {name}: **{value}**" for name, value in result["gate_checks"].items()],
        "",
        "No gold, label, runtime, or canonical artifact was changed.",
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
        "ground_truth": root / base.DEFAULT_GROUND_TRUTH,
        "adaptive_dev": root / base.DEFAULT_DEV,
        "downgraded_canary": root / base.DEFAULT_CANARY,
        "q3_cases": root / base.DEFAULT_Q3_CASES,
        "assembler_cases": root / base.DEFAULT_ASSEMBLER_CASES,
        "enumeration": root / base.DEFAULT_ENUMERATION,
        "segment_scores": root / base.DEFAULT_SEGMENT_SCORES,
        "dev_runtime": root / base.DEFAULT_DEV_RUNTIME,
        "canary_runtime": root / base.DEFAULT_CANARY_RUNTIME,
        "chunks": root / base.DEFAULT_CHUNKS,
        "documents": root / base.DEFAULT_DOCUMENTS,
        "temporal": root / base.DEFAULT_TEMPORAL,
        "authored_set": root / base.DEFAULT_AUTHORED_SET,
        "authored_results": root / base.DEFAULT_AUTHORED_RESULTS,
        "entity_anchor_source": root / "src/v3/requirement_entity_anchor.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    before = {name: base.file_sha256(path) for name, path in inputs.items()}
    chunks = base.read_jsonl(inputs["chunks"])
    documents = base.read_jsonl(inputs["documents"])
    entity_index = build_official_entity_index(documents, chunks)
    evaluations = base.read_jsonl(inputs["adaptive_dev"]) + base.read_jsonl(
        inputs["downgraded_canary"]
    )
    assembler = base.enrich_assembler_cases(
        base.read_jsonl(inputs["assembler_cases"]),
        base.read_jsonl(inputs["enumeration"]),
    )
    segment_scores = base.read_jsonl(inputs["segment_scores"])
    routes = base._route_map(
        base.read_jsonl(inputs["dev_runtime"]),
        base.read_jsonl(inputs["canary_runtime"]),
    )
    fallback_cases, fallback_scores = base.build_bounded_fallback_inputs(
        assembler_cases=assembler,
        segment_score_rows=segment_scores,
        routes=routes,
        chunks=chunks,
    )
    fallback_rows = base.assemble_chunk_diverse_configuration(
        fallback_cases,
        fallback_scores,
        threshold=base.ASSEMBLER_THRESHOLD,
        k=base.ASSEMBLER_K,
    )
    demo = base.DemoBackbone(
        root=root, planner_model="qwen3:8b", enable_v3_2_candidates=True
    )
    demo._initialize()
    frozen_rows = evaluate_frozen(
        demo=demo,
        ground_truth=base.read_jsonl(inputs["ground_truth"]),
        evaluations=evaluations,
        assembler=assembler,
        fallback_rows=fallback_rows,
        segment_scores=segment_scores,
        routes=routes,
        chunks=chunks,
        documents=documents,
        entity_index=entity_index,
    )
    authored_rows = evaluate_authored(
        demo=demo,
        evaluations=base.read_jsonl(inputs["authored_set"]),
        results=base.read_jsonl(inputs["authored_results"]),
        chunks=chunks,
        temporal_rows=base.read_jsonl(inputs["temporal"]),
        entity_index=entity_index,
    )
    result = summarize(frozen_rows, authored_rows)
    rows = frozen_rows + authored_rows
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_requirement_entity_anchor_ab",
        "result": result,
        "constraints": {
            "gold_or_labels_changed": False,
            "guide_sibling_applied": False,
            "guide_sibling_provisional_only": True,
            "gold_available_to_decision": False,
            "new_domain_keyword_rules": 0,
            "training_or_reindex": False,
            "runtime_or_canonical_promoted": False,
            "frozen_blind_accessed": False,
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
    cases_path = evidence_dir / f"requirement_entity_anchor_ab_cases_{cases_sha}.jsonl"
    base.write_immutable(cases_path, cases_bytes)
    report_bytes = base._canonical_json_bytes(report, indent=2)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = reports_dir / f"requirement_entity_anchor_ab_{report_sha}.json"
    base.write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = reports_dir / f"requirement_entity_anchor_ab_{markdown_sha}.md"
    base.write_immutable(markdown_path, markdown_bytes)
    after = {name: base.file_sha256(path) for name, path in inputs.items()}
    if before != after:
        raise RuntimeError("Frozen input changed during entity-anchor A/B")
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
    manifest_path = evidence_dir / f"requirement_entity_anchor_ab_manifest_{manifest_sha}.json"
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
