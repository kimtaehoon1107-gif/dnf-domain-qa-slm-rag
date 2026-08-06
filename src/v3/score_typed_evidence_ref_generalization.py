from __future__ import annotations

import re
from collections import Counter
from typing import Any

from src.v3.value_normalization import (
    CURRENCY_UNITS,
    boolean_value,
    canonical_categorical_values,
    currency_values,
    duration_range_values,
    number_values,
    time_sequence,
    time_values,
)


SCORER_VERSION = "typed-evidence-ref-generalization-scorer-v7"
NORMALIZATION_CONTRACT = {
    "version": "typed-evidence-ref-generalization-normalization-v7",
    "rules": [
        "Whitespace, punctuation, and Korean zero-padded month/day variants are normalized.",
        "Korean and ISO dates are compared as YYYY-MM-DD; month/day-only forms use the frozen as_of year.",
        "06시, 6시, and 06:00 are compared as 06:00; 오전/오후 are converted to 24-hour time.",
        "time and time_range values use the same ordered clock normalization in the verifier and scorer.",
        "duration_range values require both endpoints and the same normalized duration unit.",
        "Plain numbers normalize commas and Korean 만/억 scales in both the verifier and scorer.",
        "Currency commas, Korean 만/억 scales, domain currency units, and unit-first count forms are normalized to integer amount plus unit.",
        "Percentages and plain numbers are compared numerically.",
        "Boolean answers normalize explicit true/false and Korean positive/negative actions while protecting 불가 state nouns.",
        "Strict typed evidence must contain the expected normalized value inside its overlap with a pre-approved evidence unit; boundary-only overlap and same-chunk fallback are not allowed.",
        "Entity values that begin or end with digits use numeric boundaries, so 110 does not match 1100.",
        "For text, enum, entity, and entity_list values, a citation must fully cover a pre-approved evidence unit to use that unit as canonical gold when required_values is a human-authored summary.",
        "No semantic paraphrase credit is added beyond the typed normalizations above.",
        "Automatic semantic false-full is reported separately from unsupported-question false-full and still requires human evidence adjudication.",
        "A blocked model claim is labeled verifier_rejected_model_claim; overreject versus correct reject is a separate human adjudication.",
    ],
}

def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _date_values(value: Any, *, as_of: str) -> set[str]:
    text = str(value or "")
    year = int(as_of[:4])
    values = set()
    for match in re.finditer(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)", text):
        values.add(
            f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        )
    for match in re.finditer(
        r"(?<!\d)(20\d{2})\s*년\s*0?(\d{1,2})\s*월\s*0?(\d{1,2})\s*일",
        text,
    ):
        values.add(
            f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        )
    for match in re.finditer(
        r"(?<![\d년])0?(\d{1,2})\s*월\s*0?(\d{1,2})\s*일",
        text,
    ):
        values.add(f"{year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}")
    for match in re.finditer(r"(?<![\d.])0?(\d{1,2})[./]0?(\d{1,2})(?![\d.])", text):
        values.add(f"{year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}")
    return values


def _percentage_values(value: Any) -> set[float]:
    return {
        float(match.group(1))
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", str(value or ""))
    }


def _expected_currency(value: Any) -> tuple[int, str] | None:
    if not isinstance(value, dict):
        parsed = currency_values(value)
        return next(iter(parsed)) if len(parsed) == 1 else None
    amount = value.get("amount")
    unit = str(value.get("unit") or "").casefold()
    if not isinstance(amount, (int, float)) or unit not in CURRENCY_UNITS:
        return None
    return int(amount), CURRENCY_UNITS[unit]


