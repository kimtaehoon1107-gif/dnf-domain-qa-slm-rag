from __future__ import annotations

import re
import statistics
from datetime import date
from typing import Any

from src.v3.product_evidence_pack import explicit_question_clauses
from src.v3.value_normalization import (
    boolean_value,
    currency_values,
    number_values,
    time_values,
)


SCORER_VERSION = "product-free-rag-a6-scorer-v2"


_GENERIC_QUESTION_TOKENS = {
    "알려줘",
    "정확히",
    "뭐야",
    "무엇",
    "어디",
    "몇",
    "얼마",
}
_ABSTENTION_CUES = (
    "확인할 수 없",
    "알 수 없",
    "공식 근거가 없",
    "제공되지 않",
)


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _date_values(value: Any, *, as_of: str) -> set[str]:
    text = str(value or "")
    default_year = int(as_of[:4])
    output = set()
    for match in re.finditer(
        r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)",
        text,
    ):
        output.add(
            f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        )
    for match in re.finditer(
        r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
        text,
    ):
        output.add(
            f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        )
    for match in re.finditer(
        r"(?<![\d년])(\d{1,2})\s*월\s*(\d{1,2})\s*일",
        text,
    ):
        output.add(
            f"{default_year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
        )
    return output


def _scalar_present(
    expected: Any,
    observed: str,
    *,
    as_of: str,
) -> bool:
    if isinstance(expected, bool):
        return (
            boolean_value(expected) is not None
            and boolean_value(expected) == boolean_value(observed)
        )
    if isinstance(expected, (int, float)):
        return float(expected) in number_values(observed)
    text = str(expected or "")
    if not text:
        return False
    expected_dates = _date_values(text, as_of=as_of)
    if expected_dates:
        if not expected_dates <= _date_values(observed, as_of=as_of):
            return False
        expected_times = time_values(text)
        return not expected_times or expected_times <= time_values(observed)
    compact = _compact(text)
    return bool(compact) and compact in _compact(observed)


def _structured_present(
    expected: Any,
    observed: str,
    *,
    as_of: str,
    include_keys: bool = False,
) -> bool:
    if isinstance(expected, dict):
        amount_key = (
            "amount"
            if "amount" in expected
            else "price"
            if "price" in expected and "unit" in expected
            else None
        )
        if amount_key is not None and "unit" in expected:
            amount = expected.get(amount_key)
            unit = str(expected.get("unit") or "")
            if not isinstance(amount, (int, float)) or not unit:
                return False
            normalized_pair_present = any(
                numeric == int(amount) and normalized_unit == unit.casefold()
                for numeric, normalized_unit in currency_values(observed)
            )
            pair_present = normalized_pair_present or bool(
                float(amount) in number_values(observed)
                and _compact(unit) in _compact(observed)
            )
            remaining = {
                key: value
                for key, value in expected.items()
                if key not in {amount_key, "unit"}
            }
            return pair_present and all(
                _structured_present(value, observed, as_of=as_of)
                for value in remaining.values()
            )
        key_checks = [
            (
                _scalar_present(key, observed, as_of=as_of)
                or (
                    str(key).endswith("날개")
                    and _scalar_present(
                        str(key)[: -len("날개")].strip(),
                        observed,
                        as_of=as_of,
                    )
                )
            )
            for key in expected
            if include_keys and re.search(r"[가-힣]", str(key))
        ]
        return all(key_checks) and all(
            _structured_present(value, observed, as_of=as_of)
            for value in expected.values()
        )
    if isinstance(expected, list):
        return all(
            _structured_present(value, observed, as_of=as_of)
            for value in expected
        )
    return _scalar_present(expected, observed, as_of=as_of)


def requirement_value_complete(
    requirement: dict[str, Any],
    *,
    rendered_answer: str,
    as_of: str,
) -> bool:
    values = requirement.get("required_values") or []
    if requirement.get("expected_status") != "supported" or not values:
        return False
    value_type = str(requirement.get("value_type") or "")
    if value_type in {"time_range", "date_range"}:
        if value_type == "time_range":
            expected = set()
            for value in values:
                expected.update(time_values(value))
            return bool(expected) and expected <= time_values(rendered_answer)
        expected_dates = set()
        for value in values:
            expected_dates.update(_date_values(value, as_of=as_of))
        return bool(expected_dates) and expected_dates <= _date_values(
            rendered_answer,
            as_of=as_of,
        )
    return all(
        _structured_present(
            value,
            rendered_answer,
            as_of=as_of,
            include_keys=requirement.get("relation") == "avatar_market_type_mapping",
        )
        for value in values
    )


