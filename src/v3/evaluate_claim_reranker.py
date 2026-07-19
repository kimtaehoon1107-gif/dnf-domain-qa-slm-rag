from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import tokenize_lexical
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.claim_aware_reranker import CLAIM_RERANKER_VERSION, rerank_evidence
from src.v3.run_unified_runtime import PARTIAL_DISCLAIMER


EVALUATION_SCHEMA_VERSION = "dnf_claim_reranker_evaluation_v3.1"
VERIFICATION_SCHEMA_VERSION = "dnf_reranked_claim_verification_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_claim_reranker_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_claim_reranker_report_v3.1"
EVALUATOR_VERSION = "dnf-claim-reranker-evaluator-v3.1.0"
BUILT_AT = "2026-07-19T18:00:00+09:00"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_BASELINE_CASES = Path(
    "data/v3/runtime/unified_runtime_cases_"
    "f28e2fbfb768c901dc4f1079f262252d645a74c7e4ee494180c2879e528f7789.jsonl"
)
DEFAULT_BASELINE_MANIFEST = Path(
    "data/v3/runtime/unified_runtime_manifest_"
    "7f9d747c65960db5985c2ddf07592e09f0f82053b41db2801ce117151ac032c3.json"
)
DEFAULT_BGE_SCORES = Path(
    "data/v3/evidence/evidence_reranker_scores_"
    "ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl"
)
DEFAULT_BGE_MANIFEST = Path(
    "data/v3/evidence/evidence_reranker_manifest_"
    "ad6b3f074d8f6edf848c0129d0ea3d8de1c9438aa3de98dde0bfac0fb7a2f26c.json"
)
DEFAULT_CONTRACT = Path("docs/v3/claim_aware_reranker.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _claim_id(case_id: str, chunk_id: str, claim_text: str) -> str:
    payload = f"{case_id}\n{chunk_id}\n{claim_text}".encode("utf-8")
    return f"reranked_claim_sha256_{hashlib.sha256(payload).hexdigest()}"


def verify_reranked_claim(
    claim: dict[str, Any],
    route: dict[str, Any],
    chunk: dict[str, Any],
    document: dict[str, Any],
    *,
    current_policy_document_id: str | None,
) -> dict[str, Any]:
    current = route["time_scope"] == "current"
    allowed_sources = set(route["source_ids"])
    allowed_kinds = set(route["source_kinds"])
    gates = {
        "citation_chunk_exact": claim["citation_chunk_id"] == chunk["chunk_id"],
        "citation_parent_exact": claim["citation_parent_document_id"]
        == chunk["parent_document_id"]
        == document["document_id"],
        "exact_canonical_quote": bool(claim["claim_text"])
        and claim["claim_text"] in chunk["display_text"],
        "source_policy": chunk["source_id"] in allowed_sources
        and (not allowed_kinds or chunk["source_kind"] in allowed_kinds)
        and document["source_id"] == chunk["source_id"]
        and document["source_kind"] == chunk["source_kind"],
        "temporal_policy": (not current)
        or (
            chunk["status"] in {"current", "upcoming"}
            and chunk["default_exposure"]
            and document["status"] in {"current", "upcoming"}
            and document["default_exposure"]
        ),
        "revision_exact": claim["revision_id"] == document["revision_id"],
        "current_policy_revision": not (
            current and document["source_id"] == "dnf_account_policy"
        )
        or document["document_id"] == current_policy_document_id,
    }
    return {
        "verification_schema_version": VERIFICATION_SCHEMA_VERSION,
        "gates": gates,
        "verified": all(gates.values()),
    }


def _gold_span_token_recall(claim_text: str, evidence_span: str) -> float:
    gold_tokens = set(tokenize_lexical(evidence_span))
    if not gold_tokens:
        return 0.0
    return len(gold_tokens & set(tokenize_lexical(claim_text))) / len(gold_tokens)


def _matched_groups(dev: dict[str, Any], chunk_ids: set[str]) -> list[str]:
    return sorted(
        group["group_id"]
        for group in dev["evidence_groups"]
        if chunk_ids.intersection(group["acceptable_chunk_ids"])
    )


def _candidate_from_merge(
    merged: dict[str, Any],
    chunk: dict[str, Any],
    model_score: float | None,
) -> dict[str, Any]:
    if merged["display_text"] != chunk["display_text"]:
        raise RuntimeError(f"Baseline merge text changed: {chunk['chunk_id']}")
    candidate = {
        "selected_rank": merged["best_selected_rank"],
        "retrieval_rank": min(
            attachment["retrieval_rank"] for attachment in merged["attachments"]
        ),
        "chunk_id": chunk["chunk_id"],
        "parent_document_id": chunk["parent_document_id"],
        "source_id": chunk["source_id"],
        "source_kind": chunk["source_kind"],
        "status": chunk["status"],
        "default_exposure": chunk["default_exposure"],
        "review_required": chunk["review_required"],
        "display_text": chunk["display_text"],
    }
    if model_score is not None:
        candidate["reranker_score"] = model_score
    return candidate


def _ranking_summary(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rerank_rank": row["rerank_rank"],
            "original_selected_rank": row["original_selected_rank"],
            "retrieval_rank": row["retrieval_rank"],
            "chunk_id": row["chunk_id"],
            "parent_document_id": row["parent_document_id"],
            "source_id": row["source_id"],
            "source_kind": row["source_kind"],
            "status": row["status"],
            "default_exposure": row["default_exposure"],
            "preferred_quote": row["preferred_quote"],
            "claim_relevance_score": row["claim_relevance_score"],
            "promotion_tier": row["promotion_tier"],
            "promotion_reason": row["promotion_reason"],
            "score_components": row["claim_relevance_components"],
        }
        for row in ranked
    ]