def value_present(
    expected: Any,
    value_type: str,
    observed: Any,
    *,
    as_of: str,
    relation: str | None = None,
) -> bool:
    if value_type == "boolean" or isinstance(expected, bool):
        return boolean_value(expected) is not None and boolean_value(expected) == boolean_value(
            observed
        )
    if isinstance(expected, dict):
        normalized = _expected_currency(expected)
        return normalized is not None and normalized in currency_values(
            observed
        )
    if value_type in {"currency", "price"}:
        normalized = _expected_currency(expected)
        return normalized is not None and normalized in currency_values(observed)
    if value_type == "percentage":
        expected_values = (
            {float(expected)}
            if isinstance(expected, (int, float))
            else _percentage_values(expected) or number_values(expected)
        )
        return bool(expected_values) and expected_values <= _percentage_values(observed)
    if value_type == "number" or isinstance(expected, (int, float)):
        return float(expected) in number_values(observed)
    if value_type == "time":
        expected_times = time_values(expected)
        return len(expected_times) == 1 and expected_times <= time_values(
            observed
        )
    if value_type == "time_range":
        expected_times = time_sequence(expected)
        observed_times = time_sequence(observed)
        return len(expected_times) >= 2 and any(
            observed_times[index : index + len(expected_times)]
            == expected_times
            for index in range(
                len(observed_times) - len(expected_times) + 1
            )
        )
    if value_type == "duration_range":
        expected_ranges = duration_range_values(expected)
        return bool(expected_ranges) and expected_ranges <= duration_range_values(
            observed
        )

    expected_text = str(expected)
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2})?", expected_text):
        expected_date = expected_text[:10]
        expected_time = expected_text[11:16]
        return expected_date in _date_values(observed, as_of=as_of) and expected_time in time_values(
            observed
        )
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", expected_text):
        return expected_text in _date_values(observed, as_of=as_of)
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", expected_text):
        return expected_text in time_values(observed)

    canonical_expected = canonical_categorical_values(
        expected,
        relation=relation,
    )
    if canonical_expected:
        return canonical_expected <= canonical_categorical_values(
            observed,
            relation=relation,
        )

    compact_expected = _compact(expected_text)
    if (
        value_type in {"entity", "entity_list"}
        and compact_expected
        and (
            compact_expected[0].isdigit()
            or compact_expected[-1].isdigit()
        )
    ):
        prefix = r"(?<!\d)" if compact_expected[0].isdigit() else ""
        suffix = r"(?!\d)" if compact_expected[-1].isdigit() else ""
        return bool(
            re.search(
                prefix + re.escape(compact_expected) + suffix,
                _compact(observed),
            )
        )
    return bool(compact_expected) and compact_expected in _compact(observed)


def _citation_exact(citation: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]) -> bool:
    chunk = chunks_by_id.get(citation.get("chunk_id"))
    if chunk is None:
        return False
    start = citation.get("start_char")
    end = citation.get("end_char")
    return (
        isinstance(start, int)
        and isinstance(end, int)
        and chunk["display_text"][start:end] == citation.get("text")
    )


def _citation_supports_unit(
    citation: dict[str, Any],
    unit: dict[str, Any],
    *,
    expected: Any,
    value_type: str,
    as_of: str,
) -> bool:
    if citation.get("chunk_id") != unit["chunk_id"]:
        return False
    citation_start = citation.get("start_char")
    citation_end = citation.get("end_char")
    if not isinstance(citation_start, int) or not isinstance(
        citation_end,
        int,
    ):
        return False
    covers_unit = (
        citation_start <= unit["start_char"]
        and citation_end >= unit["end_char"]
    )
    if value_type not in _STRICT_VALUE_TYPES:
        return covers_unit

    overlap_start = max(citation_start, unit["start_char"])
    overlap_end = min(citation_end, unit["end_char"])
    if overlap_start >= overlap_end:
        return False
    unit_text = str(unit.get("text") or "")
    overlap_text = unit_text[
        overlap_start - unit["start_char"] : overlap_end - unit["start_char"]
    ]
    return value_present(
        expected,
        value_type,
        overlap_text,
        as_of=as_of,
    )


_STRICT_VALUE_TYPES = {
    "boolean",
    "currency",
    "date",
    "date_range",
    "datetime",
    "duration_range",
    "number",
    "percentage",
    "price",
    "time",
    "time_range",
}


def _approved_evidence_groups(
    requirement: dict[str, Any],
    *,
    as_of: str,
) -> list[list[dict[str, Any]]]:
    values = requirement.get("required_values") or []
    units = requirement.get("acceptable_evidence_units") or []
    if not values or not units:
        return [[]]

    groups = []
    for value_index, value in enumerate(values):
        matching_units = [
            unit
            for unit in units
            if value_present(
                value,
                requirement["value_type"],
                unit["text"],
                as_of=as_of,
                relation=requirement.get("relation"),
            )
        ]
        if (
            not matching_units
            and requirement["value_type"] not in _STRICT_VALUE_TYPES
            and len(units) == len(values)
        ):
            matching_units = [units[value_index]]
        groups.append(matching_units)
    return groups


