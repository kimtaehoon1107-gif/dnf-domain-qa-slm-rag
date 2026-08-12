from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from src.v3.answer_target_router import _base_tag, _kiwi
from src.v3.product_evidence_pack import (
    content_kind_table_row_present,
    explicit_question_subjects,
)
from src.v3.product_question_semantics import comparison_requested
from src.v3.simple_evidence_refs import (
    _chunk_atomic_units,
    _compact_char_ngrams,
)


_NOMINAL_TAGS = {"NNG", "NNP", "NNB", "NR", "NP", "SL", "SH", "SN"}
_MARKER_TO_AVAILABILITY = {"-": False, "X": False, "O": True}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _comparison_label(value: str) -> str:
    tokens = list(_kiwi().tokenize(value))
    nominal_indexes = [
        index
        for index, token in enumerate(tokens)
        if _base_tag(token) in _NOMINAL_TAGS
        and str(token.form).strip()
    ]
    if not nominal_indexes:
        return re.sub(r"[^0-9A-Za-z가-힣]+", "", value)
    index = nominal_indexes[-1]
    parts = [str(tokens[index].form).strip()]
    if (
        _base_tag(tokens[index]) != "SN"
        and index > 0
        and _base_tag(tokens[index - 1]) == "SN"
    ):
        parts.insert(0, str(tokens[index - 1].form).strip())
        if (
            index > 1
            and str(tokens[index - 2].form).strip() == "제"
            and _base_tag(tokens[index - 2]) in {"MM", "XPN"}
        ):
            parts.insert(0, "제")
    return "".join(parts)


def comparison_labels(question: str) -> list[str]:
    if not comparison_requested(question):
        return []
    subjects = explicit_question_subjects(question)
    if len(subjects) < 2:
        return []
    labels = []
    for subject in subjects[:2]:
        label = _comparison_label(subject)
        if not label:
            return []
        labels.append(label)
    return labels if len({_compact(label) for label in labels}) == 2 else []


def _comparison_label_candidates(value: str) -> list[str]:
    """Return surface suffixes that may correspond to a real table header."""

    candidates = []

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        compact = _compact(candidate)
        if candidate and compact not in {_compact(item) for item in candidates}:
            candidates.append(candidate)

    add(_comparison_label(value))
    words = value.split()
    for size in range(1, len(words) + 1):
        add(" ".join(words[-size:]))
    for token in reversed(list(_kiwi().tokenize(value))):
        if _base_tag(token) in _NOMINAL_TAGS:
            add(str(token.form))
    return candidates


