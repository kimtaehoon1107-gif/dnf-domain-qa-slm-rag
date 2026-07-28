from __future__ import annotations

import copy
import re
from typing import Any

from src.v3.grounded_answer_generator import extract_factual_tokens


_BRACKETED_MONTH = re.compile(r"\[(?P<month>\d{1,2})월\]")
_SUBJECT_YEAR_MONTH = re.compile(
    r"(?P<year>20\d{2})년\s*(?P<month>\d{1,2})월"
    r"(?=\s*(?:에\s*(?:판매|출시)|이달의\s*아이템))"
)
_COMPARISON_MARKERS = ("비교", "각각", "현재", "종전", "이전")
_HIGH_RISK_RELATION_MARKERS = ("누적", "최대", "최소")

_TEMPORAL_ROLE_MARKERS = {
    "published_at": ("게시", "등록일", "작성일"),
    "effective_at": ("적용", "시행일"),
    "deletion_at": ("삭제",),
    "sale_period": ("판매 기간", "판매기간"),
    "event_period": ("이벤트 기간", "진행 기간"),
    "maintenance_time": ("정기점검", "점검 시간"),
}


def _compact(value: Any) -> str:
    return re.sub(r"[\s,]+", "", str(value or "").casefold())


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
    rendered = "\n".join(
        f"- {row['answer']} "
        + " ".join(
            f"[{citation['chunk_id']}]"
            for citation in row.get("citations", [])
        )
        for row in supported
    )
    result["response_mode"] = response_mode
    result["rendered_answer"] = rendered
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
    failure_reasons = audit.setdefault("failure_reasons", [])
    if reason not in failure_reasons:
        failure_reasons.append(reason)
    if details:
        audit.setdefault("guard_details", {})[reason] = details
    result["verification"]["raw_output_passed_without_sanitization"] = False