def _time_label(time_scope: str) -> str:
    return "현재 기준" if time_scope == "current" else f"{time_scope} 기준"


def _single_response(
    case_id: str,
    question: str,
    answerability: str,
    route: dict[str, Any],
    chosen: dict[str, Any],
    chunk: dict[str, Any],
    document: dict[str, Any],
    current_policy_document_id: str,
) -> dict[str, Any]:
    claim = {
        "claim_id": _claim_id(
            case_id, chosen["chunk_id"], chosen["preferred_quote"]
        ),
        "question": question,
        "claim_mode": "claim_aware_exact_extractive_quote",
        "claim_text": chosen["preferred_quote"],
        "citation_chunk_id": chosen["chunk_id"],
        "citation_parent_document_id": chosen["parent_document_id"],
        "source_id": chosen["source_id"],
        "source_kind": chosen["source_kind"],
        "revision_id": document["revision_id"],
        "status": chosen["status"],
        "default_exposure": chosen["default_exposure"],
        "time_scope": route["time_scope"],
    }
    verification = verify_reranked_claim(
        claim,
        route,
        chunk,
        document,
        current_policy_document_id=current_policy_document_id,
    )
    if not verification["verified"]:
        return {
            "runtime_status": "blocked_verification_failed",
            "response_type": "fail_closed",
            "rendered_answer": "",
            "citation_chunk_ids": [],
            "claims": [claim],
            "verification": verification,
        }
    rendered = (
        f"- [{_time_label(route['time_scope'])}] {claim['claim_text']} "
        f"[{claim['citation_chunk_id']}]"
    )
    if answerability == "partial":
        rendered = PARTIAL_DISCLAIMER + rendered
    return {
        "runtime_status": "success",
        "response_type": "partial_official_fact"
        if answerability == "partial"
        else "verified_reranked_extractive_answer",
        "rendered_answer": rendered,
        "citation_chunk_ids": [claim["citation_chunk_id"]],
        "claims": [claim],
        "verification": verification,
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    return "\n".join(
        [
            "# DNF RAG v3 claim-aware evidence reranker",
            "",
            "## 결과",
            "",
            f"- adaptive dev rows: {metrics['dev_rows']}",
            f"- baseline cited evidence groups: {metrics['baseline_cited_group_hits']}/{metrics['expected_evidence_groups']}",
            f"- reranked cited evidence groups: {metrics['reranked_cited_group_hits']}/{metrics['expected_evidence_groups']}",
            f"- strict improvements: {metrics['strict_improvements']}",
            f"- strict regressions: {metrics['strict_regressions']}",
            f"- moved top evidence: {metrics['moved_top_evidence']}",
            f"- verified claims: {metrics['verified_claims']}/{metrics['expected_evidence_groups']}",
            f"- policy violations: {metrics['policy_violations']}",
            "",
            "## 판정",
            "",
            *[f"- {name}: **{value}**" for name, value in report["decisions"].items()],
            "",
            "## 남은 strict mismatch",
            "",
            *[
                f"- {row['question']} ({', '.join(row['source_ids'])}): "
                f"{row['reason']}"
                for row in report["strict_mismatches"]
            ],
            "",
            "gold ID는 runtime reranker 입력에 사용하지 않았고 평가 후에만 대조했다.",
            "이 결과는 adaptive development replay이며 final blind 성능이 아니다.",
            "",
        ]
    )


def freeze_claim_reranker(
    *,
    root: Path,
    documents_path: Path | None = None,
    chunks_path: Path | None = None,
    dev_set_path: Path | None = None,
    overlay_path: Path | None = None,
    baseline_cases_path: Path | None = None,
    baseline_manifest_path: Path | None = None,
    bge_scores_path: Path | None = None,
    bge_manifest_path: Path | None = None,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()

    def resolve(path: Path | None, default: Path) -> Path:
        value = default if path is None else path
        return value if value.is_absolute() else root / value

    documents_path = resolve(documents_path, DEFAULT_DOCUMENTS)
    chunks_path = resolve(chunks_path, DEFAULT_CHUNKS)
    dev_set_path = resolve(dev_set_path, DEFAULT_DEV_SET)
    overlay_path = resolve(overlay_path, DEFAULT_OVERLAY)
    baseline_cases_path = resolve(baseline_cases_path, DEFAULT_BASELINE_CASES)
    baseline_manifest_path = resolve(
        baseline_manifest_path, DEFAULT_BASELINE_MANIFEST
    )
    bge_scores_path = resolve(bge_scores_path, DEFAULT_BGE_SCORES)
    bge_manifest_path = resolve(bge_manifest_path, DEFAULT_BGE_MANIFEST)
    contract_path = resolve(contract_path, DEFAULT_CONTRACT)
    input_paths = {
        "documents": documents_path,
        "chunks": chunks_path,
        "adaptive_retrieval_dev": dev_set_path,
        "temporal_overlay": overlay_path,
        "baseline_runtime_cases": baseline_cases_path,
        "baseline_runtime_manifest": baseline_manifest_path,
        "frozen_bge_scores": bge_scores_path,
        "frozen_bge_manifest": bge_manifest_path,
        "claim_reranker_source": root / "src/v3/claim_aware_reranker.py",
        "evaluator_source": root / "src/v3/evaluate_claim_reranker.py",
        "contract": contract_path,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}

    documents_by_id = {
        row["document_id"]: row for row in read_jsonl(documents_path)
    }
    chunks_by_id = {row["chunk_id"]: row for row in read_jsonl(chunks_path)}
    dev_by_id = {row["dev_id"]: row for row in read_jsonl(dev_set_path)}
    baseline_rows = read_jsonl(baseline_cases_path)
    bge_by_id = {
        row["dev_id"]: {
            candidate["chunk_id"]: candidate["reranker_score"]
            for candidate in row["candidates"]
        }
        for row in read_jsonl(bge_scores_path)
    }
    current_policy_rows = [
        row for row in read_jsonl(overlay_path) if row["is_current_revision"]
    ]
    if len(current_policy_rows) != 1:
        raise RuntimeError("Expected exactly one current account-policy revision")
    current_policy_document_id = current_policy_rows[0]["document_id"]

    output_rows = []
    expected_group_count = 0
    baseline_group_hits = 0
    reranked_group_hits = 0
    strict_improvements = 0
    strict_regressions = 0
    moved_top_evidence = 0
    verified_claims = 0
    false_route_evidence_exposures = 0
    partial_disclaimers = 0
    policy_violations = 0
    promotion_reasons: Counter[str] = Counter()
    group_recalls = []
    strict_mismatches = []

    for baseline in sorted(baseline_rows, key=lambda row: row["query_ordinal"]):
        case_id = baseline["case_id"]
        dev = dev_by_id[case_id]
        route = baseline["route"]
        action = route["route_action"]
        reranker_summary = None
        if action == "retrieve":
            model_scores = bge_by_id.get(case_id, {})
            candidates = []
            for merged in baseline["response"]["merge"]["merged_candidates"]:
                chunk = chunks_by_id[merged["chunk_id"]]
                candidates.append(
                    _candidate_from_merge(
                        merged, chunk, model_scores.get(chunk["chunk_id"])
                    )
                )
            ranked = rerank_evidence(dev["question"], candidates)
            chosen = ranked[0]
            moved_top_evidence += chosen["original_selected_rank"] != 1
            promotion_reasons[chosen["promotion_reason"]] += 1
            chunk = chunks_by_id[chosen["chunk_id"]]
            document = documents_by_id[chunk["parent_document_id"]]
            response = _single_response(
                case_id,
                dev["question"],
                dev["answerability"],
                route,
                chosen,
                chunk,
                document,
                current_policy_document_id,
            )
            reranker_summary = {
                "candidate_count": len(ranked),
                "ranked_candidates": _ranking_summary(ranked),
            }
            verification = response["verification"]
            verified_claims += bool(verification["verified"])
            policy_violations += sum(
                not value
                for name, value in verification["gates"].items()
                if name
                in {
                    "source_policy",
                    "temporal_policy",
                    "revision_exact",
                    "current_policy_revision",
                }
            )
        else:
            response = baseline["response"]
            verification = response.get("verification")
            if action == "decompose" and verification is not None:
                verified_claims += sum(
                    row["verified"] for row in verification["claim_results"]
                )

        cited_ids = set(response["citation_chunk_ids"])
        expected_ids = {group["group_id"] for group in dev["evidence_groups"]}
        baseline_matches = set(baseline["cited_evidence_group_ids"])
        reranked_matches = set(_matched_groups(dev, cited_ids))
        expected_group_count += len(expected_ids)
        baseline_group_hits += len(expected_ids & baseline_matches)
        reranked_group_hits += len(expected_ids & reranked_matches)
        strict_improvements += len((expected_ids & reranked_matches) - baseline_matches)
        strict_regressions += len((expected_ids & baseline_matches) - reranked_matches)
        if dev["answerability"] == "false" and cited_ids:
            false_route_evidence_exposures += 1
        if dev["answerability"] == "partial" and response[
            "rendered_answer"
        ].startswith(PARTIAL_DISCLAIMER):
            partial_disclaimers += 1

        claims = []
        if action == "retrieve":
            claims = response["claims"]
        elif response.get("answer_plan") is not None:
            claims = response["answer_plan"]["claims"]
        for group in dev["evidence_groups"]:
            matching_claims = [
                claim
                for claim in claims
                if claim["citation_chunk_id"] in group["acceptable_chunk_ids"]
            ]
            group_recalls.append(
                max(
                    (
                        _gold_span_token_recall(
                            claim["claim_text"], group["evidence_span"]
                        )
                        for claim in matching_claims
                    ),
                    default=0.0,
                )
            )
        missing = sorted(expected_ids - reranked_matches)
        if missing:
            retrieval_matches = set(baseline["retrieval_evidence_group_ids"])
            strict_mismatches.append(
                {
                    "case_id": case_id,
                    "question": dev["question"],
                    "source_ids": route["source_ids"],
                    "missing_group_ids": missing,
                    "chosen_chunk_ids": sorted(cited_ids),
                    "reason": "acceptable_chunk_not_in_routed_candidates"
                    if expected_ids - retrieval_matches
                    else "strict_annotation_mismatch_requires_review",
                }
            )
        output_rows.append(
            {
                "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                "evaluator_version": EVALUATOR_VERSION,
                "case_id": case_id,
                "query_ordinal": baseline["query_ordinal"],
                "question": dev["question"],
                "route": route,
                "baseline_citation_chunk_ids": baseline["response"][
                    "citation_chunk_ids"
                ],
                "reranker": reranker_summary,
                "response": response,
                "expected_evidence_group_ids": sorted(expected_ids),
                "baseline_cited_evidence_group_ids": sorted(baseline_matches),
                "reranked_cited_evidence_group_ids": sorted(reranked_matches),
                "evaluation_role": "adaptive_dev_not_final_benchmark",
            }
        )

    metrics = {
        "dev_rows": len(output_rows),
        "expected_evidence_groups": expected_group_count,
        "baseline_cited_group_hits": baseline_group_hits,
        "reranked_cited_group_hits": reranked_group_hits,
        "strict_improvements": strict_improvements,
        "strict_regressions": strict_regressions,
        "moved_top_evidence": moved_top_evidence,
        "promotion_reason_counts": dict(sorted(promotion_reasons.items())),
        "verified_claims": verified_claims,
        "false_route_evidence_exposures": false_route_evidence_exposures,
        "partial_disclaimers": partial_disclaimers,
        "policy_violations": policy_violations,
        "strict_mismatch_count": len(strict_mismatches),
        "minimum_gold_span_token_recall": round(min(group_recalls), 8),
        "mean_gold_span_token_recall": round(
            sum(group_recalls) / len(group_recalls), 8
        ),
    }
    integration_gates = {
        "dev_rows_63": len(output_rows) == 63,
        "verified_claims_59": verified_claims == 59,
        "false_route_evidence_exposure_zero": false_route_evidence_exposures == 0,
        "partial_disclaimers_8": partial_disclaimers == 8,
        "policy_violations_zero": policy_violations == 0,
        "strict_regressions_zero": strict_regressions == 0,
        "strict_improvements_positive": strict_improvements > 0,
    }
    quality_gates = {
        "reranked_cited_groups_all_59": reranked_group_hits == expected_group_count,
        "strict_mismatch_zero": not strict_mismatches,
        "minimum_gold_span_token_recall_at_least_0_50": min(group_recalls) >= 0.50,
        "independent_holdout_measured": False,
    }
    integration_go = all(integration_gates.values())
    quality_go = all(quality_gates.values())
    decisions = {
        "claim_aware_reranker_adaptive": "GO" if integration_go else "NO-GO",
        "reranked_runtime_integration": "GO" if integration_go else "NO-GO",
        "strict_59_of_59_quality": "GO" if quality_go else "NO-GO",
        "production_evidence_selector": "NO-GO",
        "final_benchmark": "NO-GO",
    }

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    rows_bytes = _serialize_jsonl(output_rows, lambda row: row["query_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = evidence_dir / f"claim_reranker_cases_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "claim_reranker_version": CLAIM_RERANKER_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "built_at": BUILT_AT,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "runtime_contract": {
            "gold_available_to_reranker": False,
            "candidate_pool": "route_filtered_baseline_selected_evidence",
            "bge_override": "score_at_least_0.80_and_delta_at_least_0.30",
            "claim_mode": "exact_contiguous_canonical_chunk_quote",
        },
        "cases": {
            "path": _relative(root, rows_path),
            "sha256": rows_sha,
            "row_count": len(output_rows),
        },
        "metrics": metrics,
        "integration_gates": integration_gates,
        "quality_gates": quality_gates,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"claim_reranker_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "claim_reranker_version": CLAIM_RERANKER_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "metrics": metrics,
        "integration_gates": integration_gates,
        "quality_gates": quality_gates,
        "decisions": decisions,
        "strict_mismatches": strict_mismatches,
        "artifacts": {
            "cases_path": _relative(root, rows_path),
            "cases_sha256": rows_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "independent_reranker_holdout",
            "unreviewed_alternative_evidence_semantic_support",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"claim_reranker_runtime_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"claim_reranker_runtime_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during claim-reranker replay: {name}")
    return {
        "cases_path": str(rows_path),
        "cases_sha256": rows_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "metrics": metrics,
        "integration_gates": integration_gates,
        "quality_gates": quality_gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Evaluate the v3 claim-aware evidence reranker"
    )
    parser.add_argument("--root", type=Path, default=root)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = freeze_claim_reranker(root=parse_args().root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
