from __future__ import annotations

import re
from typing import Any

from src.v3.answer_target_router import (
    NOMINAL_MODIFIER_TAGS,
    _base_tag,
    _clause_boundaries,
    _is_nominal_tag,
    _kiwi,
)
from src.v3.simple_evidence_refs import (
    _chunk_atomic_units,
    _compact_char_ngrams,
    _compact_tokens,
    _unit_metadata,
)

_TABLE_CUES = ("표", "전부", "전체", "목록")
_COMPLETE_LIST_CUES = ("조건", "종류", "전부", "전체", "목록")
_SURFACE_SEPARATOR = re.compile(
    r"\s*(?:[?？]|,|그리고|및|"
    r"(?<=[가-힣0-9)\]}'\"’”」』】])"
    r"(?:와|과|이랑|랑|하고)(?=\s))\s*"
)
_SURFACE_CONJUNCTION = re.compile(r"(?:와|과|이랑|랑|하고)\s+")
_INTERNAL_QUESTION_BOUNDARY = re.compile(r"[?？]\s+(?=\S)")
_EXPLICIT_DATE = re.compile(
    r"(?<!\d)20\d{2}\s*년\s*\d{1,2}\s*월"
    r"(?:\s*\d{1,2}\s*일)?"
    r"|(?<!\d)20\d{2}[./-]\d{1,2}[./-]\d{1,2}(?!\d)"
)
_TOPIC_SUBJECT = re.compile(r"^(.{2,40}?)(?:은|는)\s+")
_NOMINATIVE_SUBJECT = re.compile(r"^(.{1,36}?)(?:이|가)\s+")
_NUMBERED_LIST_ITEM = re.compile(
    r"^\s*(?:\d{1,2}[.)]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*"
)
_TRAILING_COORDINATION = re.compile(r"(?:와|과|이랑|랑|하고)$")
_HEADER_PUBLISHED_TIMESTAMP = re.compile(
    r"20\d{2}[.]\d{2}[.]\d{2}\s+\d{1,2}:\d{2}"
)
_HEADER_VIEW_COUNT = re.compile(r"\d{1,3}(?:,\d{3})+")
_PUBLISHED_TIMESTAMP_QUESTION = re.compile(
    r"(?:게시|게재|등록|공지)\S*\s*"
    r"(?:언제|시점|시각|시간|날짜)"
    r"|(?:언제|시점|시각|시간|날짜)\S*\s*"
    r"(?:게시|게재|등록|공지)"
)


def _focus_without_explicit_date(value: str) -> str:
    return " ".join(_EXPLICIT_DATE.sub(" ", value).split())


def _relation_tail(value: str) -> str:
    possessive = value.find("의 ")
    if possessive >= 0:
        return value[possessive + 2 :].strip()
    tokens = value.split()
    if len(tokens) <= 1:
        return value
    return " ".join(tokens[-min(4, len(tokens) - 1) :])


def _surface_subjects(question: str) -> list[str] | None:
    if "표" in question:
        return None
    normalized = " ".join(str(question or "").split())
    parts = [
        part.strip(" ?.")
        for part in _SURFACE_SEPARATOR.split(normalized)
        if len(part.strip(" ?.")) >= 2
    ]
    if len(parts) < 2:
        return None
    if not _SURFACE_CONJUNCTION.search(normalized):
        anchor = parts[0]
        if "의 " not in anchor:
            return None
        return [_focus_without_explicit_date(anchor.rsplit("의 ", 1)[0])]
    subjects = []
    for index, part in enumerate(parts):
        if index >= 2:
            subjects.append("")
            continue
        if "의 " in part:
            subject = part.rsplit("의 ", 1)[0]
        elif index == 0:
            subject = part
        else:
            tokens = part.split()
            subject = tokens[0] if tokens else ""
        subjects.append(_focus_without_explicit_date(subject))
    return subjects


