from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

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
from src.v3.generate_verified_answer import build_answer_plan, verify_answer_plan
from src.v3.question_router import (
    DEFAULT_AS_OF,
    build_source_entity_index,
    route_and_retrieve_with_embedding,
)
from src.v3.retrieve_decomposed import (
    infer_historical_month_window,
    merge_decomposed_evidence,
)
from src.v3.retrieve_v3 import load_runtime_artifacts
from src.v3.select_evidence import select_evidence


RUNTIME_SCHEMA_VERSION = "dnf_unified_runtime_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_unified_runtime_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_unified_runtime_report_v3.1"
RUNTIME_VERSION = "dnf-unified-adaptive-runtime-v3.1.0"
BUILT_AT = "2026-07-19T16:00:00+09:00"
TOP_K = 10
PARTIAL_DISCLAIMER = (
    "공식 문서에서 확인 가능한 사실만 제시합니다. 개인 계정에 가장 좋은 선택은 "
    "판단할 수 없습니다.\n"
)

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BM25_INDEX = Path(
    "data/v3/indexes/bm25_index_"
    "af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/bm25_manifest_"
    "f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_DENSE_MANIFEST = Path(
    "data/v3/indexes/dense_full_manifest_"
    "51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_QUERY_EMBEDDINGS = Path(
    "data/v3/retrieval/retrieval_dev_query_embeddings_"
    "323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32"
)
DEFAULT_ROUTER_CASES = Path(
    "data/v3/router/question_router_cases_"
    "caa3ff01684fbee3937ef4115c283398c3d4983fd1187680ff561a5438f894c9.jsonl"
)
DEFAULT_ROUTER_MANIFEST = Path(
    "data/v3/router/question_router_manifest_"
    "05db67ce7dea7779b40b679b861f082643644e11c2ec20c2de972d8b817d464a.json"
)
DEFAULT_DECOMPOSED_CASES = Path(
    "data/v3/decomposition/decomposed_hybrid_cases_"
    "3ee97cdf7a0ad0f7c124269ea9459a8ba2633d20d4572b11a333e86b5fd35c67.jsonl"
)
DEFAULT_DECOMPOSED_MANIFEST = Path(
    "data/v3/decomposition/decomposed_hybrid_manifest_"
    "d352cf2bcc21f89acfb7647e48ce91b1b1b0fd819ddb901e64b54713aed9e980.json"
)
DEFAULT_MULTI_ANSWERS = Path(
    "data/v3/generation/extractive_answer_cases_"
    "dca2d88deda9146058a0aaa77ef42fecd1616ed6f257eabbc18848127dacc199.jsonl"
)
DEFAULT_MULTI_ANSWER_MANIFEST = Path(
    "data/v3/generation/extractive_answer_manifest_"
    "99ab5c4249e3d86f4b531cf85869fcc6766679ab8928c9d657af2e07397ae784.json"
)
DEFAULT_CONTRACT = Path("docs/v3/unified_runtime.md")


ROUTE_CONTRACT_FIELDS = (
    "intent",
    "source_ids",
    "source_kinds",
    "time_scope",
    "temporal_as_of",
    "default_exposure_only",
    "allowed_statuses",
    "needs_decomposition",
    "needs_clarification",
    "route_action",
    "answerability",
    "answerability_reason",
)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def route_signature(route: dict[str, Any]) -> dict[str, Any]:
    """Return only fields that affect runtime behavior."""
    return {field: route.get(field) for field in ROUTE_CONTRACT_FIELDS}


