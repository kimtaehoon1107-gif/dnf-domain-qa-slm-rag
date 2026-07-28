from __future__ import annotations

import copy
import re
import time
from typing import Any


ATTRIBUTE_GROUPS = {
    "price": {
        "question": ("가격", "판매가"),
        "evidence": ("가격", "판매가"),
    },
    "purchase_limit": {
        "question": ("구매 제한", "구매제한", "구매 가능 횟수"),
        "evidence": ("구매 제한", "구매제한", "구매 가능 횟수", "구매횟수"),
    },
    "trade_type": {
        "question": ("거래 타입", "거래타입", "거래 유형", "거래유형"),
        "evidence": ("거래 타입", "거래타입", "거래 유형", "거래유형"),
    },
    "duration": {
        "question": ("사용 기간", "사용기간", "기간 제한", "기간제한"),
        "evidence": ("사용 기간", "사용기간", "기간 제한", "기간제한"),
    },
    "deletion_at": {
        "question": ("삭제 시각", "삭제시각", "삭제일", "삭제 일시"),
        "evidence": ("삭제 시각", "삭제시각", "삭제일", "삭제 일시"),
    },
}

ROW_SUBJECT_ATTRIBUTES = {
    "아바타부위",
    "아이템명칭",
    "아이템명",
    "상품명",
    "판매목록",
    "판매물품",
}
_QUERY_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_QUERY_STOPWORDS = {
    "각각",
    "게임",
    "기준",
    "알려줘",
    "어디",
    "언제",
    "얼마",
    "있어",
    "하는",
}


def compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def select_exact_query_window(
    text: Any,
    *,
    question: str,
    max_chars: int,
    title: str = "",
) -> str:
    """Select a query-relevant exact source slice without synthetic ellipses."""

    source = str(text or "")
    if max_chars <= 0:
        return ""
    if len(source) <= max_chars:
        return source
    terms = {
        token.casefold()
        for token in _QUERY_TOKEN.findall(question)
        if len(token) >= 2 and token.casefold() not in _QUERY_STOPWORDS
    }
    title_text = str(title or "").casefold()
    non_title_terms = {term for term in terms if term not in title_text}
    if non_title_terms:
        terms = non_title_terms
    stride = max(1, max_chars // 2)
    starts = list(range(0, len(source) - max_chars + 1, stride))
    final_start = len(source) - max_chars
    if not starts or starts[-1] != final_start:
        starts.append(final_start)
    scored = []
    for start in starts:
        window = source[start : start + max_chars]
        lowered = window.casefold()
        matches = [term for term in terms if term in lowered]
        score = sum(len(term) * len(term) for term in matches)
        scored.append((score, len(matches), -start, start))
    start = max(scored)[-1]
    return source[start : start + max_chars]


def _recompute_exposure(result: dict[str, Any]) -> dict[str, Any]:
    requirements = result.get("requirements") or []
    supported = [
        row for row in requirements if row.get("status") == "supported_exact"
    ]
    if not supported:
        response_mode = "abstain"
    elif len(supported) == len(requirements):
        response_mode = "full_answer"
    else:
        response_mode = "partial_answer"
    result["response_mode"] = response_mode
    result["rendered_answer"] = "\n".join(
        f"- {row['answer']} "
        + " ".join(
            f"[{citation['chunk_id']}]"
            for citation in row.get("citations", [])
        )
        for row in supported
    )
    return result


def _block_requirement(
    result: dict[str, Any],
    *,
    requirement_index: int,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    requirement = next(
        row
        for row in result.get("requirements", [])
        if int(row["requirement_index"]) == requirement_index
    )
    requirement["status"] = "unsupported"
    requirement["answer"] = ""
    requirement["citations"] = []
    audits = result.setdefault("verification", {}).setdefault(
        "requirements", []
    )
    audit = next(
        (
            row
            for row in audits
            if int(row["requirement_index"]) == requirement_index
        ),
        None,
    )
    if audit is None:
        audit = {
            "requirement_index": requirement_index,
            "model_status": "supported",
            "exposed_status": "unsupported",
            "failure_reasons": [],
        }
        audits.append(audit)
    audit["exposed_status"] = "unsupported"
    reasons = audit.setdefault("failure_reasons", [])
    if reason not in reasons:
        reasons.append(reason)
    if details:
        audit.setdefault("guard_details", {})[reason] = details
    result["verification"]["raw_output_passed_without_sanitization"] = False


def build_table_rows_by_chunk(
    table_facts: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in table_facts:
        chunk_id = str(fact["source_chunk_id"])
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        start = int(fact["start_offset"])
        end = int(fact["end_offset"])
        row_text = str(fact["row_text"])
        if chunk["display_text"][start:end] != row_text:
            raise RuntimeError(
                f"table fact is not an exact chunk slice: {fact['row_id']}"
            )
        row = rows.setdefault(
            (chunk_id, str(fact["row_id"])),
            {
                "row_id": str(fact["row_id"]),
                "start_char": start,
                "end_char": end,
                "row_text": row_text,
                "facts": [],
            },
        )
        row["facts"].append(
            {
                "subject": fact.get("subject"),
                "attribute": str(fact.get("attribute") or ""),
                "value": str(fact.get("value") or ""),
            }
        )
    output: dict[str, list[dict[str, Any]]] = {}
    for (chunk_id, _), row in rows.items():
        output.setdefault(chunk_id, []).append(row)
    for chunk_rows in output.values():
        chunk_rows.sort(key=lambda row: (row["start_char"], row["row_id"]))
    return output


def requested_attribute_group(text: str) -> str | None:
    normalized = compact(text)
    matches = [
        group
        for group, aliases in ATTRIBUTE_GROUPS.items()
        if any(compact(alias) in normalized for alias in aliases["question"])
    ]
    return matches[0] if len(matches) == 1 else None


def evidence_attribute_group(attribute: str) -> str | None:
    normalized = compact(attribute)
    matches = [
        group
        for group, aliases in ATTRIBUTE_GROUPS.items()
        if any(compact(alias) in normalized for alias in aliases["evidence"])
    ]
    return matches[0] if len(matches) == 1 else None


def _row_subject_matches_question(
    row: dict[str, Any],
    question: str,
) -> bool | None:
    question_key = compact(question)
    candidates = {
        compact(fact.get("value"))
        for fact in row.get("facts", [])
        if compact(fact.get("attribute")) in ROW_SUBJECT_ATTRIBUTES
        and len(compact(fact.get("value"))) >= 2
    }
    if not candidates:
        return None
    return any(candidate in question_key for candidate in candidates)


def apply_table_attribute_identity_guard(
    result: dict[str, Any],
    *,
    question: str,
    table_rows_by_chunk: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Reject a table value when it belongs to a different requested column."""

    guarded = copy.deepcopy(result)
    for requirement in guarded.get("requirements", []):
        if requirement.get("status") != "supported_exact":
            continue
        question_part = str(requirement.get("question_part") or "").strip()
        group = requested_attribute_group(question_part or question)
        if group is None:
            continue
        answer_key = compact(requirement.get("answer"))
        matching_facts = []
        for citation in requirement.get("citations") or []:
            chunk_id = str(citation.get("chunk_id") or "")
            citation_start = int(citation.get("start_char") or 0)
            citation_end = int(citation.get("end_char") or 0)
            for row in table_rows_by_chunk.get(chunk_id, []):
                if (
                    citation_end <= int(row["start_char"])
                    or citation_start >= int(row["end_char"])
                ):
                    continue
                subject_match = _row_subject_matches_question(row, question)
                if subject_match is False:
                    continue
                for fact in row.get("facts", []):
                    value_key = compact(fact.get("value"))
                    if not value_key:
                        continue
                    if value_key in answer_key or answer_key in value_key:
                        matching_facts.append(
                            {
                                "row_id": row["row_id"],
                                "subject_match": subject_match,
                                "attribute": fact["attribute"],
                                "attribute_group": evidence_attribute_group(
                                    fact["attribute"]
                                ),
                                "value": fact["value"],
                            }
                        )
        if not matching_facts:
            continue
        if any(fact["attribute_group"] == group for fact in matching_facts):
            continue
        _block_requirement(
            guarded,
            requirement_index=int(requirement["requirement_index"]),
            reason="table_attribute_identity_mismatch",
            details={
                "requested_attribute_group": group,
                "matched_facts": matching_facts,
            },
        )
    return _recompute_exposure(guarded)


def select_query_table_rows(
    table_rows_by_chunk: dict[str, list[dict[str, Any]]],
    *,
    question: str,
) -> dict[str, list[dict[str, Any]]]:
    """Select exact table rows whose subject and requested column match."""

    group = requested_attribute_group(question)
    if group is None:
        return {}
    selected = {}
    for chunk_id, rows in table_rows_by_chunk.items():
        matched = []
        for row in rows:
            if _row_subject_matches_question(row, question) is not True:
                continue
            if not any(
                evidence_attribute_group(fact.get("attribute", "")) == group
                for fact in row.get("facts", [])
            ):
                continue
            matched.append(row)
        if matched:
            selected[chunk_id] = matched
    return selected


def recover_unique_whitespace_quotes(
    raw_output: dict[str, Any],
    *,
    candidate_chunk_ids: list[str],
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Restore only a unique whitespace-normalized quote to its exact slice."""

    recovered = copy.deepcopy(raw_output)
    audit = []
    candidate_ref_to_chunk_id = {
        str(index): chunk_id
        for index, chunk_id in enumerate(candidate_chunk_ids, 1)
    }
    for requirement_index, requirement in enumerate(
        recovered.get("requirements") or [],
        1,
    ):
        for evidence_index, evidence in enumerate(
            requirement.get("evidence") or [],
            1,
        ):
            chunk_id = candidate_ref_to_chunk_id.get(
                str(evidence.get("candidate_ref") or "")
            )
            chunk = chunks_by_id.get(str(chunk_id or ""))
            quote = str(evidence.get("quote") or "")
            if chunk is None or not quote:
                continue
            source_text = str(chunk.get("display_text") or "")
            if source_text.find(quote) >= 0:
                continue
            source_positions = [
                index
                for index, char in enumerate(source_text)
                if not char.isspace()
            ]
            normalized_source = "".join(
                source_text[index] for index in source_positions
            )
            normalized_quote = "".join(quote.split())
            normalized_start = normalized_source.find(normalized_quote)
            if (
                not normalized_quote
                or normalized_start < 0
                or normalized_source.find(
                    normalized_quote,
                    normalized_start + 1,
                )
                >= 0
            ):
                continue
            start = source_positions[normalized_start]
            end = (
                source_positions[
                    normalized_start + len(normalized_quote) - 1
                ]
                + 1
            )
            evidence["quote"] = source_text[start:end]
            audit.append(
                {
                    "requirement_index": requirement_index,
                    "evidence_index": evidence_index,
                    "chunk_id": chunk_id,
                    "start_char": start,
                    "end_char": end,
                }
            )
    return recovered, audit


_FULL_DATE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*(?:년|[./-])\s*"
    r"(?P<month>\d{1,2})\s*(?:월|[./-])\s*"
    r"(?P<day>\d{1,2})\s*일?"
)
_MONTH_DAY = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})\s*(?:월|[./])\s*"
    r"(?P<day>\d{1,2})\s*일?"
)
_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*년?")
_CLOCK_COLON = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?!\d)"
)
_CLOCK_KOREAN = re.compile(
    r"(?:(?P<ampm>오전|오후)\s*)?"
    r"(?P<hour>[01]?\d|2[0-3])\s*시"
    r"(?:\s*(?P<minute>[0-5]?\d)\s*분)?"
)
_NUMBER_UNIT = re.compile(
    r"(?<![\d,])(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|퍼센트|골드|세라|마일리지|포인트|개월|개|회|번|명|"
    r"일|년|주|시간|분|초|원|위|레벨|lv|gb|mb|kb)",
    re.IGNORECASE,
)