def _resolved_comparison_labels(
    question: str,
    *,
    parent_ids: list[str],
    chunks_by_parent: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Resolve question surfaces against two distinct cells in one table header."""

    if not comparison_requested(question):
        return []
    question_compact = _compact(question)
    for parent_id in parent_ids:
        for chunk in sorted(
            chunks_by_parent.get(parent_id, []),
            key=lambda row: (
                int(row.get("chunk_index") or 0),
                int(row.get("start_offset") or 0),
                str(row.get("chunk_id") or ""),
            ),
        ):
            if not bool(chunk.get("default_exposure", False)):
                continue
            for _, _, line in _line_spans(str(chunk.get("display_text") or "")):
                cells = _cells(line)
                if len(cells) < 3:
                    continue
                normalized_cells = [_compact(cell) for cell in cells]
                direct_matches = [
                    (question_compact.find(cell), index, cells[index])
                    for index, cell in enumerate(normalized_cells[1:], 1)
                    if cell and cell in question_compact
                ]
                direct_matches = list(
                    {
                        (position, index, label)
                        for position, index, label in direct_matches
                    }
                )
                if len(direct_matches) == 2:
                    return [
                        label
                        for _, _, label in sorted(direct_matches)
                    ]
    subjects = explicit_question_subjects(question)
    if len(subjects) < 2:
        return []
    candidate_sets = [
        _comparison_label_candidates(subject)
        for subject in subjects[:2]
    ]
    for parent_id in parent_ids:
        for chunk in sorted(
            chunks_by_parent.get(parent_id, []),
            key=lambda row: (
                int(row.get("chunk_index") or 0),
                int(row.get("start_offset") or 0),
                str(row.get("chunk_id") or ""),
            ),
        ):
            if not bool(chunk.get("default_exposure", False)):
                continue
            for _, _, line in _line_spans(str(chunk.get("display_text") or "")):
                cells = _cells(line)
                if len(cells) < 3:
                    continue
                normalized_cells = [_compact(cell) for cell in cells]
                resolved = []
                for candidates in candidate_sets:
                    match = None
                    for candidate in candidates:
                        indexes = [
                            index
                            for index, cell in enumerate(normalized_cells[1:], 1)
                            if cell == _compact(candidate)
                        ]
                        if len(indexes) == 1:
                            match = (indexes[0], cells[indexes[0]])
                            break
                    if match is None:
                        resolved = []
                        break
                    resolved.append(match)
                if (
                    len(resolved) == 2
                    and resolved[0][0] != resolved[1][0]
                ):
                    return [resolved[0][1], resolved[1][1]]
    return comparison_labels(question)


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _line_spans(text: str) -> Iterable[tuple[int, int, str]]:
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        yield offset, offset + len(line), line
        offset += len(raw_line)


def _marker(value: str) -> bool | None:
    return _MARKER_TO_AVAILABILITY.get(value.strip().upper())


def _availability_units(
    labels: list[str],
    *,
    question: str,
    parent_ids: list[str],
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_labels = [_compact(label) for label in labels]
    output = []
    seen = set()
    for candidate_index, parent_id in enumerate(parent_ids, 1):
        document = documents_by_id[parent_id]
        temporal = temporal_by_document.get(parent_id, {})
        in_table = False
        table_anchor = ""
        table_intro = ""
        last_context_line = ""
        active_header = ""
        active_indexes: tuple[int, int] | None = None
        for chunk in sorted(
            chunks_by_parent.get(parent_id, []),
            key=lambda row: (
                int(row.get("chunk_index") or 0),
                int(row.get("start_offset") or 0),
                str(row.get("chunk_id") or ""),
            ),
        ):
            if not bool(chunk.get("default_exposure", False)):
                continue
            source_text = str(chunk.get("display_text") or "")
            for start, end, line in _line_spans(source_text):
                stripped = line.strip()
                if stripped == "[TABLE]":
                    in_table = True
                    table_anchor = ""
                    table_intro = last_context_line
                    active_header = ""
                    active_indexes = None
                    continue
                if stripped == "[/TABLE]":
                    in_table = False
                    table_anchor = ""
                    table_intro = ""
                    active_header = ""
                    active_indexes = None
                    continue
                if not in_table:
                    if stripped and not stripped.startswith("#"):
                        last_context_line = stripped
                    continue
                cells = _cells(stripped)
                if not cells:
                    continue
                normalized_cells = [_compact(cell) for cell in cells]
                if not table_anchor:
                    table_anchor = normalized_cells[0]
                positions = []
                for label in normalized_labels:
                    indexes = [
                        index
                        for index, cell in enumerate(normalized_cells)
                        if cell == label
                    ]
                    if len(indexes) != 1:
                        positions = []
                        break
                    positions.append(indexes[0])
                if (
                    len(positions) == 2
                    and normalized_cells[0] == table_anchor
                ):
                    active_header = stripped
                    active_indexes = (positions[0], positions[1])
                    continue
                if active_indexes is None or max(active_indexes) >= len(cells):
                    continue
                raw_values = (
                    cells[active_indexes[0]],
                    cells[active_indexes[1]],
                )
                marker_values = (_marker(raw_values[0]), _marker(raw_values[1]))
                if any(value is None for value in marker_values):
                    continue
                subject = next(
                    (
                        cell
                        for cell in cells[: min(active_indexes)]
                        if cell and _marker(cell) is None
                    ),
                    "",
                )
                if not subject:
                    continue
                if (
                    marker_values[0] == marker_values[1]
                    and _compact(subject) not in _compact(question)
                ):
                    continue
                key = (
                    parent_id,
                    _compact(subject),
                    raw_values[0].upper(),
                    raw_values[1].upper(),
                )
                if key in seen:
                    continue
                seen.add(key)
                availability = dict(
                    zip(labels, marker_values, strict=True)
                )
                semantic = ", ".join(
                    f"{label} 획득 {'가능' if availability[label] else '불가'}"
                    for label in labels
                )
                heading = " > ".join(
                    str(value).strip()
                    for value in chunk.get("heading_path") or []
                    if str(value).strip()
                )
                output.append(
                    {
                        "candidate_ref": str(candidate_index),
                        "chunk_id": str(chunk["chunk_id"]),
                        "parent_document_id": parent_id,
                        "source_id": document.get("source_id"),
                        "title": document.get("title") or "",
                        "published_at": document.get("published_at"),
                        "valid_from": temporal.get(
                            "valid_from", document.get("valid_from")
                        ),
                        "valid_to": temporal.get(
                            "valid_to", document.get("valid_to")
                        ),
                        "revision_id": document.get("revision_id"),
                        "status": temporal.get(
                            "status", document.get("status") or chunk.get("status")
                        ),
                        "start_char": start,
                        "end_char": end,
                        "text": line,
                        "context_text": " > ".join(
                            value
                            for value in (
                                heading,
                                table_intro,
                                f"표 열: {active_header}",
                                f"열 해석: {subject}: {semantic}",
                            )
                            if value
                        ),
                        "unit_kind": "table_row",
                        "table_intro": table_intro,
                        "availability_subject": subject,
                        "availability_values": availability,
                    }
                )
    return output


def _quantity_units(
    labels: list[str],
    *,
    parent_ids: list[str],
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    units = []
    seen_texts = set()
    for candidate_index, parent_id in enumerate(parent_ids, 1):
        document = documents_by_id[parent_id]
        temporal = temporal_by_document.get(parent_id, {})
        for chunk in chunks_by_parent.get(parent_id, []):
            if not bool(chunk.get("default_exposure", False)):
                continue
            for unit in _chunk_atomic_units(
                candidate_index=candidate_index,
                chunk_id=str(chunk["chunk_id"]),
                chunk=chunk,
                document=document,
                temporal=temporal,
            ):
                if unit.get("unit_kind") != "table_row":
                    continue
                compact = _compact(str(unit.get("text") or ""))
                if not re.search(r"\d", compact):
                    continue
                if not all(f"{_compact(label)}:" in compact for label in labels):
                    continue
                labeled_values = {}
                row_cells = _cells(str(unit.get("text") or ""))
                for cell in row_cells:
                    if ":" not in cell:
                        continue
                    raw_label, raw_value = cell.split(":", 1)
                    for label in labels:
                        if _compact(raw_label) == _compact(label):
                            labeled_values[label] = raw_value.strip()
                marker_values = {
                    label: _marker(value)
                    for label, value in labeled_values.items()
                }
                if len(marker_values) == 2 and all(
                    value is not None for value in marker_values.values()
                ):
                    subject = next(
                        (
                            cell
                            for cell in row_cells
                            if cell and ":" not in cell and _marker(cell) is None
                        ),
                        "",
                    )
                    if subject:
                        unit = {
                            **unit,
                            "availability_subject": subject,
                            "availability_values": marker_values,
                            "context_text": " > ".join(
                                value
                                for value in (
                                    str(unit.get("context_text") or ""),
                                    "열 해석: "
                                    + subject
                                    + ": "
                                    + ", ".join(
                                        f"{label} 획득 "
                                        f"{'가능' if marker_values[label] else '불가'}"
                                        for label in labels
                                    ),
                                )
                                if value
                            ),
                        }
                if len(labeled_values) == 2:
                    subject = next(
                        (
                            cell
                            for cell in row_cells
                            if cell and ":" not in cell and _marker(cell) is None
                        ),
                        "",
                    )
                    if subject:
                        unit = {
                            **unit,
                            "model_text": "| "
                            + " | ".join(
                                [
                                    subject,
                                    *(
                                        f"{label}: {labeled_values[label]}"
                                        for label in labels
                                    ),
                                ]
                            )
                            + " |",
                        }
                if compact in seen_texts:
                    continue
                seen_texts.add(compact)
                units.append(unit)
    return units


def _rank_units(
    question: str,
    units: list[dict[str, Any]],
    score_pairs: Callable[[list[tuple[str, str]]], list[float]],
) -> list[dict[str, Any]]:
    if not units:
        return []
    texts = [
        "\n".join(
            value
            for value in (
                str(unit.get("title") or ""),
                str(unit.get("context_text") or ""),
                str(unit.get("text") or ""),
            )
            if value
        )
        for unit in units
    ]
    scores = list(score_pairs([(question, text) for text in texts]))
    if len(scores) != len(units):
        raise RuntimeError("table comparison score count mismatch")
    return [
        units[index]
        for index in sorted(
            range(len(units)),
            key=lambda index: (
                -float(scores[index]),
                int(units[index].get("candidate_ref") or 0),
                int(units[index].get("start_char") or 0),
            ),
        )
    ]


def _filter_context_disambiguated_units(
    question: str,
    units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, tuple[str, ...]], list[int]] = {}
    for index, unit in enumerate(units):
        subject = str(unit.get("availability_subject") or "").strip()
        values = unit.get("availability_values")
        if not subject or not isinstance(values, dict):
            continue
        key = (
            str(unit.get("parent_document_id") or ""),
            _compact(subject),
            tuple(sorted(_compact(label) for label in values)),
        )
        groups.setdefault(key, []).append(index)
    keep = set(range(len(units)))
    question_ngrams = _compact_char_ngrams(question)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        intro_ngrams = [
            _compact_char_ngrams(str(units[index].get("table_intro") or ""))
            for index in indexes
        ]
        if not all(intro_ngrams):
            continue
        shared = set.intersection(*intro_ngrams)
        scores = [
            len((ngrams - shared) & question_ngrams)
            for ngrams in intro_ngrams
        ]
        best = max(scores)
        winners = [
            index for index, score in zip(indexes, scores) if score == best
        ]
        if best < 1 or len(winners) != 1:
            continue
        keep.difference_update(indexes)
        keep.add(winners[0])
    return [unit for index, unit in enumerate(units) if index in keep]


def build_table_comparison_reservation(
    question: str,
    *,
    parent_ids: list[str],
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    score_pairs: Callable[[list[tuple[str, str]]], list[float]],
    max_reserved: int = 4,
) -> list[dict[str, Any]]:
    labels = _resolved_comparison_labels(
        question,
        parent_ids=parent_ids,
        chunks_by_parent=chunks_by_parent,
    )
    if len(labels) != 2 or max_reserved < 1:
        return []
    availability = _rank_units(
        question,
        _filter_context_disambiguated_units(
            question,
            _availability_units(
                labels,
                question=question,
                parent_ids=parent_ids,
                chunks_by_parent=chunks_by_parent,
                documents_by_id=documents_by_id,
                temporal_by_document=temporal_by_document,
            ),
        ),
        score_pairs,
    )
    quantities = _rank_units(
        question,
        _quantity_units(
            labels,
            parent_ids=parent_ids,
            chunks_by_parent=chunks_by_parent,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
        ),
        score_pairs,
    )
    per_kind = max(1, max_reserved // 2)
    selected = [*availability[:per_kind], *quantities[:per_kind]]
    selected_ids = {id(unit) for unit in selected}
    for unit in [*availability, *quantities]:
        if len(selected) >= max_reserved:
            break
        if id(unit) in selected_ids:
            continue
        selected.append(unit)
        selected_ids.add(id(unit))
    return [
        {**unit, "question_focus": question}
        for unit in selected[:max_reserved]
    ]


def merge_table_comparison_reservation(
    reserved: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
    *,
    max_units: int = 8,
) -> list[dict[str, Any]]:
    selected = []
    seen_coordinates = set()
    seen_texts = set()
    for unit in [*reserved, *semantic]:
        coordinate = (
            str(unit.get("chunk_id") or ""),
            int(unit.get("start_char") or 0),
            int(unit.get("end_char") or 0),
        )
        text_key = " ".join(str(unit.get("text") or "").casefold().split())
        if coordinate in seen_coordinates or (
            text_key and text_key in seen_texts
        ):
            continue
        selected.append(unit)
        seen_coordinates.add(coordinate)
        if text_key:
            seen_texts.add(text_key)
        if len(selected) >= max_units:
            break
    return [
        {**unit, "evidence_ref": f"E{index}"}
        for index, unit in enumerate(selected, 1)
    ]


def build_server_availability_output(
    evidence_units: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Render only unambiguous two-axis O/X table rows without Qwen."""

    if not evidence_units:
        return None
    claims = []
    seen_subjects = set()
    for unit in evidence_units:
        evidence_ref = str(unit.get("evidence_ref") or "").strip()
        subject = str(unit.get("availability_subject") or "").strip()
        values = unit.get("availability_values")
        if (
            not evidence_ref
            or not subject
            or unit.get("unit_kind") != "table_row"
            or not isinstance(values, dict)
            or len(values) != 2
            or any(type(value) is not bool for value in values.values())
        ):
            return None
        labels = [str(label).strip() for label in values]
        if any(not label for label in labels) or len(
            {_compact(label) for label in labels}
        ) != 2:
            return None
        subject_key = (
            str(unit.get("parent_document_id") or ""),
            _compact(subject),
            tuple(sorted(_compact(label) for label in labels)),
        )
        if subject_key in seen_subjects:
            return None
        seen_subjects.add(subject_key)
        rendered_values = ", ".join(
            f"{label} 획득 {'가능' if values[label] else '불가'}"
            for label in labels
        )
        claims.append(
            {
                "text": f"{subject}: {rendered_values}.",
                "evidence_refs": [evidence_ref],
            }
        )
    return {
        "mode": "answer",
        "claims": claims,
        "clarification": "",
    }


def build_server_content_kind_output(
    question: str,
    evidence_units: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Render one complete content-kind row without generative rewriting."""

    matching = [
        unit
        for unit in evidence_units
        if unit.get("complete_category")
        and unit.get("unit_kind") == "table_row"
        and str(unit.get("evidence_ref") or "").strip()
        and content_kind_table_row_present(
            question,
            str(unit.get("text") or ""),
        )
    ]
    if len(matching) != 1:
        return None
    unit = matching[0]
    cells = _cells(str(unit.get("text") or ""))
    if len(cells) < 3 or any(not cell for cell in cells):
        return None
    title = str(unit.get("title") or "").strip()
    label, values = cells[0], cells[1:]
    subject = f"{title}의 {label}" if title else label
    return {
        "mode": "answer",
        "claims": [
            {
                "text": f"{subject}는 {', '.join(values)}로 구분됩니다.",
                "evidence_refs": [str(unit["evidence_ref"])],
            }
        ],
        "clarification": "",
    }
