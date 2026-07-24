from __future__ import annotations

import re
from collections import Counter
from typing import Any


SCORER_VERSION = "typed-evidence-ref-generalization-scorer-v1"
NORMALIZATION_CONTRACT = {
    "version": "typed-evidence-ref-generalization-normalization-v1",
    "rules": [
        "Whitespace, punctuation, and Korean zero-padded month/day variants are normalized.",
        "Korean and ISO dates are compared as YYYY-MM-DD; month/day-only forms use the frozen as_of year.",
        "06시, 6시, and 06:00 are compared as 06:00; 오전/오후 are converted to 24-hour time.",
        "Currency commas and Korean 만/억 scales are normalized to integer amount plus unit.",
        "Percentages and plain numbers are compared numerically.",
        "Boolean answers normalize explicit true/false and Korean positive/negative expressions.",
        "Table-row and prose citations are equivalent only when the normalized gold value is present and the citation comes from an approved evidence chunk.",
        "For text, enum, entity, and entity_list values, a directly cited pre-approved evidence unit is the canonical gold when required_values is a human-authored summary of that unit.",
        "No semantic paraphrase credit is added beyond the typed normalizations above.",
    ],
}

_CURRENCY_UNITS = {
    "세라": "SERA",
    "sera": "SERA",
    "골드": "GOLD",
    "gold": "GOLD",
    "원": "KRW",
    "krw": "KRW",
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


def _time_values(value: Any) -> set[str]:
    text = str(value or "")
    values = {
        f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
        for match in re.finditer(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    }
    for match in re.finditer(
        r"(?:(오전|오후)\s*)?([01]?\d|2[0-3])\s*시(?:\s*([0-5]?\d)\s*분)?",
        text,
    ):
        meridiem = match.group(1)
        hour = int(match.group(2))
        minute = int(match.group(3) or 0)
        if meridiem == "오전" and hour == 12:
            hour = 0
        elif meridiem == "오후" and hour < 12:
            hour += 12
        values.add(f"{hour:02d}:{minute:02d}")
    return values


def _currency_values(value: Any) -> set[tuple[int, str]]:
    text = str(value or "")
    values = set()
    pattern = re.compile(
        r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>만|억)?\s*"
        r"(?P<unit>세라|골드|원|SERA|GOLD|KRW)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        amount = float(match.group("amount").replace(",", ""))
        scale = {"만": 10_000, "억": 100_000_000}.get(match.group("scale"), 1)
        unit = _CURRENCY_UNITS[match.group("unit").casefold()]
        values.add((int(amount * scale), unit))
    return values


def _number_values(value: Any) -> set[float]:
    text = str(value or "")
    values = set()
    for match in re.finditer(r"(?<![\d,])(\d[\d,]*(?:\.\d+)?)\s*(만|억)?", text):
        amount = float(match.group(1).replace(",", ""))
        scale = {"만": 10_000, "억": 100_000_000}.get(match.group(2), 1)
        values.add(amount * scale)
    return values


def _percentage_values(value: Any) -> set[float]:
    return {
        float(match.group(1))
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", str(value or ""))
    }


def _boolean_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    compact = _compact(value)
    if compact in {"true", "yes", "예", "적용", "포함", "가능"}:
        return True
    if compact in {"false", "no", "아니오", "미적용", "제외", "불가"}:
        return False
    negative = ("않", "미적용", "제외", "불가", "없", "아니")
    positive = ("적용됩니다", "포함됩니다", "가능합니다", "수정됩니다")
    if any(marker in compact for marker in negative):
        return False
    if any(marker in compact for marker in positive):
        return True
    return None


def _expected_currency(value: Any) -> tuple[int, str] | None:
    if not isinstance(value, dict):
        parsed = _currency_values(value)
        return next(iter(parsed)) if len(parsed) == 1 else None
    amount = value.get("amount")
    unit = str(value.get("unit") or "").casefold()
    if not isinstance(amount, (int, float)) or unit not in _CURRENCY_UNITS:
        return None
    return int(amount), _CURRENCY_UNITS[unit]


def value_present(expected: Any, value_type: str, observed: Any, *, as_of: str) -> bool:
    if value_type == "boolean" or isinstance(expected, bool):
        return _boolean_value(expected) is not None and _boolean_value(expected) == _boolean_value(
            observed
        )
    if isinstance(expected, dict):
        amount = expected.get("amount")
        unit = _compact(expected.get("unit"))
        return (
            isinstance(amount, (int, float))
            and float(amount) in _number_values(observed)
            and bool(unit)
            and unit in _compact(observed)
        )
    if value_type in {"currency", "price"}:
        normalized = _expected_currency(expected)
        return normalized is not None and normalized in _currency_values(observed)
    if value_type == "percentage":
        expected_values = (
            {float(expected)}
            if isinstance(expected, (int, float))
            else _percentage_values(expected) or _number_values(expected)
        )
        return bool(expected_values) and expected_values <= _percentage_values(observed)
    if value_type == "number" or isinstance(expected, (int, float)):
        return float(expected) in _number_values(observed)

    expected_text = str(expected)
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2})?", expected_text):
        expected_date = expected_text[:10]
        expected_time = expected_text[11:16]
        return expected_date in _date_values(observed, as_of=as_of) and expected_time in _time_values(
            observed
        )
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", expected_text):
        return expected_text in _date_values(observed, as_of=as_of)
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", expected_text):
        return expected_text in _time_values(observed)

    compact_expected = _compact(expected_text)
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
    citation_start = int(citation.get("start_char") or 0)
    citation_end = int(citation.get("end_char") or 0)
    overlaps = citation_start < unit["end_char"] and unit["start_char"] < citation_end
    return overlaps or (
        value_present(expected, value_type, citation.get("text", ""), as_of=as_of)
        and value_present(expected, value_type, unit["text"], as_of=as_of)
    )


