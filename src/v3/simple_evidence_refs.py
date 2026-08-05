from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SIMPLE_EVIDENCE_REF_VERSION = "dnf-simple-evidence-ref-v1"
ATOMIC_EVIDENCE_REF_VERSION = "dnf-simple-atomic-evidence-ref-v1"
DEFAULT_MAX_ATOMIC_UNITS = 12
SIMPLE_EVIDENCE_REF_SYSTEM_INSTRUCTIONS = """당신은 던전앤파이터 공식 문서만 근거로 답하는 QA 모델입니다.
질문 전체에 답하는 result 하나만 반환하고, 요구사항을 새로 만들거나 분해하지 마세요.
근거가 충분하면 supported, 일부만 답할 수 있으면 partial, 부족하면 unsupported로 표시하세요.
supported 또는 partial인 경우 짧고 직접적인 답과 제공된 E번호만 반환하세요.
질문이 종류·목록·전체를 요구하면 선택한 근거에 명시된 항목을 임의로 생략하지 마세요.
원문을 직접 복사하거나 후보 번호·chunk ID·출처 좌표를 만들지 마세요.
답을 지지하는 최소한의 E번호만 선택하세요.
unsupported인 경우 answer와 evidence_refs를 비우세요.
"""


class SimpleEvidenceRefRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(supported|partial|unsupported)$")
    answer: str = Field(max_length=1200)
    evidence_refs: list[str] = Field(max_length=4)

    @model_validator(mode="after")
    def validate_support_shape(self) -> "SimpleEvidenceRefRequirement":
        if self.status in {"supported", "partial"} and (
            not self.answer.strip() or not self.evidence_refs
        ):
            raise ValueError(
                "supported or partial answers need an answer and evidence refs"
            )
        if self.status == "unsupported" and (
            self.answer.strip() or self.evidence_refs
        ):
            raise ValueError(
                "unsupported requirements must not contain an answer or evidence refs"
            )
        return self


class SimpleEvidenceRefOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_time_scope: str = Field(pattern="^(current|historical|comparison)$")
    result: SimpleEvidenceRefRequirement


def _unit_metadata(
    *,
    candidate_index: int,
    chunk_id: str,
    chunk: dict[str, Any],
    document: dict[str, Any],
    temporal: dict[str, Any],
    start_char: int,
    end_char: int,
    text: str,
    context_text: str,
    unit_kind: str,
) -> dict[str, Any]:
    return {
        "candidate_ref": str(candidate_index),
        "chunk_id": chunk_id,
        "parent_document_id": str(chunk["parent_document_id"]),
        "source_id": document["source_id"],
        "title": document.get("title") or "",
        "published_at": document.get("published_at"),
        "valid_from": temporal.get(
            "valid_from",
            document.get("valid_from"),
        ),
        "valid_to": temporal.get(
            "valid_to",
            document.get("valid_to"),
        ),
        "revision_id": document.get("revision_id"),
        "status": temporal.get(
            "status",
            document.get("status") or chunk.get("status"),
        ),
        "start_char": start_char,
        "end_char": end_char,
        "text": text,
        "context_text": context_text,
        "unit_kind": unit_kind,
    }


