from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


PRODUCT_SOURCE_IDS = frozenset(
    {
        "dnf_event",
        "dnf_monthly_item",
        "dnf_seria_shop",
    }
)
PRODUCT_SOURCE_KINDS = frozenset({"event", "monthly_item", "shop_product"})

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*년?")
_SUBJECT_YEAR_MONTH = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*년\s*"
    r"(?P<month>1[0-2]|0?[1-9])\s*월"
)
_BRACKETED_MONTH = re.compile(r"\[(?P<month>1[0-2]|0?[1-9])\s*월[^\]]*\]")
_MONTHLY_HEADER = re.compile(
    r"(?<!\d)(?P<month>1[0-2]|0?[1-9])\s*월\s*이달의\s*아이템"
)
_ISO_DATE = re.compile(
    r"(?<!\d)20\d{2}[-./](?P<month>1[0-2]|0?[1-9])"
    r"[-./]\d{1,2}(?!\d)"
)
_ORDINAL_PATTERNS = {
    "week": re.compile(r"(?<!\d)(\d{1,2})\s*주차"),
    "stage": re.compile(r"(?<!\d)(\d{1,2})\s*단계"),
    "round": re.compile(r"(?<!\d)(\d{1,2})\s*회차"),
}

_PRODUCT_MARKERS = frozenset(
    {
        "박스",
        "상자",
        "상품",
        "아이템",
        "아바타",
        "패키지",
        "이달의아이템",
    }
)
_GENERIC_PRODUCT_TOKENS = frozenset(
    {
        "가격",
        "거래",
        "거래타입",
        "구매",
        "구성품",
        "보너스",
        "상자",
        "상품",
        "세트",
        "아이템",
        "아바타",
        "콤보",
        "패키지",
        "판매",
        "풀세트",
    }
)


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _subject_text(requirement: dict[str, Any]) -> str:
    return " ".join(
        str(requirement.get(key) or "")
        for key in ("subject", "subject_group")
        if requirement.get(key)
    ).strip()


def looks_like_product_requirement(requirement: dict[str, Any]) -> bool:
    subject = _compact(_subject_text(requirement))
    return any(marker in subject for marker in _PRODUCT_MARKERS)


def _subject_discriminators(requirement: dict[str, Any]) -> tuple[str, ...]:
    subject = _subject_text(requirement)
    terms = []
    for token in _TOKEN.findall(subject):
        normalized = _compact(token)
        if (
            len(normalized) < 2
            or normalized in _GENERIC_PRODUCT_TOKENS
            or re.fullmatch(r"20\d{2}년?", normalized)
            or re.fullmatch(r"\d{1,2}월", normalized)
        ):
            continue
        terms.append(normalized)
    return tuple(dict.fromkeys(terms))


def explicit_record_constraints(
    question: str,
    requirement: dict[str, Any],
) -> dict[str, Any]:
    """Extract only explicit record identity qualifiers from the request."""

    identity_text = "\n".join((question, _subject_text(requirement)))
    year_months = {
        (int(match.group("year")), int(match.group("month")))
        for match in _SUBJECT_YEAR_MONTH.finditer(identity_text)
    }
    months = {
        int(match.group("month"))
        for pattern in (_BRACKETED_MONTH, _MONTHLY_HEADER)
        for match in pattern.finditer(identity_text)
    }
    months.update(month for _, month in year_months)
    years = {year for year, _ in year_months}
    if not years:
        years = {int(value) for value in _YEAR.findall(_subject_text(requirement))}
    ordinals = {
        kind: sorted(
            {
                int(match.group(1))
                for match in pattern.finditer(identity_text)
            }
        )
        for kind, pattern in _ORDINAL_PATTERNS.items()
    }
    return {
        "years": sorted(years),
        "months": sorted(months),
        "ordinals": {
            kind: values for kind, values in ordinals.items() if values
        },
        "subject_discriminators": list(
            _subject_discriminators(requirement)
        ),
    }


def _record_identity_text(units: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(value or "")
        for unit in units
        for value in (
            unit.get("title"),
            unit.get("context_text"),
            unit.get("text"),
        )
        if value
    )


def _record_period_identity_text(units: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(value or "")
        for unit in units
        for value in (
            unit.get("title"),
            unit.get("context_text"),
            unit.get("published_at"),
            unit.get("valid_from"),
            unit.get("valid_to"),
        )
        if value
    )