def explicit_question_subjects(question: str) -> list[str]:
    """Return only subjects explicit in coordination or a short topic phrase."""

    normalized = _focus_without_explicit_date(
        " ".join(str(question or "").split())
    )
    if not normalized or "표" in normalized:
        return []
    parts = [
        part.strip(" ?.")
        for part in _SURFACE_SEPARATOR.split(normalized)
        if len(part.strip(" ?.")) >= 2
    ]
    if len(parts) >= 2 and _SURFACE_CONJUNCTION.search(normalized):
        first = parts[0]
        if "에서 " in first:
            first = first.rsplit("에서 ", 1)[1]
        second = parts[1]
        if "의 " in second:
            second = second.rsplit("의 ", 1)[0]
        else:
            second = second.split()[0]
        subjects = [first.strip(), second.strip()]
        if all(2 <= len(subject) <= 24 for subject in subjects):
            return subjects
    topic = _TOPIC_SUBJECT.match(normalized) or _NOMINATIVE_SUBJECT.match(
        normalized
    )
    if topic:
        subject = topic.group(1).strip()
        for separator in ("에서 ", "에는 ", "에선 "):
            if separator in subject:
                subject = subject.rsplit(separator, 1)[1].strip()
        if 2 <= len(subject) <= 24:
            return [subject]
    return []


def explicit_nominative_question_subjects(question: str) -> list[str]:
    """Return one literal 이/가 subject; avoid broad topic inference."""

    normalized = _focus_without_explicit_date(
        " ".join(str(question or "").split())
    )
    tokens = list(_kiwi().tokenize(normalized))
    for particle_index, particle in enumerate(tokens):
        if _base_tag(particle) != "JKS":
            continue
        phrase_start = particle_index
        while phrase_start > 0:
            tag = _base_tag(tokens[phrase_start - 1])
            if _is_nominal_tag(tag) or tag in NOMINAL_MODIFIER_TAGS:
                phrase_start -= 1
                continue
            break
        phrase = tokens[phrase_start:particle_index]
        if not phrase or int(phrase[0].start) != 0:
            continue
        subject = normalized[
            int(phrase[0].start) : int(particle.start)
        ].strip()
        return [subject] if 2 <= len(subject) <= 24 else []
    return []


def _kiwi_independent_clause_parts(question: str) -> list[str]:
    normalized = " ".join(str(question or "").split())
    tokens = list(_kiwi().tokenize(normalized))
    boundaries = [
        boundary
        for boundary in _clause_boundaries(tokens)
        if str(tokens[boundary].form) == "고"
    ]
    if not boundaries:
        return []
    parts = []
    start_char = 0
    for boundary in boundaries:
        connective = tokens[boundary]
        part = normalized[start_char : int(connective.start)].strip(" ?.")
        if len(part) >= 2:
            parts.append(part)
        start_char = int(connective.start) + int(connective.len)
    final = normalized[start_char:].strip(" ?.")
    if len(final) >= 2:
        parts.append(final)
    return parts if len(parts) >= 2 else []


def _kiwi_shared_topic_anchor(question: str) -> str:
    normalized = " ".join(str(question or "").split())
    tokens = list(_kiwi().tokenize(normalized))
    boundaries = [
        boundary
        for boundary in _clause_boundaries(tokens)
        if str(tokens[boundary].form) == "고"
    ]
    if not boundaries:
        return ""
    first_boundary = boundaries[0]
    particles = [
        token
        for token in tokens[:first_boundary]
        if (
            _base_tag(token) in {"JKS", "JX"}
            and str(token.form) in {"은", "는", "이", "가"}
        )
    ]
    if not particles:
        return ""
    return normalized[: int(particles[-1].start)].strip()


def _complete_kiwi_open_verb_clause(part: str) -> str:
    tokens = list(_kiwi().tokenize(part))
    for token in reversed(tokens):
        tag = _base_tag(token)
        if tag in {"VV", "VX", "XSV"}:
            return f"{part}는지"
        if tag in {"VA", "XSA", "VCP", "VCN"}:
            return part
    return part


def kiwi_independent_requirement_queries(question: str) -> list[str]:
    """Return only Kiwi-confirmed independent clauses for retrieval."""

    normalized = " ".join(str(question or "").split())
    parts = _kiwi_independent_clause_parts(normalized)
    if not parts:
        return []
    parts = [
        *(
            _complete_kiwi_open_verb_clause(part)
            for part in parts[:-1]
        ),
        parts[-1],
    ]
    anchor = _kiwi_shared_topic_anchor(normalized)
    first_part = parts[0]
    if anchor and first_part.startswith(anchor):
        tail = first_part[len(anchor) :].lstrip()
        if tail[:1] in {"은", "는", "이", "가"}:
            tail = tail[1:].lstrip()
        first_part = " ".join((anchor, tail)).strip()
    return list(
        dict.fromkeys(
            [
                first_part,
                *(
                    " ".join((anchor, part)).strip()
                    for part in parts[1:]
                ),
            ]
        )
    )


