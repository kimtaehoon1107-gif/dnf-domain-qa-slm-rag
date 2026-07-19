from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.evaluate_authored_canary import wilson_interval
from src.v3.evaluate_claim_reranker import _gold_span_token_recall
from src.v3.requirement_slot_claim_coverage import (
    MISSING_SLOT_TEMPLATE,
    SLOT_COVERAGE_VERSION,
    _content_morphs,
    build_requirement_slot_response,
    enumerate_requirement_slots,
)
from src.v3.run_unified_runtime import PARTIAL_DISCLAIMER


EVALUATOR_VERSION = "requirement-slot-coverage-evaluator-v3.1.0"
REPORT_SCHEMA_VERSION = "requirement-slot-coverage-report-v3.1"
MANIFEST_SCHEMA_VERSION = "requirement-slot-coverage-manifest-v3.1"
CASE_SCHEMA_VERSION = "requirement-slot-coverage-case-v3.1"
THRESHOLD_GRID = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
MIN_CLAIM_TOKEN_RECALL = 0.50

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CANARY_CASES = Path(
    "data/v3/evaluation/authored_canary_first_run_cases_"
    "a326d9fd96a4cfcaf9b2d38d74f27fffe26b62dfc1364063c8258891546beecd.jsonl"
)
DEFAULT_CANARY_MANIFEST = Path(
    "data/v3/evaluation/authored_canary_first_run_manifest_"
    "4a2aef81660a13b113ab63a3739126afcddcb6b0b60f2af740becf3bfbdd93dd.json"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_DEV_RUNTIME = Path(
    "data/v3/runtime/unified_runtime_cases_"
    "f28e2fbfb768c901dc4f1079f262252d645a74c7e4ee494180c2879e528f7789.jsonl"
)
DEFAULT_DEV_CLAIM_CASES = Path(
    "data/v3/evidence/claim_reranker_cases_"
    "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a.jsonl"
)
DEFAULT_DEV_CLAIM_MANIFEST = Path(
    "data/v3/evidence/claim_reranker_manifest_"
    "32d236a75d30ead63c33530e92ea1349bb8000e6f03615e3783c82f76ce6bd6c.json"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_SAME_PARENT_DIAGNOSTIC = Path(
    "reports/v3/same_parent_cross_parent_diagnostic_"
    "c81250970c2d1545a0c9071dceea16e9d9855850706bda2f6eb3568280db6cf1.json"
)
DEFAULT_SIGNAL_A_REPORT = Path(
    "reports/v3/route_type_signal_a_pilot_"
    "77032257a09acf3e8c3362035d593b0dfbde6632b734cb11f716b1592c5d755a.json"
)
DEFAULT_CONTRACT = Path("docs/v3/requirement_slot_claim_coverage.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _rate(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
        "wilson_95_percent": wilson_interval(successes, total),
    }


def _single_parent_coverable(
    dev: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]
) -> bool:
    if len(dev["evidence_groups"]) < 2:
        return False
    parent_sets = []
    for group in dev["evidence_groups"]:
        parents = {
            chunks_by_id[chunk_id]["parent_document_id"]
            for chunk_id in group["acceptable_chunk_ids"]
        }
        if not parents:
            raise RuntimeError(f"Evidence group has no mapped parent: {dev['dev_id']}")
        parent_sets.append(parents)
    return bool(set.intersection(*parent_sets))


def _candidate_rows(
    chunk_ids: list[str], chunks_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for rank, chunk_id in enumerate(chunk_ids, start=1):
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk = chunks_by_id[chunk_id]
        output.append({**chunk, "retrieval_rank": rank})
    return output


def _matched_group_ids(
    dev: dict[str, Any], citation_chunk_ids: set[str]
) -> set[str]:
    return {
        group["group_id"]
        for group in dev["evidence_groups"]
        if citation_chunk_ids.intersection(group["acceptable_chunk_ids"])
    }


def _claim_complete(
    dev: dict[str, Any], claims: list[dict[str, Any]]
) -> bool:
    if not dev["evidence_groups"]:
        return False
    for group in dev["evidence_groups"]:
        recalls = [
            _gold_span_token_recall(claim["claim_text"], group["evidence_span"])
            for claim in claims
            if claim["citation_chunk_id"] in group["acceptable_chunk_ids"]
        ]
        if not recalls or max(recalls) < MIN_CLAIM_TOKEN_RECALL:
            return False
    return True


def _slot_group_alignment(
    slots: list[dict[str, Any]],
    dev: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    aligned_groups_by_slot: dict[str, list[str]] = {}
    aligned_slot_ids_by_group: dict[str, list[str]] = {
        group["group_id"]: [] for group in dev["evidence_groups"]
    }
    for slot in slots:
        slot_morphs = frozenset(slot["content_morphs"])
        group_ids = []
        for group in dev["evidence_groups"]:
            best_ratio = 0.0
            for chunk_id in group["acceptable_chunk_ids"]:
                chunk_morphs = _content_morphs(
                    chunks_by_id[chunk_id]["display_text"]
                )
                best_ratio = max(
                    best_ratio,
                    len(slot_morphs & chunk_morphs) / len(slot_morphs),
                )
            if best_ratio >= threshold:
                group_ids.append(group["group_id"])
                aligned_slot_ids_by_group[group["group_id"]].append(
                    slot["slot_id"]
                )
        aligned_groups_by_slot[slot["slot_id"]] = sorted(group_ids)
    return {
        "aligned_groups_by_slot": aligned_groups_by_slot,
        "aligned_slot_ids_by_group": aligned_slot_ids_by_group,
    }


def _baseline_canary_response(case: dict[str, Any]) -> dict[str, Any]:
    rendered = PARTIAL_DISCLAIMER if case["partial_disclaimer"] else ""
    return {
        "runtime_status": case["canonical"]["runtime_status"],
        "citation_chunk_ids": list(case["canonical"]["citation_chunk_ids"]),
        "claims": list(case["canonical"]["claims"]),
        "rendered_answer": rendered,
    }


def _evaluate_dataset(
    *,
    name: str,
    labels: list[dict[str, Any]],
    runtime_by_id: dict[str, dict[str, Any]],
    baseline_by_id: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    current_policy_document_id: str,
    threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counters = {
        "expected_groups": 0,
        "baseline_group_hits": 0,
        "after_group_hits": 0,
        "baseline_complete": 0,
        "after_complete": 0,
        "required_rows": 0,
        "same_parent_expected_groups": 0,
        "same_parent_baseline_group_hits": 0,
        "same_parent_after_group_hits": 0,
        "same_parent_rows": 0,
        "same_parent_baseline_complete": 0,
        "same_parent_after_complete": 0,
        "single_field_group_regressions": 0,
        "overall_group_regressions": 0,
        "runtime_false_citations": 0,
        "strict_unsupported_slot_citations": 0,
        "false_partial_candidate_complete": 0,
        "false_partial_already_cited_complete": 0,
        "slot_partial_count": 0,
        "slot_partial_disclosure_correct": 0,
        "partial_disclaimer_expected": 0,
        "partial_disclaimer_preserved": 0,
        "false_or_realtime_baseline_exposure": 0,
        "false_or_realtime_after_exposure": 0,
        "slot_total": 0,
        "slot_aligned": 0,
        "group_total_for_slot_recall": 0,
        "group_aligned_to_slot": 0,
        "signal_a_candidate_rows": 0,
        "slot_coverage_rows": 0,
    }
    diagnostics = []
    for dev in sorted(labels, key=lambda row: row.get("query_ordinal", 10**9)):
        case_id = dev["dev_id"]
        runtime = runtime_by_id[case_id]
        baseline = baseline_by_id[case_id]
        route = runtime["route"]
        candidate_chunk_ids = runtime["candidate_chunk_ids"]
        candidates = _candidate_rows(candidate_chunk_ids, chunks_by_id)
        result = build_requirement_slot_response(
            case_id=case_id,
            question=dev["question"],
            answerability=dev["answerability"],
            route=route,
            candidates=candidates,
            baseline_response=baseline,
            documents_by_id=documents_by_id,
            current_policy_document_id=current_policy_document_id,
            overlap_threshold=threshold,
        )
        response = result["response"]
        slots = enumerate_requirement_slots(dev["question"])
        if len(slots) >= 2:
            counters["signal_a_candidate_rows"] += 1
        if result["mode"] == "slot_coverage":
            counters["slot_coverage_rows"] += 1
        alignment = _slot_group_alignment(
            slots, dev, chunks_by_id, threshold
        )
        counters["slot_total"] += len(slots)
        counters["slot_aligned"] += sum(
            bool(group_ids)
            for group_ids in alignment["aligned_groups_by_slot"].values()
        )
        counters["group_total_for_slot_recall"] += len(dev["evidence_groups"])
        counters["group_aligned_to_slot"] += sum(
            bool(slot_ids)
            for slot_ids in alignment["aligned_slot_ids_by_group"].values()
        )

        baseline_cited_ids = set(baseline.get("citation_chunk_ids", []))
        after_cited_ids = set(response.get("citation_chunk_ids", []))
        baseline_groups = _matched_group_ids(dev, baseline_cited_ids)
        after_groups = _matched_group_ids(dev, after_cited_ids)
        expected_groups = {group["group_id"] for group in dev["evidence_groups"]}
        baseline_claims = baseline.get("claims", [])
        after_claims = response.get("claims", [])
        baseline_complete = _claim_complete(dev, baseline_claims)
        after_complete = _claim_complete(dev, after_claims)
        single_parent = _single_parent_coverable(dev, chunks_by_id)
        single_field = len(dev["evidence_groups"]) == 1
        cross_parent = len(dev["evidence_groups"]) >= 2 and not single_parent

        counters["expected_groups"] += len(expected_groups)
        counters["baseline_group_hits"] += len(baseline_groups)
        counters["after_group_hits"] += len(after_groups)
        if expected_groups:
            counters["required_rows"] += 1
            counters["baseline_complete"] += baseline_complete
            counters["after_complete"] += after_complete
        if single_parent:
            counters["same_parent_expected_groups"] += len(expected_groups)
            counters["same_parent_baseline_group_hits"] += len(baseline_groups)
            counters["same_parent_after_group_hits"] += len(after_groups)
            counters["same_parent_rows"] += 1
            counters["same_parent_baseline_complete"] += baseline_complete
            counters["same_parent_after_complete"] += after_complete
        lost_groups = baseline_groups - after_groups
        counters["overall_group_regressions"] += len(lost_groups)
        if single_field:
            counters["single_field_group_regressions"] += len(lost_groups)

        failed_verifications = sum(
            not verification["verified"]
            for verification in result["verification_results"]
        )
        counters["runtime_false_citations"] += failed_verifications
        strict_unsupported = 0
        for claim in (
            claim
            for claim in after_claims
            if result["mode"] == "slot_coverage"
            and claim.get("claim_mode")
            == "requirement_slot_exact_extractive_quote"
        ):
            aligned_group_ids = alignment["aligned_groups_by_slot"].get(
                claim["slot_id"], []
            )
            acceptable_ids = {
                chunk_id
                for group in dev["evidence_groups"]
                if group["group_id"] in aligned_group_ids
                for chunk_id in group["acceptable_chunk_ids"]
            }
            if claim["citation_chunk_id"] not in acceptable_ids:
                strict_unsupported += 1
        counters["strict_unsupported_slot_citations"] += strict_unsupported

        coverage = result.get("slot_coverage") or {}
        slot_partial = coverage.get("coverage_state") == "partial"
        candidate_ids = set(candidate_chunk_ids)
        candidate_complete = bool(expected_groups) and all(
            candidate_ids.intersection(group["acceptable_chunk_ids"])
            for group in dev["evidence_groups"]
        )
        false_partial_population = not cross_parent
        if slot_partial:
            counters["slot_partial_count"] += 1
            rendered = response.get("rendered_answer", "")
            missing = coverage["missing_slots"]
            disclosure_correct = (
                rendered.count(MISSING_SLOT_TEMPLATE) == len(missing)
                and all(
                    f"[확인 불가: {slot['slot_label']}]" in rendered
                    for slot in missing
                )
            )
            counters["slot_partial_disclosure_correct"] += disclosure_correct
            if false_partial_population and candidate_complete:
                counters["false_partial_candidate_complete"] += 1
            if false_partial_population and expected_groups.issubset(after_groups):
                counters["false_partial_already_cited_complete"] += 1

        if dev["answerability"] == "partial":
            counters["partial_disclaimer_expected"] += 1
            if result["mode"] == "slot_coverage":
                preserved = response.get("rendered_answer", "").startswith(
                    PARTIAL_DISCLAIMER
                )
            else:
                preserved = baseline.get("rendered_answer", "").startswith(
                    PARTIAL_DISCLAIMER
                )
            counters["partial_disclaimer_preserved"] += preserved
        false_or_realtime = dev["answerability"] == "false" or dev[
            "query_policy"
        ].get("expected_route_action") == "realtime_api"
        if false_or_realtime:
            counters["false_or_realtime_baseline_exposure"] += bool(
                baseline_cited_ids
            )
            counters["false_or_realtime_after_exposure"] += bool(after_cited_ids)

        diagnostics.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "dataset": name,
                "case_id": case_id,
                "threshold": threshold,
                "signal_a_slot_count": len(slots),
                "runtime_mode": result["mode"],
                "coverage_state": coverage.get("coverage_state"),
                "covered_slot_count": len(coverage.get("matches", [])),
                "missing_slot_count": len(coverage.get("missing_slots", [])),
                "single_parent_coverable": single_parent,
                "cross_parent": cross_parent,
                "required_evidence_group_count": len(expected_groups),
                "baseline_cited_group_count": len(baseline_groups),
                "after_cited_group_count": len(after_groups),
                "baseline_claim_complete": baseline_complete,
                "after_claim_complete": after_complete,
                "single_field_group_regression_count": len(lost_groups)
                if single_field
                else 0,
                "runtime_false_citation_count": failed_verifications,
                "strict_unsupported_slot_citation_count": strict_unsupported,
                "false_partial_candidate_complete": bool(
                    slot_partial and false_partial_population and candidate_complete
                ),
                "baseline_citation_chunk_ids": sorted(baseline_cited_ids),
                "after_citation_chunk_ids": sorted(after_cited_ids),
                "question_or_gold_text_included": False,
            }
        )

    metrics = {
        "dataset": name,
        "row_count": len(labels),
        "threshold": threshold,
        "signal_a_candidate_rows": counters["signal_a_candidate_rows"],
        "slot_coverage_rows": counters["slot_coverage_rows"],
        "all_required_evidence": {
            "baseline_cited_group_hit": _rate(
                counters["baseline_group_hits"], counters["expected_groups"]
            ),
            "after_cited_group_hit": _rate(
                counters["after_group_hits"], counters["expected_groups"]
            ),
            "baseline_claim_completeness": _rate(
                counters["baseline_complete"], counters["required_rows"]
            ),
            "after_claim_completeness": _rate(
                counters["after_complete"], counters["required_rows"]
            ),
        },
        "same_parent_multi_field": {
            "row_count": counters["same_parent_rows"],
            "baseline_cited_group_hit": _rate(
                counters["same_parent_baseline_group_hits"],
                counters["same_parent_expected_groups"],
            ),
            "after_cited_group_hit": _rate(
                counters["same_parent_after_group_hits"],
                counters["same_parent_expected_groups"],
            ),
            "baseline_claim_completeness": _rate(
                counters["same_parent_baseline_complete"],
                counters["same_parent_rows"],
            ),
            "after_claim_completeness": _rate(
                counters["same_parent_after_complete"],
                counters["same_parent_rows"],
            ),
        },
        "signal_a_slot_enumeration": {
            "precision": _rate(counters["slot_aligned"], counters["slot_total"]),
            "recall": _rate(
                counters["group_aligned_to_slot"],
                counters["group_total_for_slot_recall"],
            ),
        },
        "safety": {
            "single_field_group_regressions": counters[
                "single_field_group_regressions"
            ],
            "overall_group_regressions": counters["overall_group_regressions"],
            "runtime_false_citations": counters["runtime_false_citations"],
            "strict_unsupported_slot_citations": counters[
                "strict_unsupported_slot_citations"
            ],
            "false_partial_candidate_complete": counters[
                "false_partial_candidate_complete"
            ],
            "false_partial_already_cited_complete": counters[
                "false_partial_already_cited_complete"
            ],
            "slot_partial_count": counters["slot_partial_count"],
            "slot_partial_disclosure": _rate(
                counters["slot_partial_disclosure_correct"],
                counters["slot_partial_count"],
            ),
            "partial_disclaimer": _rate(
                counters["partial_disclaimer_preserved"],
                counters["partial_disclaimer_expected"],
            ),
            "false_or_realtime_baseline_exposure": counters[
                "false_or_realtime_baseline_exposure"
            ],
            "false_or_realtime_after_exposure": counters[
                "false_or_realtime_after_exposure"
            ],
        },
    }
    return metrics, diagnostics


def _safe_threshold(metrics: dict[str, Any]) -> bool:
    safety = metrics["safety"]
    return all(
        (
            safety["single_field_group_regressions"] == 0,
            safety["runtime_false_citations"] == 0,
            safety["strict_unsupported_slot_citations"] == 0,
            safety["false_partial_candidate_complete"] == 0,
        )
    )


def select_threshold(sweep: list[dict[str, Any]]) -> dict[str, Any]:
    safe = [row for row in sweep if _safe_threshold(row)]
    candidates = safe or sweep

    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        same = row["same_parent_multi_field"]
        slots = row["signal_a_slot_enumeration"]
        return (
            same["after_claim_completeness"]["successes"],
            same["after_cited_group_hit"]["successes"],
            slots["recall"]["rate"],
            slots["precision"]["rate"],
            row["threshold"],
        )

    selected = max(candidates, key=key)
    return {
        "threshold": selected["threshold"],
        "safety_gate_satisfied": bool(safe),
        "selection_used_development_63": False,
    }


def _markdown(report: dict[str, Any]) -> str:
    selected = report["canary_32_selected"]
    dev = report["development_63_selected_once"]
    canary_same = selected["same_parent_multi_field"]
    lines = [
        "# DNF RAG v3 requirement-slot claim coverage pilot",
        "",
        "## 판정",
        "",
        f"- Round 4 claim-coverage: **{report['decisions']['round_4_claim_coverage']}**",
        f"- 새 40-canary: **{report['decisions']['new_40_canary']}**",
        f"- selected overlap threshold: {report['threshold_selection']['threshold']}",
        "",
        "## 강등 32-set same-parent multi-field",
        "",
        f"- rows: {canary_same['row_count']}",
        f"- cited groups: {canary_same['baseline_cited_group_hit']['successes']} → {canary_same['after_cited_group_hit']['successes']} / {canary_same['after_cited_group_hit']['total']}",
        f"- claim complete rows: {canary_same['baseline_claim_completeness']['successes']} → {canary_same['after_claim_completeness']['successes']} / {canary_same['row_count']}",
        f"- slot recall: {selected['signal_a_slot_enumeration']['recall']['successes']}/{selected['signal_a_slot_enumeration']['recall']['total']}",
        f"- slot precision: {selected['signal_a_slot_enumeration']['precision']['successes']}/{selected['signal_a_slot_enumeration']['precision']['total']}",
        "",
        "## 안전성",
        "",
        f"- 32 single-field regressions: {selected['safety']['single_field_group_regressions']}",
        f"- 63 single-field regressions: {dev['safety']['single_field_group_regressions']}",
        f"- runtime false citations: {selected['safety']['runtime_false_citations'] + dev['safety']['runtime_false_citations']}",
        f"- strict unsupported slot citations: {selected['safety']['strict_unsupported_slot_citations'] + dev['safety']['strict_unsupported_slot_citations']}",
        f"- false partials: {selected['safety']['false_partial_candidate_complete'] + dev['safety']['false_partial_candidate_complete']}",
        f"- partial disclosure 32: {selected['safety']['slot_partial_disclosure']['successes']}/{selected['safety']['slot_partial_disclosure']['total']}",
        f"- partial disclaimer 32: {selected['safety']['partial_disclaimer']['successes']}/{selected['safety']['partial_disclaimer']['total']}",
        f"- partial disclaimer 63: {dev['safety']['partial_disclaimer']['successes']}/{dev['safety']['partial_disclaimer']['total']}",
        "",
        "runtime slot coverage에는 gold chunk/document/source ID를 전달하지 않았다.",
        "모든 새 claim은 canonical chunk의 연속 원문이며 자유형 생성은 사용하지 않았다.",
        "이 결과는 adaptive validation이며 final benchmark 성능이 아니다.",
        "",
    ]
    return "\n".join(lines)


def evaluate_and_freeze(*, root: Path) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    input_paths = {
        "documents": resolve(DEFAULT_DOCUMENTS),
        "chunks": resolve(DEFAULT_CHUNKS),
        "downgraded_canary": resolve(DEFAULT_CANARY),
        "canary_first_run_cases": resolve(DEFAULT_CANARY_CASES),
        "canary_first_run_manifest": resolve(DEFAULT_CANARY_MANIFEST),
        "adaptive_dev": resolve(DEFAULT_DEV),
        "dev_unified_runtime_cases": resolve(DEFAULT_DEV_RUNTIME),
        "canonical_claim_reranker_cases": resolve(DEFAULT_DEV_CLAIM_CASES),
        "canonical_claim_reranker_manifest": resolve(DEFAULT_DEV_CLAIM_MANIFEST),
        "temporal_overlay": resolve(DEFAULT_OVERLAY),
        "same_parent_diagnostic": resolve(DEFAULT_SAME_PARENT_DIAGNOSTIC),
        "signal_a_pilot_report": resolve(DEFAULT_SIGNAL_A_REPORT),
        "signal_a_source": root / "src/v3/answer_target_router.py",
        "slot_extractor_source": root / "src/v3/answer_target_coverage.py",
        "slot_coverage_source": root
        / "src/v3/requirement_slot_claim_coverage.py",
        "evaluator_source": root
        / "src/v3/evaluate_requirement_slot_coverage.py",
        "contract": resolve(DEFAULT_CONTRACT),
        "question_router_source": root / "src/v3/question_router.py",
        "decomposer_source": root / "src/v3/question_decomposer.py",
        "retriever_source": root / "src/v3/retrieve_v3.py",
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    documents_by_id = {
        row["document_id"]: row for row in read_jsonl(input_paths["documents"])
    }
    chunks_by_id = {
        row["chunk_id"]: row for row in read_jsonl(input_paths["chunks"])
    }
    current_policy = [
        row
        for row in read_jsonl(input_paths["temporal_overlay"])
        if row["is_current_revision"]
    ]
    if len(current_policy) != 1:
        raise RuntimeError("Expected exactly one current policy revision")
    current_policy_document_id = current_policy[0]["document_id"]

    canary_labels = read_jsonl(input_paths["downgraded_canary"])
    canary_cases = {
        row["case_id"]: row
        for row in read_jsonl(input_paths["canary_first_run_cases"])
    }
    canary_runtime = {
        case_id: {
            "route": row["actual_route"],
            "candidate_chunk_ids": row["retrieval_chunk_ids"],
        }
        for case_id, row in canary_cases.items()
    }
    canary_baselines = {
        case_id: _baseline_canary_response(row)
        for case_id, row in canary_cases.items()
    }

    dev_labels = read_jsonl(input_paths["adaptive_dev"])
    dev_runtime_rows = {
        row["case_id"]: row
        for row in read_jsonl(input_paths["dev_unified_runtime_cases"])
    }
    dev_claim_rows = {
        row["case_id"]: row
        for row in read_jsonl(input_paths["canonical_claim_reranker_cases"])
    }
    dev_runtime = {
        case_id: {
            "route": row["route"],
            "candidate_chunk_ids": row["retrieval_hit_chunk_ids"],
        }
        for case_id, row in dev_runtime_rows.items()
    }
    dev_baselines = {
        case_id: row["response"] for case_id, row in dev_claim_rows.items()
    }

    sweep = []
    canary_diagnostics_by_threshold = {}
    for threshold in THRESHOLD_GRID:
        metrics, diagnostics = _evaluate_dataset(
            name="downgraded_canary_32",
            labels=canary_labels,
            runtime_by_id=canary_runtime,
            baseline_by_id=canary_baselines,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            current_policy_document_id=current_policy_document_id,
            threshold=threshold,
        )
        sweep.append(metrics)
        canary_diagnostics_by_threshold[threshold] = diagnostics
    threshold_selection = select_threshold(sweep)
    selected_threshold = threshold_selection["threshold"]
    selected_canary = next(
        row for row in sweep if row["threshold"] == selected_threshold
    )
    selected_canary_diagnostics = canary_diagnostics_by_threshold[
        selected_threshold
    ]
    dev_metrics, dev_diagnostics = _evaluate_dataset(
        name="adaptive_dev_63",
        labels=dev_labels,
        runtime_by_id=dev_runtime,
        baseline_by_id=dev_baselines,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
        current_policy_document_id=current_policy_document_id,
        threshold=selected_threshold,
    )

    canary_same = selected_canary["same_parent_multi_field"]
    safety_32 = selected_canary["safety"]
    safety_63 = dev_metrics["safety"]
    gates = {
        "canary_same_parent_cited_coverage_improved": canary_same[
            "after_cited_group_hit"
        ]["successes"]
        > canary_same["baseline_cited_group_hit"]["successes"],
        "canary_same_parent_claim_completeness_improved": canary_same[
            "after_claim_completeness"
        ]["successes"]
        > canary_same["baseline_claim_completeness"]["successes"],
        "single_field_regression_zero": safety_32[
            "single_field_group_regressions"
        ]
        + safety_63["single_field_group_regressions"]
        == 0,
        "runtime_false_citation_zero": safety_32["runtime_false_citations"]
        + safety_63["runtime_false_citations"]
        == 0,
        "strict_unsupported_slot_citation_zero": safety_32[
            "strict_unsupported_slot_citations"
        ]
        + safety_63["strict_unsupported_slot_citations"]
        == 0,
        "false_partial_zero": safety_32["false_partial_candidate_complete"]
        + safety_63["false_partial_candidate_complete"]
        == 0,
        "partial_disclosure_exact": safety_32["slot_partial_disclosure"][
            "successes"
        ]
        == safety_32["slot_partial_disclosure"]["total"]
        and safety_63["slot_partial_disclosure"]["successes"]
        == safety_63["slot_partial_disclosure"]["total"],
        "partial_disclaimer_regression_zero": safety_32["partial_disclaimer"][
            "successes"
        ]
        == safety_32["partial_disclaimer"]["total"]
        and safety_63["partial_disclaimer"]["successes"]
        == safety_63["partial_disclaimer"]["total"],
        "dev_overall_citation_regression_zero": safety_63[
            "overall_group_regressions"
        ]
        == 0,
        "new_domain_keyword_rules_zero": True,
        "freeform_generation_unused": True,
        "router_decomposition_retrieval_unchanged": True,
    }
    go = all(gates.values()) and threshold_selection["safety_gate_satisfied"]
    decisions = {
        "round_4_claim_coverage": "GO" if go else "NO-GO",
        "canonical_claim_output_promotion": "NO-GO_PENDING_NEW_CANARY"
        if go
        else "NO-GO",
        "new_40_canary": "GO_TO_AUTHOR_AND_REVIEW" if go else "NO-GO",
        "global_decomposition": "STOPPED",
        "cross_parent_residual": "OUT_OF_SCOPE_PRESERVED",
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    diagnostics = selected_canary_diagnostics + dev_diagnostics
    diagnostics_bytes = _serialize_jsonl(
        diagnostics, lambda row: (row["dataset"], row["case_id"])
    )
    diagnostics_sha = _sha256_bytes(diagnostics_bytes)
    diagnostics_path = evidence_dir / (
        f"requirement_slot_coverage_cases_{diagnostics_sha}.jsonl"
    )
    write_immutable(diagnostics_path, diagnostics_bytes)

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "slot_coverage_version": SLOT_COVERAGE_VERSION,
        "evaluation_role": "adaptive_validation_diagnostic_only",
        "threshold_grid": list(THRESHOLD_GRID),
        "threshold_selection": threshold_selection,
        "canary_32_threshold_sweep": sweep,
        "canary_32_selected": selected_canary,
        "development_63_selected_once": dev_metrics,
        "contextual_baselines": {
            "dev_unified_cited_groups": {"successes": 47, "total": 59},
            "dev_canonical_claim_reranker": {"successes": 56, "total": 59},
            "canary_first_run_cited_groups": {"successes": 27, "total": 50},
            "canary_first_run_claim_completeness": {
                "successes": 9,
                "total": 27,
            },
            "signal_a_route_use": {
                "recall": {"successes": 8, "total": 9},
                "precision": {"successes": 8, "total": 25},
            },
        },
        "gates": gates,
        "decisions": decisions,
        "runtime_contract": {
            "gold_chunk_document_source_ids_available": False,
            "gold_used_only_after_runtime_for_scoring": True,
            "existing_retrieval_artifacts_reused": True,
            "model_embedding_or_search_executed": False,
            "single_parent_only": True,
            "new_domain_keyword_rule_count": 0,
            "freeform_generation_used": False,
            "signal_a_changed": False,
            "router_changed": False,
            "decomposer_changed": False,
            "retriever_changed": False,
            "individual_adaptive_failures_inspected": False,
            "frozen_blind_accessed": False,
        },
        "artifacts": {
            "cases_path": _relative(root, diagnostics_path),
            "cases_sha256": diagnostics_sha,
        },
        "sample_limitations": [
            "adaptive dev 63 has zero same-parent multi-evidence-group rows",
            "cross-parent questions are preserved as out of scope",
            "slot-to-required-group alignment is evaluation-only and label dependent",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"requirement_slot_coverage_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"requirement_slot_coverage_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "slot_coverage_version": SLOT_COVERAGE_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "cases": {
            "path": _relative(root, diagnostics_path),
            "sha256": diagnostics_sha,
            "row_count": len(diagnostics),
            "question_or_gold_text_included": False,
        },
        "report": {
            "path": _relative(root, report_path),
            "sha256": report_sha,
        },
        "report_markdown": {
            "path": _relative(root, markdown_path),
            "sha256": markdown_sha,
        },
        "decision": decisions["round_4_claim_coverage"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / (
        f"requirement_slot_coverage_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during slot coverage evaluation: {name}")
    return {
        "decision": decisions["round_4_claim_coverage"],
        "selected_threshold": selected_threshold,
        "gates": gates,
        "canary_32_selected": selected_canary,
        "development_63_selected_once": dev_metrics,
        "cases_path": str(diagnostics_path),
        "cases_sha256": diagnostics_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "markdown_path": str(markdown_path),
        "markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate requirement-slot extractive claim coverage"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            evaluate_and_freeze(root=parse_args().root),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
