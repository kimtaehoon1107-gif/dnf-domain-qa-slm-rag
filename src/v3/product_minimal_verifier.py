from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.v3.simple_rag_minimal_verifier import factual_values_supported
from src.v3.product_evidence_pack import (
    explicit_question_clauses,
    kiwi_independent_requirement_queries,
)


_ALLOWED_MODES = {"answer", "partial", "clarification", "unsupported"}
_UNSUPPORTED_LANGUAGE = (
    "확인할 수 없습니다",
    "알 수 없습니다",
    "근거가 없습니다",
    "정보가 없습니다",
    "근거 부족",
    "확인되지 않습니다",
    "제공되지 않았",
    "명시되지 않았",
)
_COMPLETE_CUES = ("전부", "전체", "목록")
_MIN_ATOMIC_EVIDENCE_RELEVANCE = 0.1
_NON_BLOCKING_REJECTION_REASONS = {
    "claim_does_not_address_question_surface",
    "evidence_relevance_below_threshold",
}
_NUMBER = re.compile(
    r"(?<![0-9A-Za-z])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![0-9A-Za-z])"
)
_CLOCK_COLON = re.compile(
    r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)"
)
_CLOCK_KOREAN = re.compile(
    r"(?:(?:오전|오후)\s*)?"
    r"(?<!\d)(?:[01]?\d|2[0-3])\s*시"
    r"(?:\s*[0-5]?\d\s*분)?"
)
_KOREAN_SCALED_NUMBER = re.compile(
    r"(?<!\d)(?P<number>\d+(?:\.\d+)?)\s*"
    r"(?P<scale>천|만)\s*"
    r"(?P<unit>원|골드|세라|포인트)"
)
_KOREAN_QUANTIFIED_VALUE = re.compile(
    r"(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:개|회|번|개월|년|일|시간|분|초|명|원)"
)
_MILEAGE_M_VALUE = re.compile(
    r"(?<![0-9A-Za-z])(?P<number>\d+(?:\.\d+)?)\s*M(?![A-Za-z])",
    re.IGNORECASE,
)
_NUMERIC_QUESTION = re.compile(r"(?:몇|얼마)")
_BINARY_QUESTION = re.compile(
    r"(?:수\s*있|가능(?:해|한|하|했|했어|합니까)|"
    r"되(?:어|는|나|나요)|됐(?:어|나|나요|습니까)?|"
    r"있(?:었어|었나|었나요|어|나요|습니까)?|맞아|적용)"
)
_BINARY_ANSWER = re.compile(
    r"(?:수\s*(?:있|없)|가능|불가|어렵|되지\s*않|"
    r"있지\s*않|없(?:다|습니다)?|할\s*수\s*없|"
    r"동일하게\s*적용|적용(?:됩니다|된다|돼요)|맞(?:다|습니다))"
)
_YEAR_MONTH = re.compile(r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월")
_FULL_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)
_ISO_DATE = re.compile(
    r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)"
)
_SLASH_MONTH_DAY = re.compile(
    r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)"
)
_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*년")
_MONTH = re.compile(r"(?<!\d)(\d{1,2})\s*월")
_REVISION = re.compile(
    r"(?:revision|rev(?:ision)?|개정)\s*[:#-]?\s*([0-9A-Za-z._-]+)",
    re.IGNORECASE,
)
_STATUS_ALIASES = {
    "current": ("current", "현재", "진행 중"),
    "expired": ("expired", "만료", "종료"),
}
_PROCESSING_DURATION_CLAIM = re.compile(
    r"(?:처리|소요)\s*(?:기간|시간)"
)
_PROCESSING_DURATION_EVIDENCE = re.compile(
    r"(?:처리|소요|완료|걸리|영업\s*일)"
)
_ABSENCE_CLAIM = re.compile(
    r"(?:제한|기한|횟수|수량|조건|항목|종류)"
    r"[^.\n]{0,30}"
    r"(?:존재하지\s*않|없(?:다|습니다|었)|무제한|정해져\s*있지\s*않)"
)
_ABSENCE_EVIDENCE = re.compile(
    r"(?:없음|없다|없습니다|존재하지\s*않|무제한|"
    r"제한\s*없|기한\s*없|정해져\s*있지\s*않)"
)


def _compact(value: Any) -> str:
    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(value or "").casefold(),
    )


def _compact_tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(
            r"[0-9A-Za-z가-힣]+",
            str(value or ""),
        )
        if len(token) >= 2
    }


