"""Grounded answer generation with mechanical abstain and post-generation checking.

The language model is never asked to judge sufficiency, choose evidence, or decide
whether a requirement is answerable. Those stay mechanical:

1. ``partition_requirements`` uses the frozen value-shape contract to split requirements
   into generatable (the cited spans actually carry the requested value) and
   non-generatable (they do not). Non-generatable requirements are reported as
   "not confirmable from the documents" and are never sent to the model.
2. ``build_generation_request`` packs only the question, requirement labels and
   either exact cited spans or mechanically bound table attribute/value units.
   Gold, full chunks and evidence groups are never included.
3. ``verify_generated_answer`` re-checks the produced text: every factual token
   (numbers with units, percentages, dates, clock times) must already appear in the
   evidence, and every selected table value token must appear in the answer.

A failed verification is not repaired by the model. The caller falls back to the
existing extractive citation output.
"""

from __future__ import annotations

import re
from typing import Any

from src.v3.requirement_value_shape import apply_value_shape_veto

GENERATOR_CONTRACT_VERSION = "grounded-answer-generator-v1.1.0"

_COST_CONTEXT_MARKERS = (
    "price",
    "cost",
    "cash_value",
    "\uac00\uaca9",
    "\ube44\uc6a9",
    "\ud310\ub9e4\uac00",
    "\uc218\uc218\ub8cc",
    "\uace8\ub4dc",
    "\uc138\ub77c",
    "\ucf54\uc778",
    "\ub9c8\uc77c\ub9ac\uc9c0",
)
UNCONFIRMABLE_MESSAGE = "문서에서 확인할 수 없습니다."

SYSTEM_PROMPT = (
    "당신은 공식 문서에서 이미 선별된 인용문만으로 한국어 답변을 작성합니다.\n"
    "규칙:\n"
    "1. 제공된 인용문에 없는 사실, 숫자, 날짜, 이름을 절대 추가하지 마세요.\n"
    "2. 인용문의 수치와 날짜는 표기를 바꾸지 말고 그대로 사용하세요.\n"
    "3. 추측하거나 일반 상식으로 보충하지 마세요.\n"
    "4. 각 요구사항에 대해 한두 문장으로 간결하게 답하세요.\n"
    "5. 인용문이 요구사항에 답하지 못하면 그 요구는 답하지 마세요."
)
TABLE_VALUE_SYSTEM_PROMPT = (
    "\nStructured units marked [TABLE VALUE] were already selected mechanically "
    "for the requirement. Do not judge support or reinterpret column positions. "
    "Render every attribute = value pair once, preserving each value and unit exactly."
)

# Factual tokens the model must not invent. Ordered so longer units win.
_UNIT = (
    r"%|퍼센트|골드|세라|마일리지|포인트|개월|개|회|번|명|일|년|주|시간|분|초|"
    r"원|위|레벨|Lv|GB|MB|KB"
)
_NUMBER = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
_FACT_PATTERNS = (
    re.compile(rf"(?:{_NUMBER})\s*(?:{_UNIT})"),
    re.compile(r"\d{4}\s*[년./-]\s*\d{1,2}\s*[월./-]\s*\d{1,2}\s*일?"),
    re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d{1,2}\s*[./]\s*\d{1,2}"),
    re.compile(r"(?:오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?"),
    re.compile(r"\d{1,2}:\d{2}"),
)


def _normalize(text: str) -> str:
    """Collapse whitespace so ``100,000 골드`` and ``100,000골드`` compare equal."""
    return re.sub(r"\s+", "", text)