def _single_subquestion(dev: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    payload = f"{dev['dev_id']}\n{dev['question']}".encode("utf-8")
    return {
        "subquestion_id": f"subquestion_sha256_{hashlib.sha256(payload).hexdigest()}",
        "ordinal": 1,
        "question": dev["question"],
        "relationship": "single_fact",
        "time_hint": route["time_scope"],
        "source_hint": route["source_ids"][0] if len(route["source_ids"]) == 1 else None,
    }


def _build_single_retrieval_case(
    dev: dict[str, Any],
    routed: dict[str, Any],
    selected: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    route = routed["route"]
    temporal_window = infer_historical_month_window(
        dev["question"], route["time_scope"]
    )
    child = {
        "subquestion": _single_subquestion(dev, route),
        "route": route,
        "temporal_resolution": routed.get("temporal_resolution"),
        "temporal_window": list(temporal_window) if temporal_window else None,
        "hits": routed.get("hits", []),
        "selected_evidence": selected,
    }
    return {
        "case_id": dev["dev_id"],
        "parent_question": dev["question"],
        "children": [child],
        "merge": merge_decomposed_evidence(
            dev["dev_id"], [child], documents_by_id
        ),
    }


def build_single_runtime_response(
    dev: dict[str, Any],
    routed: dict[str, Any],
    selected: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    retrieval_case = _build_single_retrieval_case(
        dev, routed, selected, documents_by_id
    )
    if retrieval_case["merge"]["merge_status"].startswith("blocked_"):
        return {
            "runtime_status": "blocked_no_verified_evidence",
            "response_type": "fail_closed",
            "rendered_answer": "",
            "citation_chunk_ids": [],
            "answer_plan": None,
            "verification": None,
            "merge": retrieval_case["merge"],
        }

    plan = build_answer_plan(retrieval_case, documents_by_id)
    verification = verify_answer_plan(plan, retrieval_case, documents_by_id)
    if not verification["verified"]:
        return {
            "runtime_status": "blocked_verification_failed",
            "response_type": "fail_closed",
            "rendered_answer": "",
            "citation_chunk_ids": [],
            "answer_plan": plan,
            "verification": verification,
            "merge": retrieval_case["merge"],
        }

    partial = routed["route"]["answerability"] == "partial"
    rendered = plan["rendered_answer"]
    if partial:
        rendered = PARTIAL_DISCLAIMER + rendered
    return {
        "runtime_status": "success",
        "response_type": (
            "partial_official_fact" if partial else "verified_extractive_answer"
        ),
        "rendered_answer": rendered,
        "citation_chunk_ids": [
            claim["citation_chunk_id"] for claim in plan["claims"]
        ],
        "answer_plan": plan,
        "verification": verification,
        "merge": retrieval_case["merge"],
    }


def build_abstention_response(
    dev: dict[str, Any], route: dict[str, Any]
) -> dict[str, Any]:
    del dev
    action = route["route_action"]
    if action == "realtime_api":
        response_type = "realtime_required"
        message = "현재 상태는 정적 공식 문서가 아니라 실시간 API 확인이 필요합니다."
    elif action == "clarify":
        response_type = "clarification_required"
        message = "공식 근거 범위를 정하려면 질문을 더 구체화해야 합니다."
    else:
        response_type = "rejected"
        message = "공식 문서 코퍼스로 근거 있는 답변을 제공할 수 없습니다."
    return {
        "runtime_status": "abstained",
        "response_type": response_type,
        "rendered_answer": message,
        "citation_chunk_ids": [],
        "answer_plan": None,
        "verification": None,
        "merge": None,
    }


def _gold_span_token_recall(claim_text: str, evidence_span: str) -> float:
    gold_tokens = set(tokenize_lexical(evidence_span))
    if not gold_tokens:
        return 0.0
    return len(gold_tokens & set(tokenize_lexical(claim_text))) / len(gold_tokens)


def _matched_group_ids(
    dev: dict[str, Any], chunk_ids: set[str]
) -> list[str]:
    return sorted(
        group["group_id"]
        for group in dev["evidence_groups"]
        if chunk_ids.intersection(group["acceptable_chunk_ids"])
    )


def _multi_response(answer_case: dict[str, Any]) -> dict[str, Any]:
    plan = answer_case["answer_plan"]
    verification = answer_case["verification"]
    if not verification["verified"]:
        return {
            "runtime_status": "blocked_verification_failed",
            "response_type": "fail_closed",
            "rendered_answer": "",
            "citation_chunk_ids": [],
            "answer_plan": plan,
            "verification": verification,
            "merge": None,
        }
    return {
        "runtime_status": "success",
        "response_type": "verified_decomposed_answer",
        "rendered_answer": plan["rendered_answer"],
        "citation_chunk_ids": [
            claim["citation_chunk_id"] for claim in plan["claims"]
        ],
        "answer_plan": plan,
        "verification": verification,
        "merge": None,
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    failures = report["failures"]
    return "\n".join(
        [
            "# DNF RAG v3 unified adaptive runtime",
            "",
            "## 실행 결과",
            "",
            f"- adaptive dev rows: {metrics['dev_rows']}",
            f"- route actions: {metrics['route_action_counts']}",
            f"- successful verified responses: {metrics['successful_verified_responses']}/{metrics['answerable_rows']}",
            f"- verified claims: {metrics['verified_claims']}/{metrics['expected_evidence_groups']}",
            f"- retrieval evidence groups: {metrics['retrieval_evidence_group_hits']}/{metrics['expected_evidence_groups']}",
            f"- selected evidence groups: {metrics['selected_evidence_group_hits']}/{metrics['expected_evidence_groups']}",
            f"- cited evidence groups: {metrics['cited_evidence_group_hits']}/{metrics['expected_evidence_groups']}",
            f"- minimum gold-span token recall: {metrics['minimum_gold_span_token_recall']:.4f}",
            f"- false-route evidence exposures: {metrics['false_route_evidence_exposures']}",
            f"- policy violations: {metrics['policy_violations']}",
            "",
            "## 판정",
            "",
            *[f"- {name}: **{value}**" for name, value in report["decisions"].items()],
            "",
            "## 엄격 게이트 실패",
            "",
            *(
                [
                    f"- {row['question']} ({', '.join(row['source_ids'])}): "
                    f"{', '.join(row['reasons'])}"
                    for row in failures
                ]
                if failures
                else ["- 없음"]
            ),
            "",
            "이 결과는 adaptive development replay이며 final blind 성능이 아니다.",
            "",
        ]
    )


def freeze_unified_runtime(
    *,
    root: Path,
    artifact_root: Path | None = None,
    documents_path: Path | None = None,
    chunks_path: Path | None = None,
    bm25_index_path: Path | None = None,
    bm25_manifest_path: Path | None = None,
    dense_manifest_path: Path | None = None,
    overlay_path: Path | None = None,
    dev_set_path: Path | None = None,
    query_embeddings_path: Path | None = None,
    router_cases_path: Path | None = None,
    router_manifest_path: Path | None = None,
    decomposed_cases_path: Path | None = None,
    decomposed_manifest_path: Path | None = None,
    multi_answers_path: Path | None = None,
    multi_answer_manifest_path: Path | None = None,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    artifact_root = root if artifact_root is None else artifact_root.resolve()

    def resolve(path: Path | None, default: Path) -> Path:
        value = default if path is None else path
        return value if value.is_absolute() else root / value

    documents_path = resolve(documents_path, DEFAULT_DOCUMENTS)
    chunks_path = resolve(chunks_path, DEFAULT_CHUNKS)
    bm25_index_path = resolve(bm25_index_path, DEFAULT_BM25_INDEX)
    bm25_manifest_path = resolve(bm25_manifest_path, DEFAULT_BM25_MANIFEST)
    dense_manifest_path = resolve(dense_manifest_path, DEFAULT_DENSE_MANIFEST)
    overlay_path = resolve(overlay_path, DEFAULT_OVERLAY)
    dev_set_path = resolve(dev_set_path, DEFAULT_DEV_SET)
    query_embeddings_path = resolve(query_embeddings_path, DEFAULT_QUERY_EMBEDDINGS)
    router_cases_path = resolve(router_cases_path, DEFAULT_ROUTER_CASES)
    router_manifest_path = resolve(router_manifest_path, DEFAULT_ROUTER_MANIFEST)
    decomposed_cases_path = resolve(decomposed_cases_path, DEFAULT_DECOMPOSED_CASES)
    decomposed_manifest_path = resolve(
        decomposed_manifest_path, DEFAULT_DECOMPOSED_MANIFEST
    )
    multi_answers_path = resolve(multi_answers_path, DEFAULT_MULTI_ANSWERS)
    multi_answer_manifest_path = resolve(
        multi_answer_manifest_path, DEFAULT_MULTI_ANSWER_MANIFEST
    )
    contract_path = resolve(contract_path, DEFAULT_CONTRACT)

    source_paths = {
        "runtime_builder": root / "src/v3/run_unified_runtime.py",
        "question_router": root / "src/v3/question_router.py",
        "retriever": root / "src/v3/retrieve_v3.py",
        "selector": root / "src/v3/select_evidence.py",
        "decomposed_retriever": root / "src/v3/retrieve_decomposed.py",
        "generator_verifier": root / "src/v3/generate_verified_answer.py",
    }
    input_paths = {
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_index": bm25_index_path,
        "bm25_manifest": bm25_manifest_path,
        "dense_manifest": dense_manifest_path,
        "temporal_overlay": overlay_path,
        "adaptive_retrieval_dev": dev_set_path,
        "query_embeddings": query_embeddings_path,
        "router_cases": router_cases_path,
        "router_manifest": router_manifest_path,
        "decomposed_cases": decomposed_cases_path,
        "decomposed_manifest": decomposed_manifest_path,
        "multi_answers": multi_answers_path,
        "multi_answer_manifest": multi_answer_manifest_path,
        "contract": contract_path,
        **source_paths,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}

    documents = read_jsonl(documents_path)
    chunks = read_jsonl(chunks_path)
    overlay_rows = read_jsonl(overlay_path)
    dev_rows = read_jsonl(dev_set_path)
    router_by_id = {
        row["case_id"]: row for row in read_jsonl(router_cases_path)
    }
    decomposed_by_id = {
        row["case_id"]: row for row in read_jsonl(decomposed_cases_path)
    }
    multi_answer_by_id = {
        row["case_id"]: row for row in read_jsonl(multi_answers_path)
    }
    artifacts = load_runtime_artifacts(
        root,
        bm25_manifest_path=bm25_manifest_path,
        dense_manifest_path=dense_manifest_path,
        chunks_path=chunks_path,
        documents_path=documents_path,
    )
    embeddings = np.fromfile(query_embeddings_path, dtype="<f4")
    dimension = artifacts.dense_embeddings.shape[1]
    if embeddings.size != len(dev_rows) * dimension:
        raise RuntimeError("Frozen query embeddings have invalid size")
    embeddings = embeddings.reshape(len(dev_rows), dimension)
    source_entity_index = build_source_entity_index(documents, chunks)

    rows = []
    route_action_counts: Counter[str] = Counter()
    answerability_exact = 0
    route_exact = 0
    successful_verified_responses = 0
    verified_plans = 0
    verified_claims = 0
    expected_groups = 0
    retrieval_group_hits = 0
    selected_group_hits = 0
    cited_group_hits = 0
    false_route_evidence_exposures = 0
    partial_disclaimers = 0
    policy_violations = 0
    claim_group_specificity_errors = 0
    group_recalls = []
    failures = []
    citation_failures_by_source: Counter[str] = Counter()
    retrieval_failure_count = 0
    top_claim_selection_failure_count = 0

    for ordinal, (dev, embedding) in enumerate(zip(dev_rows, embeddings, strict=True)):
        case_id = dev["dev_id"]
        canonical_router = router_by_id.get(case_id)
        if canonical_router is None or canonical_router["query_ordinal"] != ordinal:
            raise RuntimeError(f"Router case ordering mismatch: {case_id}")
        routed = route_and_retrieve_with_embedding(
            dev["question"],
            embedding,
            artifacts,
            overlay_rows,
            top_k=TOP_K,
            current_as_of=DEFAULT_AS_OF,
            source_entity_index=source_entity_index,
        )
        route = routed["route"]
        action = route["route_action"]
        route_action_counts[action] += 1
        is_route_exact = route_signature(route) == route_signature(
            canonical_router["route"]
        )
        route_exact += is_route_exact
        is_answerability_exact = route["answerability"] == dev["answerability"]
        answerability_exact += is_answerability_exact

        retrieval_ids = {row["chunk_id"] for row in routed["hits"]}
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        if action == "retrieve":
            selected = select_evidence(
                dev["question"], routed["hits"], artifacts.chunks_by_id
            )
            selected_ids = {row["chunk_id"] for row in selected}
            response = build_single_runtime_response(
                dev, routed, selected, artifacts.documents_by_id
            )
            policy_violations += len(response["merge"]["policy_violations"])
        elif action == "decompose":
            decomposed = decomposed_by_id.get(case_id)
            answer_case = multi_answer_by_id.get(case_id)
            if decomposed is None or answer_case is None:
                raise RuntimeError(f"Missing frozen decomposition: {case_id}")
            retrieval_ids = {
                chunk_id
                for child in decomposed["children"]
                for chunk_id in child["hybrid_hit_chunk_ids"]
            }
            selected_ids = {
                row["chunk_id"]
                for child in decomposed["children"]
                for row in child["selected_evidence"]
            }
            policy_violations += len(decomposed["merge"]["policy_violations"])
            response = _multi_response(answer_case)
        else:
            response = build_abstention_response(dev, route)

        cited_ids = set(response["citation_chunk_ids"])
        if response["runtime_status"] == "success":
            successful_verified_responses += 1
        verification = response["verification"]
        if verification is not None:
            verified_plans += bool(verification["verified"])
            verified_claims += sum(
                bool(row["verified"]) for row in verification["claim_results"]
            )
        if dev["answerability"] == "partial" and response[
            "rendered_answer"
        ].startswith(PARTIAL_DISCLAIMER):
            partial_disclaimers += 1
        if dev["answerability"] == "false" and (
            retrieval_ids or selected_ids or cited_ids
        ):
            false_route_evidence_exposures += 1

        expected_ids = {group["group_id"] for group in dev["evidence_groups"]}
        retrieval_matches = set(_matched_group_ids(dev, retrieval_ids))
        selected_matches = set(_matched_group_ids(dev, selected_ids))
        cited_matches = set(_matched_group_ids(dev, cited_ids))
        expected_groups += len(expected_ids)
        retrieval_group_hits += len(expected_ids & retrieval_matches)
        selected_group_hits += len(expected_ids & selected_matches)
        cited_group_hits += len(expected_ids & cited_matches)
        if expected_ids - retrieval_matches:
            retrieval_failure_count += 1
        if expected_ids.issubset(selected_matches) and expected_ids - cited_matches:
            top_claim_selection_failure_count += 1
        if expected_ids - cited_matches:
            for source_id in route["source_ids"]:
                citation_failures_by_source[source_id] += 1

        claims = (
            response["answer_plan"]["claims"]
            if response["answer_plan"] is not None
            else []
        )
        claim_audit = []
        for claim in claims:
            matches = [
                group
                for group in dev["evidence_groups"]
                if claim["citation_chunk_id"] in group["acceptable_chunk_ids"]
            ]
            claim_group_specificity_errors += len(matches) != 1
            claim_audit.append(
                {
                    "claim_id": claim["claim_id"],
                    "matched_evidence_group_ids": sorted(
                        group["group_id"] for group in matches
                    ),
                    "gold_span_token_recall": round(
                        max(
                            (
                                _gold_span_token_recall(
                                    claim["claim_text"], group["evidence_span"]
                                )
                                for group in matches
                            ),
                            default=0.0,
                        ),
                        8,
                    ),
                }
            )
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

        reasons = []
        if not is_route_exact:
            reasons.append("route_contract_mismatch")
        if not is_answerability_exact:
            reasons.append("answerability_mismatch")
        for name, matches in (
            ("retrieval", retrieval_matches),
            ("selected", selected_matches),
            ("cited", cited_matches),
        ):
            missing = sorted(expected_ids - matches)
            if missing:
                reasons.append(f"missing_{name}:{','.join(missing)}")
        if dev["answerability"] != "false" and response["runtime_status"] != "success":
            reasons.append(response["runtime_status"])
        if reasons:
            failures.append(
                {
                    "case_id": case_id,
                    "question": dev["question"],
                    "source_ids": route["source_ids"],
                    "reasons": reasons,
                }
            )

        rows.append(
            {
                "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
                "runtime_version": RUNTIME_VERSION,
                "case_id": case_id,
                "query_ordinal": ordinal,
                "question": dev["question"],
                "expected_answerability": dev["answerability"],
                "route": route,
                "route_contract_exact": is_route_exact,
                "answerability_exact": is_answerability_exact,
                "retrieval_hit_chunk_ids": sorted(retrieval_ids),
                "selected_chunk_ids": sorted(selected_ids),
                "response": response,
                "expected_evidence_group_ids": sorted(expected_ids),
                "retrieval_evidence_group_ids": sorted(retrieval_matches),
                "selected_evidence_group_ids": sorted(selected_matches),
                "cited_evidence_group_ids": sorted(cited_matches),
                "claim_audit": claim_audit,
                "evaluation_role": "adaptive_dev_not_final_benchmark",
            }
        )

    metrics = {
        "dev_rows": len(rows),
        "answerable_rows": sum(
            row["answerability"] != "false" for row in dev_rows
        ),
        "route_action_counts": dict(sorted(route_action_counts.items())),
        "route_contract_exact": route_exact,
        "answerability_exact": answerability_exact,
        "successful_verified_responses": successful_verified_responses,
        "verified_plans": verified_plans,
        "verified_claims": verified_claims,
        "expected_evidence_groups": expected_groups,
        "retrieval_evidence_group_hits": retrieval_group_hits,
        "selected_evidence_group_hits": selected_group_hits,
        "cited_evidence_group_hits": cited_group_hits,
        "claim_group_specificity_errors": claim_group_specificity_errors,
        "retrieval_failure_count": retrieval_failure_count,
        "top_claim_selection_failure_count": top_claim_selection_failure_count,
        "citation_failures_by_source": dict(
            sorted(citation_failures_by_source.items())
        ),
        "minimum_gold_span_token_recall": round(min(group_recalls), 8),
        "mean_gold_span_token_recall": round(
            sum(group_recalls) / len(group_recalls), 8
        ),
        "false_route_evidence_exposures": false_route_evidence_exposures,
        "partial_disclaimers": partial_disclaimers,
        "policy_violations": policy_violations,
    }
    integration_gates = {
        "dev_rows_63": len(rows) == 63,
        "route_contract_exact_63": route_exact == 63,
        "answerability_exact_63": answerability_exact == 63,
        "route_actions_expected": dict(route_action_counts)
        == {"retrieve": 51, "decompose": 4, "reject": 6, "realtime_api": 2},
        "verified_responses_55": successful_verified_responses == 55,
        "verified_plans_55": verified_plans == 55,
        "verified_claims_59": verified_claims == 59,
        "partial_disclaimers_8": partial_disclaimers == 8,
        "false_route_evidence_exposure_zero": false_route_evidence_exposures == 0,
        "policy_violations_zero": policy_violations == 0,
    }
    quality_gates = {
        "retrieval_evidence_groups_all_59": retrieval_group_hits == 59,
        "selected_evidence_groups_all_59": selected_group_hits == 59,
        "cited_evidence_groups_all_59": cited_group_hits == 59,
        "claim_matches_exactly_one_group": claim_group_specificity_errors == 0,
        "minimum_gold_span_token_recall_at_least_0_50": min(group_recalls) >= 0.50,
    }
    integration_go = all(integration_gates.values())
    quality_go = all(quality_gates.values())
    decisions = {
        "unified_runtime_integration": "GO" if integration_go else "NO-GO",
        "adaptive_end_to_end_quality": "GO" if quality_go else "NO-GO",
        "extractive_runtime_baseline_promotion": (
            "GO" if integration_go and quality_go else "NO-GO"
        ),
        "natural_language_generator": "NO-GO",
        "production_nli_verifier": "NO-GO",
        "final_benchmark": "NO-GO",
    }

    runtime_dir = artifact_root / "data/v3/runtime"
    reports_dir = artifact_root / "reports/v3"
    rows_bytes = _serialize_jsonl(rows, lambda row: row["query_ordinal"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = runtime_dir / f"unified_runtime_cases_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "built_at": BUILT_AT,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "runtime_contract": {
            "top_k": TOP_K,
            "current_as_of": DEFAULT_AS_OF,
            "single_mode": "route_retrieve_select_exact_quote_verify",
            "multi_mode": "frozen_decomposition_exact_quote_verify",
            "unsupported_mode": "zero_evidence_abstention",
            "gold_available_to_runtime": False,
        },
        "cases": {
            "path": _relative(artifact_root, rows_path),
            "sha256": rows_sha,
            "row_count": len(rows),
        },
        "metrics": metrics,
        "integration_gates": integration_gates,
        "quality_gates": quality_gates,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = runtime_dir / f"unified_runtime_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "metrics": metrics,
        "integration_gates": integration_gates,
        "quality_gates": quality_gates,
        "decisions": decisions,
        "failures": failures,
        "artifacts": {
            "cases_path": _relative(artifact_root, rows_path),
            "cases_sha256": rows_sha,
            "manifest_path": _relative(artifact_root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "natural_language_generation_quality",
            "natural_contradiction_verifier_performance",
            "independent_holdout",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"unified_runtime_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"unified_runtime_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during runtime replay: {name}")
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
        description="Replay the unified DNF v3 adaptive runtime"
    )
    parser.add_argument("--root", type=Path, default=root)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = freeze_unified_runtime(root=parse_args().root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
