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
_DURATION_DAY_RANGE = re.compile(
    r"(?<!\d)(?P<start>\d+)\s*일?\s*"
    r"(?:~|～|–|—|-|/|에서)\s*"
    r"(?P<end>\d+)\s*일"
)
_NON_PLAIN_NUMBER_PATTERNS = (
    _CURRENCY_FORWARD,
    _CURRENCY_REVERSE_COUNT,
    _DURATION_DAY_RANGE,
    re.compile(
        r"(?<!\d)20\d{2}\s*(?:년|[./-])\s*\d{1,2}"
        r"\s*(?:월|[./-])\s*\d{1,2}\s*일?"
    ),
    re.compile(r"(?<!\d)\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(
        r"(?<![\d.])(?:0?[1-9]|1[0-2])[./]"
        r"(?:0?[1-9]|[12]\d|3[01])(?![\d.])"
    ),
    re.compile(r"(?<!\d)20\d{2}\s*년"),
    re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)"),
    re.compile(
        r"(?<!\d)(?:(?:오전|오후)\s*)?"
        r"(?:[01]?\d|2[0-3])\s*시"
        r"(?:\s*[0-5]?\d\s*분)?"
    ),
    re.compile(r"(?<!\d)\d+(?:\.\d+)?\s*%"),
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
    r"(?:되지\s*않|하지\s*않|지\s*않(?:습니다|았다|는다|음)?|"
    r"불가능|미적용|제외됩니다|계산되지|"
    r"없(?:습니다|었다|다|음)|어렵(?:습니다|었다|다))"
)
_BOOLEAN_POSITIVE_ACTION = re.compile(
    r"(?:할|될)\s*수\s*있(?:습니다|었습니다|다|었다)"
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


def number_values(value: Any) -> set[float]:
    text_chars = list(str(value or ""))
    text = "".join(text_chars)
    for pattern in _NON_PLAIN_NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            text_chars[match.start() : match.end()] = (
                " " for _ in range(match.end() - match.start())
            )
    text = "".join(text_chars)
    values = set()
    for match in re.finditer(
        r"(?<![\d,])(\d[\d,]*(?:\.\d+)?)\s*(만|억)?",
        text,
    ):
        amount = float(match.group(1).replace(",", ""))
        scale = {"만": 10_000, "억": 100_000_000}.get(
            match.group(2),
            1,
        )
        values.add(amount * scale)
    return values


def duration_range_values(value: Any) -> set[tuple[int, int, str]]:
    values = set()
    for match in _DURATION_DAY_RANGE.finditer(str(value or "")):
        start = int(match.group("start"))
        end = int(match.group("end"))
        if start <= end:
            values.add((start, end, "day"))
    return values


def time_sequence(value: Any) -> list[str]:
    text = str(value or "")
    occurrences: list[tuple[int, int, str]] = []
    for match in re.finditer(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        text,
    ):
        occurrences.append(
            (
                match.start(),
                match.end(),
                f"{int(match.group(1)):02d}:{int(match.group(2)):02d}",
            )
        )
    for match in re.finditer(
        r"(?:(오전|오후)\s*)?([01]?\d|2[0-3])\s*시"
        r"(?:\s*([0-5]?\d)\s*분)?",
        text,
    ):
        meridiem = match.group(1)
        hour = int(match.group(2))
        minute = int(match.group(3) or 0)
        if meridiem == "오전" and hour == 12:
            hour = 0
        elif meridiem == "오후" and hour < 12:
            hour += 12
        occurrences.append(
            (
                match.start(),
                match.end(),
                f"{hour:02d}:{minute:02d}",
            )
        )
    sequence = []
    occupied: list[tuple[int, int]] = []
    for start, end, normalized in sorted(occurrences):
        if any(
            start < other_end and end > other_start
            for other_start, other_end in occupied
        ):
            continue
        occupied.append((start, end))
        sequence.append(normalized)
    return sequence


def time_values(value: Any) -> set[str]:
    return set(time_sequence(value))


def boolean_evidence(value: Any) -> set[bool]:
    text = str(value or "")
    masked = _BOOLEAN_STATE_NOUN.sub("___", text)
    if _BOOLEAN_NEGATIVE_ACTION.search(masked):
        return {False}
    if (
        any(marker in text for marker in _BOOLEAN_POSITIVE_MARKERS)
        or _BOOLEAN_POSITIVE_ACTION.search(text)
    ):
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


_LOCATION_RELATIONS = {
    "deletion_location",
    "lookup_location",
    "redeem_location",
    "registration_location",
    "usable_locations",
}


def canonical_categorical_values(
    value: Any,
    *,
    relation: str | None,
) -> set[str]:
    text = str(value or "").casefold()
    if relation == "appeal_channel":
        if "고객센터" in text or re.search(
            r"1\s*:\s*1\s*문의",
            text,
        ):
            return {"customer_support_inquiry"}
        return set()

    if relation not in _LOCATION_RELATIONS:
        return set()

    values = set()
    if re.search(r"게임\s*내", text) or re.search(
        r"게임(?!\s*홈페이지)",
        text,
    ):
        values.add("in_game")
    if "웹" in text or "홈페이지" in text:
        values.add("web")
    return values
