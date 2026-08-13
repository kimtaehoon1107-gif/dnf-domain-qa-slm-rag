from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import tokenize_lexical
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.retrieve_decomposed import document_overlaps_window


ANSWER_PLAN_SCHEMA_VERSION = "dnf_answer_plan_v3.1"
VERIFICATION_SCHEMA_VERSION = "dnf_claim_verification_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_extractive_generator_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_extractive_generator_report_v3.1"
GENERATOR_VERSION = "dnf-schema-extractive-generator-v3.1.0"
VERIFIER_VERSION = "dnf-deterministic-claim-verifier-v3.1.0"
BUILT_AT = "2026-07-19T13:00:00+09:00"
MAX_QUOTE_CHARS = 700
MAX_SEGMENT_WINDOW = 3
MIN_GOLD_SPAN_TOKEN_RECALL = 0.50

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_DECOMPOSED_CASES = Path(
    "data/v3/decomposition/"
    "decomposed_hybrid_cases_"
    "3ee97cdf7a0ad0f7c124269ea9459a8ba2633d20d4572b11a333e86b5fd35c67.jsonl"
)
DEFAULT_DECOMPOSED_MANIFEST = Path(
    "data/v3/decomposition/"
    "decomposed_hybrid_manifest_"
    "d352cf2bcc21f89acfb7647e48ce91b1b1b0fd819ddb901e64b54713aed9e980.json"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/generate_verified_answer.py")
DEFAULT_RETRIEVAL_SOURCE = Path("src/v3/retrieve_decomposed.py")
DEFAULT_SELECTOR_SOURCE = Path("src/v3/select_evidence.py")
DEFAULT_CONTRACT = Path("docs/v3/extractive_generator_verifier.md")

GENERIC_QUERY_TOKENS = {
    "faq",
    "기준으로",
    "알려줘",
    "정리해줘",
    "언제",
    "대한",
    "무엇인가요",
    "무엇이야",
    "운영정책",
    "이달의",
    "세리아",
    "상점",
}
DATE_SIGNAL = re.compile(
    r"(?:20\d{2}년\s*\d{1,2}월|\d{1,2}월\s*\d{1,2}일|\d{1,3}일|\d{1,3}회|\d{1,2}:\d{2})"
)
TIME_QUERY_MARKERS = ("언제", "기간", "기한", "종료", "삭제", "보관")
TIME_EVIDENCE_MARKERS = ("기간", "기한", "종료", "삭제", "보유", "일괄", "점검")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _segments(text: str) -> list[tuple[int, int]]:
    spans = []
    for line in re.finditer(r"[^\n|]+", text):
        for sentence in re.finditer(r"[^.!?]+(?:[.!?]+|$)", line.group(0)):
            start = line.start() + sentence.start()
            end = line.start() + sentence.end()
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            if end - start >= 4:
                spans.append((start, end))
    if not spans and text.strip():
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        spans.append((start, end))
    return spans


def _quote_score(question: str, quote: str) -> tuple[int, int, int, int, int]:
    query_tokens = {
        token
        for token in tokenize_lexical(question)
        if token not in GENERIC_QUERY_TOKENS
    }
    quote_tokens = set(tokenize_lexical(quote))
    overlap = len(query_tokens & quote_tokens)
    numeric_overlap = len(
        {
            token
            for token in query_tokens & quote_tokens
            if any(character.isdigit() for character in token)
        }
    )
    time_question = any(marker in question for marker in TIME_QUERY_MARKERS)
    date_signal = bool(DATE_SIGNAL.search(quote)) if time_question else False
    intent_score = 0
    if "삭제" in question:
        intent_score += 40 if "삭제" in quote else 0
        intent_score += 10 if date_signal else 0
    elif "판매" in question and "종료" in question:
        intent_score += 45 if "부터" in quote and "까지" in quote else 0
        intent_score += 35 if "판매기간" in quote else 0
        intent_score += 20 if "점검 전" in quote else 0
        intent_score += 10 if date_signal else 0
    elif "진행" in question and "종료" in question:
        intent_score += 40 if "기간" in quote or "~" in quote else 0
        intent_score += 20 if "점검 전" in quote else 0
        intent_score += 10 if date_signal else 0
    elif "기한" in question or "보관기간" in question:
        intent_score += (
            40
            if any(marker in quote for marker in ("이내", "보유", "기간"))
            else 0
        )
        intent_score += 10 if date_signal else 0
    if "복구" in question and "불가능" in question and "손실" in question:
        intent_score += (
            40
            if "손실" in quote
            and ("불가능" in quote or "가능하지" in quote)
            else 0
        )
        intent_score += (
            30
            if "손실은 복구가 불가능" in quote
            or "손실은 복구가 가능하지" in quote
            else 0
        )
    if "아이템" in question:
        intent_score += 20 if "아이템" in quote else 0
        intent_score -= (
            20 if "엠블렘" in quote and "엠블렘" not in question else 0
        )
    complete_sentence = quote.rstrip().endswith((".", "!", "?"))
    if intent_score:
        return (
            intent_score,
            int(complete_sentence),
            -len(quote),
            numeric_overlap,
            overlap,
        )
    return (0, numeric_overlap, overlap, int(complete_sentence), -len(quote))


def extract_relevant_quote(question: str, evidence_text: str) -> str:
    if not question.strip():
        raise RuntimeError("question must not be empty")
    if not evidence_text.strip():
        raise RuntimeError("evidence_text must not be empty")
    spans = _segments(evidence_text)
    candidates = []
    for start_index, (start, _) in enumerate(spans):
        for width in range(1, MAX_SEGMENT_WINDOW + 1):
            end_index = start_index + width - 1
            if end_index >= len(spans):
                break
            end = spans[end_index][1]
            quote = evidence_text[start:end].strip(" \t\r\n|")
            if not quote or len(quote) > MAX_QUOTE_CHARS:
                continue
            candidates.append((_quote_score(question, quote), start, end, quote))
    if not candidates:
        raise RuntimeError("No bounded exact quote candidate")
    candidates.sort(key=lambda row: (row[0], -row[1], -row[2]), reverse=True)
    quote = candidates[0][3]
    if quote not in evidence_text:
        raise RuntimeError("Extractive quote lost source offset")
    return quote


def _claim_id(
    parent_id: str, subquestion_id: str, chunk_id: str, claim_text: str
) -> str:
    payload = f"{parent_id}\n{subquestion_id}\n{chunk_id}\n{claim_text}".encode(
        "utf-8"
    )
    return f"claim_sha256_{hashlib.sha256(payload).hexdigest()}"


def _time_label(child: dict[str, Any]) -> str:
    time_scope = child["route"]["time_scope"]
    if time_scope == "current":
        return "현재 기준"
    if child.get("temporal_window"):
        start, end = child["temporal_window"]
        return f"{start}~{end} 기준"
    if time_scope == "comparison":
        return "변경 전후 비교"
    return f"{time_scope} 기준"


def build_answer_plan(
    retrieval_case: dict[str, Any],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merge_status = retrieval_case["merge"]["merge_status"]
    if merge_status.startswith("blocked_"):
        raise RuntimeError(f"Cannot generate from blocked merge: {merge_status}")
    merged_chunk_ids = {
        row["chunk_id"] for row in retrieval_case["merge"]["merged_candidates"]
    }
    claims = []
    for child in sorted(
        retrieval_case["children"],
        key=lambda row: row["subquestion"]["ordinal"],
    ):
        selected = sorted(
            child["selected_evidence"],
            key=lambda row: (row["selected_rank"], row["chunk_id"]),
        )
        if not selected:
            raise RuntimeError("Cannot generate without selected evidence")
        evidence = selected[0]
        if evidence["chunk_id"] not in merged_chunk_ids:
            raise RuntimeError("Top selected evidence is missing from merge packet")
        document = documents_by_id.get(evidence["parent_document_id"])
        if document is None:
            raise RuntimeError(
                f"Unknown generation document: {evidence['parent_document_id']}"
            )
        subquestion = child["subquestion"]
        claim_text = extract_relevant_quote(
            subquestion["question"], evidence["display_text"]
        )
        claim_id = _claim_id(
            retrieval_case["case_id"],
            subquestion["subquestion_id"],
            evidence["chunk_id"],
            claim_text,
        )
        claims.append(
            {
                "claim_id": claim_id,
                "subquestion_id": subquestion["subquestion_id"],
                "child_ordinal": subquestion["ordinal"],
                "question": subquestion["question"],
                "relationship": subquestion["relationship"],
                "time_scope": child["route"]["time_scope"],
                "time_label": _time_label(child),
                "claim_mode": "exact_extractive_quote",
                "claim_text": claim_text,
                "citation_chunk_id": evidence["chunk_id"],
                "citation_parent_document_id": evidence["parent_document_id"],
                "source_id": evidence["source_id"],
                "source_kind": evidence["source_kind"],
                "revision_id": document["revision_id"],
                "lineage_id": document["lineage_id"],
                "status": evidence["status"],
                "default_exposure": evidence["default_exposure"],
                "valid_from": document.get("valid_from"),
                "valid_to": document.get("valid_to"),
            }
        )
    rendered_answer = "\n".join(
        f"- [{claim['time_label']}] {claim['claim_text']} "
        f"[{claim['citation_chunk_id']}]"
        for claim in claims
    )
    plan_payload = {
        "answer_plan_schema_version": ANSWER_PLAN_SCHEMA_VERSION,
        "parent_id": retrieval_case["case_id"],
        "parent_question": retrieval_case["parent_question"],
        "answer_mode": "schema_constrained_extractive",
        "claims": claims,
        "rendered_answer": rendered_answer,
    }
    return {
        **plan_payload,
        "answer_plan_id": "answer_plan_sha256_"
        + _sha256_bytes(_canonical_json_bytes(plan_payload)),
    }


def _claim_id_valid(parent_id: str, claim: dict[str, Any]) -> bool:
    return claim["claim_id"] == _claim_id(
        parent_id,
        claim["subquestion_id"],
        claim["citation_chunk_id"],
        claim["claim_text"],
    )


def verify_answer_plan(
    plan: dict[str, Any],
    retrieval_case: dict[str, Any],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    child_by_id = {
        row["subquestion"]["subquestion_id"]: row
        for row in retrieval_case["children"]
    }
    expected_subquestions = set(child_by_id)
    actual_subquestions = {row["subquestion_id"] for row in plan["claims"]}
    claim_results = []
    for claim in plan["claims"]:
        child = child_by_id.get(claim["subquestion_id"])
        selected_by_chunk = (
            {
                row["chunk_id"]: row for row in child["selected_evidence"]
            }
            if child is not None
            else {}
        )
        evidence = selected_by_chunk.get(claim["citation_chunk_id"])
        document = documents_by_id.get(claim["citation_parent_document_id"])
        citation_selected = evidence is not None
        exact_quote = bool(
            evidence is not None and claim["claim_text"] in evidence["display_text"]
        )
        source_valid = bool(
            child is not None
            and evidence is not None
            and evidence["source_id"] in child["route"]["source_ids"]
            and (
                not child["route"]["source_kinds"]
                or evidence["source_kind"] in child["route"]["source_kinds"]
            )
            and claim["source_id"] == evidence["source_id"]
            and claim["source_kind"] == evidence["source_kind"]
        )
        temporal_valid = child is not None and evidence is not None
        if temporal_valid and child["route"]["time_scope"] == "current":
            temporal_valid = (
                evidence["status"] in {"current", "upcoming"}
                and evidence["default_exposure"]
                and document is not None
                and document["status"] in {"current", "upcoming"}
                and document["default_exposure"]
            )
        if temporal_valid and child.get("temporal_window"):
            temporal_valid = bool(
                document is not None
                and document_overlaps_window(
                    document, tuple(child["temporal_window"])
                )
            )
        temporal_resolution = child.get("temporal_resolution") if child else None
        revision_valid = bool(
            document is not None
            and claim["revision_id"] == document["revision_id"]
            and claim["lineage_id"] == document["lineage_id"]
        )
        if revision_valid and temporal_resolution is not None:
            revision_valid = (
                claim["citation_parent_document_id"]
                == temporal_resolution["selected_document_id"]
                and claim["revision_id"]
                == temporal_resolution["selected_revision_id"]
            )
        result = {
            "claim_id": claim["claim_id"],
            "subquestion_id": claim["subquestion_id"],
            "citation_selected": citation_selected,
            "exact_quote": exact_quote,
            "source_valid": source_valid,
            "temporal_valid": temporal_valid,
            "revision_valid": revision_valid,
            "claim_id_valid": _claim_id_valid(plan["parent_id"], claim),
            "rendered": claim["claim_text"] in plan["rendered_answer"]
            and f"[{claim['citation_chunk_id']}]" in plan["rendered_answer"],
        }
        result["verified"] = all(
            value
            for key, value in result.items()
            if key
            not in {
                "claim_id",
                "subquestion_id",
                "verified",
            }
        )
        claim_results.append(result)

    revision_pair_valid = True
    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for claim in plan["claims"]:
        by_lineage.setdefault(claim["lineage_id"], []).append(claim)
    for claims in by_lineage.values():
        revisions = {row["revision_id"] for row in claims}
        time_scopes = {row["time_scope"] for row in claims}
        if len(revisions) > 1 and not (
            "comparison" in time_scopes
            or {"current", "historical"}.issubset(time_scopes)
        ):
            revision_pair_valid = False

    gates = {
        "merge_input_unblocked": not retrieval_case["merge"][
            "merge_status"
        ].startswith("blocked_"),
        "claim_count_matches_children": len(plan["claims"])
        == len(retrieval_case["children"]),
        "subquestion_coverage_exact": actual_subquestions == expected_subquestions,
        "unique_claim_ids": len({row["claim_id"] for row in plan["claims"]})
        == len(plan["claims"]),
        "citations_selected": all(
            row["citation_selected"] for row in claim_results
        ),
        "claims_exact_quotes": all(row["exact_quote"] for row in claim_results),
        "source_policy_valid": all(row["source_valid"] for row in claim_results),
        "temporal_policy_valid": all(
            row["temporal_valid"] for row in claim_results
        ),
        "revision_policy_valid": revision_pair_valid
        and all(row["revision_valid"] for row in claim_results),
        "claim_ids_stable": all(row["claim_id_valid"] for row in claim_results),
        "rendered_answer_complete": all(row["rendered"] for row in claim_results),
        "nonempty_bounded_claims": all(
            0 < len(row["claim_text"]) <= MAX_QUOTE_CHARS
            for row in plan["claims"]
        ),
    }
    return {
        "verification_schema_version": VERIFICATION_SCHEMA_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "answer_plan_id": plan["answer_plan_id"],
        "claim_results": claim_results,
        "gates": gates,
        "verified": all(gates.values()),
    }


def _gold_span_token_recall(claim_text: str, evidence_span: str) -> float:
    gold_tokens = set(tokenize_lexical(evidence_span))
    if not gold_tokens:
        return 0.0
    return len(gold_tokens & set(tokenize_lexical(claim_text))) / len(gold_tokens)


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    return "\n".join(
        [
            "# DNF RAG v3 schema-constrained extractive Generator/Verifier pilot",
            "",
            "## 결과",
            "",
            f"- answer plans: {metrics['answer_plans']}",
            f"- claims: {metrics['claims']}",
            f"- verified plans: {metrics['verified_plans']}/{metrics['answer_plans']}",
            f"- cited evidence groups: {metrics['cited_evidence_group_hits']}/{metrics['evidence_group_count']}",
            f"- minimum gold-span token recall: {metrics['minimum_gold_span_token_recall']:.4f}",
            f"- maximum claim chars: {metrics['maximum_claim_chars']}",
            "",
            "## 판정",
            "",
            *[
                f"- {name}: **{value}**"
                for name, value in report["decisions"].items()
            ],
            "",
            "claim은 cited ChunkV3의 연속 원문 구절이며 자유 생성이나 paraphrase가 아니다.",
            "이 결과는 adaptive development pilot이며 final blind 성능이 아니다.",
            "",
        ]
    )


def freeze_extractive_generator(
    *,
    root: Path,
    artifact_root: Path | None = None,
    documents_path: Path,
    dev_set_path: Path,
    decomposed_cases_path: Path,
    decomposed_manifest_path: Path,
    builder_source_path: Path,
    retrieval_source_path: Path,
    selector_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    documents = read_jsonl(documents_path)
    documents_by_id = {row["document_id"]: row for row in documents}
    dev_by_id = {row["dev_id"]: row for row in read_jsonl(dev_set_path)}
    retrieval_cases = read_jsonl(decomposed_cases_path)
    output_rows = []
    evidence_group_count = 0
    cited_group_hits = 0
    claim_group_specificity_errors = 0
    recalls = []
    claim_lengths = []
    verified_plans = 0
    verified_claims = 0
    for retrieval_case in sorted(
        retrieval_cases, key=lambda row: row["case_id"]
    ):
        plan = build_answer_plan(retrieval_case, documents_by_id)
        verification = verify_answer_plan(plan, retrieval_case, documents_by_id)
        dev = dev_by_id[retrieval_case["case_id"]]
        expected_groups = {row["group_id"] for row in dev["evidence_groups"]}
        cited_groups = set()
        claim_audit = []
        for claim in plan["claims"]:
            matches = [
                group
                for group in dev["evidence_groups"]
                if claim["citation_chunk_id"] in group["acceptable_chunk_ids"]
            ]
            group_ids = sorted(group["group_id"] for group in matches)
            cited_groups.update(group_ids)
            claim_group_specificity_errors += len(group_ids) != 1
            recall = max(
                (
                    _gold_span_token_recall(
                        claim["claim_text"], group["evidence_span"]
                    )
                    for group in matches
                ),
                default=0.0,
            )
            recalls.append(recall)
            claim_lengths.append(len(claim["claim_text"]))
            claim_audit.append(
                {
                    "claim_id": claim["claim_id"],
                    "matched_evidence_group_ids": group_ids,
                    "gold_span_token_recall": round(recall, 8),
                }
            )
        evidence_group_count += len(expected_groups)
        cited_group_hits += len(expected_groups & cited_groups)
        verified_plans += verification["verified"]
        verified_claims += sum(
            row["verified"] for row in verification["claim_results"]
        )
        output_rows.append(
            {
                "case_id": retrieval_case["case_id"],
                "evaluation_role": "adaptive_dev_not_final_benchmark",
                "answer_plan": plan,
                "verification": verification,
                "claim_audit": claim_audit,
                "expected_evidence_group_ids": sorted(expected_groups),
                "cited_evidence_group_ids": sorted(cited_groups),
            }
        )

    claim_count = sum(len(row["answer_plan"]["claims"]) for row in output_rows)
    metrics = {
        "answer_plans": len(output_rows),
        "claims": claim_count,
        "verified_plans": verified_plans,
        "verified_claims": verified_claims,
        "evidence_group_count": evidence_group_count,
        "cited_evidence_group_hits": cited_group_hits,
        "claim_group_specificity_errors": claim_group_specificity_errors,
        "minimum_gold_span_token_recall": round(min(recalls), 8) if recalls else 0.0,
        "mean_gold_span_token_recall": round(sum(recalls) / len(recalls), 8)
        if recalls
        else 0.0,
        "maximum_claim_chars": max(claim_lengths) if claim_lengths else 0,
        "mean_claim_chars": round(sum(claim_lengths) / len(claim_lengths), 2)
        if claim_lengths
        else 0.0,
    }
    gates = {
        "answer_plan_count_4": len(output_rows) == 4,
        "claim_count_8": claim_count == 8,
        "verified_plan_count_4": verified_plans == 4,
        "verified_claim_count_8": verified_claims == 8,
        "cited_evidence_groups_all": cited_group_hits == evidence_group_count,
        "each_claim_matches_one_evidence_group": claim_group_specificity_errors == 0,
        "minimum_gold_span_token_recall_at_least_0_50": min(recalls)
        >= MIN_GOLD_SPAN_TOKEN_RECALL,
        "maximum_claim_chars_at_most_700": max(claim_lengths) <= MAX_QUOTE_CHARS,
    }
    go = all(gates.values())
    decisions = {
        "answer_plan_contract": "GO" if go else "NO-GO",
        "schema_constrained_extractive_generator": "GO" if go else "NO-GO",
        "deterministic_claim_verifier": "GO" if go else "NO-GO",
        "natural_language_generator": "NO-GO",
        "production_nli_verifier": "NO-GO",
        "final_benchmark": "NO-GO",
    }

    generation_dir = artifact_root / "data/v3/generation"
    reports_dir = artifact_root / "reports/v3"
    rows_bytes = _serialize_jsonl(output_rows, lambda row: row["case_id"])
    rows_sha = _sha256_bytes(rows_bytes)
    rows_path = generation_dir / f"extractive_answer_cases_{rows_sha}.jsonl"
    write_immutable(rows_path, rows_bytes)
    input_paths = {
        "documents": documents_path,
        "adaptive_retrieval_dev": dev_set_path,
        "decomposed_hybrid_cases": decomposed_cases_path,
        "decomposed_hybrid_manifest": decomposed_manifest_path,
        "builder_source": builder_source_path,
        "retrieval_source": retrieval_source_path,
        "selector_source": selector_source_path,
        "contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "built_at": BUILT_AT,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in input_paths.items()
        },
        "generation_contract": {
            "mode": "one_exact_quote_from_top_selected_evidence_per_child",
            "max_quote_chars": MAX_QUOTE_CHARS,
            "max_segment_window": MAX_SEGMENT_WINDOW,
            "gold_available_to_generator": False,
            "free_form_generation": False,
        },
        "cases": {
            "path": _relative(artifact_root, rows_path),
            "sha256": rows_sha,
            "row_count": len(output_rows),
            "claim_count": claim_count,
        },
        "metrics": metrics,
        "gates": gates,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = generation_dir / f"extractive_answer_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "metrics": metrics,
        "gates": gates,
        "decisions": decisions,
        "artifacts": {
            "cases_path": _relative(artifact_root, rows_path),
            "cases_sha256": rows_sha,
            "manifest_path": _relative(artifact_root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "paraphrased_generation_quality",
            "natural_contradiction_verifier_performance",
            "independent_holdout",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"extractive_generator_verifier_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"extractive_generator_verifier_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
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
        "gates": gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build schema-constrained extractive answers and verify claims"
    )
    parser.add_argument("--root", type=Path, default=root)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = parse_args().root.resolve()
    result = freeze_extractive_generator(
        root=root,
        documents_path=root / DEFAULT_DOCUMENTS,
        dev_set_path=root / DEFAULT_DEV_SET,
        decomposed_cases_path=root / DEFAULT_DECOMPOSED_CASES,
        decomposed_manifest_path=root / DEFAULT_DECOMPOSED_MANIFEST,
        builder_source_path=root / DEFAULT_BUILDER_SOURCE,
        retrieval_source_path=root / DEFAULT_RETRIEVAL_SOURCE,
        selector_source_path=root / DEFAULT_SELECTOR_SOURCE,
        contract_path=root / DEFAULT_CONTRACT,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