def explicit_question_clauses(question: str) -> list[str]:
    """Return only clauses literally separated on the question surface."""

    normalized = " ".join(str(question or "").split())
    surface_parts = [
        _TRAILING_COORDINATION.sub("", part.strip(" ?.")).strip()
        for part in _SURFACE_SEPARATOR.split(normalized)
        if len(
            _TRAILING_COORDINATION.sub(
                "",
                part.strip(" ?."),
            ).strip()
        )
        >= 2
    ]
    if len(surface_parts) > 1:
        return surface_parts
    return _kiwi_independent_clause_parts(normalized) or surface_parts


def surface_requirement_queries(question: str) -> list[str]:
    """Split only explicit surface clauses; do not infer domain relations."""

    normalized = " ".join(str(question or "").split())
    if not normalized:
        raise RuntimeError("question must not be empty")
    clean = normalized.strip(" ?.")
    parts = explicit_question_clauses(normalized)
    focused = list(parts)
    if len(parts) > 1:
        kiwi_parts = _kiwi_independent_clause_parts(normalized)
        if _INTERNAL_QUESTION_BOUNDARY.search(normalized):
            focused = parts
        elif kiwi_parts and parts == kiwi_parts:
            focused = kiwi_independent_requirement_queries(normalized)
        elif (
            _SURFACE_CONJUNCTION.search(normalized)
            and len(explicit_question_subjects(normalized)) >= 2
        ):
            tail = _relation_tail(parts[1])
            focused[0] = " ".join((parts[0], tail)).strip()
        else:
            anchor = parts[0]
            if "의 " in anchor:
                anchor = anchor.rsplit("의 ", 1)[0]
            focused = [
                parts[0],
                *(" ".join((anchor, part)) for part in parts[1:]),
            ]
    return list(
        dict.fromkeys(
            [
                normalized,
                *(
                    query
                    for part in focused
                    if part != clean
                    for query in (
                        part,
                        _focus_without_explicit_date(part),
                    )
                ),
            ]
        )
    )[:9]


def _query_score(
    unit: dict[str, Any],
    query: str,
) -> tuple[int, int, int, int, int, int, int, int]:
    query_tokens = _compact_tokens(query)
    query_ngrams = _compact_char_ngrams(query)
    text = str(unit.get("text") or "")
    title = str(unit.get("title") or "")
    identity = " ".join(
        (
            title,
            str(unit.get("context_text") or ""),
        )
    )
    text_tokens = _compact_tokens(text)
    identity_tokens = _compact_tokens(identity)
    text_ngrams = _compact_char_ngrams(text)
    identity_ngrams = _compact_char_ngrams(identity)
    text_overlap = query_tokens & text_tokens
    identity_overlap = query_tokens & identity_tokens
    relation_ngrams = query_ngrams - _compact_char_ngrams(title)
    relation_overlap = len(relation_ngrams & text_ngrams)
    identity_ngram_overlap = len(query_ngrams & identity_ngrams)
    return (
        relation_overlap + identity_ngram_overlap,
        relation_overlap,
        identity_ngram_overlap,
        sum(len(token) ** 2 for token in text_overlap),
        len(query_ngrams & text_ngrams),
        sum(len(token) ** 2 for token in identity_overlap),
        -int(unit["candidate_ref"]),
        -int(unit["start_char"]),
    )


def _table_query_score(
    unit: dict[str, Any],
    query: str,
) -> tuple[int, int, int, int, int, int, int, int]:
    score = _query_score(unit, query)
    return (
        score[2],
        score[0],
        score[1],
        score[3],
        score[4],
        score[5],
        score[6],
        score[7],
    )