def _surface_fragments(value: Any) -> set[str]:
    compact = _compact(value)
    return {
        compact[index : index + size]
        for size in (2, 3)
        for index in range(max(0, len(compact) - size + 1))
    }


def _subjectless_surface(
    value: Any,
    requested_subjects: list[str],
) -> str:
    text = str(value or "")
    for subject in sorted(requested_subjects, key=len, reverse=True):
        text = re.sub(re.escape(subject), " ", text, flags=re.IGNORECASE)
    for pattern in (
        _FULL_DATE,
        _YEAR_MONTH,
        _ISO_DATE,
        _SLASH_MONTH_DAY,
        _REVISION,
    ):
        text = pattern.sub(" ", text)
    return text


def _surface_overlap(left: str, right: str) -> bool:
    return bool(
        _compact_tokens(left) & _compact_tokens(right)
        or _surface_fragments(left) & _surface_fragments(right)
    )


def _claim_addresses_question_surface(
    question: str,
    claim_text: str,
    evidence_context: str,
    *,
    requested_subjects: list[str],
) -> bool:
    if not requested_subjects:
        return True
    question_surface = _subjectless_surface(
        question,
        requested_subjects,
    )
    if not _compact(question_surface):
        return True
    claim_surface = _subjectless_surface(
        claim_text,
        requested_subjects,
    )
    evidence_surface = _subjectless_surface(
        evidence_context,
        requested_subjects,
    )
    return (
        _surface_overlap(question_surface, claim_surface)
        and _surface_overlap(question_surface, evidence_surface)
    )


def _evidence_relevance_supported(
    selected_units: list[dict[str, Any]],
) -> bool:
    scores = [
        float(unit["question_relevance_score"])
        for unit in selected_units
        if unit.get("question_relevance_score") is not None
    ]
    return bool(
        not scores or max(scores) >= _MIN_ATOMIC_EVIDENCE_RELEVANCE
    )


