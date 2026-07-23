from __future__ import annotations

import copy
import re
from typing import Any


VALUE_SHAPE_VERSION = "requirement-value-shape-v3.3.0"

# These markers are applied only to the planner's normalized relation label. They
# are not question-intent routing rules and never turn evidence into support.
_PERCENT_RELATION_MARKERS = (
    "증가율",
    "상승률",
    "개선율",
    "감소율",
    "조정 비율",
)
_COST_RELATION_MARKERS = (
    "price",
    "cost",
    "cash_value",
    "가격",
    "판매가",
    "수수료",
)
_COUNT_RELATION_MARKERS = (
    "count",
    "횟수",
    "수량",
    "인원",
    "길이",
    "사용량",
    "남은량",
    "한도",
    "참여 단위",
)
_CALENDAR_DATE_RELATION_MARKERS = (
    "date",
    "날짜",
    "일자",
    "종료일",
    "시작일",
)
_CLOCK_RELATION_MARKERS = ("시간", "시점")

_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_PERCENT_RE = re.compile(rf"(?<![\d.]){_NUMBER}\s*%")
_CALENDAR_DATE_RE = re.compile(
    r"(?:\d{4}\s*[년./-]\s*\d{1,2}\s*[월./-]\s*\d{1,2}\s*일?"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|\d{4}-\d{2}-\d{2})"
)
_CLOCK_RE = re.compile(
    r"(?:오전|오후)?\s*(?:[01]?\d|2[0-3])\s*:\s*[0-5]\d"
    r"|(?:오전|오후)\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?"
)
_DURATION_RE = re.compile(
    rf"(?<![\d.]){_NUMBER}\s*(?:년|개월|달|주|일|시간|분|초)(?!\s*[월일:])"
)
# A period can also be written without a number+unit pair: as a dated range
# ("06.25 ~ 07.30") or as an unbounded term ("영구"). Both are checked on the raw
# text because _mask_calendar_and_clock would erase the range endpoints.
_DATE_TOKEN = r"(?:\d{4}\s*[년./-]\s*)?\d{1,2}\s*[월./-]\s*\d{1,2}\s*일?"
_DATE_RANGE_RE = re.compile(
    rf"{_DATE_TOKEN}[^~\n]{{0,25}}~[^~\n]{{0,25}}{_DATE_TOKEN}"
)
_UNBOUNDED_DURATION_RE = re.compile(r"영구")
_CURRENCY_RE = re.compile(
    rf"(?<![\d.]){_NUMBER}\s*(?:만|억)?\s*(?:골드|세라|원|마일리지|코인)"
)
_QUANTITY_RE = re.compile(
    rf"(?<![\d.]){_NUMBER}\s*(?:개|회|번|명|마리|단계|자|글자|칸|"
    r"GB|MB|KB|피로도|마일리지|포인트|골드|세라|원|코인)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _normalized_relation(requirement: dict[str, Any]) -> str:
    return " ".join(str(requirement.get("relation") or "").lower().split())


def normalize_expected_value_shape(requirement: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative typed expectation for a planner requirement.

    ``veto_enabled`` is deliberately false when the normalized planner fields do
    not identify one value shape with high precision. Unknown never means
    unsupported.
    """

    relation = _normalized_relation(requirement)
    value_type = str(requirement.get("value_type") or "").strip().lower()
    expected_kind: str | None = None
    reason = "no_high_precision_shape_contract"

    if value_type in {"percentage", "percent"} or any(
        marker in relation for marker in _PERCENT_RELATION_MARKERS
    ):
        expected_kind = "percentage"
        reason = "planner_relation_denotes_rate_or_percentage"
    elif value_type == "duration":
        expected_kind = "duration"
        reason = "planner_value_type_duration"
    elif value_type == "date-time":
        expected_kind = "clock_or_datetime"
        reason = "planner_value_type_datetime"
    elif value_type == "date" and any(
        marker in relation for marker in _CALENDAR_DATE_RELATION_MARKERS
    ):
        expected_kind = "calendar_date"
        reason = "planner_relation_denotes_calendar_date"
    elif value_type == "date" and any(
        marker in relation for marker in _CLOCK_RELATION_MARKERS
    ):
        expected_kind = "clock_or_datetime"
        reason = "planner_relation_denotes_clock_or_temporal_point"
    elif value_type == "amount" and any(
        marker in relation for marker in _COST_RELATION_MARKERS
    ):
        expected_kind = "cost_value"
        reason = "planner_relation_denotes_price_or_cost"
    elif value_type == "amount" and any(
        marker in relation for marker in _COUNT_RELATION_MARKERS
    ):
        expected_kind = "count_value"
        reason = "planner_relation_denotes_count_or_limit"

    return {
        "expected_kind": expected_kind,
        "reason": reason,
        "veto_enabled": expected_kind is not None,
        "value_shape_version": VALUE_SHAPE_VERSION,
    }


def _mask_calendar_and_clock(text: str) -> str:
    masked = _CALENDAR_DATE_RE.sub(" ", text)
    return _CLOCK_RE.sub(" ", masked)


def detect_value_shapes(text: str) -> set[str]:
    shapes: set[str] = set()
    if _PERCENT_RE.search(text):
        shapes.add("percentage")
    if _CALENDAR_DATE_RE.search(text):
        shapes.add("calendar_date")
    if _CLOCK_RE.search(text):
        shapes.add("clock_or_datetime")
    if _DATE_RANGE_RE.search(text) or _UNBOUNDED_DURATION_RE.search(text):
        shapes.add("duration")

    non_timestamp = _mask_calendar_and_clock(text)
    if _DURATION_RE.search(non_timestamp):
        shapes.add("duration")
    if _CURRENCY_RE.search(non_timestamp):
        shapes.update({"currency", "cost_value", "count_value"})
    if _QUANTITY_RE.search(non_timestamp):
        shapes.update({"quantity", "cost_value", "count_value"})
    return shapes


def apply_value_shape_veto(
    requirement: dict[str, Any], decision: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Downgrade only an already-supported decision missing a required shape.

    A matching shape is merely ``not_disproven``; it is never promoted to
    semantic support. This keeps the component a one-way safety veto.
    """

    output = copy.deepcopy(decision)
    contract = normalize_expected_value_shape(requirement)
    text = "\n".join(str(span.get("text") or "") for span in decision.get("spans", []))
    detected = sorted(detect_value_shapes(text))
    expected = contract["expected_kind"]
    vetoed = bool(
        decision.get("status") == "supported_exact"
        and contract["veto_enabled"]
        and expected not in detected
    )
    if vetoed:
        output["status"] = "unsupported"
        output["spans"] = []
        output["unsupported_message"] = "문서에서 요구된 값 형식을 확인할 수 없습니다."

    audit = {
        "requirement_id": requirement.get("requirement_id"),
        "expected_kind": expected,
        "normalization_reason": contract["reason"],
        "veto_enabled": contract["veto_enabled"],
        "detected_kinds": detected,
        "baseline_status": decision.get("status"),
        "b1_status": output.get("status"),
        "vetoed": vetoed,
        "support_semantics": "absence_only_veto_never_positive_entailment",
    }
    return output, audit