def _requirement_score(
    unit: dict[str, Any],
    *,
    query: str,
    subject: str,
) -> tuple[int, int, int, int, int, int, int, int]:
    subject_tokens = _compact_tokens(subject)
    relation_tokens = _compact_tokens(query) - subject_tokens
    text = str(unit.get("text") or "")
    identity = " ".join(
        (
            str(unit.get("title") or ""),
            str(unit.get("context_text") or ""),
            text,
        )
    )
    text_tokens = _compact_tokens(text)
    identity_tokens = _compact_tokens(identity)
    relation_text_overlap = relation_tokens & text_tokens
    subject_identity_overlap = subject_tokens & identity_tokens
    relation_surface = " ".join(sorted(relation_tokens))
    subject_surface = " ".join(sorted(subject_tokens))
    fallback = _query_score(unit, query)
    return (
        sum(len(token) ** 2 for token in subject_identity_overlap),
        len(
            _compact_char_ngrams(subject_surface)
            & _compact_char_ngrams(identity)
        ),
        sum(len(token) ** 2 for token in relation_text_overlap),
        len(
            _compact_char_ngrams(relation_surface)
            & _compact_char_ngrams(text)
        ),
        fallback[0],
        fallback[1],
        fallback[6],
        fallback[7],
    )


def _dedupe_key(unit: dict[str, Any]) -> str:
    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(unit.get("text") or "").casefold(),
    )


def _has_substantive_text_overlap(left: str, right: str) -> bool:
    left_ngrams = {
        ngram
        for ngram in _compact_char_ngrams(left)
        if any(character.isalpha() for character in ngram)
    }
    right_ngrams = {
        ngram
        for ngram in _compact_char_ngrams(right)
        if any(character.isalpha() for character in ngram)
    }
    return bool(left_ngrams & right_ngrams)


