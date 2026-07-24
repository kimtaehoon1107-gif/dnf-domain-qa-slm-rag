from __future__ import annotations

import re
from typing import Any


CURRENCY_UNITS = {
    "광휘의 잔영": "광휘의 잔영",
    "골드 코인": "골드 코인",
    "세라 코인": "세라 코인",
    "마일리지": "마일리지",
    "포인트": "포인트",
    "코인": "코인",
    "세라": "세라",
    "sera": "세라",
    "골드": "골드",
    "gold": "골드",
    "원": "원",
    "krw": "원",
}

_UNIT_ALTERNATION = "|".join(
    re.escape(unit)
    for unit in sorted(CURRENCY_UNITS, key=len, reverse=True)
)
_CURRENCY_FORWARD = re.compile(
    rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>만|억)?\s*"
    rf"(?P<unit>{_UNIT_ALTERNATION})",
    re.IGNORECASE,
)
_CURRENCY_REVERSE_COUNT = re.compile(
    rf"(?P<unit>{_UNIT_ALTERNATION})\s*"
    r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>만|억)?\s*개",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"(?<![\d,])(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>만|억)?"
)

_BOOLEAN_POSITIVE_MARKERS = (
    "교환가능",
    "계산됩니다",
    "수정",
    "개선",
    "추가",
    "변경",
    "적용",
    "포함",
    "가능",
)
_BOOLEAN_NEGATIVE_ACTION = re.compile(
    r"(?:되지\s*않|하지\s*않|지\s*않습니다|불가능|미적용|"
    r"제외됩니다|계산되지|없습니다|없음)"
)
_BOOLEAN_STATE_NOUN = re.compile(
    r"(?:교환|거래|환불|사용|합성)\s*불가"
)


def _scaled_amount(amount_text: str, scale_text: str | None) -> int:
    amount = float(amount_text.replace(",", ""))
    scale = {"만": 10_000, "억": 100_000_000}.get(scale_text, 1)
    return int(amount * scale)


def currency_values(value: Any) -> set[tuple[int, str]]:
    text = str(value or "")
    values = set()
    occupied: list[tuple[int, int]] = []
    for pattern in (_CURRENCY_FORWARD, _CURRENCY_REVERSE_COUNT):
        for match in pattern.finditer(text):
            if any(
                match.start() < end and match.end() > start
                for start, end in occupied
            ):
                continue
            unit = CURRENCY_UNITS[match.group("unit").casefold()]
            values.add(
                (
                    _scaled_amount(
                        match.group("amount"),
                        match.group("scale"),
                    ),
                    unit,
                )
            )
            occupied.append((match.start(), match.end()))
    return values


def amount_of(value: Any) -> int | None:
    match = _AMOUNT.search(str(value or ""))
    if match is None:
        return None
    return _scaled_amount(match.group("amount"), match.group("scale"))


def boolean_evidence(value: Any) -> set[bool]:
    text = str(value or "")
    masked = _BOOLEAN_STATE_NOUN.sub("___", text)
    if _BOOLEAN_NEGATIVE_ACTION.search(masked):
        return {False}
    if any(marker in text for marker in _BOOLEAN_POSITIVE_MARKERS):
        return {True}
    return set()


def boolean_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    compact = re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())
    if compact in {"true", "yes", "예", "적용", "포함", "가능"}:
        return True
    if compact in {"false", "no", "아니오", "미적용", "제외", "불가"}:
        return False
    evidence_values = boolean_evidence(value)
    return next(iter(evidence_values)) if len(evidence_values) == 1 else None
