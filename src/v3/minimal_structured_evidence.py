from __future__ import annotations

import json
import re
from typing import Any, Callable


_LINE = re.compile(r"[^\r\n]+")
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_ORDINAL_HEADERS = ("1차", "2차", "3차", "4차", "5차")
_RELATION_COLUMNS = {
    "first_penalty": ("1차",),
    "second_penalty": ("2차",),
    "third_penalty": ("3차",),
    "fourth_penalty": ("4차",),
    "price": ("가격", "판매가", "판매가격"),
    "trade_type": ("거래타입", "거래유형"),
    "purchase_limit": ("구매제한", "구매조건"),
    "deletion_at": ("삭제일", "삭제시각", "삭제일시"),
    "sale_period": ("판매기간",),
}
_GENERIC_SUBJECT_TOKENS = frozenset(
    {
        "관련",
        "기준",
        "행위",
        "이용제한",
        "제한",
    }
)


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _scope_from_cells(cells: list[str]) -> str | None:
    text = " ".join(cells)
    if "커뮤니티 이용제한" in text or any(
        "게시물" in cell for cell in cells[1:]
    ):
        return "community"
    if (
        "게임 내 이용제한" in text
        or "게임 이용제한" in text
        or any("계정" in cell for cell in cells[1:])
    ):
        return "game_account"
    return None


def _header_row(cells: list[str]) -> bool:
    normalized = {_compact(cell) for cell in cells}
    return bool(
        normalized & {_compact(value) for value in _ORDINAL_HEADERS}
    )


def _restriction_values(cells: list[str]) -> bool:
    return len(cells) >= 2 and any(
        marker in " ".join(cells[1:])
        for marker in ("이용제한", "등록제한", "거래제한")
    )


def _row_fact(
    *,
    chunk_id: str,
    start_char: int,
    end_char: int,
    line: str,
    cells: list[str],
    headers: list[str],
    inherited_scope: str | None,
) -> dict[str, Any] | None:
    scope = _scope_from_cells(cells) or inherited_scope
    scope_lead = (
        len(cells) >= 3
        and "이용제한" in cells[0]
        and _restriction_values(cells[1:])
    )
    if scope_lead:
        subject_index = 1
        value_cells = cells[2:]
    else:
        subject_index = 0
        value_cells = cells[1:]
    if not value_cells:
        return None

    value_headers = headers[subject_index + 1 :]
    if len(value_headers) != len(value_cells):
        value_headers = list(_ORDINAL_HEADERS[: len(value_cells)])
    attributes = {
        header: value
        for header, value in zip(
            value_headers,
            value_cells,
            strict=True,
        )
        if header and value
    }
    if not attributes:
        return None
    return {
        "chunk_id": chunk_id,
        "start_char": start_char,
        "end_char": end_char,
        "text": line.strip(),
        "scope": scope,
        "row_subject": cells[subject_index],
        "attributes": attributes,
    }