def _previous_parent_chunks(
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    chunks_by_parent: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks_by_id.values():
        parent_document_id = str(chunk.get("parent_document_id") or "")
        if parent_document_id:
            chunks_by_parent.setdefault(parent_document_id, []).append(chunk)
    previous_by_chunk_id = {}
    for chunks in chunks_by_parent.values():
        ordered = sorted(
            chunks,
            key=lambda chunk: (
                int(chunk.get("chunk_index") or 0),
                int(chunk.get("start_offset") or 0),
                str(chunk.get("chunk_id") or ""),
            ),
        )
        for previous, current in zip(ordered, ordered[1:]):
            previous_by_chunk_id[str(current["chunk_id"])] = previous
    return previous_by_chunk_id


def _product_header_metadata_spans(
    chunk: dict[str, Any],
) -> list[tuple[int, int, str]]:
    """Locate only structured timestamp/view lines in the leading header."""

    source_text = str(chunk.get("display_text") or "")
    lines = []
    for match in re.finditer(r"[^\r\n]+", source_text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        lines.append(
            (
                match.start() + left,
                match.start() + right,
                source_text[
                    match.start() + left : match.start() + right
                ],
            )
        )
        if len(lines) >= 6:
            break
    if len(lines) < 3 or not lines[0][2].startswith("#"):
        return []
    timestamp_indexes = [
        index
        for index, (_, _, line) in enumerate(lines)
        if 2 <= index <= 4
        and _HEADER_PUBLISHED_TIMESTAMP.fullmatch(line)
    ]
    if len(timestamp_indexes) != 1:
        return []
    timestamp_index = timestamp_indexes[0]
    start, end, _ = lines[timestamp_index]
    spans = [(start, end, "published_timestamp")]
    view_index = timestamp_index + 1
    if view_index < len(lines):
        view_start, view_end, view_line = lines[view_index]
        if _HEADER_VIEW_COUNT.fullmatch(view_line):
            spans.append((view_start, view_end, "view_count"))
    return spans


def _without_product_header_metadata_units(
    units: list[dict[str, Any]],
    *,
    chunk: dict[str, Any],
    question: str = "",
) -> list[dict[str, Any]]:
    spans = _product_header_metadata_spans(chunk)
    if not spans:
        return units
    return [
        unit
        for unit in units
        if not any(
            int(unit["start_char"]) >= start
            and int(unit["end_char"]) <= end
            and _product_header_metadata_kind_is_filtered(kind, question)
            for start, end, kind in spans
        )
    ]


def _product_header_metadata_kind_is_filtered(
    kind: str,
    question: str,
) -> bool:
    if kind != "published_timestamp":
        return True
    return not _PUBLISHED_TIMESTAMP_QUESTION.search(" ".join(question.split()))


def _previous_chunk_context_line(
    chunk: dict[str, Any],
    previous_chunk: dict[str, Any] | None,
) -> str:
    if previous_chunk is None:
        return ""
    current_start = int(chunk.get("start_offset") or 0)
    previous_end = int(previous_chunk.get("end_offset") or 0)
    if current_start and previous_end and previous_end < current_start:
        return ""
    lines = [
        line.strip()
        for line in str(previous_chunk.get("display_text") or "").splitlines()
        if line.strip()
        and not _NUMBERED_LIST_ITEM.match(line.strip())
        and len(line.strip()) <= 200
    ]
    return lines[-1] if lines else ""


def _short_numbered_list_units(
    *,
    candidate_index: int,
    chunk_id: str,
    chunk: dict[str, Any],
    document: dict[str, Any],
    temporal: dict[str, Any],
    previous_chunk: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_text = str(chunk.get("display_text") or "")
    if not source_text:
        return []
    line_spans = []
    for match in re.finditer(r"[^\r\n]+", source_text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        start = match.start() + left
        end = match.start() + right
        line_spans.append((start, end, source_text[start:end]))

    groups: list[list[tuple[int, int, str]]] = []
    current: list[tuple[int, int, str]] = []
    for span in line_spans:
        if _NUMBERED_LIST_ITEM.match(span[2]):
            current.append(span)
            continue
        if len(current) >= 2:
            groups.append(current)
        current = []
    if len(current) >= 2:
        groups.append(current)

    context = " > ".join(
        str(value).strip()
        for value in (chunk.get("heading_path") or ())
        if str(value).strip()
    )
    units = []
    for group in groups:
        start = group[0][0]
        end = group[-1][1]
        if len(group) > 8 or end - start > 400:
            continue
        preceding_lines = [
            text
            for _, line_end, text in line_spans
            if line_end <= start
            and not _NUMBERED_LIST_ITEM.match(text)
            and len(text) <= 200
        ]
        boundary_context = (
            _previous_chunk_context_line(chunk, previous_chunk)
            if not preceding_lines and start <= 80
            else ""
        )
        list_context = " > ".join(
            value
            for value in (
                context,
                preceding_lines[-1] if preceding_lines else boundary_context,
            )
            if value
        )
        unit = _unit_metadata(
            candidate_index=candidate_index,
            chunk_id=chunk_id,
            chunk=chunk,
            document=document,
            temporal=temporal,
            start_char=start,
            end_char=end,
            text=source_text[start:end],
            context_text=list_context,
            unit_kind="numbered_list",
        )
        unit.update(
            {
                "complete_list": True,
                "list_item_count": len(group),
            }
        )
        units.append(unit)
    return units


def _table_label(lines: list[str]) -> str:
    for line in reversed(lines):
        stripped = line.strip().lstrip("#").strip()
        if "비용" in stripped or "표" in stripped:
            return re.sub(
                r"(?:은|는)\s*아래와\s*같습니다\.?$",
                "",
                stripped,
            ).strip()
    return lines[-1].strip().lstrip("#").strip() if lines else "표"


def _complete_table_units(
    candidate_chunk_ids: list[str],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    units = []
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        document = documents_by_id[parent_document_id]
        source_text = str(chunk.get("display_text") or "")
        search_start = 0
        while True:
            table_open = source_text.find("[TABLE]", search_start)
            if table_open < 0:
                break
            content_start = table_open + len("[TABLE]")
            if source_text.startswith("\r\n", content_start):
                content_start += 2
            elif source_text.startswith("\n", content_start):
                content_start += 1
            table_close = source_text.find("[/TABLE]", content_start)
            if table_close < 0:
                break
            content_end = table_close
            while (
                content_end > content_start
                and source_text[content_end - 1] in "\r\n"
            ):
                content_end -= 1
            prior_lines = [
                line
                for line in source_text[:table_open].splitlines()[-4:]
                if line.strip() and line.strip() != "[/TABLE]"
            ]
            label = _table_label(prior_lines)
            table_text = source_text[content_start:content_end]
            row_count = max(
                0,
                sum(
                    line.strip().startswith("|")
                    for line in table_text.splitlines()
                )
                - 1,
            )
            unit = _unit_metadata(
                candidate_index=candidate_index,
                chunk_id=chunk_id,
                chunk=chunk,
                document=document,
                temporal=temporal_by_document.get(
                    parent_document_id,
                    {},
                ),
                start_char=content_start,
                end_char=content_end,
                text=table_text,
                context_text=" > ".join(
                    value
                    for value in (
                        " > ".join(
                            str(part)
                            for part in (chunk.get("heading_path") or [])
                            if str(part).strip()
                        ),
                        label,
                    )
                    if value
                ),
                unit_kind="complete_table",
            )
            unit.update(
                {
                    "complete": True,
                    "table_label": label,
                    "table_row_count": row_count,
                }
            )
            units.append(unit)
            search_start = table_close + len("[/TABLE]")
    return units


def build_product_evidence_pack(
    candidate_chunk_ids: list[str],
    *,
    question: str,
    requirement_queries: list[str] | None,
    requested_subjects: list[str] | None = None,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    max_units: int = 8,
) -> list[dict[str, Any]]:
    """Select exact evidence units while preserving requirement coverage."""

    if max_units < 1:
        raise ValueError("max_units must be positive")
    queries = list(
        dict.fromkeys(
            query.strip()
            for query in (requirement_queries or [question])
            if query.strip()
        )
    )
    if not queries:
        raise RuntimeError("question or requirement query must not be empty")
    subjects = [
        str(subject).strip()
        for subject in (requested_subjects or [])
        if str(subject).strip()
    ]
    if len(subjects) == 1:
        query_subjects = subjects * len(queries)
    elif len(subjects) == len(queries):
        query_subjects = subjects
    else:
        query_subjects = [""] * len(queries)

    table_requested = (
        any(cue in question for cue in _TABLE_CUES)
        or ("종류" in question and "한 종류" not in question)
        or sum("비용" in query for query in queries) >= 2
    )
    if table_requested:
        table_units = _complete_table_units(
            candidate_chunk_ids,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
        )
        selected_tables = []
        selected_coordinates = set()
        for query, subject in zip(
            queries,
            query_subjects,
            strict=True,
        ):
            for unit in sorted(
                table_units,
                key=lambda row, query=query, subject=subject: (
                    _requirement_score(
                        row,
                        query=query,
                        subject=subject,
                    )
                    if subject
                    else _table_query_score(row, query)
                ),
                reverse=True,
            ):
                coordinate = (
                    unit["chunk_id"],
                    unit["start_char"],
                    unit["end_char"],
                )
                if coordinate in selected_coordinates:
                    continue
                selected_tables.append(
                    {
                        **unit,
                        "question_focus": query,
                    }
                )
                selected_coordinates.add(coordinate)
                break
        if selected_tables:
            return [
                {
                    **unit,
                    "evidence_ref": f"T{index}",
                }
                for index, unit in enumerate(
                    selected_tables[:max_units],
                    1,
                )
            ]

    previous_by_chunk_id = _previous_parent_chunks(chunks_by_id)
    all_units = []
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        document = documents_by_id[parent_document_id]
        temporal = temporal_by_document.get(parent_document_id, {})
        all_units.extend(
            _without_product_header_metadata_units(
                _chunk_atomic_units(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                ),
                chunk=chunk,
                question=question,
            )
        )
        all_units.extend(
            _without_product_header_metadata_units(
                _short_numbered_list_units(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                    previous_chunk=previous_by_chunk_id.get(chunk_id),
                ),
                chunk=chunk,
                question=question,
            )
        )

    rankings = [
        sorted(
            all_units,
            key=lambda unit, query=query, subject=subject: (
                _requirement_score(
                    unit,
                    query=query,
                    subject=subject,
                )
                if subject
                else _query_score(unit, query)
            ),
            reverse=True,
        )
        for query, subject in zip(
            queries,
            query_subjects,
            strict=True,
        )
    ]
    coverage_limit = min(max_units, len(rankings))
    cursors = [0] * len(rankings)
    selected = []
    selected_keys = set()
    while len(selected) < coverage_limit:
        added = False
        for ranking_index, ranking in enumerate(rankings):
            while cursors[ranking_index] < len(ranking):
                unit = ranking[cursors[ranking_index]]
                cursors[ranking_index] += 1
                key = _dedupe_key(unit)
                if not key or key in selected_keys:
                    continue
                selected.append(
                    {
                        **unit,
                        "question_focus": queries[ranking_index],
                    }
                )
                selected_keys.add(key)
                added = True
                break
            if len(selected) >= coverage_limit:
                break
        if not added:
            break

    overall_ranking = sorted(
        all_units,
        key=lambda unit: _query_score(unit, question),
        reverse=True,
    )
    for unit in overall_ranking:
        if len(selected) >= max_units:
            break
        key = _dedupe_key(unit)
        if not key or key in selected_keys:
            continue
        selected.append(unit)
        selected_keys.add(key)

    return [
        {
            **unit,
            "evidence_ref": f"E{index}",
        }
        for index, unit in enumerate(selected, 1)
    ]


def build_compact_product_evidence_pack(
    candidate_chunk_ids: list[str],
    *,
    question: str,
    requirement_queries: list[str] | None = None,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    max_units: int = 8,
) -> list[dict[str, Any]]:
    """Select a bounded exact-unit set from explicit question surfaces."""

    if requirement_queries is None:
        queries = surface_requirement_queries(question)
        selection_queries = queries[1:] if len(queries) > 1 else queries
    else:
        selection_queries = list(
            dict.fromkeys(
                query.strip()
                for query in requirement_queries
                if query.strip()
            )
        ) or [question]
    return build_product_evidence_pack(
        candidate_chunk_ids,
        question=question,
        requirement_queries=selection_queries,
        requested_subjects=_surface_subjects(question),
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
        temporal_by_document=temporal_by_document,
        max_units=max_units,
    )


def _atomic_reranker_text(unit: dict[str, Any]) -> str:
    return "\n".join(
        value
        for value in (
            f"제목: {unit.get('title') or ''}",
            f"문맥: {unit.get('context_text') or ''}",
            f"근거: {unit.get('text') or ''}",
        )
        if value.split(":", 1)[-1].strip()
    )


def select_semantic_product_evidence_units(
    units: list[dict[str, Any]],
    *,
    selection_queries: list[str],
    question: str,
    score_pairs,
    max_units: int = 8,
    prefilter_per_query: int | None = None,
    reserve_per_query: int = 1,
) -> list[dict[str, Any]]:
    """Reserve surface queries and distinct parent contexts before filling."""

    if reserve_per_query < 1:
        raise ValueError("reserve_per_query must be positive")

    queries = list(dict.fromkeys([*selection_queries, question]))
    unit_texts = [_atomic_reranker_text(unit) for unit in units]
    indexes_by_query = {}
    pairs = []
    for query in queries:
        indexes = list(range(len(units)))
        if prefilter_per_query is not None:
            indexes = sorted(
                indexes,
                key=lambda index: _query_score(units[index], query),
                reverse=True,
            )[:prefilter_per_query]
        indexes_by_query[query] = indexes
        pairs.extend((query, unit_texts[index]) for index in indexes)
    scores = list(score_pairs(pairs))
    if len(scores) != len(pairs):
        raise RuntimeError("atomic evidence score count mismatch")
    scores_by_query = {}
    offset = 0
    for query in queries:
        indexes = indexes_by_query[query]
        scores_by_query[query] = {
            index: scores[offset + position]
            for position, index in enumerate(indexes)
        }
        offset += len(indexes)
    selected = []
    selected_keys = set()
    question_focus_by_unit = {}

    def parent_key(unit: dict[str, Any]) -> str:
        return str(
            unit.get("parent_document_id")
            or unit.get("chunk_id")
            or unit.get("candidate_ref")
            or ""
        )

    def ranked_indexes(query: str) -> list[int]:
        ranked = sorted(
            indexes_by_query[query],
            key=lambda index: (
                -float(scores_by_query[query][index]),
                int(units[index]["candidate_ref"]),
                int(units[index]["start_char"]),
            ),
        )
        if not ranked or not any(
            cue in query for cue in _COMPLETE_LIST_CUES
        ):
            return ranked
        best_score = float(scores_by_query[query][ranked[0]])
        complete_lists = [
            index
            for index in ranked
            if units[index].get("complete_list")
            and float(scores_by_query[query][index])
            >= best_score - 0.05
        ]
        if not complete_lists:
            return ranked
        complete_list_indexes = set(complete_lists)
        return [
            *complete_lists,
            *(
                index
                for index in ranked
                if index not in complete_list_indexes
            ),
        ]

    for query in selection_queries:
        for index in ranked_indexes(query)[:reserve_per_query]:
            unit = units[index]
            key = _dedupe_key(unit)
            if not key or key in selected_keys:
                continue
            selected.append(unit)
            selected_keys.add(key)
            question_focus_by_unit[id(unit)] = query
            if len(selected) >= max_units:
                break
        if len(selected) >= max_units:
            break
    question_ranking = ranked_indexes(question)
    question_score_floor = None
    if question_ranking and len(selection_queries) == 1:
        best_question_index = question_ranking[0]
        best_question_score = float(
            scores_by_query[question][best_question_index]
        )
        if (
            0.8 <= best_question_score <= 1.000001
            and _has_substantive_text_overlap(
                question,
                str(units[best_question_index].get("text") or ""),
            )
        ):
            question_score_floor = best_question_score * 0.5

    def question_score_is_eligible(index: int) -> bool:
        return bool(
            question_score_floor is None
            or float(scores_by_query[question][index])
            >= question_score_floor
        )

    selected_parents = {
        parent_key(unit) for unit in selected if parent_key(unit)
    }
    parent_reserve_limit = min(
        3 if len(selection_queries) == 1 else 2,
        max_units,
    )
    for index in question_ranking:
        if (
            len(selected) >= max_units
            or len(selected_parents) >= parent_reserve_limit
        ):
            break
        if not question_score_is_eligible(index):
            continue
        unit = units[index]
        parent = parent_key(unit)
        key = _dedupe_key(unit)
        if not key or key in selected_keys or parent in selected_parents:
            continue
        selected.append(unit)
        selected_keys.add(key)
        if parent:
            selected_parents.add(parent)
    for index in question_ranking:
        if len(selected) >= max_units:
            break
        if not question_score_is_eligible(index):
            continue
        unit = units[index]
        key = _dedupe_key(unit)
        if not key or key in selected_keys:
            continue
        selected.append(unit)
        selected_keys.add(key)
    unit_indexes = {id(unit): index for index, unit in enumerate(units)}
    output = []
    for evidence_index, unit in enumerate(selected, 1):
        unit_index = unit_indexes[id(unit)]
        relevance_scores = [
            float(query_scores[unit_index])
            for query_scores in scores_by_query.values()
            if unit_index in query_scores
        ]
        output.append(
            {
                **unit,
                "evidence_ref": f"E{evidence_index}",
                "question_focus": question_focus_by_unit.get(
                    id(unit),
                    "",
                ),
                "question_relevance_score": (
                    round(max(relevance_scores), 8)
                    if relevance_scores
                    else None
                ),
            }
        )
    return output


def build_atomic_reranked_product_evidence_pack(
    candidate_chunk_ids: list[str],
    *,
    question: str,
    requirement_queries: list[str] | None = None,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    score_pairs,
    max_units: int = 8,
    prefilter_per_query: int | None = None,
    reserve_per_query: int = 1,
) -> list[dict[str, Any]]:
    """Use BGE scores only inside the fixed top candidate chunks."""

    current = build_compact_product_evidence_pack(
        candidate_chunk_ids,
        question=question,
        requirement_queries=requirement_queries,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
        temporal_by_document=temporal_by_document,
        max_units=max_units,
    )
    if any(unit.get("complete") for unit in current):
        return current
    previous_by_chunk_id = _previous_parent_chunks(chunks_by_id)
    all_units = []
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        document = documents_by_id[parent_document_id]
        temporal = temporal_by_document.get(parent_document_id, {})
        all_units.extend(
            _without_product_header_metadata_units(
                _chunk_atomic_units(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                ),
                chunk=chunk,
                question=question,
            )
        )
        all_units.extend(
            _without_product_header_metadata_units(
                _short_numbered_list_units(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                    previous_chunk=previous_by_chunk_id.get(chunk_id),
                ),
                chunk=chunk,
                question=question,
            )
        )
    if requirement_queries is None:
        queries = surface_requirement_queries(question)
        selection_queries = queries[1:] if len(queries) > 1 else queries
    else:
        selection_queries = list(
            dict.fromkeys(
                query.strip()
                for query in requirement_queries
                if query.strip()
            )
        ) or [question]
    return select_semantic_product_evidence_units(
        all_units,
        selection_queries=selection_queries,
        question=question,
        score_pairs=score_pairs,
        max_units=max_units,
        prefilter_per_query=prefilter_per_query,
        reserve_per_query=reserve_per_query,
    )


def product_model_evidence_payload(
    units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = []
    for unit in units:
        text = str(unit["text"])
        if unit.get("complete"):
            text = (
                f"{unit.get('table_label') or '표'}: "
                f"완전한 {int(unit.get('table_row_count') or 0)}행 표"
            )
        payload.append(
            {
                "evidence_ref": unit["evidence_ref"],
                "candidate_ref": unit["candidate_ref"],
                "title": unit["title"],
                "question_focus": unit.get("question_focus") or "",
                "context": unit.get("context_text") or "",
                "text": text,
            }
        )
    return payload