def score_generalization_cases(
    sealed_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(sealed_rows) != len(run_rows):
        raise RuntimeError("sealed and run row counts differ")
    run_by_id = {row["candidate_id"]: row for row in run_rows}
    if len(run_by_id) != len(run_rows):
        raise RuntimeError("duplicate run candidate_id")

    scored_rows = []
    for sealed in sealed_rows:
        run = run_by_id.get(sealed["candidate_id"])
        if run is None:
            raise RuntimeError(f"missing run row: {sealed['candidate_id']}")
        decisions = {
            row["requirement_id"]: row
            for row in run["verified_output"]["requirements"]
        }
        audits = {
            row["requirement_id"]: row
            for row in run["verified_output"]["verification"]["requirements"]
        }
        requirement_scores = []
        for requirement in sealed["requirements"]:
            requirement_id = requirement["requirement_id"]
            decision = decisions.get(requirement_id, {})
            audit = audits.get(requirement_id, {})
            expected_supported = requirement["expected_status"] == "supported"
            exposed_supported = decision.get("status") == "supported_exact"
            answer = decision.get("answer", "")
            values = requirement["required_values"]
            citations = decision.get("citations") or []
            citation_slices_exact = all(
                _citation_exact(citation, chunks_by_id) for citation in citations
            )
            evidence_complete = False
            if expected_supported and values:
                value_hits = [
                    (
                        any(
                            _citation_supports_unit(
                                citation,
                                unit,
                                expected=value,
                                value_type=requirement["value_type"],
                                as_of=sealed["as_of"],
                            )
                            for citation in citations
                            for unit in matching_units
                        )
                    )
                    for value, matching_units in zip(
                        values,
                        _approved_evidence_groups(
                            requirement,
                            as_of=sealed["as_of"],
                        ),
                        strict=True,
                    )
                ]
                evidence_complete = all(value_hits)
            normalized_value_complete = bool(
                expected_supported
                and exposed_supported
                and values
                and all(
                    value_present(
                        value,
                        requirement["value_type"],
                        answer,
                        as_of=sealed["as_of"],
                        relation=requirement.get("relation"),
                    )
                    for value in values
                )
            )
            value_complete = normalized_value_complete or bool(
                expected_supported
                and exposed_supported
                and requirement["value_type"] not in _STRICT_VALUE_TYPES
                and evidence_complete
            )
            typed_claim_complete = bool(
                normalized_value_complete and evidence_complete
            )
            false_full = not expected_supported and exposed_supported
            automatic_false_supported = bool(
                expected_supported
                and exposed_supported
                and not typed_claim_complete
            )
            requirement_scores.append(
                {
                    "requirement_id": requirement_id,
                    "expected_status": requirement["expected_status"],
                    "exposed_status": decision.get("status"),
                    "model_status": audit.get("model_status"),
                    "gold_value_complete": value_complete,
                    "typed_answer_value_complete": (
                        normalized_value_complete
                    ),
                    "typed_claim_complete": typed_claim_complete,
                    "evidence_span_hit": evidence_complete,
                    "citation_slices_exact": citation_slices_exact,
                    "false_full": false_full,
                    "automatic_false_supported": automatic_false_supported,
                    "answer": answer,
                    "failure_reasons": audit.get("failure_reasons", []),
                }
            )

        supported_scores = [
            row for row in requirement_scores if row["expected_status"] == "supported"
        ]
        supported_exposed = sum(
            row["exposed_status"] == "supported_exact" for row in supported_scores
        )
        gold_complete = bool(supported_scores) and all(
            row["gold_value_complete"] for row in supported_scores
        )
        typed_answer_complete = bool(supported_scores) and all(
            row["typed_answer_value_complete"]
            for row in supported_scores
        )
        supported_typed_claim_complete = bool(supported_scores) and all(
            row["typed_claim_complete"] for row in supported_scores
        )
        false_full = any(row["false_full"] for row in requirement_scores)
        typed_claim_complete = (
            supported_typed_claim_complete and not false_full
        )
        if gold_complete:
            outcome = "correct"
        elif supported_exposed == 0:
            outcome = "no_response"
        else:
            outcome = "incorrect"
        if typed_claim_complete:
            typed_outcome = "correct"
        elif supported_exposed == 0:
            typed_outcome = "no_response"
        else:
            typed_outcome = "incorrect"
        automatic_semantic_false_full = bool(
            run["verified_output"].get("response_mode") == "full_answer"
            and (
                false_full
                or any(
                    row["automatic_false_supported"]
                    for row in requirement_scores
                )
            )
        )
        unsupported_expected = any(
            row["expected_status"] == "unsupported" for row in requirement_scores
        )
        generation_error = bool(
            run["verified_output"]["verification"].get("generation_error")
        )
        candidate_pools = run.get("requirement_candidate_chunk_ids") or []
        candidate_complete = all(
            all(
                bool(
                    set(
                        candidate_pools[index]
                        if index < len(candidate_pools)
                        else []
                    )
                    & {unit["chunk_id"] for unit in evidence_group}
                )
                for evidence_group in _approved_evidence_groups(
                    requirement,
                    as_of=sealed["as_of"],
                )
            )
            for index, requirement in enumerate(sealed["requirements"])
            if requirement["expected_status"] == "supported"
        )
        holdout_score = {
            "slot_ordinal": sealed["slot_ordinal"],
            "outcome": outcome,
            "gold_value_complete": gold_complete,
            "typed_answer_value_complete": typed_answer_complete,
            "typed_claim_complete": typed_claim_complete,
            "typed_outcome": typed_outcome,
            "all_evidence_spans_hit": bool(supported_scores)
            and all(row["evidence_span_hit"] for row in supported_scores),
            "candidate_all_gold_covered": candidate_complete,
            "all_citation_slices_exact": all(
                row["citation_slices_exact"] for row in requirement_scores
            ),
            "has_unsupported_requirement": unsupported_expected,
            "false_full": false_full,
            "automatic_semantic_false_full": automatic_semantic_false_full,
            "honest_unsupported_abstention": unsupported_expected and not false_full,
            "generation_error": generation_error,
            "requirement_scores": requirement_scores,
        }
        if false_full:
            failure_stage = "unsupported_false_full"
        elif (
            automatic_semantic_false_full
            and typed_outcome != "correct"
        ):
            failure_stage = "automatic_semantic_false_full"
        elif generation_error:
            failure_stage = "generation_error"
        elif not candidate_complete:
            failure_stage = "retrieval_missing_gold"
        elif outcome == "correct":
            failure_stage = None
        elif any(
            row["model_status"] == "supported"
            and row["exposed_status"] != "supported_exact"
            for row in supported_scores
        ):
            failure_stage = "verifier_rejected_model_claim"
        elif outcome == "no_response":
            failure_stage = "generator_abstain"
        else:
            failure_stage = "generator_value_selection"
        holdout_score["failure_stage"] = failure_stage
        scored_rows.append({**run, "holdout_score": holdout_score})

    total = len(scored_rows)
    outcome_counts = Counter(row["holdout_score"]["outcome"] for row in scored_rows)
    typed_outcome_counts = Counter(
        row["holdout_score"]["typed_outcome"] for row in scored_rows
    )
    honest_rows = [
        row for row in scored_rows if row["holdout_score"]["has_unsupported_requirement"]
    ]
    latencies = sorted(
        float(row.get("model_call", {}).get("latency_ms", 0.0))
        for row in scored_rows
    )

    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
        return round(values[index], 3)

    summary = {
        "scorer_version": SCORER_VERSION,
        "normalization_contract": NORMALIZATION_CONTRACT,
        "fixed_denominator": total,
        "gold_value_complete": {
            "successes": sum(row["holdout_score"]["gold_value_complete"] for row in scored_rows),
            "total": total,
        },
        "typed_answer_value_complete": {
            "successes": sum(
                row["holdout_score"]["typed_answer_value_complete"]
                for row in scored_rows
            ),
            "total": total,
        },
        "typed_claim_complete": {
            "successes": sum(
                row["holdout_score"]["typed_claim_complete"]
                for row in scored_rows
            ),
            "total": total,
        },
        "outcomes": {
            "correct": outcome_counts["correct"],
            "incorrect": outcome_counts["incorrect"],
            "no_response": outcome_counts["no_response"],
        },
        "typed_outcomes": {
            "correct": typed_outcome_counts["correct"],
            "incorrect": typed_outcome_counts["incorrect"],
            "no_response": typed_outcome_counts["no_response"],
        },
        "all_evidence_spans_hit": {
            "successes": sum(
                row["holdout_score"]["all_evidence_spans_hit"] for row in scored_rows
            ),
            "total": total,
        },
        "candidate_all_gold_covered": {
            "successes": sum(
                row["holdout_score"]["candidate_all_gold_covered"] for row in scored_rows
            ),
            "total": total,
        },
        "honest_unsupported": {
            "slots": [row["holdout_score"]["slot_ordinal"] for row in honest_rows],
            "correct_abstentions": sum(
                row["holdout_score"]["honest_unsupported_abstention"]
                for row in honest_rows
            ),
            "false_full": sum(row["holdout_score"]["false_full"] for row in honest_rows),
            "total": len(honest_rows),
        },
        "automatic_semantic_false_full": {
            "count": sum(
                row["holdout_score"]["automatic_semantic_false_full"]
                for row in scored_rows
            ),
            "slots": [
                row["holdout_score"]["slot_ordinal"]
                for row in scored_rows
                if row["holdout_score"]["automatic_semantic_false_full"]
            ],
        },
        "relation_validation": {
            "explicit_alias": sum(
                audit.get("relation_validation_state") == "explicit_alias"
                for row in scored_rows
                for audit in row["verified_output"]["verification"].get(
                    "requirements",
                    [],
                )
            ),
            "surface_fallback": sum(
                audit.get("relation_validation_state") == "surface_fallback"
                for row in scored_rows
                for audit in row["verified_output"]["verification"].get(
                    "requirements",
                    [],
                )
            ),
            "unvalidated": sum(
                audit.get("relation_validation_state") == "unvalidated"
                for row in scored_rows
                for audit in row["verified_output"]["verification"].get(
                    "requirements",
                    [],
                )
            ),
            "total": sum(
                1
                for row in scored_rows
                for audit in row["verified_output"]["verification"].get(
                    "requirements",
                    [],
                )
                if audit.get("relation_validation_state")
                in {
                    "explicit_alias",
                    "surface_fallback",
                    "unvalidated",
                }
            ),
            "exposed_unvalidated_slots": sorted(
                {
                    row["holdout_score"]["slot_ordinal"]
                    for row in scored_rows
                    if any(
                        audit.get("relation_validation_state")
                        == "unvalidated"
                        and audit.get("exposed_status")
                        == "supported_exact"
                        for audit in row["verified_output"]["verification"].get(
                            "requirements",
                            [],
                        )
                    )
                }
            ),
        },
        "verifier_rejection_reasons": dict(
            sorted(
                Counter(
                    reason
                    for row in scored_rows
                    for audit in row["verified_output"]["verification"].get(
                        "requirements",
                        [],
                    )
                    if audit.get("model_status") == "supported"
                    and audit.get("exposed_status") != "supported_exact"
                    for reason in audit.get("failure_reasons", [])
                ).items()
            )
        ),
        "generation_error_count": sum(
            row["holdout_score"]["generation_error"] for row in scored_rows
        ),
        "all_citation_slices_exact": all(
            row["holdout_score"]["all_citation_slices_exact"] for row in scored_rows
        ),
        "latency_ms": {
            "total": round(sum(latencies), 3),
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "usage": {
            key: sum(
                int(row.get("model_call", {}).get("usage", {}).get(key, 0))
                for row in scored_rows
            )
            for key in ("input_tokens", "output_tokens", "total_tokens")
        },
        "failure_slots": [
            row["holdout_score"]["slot_ordinal"]
            for row in scored_rows
            if row["holdout_score"]["outcome"] != "correct"
            or row["holdout_score"]["false_full"]
            or row["holdout_score"]["automatic_semantic_false_full"]
        ],
    }
    failure_rows = [
        row for row in scored_rows if row["holdout_score"]["failure_stage"] is not None
    ]
    summary["failure_breakdown"] = dict(
        sorted(
            Counter(
                row["holdout_score"]["failure_stage"] for row in failure_rows
            ).items()
        )
    )
    summary["failure_cases"] = [
        {
            "slot_ordinal": row["holdout_score"]["slot_ordinal"],
            "failure_stage": row["holdout_score"]["failure_stage"],
            "outcome": row["holdout_score"]["outcome"],
            "typed_outcome": row["holdout_score"]["typed_outcome"],
            "false_full": row["holdout_score"]["false_full"],
            "automatic_semantic_false_full": row["holdout_score"][
                "automatic_semantic_false_full"
            ],
        }
        for row in failure_rows
    ]
    summary["gates"] = {
        "generation_error_zero": summary["generation_error_count"] == 0,
        "honest_unsupported_false_full_zero": summary["honest_unsupported"]["false_full"]
        == 0,
        "automatic_semantic_false_full_zero": summary[
            "automatic_semantic_false_full"
        ]["count"]
        == 0,
    }
    return scored_rows, summary