def _citations(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        citation
        for claim in result.get("claims") or []
        for citation in claim.get("citations") or []
    ]


def citation_exact(
    citation: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> bool:
    chunk = chunks_by_id.get(str(citation.get("chunk_id") or ""))
    start = citation.get("start_char")
    end = citation.get("end_char")
    return bool(
        chunk is not None
        and isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= len(str(chunk["display_text"]))
        and str(chunk["display_text"])[start:end] == citation.get("text")
    )


def _citation_covers_unit(
    citation: dict[str, Any],
    unit: dict[str, Any],
) -> bool:
    start = citation.get("start_char")
    end = citation.get("end_char")
    return bool(
        citation.get("chunk_id") == unit.get("chunk_id")
        and isinstance(start, int)
        and isinstance(end, int)
        and start < unit.get("end_char", -1)
        and end > unit.get("start_char", -1)
    )


def _expected_mode(row: dict[str, Any]) -> str:
    return {
        "full_answer": "answer",
        "partial_answer": "partial",
        "clarification": "clarification",
        "abstain": "unsupported",
    }[row["expected_response_mode"]]


def _relation_tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
        if len(token) >= 2 and token.casefold() not in _GENERIC_QUESTION_TOKENS
    }


def _claim_matches_unsupported_clause(claim: str, clause: str) -> bool:
    clause_tokens = _relation_tokens(clause)
    claim_tokens = _relation_tokens(claim)
    return len(clause_tokens & claim_tokens) >= 2


def _unsupported_value_exposed(value_type: str, claim: str) -> bool:
    if not claim.strip() or any(cue in claim for cue in _ABSTENTION_CUES):
        return False
    if value_type == "percentage":
        return bool(
            re.search(r"(?<!\d)\d+(?:\.\d+)?\s*(?:%|퍼센트)", claim)
        )
    if value_type in {"number", "structured_values", "object"}:
        return bool(re.search(r"\d", claim) or boolean_value(claim) is not None)
    if value_type in {"currency", "price"}:
        return bool(currency_values(claim))
    if value_type in {"date", "date_range"}:
        return bool(re.search(r"\d", claim))
    if value_type in {"time", "time_range"}:
        return bool(time_values(claim))
    if value_type == "boolean":
        return boolean_value(claim) is not None
    return True


