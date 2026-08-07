from __future__ import annotations

import re
from typing import Any

from src.v3.value_normalization import boolean_evidence


_NEGATIVE_NARRATIVE = re.compile(
    r"(?:무관(?:합니다)?|어렵습니다|할\s*수\s*없|"
    r"포함되지|집계되지|적용되지|지원하지|제외(?:됩니다)?|불가능)"
)
_UNLIMITED = re.compile(
    r"(?:기간\s*)?무제한|기한(?:이)?\s*없|기간\s*제한(?:이)?\s*없"
)


def boolean_relation_evidence(
    requirement: dict[str, Any],
    evidence_text: str,
) -> set[bool]:
    observed = set(boolean_evidence(evidence_text))
    if _NEGATIVE_NARRATIVE.search(evidence_text):
        return {False}

    relation = re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(requirement.get("relation") or "").casefold(),
    )
    deadline_relation = (
        "deadline" in relation
        or ("삭제" in relation and "기한" in relation)
        or ("기간" in relation and "제한" in relation)
    )
    if deadline_relation and _UNLIMITED.search(evidence_text):
        return {False}
    return observed


def boolean_prompt_guidance(
    requirements: list[dict[str, Any]],
) -> str:
    if not any(
        requirement.get("value_type") == "boolean"
        for requirement in requirements
    ):
        return ""
    return (
        "\nboolean 해석 규칙:\n"
        "- relation은 질문의 긍정 명제입니다. 무관·어렵습니다·할 수 없음·"
        "포함되지 않음은 false입니다.\n"
        "- 삭제 기한 존재 여부에서 기간 무제한·기한 없음은 false입니다.\n"
        "- 긍정/부정 방향을 직접 확인할 수 없으면 unsupported로 두세요.\n"
    )