def _citation_context(
    citation: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> str:
    chunk = chunks_by_id.get(str(citation.get("chunk_id") or ""), {})
    document_id = str(
        citation.get("parent_document_id")
        or chunk.get("parent_document_id")
        or ""
    )
    document = documents_by_id.get(document_id, {})
    return "\n".join(
        str(value or "")
        for value in (
            document.get("title"),
            document.get("published_at"),
            chunk.get("display_text"),
        )
        if value
    )


def _subject_periods(question: str) -> set[tuple[int | None, int]]:
    periods: set[tuple[int | None, int]] = {
        (None, int(match.group("month")))
        for match in _BRACKETED_MONTH.finditer(question)
    }
    periods.update(
        (
            int(match.group("year")),
            int(match.group("month")),
        )
        for match in _SUBJECT_YEAR_MONTH.finditer(question)
    )
    return periods


def _context_has_subject_period(
    context: str,
    *,
    year: int | None,
    month: int,
) -> bool:
    month_surface = (
        str(month)
        if month >= 10
        else rf"(?:{month}|0{month})"
    )
    month_patterns = (
        rf"\[{month_surface}월\]",
        rf"(?<!\d){month_surface}월\s*이달의\s*아이템",
        rf"(?<!\d){month_surface}월에\s*(?:판매|출시)",
    )
    if year is None:
        return any(re.search(pattern, context) for pattern in month_patterns)
    explicit_year_month = (
        rf"(?<!\d){year}\s*년\s*{month_surface}\s*월",
        rf"(?<!\d){year}[-./]{month:02d}(?!\d)",
    )
    if any(re.search(pattern, context) for pattern in explicit_year_month):
        return True
    return bool(
        any(re.search(pattern, context) for pattern in month_patterns)
        and re.search(rf"(?<!\d){year}(?:년)?", context)
    )


def apply_subject_period_identity_guard(
    result: dict[str, Any],
    *,
    question: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Reject a claim sourced from a different explicit product-period record."""

    guarded = copy.deepcopy(result)
    periods = _subject_periods(question)
    if len(periods) != 1:
        return guarded
    year, month = next(iter(periods))
    for requirement in guarded.get("requirements", []):
        if requirement.get("status") != "supported_exact":
            continue
        citations = requirement.get("citations") or []
        contexts = [
            _citation_context(
                citation,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
            )
            for citation in citations
        ]
        if any(
            _context_has_subject_period(
                context,
                year=year,
                month=month,
            )
            for context in contexts
        ):
            continue
        _block_requirement(
            guarded,
            requirement_index=int(requirement["requirement_index"]),
            reason="explicit_subject_period_identity_mismatch",
            details={"year": year, "month": month},
        )
    return _recompute_exposure(guarded)


def _expected_temporal_role(text: str) -> str | None:
    compact = _compact(text)
    if "게시" in compact:
        return "published_at"
    if "적용" in compact or "시행일" in compact:
        return "effective_at"
    if "삭제" in compact:
        return "deletion_at"
    if "판매기간" in compact:
        return "sale_period"
    if "이벤트" in compact and (
        "언제부터" in compact or "기간" in compact
    ):
        return "event_period"
    if "점검" in compact and (
        "몇시" in compact or "시간" in compact or "시부터" in compact
    ):
        return "maintenance_time"
    return None


def _evidence_temporal_roles(text: str) -> set[str]:
    compact = _compact(text)
    return {
        role
        for role, markers in _TEMPORAL_ROLE_MARKERS.items()
        if any(_compact(marker) in compact for marker in markers)
    }


def apply_temporal_role_guard(
    result: dict[str, Any],
    *,
    question: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Reject only an explicit temporal-role conflict; unknown evidence is audited."""

    guarded = copy.deepcopy(result)
    for requirement in guarded.get("requirements", []):
        if requirement.get("status") != "supported_exact":
            continue
        expected = _expected_temporal_role(
            str(requirement.get("question_part") or "")
        ) or _expected_temporal_role(question)
        if expected is None:
            continue
        citations = requirement.get("citations") or []
        roles = set().union(
            *(
                _evidence_temporal_roles(
                    str(citation.get("text") or "")
                )
                for citation in citations
            )
        )
        if not roles:
            contexts = [
                _citation_context(
                    citation,
                    chunks_by_id=chunks_by_id,
                    documents_by_id=documents_by_id,
                )
                for citation in citations
            ]
            roles = set().union(
                *(_evidence_temporal_roles(context) for context in contexts)
            )
        if not roles or expected in roles:
            continue
        _block_requirement(
            guarded,
            requirement_index=int(requirement["requirement_index"]),
            reason="temporal_role_conflict",
            details={
                "expected_role": expected,
                "evidence_roles": sorted(roles),
            },
        )
    return _recompute_exposure(guarded)


def apply_relation_value_colocation_guard(
    result: dict[str, Any],
    *,
    question: str,
) -> dict[str, Any]:
    """Require high-risk max/min/cumulative values and relation anchors together."""

    guarded = copy.deepcopy(result)
    for requirement in guarded.get("requirements", []):
        if requirement.get("status") != "supported_exact":
            continue
        relation_text = (
            f"{question} {requirement.get('question_part') or ''}"
        )
        anchors = [
            marker
            for marker in _HIGH_RISK_RELATION_MARKERS
            if marker in relation_text
        ]
        factual_tokens = extract_factual_tokens(
            str(requirement.get("answer") or "")
        )
        if not anchors or not factual_tokens:
            continue
        supported = False
        for citation in requirement.get("citations") or []:
            text = str(citation.get("text") or "")
            compact = _compact(text)
            if all(anchor in text for anchor in anchors) and all(
                _compact(token) in compact for token in factual_tokens
            ):
                supported = True
                break
        if supported:
            continue
        _block_requirement(
            guarded,
            requirement_index=int(requirement["requirement_index"]),
            reason="relation_value_not_colocated",
            details={
                "relation_anchors": anchors,
                "factual_tokens": factual_tokens,
            },
        )
    return _recompute_exposure(guarded)