def unsupported_requirement_overclaim_checks(
    frozen: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    unsupported = [
        requirement
        for requirement in frozen.get("requirements") or []
        if requirement.get("expected_status") == "unsupported"
    ]
    if not unsupported or str(result.get("mode") or "") not in {
        "answer",
        "partial",
    }:
        return []
    claims = [
        str(claim.get("text") or "").strip()
        for claim in result.get("claims") or []
        if str(claim.get("text") or "").strip()
    ]
    if not claims:
        rendered = str(result.get("rendered_answer") or "").strip()
        claims = [rendered] if rendered else []
    clauses = explicit_question_clauses(str(frozen.get("question_text") or ""))
    unsupported_clauses = (
        clauses[-len(unsupported) :]
        if len(clauses) >= len(unsupported)
        else clauses
    )
    checks = []
    for index, requirement in enumerate(unsupported):
        clause = (
            unsupported_clauses[index]
            if index < len(unsupported_clauses)
            else str(frozen.get("question_text") or "")
        )
        matched_claims = [
            claim
            for claim in claims
            if (
                len(unsupported) == len(frozen.get("requirements") or []) == 1
                or _claim_matches_unsupported_clause(claim, clause)
            )
        ]
        exposed_claims = [
            claim
            for claim in matched_claims
            if _unsupported_value_exposed(
                str(requirement.get("value_type") or ""),
                claim,
            )
        ]
        checks.append(
            {
                "requirement_id": requirement["requirement_id"],
                "question_clause": clause,
                "matched_claims": matched_claims,
                "exposed_claims": exposed_claims,
                "unsupported_value_exposed": bool(exposed_claims),
            }
        )
    return checks


def score_case(
    frozen: dict[str, Any],
    result: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    expected_mode = _expected_mode(frozen)
    actual_mode = str(result.get("mode") or "")
    rendered_answer = str(result.get("rendered_answer") or "")
    query_mode = frozen["expected_query_mode"]
    citations = _citations(result)
    actual_qwen_called = result.get("generation") is not None
    base = {
        "slot_ordinal": frozen["slot_ordinal"],
        "candidate_id": frozen["candidate_id"],
        "question": frozen["question_text"],
        "expected_query_mode": query_mode,
        "expected_mode": expected_mode,
        "actual_mode": actual_mode,
        "mode_match": actual_mode == expected_mode,
        "qwen_call_match": actual_qwen_called
        == frozen["expected_qwen_called"],
        "false_full_candidate": bool(
            frozen["expected_response_mode"] in {"partial_answer", "abstain"}
            and actual_mode == "answer"
        ),
        "unsupported_overclaim_candidate": False,
    }
    if frozen["expected_response_mode"] == "clarification":
        clarification = str(result.get("clarification") or rendered_answer)
        exact = _compact(clarification) == _compact(
            frozen["expected_clarification"]
        )
        return {
            **base,
            "meaning_complete": bool(base["mode_match"] and exact),
            "citation_policy_restored": True,
            "clarification_exact": exact,
            "requirement_scores": [],
            "result": result,
        }

    if query_mode == "metadata":
        actual_document_ids = [
            str(row.get("document_id") or "")
            for row in result.get("candidates") or []
        ]
        expected_document_ids = frozen["expected_document_ids"]
        documents_exact = actual_document_ids == expected_document_ids
        metadata_scores = [
            {
                "requirement_id": requirement["requirement_id"],
                "value_complete": all(
                    _structured_present(value, rendered_answer, as_of=frozen["as_of"])
                    for value in requirement["required_values"]
                ),
            }
            for requirement in frozen["requirements"]
        ]
        effective_as_of_match = (
            result.get("verification", {}).get("effective_as_of")
            == frozen["expected_effective_as_of"]
        )
        metadata_citations = citations
        citation_documents = [
            str(citation.get("document_id") or "")
            for citation in metadata_citations
        ]
        metadata_refs_exact = (
            citation_documents == expected_document_ids
            and all(citation.get("field_refs") for citation in metadata_citations)
        )
        meaning_complete = bool(
            base["mode_match"]
            and documents_exact
            and effective_as_of_match
            and all(score["value_complete"] for score in metadata_scores)
        )
        return {
            **base,
            "meaning_complete": meaning_complete,
            "citation_policy_restored": metadata_refs_exact,
            "metadata_documents_exact": documents_exact,
            "effective_as_of_match": effective_as_of_match,
            "requirement_scores": metadata_scores,
            "result": result,
        }

    unsupported_checks = unsupported_requirement_overclaim_checks(
        frozen,
        result,
    )
    unsupported_by_id = {
        check["requirement_id"]: check
        for check in unsupported_checks
    }
    base["unsupported_overclaim_candidate"] = any(
        check["unsupported_value_exposed"]
        for check in unsupported_checks
    )
    base["unsupported_overclaim_checks"] = unsupported_checks
    requirement_scores = []
    for requirement in frozen["requirements"]:
        supported = requirement["expected_status"] == "supported"
        value_complete = (
            requirement_value_complete(
                requirement,
                rendered_answer=rendered_answer,
                as_of=frozen["as_of"],
            )
            if supported
            else False
        )
        evidence_complete = bool(
            supported
            and any(
                _citation_covers_unit(citation, unit)
                for citation in citations
                for unit in requirement["acceptable_evidence_units"]
            )
        )
        canonical_evidence_credit = bool(
            evidence_complete
            and requirement.get("value_type")
            in {"text", "enum", "entity", "entity_list"}
        )
        requirement_scores.append(
            {
                "requirement_id": requirement["requirement_id"],
                "expected_status": requirement["expected_status"],
                "direct_value_complete": value_complete,
                "value_complete": bool(
                    value_complete or canonical_evidence_credit
                ),
                "evidence_complete": evidence_complete,
                "claim_complete": bool(
                    evidence_complete
                    and (value_complete or canonical_evidence_credit)
                ),
                "unsupported_value_exposed": bool(
                    unsupported_by_id.get(
                        requirement["requirement_id"],
                        {},
                    ).get("unsupported_value_exposed", False)
                ),
            }
        )
    supported_scores = [
        score
        for score in requirement_scores
        if score["expected_status"] == "supported"
    ]
    all_requirements_unsupported = bool(requirement_scores) and not supported_scores
    citations_exact = all(
        citation_exact(citation, chunks_by_id=chunks_by_id)
        for citation in citations
    )
    citation_policy_restored = bool(
        citations_exact
        and result.get("verification", {}).get("all_exposed_citations_verified")
    )
    return {
        **base,
        "meaning_complete": bool(
            base["mode_match"]
            and (
                all_requirements_unsupported
                or (
                    supported_scores
                    and all(score["claim_complete"] for score in supported_scores)
                )
            )
        ),
        "citation_policy_restored": citation_policy_restored,
        "all_exposed_citations_exact": citations_exact,
        "requirement_scores": requirement_scores,
        "result": result,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            int(fraction * len(ordered) + 0.999999) - 1,
        ),
    )
    return round(ordered[index], 3)


def summarize(
    rows: list[dict[str, Any]],
    *,
    expected_count: int,
    error_count: int,
    regression_passed: bool,
) -> dict[str, Any]:
    clear_rows = [
        row for row in rows if row["expected_mode"] != "clarification"
    ]
    semantic_correct = sum(row["meaning_complete"] for row in clear_rows)
    semantic_accuracy = (
        semantic_correct / len(clear_rows) if clear_rows else 0.0
    )
    latencies = [
        float(row["result"].get("latency", {}).get("total_ms") or 0.0)
        for row in rows
    ]
    generation = [
        row["result"]["generation"]
        for row in rows
        if row["result"].get("generation") is not None
    ]
    input_tokens = [
        int(item.get("usage", {}).get("input_tokens") or 0)
        for item in generation
    ]
    p50_ms = round(statistics.median(latencies), 3) if latencies else None
    p95_ms = _percentile(latencies, 0.95)
    gates = {
        "completed_32": len(rows) == expected_count == 32,
        "clear_semantic_accuracy_at_least_80pct": semantic_accuracy >= 0.8,
        "false_full_zero": not any(row["false_full_candidate"] for row in rows),
        "unsupported_overclaim_zero": not any(
            row.get("unsupported_overclaim_candidate", False) for row in rows
        ),
        "citation_policy_restoration_32_of_32": sum(
            row["citation_policy_restored"] for row in rows
        )
        == expected_count,
        "generation_errors_zero": error_count == 0,
        "qwen_call_contract_all_match": all(
            row["qwen_call_match"] for row in rows
        ),
        "regression_tests_passed": regression_passed,
        "average_input_tokens_at_most_2000": (
            bool(input_tokens) and sum(input_tokens) / len(input_tokens) <= 2000
        ),
        "p50_at_most_15_seconds": p50_ms is not None and p50_ms <= 15000,
        "p95_at_most_30_seconds": p95_ms is not None and p95_ms <= 30000,
    }
    return {
        "type": "summary",
        "status": "provisional_awaiting_human_semantic_review",
        "scorer_version": SCORER_VERSION,
        "case_count": expected_count,
        "completed": len(rows),
        "clear_case_count": len(clear_rows),
        "clear_semantic_correct": semantic_correct,
        "clear_semantic_accuracy": semantic_accuracy,
        "false_full_slots": [
            row["slot_ordinal"]
            for row in rows
            if row["false_full_candidate"]
        ],
        "unsupported_overclaim_slots": [
            row["slot_ordinal"]
            for row in rows
            if row.get("unsupported_overclaim_candidate", False)
        ],
        "citation_policy_restored": sum(
            row["citation_policy_restored"] for row in rows
        ),
        "generation_calls": len(generation),
        "generation_error_count": error_count,
        "average_input_tokens": (
            sum(input_tokens) / len(input_tokens) if input_tokens else None
        ),
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "gates": gates,
        "automated_go_candidate": all(gates.values()),
        "human_semantic_review_required": True,
        "go": None,
    }