def _observed_record_months(text: str) -> set[int]:
    explicit_months = {
        int(match.group("month"))
        for pattern in (_BRACKETED_MONTH, _MONTHLY_HEADER)
        for match in pattern.finditer(text)
    }
    if explicit_months:
        return explicit_months
    return {
        int(match.group("month"))
        for match in _ISO_DATE.finditer(text)
    }


def _record_matches(
    units: list[dict[str, Any]],
    constraints: dict[str, Any],
) -> tuple[bool, list[str]]:
    identity_text = _record_identity_text(units)
    period_identity_text = _record_period_identity_text(units)
    normalized_identity = _compact(identity_text)
    failures = []

    discriminators = constraints["subject_discriminators"]
    missing_terms = [
        term for term in discriminators if term not in normalized_identity
    ]
    if missing_terms:
        failures.append("canonical_subject_mismatch")

    requested_years = set(constraints["years"])
    observed_years = {
        int(value) for value in _YEAR.findall(period_identity_text)
    }
    if (
        requested_years
        and observed_years
        and requested_years.isdisjoint(observed_years)
    ):
        failures.append("explicit_year_mismatch")

    requested_months = set(constraints["months"])
    observed_months = _observed_record_months(period_identity_text)
    if (
        requested_months
        and observed_months
        and requested_months.isdisjoint(observed_months)
    ):
        failures.append("explicit_month_mismatch")

    for kind, requested_values in constraints["ordinals"].items():
        observed_values = {
            int(match.group(1))
            for match in _ORDINAL_PATTERNS[kind].finditer(identity_text)
        }
        if (
            observed_values
            and set(requested_values).isdisjoint(observed_values)
        ):
            failures.append(f"explicit_{kind}_mismatch")

    return not failures, failures


def evaluate_record_identity(
    requirement: dict[str, Any],
    evidence_units: list[dict[str, Any]],
    *,
    question: str,
    force: bool = False,
) -> dict[str, Any]:
    """Fail closed when selected product evidence belongs to another record."""

    if not force and not looks_like_product_requirement(requirement):
        return {"state": "not_applicable", "failures": [], "records": []}

    product_units = [
        unit
        for unit in evidence_units
        if unit.get("source_id") in PRODUCT_SOURCE_IDS
        or unit.get("source_kind") in PRODUCT_SOURCE_KINDS
    ]
    if not product_units:
        return {
            "state": "not_applicable",
            "failures": [],
            "records": [],
        }

    constraints = explicit_record_constraints(question, requirement)
    by_record: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for index, unit in enumerate(product_units):
        record_id = (
            unit.get("parent_document_id"),
            unit.get("revision_id"),
        )
        if record_id == (None, None):
            record_id = ("evidence", index)
        by_record[record_id].append(unit)

    records = []
    all_failures = []
    for record_id, units in by_record.items():
        matched, failures = _record_matches(units, constraints)
        records.append(
            {
                "record_id": list(record_id),
                "matched": matched,
                "failures": failures,
            }
        )
        all_failures.extend(failures)

    if all(record["matched"] for record in records):
        return {"state": "matched", "failures": [], "records": records}
    return {
        "state": "mismatch",
        "failures": sorted(set(all_failures)),
        "records": records,
    }


def assess_record_identity_sufficiency(
    requirement: dict[str, Any],
    evidence_units: list[dict[str, Any]],
    *,
    question: str,
    force: bool = False,
) -> dict[str, Any]:
    """Shadow whether any retrieved product record matches the request."""

    if not force and not looks_like_product_requirement(requirement):
        return {
            "assessable": False,
            "would_trigger": False,
            "reason": "not_a_product_requirement",
            "matching_records": [],
        }
    product_units = [
        unit
        for unit in evidence_units
        if unit.get("source_id") in PRODUCT_SOURCE_IDS
        or unit.get("source_kind") in PRODUCT_SOURCE_KINDS
    ]
    if not product_units:
        return {
            "assessable": False,
            "would_trigger": False,
            "reason": "no_structured_product_records",
            "matching_records": [],
        }

    constraints = explicit_record_constraints(question, requirement)
    by_record: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for index, unit in enumerate(product_units):
        record_id = (
            unit.get("parent_document_id"),
            unit.get("revision_id"),
        )
        if record_id == (None, None):
            record_id = ("evidence", index)
        by_record[record_id].append(unit)
    matching_records = [
        list(record_id)
        for record_id, units in by_record.items()
        if _record_matches(units, constraints)[0]
    ]
    return {
        "assessable": True,
        "would_trigger": not matching_records,
        "reason": (
            "matching_record_present"
            if matching_records
            else "explicit_record_identity_missing"
        ),
        "matching_records": matching_records,
    }