def _claim_relation_role_supported(
    claim_text: str,
    selected_units: list[dict[str, Any]],
) -> bool:
    if _PROCESSING_DURATION_CLAIM.search(claim_text) is None:
        return True
    direct_evidence = "\n".join(
        " ".join(
            (
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
        )
        for unit in selected_units
    )
    return _PROCESSING_DURATION_EVIDENCE.search(direct_evidence) is not None


_NORMATIVE_QUESTION = re.compile(
    r"(?:추천|권장|어떤\s+.+(?:좋|나아)|뭐가\s+.+(?:좋|나아)|\bbest\b)",
    re.IGNORECASE,
)
_NORMATIVE_EVIDENCE = re.compile(
    r"(?:추천|권장|적합|유리|효율적|\bbest\b|\brecommend(?:ed|ation)?\b)",
    re.IGNORECASE,
)


def _normative_relation_supported(
    question: str,
    selected_units: list[dict[str, Any]],
) -> bool:
    if _NORMATIVE_QUESTION.search(question) is None:
        return True
    direct_evidence = "\n".join(
        " ".join(
            (
                str(unit.get("title") or ""),
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
        )
        for unit in selected_units
    )
    return _NORMATIVE_EVIDENCE.search(direct_evidence) is not None


def _negative_absence_claim_supported(
    claim_text: str,
    selected_units: list[dict[str, Any]],
) -> bool:
    if _ABSENCE_CLAIM.search(claim_text) is None:
        return True
    evidence = " ".join(
        " ".join(
            (
                str(unit.get("title") or ""),
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
        )
        for unit in selected_units
    )
    return _ABSENCE_EVIDENCE.search(evidence) is not None


def _canonical_number(value: str) -> str:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return value.replace(",", "")
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _mask_matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    characters = list(text)
    for pattern in patterns:
        for match in pattern.finditer(text):
            characters[match.start() : match.end()] = " " * (
                match.end() - match.start()
            )
    return "".join(characters)


def _scaled_numeric_values(value: Any) -> set[str]:
    factors = {"천": Decimal(1000), "만": Decimal(10000)}
    return {
        _canonical_number(
            str(
                Decimal(match.group("number"))
                * factors[match.group("scale")]
            )
        )
        for match in _KOREAN_SCALED_NUMBER.finditer(str(value or ""))
    }


def _numeric_values(value: Any) -> set[str]:
    text = str(value or "")
    masked = _mask_matches(
        text,
        (_CLOCK_COLON, _CLOCK_KOREAN, _KOREAN_SCALED_NUMBER),
    )
    return {
        _canonical_number(match.group(0))
        for match in _NUMBER.finditer(masked)
    } | _scaled_numeric_values(text) | {
        _canonical_number(match.group("number"))
        for match in _MILEAGE_M_VALUE.finditer(text)
    }


def _normalize_scaled_number_units(value: Any) -> str:
    factors = {"천": Decimal(1000), "만": Decimal(10000)}

    def replace(match: re.Match[str]) -> str:
        normalized = _canonical_number(
            str(
                Decimal(match.group("number"))
                * factors[match.group("scale")]
            )
        )
        return f"{normalized}{match.group('unit')}"

    normalized = _KOREAN_SCALED_NUMBER.sub(replace, str(value or ""))
    return _MILEAGE_M_VALUE.sub(
        lambda match: f"{match.group('number')}마일리지",
        normalized,
    )


def _normalized_factual_values_supported(
    answer: str,
    evidence_context: str,
) -> bool:
    return factual_values_supported(
        _normalize_scaled_number_units(answer),
        _normalize_scaled_number_units(evidence_context),
    )


def _claim_clause_relevance_score(
    claim_text: str,
    clause: str,
    other_clauses: list[str],
) -> tuple[int, int, int]:
    other_tokens = set().union(
        *(_compact_tokens(other) for other in other_clauses)
    )
    unique_tokens = _compact_tokens(clause) - other_tokens
    claim_tokens = _compact_tokens(claim_text)

    other_fragments = set().union(
        *(_surface_fragments(other) for other in other_clauses)
    )
    unique_fragments = _surface_fragments(clause) - other_fragments
    claim_fragments = _surface_fragments(claim_text)
    fragment_overlap = unique_fragments & claim_fragments
    return (
        sum(len(token) ** 2 for token in unique_tokens & claim_tokens),
        sum(len(fragment) == 3 for fragment in fragment_overlap),
        sum(len(fragment) == 2 for fragment in fragment_overlap),
    )


def _required_factual_value_present(question: str, claim_text: str) -> bool:
    if _NUMERIC_QUESTION.search(question) is None:
        return True
    if (
        _numeric_values(claim_text)
        or _CLOCK_COLON.search(claim_text)
        or _CLOCK_KOREAN.search(claim_text)
        or _KOREAN_QUANTIFIED_VALUE.search(claim_text)
    ):
        return True

    clauses = kiwi_independent_requirement_queries(question)
    if len(clauses) < 2:
        clauses = explicit_question_clauses(question)
    if len(clauses) < 2:
        return False

    scores = [
        _claim_clause_relevance_score(
            claim_text,
            clause,
            [
                other
                for index, other in enumerate(clauses)
                if index != clause_index
            ],
        )
        for clause_index, clause in enumerate(clauses)
    ]
    best_score = max(scores)
    if best_score == (0, 0, 0):
        return False
    best_clauses = [
        clause for clause, score in zip(clauses, scores) if score == best_score
    ]
    return all(
        _NUMERIC_QUESTION.search(clause) is None for clause in best_clauses
    )


def _verified_binary_answer(question: str, claims: list[dict[str, Any]]) -> bool:
    return bool(
        len(explicit_question_clauses(question)) == 1
        and len(claims) == 1
        and _BINARY_QUESTION.search(question)
        and _BINARY_ANSWER.search(str(claims[0].get("text") or ""))
    )


def _condition_values(value: Any) -> dict[str, set[Any]]:
    text = str(value or "")
    year_months = {
        (int(match.group(1)), int(match.group(2)))
        for match in _YEAR_MONTH.finditer(text)
    }
    iso_dates = {
        date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        for match in _ISO_DATE.finditer(text)
    }
    full_dates = {
        date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        for match in _FULL_DATE.finditer(text)
    }
    all_dates = iso_dates | full_dates
    year_months.update(
        (value.year, value.month) for value in all_dates
    )
    return {
        "dates": all_dates,
        "year_months": year_months,
        "years": {
            int(match.group(1)) for match in _YEAR.finditer(text)
        }
        | {value.year for value in all_dates},
        "months": {
            int(match.group(1)) for match in _MONTH.finditer(text)
        }
        | {value.month for value in all_dates},
        "revisions": {
            match.group(1).casefold()
            for match in _REVISION.finditer(text)
        },
    }


def _date_in_unit(
    requested: date,
    unit: dict[str, Any],
) -> bool:
    valid_from = str(unit.get("valid_from") or "")
    valid_to = str(unit.get("valid_to") or "")
    try:
        lower = date.fromisoformat(valid_from) if valid_from else None
        upper = date.fromisoformat(valid_to) if valid_to else None
    except ValueError:
        return False
    return (
        (lower is None or lower <= requested)
        and (upper is None or requested <= upper)
        and (lower is not None or upper is not None)
    )


def _explicit_conditions_match(
    question: str,
    evidence: str,
    *,
    selected_units: list[dict[str, Any]],
) -> bool:
    requested = _condition_values(question)
    available = _condition_values(evidence)
    if not all(
        requested_date in available["dates"]
        or any(
            requested_date.month == int(match.group(1))
            and requested_date.day == int(match.group(2))
            for match in _SLASH_MONTH_DAY.finditer(evidence)
        )
        or any(
            _date_in_unit(requested_date, unit)
            for unit in selected_units
        )
        for requested_date in requested["dates"]
    ):
        return False
    if not requested["year_months"] <= available["year_months"]:
        return False
    if not requested["years"] <= available["years"]:
        return False
    if not requested["months"] <= available["months"]:
        return False
    if not requested["revisions"] <= available["revisions"]:
        return False
    return True


def _matching_explicit_condition_evidence(
    question: str,
    citations: list[dict[str, Any]],
    selected_units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    requested = _condition_values(question)
    if not any(requested.values()):
        return citations, selected_units, []
    matching = [
        (citation, unit)
        for citation, unit in zip(citations, selected_units, strict=True)
        if _explicit_conditions_match(
            question,
            _unit_evidence_context(unit),
            selected_units=[unit],
        )
    ]
    if not matching:
        return citations, selected_units, []
    kept_refs = {
        str(citation["evidence_ref"]) for citation, _ in matching
    }
    pruned_refs = [
        str(citation["evidence_ref"])
        for citation in citations
        if str(citation["evidence_ref"]) not in kept_refs
    ]
    return (
        [citation for citation, _ in matching],
        [unit for _, unit in matching],
        pruned_refs,
    )


def _without_shared_question_conditions(
    claim_text: str,
    question: str,
) -> str:
    output = claim_text
    for pattern in (_FULL_DATE, _YEAR_MONTH, _REVISION):
        for match in pattern.finditer(question):
            value = match.group(0)
            occurrences = list(re.finditer(re.escape(value), output))
            protected = (
                list(_FULL_DATE.finditer(output))
                if pattern is _YEAR_MONTH
                else []
            )
            for occurrence in reversed(occurrences):
                if any(
                    full_date.start() <= occurrence.start()
                    and occurrence.end() <= full_date.end()
                    for full_date in protected
                ):
                    continue
                output = (
                    output[: occurrence.start()]
                    + " "
                    + output[occurrence.end() :]
                )
    if _BINARY_QUESTION.search(question) and _BINARY_ANSWER.search(
        claim_text
    ):
        for pattern in (
            _CLOCK_COLON,
            _CLOCK_KOREAN,
            _KOREAN_SCALED_NUMBER,
            _NUMBER,
        ):
            for match in pattern.finditer(question):
                value = match.group(0)
                if value in output:
                    output = output.replace(value, " ")
    return output


def _unit_evidence_context(unit: dict[str, Any]) -> str:
    return " ".join(
        (
            str(unit.get("title") or ""),
            str(unit.get("context_text") or ""),
            f"published_at: {unit.get('published_at') or ''}",
            f"valid_from: {unit.get('valid_from') or ''}",
            f"valid_to: {unit.get('valid_to') or ''}",
            f"revision: {unit.get('revision_id') or ''}",
            f"status: {unit.get('status') or ''}",
            str(unit.get("table_row_count") or ""),
            str(unit.get("text") or ""),
        )
    )


def _status_values(value: Any) -> set[str]:
    text = str(value or "").casefold()
    return {
        canonical
        for canonical, aliases in _STATUS_ALIASES.items()
        if any(alias in text for alias in aliases)
    }


def _cross_parent_structured_values_supported(
    claim_text: str,
    question: str,
    selected_units: list[dict[str, Any]],
) -> bool:
    units_by_parent: dict[str, list[dict[str, Any]]] = {}
    for unit in selected_units:
        parent = str(
            unit.get("parent_document_id")
            or unit.get("chunk_id")
            or ""
        )
        if parent:
            units_by_parent.setdefault(parent, []).append(unit)
    if len(units_by_parent) < 2:
        return True

    factual_claim = _without_shared_question_conditions(
        claim_text,
        question,
    )
    claim_numbers = _numeric_values(factual_claim)
    claim_revisions = _condition_values(claim_text)["revisions"]
    requested_statuses = _status_values(f"{question}\n{claim_text}")
    for parent_units in units_by_parent.values():
        parent_context = "\n".join(
            _unit_evidence_context(unit) for unit in parent_units
        )
        if not _explicit_conditions_match(
            question,
            parent_context,
            selected_units=parent_units,
        ):
            return False
        if claim_numbers and (
            not claim_numbers <= _numeric_values(parent_context)
            or not _normalized_factual_values_supported(
                factual_claim,
                parent_context,
            )
        ):
            return False
        if not claim_revisions <= _condition_values(parent_context)[
            "revisions"
        ]:
            return False
        if requested_statuses:
            parent_statuses = {
                status
                for unit in parent_units
                for status in _status_values(unit.get("status"))
            }
            if not requested_statuses <= parent_statuses:
                return False
    return True


def _resolve_citations(
    evidence_refs: list[str],
    *,
    units_by_ref: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    citations = []
    failures = []
    selected_units = []
    for evidence_ref in dict.fromkeys(evidence_refs):
        unit = units_by_ref.get(evidence_ref)
        if unit is None:
            failures.append(f"evidence_ref_not_provided:{evidence_ref}")
            continue
        chunk_id = str(unit.get("chunk_id") or "")
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            failures.append(f"evidence_chunk_not_found:{evidence_ref}")
            continue
        source_text = str(chunk.get("display_text") or "")
        start = int(unit.get("start_char", -1))
        end = int(unit.get("end_char", -1))
        if (
            start < 0
            or end <= start
            or end > len(source_text)
            or source_text[start:end] != str(unit.get("text") or "")
        ):
            failures.append(f"evidence_coordinate_mismatch:{evidence_ref}")
            continue
        selected_units.append(unit)
        citations.append(
            {
                "evidence_ref": evidence_ref,
                "chunk_id": chunk_id,
                "start_char": start,
                "end_char": end,
                "text": source_text[start:end],
                "title": str(unit.get("title") or ""),
            }
        )
    return citations, failures, selected_units


def _mentioned_subjects(
    text: str,
    requested_subjects: list[str],
) -> list[str]:
    compact_text = _compact(text)
    return [
        subject
        for subject in requested_subjects
        if _compact(subject) and _compact(subject) in compact_text
    ]


def _subjects_bound_to_evidence(
    claim_text: str,
    *,
    requested_subjects: list[str],
    selected_units: list[dict[str, Any]],
) -> bool:
    if not requested_subjects:
        return True
    mentioned = _mentioned_subjects(claim_text, requested_subjects)
    subjects_to_bind = mentioned or (
        requested_subjects if len(requested_subjects) == 1 else []
    )
    if not subjects_to_bind:
        return False
    identities = [
        " ".join(
            (
                str(unit.get("subject") or ""),
                str(unit.get("title") or ""),
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
        )
        for unit in selected_units
    ]
    return all(
        any(
            _compact(subject) in _compact(identity)
            or (
                bool(_compact_tokens(subject))
                and _compact_tokens(subject)
                <= _compact_tokens(identity)
            )
            or _surface_overlap(subject, identity)
            for identity in identities
        )
        for subject in subjects_to_bind
    )


def _explicit_clauses_covered(
    question: str,
    claims: list[dict[str, Any]],
    *,
    units_by_ref: dict[str, dict[str, Any]],
) -> bool:
    kiwi_clauses = kiwi_independent_requirement_queries(question)
    clauses = kiwi_clauses or explicit_question_clauses(question)
    if len(clauses) < 2:
        return True
    clause_tokens = [_compact_tokens(clause) for clause in clauses]
    common_tokens = set.intersection(*clause_tokens)
    clause_fragments = [_surface_fragments(clause) for clause in clauses]
    common_fragments = set.intersection(*clause_fragments)
    generic_tokens = {"알려줘", "뭐였어", "언제였어", "각각"}
    claim_contexts = []
    claim_focuses = []
    for claim in claims:
        selected_units = [
            units_by_ref[evidence_ref]
            for evidence_ref in claim["evidence_refs"]
            if evidence_ref in units_by_ref
        ]
        claim_contexts.append(
            " ".join(
                [
                    claim["text"],
                    *(
                        " ".join(
                            (
                                str(unit.get("title") or ""),
                                str(unit.get("context_text") or ""),
                                str(unit.get("text") or ""),
                            )
                        )
                        for unit in selected_units
                    ),
                ]
            )
        )
        claim_focuses.append(
            {
                _compact(str(unit.get("question_focus") or ""))
                for unit in selected_units
                if str(unit.get("question_focus") or "").strip()
            }
        )

    def lexical_match(clause_index: int, claim_index: int) -> bool:
        tokens = clause_tokens[clause_index]
        fragments = clause_fragments[clause_index]
        distinctive_tokens = tokens - common_tokens - generic_tokens
        distinctive_fragments = (
            fragments - common_fragments
            if kiwi_clauses
            else fragments
        )
        minimum_fragment_matches = 1 if kiwi_clauses else 2
        context = claim_contexts[claim_index]
        return bool(
            distinctive_tokens & _compact_tokens(context)
            or len(
                distinctive_fragments & _surface_fragments(context)
            )
            >= minimum_fragment_matches
        )

    if any(
        all(
            lexical_match(clause_index, claim_index)
            for clause_index in range(len(clauses))
        )
        for claim_index in range(len(claims))
    ):
        return True

    eligible_claims = []
    for clause_index, clause in enumerate(clauses):
        normalized_clause = _compact(clause)
        eligible_claims.append(
            [
                claim_index
                for claim_index in range(len(claims))
                if lexical_match(clause_index, claim_index)
                or (
                    bool(kiwi_clauses)
                    and normalized_clause in claim_focuses[claim_index]
                )
            ]
        )

    def assign_distinct_claims(
        clause_index: int,
        used_claims: set[int],
    ) -> bool:
        if clause_index >= len(eligible_claims):
            return True
        for claim_index in eligible_claims[clause_index]:
            if claim_index in used_claims:
                continue
            if assign_distinct_claims(
                clause_index + 1,
                {*used_claims, claim_index},
            ):
                return True
        return False

    return assign_distinct_claims(0, set())


def _replacement_evidence_for_claim(
    *,
    question: str,
    claim_text: str,
    evidence_units: list[dict[str, Any]],
    units_by_ref: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    requested_subjects: list[str],
) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    factual_claim = _without_shared_question_conditions(
        claim_text,
        question,
    )
    question_tokens = _compact_tokens(question)
    replacements = []
    for unit in evidence_units:
        evidence_ref = str(unit.get("evidence_ref") or "")
        citations, failures, selected_units = _resolve_citations(
            [evidence_ref],
            units_by_ref=units_by_ref,
            chunks_by_id=chunks_by_id,
        )
        if failures or len(citations) != 1 or len(selected_units) != 1:
            continue
        evidence_context = _unit_evidence_context(unit)
        identity_context = " ".join(
            (
                str(unit.get("title") or ""),
                str(unit.get("context_text") or ""),
            )
        )
        identity_overlap = len(
            question_tokens & _compact_tokens(identity_context)
        )
        if identity_overlap < 2:
            continue
        if not _explicit_conditions_match(
            question,
            evidence_context,
            selected_units=[unit],
        ):
            continue
        if not _subjects_bound_to_evidence(
            claim_text,
            requested_subjects=requested_subjects,
            selected_units=[unit],
        ):
            continue
        if not _claim_addresses_question_surface(
            question,
            claim_text,
            evidence_context,
            requested_subjects=requested_subjects,
        ):
            continue
        if not _evidence_relevance_supported([unit]):
            continue
        if not _claim_relation_role_supported(claim_text, [unit]):
            continue
        if not _negative_absence_claim_supported(claim_text, [unit]):
            continue
        if (
            not _numeric_values(factual_claim)
            <= _numeric_values(evidence_context)
            or not _normalized_factual_values_supported(
                factual_claim,
                evidence_context,
            )
        ):
            continue
        replacements.append(
            (
                -identity_overlap,
                -float(unit.get("question_relevance_score") or 0.0),
                int(unit.get("candidate_ref") or 0),
                int(unit.get("start_char") or 0),
                evidence_ref,
                citations[0],
                unit,
            )
        )
    if not replacements:
        return None
    replacements.sort(key=lambda row: row[:4])
    best = replacements[0]
    return str(best[4]), best[5], best[6]


def verify_product_claim_output(
    output: dict[str, Any],
    *,
    question: str,
    evidence_units: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    requested_subjects: list[str] | None = None,
) -> dict[str, Any]:
    """Verify short product claims without validating every natural-language token."""

    model_mode = str(output.get("mode") or "")
    if model_mode not in _ALLOWED_MODES:
        raise RuntimeError(f"unsupported product response mode: {model_mode}")
    raw_claims = output.get("claims")
    if not isinstance(raw_claims, list):
        raise RuntimeError("product claims must be a list")
    subjects = [
        str(subject).strip()
        for subject in (requested_subjects or [])
        if str(subject).strip()
    ]
    clarification = str(output.get("clarification") or "").strip()
    if model_mode == "clarification":
        contract_valid = not raw_claims and bool(clarification)
        return {
            "mode": "clarification" if clarification else "unsupported",
            "model_mode": model_mode,
            "claims": [],
            "rejected_claims": [
                {
                    "claim_index": claim_index,
                    "text": "",
                    "evidence_refs": [],
                    "reasons": ["clarification_must_not_include_claims"],
                }
                for claim_index, _ in enumerate(raw_claims, 1)
            ],
            "clarification": clarification,
            "verification": {
                "all_exposed_citations_verified": True,
                "requested_subjects": subjects,
                "covered_subjects": [],
                "all_requested_subjects_covered": not subjects,
                "all_explicit_question_clauses_covered": False,
                "complete_evidence_required": any(
                    cue in question for cue in _COMPLETE_CUES
                ),
                "complete_evidence_present": False,
                "clarification_contract_valid": contract_valid,
                "raw_output_passed_without_sanitization": contract_valid,
            },
        }
    units_by_ref = {
        str(unit["evidence_ref"]): unit
        for unit in evidence_units
    }
    accepted = []
    rejected = []
    pruned_evidence_refs = set()
    rebound_evidence_refs = []
    for claim_index, raw_claim in enumerate(raw_claims, 1):
        if not isinstance(raw_claim, dict):
            raise RuntimeError("each product claim must be an object")
        text = str(raw_claim.get("text") or "").strip()
        evidence_refs = [
            str(value)
            for value in (raw_claim.get("evidence_refs") or [])
        ]
        citations, failures, selected_units = _resolve_citations(
            evidence_refs,
            units_by_ref=units_by_ref,
            chunks_by_id=chunks_by_id,
        )
        citations, selected_units, condition_pruned_refs = (
            _matching_explicit_condition_evidence(
                question,
                citations,
                selected_units,
            )
        )
        if condition_pruned_refs:
            pruned_evidence_refs.update(condition_pruned_refs)
            evidence_refs = [
                str(citation["evidence_ref"]) for citation in citations
            ]
        reasons = list(failures)
        if not reasons and any(
            marker in text for marker in _UNSUPPORTED_LANGUAGE
        ):
            reasons.append("unsupported_language_in_claim")
        if not reasons and _compact(text) == _compact(question):
            reasons.append("claim_repeats_question")
        if not reasons and not _required_factual_value_present(
            question,
            text,
        ):
            reasons.append("required_factual_value_missing")
        if not reasons and not _subjects_bound_to_evidence(
            text,
            requested_subjects=subjects,
            selected_units=selected_units,
        ):
            reasons.append("claim_subject_not_bound_to_evidence")
        evidence_context = "\n".join(
            _unit_evidence_context(unit) for unit in selected_units
        )
        if not reasons and not _claim_addresses_question_surface(
            question,
            text,
            evidence_context,
            requested_subjects=subjects,
        ):
            reasons.append("claim_does_not_address_question_surface")
        if not reasons and not _evidence_relevance_supported(selected_units):
            reasons.append("evidence_relevance_below_threshold")
        if not reasons and not _claim_relation_role_supported(
            text,
            selected_units,
        ):
            reasons.append("question_relation_role_mismatch")
        if not reasons and not _normative_relation_supported(
            question,
            selected_units,
        ):
            reasons.append("normative_relation_not_in_evidence")
        if not reasons and not _negative_absence_claim_supported(
            text,
            selected_units,
        ):
            reasons.append("negative_absence_not_in_evidence")
        if not reasons and not _cross_parent_structured_values_supported(
            text,
            question,
            selected_units,
        ):
            reasons.append("cross_parent_structured_value_conflict")
        condition_mismatch = bool(
            not reasons
            and not _explicit_conditions_match(
                question,
                evidence_context,
                selected_units=selected_units,
            )
        )
        factual_claim = _without_shared_question_conditions(
            text,
            question,
        )
        factual_mismatch = bool(
            not reasons
            and (
                not _numeric_values(factual_claim)
                <= _numeric_values(evidence_context)
                or not _normalized_factual_values_supported(
                    factual_claim,
                    evidence_context,
                )
            )
        )
        if not reasons and (condition_mismatch or factual_mismatch):
            replacement = _replacement_evidence_for_claim(
                question=question,
                claim_text=text,
                evidence_units=evidence_units,
                units_by_ref=units_by_ref,
                chunks_by_id=chunks_by_id,
                requested_subjects=subjects,
            )
            if replacement is None:
                reasons.append(
                    "explicit_question_condition_mismatch"
                    if condition_mismatch
                    else "factual_values_not_in_evidence"
                )
            else:
                replacement_ref, replacement_citation, replacement_unit = (
                    replacement
                )
                rebound_evidence_refs.append(
                    {
                        "claim_index": claim_index,
                        "from": list(evidence_refs),
                        "to": [replacement_ref],
                    }
                )
                evidence_refs = [replacement_ref]
                citations = [replacement_citation]
                selected_units = [replacement_unit]
                evidence_context = _unit_evidence_context(
                    replacement_unit
                )
        if reasons:
            rejected.append(
                {
                    "claim_index": claim_index,
                    "text": text,
                    "evidence_refs": evidence_refs,
                    "reasons": reasons,
                }
            )
            continue
        accepted.append(
            {
                "_claim_index": claim_index,
                "_mentioned_subjects": set(
                    _mentioned_subjects(text, subjects)
                ),
                "_question_surface": (
                    _surface_fragments(question)
                    & _surface_fragments(evidence_context)
                ),
                "text": text,
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
                "citations": citations,
            }
        )

    if len(subjects) > 1:
        retained = []
        for claim in accepted:
            dominated = any(
                claim["_mentioned_subjects"]
                and claim["_mentioned_subjects"]
                == other["_mentioned_subjects"]
                and claim["_question_surface"]
                < other["_question_surface"]
                for other in accepted
                if other is not claim
            )
            if dominated:
                rejected.append(
                    {
                        "claim_index": claim["_claim_index"],
                        "text": claim["text"],
                        "evidence_refs": claim["evidence_refs"],
                        "reasons": [
                            "redundant_subject_evidence_misses_question_surface"
                        ],
                    }
                )
            else:
                retained.append(claim)
        accepted = retained

    accepted = [
        {
            "text": claim["text"],
            "evidence_refs": claim["evidence_refs"],
            "citations": claim["citations"],
        }
        for claim in accepted
    ]

    covered_subjects = {
        subject
        for claim in accepted
        for subject in _mentioned_subjects(claim["text"], subjects)
    }
    if len(subjects) == 1 and accepted:
        covered_subjects.add(subjects[0])
    all_subjects_covered = (
        not subjects or covered_subjects == set(subjects)
    )
    all_explicit_clauses_covered = _explicit_clauses_covered(
        question,
        accepted,
        units_by_ref=units_by_ref,
    )
    clarification_contract_valid = not clarification
    complete_required = (
        any(cue in question for cue in _COMPLETE_CUES)
        or ("종류" in question and "한 종류" not in question)
    )
    complete_present = any(
        bool(unit.get("complete") or unit.get("complete_list"))
        for claim in accepted
        for evidence_ref in claim["evidence_refs"]
        if (unit := units_by_ref.get(evidence_ref)) is not None
    )
    blocking_rejections = [
        rejection
        for rejection in rejected
        if not set(rejection["reasons"])
        <= _NON_BLOCKING_REJECTION_REASONS
    ]
    if not accepted:
        mode = (
            "clarification"
            if model_mode == "clarification"
            and str(output.get("clarification") or "").strip()
            else "unsupported"
        )
    elif (
        (
            model_mode == "answer"
            or (
                model_mode == "partial"
                and _verified_binary_answer(question, accepted)
            )
        )
        and clarification_contract_valid
        and not blocking_rejections
        and all_subjects_covered
        and all_explicit_clauses_covered
        and (not complete_required or complete_present)
    ):
        mode = "answer"
    else:
        mode = "partial"
    return {
        "mode": mode,
        "model_mode": model_mode,
        "claims": accepted,
        "rejected_claims": rejected,
        "clarification": clarification,
        "verification": {
            "all_exposed_citations_verified": True,
            "requested_subjects": subjects,
            "covered_subjects": sorted(covered_subjects),
            "all_requested_subjects_covered": all_subjects_covered,
            "all_explicit_question_clauses_covered": (
                all_explicit_clauses_covered
            ),
            "complete_evidence_required": complete_required,
            "complete_evidence_present": complete_present,
            "clarification_contract_valid": clarification_contract_valid,
            "pruned_evidence_refs": sorted(pruned_evidence_refs),
            "rebound_evidence_refs": rebound_evidence_refs,
            "raw_output_passed_without_sanitization": (
                not rejected
                and mode == model_mode
                and clarification_contract_valid
                and not pruned_evidence_refs
                and not rebound_evidence_refs
            ),
        },
    }