def build_simple_evidence_units(
    candidate_chunk_ids: list[str],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map each retrieved chunk to one short ref with exact coordinates."""

    units = []
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        document = documents_by_id[parent_document_id]
        source_text = str(chunk.get("display_text") or "")
        if not source_text:
            continue
        temporal = temporal_by_document.get(parent_document_id, {})
        heading_path = chunk.get("heading_path") or ()
        units.append(
            {
                "evidence_ref": f"E{len(units) + 1}",
                "candidate_ref": str(candidate_index),
                "chunk_id": chunk_id,
                "parent_document_id": parent_document_id,
                "source_id": document["source_id"],
                "title": document.get("title") or "",
                "published_at": document.get("published_at"),
                "valid_from": temporal.get(
                    "valid_from",
                    document.get("valid_from"),
                ),
                "valid_to": temporal.get(
                    "valid_to",
                    document.get("valid_to"),
                ),
                "revision_id": document.get("revision_id"),
                "status": temporal.get(
                    "status",
                    document.get("status") or chunk.get("status"),
                ),
                "start_char": 0,
                "end_char": len(source_text),
                "text": source_text,
                "context_text": " > ".join(
                    str(value) for value in heading_path if str(value).strip()
                ),
            }
        )
    return units


def _exact_line_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    for match in re.finditer(r"[^\r\n]+", text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        start = match.start() + left
        end = match.start() + right
        spans.append((start, end, text[start:end]))
    return spans


def _sentence_spans(
    text: str,
    *,
    line_start: int,
) -> list[tuple[int, int, str]]:
    if re.match(r"^\s*\d+\.\s+", text):
        left = len(text) - len(text.lstrip())
        right = len(text.rstrip())
        return [
            (
                line_start + left,
                line_start + right,
                text[left:right],
            )
        ]
    spans = []
    boundary = re.compile(r".+?(?:[.!?](?=\s|$)|$)")
    for match in boundary.finditer(text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        start = line_start + match.start() + left
        end = line_start + match.start() + right
        spans.append((start, end, raw[left:right]))
    return spans


def _is_table_separator(text: str) -> bool:
    cells = [cell.strip() for cell in text.strip().strip("|").split("|")]
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell) is not None for cell in cells
    )


def _compact_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[0-9A-Za-z가-힣]+", text)
        if len(token) >= 2
    }


def _compact_char_ngrams(text: str) -> set[str]:
    compact = re.sub(r"[^0-9A-Za-z가-힣]+", "", text.casefold())
    return {
        compact[index : index + size]
        for size in (2, 3)
        for index in range(max(0, len(compact) - size + 1))
    }


def _atomic_relevance_score(
    unit: dict[str, Any],
    *,
    question_tokens: set[str],
    question_ngrams: set[str],
) -> tuple[int, int, int, int]:
    unit_text = str(unit.get("text") or "")
    context = "\n".join(
        (
            str(unit.get("title") or ""),
            str(unit.get("context_text") or ""),
        )
    )
    searchable = "\n".join((context, unit_text))
    unit_tokens = _compact_tokens(searchable)
    overlap = question_tokens & unit_tokens
    overlap_score = sum(len(token) * len(token) for token in overlap)
    text_ngram_score = len(
        question_ngrams & _compact_char_ngrams(unit_text)
    )
    context_ngram_score = len(
        question_ngrams & _compact_char_ngrams(context)
    )
    candidate_rank = int(unit["candidate_ref"])
    return (
        overlap_score + (text_ngram_score * 4) + context_ngram_score,
        text_ngram_score,
        len(overlap),
        -candidate_rank,
    )


def _chunk_atomic_units(
    *,
    candidate_index: int,
    chunk_id: str,
    chunk: dict[str, Any],
    document: dict[str, Any],
    temporal: dict[str, Any],
) -> list[dict[str, Any]]:
    source_text = str(chunk.get("display_text") or "")
    if not source_text:
        return []
    heading_parts = [
        str(value).strip()
        for value in (chunk.get("heading_path") or ())
        if str(value).strip()
    ]
    current_heading = " > ".join(heading_parts)
    table_header = ""
    table_subject = ""
    in_table = False
    units = []
    for start, end, line in _exact_line_spans(source_text):
        stripped = line.strip()
        if stripped == "[TABLE]":
            in_table = True
            table_header = ""
            table_subject = ""
            continue
        if stripped == "[/TABLE]":
            in_table = False
            table_header = ""
            table_subject = ""
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                current_heading = " > ".join([*heading_parts, heading])
            continue
        if in_table and stripped.startswith("|") and stripped.endswith("|"):
            if _is_table_separator(stripped):
                continue
            if not table_header:
                table_header = stripped
                continue
            normalized = re.sub(r"\s+", "", stripped)
            if not table_subject and any(
                label in normalized
                for label in (
                    "아이템명",
                    "상품명",
                    "판매물품",
                    "판매목록",
                    "구분",
                )
            ):
                table_subject = stripped
            context = " > ".join(
                value
                for value in (
                    current_heading,
                    f"표 헤더: {table_header}",
                    (
                        f"표 대상: {table_subject}"
                        if table_subject and table_subject != stripped
                        else ""
                    ),
                )
                if value
            )
            units.append(
                _unit_metadata(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                    start_char=start,
                    end_char=end,
                    text=source_text[start:end],
                    context_text=context,
                    unit_kind="table_row",
                )
            )
            continue
        for sentence_start, sentence_end, sentence in _sentence_spans(
            line,
            line_start=start,
        ):
            units.append(
                _unit_metadata(
                    candidate_index=candidate_index,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    document=document,
                    temporal=temporal,
                    start_char=sentence_start,
                    end_char=sentence_end,
                    text=source_text[sentence_start:sentence_end],
                    context_text=current_heading,
                    unit_kind="sentence",
                )
            )
    return units


def build_atomic_evidence_units(
    candidate_chunk_ids: list[str],
    *,
    question: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    max_units: int = DEFAULT_MAX_ATOMIC_UNITS,
) -> list[dict[str, Any]]:
    """Build exact sentence/table-row refs and retain candidate diversity."""

    if max_units < 1:
        raise ValueError("max_units must be positive")
    question_tokens = _compact_tokens(question)
    question_ngrams = _compact_char_ngrams(question)
    all_units = []
    units_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for candidate_index, chunk_id in enumerate(candidate_chunk_ids, 1):
        chunk = chunks_by_id[chunk_id]
        parent_document_id = str(chunk["parent_document_id"])
        document = documents_by_id[parent_document_id]
        temporal = temporal_by_document.get(parent_document_id, {})
        chunk_units = _chunk_atomic_units(
            candidate_index=candidate_index,
            chunk_id=chunk_id,
            chunk=chunk,
            document=document,
            temporal=temporal,
        )
        if not chunk_units:
            continue
        units_by_candidate[str(candidate_index)] = chunk_units
        all_units.extend(chunk_units)

    def sort_key(unit: dict[str, Any]) -> tuple[int, int, int, int, int]:
        score = _atomic_relevance_score(
            unit,
            question_tokens=question_tokens,
            question_ngrams=question_ngrams,
        )
        return (*score, -int(unit["start_char"]))

    selected = []
    selected_keys = set()
    for candidate_ref in sorted(units_by_candidate, key=int):
        best = max(units_by_candidate[candidate_ref], key=sort_key)
        key = (
            best["chunk_id"],
            best["start_char"],
            best["end_char"],
        )
        selected.append(best)
        selected_keys.add(key)
        if len(selected) >= max_units:
            break
    for unit in sorted(all_units, key=sort_key, reverse=True):
        key = (unit["chunk_id"], unit["start_char"], unit["end_char"])
        if key in selected_keys:
            continue
        selected.append(unit)
        selected_keys.add(key)
        if len(selected) >= max_units:
            break
    selected.sort(
        key=lambda unit: (
            int(unit["candidate_ref"]),
            int(unit["start_char"]),
        )
    )
    return [
        {
            **unit,
            "evidence_ref": f"E{index}",
        }
        for index, unit in enumerate(selected, 1)
    ]


def model_evidence_payload(
    units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only fields the generator needs for evidence selection."""

    return [
        {
            "evidence_ref": unit["evidence_ref"],
            "candidate_ref": unit["candidate_ref"],
            "title": unit["title"],
            "context": unit.get("context_text") or "",
            "text": unit["text"],
        }
        for unit in units
    ]


def build_simple_evidence_ref_prompt(
    *,
    question: str,
    as_of: str,
    evidence_units: list[dict[str, Any]],
) -> str:
    payload = {
        "as_of": as_of,
        "question": question,
        "evidence_units": model_evidence_payload(evidence_units),
    }
    return (
        "다음 JSON의 질문에 evidence_units만 사용해 답하세요.\n"
        "인용문을 복사하지 말고 evidence_ref의 E번호만 선택하세요.\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def resolve_evidence_refs(
    evidence_refs: list[str],
    *,
    evidence_units_by_ref: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve short refs to exact citations and reject stale coordinates."""

    citations = []
    failures = []
    for evidence_ref in dict.fromkeys(evidence_refs):
        unit = evidence_units_by_ref.get(evidence_ref)
        if unit is None:
            failures.append(f"evidence_ref_not_provided:{evidence_ref}")
            continue
        chunk = chunks_by_id.get(str(unit.get("chunk_id") or ""))
        if chunk is None:
            failures.append(f"evidence_chunk_not_found:{evidence_ref}")
            continue
        source_text = str(chunk.get("display_text") or "")
        start = int(unit.get("start_char", -1))
        end = int(unit.get("end_char", -1))
        if (
            start < 0
            or end <= start
            or end > len(source_text)
            or source_text[start:end] != unit.get("text")
        ):
            failures.append(f"evidence_coordinate_mismatch:{evidence_ref}")
            continue
        citations.append(
            {
                "evidence_ref": evidence_ref,
                "candidate_ref": unit["candidate_ref"],
                "chunk_id": unit["chunk_id"],
                "parent_document_id": unit["parent_document_id"],
                "source_id": unit["source_id"],
                "title": unit["title"],
                "published_at": unit.get("published_at"),
                "start_char": start,
                "end_char": end,
                "text": source_text[start:end],
            }
        )
    return citations, failures


def verify_simple_evidence_ref_output(
    output: SimpleEvidenceRefOutput | dict[str, Any],
    *,
    question: str,
    evidence_units: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    parsed = (
        output
        if isinstance(output, SimpleEvidenceRefOutput)
        else SimpleEvidenceRefOutput.model_validate(output)
    )
    units_by_ref = {
        str(unit["evidence_ref"]): unit for unit in evidence_units
    }
    result = parsed.result
    citations = []
    failures = []
    if result.status in {"supported", "partial"}:
        citations, failures = resolve_evidence_refs(
            result.evidence_refs,
            evidence_units_by_ref=units_by_ref,
            chunks_by_id=chunks_by_id,
        )
    exposed_supported = (
        result.status in {"supported", "partial"}
        and not failures
        and bool(citations)
    )
    decision = {
        "requirement_index": 1,
        "question_part": question,
        "status": "supported_exact" if exposed_supported else "unsupported",
        "answer": result.answer if exposed_supported else "",
        "citations": citations if exposed_supported else [],
    }
    audit = {
        "requirement_index": 1,
        "model_status": result.status,
        "exposed_status": (
            "supported_exact" if exposed_supported else "unsupported"
        ),
        "failure_reasons": failures,
    }
    if not exposed_supported:
        response_mode = "abstain"
    elif result.status == "partial":
        response_mode = "partial_answer"
    else:
        response_mode = "full_answer"
    rendered = ""
    if exposed_supported:
        rendered = f"- {decision['answer']} " + " ".join(
            f"[{citation['chunk_id']}]" for citation in citations
        )
    return {
        "question_time_scope": parsed.question_time_scope,
        "model_response_mode": {
            "supported": "full_answer",
            "partial": "partial_answer",
            "unsupported": "abstain",
        }[result.status],
        "response_mode": response_mode,
        "requirements": [decision],
        "rendered_answer": rendered,
        "verification": {
            "requirements": [audit],
            "raw_output_passed_without_sanitization": not failures,
            "all_exposed_citations_verified": True,
        },
    }
