from __future__ import annotations

import re


_REWARD_KIND_REQUEST = re.compile(
    r"(?:보상\s*(?:종류|목록|내역|구성|항목|품목)|"
    r"(?:전부|전체|모든)\s*보상|보상\s*(?:전부|전체|모두)|"
    r"(?:어떤|무슨)\s*보상(?:들)?|"
    r"보상(?:은|는|이|가)?\s*(?:뭐뭐|뭐(?:가|이)?)\s*있|"
    r"(?:어떤|무슨)\s*(?:아이템|전리품)(?:을|를)?\s*"
    r"(?:얻|획득|받|지급|드롭|나오)|"
    r"(?:무엇|뭘|뭐를)\s*(?:얻|획득|받)|"
    r"(?:지급|획득|드롭)되는\s*(?:아이템|전리품).*(?:나열|목록|종류))"
)
_CONTENT_KIND_REQUEST = re.compile(
    r"(?:(?:레이드|던전|콘텐츠)(?:의)?\s*종류|"
    r"(?:어떤|무슨)\s*(?:난이도|모드|유형)|"
    r"(?:난이도|모드|유형)(?:은|는|이|가|을|를|로)?\s*"
    r"(?:뭐|무엇|몇|알려|구분|나뉘))"
)
_COMPARISON_REQUEST = re.compile(r"(?:차이|비교)")
_NUMBERED_LIST_REQUEST_CUES = (
    "조건",
    "정보",
    "목록",
    "항목",
    "종류",
    "전부",
    "전체",
)
_SINGLE_LIST_REQUEST_CUES = ("한 가지", "하나만", "한 개")
_TABLE_EVIDENCE_REQUEST_CUES = ("표", "전부", "전체", "목록")
_EVIDENCE_COMPLETE_LIST_CUES = ("조건", "종류", "전부", "전체", "목록")
_VERIFIED_COMPLETE_CUES = ("전부", "전체", "목록", "뭐뭐")
_NATURAL_REWARD_ENUMERATION = re.compile(
    r"(?:어떤|무슨)\s*보상(?:들)?|"
    r"보상(?:은|는|이|가)?\s*뭐(?:가|이)?\s*있"
)

_RELEASE_ACTION = re.compile(
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)"
)
_RELEASE_DATE_QUESTION = re.compile(
    r"(?:(?:언제|날짜|일자|날|시점)[^?？.]{0,40}"
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)|"
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)"
    r"[^?？.]{0,40}(?:언제|날짜|일자|날|시점|일))"
)
_RELEASE_DATE_PRIORITY_QUESTION = re.compile(
    r"(?:(?:언제|날짜|일자|날|시점)[^?？.]{0,40}"
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)|"
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)"
    r"[^?？.]{0,40}(?:언제|날짜|일자|날|시점))"
)
_RELEASE_QUERY_PHRASE = re.compile(
    r"(?:언제\s*)?"
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)"
    r"(?:되었|됐|된\s*날|한\s*날|된|했|한|되는|될)?"
    r"(?:어|어요|나요|습니까|어야)?"
    r"(?:\s*(?:일자|날짜|날|시점|일))?"
    r"(?:은|는|이|가|을|를)?"
)
_RELEASE_SUBJECT_TAIL = re.compile(
    r"\s*(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)"
    r"(?:된\s*날|한\s*날|일자|날짜|시점|날|일)?$"
)
_RELEASE_DATE_SURFACE = re.compile(
    r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|"
    r"20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|"
    r"\d{1,2}/\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
_RELEASE_RELATION_STATEMENT = re.compile(
    r"(?:서비스\s*시작|출시|오픈|공개|업데이트|추가|도입|적용)"
    r"(?:\s*일|[^.\n]{0,40}"
    r"(?:됐|되었|됩니다|되는|했|합니다|일자|날짜|날|시점))"
)


def reward_kind_requested(question: str) -> bool:
    """Recognize a request for reward item kinds, not one named item fact."""

    return _REWARD_KIND_REQUEST.search(" ".join(str(question).split())) is not None


def content_kind_requested(question: str) -> bool:
    """Recognize a request for the category row of one game content."""

    return _CONTENT_KIND_REQUEST.search(" ".join(str(question).split())) is not None


def comparison_requested(question: str) -> bool:
    return _COMPARISON_REQUEST.search(str(question)) is not None


def numbered_list_requested(question: str) -> bool:
    normalized = " ".join(str(question or "").split())
    return bool(
        any(cue in normalized for cue in _NUMBERED_LIST_REQUEST_CUES)
        and not any(cue in normalized for cue in _SINGLE_LIST_REQUEST_CUES)
    )


def table_evidence_requested(question: str) -> bool:
    return any(cue in question for cue in _TABLE_EVIDENCE_REQUEST_CUES)


def evidence_complete_list_requested(question: str) -> bool:
    return any(cue in question for cue in _EVIDENCE_COMPLETE_LIST_CUES)


def verified_complete_answer_requested(question: str) -> bool:
    return bool(
        any(cue in question for cue in _VERIFIED_COMPLETE_CUES)
        or ("종류" in question and "한 종류" not in question)
        or _NATURAL_REWARD_ENUMERATION.search(question) is not None
    )


def release_date_requested(question: str) -> bool:
    return _RELEASE_DATE_QUESTION.search(" ".join(str(question).split())) is not None


def release_date_priority_requested(question: str) -> bool:
    """Return whether semantic date evidence should outrank lexical hits."""

    return (
        _RELEASE_DATE_PRIORITY_QUESTION.search(
            " ".join(str(question).split())
        )
        is not None
    )


def rewrite_release_date_query(question: str) -> str | None:
    normalized = " ".join(str(question).split())
    if not release_date_requested(normalized):
        return None
    rewritten = " ".join(
        _RELEASE_QUERY_PHRASE.sub(
            "업데이트 되는 내용",
            normalized,
            count=1,
        ).split()
    )
    return rewritten if rewritten and rewritten != normalized else None


def normalize_release_date_subjects(
    question: str,
    subjects: list[str],
) -> list[str]:
    """Remove a release-date relation accidentally parsed as subject identity."""

    if not release_date_requested(question):
        return list(subjects)
    normalized = []
    for subject in subjects:
        original = " ".join(str(subject).split())
        trimmed = _RELEASE_SUBJECT_TAIL.sub("", original).strip()
        normalized.append(trimmed if len(trimmed) >= 2 else original)
    return list(dict.fromkeys(normalized))


def release_date_surface_present(value: str) -> bool:
    return _RELEASE_DATE_SURFACE.search(str(value)) is not None


def release_date_claim_present(value: str) -> bool:
    text = str(value)
    return bool(
        release_date_surface_present(text)
        and _RELEASE_ACTION.search(text)
    )


def release_relation_evidence_present(value: str) -> bool:
    return _RELEASE_RELATION_STATEMENT.search(str(value)) is not None