_STRICT_VALUE_TYPES = {
    "boolean",
    "currency",
    "date",
    "date_range",
    "datetime",
    "number",
    "percentage",
    "price",
}


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
                units = requirement["acceptable_evidence_units"]
                value_hits = []
                for value_index, value in enumerate(values):
                    matching_units = [
                        unit
                        for unit in units
                        if value_present(
                            value,
                            requirement["value_type"],
                            unit["text"],
                            as_of=sealed["as_of"],
                        )
                    ]
                    if not matching_units and len(units) == len(values):
                        matching_units = [units[value_index]]
                    elif not matching_units:
                        matching_units = units
                    value_hits.append(
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
            false_full = not expected_supported and exposed_supported
            requirement_scores.append(
                {
                    "requirement_id": requirement_id,
                    "expected_status": requirement["expected_status"],
                    "exposed_status": decision.get("status"),
                    "model_status": audit.get("model_status"),
                    "gold_value_complete": value_complete,
                    "evidence_span_hit": evidence_complete,
                    "citation_slices_exact": citation_slices_exact,
                    "false_full": false_full,
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
        if gold_complete:
            outcome = "correct"
        elif supported_exposed == 0:
            outcome = "no_response"
        else:
            outcome = "incorrect"
        false_full = any(row["false_full"] for row in requirement_scores)
        unsupported_expected = any(
            row["expected_status"] == "unsupported" for row in requirement_scores
        )
        generation_error = bool(
            run["verified_output"]["verification"].get("generation_error")
        )
        candidate_pools = run.get("requirement_candidate_chunk_ids") or []
        candidate_complete = all(
            bool(
                set(candidate_pools[index])
                & {
                    unit["chunk_id"]
                    for unit in requirement["acceptable_evidence_units"]
                }
            )
            for index, requirement in enumerate(sealed["requirements"])
            if requirement["expected_status"] == "supported"
        )
        holdout_score = {
            "slot_ordinal": sealed["slot_ordinal"],
            "outcome": outcome,
            "gold_value_complete": gold_complete,
            "all_evidence_spans_hit": bool(supported_scores)
            and all(row["evidence_span_hit"] for row in supported_scores),
            "candidate_all_gold_covered": candidate_complete,
            "all_citation_slices_exact": all(
                row["citation_slices_exact"] for row in requirement_scores
            ),
            "has_unsupported_requirement": unsupported_expected,
            "false_full": false_full,
            "honest_unsupported_abstention": unsupported_expected and not false_full,
            "generation_error": generation_error,
            "requirement_scores": requirement_scores,
        }
        if false_full:
            failure_stage = "unsupported_false_full"
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
            failure_stage = "verifier_overreject"
        elif outcome == "no_response":
            failure_stage = "generator_abstain"
        else:
            failure_stage = "generator_value_selection"
        holdout_score["failure_stage"] = failure_stage
        scored_rows.append({**run, "holdout_score": holdout_score})

    total = len(scored_rows)
    outcome_counts = Counter(row["holdout_score"]["outcome"] for row in scored_rows)
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
        "outcomes": {
            "correct": outcome_counts["correct"],
            "incorrect": outcome_counts["incorrect"],
            "no_response": outcome_counts["no_response"],
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
            "false_full": row["holdout_score"]["false_full"],
        }
        for row in failure_rows
    ]
    summary["gates"] = {
        "generation_error_zero": summary["generation_error_count"] == 0,
        "honest_unsupported_false_full_zero": summary["honest_unsupported"]["false_full"]
        == 0,
    }
    return scored_rows, summary