def extract_factual_tokens(text: str) -> list[str]:
    """Return every number-bearing token a grounded answer must not invent."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _FACT_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0).strip()
            key = _normalize(token)
            if key and key not in seen:
                seen.add(key)
                found.append(token)
    return found


def cited_span_texts(decisions: list[dict[str, Any]]) -> list[str]:
    return [
        str(span.get("text") or "")
        for decision in decisions
        for span in decision.get("spans", [])
    ]


_SURFACE_TOKEN_RE = re.compile(r"[0-9A-Za-z\uac00-\ud7a3]+")
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "hundred": "100",
}


def _surface_tokens(value: Any) -> set[str]:
    return {
        token.lower()
        for token in _SURFACE_TOKEN_RE.findall(str(value or ""))
        if len(token) > 1
    }


def _surface_key(value: Any) -> str:
    return "".join(_SURFACE_TOKEN_RE.findall(str(value or "").lower()))


def _surface_match_score(left: Any, right: Any) -> tuple[int, int]:
    left_key = _surface_key(left)
    right_key = _surface_key(right)
    if not left_key or not right_key:
        return (0, 0)
    overlap = len(_surface_tokens(left) & _surface_tokens(right))
    if left_key == right_key:
        return (3, overlap)
    if left_key in right_key or right_key in left_key:
        return (2, overlap)
    if overlap:
        return (1, overlap)
    return (0, 0)


def _numeric_qualifiers(value: Any) -> set[str]:
    text = str(value or "").lower()
    output = set(re.findall(r"\d+", text))
    tokens = _surface_tokens(text)
    output.update(number for word, number in _NUMBER_WORDS.items() if word in tokens)
    return output


def _attribute_markers(relation: Any) -> tuple[str, ...]:
    key = _surface_key(relation)
    if any(
        marker in key
        for marker in (
            "price",
            "cost",
            "cashvalue",
            "\uac00\uaca9",
            "\ube44\uc6a9",
            "\ud310\ub9e4\uac00",
            "\uc218\uc218\ub8cc",
        )
    ):
        return (
            "price",
            "cost",
            "\uac00\uaca9",
            "\ube44\uc6a9",
            "\uace8\ub4dc",
            "\uc138\ub77c",
        )
    if any(
        marker in key
        for marker in (
            "transaction",
            "trade",
            "\uac70\ub798",
            "\uadc0\uc18d",
            "\uad50\ud658",
        )
    ):
        return (
            "transaction",
            "trade",
            "\uac70\ub798",
            "\uadc0\uc18d",
            "\uad50\ud658",
        )
    if any(
        marker in key
        for marker in (
            "delete",
            "deletion",
            "expiry",
            "expiration",
            "\uc0ad\uc81c",
            "\ub9cc\ub8cc",
        )
    ):
        return (
            "delete",
            "expiry",
            "\uc0ad\uc81c",
            "\ub9cc\ub8cc",
            "\uae30\uac04",
        )
    return ()


def _strong_surface_match(left: Any, right: Any) -> bool:
    score = _surface_match_score(left, right)
    return score[0] >= 2 or score[1] >= 2


def _cost_subject_aligned(
    requirement: dict[str, Any],
    spans: list[dict[str, Any]],
) -> bool:
    """Require a cost subject to occupy the entity cell, not the value cell.

    Only valid on table entity cells. The surface matcher does not strip Korean
    particles, so on prose spans "마일리지샵을" misses "마일리지샵" while a bare
    "2026.04.30 06:00" matches on "2026" -- reusing this to rank arbitrary spans was
    measured and reverted.
    """

    subject = str(requirement.get("subject") or "").strip()
    if not subject:
        return True
    pipe_subjects = []
    prose = []
    for span in spans:
        text = str(span.get("text") or "")
        for line in text.splitlines():
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            if len(cells) >= 2:
                pipe_subjects.append(cells[0])
            elif line.strip():
                prose.append(line.strip())
    candidates = pipe_subjects if pipe_subjects else prose
    return any(_strong_surface_match(subject, candidate) for candidate in candidates)


def table_value_spans(
    requirement: dict[str, Any], table_views: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Bind the best matching table row's columns to their values.

    The model receives explicit ``subject / attribute = value`` units instead of a
    positional Markdown row. Row support remains traceable to the exact source slice.
    """

    subject = str(requirement.get("subject") or "")
    relation = str(requirement.get("relation") or "")
    selection_surface = f"{subject} {relation}".strip()
    candidates: list[
        tuple[tuple[int, int, int, int], dict[str, Any], dict[str, Any]]
    ] = []
    for view in table_views:
        table_score = _surface_match_score(subject, view.get("table_subject"))
        for row in view.get("rows", []):
            row_score = _surface_match_score(
                selection_surface,
                row.get("subject"),
            )
            score = (*row_score, *table_score)
            if (
                row_score[0] >= 2 or row_score[1] >= 2
            ) and score > (0, 0, 0, 0):
                candidates.append((score, view, row))
    if not candidates:
        return []

    qualifiers = _numeric_qualifiers(relation)
    if qualifiers:
        qualified = [
            candidate
            for candidate in candidates
            if qualifiers <= _numeric_qualifiers(candidate[2].get("subject"))
        ]
        if not qualified:
            return []
        candidates = qualified

    best_score = max(score for score, _, _ in candidates)
    view, row = next(
        (view, row)
        for score, view, row in candidates
        if score == best_score
    )
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    values = row.get("values") or {}
    attributes = [
        attribute
        for attribute in view.get("attributes", values.keys())
        if values.get(attribute) is not None
    ]
    attribute_scores = {
        attribute: _surface_match_score(relation, attribute)
        for attribute in attributes
    }
    best_attribute_score = max(attribute_scores.values(), default=(0, 0))
    if best_attribute_score[0] > 0:
        attributes = [
            attribute
            for attribute in attributes
            if attribute_scores[attribute] == best_attribute_score
        ]
    else:
        markers = _attribute_markers(relation)
        explicit_cost_attribute = any(
            any(
                _surface_key(marker) in _surface_key(attribute)
                for marker in ("price", "cost", "\uac00\uaca9", "\ube44\uc6a9")
            )
            for attribute in attributes
        )
        cost_bundle = bool(
            markers
            and markers[0] == "price"
            and not explicit_cost_attribute
            and any(
                _surface_key(marker)
                in _surface_key(
                    f"{view.get('table_subject') or ''} "
                    f"{view.get('caption') or ''}"
                )
                for marker in ("price", "cost", "\uac00\uaca9", "\ube44\uc6a9")
            )
        )
        marked = [
            attribute
            for attribute in attributes
            if any(
                _surface_key(marker) in _surface_key(attribute)
                for marker in markers
            )
        ]
        if cost_bundle:
            pass
        elif marked:
            attributes = marked
        else:
            return []

    for attribute_index, attribute in enumerate(attributes, 1):
        value = str(values[attribute])
        source_chunk_id = str(row.get("source_chunk_id") or "")
        row_id = str(row.get("row_id") or "")
        key = (source_chunk_id, row_id, str(attribute), value)
        if key in seen:
            continue
        seen.add(key)
        row_subject = str(row.get("subject") or subject)
        output.append(
            {
                "span_id": (
                    f"table_value:{view.get('table_id')}:{row_id}:"
                    f"{attribute_index}"
                ),
                "chunk_id": source_chunk_id,
                "start_char": int(row.get("start_offset") or 0),
                "end_char": int(row.get("end_offset") or 0),
                "text": f"{row_subject} \u00b7 {attribute} = {value}",
                "evidence_kind": "table_attribute_value",
                "table_id": view.get("table_id"),
                "row_id": row_id,
                "attribute": attribute,
                "value": value,
                "exact_row_text": str(row.get("exact_row_text") or ""),
            }
        )
    return output