def _date_values(value: Any) -> set[tuple[int, int, int]]:
    return {
        (
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
        for match in _FULL_DATE.finditer(str(value or ""))
    }


def _month_day_values(value: Any) -> set[tuple[int, int]]:
    text = str(value or "")
    occupied = [
        (match.start(), match.end()) for match in _FULL_DATE.finditer(text)
    ]
    return {
        (int(match.group("month")), int(match.group("day")))
        for match in _MONTH_DAY.finditer(text)
        if not any(
            match.start() < end and match.end() > start
            for start, end in occupied
        )
    }


def _year_values(value: Any) -> set[int]:
    return {int(match.group(1)) for match in _YEAR.finditer(str(value or ""))}


def _time_values(value: Any) -> set[str]:
    text = str(value or "")
    values = {
        f"{int(match.group('hour')):02d}:{int(match.group('minute')):02d}"
        for match in _CLOCK_COLON.finditer(text)
    }
    for match in _CLOCK_KOREAN.finditer(text):
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        if match.group("ampm") == "오전" and hour == 12:
            hour = 0
        elif match.group("ampm") == "오후" and hour < 12:
            hour += 12
        values.add(f"{hour:02d}:{minute:02d}")
    return values


def _number_unit_values(value: Any) -> set[tuple[float, str]]:
    text_chars = list(str(value or "").casefold())
    text = "".join(text_chars)
    for pattern in (_FULL_DATE, _MONTH_DAY):
        for match in pattern.finditer(text):
            text_chars[match.start() : match.end()] = (
                " " for _ in range(match.end() - match.start())
            )
    values = set()
    for match in _NUMBER_UNIT.finditer("".join(text_chars)):
        number = float(match.group("number").replace(",", ""))
        unit = match.group("unit").casefold()
        if unit == "퍼센트":
            unit = "%"
        values.add((number, unit))
    return values


def factual_values_supported(
    answer: str,
    evidence_context: str,
    *,
    context_years: set[int] | None = None,
) -> bool:
    answer_dates = _date_values(answer)
    evidence_dates = _date_values(evidence_context)
    evidence_month_days = _month_day_values(evidence_context)
    evidence_years = _year_values(evidence_context) | set(context_years or ())
    if any(
        date not in evidence_dates
        and (
            (date[1], date[2]) not in evidence_month_days
            or date[0] not in evidence_years
        )
        for date in answer_dates
    ):
        return False
    answer_month_days = _month_day_values(answer)
    full_month_days = {(month, day) for _, month, day in evidence_dates}
    if not answer_month_days <= (evidence_month_days | full_month_days):
        return False
    answer_times = _time_values(answer)
    if not answer_times <= _time_values(evidence_context):
        return False
    answer_number_units = _number_unit_values(answer)
    evidence_number_units = _number_unit_values(evidence_context)
    if not answer_number_units <= evidence_number_units:
        return False
    return True


def enforce_normalized_factual_support(
    result: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate normalized factual values while preserving exact citations."""

    checked = copy.deepcopy(result)
    for requirement in list(checked.get("requirements") or []):
        if requirement.get("status") != "supported_exact":
            continue
        evidence_texts = []
        context_years = set()
        for citation in requirement.get("citations") or []:
            chunk = chunks_by_id.get(str(citation.get("chunk_id") or ""), {})
            document_id = str(
                citation.get("parent_document_id")
                or chunk.get("parent_document_id")
                or ""
            )
            document = documents_by_id.get(document_id, {})
            evidence_texts.append(str(citation.get("text") or ""))
            context_years.update(
                _year_values(
                    "\n".join(
                        (
                            str(document.get("title") or ""),
                            str(document.get("published_at") or ""),
                        )
                    )
                )
            )
        if factual_values_supported(
            str(requirement.get("answer") or ""),
            "\n".join(evidence_texts),
            context_years=context_years,
        ):
            continue
        _block_requirement(
            checked,
            requirement_index=int(requirement["requirement_index"]),
            reason="normalized_factual_values_not_in_evidence",
        )
    checked.setdefault("verification", {})[
        "normalized_factual_value_check"
    ] = True
    return _recompute_exposure(checked)


def normalized_route_scope(route_scope: Any) -> str | None:
    value = str(route_scope or "")
    if value in {"current", "historical", "comparison"}:
        return value
    if value == "mixed":
        return "comparison"
    return None


def apply_server_scope_agreement_guard(
    result: dict[str, Any],
    *,
    model_scope: Any,
    route_scope: Any,
) -> dict[str, Any]:
    """Fail closed when the model tries to replace the server time scope."""

    guarded = copy.deepcopy(result)
    expected = normalized_route_scope(route_scope)
    actual = str(model_scope or "")
    if expected is None or actual == expected:
        return guarded
    for requirement in list(guarded.get("requirements") or []):
        if requirement.get("status") != "supported_exact":
            continue
        _block_requirement(
            guarded,
            requirement_index=int(requirement["requirement_index"]),
            reason="model_server_time_scope_disagreement",
            details={
                "model_scope": actual,
                "server_scope": expected,
            },
        )
    return _recompute_exposure(guarded)


class ObservedGroundedGenerator:
    """Drop-in local generator that preserves raw structured output metadata."""

    def __init__(
        self,
        *,
        output_schema: Any,
        system_instructions: str,
        max_tokens: int = 4000,
    ) -> None:
        self.output_schema = output_schema
        self.system_instructions = system_instructions
        self.max_tokens = max_tokens
        self.last: dict[str, Any] = {}

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        usage = response.usage
        input_tokens = int(usage.prompt_tokens or 0)
        output_tokens = int(usage.completion_tokens or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(
                usage.total_tokens or input_tokens + output_tokens
            ),
        }

    def __call__(
        self,
        *,
        prompt: str,
        model: str,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        from openai import OpenAI, __version__ as sdk_version

        self.last = {
            "prompt_chars": len(prompt),
            "requested_max_tokens": self.max_tokens,
        }
        client = OpenAI(max_retries=2, timeout=timeout_seconds)
        started = time.perf_counter()
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_instructions,
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format=self.output_schema,
                temperature=0,
                max_tokens=self.max_tokens,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Model returned no parsed structured output")
            usage = self._usage(response)
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            self.last.update(
                {
                    "output": parsed.model_dump(),
                    "finish_reason": response.choices[0].finish_reason,
                    "returned_model": response.model,
                    "usage": usage,
                    "latency_ms": latency_ms,
                    "error": None,
                }
            )
            return {
                "output": parsed.model_dump(),
                "requested_model": model,
                "returned_model": response.model,
                "openai_sdk_version": sdk_version,
                "usage": usage,
                "latency_ms": latency_ms,
                "provider": "ollama_openai_compatible",
            }
        except Exception as exc:
            self.last.update(
                {
                    "finish_reason": (
                        "length"
                        if "length limit was reached" in str(exc)
                        else None
                    ),
                    "latency_ms": round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