def build_structured_rows_by_coordinate(
    candidate_chunk_ids: list[str],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[tuple[str, int, int], dict[str, Any]]:
    rows: dict[tuple[str, int, int], dict[str, Any]] = {}
    for chunk_id in dict.fromkeys(candidate_chunk_ids):
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        text = str(chunk.get("display_text") or "")
        headers: list[str] = []
        inherited_scope: str | None = None
        for match in _LINE.finditer(text):
            line = match.group(0)
            stripped = line.strip()
            if stripped == "[/TABLE]":
                headers = []
                inherited_scope = None
                continue
            if stripped.startswith("[") and "이용제한" in stripped:
                inherited_scope = (
                    "community"
                    if "커뮤니티" in stripped
                    else "game_account"
                )
                continue
            cells = _cells(stripped)
            if not cells:
                continue
            if _header_row(cells):
                headers = cells
                continue
            if not headers and not _restriction_values(cells):
                continue
            fact = _row_fact(
                chunk_id=chunk_id,
                start_char=match.start()
                + len(line)
                - len(line.lstrip()),
                end_char=match.end()
                - len(line)
                + len(line.rstrip()),
                line=stripped,
                cells=cells,
                headers=headers,
                inherited_scope=inherited_scope,
            )
            if fact is None:
                continue
            if fact["scope"]:
                inherited_scope = fact["scope"]
            rows[
                (
                    fact["chunk_id"],
                    fact["start_char"],
                    fact["end_char"],
                )
            ] = fact
    return rows


def annotate_prompt_with_structured_rows(
    prompt: str,
    *,
    evidence_units_by_ref: dict[str, dict[str, Any]],
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ],
) -> str:
    metadata_by_ref = {}
    for evidence_ref, unit in evidence_units_by_ref.items():
        fact = structured_rows_by_coordinate.get(
            (
                unit["chunk_id"],
                unit["start_char"],
                unit["end_char"],
            )
        )
        if fact is None:
            continue
        metadata_by_ref[evidence_ref] = (
            "structured="
            + json.dumps(
                {
                    "scope": fact["scope"],
                    "row_subject": fact["row_subject"],
                    "attributes": fact["attributes"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    if not metadata_by_ref:
        return prompt
    lines = []
    for line in prompt.splitlines():
        evidence_ref = line.split("\t", 1)[0]
        metadata = metadata_by_ref.get(evidence_ref)
        if metadata:
            line = f"{evidence_ref}\t{metadata}\t" + line.split("\t", 1)[1]
        lines.append(line)
    return "\n".join(lines)


def _subject_matches(subject: str, row_subject: str) -> bool:
    terms = [
        _compact(token)
        for token in _TOKEN.findall(subject)
        if len(_compact(token)) >= 2
        and _compact(token) not in _GENERIC_SUBJECT_TOKENS
    ]
    observed = _compact(row_subject)
    return bool(terms) and all(term in observed for term in terms)


def verify_structured_row_binding(
    requirement: dict[str, Any],
    value: Any,
    selected_units: list[dict[str, Any]],
    *,
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ],
    value_matches: Callable[[Any, str], bool],
) -> dict[str, Any]:
    relation = str(requirement.get("relation") or "")
    requested_columns = _RELATION_COLUMNS.get(relation)
    if not requested_columns:
        return {"state": "not_applicable", "failures": [], "facts": []}

    selected_facts = []
    for unit in selected_units:
        fact = structured_rows_by_coordinate.get(
            (
                unit["chunk_id"],
                unit["start_char"],
                unit["end_char"],
            )
        )
        if fact is not None:
            selected_facts.append(fact)
    if not selected_facts:
        return {"state": "not_applicable", "failures": [], "facts": []}

    failures = []
    fact_audits = []
    for fact in selected_facts:
        attribute = next(
            (
                name
                for name in requested_columns
                if _compact(name)
                in {_compact(key) for key in fact["attributes"]}
            ),
            None,
        )
        attribute_value = (
            next(
                value
                for key, value in fact["attributes"].items()
                if attribute is not None
                and _compact(key) == _compact(attribute)
            )
            if attribute is not None
            else None
        )
        fact_failures = []
        if not _subject_matches(
            str(requirement.get("subject") or ""),
            fact["row_subject"],
        ):
            fact_failures.append("structured_row_subject_mismatch")
        if attribute is None:
            fact_failures.append("structured_column_mismatch")
        if (
            relation == "first_penalty"
            and fact["scope"] == "community"
        ):
            fact_failures.append("structured_scope_mismatch")
        if attribute_value is not None and not value_matches(
            value,
            attribute_value,
        ):
            fact_failures.append("structured_value_mismatch")
        failures.extend(fact_failures)
        fact_audits.append(
            {
                "scope": fact["scope"],
                "row_subject": fact["row_subject"],
                "column": attribute,
                "column_value": attribute_value,
                "failures": fact_failures,
            }
        )
    return {
        "state": "matched" if not failures else "mismatch",
        "failures": sorted(set(failures)),
        "facts": fact_audits,
    }