def apply_table_value_shape_gate(
    requirement: dict[str, Any],
    decision: dict[str, Any],
    table_views: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    table_spans = table_value_spans(requirement, table_views)
    enriched = {
        **decision,
        "spans": (
            table_spans
            if table_spans
            else [dict(span) for span in decision.get("spans", [])]
        ),
    }
    checked, audit = apply_value_shape_veto(requirement, enriched)
    evidence_text = "\n".join(
        str(span.get("text") or "") for span in enriched.get("spans", [])
    ).lower()
    cost_context_vetoed = bool(
        checked.get("status") == "supported_exact"
        and audit.get("expected_kind") == "cost_value"
        and not table_spans
        and "currency" not in audit.get("detected_kinds", [])
        and not any(marker in evidence_text for marker in _COST_CONTEXT_MARKERS)
    )
    cost_subject_alignment_vetoed = bool(
        checked.get("status") == "supported_exact"
        and audit.get("expected_kind") == "cost_value"
        and not table_spans
        and not _cost_subject_aligned(
            requirement,
            [dict(span) for span in enriched.get("spans", [])],
        )
    )
    cost_relation_vetoed = (
        cost_context_vetoed or cost_subject_alignment_vetoed
    )
    if cost_relation_vetoed:
        checked = {
            **checked,
            "status": "unsupported",
            "spans": [],
            "unsupported_message": (
                "\ubb38\uc11c\uc5d0\uc11c \uc694\uad6c\ud55c "
                "\uac00\uaca9\u00b7\ube44\uc6a9 \uad00\uacc4\ub97c "
                "\ud655\uc778\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
            ),
        }
    audit = {
        **audit,
        "b1_status": checked.get("status"),
        "vetoed": bool(audit.get("vetoed") or cost_relation_vetoed),
        "cost_relation_vetoed": cost_relation_vetoed,
        "cost_context_vetoed": cost_context_vetoed,
        "cost_subject_alignment_vetoed": cost_subject_alignment_vetoed,
        "table_value_span_count": len(table_spans),
        "table_value_row_ids": sorted(
            {span["row_id"] for span in table_spans}
        ),
    }
    return checked, audit


def partition_requirements(
    requirements: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    table_views_by_requirement: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Split requirements into generatable and unconfirmable, mechanically.

    A requirement is generatable only when it is already ``supported_exact`` and the
    value-shape contract does not veto it. Everything else is reported honestly and is
    never shown to the model.
    """

    if len(requirements) != len(decisions):
        raise RuntimeError("Requirement and decision counts differ")
    if table_views_by_requirement is None:
        table_views_by_requirement = [[] for _ in requirements]
    if len(requirements) != len(table_views_by_requirement):
        raise RuntimeError("Requirement and table-view counts differ")
    generatable: list[dict[str, Any]] = []
    unconfirmable: list[dict[str, Any]] = []
    for index, (requirement, decision, table_views) in enumerate(
        zip(
            requirements,
            decisions,
            table_views_by_requirement,
            strict=True,
        ),
        start=1,
    ):
        checked, audit = apply_table_value_shape_gate(
            requirement,
            decision,
            table_views,
        )
        entry = {
            "requirement_index": index,
            "requirement_id": requirement.get("requirement_id"),
            "subject": requirement.get("subject"),
            "relation": requirement.get("relation"),
            "expected_kind": audit["expected_kind"],
            "spans": [dict(span) for span in checked.get("spans", [])],
            "table_value_span_count": audit["table_value_span_count"],
        }
        if checked.get("status") == "supported_exact":
            generatable.append(entry)
        else:
            entry["reason"] = (
                "value_shape_absent_in_cited_spans"
                if audit["vetoed"]
                else str(decision.get("status"))
            )
            entry["message"] = UNCONFIRMABLE_MESSAGE
            unconfirmable.append(entry)
    return {
        "generator_contract_version": GENERATOR_CONTRACT_VERSION,
        "generatable": generatable,
        "unconfirmable": unconfirmable,
        "model_sees_gold": False,
    }


def build_generation_request(question: str, generatable: list[dict[str, Any]]) -> dict[str, Any]:
    """Pack only the question, requirement labels and selected evidence units."""
    blocks = []
    for entry in generatable:
        quotes = "\n".join(
            (
                "- [TABLE VALUE] "
                if span.get("evidence_kind") == "table_attribute_value"
                else "- "
            )
            + span["text"]
            for span in entry["spans"]
        )
        blocks.append(
            f"[요구 {entry['requirement_index']}] {entry.get('subject') or ''} · "
            f"{entry.get('relation') or ''}\n{quotes}"
        )
    user_prompt = (
        f"질문: {question}\n\n"
        "아래 인용문만 사용해 답하세요.\n\n" + "\n\n".join(blocks)
    )
    return {
        "system": (
            SYSTEM_PROMPT + TABLE_VALUE_SYSTEM_PROMPT
            if any(
                span.get("evidence_kind") == "table_attribute_value"
                for entry in generatable
                for span in entry["spans"]
            )
            else SYSTEM_PROMPT
        ),
        "user": user_prompt,
        "requirement_indices": [entry["requirement_index"] for entry in generatable],
    }


def verify_generated_answer(
    generated_text: str, generatable: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reject invented tokens and omitted mechanically selected table values."""
    allowed = _normalize(" ".join(span["text"] for entry in generatable for span in entry["spans"]))
    generated = _normalize(generated_text)
    tokens = extract_factual_tokens(generated_text)
    unsupported = [token for token in tokens if _normalize(token) not in allowed]
    required_tokens: list[str] = []
    seen_required: set[str] = set()
    for entry in generatable:
        for span in entry["spans"]:
            if span.get("evidence_kind") != "table_attribute_value":
                continue
            for token in extract_factual_tokens(str(span.get("value") or "")):
                key = _normalize(token)
                if key and key not in seen_required:
                    seen_required.add(key)
                    required_tokens.append(token)
    missing_required = [
        token for token in required_tokens if _normalize(token) not in generated
    ]
    return {
        "verified": not unsupported and not missing_required,
        "checked_token_count": len(tokens),
        "unsupported_tokens": unsupported,
        "required_token_count": len(required_tokens),
        "missing_required_tokens": missing_required,
        "verifier_contract_version": GENERATOR_CONTRACT_VERSION,
    }


def expand_spans_to_parent_chunks(
    entries: list[dict[str, Any]],
    chunk_text_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    """Replace extractive spans with their whole parent chunk, keeping table units.

    This is the standard-RAG evidence scope: hand the model the retrieved passage and
    let it locate the value, instead of locating it mechanically first. Table
    attribute/value units are left alone because ``verify_generated_answer`` requires
    each selected table value to appear in the answer.

    Applied to assembler decisions before ``partition_requirements``, so the
    value-shape gate also judges the widened evidence. Applying it afterwards would
    leave the gate abstaining on the narrow span, and the model would never see the
    chunk in exactly the cases this scope exists to reach.
    """

    output = []
    for entry in entries:
        table_spans = [
            span
            for span in entry["spans"]
            if span.get("evidence_kind") == "table_attribute_value"
        ]
        chunk_ids: list[str] = []
        for span in entry["spans"]:
            chunk_id = span.get("chunk_id")
            if span.get("evidence_kind") == "table_attribute_value" or not chunk_id:
                continue
            if chunk_id in chunk_text_by_id and chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
        expanded = [
            {
                "chunk_id": chunk_id,
                "text": chunk_text_by_id[chunk_id],
                "evidence_kind": "parent_chunk",
            }
            for chunk_id in chunk_ids
        ]
        spans = table_spans + expanded
        item = dict(entry)
        item["spans"] = spans if spans else entry["spans"]
        output.append(item)
    return output


def compose_answer(
    *,
    question: str,
    requirements: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    table_views_by_requirement: list[list[dict[str, Any]]] | None = None,
    chunk_text_by_id: dict[str, str] | None = None,
    generate: Any,
) -> dict[str, Any]:
    """Run the full mechanical-gate → generate → mechanical-check pipeline.

    ``generate`` is any callable taking the request dict and returning text. It is kept
    injectable so tests never need a live model.

    ``chunk_text_by_id`` widens the evidence given to the model from the selected spans
    to their whole parent chunks. Omitted, nothing changes.
    """

    if chunk_text_by_id:
        decisions = expand_spans_to_parent_chunks(decisions, chunk_text_by_id)
    partition = partition_requirements(
        requirements,
        decisions,
        table_views_by_requirement=table_views_by_requirement,
    )
    generatable = partition["generatable"]
    if not generatable:
        return {
            **partition,
            "mode": "abstain",
            "answer_text": UNCONFIRMABLE_MESSAGE,
            "verification": None,
            "used_generated_text": False,
        }
    request = build_generation_request(question, generatable)
    generated_text = str(generate(request) or "").strip()
    verification = verify_generated_answer(generated_text, generatable)
    used = bool(generated_text) and verification["verified"]
    return {
        **partition,
        "mode": "generated" if used else "extractive_fallback",
        "answer_text": generated_text if used else "",
        "verification": verification,
        "used_generated_text": used,
    }


def compose_backbone_answer(
    backbone_result: dict[str, Any],
    *,
    generate: Any,
    chunk_text_by_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compose from the public demo result, including per-requirement table views."""

    requirements = []
    decisions = []
    table_views_by_requirement = []
    for item in backbone_result.get("requirements", []):
        requirements.append(dict(item["requirement"]))
        decisions.append(
            {
                "status": (
                    "supported_exact"
                    if item.get("status") == "supported"
                    else str(item.get("status") or "unsupported")
                ),
                "spans": [
                    dict(citation)
                    for citation in item.get("citations", [])
                ],
            }
        )
        table_views_by_requirement.append(
            [dict(view) for view in item.get("table_views", [])]
        )
    return compose_answer(
        question=str(backbone_result.get("question") or ""),
        requirements=requirements,
        decisions=decisions,
        table_views_by_requirement=table_views_by_requirement,
        chunk_text_by_id=chunk_text_by_id,
        generate=generate,
    )
