from __future__ import annotations

import copy
import json
import os
import re
import time
from calendar import monthrange
from dataclasses import replace
from datetime import date
from itertools import permutations
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from src.io_utils import read_jsonl
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    build_compact_product_evidence_pack,
    build_product_evidence_pack,
    explicit_nominative_question_subjects,
    explicit_question_clauses,
    explicit_question_subjects,
    kiwi_independent_requirement_queries,
    product_model_evidence_payload,
)
from src.v3.product_minimal_verifier import verify_product_claim_output
from src.v3.value_normalization import (
    boolean_value,
    currency_values,
    number_values,
    time_values,
)


PRODUCT_FREE_RAG_VERSION = "dnf-product-free-rag-v1-experimental"
DEFAULT_RETRIEVAL_DEPTH = 20
DEFAULT_RERANK_DEPTH = 8
DEFAULT_PARENT_LIMIT = 2
DEFAULT_EVIDENCE_UNITS = 8
DEFAULT_CONTEXT_TOKENS = 4096
DEFAULT_OUTPUT_TOKENS = 768
GLOBAL_TEMPORAL_OVERLAY = Path(
    "data/v3/temporal/global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)

PRODUCT_SYSTEM_INSTRUCTIONS = """당신은 던전앤파이터 공식 문서만 근거로 답하는 QA 모델입니다.
한국어 띄어쓰기가 생략되거나 달라도 question의 대상과 속성을 evidence_units의 표현과 대조해 해석하세요.
evidence_units는 답변 항목 목록이 아니라 후보 근거입니다. 질문의 대상과 속성을 모두 직접 지지하는 근거만 선택하고 나머지는 무시하세요.
question_focus는 서버가 질문 표면에서 가져온 예약 힌트이며 근거 원문은 아닙니다. 각 focus의 대상과 속성을 text 및 context와 함께 확인해 서로 바꾸지 마세요.
질문의 각 대상을 별도 claim으로 답하세요.
같은 문서 맥락 안에서 같은 대상과 속성을 지지하는 근거가 여러 개여도 하나의 claim으로 합치세요.
하나의 근거에 짧은 번호 목록으로 조건이나 항목이 함께 있으면 질문에 해당하는 항목을 임의로 생략하지 마세요.
번호 목록의 여러 항목을 한 claim으로 합칠 때도 각 항목의 공통 주어와 핵심 표현을 생략하지 마세요.
같은 대상 명칭과 질문한 속성을 직접 지지하는 근거가 서로 다른 문서 맥락에 있고 질문에 이를 구분할 표현이 없으면, 하나를 임의로 선택하거나 합치지 말고 clarification으로 되물으세요.
clarification에서는 claims를 비우고 clarification에 사실값 없이 문서 맥락을 구분하는 짧은 질문만 쓰세요.
한 대상의 한 속성만 묻는 질문에는 claim을 하나만 출력하고 다른 evidence 속성을 나열하지 마세요.
질문에서 직접 요구한 정보만 답하고, 관련된 다른 조건을 추가하지 마세요.
같은 대상의 다른 속성을 설명하는 근거는 사용하지 마세요. 질문한 행위나 속성을 근거가 직접 다루지 않으면 그 claim은 만들지 마세요.
숫자와 기간 단위가 조건 안에 등장해도 이를 처리 기간으로 바꾸지 마세요. 근거가 처리·소요·완료에 걸리는 시간을 직접 말할 때만 처리 기간으로 답하세요.
예·아니오 질문에서는 근거에 없는 질문 속 숫자·날짜 조건을 claim에 되풀이하지 말고, 근거가 지지하는 판단만 짧게 답하세요.
질문 문장을 답으로 그대로 되풀이하지 마세요.
근거가 충분한 claim만 작성하고, 근거가 없는 대상은 claim으로 만들지 마세요.
모든 대상을 답하면 answer, 일부만 답하면 partial, 아무것도 답할 수 없으면 unsupported, 질문을 명확히 해야 하면 clarification입니다.
각 claim에는 짧고 직접적인 text와 이를 지지하는 최소 evidence_refs만 넣으세요.
횟수·수량·금액·비율·시각을 묻는 질문에서는 선택한 근거의 답 값을 claim text에 반드시 포함하세요.
제공되지 않은 E번호, 원문 좌표, chunk ID는 출력하지 마세요.
JSON 스키마 외에는 출력하지 마세요.
"""

_FULL_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)
_LISTING_TAIL = re.compile(
    r"(?:텍스트복사\s*목록|FIRST\s*PREV|PREV\s*\d+\s*NEXT)",
    re.IGNORECASE,
)
_YEAR_MONTH = re.compile(
    r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월"
)
_MONTH_DAY = re.compile(
    r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)
_GENERIC_REQUEST_TAIL = re.compile(
    r"(?:에\s*대해\s*)?"
    r"(?:알려\s*줘|설명해\s*줘|뭐야|무엇이야)"
    r"[?？.\s]*$"
)
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


class ProductClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1200)
    evidence_refs: list[str] = Field(max_length=8)


class ProductRagOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["answer", "partial", "clarification", "unsupported"]
    claims: list[ProductClaim]
    clarification: str = Field(max_length=1200)


class ProductCoverageClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_ref: str = Field(pattern=r"^Q[1-9][0-9]*$")
    text: str = Field(min_length=1, max_length=1200)
    evidence_refs: list[str] = Field(max_length=8)


class ProductCoverageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ProductCoverageClaim]
    unsupported_question_refs: list[str]
    clarification: str = Field(max_length=1200)


PRODUCT_COVERAGE_SYSTEM_INSTRUCTIONS = PRODUCT_SYSTEM_INSTRUCTIONS + """
question_requirements의 Q번호마다 정확히 한 번 판단하세요.
근거가 해당 Q의 대상과 속성을 직접 답하면 question_ref가 있는 claim을 작성하세요.
관련은 있지만 다른 혜택·조건·절차·시각·금액을 말하는 근거는 그 Q의 답으로 사용하지 마세요.
직접 답하는 근거가 없으면 값을 추측하지 말고 그 Q번호를 unsupported_question_refs에 넣으세요.
clarification이 필요하지 않다면 모든 Q번호는 claims 또는 unsupported_question_refs 중 정확히 한 곳에 있어야 합니다.
모드는 출력하지 않습니다. 서버가 Q번호별 결과로 answer, partial, unsupported를 결정합니다.
"""

_PRODUCT_COVERAGE_LEXICAL_STOPWORDS = frozenset(
    {
        "각각",
        "뭐야",
        "무엇",
        "무엇을",
        "보여줘",
        "보여주세요",
        "설명해줘",
        "설명해주세요",
        "알려줘",
        "알려주세요",
        "얼마",
        "언제",
        "있었는지",
        "정확한",
    }
)


def _product_coverage_compact_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[0-9A-Za-z가-힣]+", text)
        if len(token) >= 2
    }


def build_product_coverage_lexical_overlap_diagnostic(
    *,
    question_ref: str,
    question_text: str,
    evidence_refs: list[str],
    evidence_units: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure cited-text overlap without changing selection or acceptance."""

    question_tokens = (
        _product_coverage_compact_tokens(question_text)
        - _PRODUCT_COVERAGE_LEXICAL_STOPWORDS
    )
    units_by_ref = {
        str(unit.get("evidence_ref") or ""): unit
        for unit in evidence_units
    }
    evidence_overlap = []
    union_evidence_tokens: set[str] = set()
    denominator = max(1, len(question_tokens))
    for evidence_ref in dict.fromkeys(evidence_refs):
        unit = units_by_ref.get(str(evidence_ref), {})
        evidence_tokens = _product_coverage_compact_tokens(
            str(unit.get("text") or "")
        )
        union_evidence_tokens.update(evidence_tokens)
        matched_tokens = sorted(question_tokens & evidence_tokens)
        evidence_overlap.append(
            {
                "evidence_ref": str(evidence_ref),
                "matched_tokens": matched_tokens,
                "ratio": len(matched_tokens) / denominator,
            }
        )
    union_matched_tokens = sorted(question_tokens & union_evidence_tokens)
    return {
        "question_ref": question_ref,
        "question_tokens": sorted(question_tokens),
        "evidence_overlap": evidence_overlap,
        "union_matched_tokens": union_matched_tokens,
        "union_ratio": len(union_matched_tokens) / denominator,
        "zero_overlap_signal": bool(question_tokens)
        and not union_matched_tokens,
    }


def build_product_question_requirements(
    question: str,
) -> list[dict[str, str]]:
    """Label only explicit surface requirements; do not infer relations."""

    normalized = normalize_product_question(question)
    clauses = explicit_question_clauses(normalized)
    if len(clauses) > 1:
        kiwi_clauses = kiwi_independent_requirement_queries(normalized)
        if kiwi_clauses:
            clauses = kiwi_clauses
    else:
        clauses = [normalized]
    return [
        {"question_ref": f"Q{index}", "text": clause}
        for index, clause in enumerate(clauses, 1)
    ]


def select_parent_diverse_candidates(
    ranked: list[dict[str, Any]],
    *,
    depth: int = DEFAULT_RERANK_DEPTH,
    max_per_parent: int = DEFAULT_PARENT_LIMIT,
) -> list[dict[str, Any]]:
    if depth < 1:
        raise RuntimeError("rerank depth must be at least 1")
    if max_per_parent < 1:
        raise RuntimeError("parent limit must be at least 1")
    counts: dict[str, int] = {}
    selected = []
    for row in ranked:
        parent_document_id = str(row["parent_document_id"])
        if counts.get(parent_document_id, 0) >= max_per_parent:
            continue
        selected.append(row)
        counts[parent_document_id] = counts.get(parent_document_id, 0) + 1
        if len(selected) >= depth:
            break
    return selected


def select_required_parent_candidates(
    selected: list[dict[str, Any]],
    *,
    required_parent_document_id: str | None,
) -> list[dict[str, Any]]:
    if not required_parent_document_id:
        return list(selected)
    return [
        row
        for row in selected
        if str(row.get("parent_document_id") or "")
        == str(required_parent_document_id)
    ]


def expand_evidence_candidate_chunk_ids(
    question: str,
    selected: list[dict[str, Any]],
    *,
    chunks_by_parent: dict[str, list[dict[str, Any]]],
    max_chunks: int = DEFAULT_RERANK_DEPTH * 2,
) -> list[str]:
    """Add one question-focused sibling per selected parent for evidence only."""

    from src.v3.product_candidate_identity import shortlist_document_chunks

    chunk_ids = list(
        dict.fromkeys(str(row["chunk_id"]) for row in selected)
    )
    selected_ids = set(chunk_ids)
    parent_ids = list(
        dict.fromkeys(
            str(row["parent_document_id"]) for row in selected
        )
    )
    for parent_id in parent_ids:
        siblings = shortlist_document_chunks(
            question,
            [{"document_id": parent_id}],
            chunks_by_parent=chunks_by_parent,
            per_document=4,
        )
        for sibling in siblings:
            chunk_id = str(sibling["chunk_id"])
            if chunk_id in selected_ids:
                continue
            display_text = str(sibling.get("display_text") or "")
            retrieval_text = str(sibling.get("retrieval_text") or "")
            if (
                _LISTING_TAIL.search(display_text)
                or
                retrieval_text
                and len(retrieval_text) + 64 < len(display_text)
            ):
                continue
            chunk_ids.append(chunk_id)
            selected_ids.add(chunk_id)
            break
        if len(chunk_ids) >= max_chunks:
            break
    return chunk_ids[:max_chunks]


def search_policy_for_product_question(
    question: str,
    *,
    default_as_of: str,
) -> Any:
    from src.v3.build_bm25 import SearchPolicy

    full_date = _FULL_DATE.search(question)
    if full_date is not None:
        as_of = date(
            int(full_date.group(1)),
            int(full_date.group(2)),
            int(full_date.group(3)),
        ).isoformat()
    else:
        year_month = _YEAR_MONTH.search(question)
        if year_month is not None:
            year = int(year_month.group(1))
            month = int(year_month.group(2))
            as_of = date(
                year,
                month,
                monthrange(year, month)[1],
            ).isoformat()
        else:
            month_day = _MONTH_DAY.search(question)
            if month_day is None:
                return SearchPolicy(as_of=default_as_of)
            default_year = date.fromisoformat(default_as_of).year
            as_of = date(
                default_year,
                int(month_day.group(1)),
                int(month_day.group(2)),
            ).isoformat()
    return SearchPolicy(
        default_exposure_only=False,
        allowed_statuses=None,
        as_of=as_of,
    )


def clarification_for_subject_only_question(
    question: str,
    *,
    requirement_queries: list[str] | None,
    selected: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> str | None:
    """Clarify only when the request is just a retrieved document identity."""

    if requirement_queries:
        return None
    stripped = _GENERIC_REQUEST_TAIL.sub("", question).strip()
    if stripped == question.strip():
        return None
    compact = re.sub(r"[^0-9A-Za-z가-힣]+", "", stripped).casefold()
    if len(compact) < 4:
        return None
    for row in selected:
        document = documents_by_id.get(str(row["parent_document_id"]))
        chunk = chunks_by_id.get(str(row["chunk_id"]))
        identities = [str((document or {}).get("title") or "")]
        identities.extend((chunk or {}).get("heading_path") or [])
        for identity in identities:
            identity_compact = re.sub(
                r"[^0-9A-Za-z가-힣]+",
                "",
                str(identity),
            ).casefold()
            if compact in identity_compact:
                return (
                    f"{stripped}의 어떤 정보를 찾을까요? "
                    "예: 조건, 보상, 일정, 비용"
                )
    return None


def normalize_product_question(question: str) -> str:
    normalized = " ".join(str(question or "").split())
    normalized = re.sub(
        r"(?<=[0-9A-Za-z가-힣])"
        r"(?=(?:알려\s*줘|설명해\s*줘)[?？.\s]*$)",
        " ",
        normalized,
    )
    normalized = re.sub(
        r"(?<=[가-힣])제한"
        r"(?=\s+(?:알려\s*줘|설명해\s*줘)[?？.\s]*$)",
        " 제한",
        normalized,
    )
    return normalized


def _runtime_requirement_queries(
    question: str,
    requirement_queries: list[str] | None,
) -> list[str]:
    if requirement_queries is not None:
        return list(
            dict.fromkeys(
                normalized
                for query in requirement_queries
                if (normalized := " ".join(str(query).split()))
            )
        )
    kiwi_queries = kiwi_independent_requirement_queries(question)
    if kiwi_queries:
        return kiwi_queries
    return explicit_question_clauses(question)


def _atomic_reserve_for_requirement_queries(
    requirement_queries: list[str],
) -> int:
    return 3 if len(requirement_queries) > 1 else 1


def _should_render_complete_numbered_list(question: str) -> bool:
    normalized = " ".join(str(question or "").split())
    return (
        any(cue in normalized for cue in _NUMBERED_LIST_REQUEST_CUES)
        and not any(cue in normalized for cue in _SINGLE_LIST_REQUEST_CUES)
    )


def build_product_prompt(
    *,
    question: str,
    evidence_units: list[dict[str, Any]],
) -> str:
    payload = {
        "question": question,
        "evidence_units": product_model_evidence_payload(
            evidence_units
        ),
    }
    return (
        "다음 JSON의 question과 evidence_units만 사용해 답하세요.\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def build_product_coverage_prompt(
    *,
    question: str,
    question_requirements: list[dict[str, str]],
    evidence_units: list[dict[str, Any]],
) -> str:
    payload = {
        "question": question,
        "question_requirements": question_requirements,
        "evidence_units": product_model_evidence_payload(evidence_units),
    }
    return (
        "다음 JSON의 question, question_requirements, evidence_units만 "
        "사용해 답하세요.\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _ollama_chat_url() -> str:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return f"{base_url}/api/chat"


def _ollama_api_url(path: str) -> str:
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "http://localhost:11434/v1",
    ).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return f"{base_url}/{path.lstrip('/')}"


def _snapshot_product_evidence_pack(
    evidence_units: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    snapshots = []
    for unit in evidence_units:
        chunk = chunks_by_id.get(str(unit.get("chunk_id") or ""), {})
        snapshots.append(
            {
                "ref": str(unit["evidence_ref"]),
                "evidence_ref": str(unit["evidence_ref"]),
                "candidate_ref": str(unit.get("candidate_ref") or ""),
                "chunk_id": str(unit.get("chunk_id") or ""),
                "parent_document_id": str(
                    unit.get("parent_document_id") or ""
                ),
                "source_id": unit.get("source_id"),
                "title": unit.get("title") or "",
                "heading_path": list(chunk.get("heading_path") or []),
                "published_at": unit.get("published_at"),
                "valid_from": unit.get("valid_from"),
                "valid_to": unit.get("valid_to"),
                "revision_id": unit.get("revision_id"),
                "status": unit.get("status"),
                "start_offset": int(unit.get("start_char") or 0),
                "end_offset": int(unit.get("end_char") or 0),
                "start_char": int(unit.get("start_char") or 0),
                "end_char": int(unit.get("end_char") or 0),
                "text": str(unit.get("text") or ""),
                "context_text": str(unit.get("context_text") or ""),
                "question_focus": str(unit.get("question_focus") or ""),
                "question_relevance_score": unit.get(
                    "question_relevance_score"
                ),
                "unit_kind": str(unit.get("unit_kind") or ""),
                "complete": bool(unit.get("complete")),
                "complete_list": bool(unit.get("complete_list")),
            }
        )
    return snapshots


def _content_address_from_path(value: Any) -> str | None:
    match = re.search(r"([0-9a-f]{64})(?:\.[^.]+)?$", str(value))
    return match.group(1) if match else None


def _read_git_revision(root: Path) -> str | None:
    git_entry = root / ".git"
    git_dir = git_entry
    if git_entry.is_file():
        line = git_entry.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir:"):
            return None
        git_dir = Path(line.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = (root / git_dir).resolve()
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head or None
    ref_path = git_dir / head.split(":", 1)[1].strip()
    if ref_path.is_file():
        return ref_path.read_text(encoding="utf-8").strip() or None
    packed_refs = git_dir / "packed-refs"
    if packed_refs.is_file():
        ref_name = head.split(":", 1)[1].strip()
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            if line.startswith(("#", "^")):
                continue
            revision, _, name = line.partition(" ")
            if name == ref_name:
                return revision
    return None


def _generate_product_output_native(
    *,
    prompt: str,
    model: str,
    timeout_seconds: float,
    system_instructions: str,
    output_model: type[BaseModel],
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "format": output_model.model_json_schema(),
        "options": {
            "temperature": 0,
            "num_ctx": DEFAULT_CONTEXT_TOKENS,
            "num_predict": DEFAULT_OUTPUT_TOKENS,
        },
    }
    request = Request(
        _ollama_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = json.loads(response.read().decode("utf-8"))
    content = str((raw.get("message") or {}).get("content") or "")
    if not content:
        raise RuntimeError("product_rag_generator_returned_no_content")
    output = output_model.model_validate_json(content)
    input_tokens = int(raw.get("prompt_eval_count") or 0)
    output_tokens = int(raw.get("eval_count") or 0)
    return {
        "output": output.model_dump(),
        "model": raw.get("model") or model,
        "provider": "ollama_native",
        "latency_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def generate_product_output_native(
    *,
    prompt: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    return _generate_product_output_native(
        prompt=prompt,
        model=model,
        timeout_seconds=timeout_seconds,
        system_instructions=PRODUCT_SYSTEM_INSTRUCTIONS,
        output_model=ProductRagOutput,
    )


def generate_product_coverage_output_native(
    *,
    prompt: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    return _generate_product_output_native(
        prompt=prompt,
        model=model,
        timeout_seconds=timeout_seconds,
        system_instructions=PRODUCT_COVERAGE_SYSTEM_INSTRUCTIONS,
        output_model=ProductCoverageOutput,
    )


def _prepare_product_coverage_output(
    output: dict[str, Any],
    *,
    question_requirements: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    allowed_refs = [
        requirement["question_ref"] for requirement in question_requirements
    ]
    allowed_ref_set = set(allowed_refs)
    raw_claims = output.get("claims")
    raw_unsupported = output.get("unsupported_question_refs")
    clarification = str(output.get("clarification") or "").strip()
    issues = []
    if not isinstance(raw_claims, list):
        raw_claims = []
        issues.append("claims_not_list")
    if not isinstance(raw_unsupported, list):
        raw_unsupported = []
        issues.append("unsupported_question_refs_not_list")

    claims = []
    claim_refs = []
    claim_ref_by_text: dict[str, str] = {}
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            issues.append("claim_not_object")
            continue
        question_ref = str(raw_claim.get("question_ref") or "")
        text = str(raw_claim.get("text") or "").strip()
        evidence_refs = [
            str(value) for value in (raw_claim.get("evidence_refs") or [])
        ]
        normalized_text = " ".join(text.split())
        if question_ref not in allowed_ref_set:
            issues.append("unknown_claim_question_ref")
        if question_ref in claim_refs:
            issues.append("duplicate_claim_question_ref")
        if normalized_text in claim_ref_by_text:
            issues.append("duplicate_claim_text")
        claim_refs.append(question_ref)
        claim_ref_by_text[normalized_text] = question_ref
        claims.append({"text": text, "evidence_refs": evidence_refs})

    unsupported_refs = [str(value) for value in raw_unsupported]
    if len(unsupported_refs) != len(set(unsupported_refs)):
        issues.append("duplicate_unsupported_question_ref")
    if any(value not in allowed_ref_set for value in unsupported_refs):
        issues.append("unknown_unsupported_question_ref")
    if set(claim_refs) & set(unsupported_refs):
        issues.append("question_ref_claimed_and_unsupported")

    if clarification:
        if claims or unsupported_refs:
            issues.append("clarification_must_stand_alone")
        provisional_mode = "clarification"
    else:
        covered_refs = set(claim_refs) | set(unsupported_refs)
        if covered_refs != allowed_ref_set:
            issues.append("question_refs_not_exhaustive")
        if claims and unsupported_refs:
            provisional_mode = "partial"
        elif claims:
            provisional_mode = "answer"
        else:
            provisional_mode = "unsupported"

    contract_valid = not issues
    if not contract_valid:
        claims = []
        clarification = ""
        provisional_mode = "unsupported"
        claim_ref_by_text = {}
    legacy_output = {
        "mode": provisional_mode,
        "claims": claims,
        "clarification": clarification,
    }
    state = {
        "enabled": True,
        "contract_valid": contract_valid,
        "issues": list(dict.fromkeys(issues)),
        "question_requirements": question_requirements,
        "model_claimed_question_refs": claim_refs,
        "model_unsupported_question_refs": unsupported_refs,
        "claim_ref_by_text": claim_ref_by_text,
    }
    return legacy_output, state


def _apply_product_coverage_mode(
    verified: dict[str, Any],
    *,
    coverage_state: dict[str, Any],
) -> None:
    allowed_refs = [
        requirement["question_ref"]
        for requirement in coverage_state["question_requirements"]
    ]
    claim_ref_by_text = coverage_state["claim_ref_by_text"]
    accepted_refs = list(
        dict.fromkeys(
            claim_ref_by_text.get(" ".join(str(claim["text"]).split()), "")
            for claim in verified["claims"]
        )
    )
    accepted_refs = [value for value in accepted_refs if value]
    server_unsupported_refs = [
        value for value in allowed_refs if value not in set(accepted_refs)
    ]
    if verified["mode"] != "clarification":
        if len(accepted_refs) == len(allowed_refs):
            verified["mode"] = "answer"
        elif accepted_refs:
            verified["mode"] = "partial"
        else:
            verified["mode"] = "unsupported"
    verified["verification"]["question_coverage_contract"] = {
        key: value
        for key, value in coverage_state.items()
        if key != "claim_ref_by_text"
    } | {
        "accepted_question_refs": accepted_refs,
        "server_unsupported_question_refs": server_unsupported_refs,
    }


def _attach_product_coverage_lexical_overlap_diagnostics(
    verified: dict[str, Any],
    *,
    coverage_state: dict[str, Any],
    evidence_units: list[dict[str, Any]],
) -> None:
    started = time.perf_counter()
    requirement_text_by_ref = {
        requirement["question_ref"]: requirement["text"]
        for requirement in coverage_state["question_requirements"]
    }
    claim_ref_by_text = coverage_state["claim_ref_by_text"]
    diagnostics = []
    for claim in verified["claims"]:
        normalized_text = " ".join(str(claim["text"]).split())
        question_ref = claim_ref_by_text.get(normalized_text)
        if not question_ref:
            continue
        diagnostics.append(
            build_product_coverage_lexical_overlap_diagnostic(
                question_ref=question_ref,
                question_text=requirement_text_by_ref.get(question_ref, ""),
                evidence_refs=[
                    str(value) for value in claim.get("evidence_refs", [])
                ],
                evidence_units=evidence_units,
            )
        )
    verified["verification"][
        "question_coverage_lexical_overlap"
    ] = {
        "enabled": True,
        "diagnostic_only": True,
        "affects_claim_acceptance": False,
        "affects_evidence_selection": False,
        "claims": diagnostics,
        "zero_overlap_question_refs": [
            diagnostic["question_ref"]
            for diagnostic in diagnostics
            if diagnostic["zero_overlap_signal"]
        ],
        "latency_ms": round(
            (time.perf_counter() - started) * 1000,
            6,
        ),
    }


def _verify_product_coverage_claim_output(
    output: dict[str, Any],
    *,
    coverage_state: dict[str, Any],
    question: str,
    evidence_units: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    requested_subjects: list[str] | None,
) -> dict[str, Any]:
    verified = verify_product_claim_output(
        output,
        question=question,
        evidence_units=evidence_units,
        chunks_by_id=chunks_by_id,
        requested_subjects=requested_subjects,
    )
    if output["mode"] == "clarification" or not output["claims"]:
        return verified

    requirement_text_by_ref = {
        requirement["question_ref"]: requirement["text"]
        for requirement in coverage_state["question_requirements"]
    }
    claim_refs = coverage_state["model_claimed_question_refs"]
    per_question_checks = []
    per_question_accepted_texts = set()
    per_question_rejections = []
    for claim_index, (claim, question_ref) in enumerate(
        zip(output["claims"], claim_refs),
        1,
    ):
        requirement_text = requirement_text_by_ref.get(question_ref, "")
        claim_verification = verify_product_claim_output(
            {
                "mode": "answer",
                "claims": [claim],
                "clarification": "",
            },
            question=requirement_text,
            evidence_units=evidence_units,
            chunks_by_id=chunks_by_id,
            requested_subjects=None,
        )
        accepted = bool(claim_verification["claims"])
        per_question_checks.append(
            {
                "question_ref": question_ref,
                "accepted": accepted,
                "reasons": [
                    reason
                    for rejection in claim_verification["rejected_claims"]
                    for reason in rejection["reasons"]
                ],
            }
        )
        if accepted:
            per_question_accepted_texts.add(
                " ".join(str(claim["text"]).split())
            )
        else:
            per_question_rejections.append(
                {
                    "claim_index": claim_index,
                    "text": claim["text"],
                    "evidence_refs": claim["evidence_refs"],
                    "reasons": list(
                        dict.fromkeys(
                            reason
                            for rejection in claim_verification[
                                "rejected_claims"
                            ]
                            for reason in rejection["reasons"]
                        )
                    ),
                }
            )

    verified["claims"] = [
        claim
        for claim in verified["claims"]
        if " ".join(str(claim["text"]).split())
        in per_question_accepted_texts
    ]
    rejected_indexes = {
        int(rejection["claim_index"])
        for rejection in verified["rejected_claims"]
    }
    verified["rejected_claims"].extend(
        rejection
        for rejection in per_question_rejections
        if int(rejection["claim_index"]) not in rejected_indexes
    )
    verified["verification"]["per_question_ref_checks"] = (
        per_question_checks
    )
    if per_question_rejections:
        verified["verification"][
            "raw_output_passed_without_sanitization"
        ] = False
    return verified


def render_product_clarification_options(
    options: list[dict[str, Any]],
) -> str:
    choices = "\n".join(
        f"- {option['option_id']}: {option['title']}"
        for option in options
    )
    return (
        "질문이 여러 문서 맥락에 해당합니다. 어느 내용을 "
        f"말씀하시나요?\n\n{choices}"
    )


def _followup_tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
        if len(token) >= 2
    ]


_CONTEXT_FOCUS_PARTICLES = (
    "에서는",
    "에서",
    "에게",
    "으로",
    "부터",
    "까지",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "에",
)
_CONTEXT_FOCUS_STOPWORDS = {
    "관련",
    "내용",
    "정보",
    "알려줘",
    "설명해줘",
    "뭐야",
    "무엇이야",
}


def _context_focus_tokens(value: str) -> set[str]:
    tokens = set()
    for raw_token in _followup_tokens(value):
        token = raw_token
        for suffix in _CONTEXT_FOCUS_PARTICLES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                token = token[: -len(suffix)]
                break
        if len(token) >= 2 and token not in _CONTEXT_FOCUS_STOPWORDS:
            tokens.add(token)
    return tokens


def resolve_product_clarification_followup(
    followup: str,
    options: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = " ".join(str(followup or "").split()).casefold()
    for option in options:
        if normalized == str(option.get("option_id") or "").casefold():
            return {"status": "resolved", "option": option}
    tokens = _followup_tokens(normalized)
    scores = []
    for option in options:
        compact_title = re.sub(
            r"[^0-9a-z가-힣]+",
            "",
            str(option.get("title") or "").casefold(),
        )
        score = sum(
            len(token) ** 2
            for token in tokens
            if token in compact_title
        )
        scores.append(score)
    best_score = max(scores, default=0)
    if best_score <= 0:
        return {"status": "unmatched", "options": []}
    matched = [
        option
        for option, score in zip(options, scores, strict=True)
        if score == best_score
    ]
    if len(matched) == 1:
        return {"status": "resolved", "option": matched[0]}
    return {"status": "clarification", "options": matched}


def rewrite_product_clarification_question(
    original_question: str,
    option: dict[str, Any],
) -> str:
    return (
        f"{str(original_question).strip()} "
        f"(선택한 문서 맥락: {str(option['title']).strip()})"
    )


def _claim_value_signature(text: str) -> dict[str, set[Any]]:
    dates = set(
        match.group(0)
        for pattern in (
            r"(?<!\d)20\d{2}[./-]\d{1,2}[./-]\d{1,2}(?!\d)",
            r"(?<!\d)20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일",
            r"(?<!\d)\d{1,2}\s*월\s*\d{1,2}\s*일",
        )
        for match in re.finditer(pattern, text)
    )
    percentages = {
        float(match.group(1))
        for match in re.finditer(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:%|퍼센트)",
            text,
        )
    }
    boolean = boolean_value(text)
    return {
        "currency": set(currency_values(text)),
        "number": set(number_values(text)),
        "time": set(time_values(text)),
        "date": dates,
        "percentage": percentages,
        "boolean": {boolean} if boolean is not None else set(),
    }


def _cross_parent_claim_compatibility(
    *,
    question: str,
    claims: list[dict[str, Any]],
    units_by_ref: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    signatures = [
        _claim_value_signature(str(claim.get("text") or ""))
        for claim in claims
    ]
    conflicts = []
    for left_index, left in enumerate(signatures):
        for right_index, right in enumerate(
            signatures[left_index + 1 :],
            left_index + 1,
        ):
            for value_type in left:
                if (
                    left[value_type]
                    and right[value_type]
                    and left[value_type] != right[value_type]
                ):
                    conflicts.append(
                        {
                            "left_claim_index": left_index,
                            "right_claim_index": right_index,
                            "value_type": value_type,
                            "left_values": sorted(
                                str(value) for value in left[value_type]
                            ),
                            "right_values": sorted(
                                str(value) for value in right[value_type]
                            ),
                        }
                    )

    claim_scopes = []
    for claim in claims:
        intervals = set()
        headings = set()
        title_revisions: dict[str, set[str]] = {}
        title_revision_entries = []
        parents = set()
        evidence_lengths = []
        for evidence_ref in claim.get("evidence_refs") or []:
            unit = units_by_ref.get(str(evidence_ref))
            if unit is None:
                continue
            parent = str(
                unit.get("parent_document_id")
                or unit.get("chunk_id")
                or ""
            )
            if parent:
                parents.add(parent)
            valid_from = str(unit.get("valid_from") or "")
            valid_to = str(unit.get("valid_to") or "")
            if valid_from or valid_to:
                intervals.add((valid_from, valid_to))
            chunk = chunks_by_id.get(str(unit.get("chunk_id") or ""), {})
            heading = tuple(
                str(part).strip()
                for part in (chunk.get("heading_path") or [])
                if str(part).strip()
            )
            if heading:
                headings.add(heading)
            title = re.sub(
                r"[^0-9a-z가-힣]+",
                "",
                str(unit.get("title") or "").casefold(),
            )
            revision = str(unit.get("revision_id") or "")
            if title and revision:
                title_revisions.setdefault(title, set()).add(revision)
                title_revision_entries.append(
                    (
                        _context_focus_tokens(
                            str(unit.get("title") or "")
                        ),
                        revision,
                        str(unit.get("title") or ""),
                    )
                )
            evidence_lengths.append(len(str(unit.get("text") or "")))
        claim_scopes.append(
            {
                "intervals": intervals,
                "headings": headings,
                "title_revisions": title_revisions,
                "title_revision_entries": title_revision_entries,
                "parents": parents,
                "evidence_length": max(evidence_lengths, default=0),
            }
        )
    nonempty_intervals = {
        interval
        for scope in claim_scopes
        for interval in scope["intervals"]
    }
    nonempty_headings = {
        heading
        for scope in claim_scopes
        for heading in scope["headings"]
    }
    revisions_by_title: dict[str, set[str]] = {}
    for scope in claim_scopes:
        for title, revisions in scope["title_revisions"].items():
            revisions_by_title.setdefault(title, set()).update(revisions)
    revision_scope_conflicts = {
        title
        for title, revisions in revisions_by_title.items()
        if len(revisions) > 1
    }
    revision_entries = [
        entry
        for scope in claim_scopes
        for entry in scope["title_revision_entries"]
    ]
    for index, (left_tokens, left_revision, left_title) in enumerate(
        revision_entries
    ):
        for right_tokens, right_revision, right_title in revision_entries[
            index + 1 :
        ]:
            union = left_tokens | right_tokens
            if (
                left_revision != right_revision
                and union
                and len(left_tokens & right_tokens) / len(union) >= 0.6
            ):
                revision_scope_conflicts.add(
                    f"{left_title} <> {right_title}"
                )
    scope_conflicts = {
        "temporal_intervals": sorted(nonempty_intervals),
        "heading_paths": sorted(nonempty_headings),
        "revision_titles": sorted(
            revision_scope_conflicts
        ),
    }
    scope_compatible = bool(
        len(nonempty_intervals) <= 1
        and len(nonempty_headings) <= 1
        and not scope_conflicts["revision_titles"]
    )

    token_sets = [
        _context_focus_tokens(str(claim.get("text") or ""))
        for claim in claims
    ]
    detail_index = max(
        range(len(claims)),
        key=lambda index: (
            claim_scopes[index]["evidence_length"],
            len(token_sets[index]),
            len(str(claims[index].get("text") or "")),
            -index,
        ),
    )
    claim_indexes_by_parent: dict[str, set[int]] = {}
    for claim_index, scope in enumerate(claim_scopes):
        for parent in scope["parents"]:
            claim_indexes_by_parent.setdefault(parent, set()).add(
                claim_index
            )
    compatible_parent_indexes = max(
        claim_indexes_by_parent.values(),
        key=lambda indexes: (
            len(indexes),
            sum(
                claim_scopes[index]["evidence_length"]
                for index in indexes
            ),
            -min(indexes),
        ),
        default=set(),
    )
    keep_claim_indexes = (
        sorted(compatible_parent_indexes)
        if len(compatible_parent_indexes) > 1
        else [detail_index]
    )
    detail_tokens = token_sets[detail_index]
    subset_or_detail = all(
        not tokens
        or tokens <= detail_tokens
        or len(tokens & detail_tokens) / len(tokens) >= 0.75
        for tokens in token_sets
    )
    procedural_question = bool(
        re.search(r"어디|어떻게|방법|경로|절차", question)
    )
    compatible = bool(
        not conflicts
        and scope_compatible
        and (procedural_question or subset_or_detail)
    )
    return {
        "compatible": compatible,
        "keep_claim_indexes": keep_claim_indexes if compatible else [],
        "value_conflicts": conflicts,
        "scope_compatible": scope_compatible,
        "scope_conflicts": scope_conflicts,
        "subset_or_detail": subset_or_detail,
        "procedural_question": procedural_question,
    }


def _cross_parent_clarification(
    *,
    question: str,
    claims: list[dict[str, Any]],
    evidence_units: list[dict[str, Any]],
    requested_subjects: list[str] | None,
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    question_clauses = explicit_question_clauses(question)
    if len(explicit_question_subjects(question)) > 1:
        return None
    if len(requested_subjects or []) > 1:
        return None
    if len(claims) < 2:
        return None
    units_by_ref = {
        str(unit["evidence_ref"]): unit for unit in evidence_units
    }
    contexts: dict[str, dict[str, Any]] = {}
    claim_parent_sets = []
    for claim_index, claim in enumerate(claims):
        claim_parents = set()
        for evidence_ref in claim.get("evidence_refs") or []:
            unit = units_by_ref.get(str(evidence_ref))
            if unit is None:
                continue
            parent = str(
                unit.get("parent_document_id")
                or unit.get("chunk_id")
                or ""
            )
            title = str(unit.get("title") or "").strip()
            if parent and title:
                contexts.setdefault(parent, unit)
                claim_parents.add(parent)
        if claim_parents:
            claim_parent_sets.append((claim_index, claim_parents))
    if not any(
        left.isdisjoint(right)
        for index, (_, left) in enumerate(claim_parent_sets)
        for _, right in claim_parent_sets[index + 1 :]
    ):
        return None
    titles = list(
        dict.fromkeys(
            str(unit.get("title") or "").strip()
            for unit in contexts.values()
        )
    )
    if len(titles) < 2:
        return None
    if len(question_clauses) == len(contexts) and len(contexts) > 1:
        context_rows = list(contexts.items())
        clause_scores = [
            [
                sum(
                    len(token) ** 2
                    for token in _context_focus_tokens(
                        " ".join(
                            (
                                str(unit.get("title") or ""),
                                str(unit.get("context_text") or ""),
                                str(unit.get("text") or ""),
                            )
                        )
                    )
                    if token in re.sub(
                        r"[^0-9a-z가-힣]+",
                        "",
                        clause.casefold(),
                    )
                )
                for clause in question_clauses
            ]
            for _, unit in context_rows
        ]
        assignments = sorted(
            (
                (
                    sum(
                        clause_scores[row_index][clause_index]
                        for row_index, clause_index in enumerate(
                            assignment
                        )
                    ),
                    assignment,
                )
                for assignment in permutations(
                    range(len(question_clauses))
                )
            ),
            reverse=True,
        )
        best_total, best_assignment = assignments[0]
        second_total = assignments[1][0] if len(assignments) > 1 else -1
        if (
            best_total > second_total
            and all(
                clause_scores[row_index][clause_index] > 0
                for row_index, clause_index in enumerate(best_assignment)
            )
        ):
            return None
    question_focus = _context_focus_tokens(question)
    focus_scores = []
    for parent, unit in contexts.items():
        title = str(unit.get("title") or "").strip()
        matched_tokens = sorted(
            question_focus & _context_focus_tokens(title)
        )
        focus_scores.append(
            {
                "parent_document_id": parent,
                "candidate_ref": str(unit.get("candidate_ref") or ""),
                "title": title,
                "matched_tokens": matched_tokens,
                "overlap": len(matched_tokens),
            }
        )
    focus_scores.sort(
        key=lambda row: (
            -int(row["overlap"]),
            int(row["candidate_ref"] or 0),
            str(row["parent_document_id"]),
        )
    )
    best_focus = focus_scores[0]
    second_overlap = int(focus_scores[1]["overlap"])
    if len(question_clauses) > 1 and second_overlap < 2:
        return None
    if (
        int(best_focus["overlap"]) >= 2
        and int(best_focus["overlap"]) - second_overlap >= 2
    ):
        dominant_parent = str(best_focus["parent_document_id"])
        keep_claim_indexes = [
            claim_index
            for claim_index, parents in claim_parent_sets
            if dominant_parent in parents
        ]
        if keep_claim_indexes:
            return {
                "action": "dominant_parent",
                "dominant_parent_document_id": dominant_parent,
                "keep_claim_indexes": keep_claim_indexes,
                "diagnostics": {
                    "decision": "dominant_parent",
                    "focus_scores": focus_scores,
                },
            }
    compatibility = _cross_parent_claim_compatibility(
        question=question,
        claims=claims,
        units_by_ref=units_by_ref,
        chunks_by_id=chunks_by_id,
    )
    if compatibility["compatible"]:
        return {
            "action": "compatible_detail",
            "keep_claim_indexes": compatibility["keep_claim_indexes"],
            "diagnostics": {
                "decision": "compatible_detail",
                "focus_scores": focus_scores,
                "compatibility": compatibility,
            },
        }
    selected_title_compacts = [
        re.sub(r"[^0-9a-z가-힣]+", "", title.casefold())
        for title in titles
    ]
    anchors = [
        token
        for token in _followup_tokens(question)
        if sum(token in title for title in selected_title_compacts) >= 2
    ]
    option_units = []
    seen_parents = set()
    seen_titles = set()
    for unit in sorted(
        evidence_units,
        key=lambda value: (
            int(value.get("candidate_ref") or 0),
            int(value.get("start_char") or 0),
        ),
    ):
        parent = str(
            unit.get("parent_document_id")
            or unit.get("chunk_id")
            or ""
        )
        title = str(unit.get("title") or "").strip()
        compact_title = re.sub(
            r"[^0-9a-z가-힣]+",
            "",
            title.casefold(),
        )
        if not parent or not title:
            continue
        if parent not in contexts and not any(
            anchor in compact_title for anchor in anchors
        ):
            continue
        if parent in seen_parents or title in seen_titles:
            continue
        option_units.append(unit)
        seen_parents.add(parent)
        seen_titles.add(title)
        if len(option_units) >= 6:
            break
    options = [
        {
            "option_id": f"C{index}",
            "parent_document_id": str(
                unit.get("parent_document_id")
                or unit.get("chunk_id")
            ),
            "candidate_ref": str(unit.get("candidate_ref") or ""),
            "title": str(unit["title"]).strip(),
        }
        for index, unit in enumerate(option_units, 1)
    ]
    if len(options) < 2:
        return None
    return {
        "action": "clarification",
        "clarification": render_product_clarification_options(options),
        "options": options,
        "diagnostics": {
            "decision": "clarification",
            "focus_scores": focus_scores,
        },
    }


def answer_product_rag_from_candidates(
    *,
    question: str,
    requirement_queries: list[str] | None,
    requested_subjects: list[str] | None,
    selected: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    temporal_by_document: dict[str, dict[str, Any]],
    model: str,
    timeout_seconds: float,
    generator: Callable[..., dict[str, Any]] | None = None,
    evidence_units_override: list[dict[str, Any]] | None = None,
    use_question_coverage_contract: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    candidate_chunk_ids = [str(row["chunk_id"]) for row in selected]
    if not candidate_chunk_ids:
        return {
            "product_free_rag_version": PRODUCT_FREE_RAG_VERSION,
            "question": question,
            "mode": "unsupported",
            "claims": [],
            "rejected_claims": [],
            "clarification": "",
            "rendered_answer": "",
            "candidates": [],
            "evidence_unit_count": 0,
            "evidence_pack": [],
            "raw_model_output": None,
            "generation": None,
            "verification": {
                "all_exposed_citations_verified": True,
                "reason": "no_retrieval_candidates",
            },
            "latency_ms": round(
                (time.perf_counter() - started) * 1000,
                3,
            ),
        }
    evidence_units = (
        list(evidence_units_override)
        if evidence_units_override is not None
        else build_product_evidence_pack(
            candidate_chunk_ids,
            question=question,
            requirement_queries=requirement_queries,
            requested_subjects=requested_subjects,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=temporal_by_document,
            max_units=DEFAULT_EVIDENCE_UNITS,
        )
    )
    coverage_state = None
    if use_question_coverage_contract:
        question_requirements = build_product_question_requirements(question)
        prompt = build_product_coverage_prompt(
            question=question,
            question_requirements=question_requirements,
            evidence_units=evidence_units,
        )
        generate = generator or generate_product_coverage_output_native
    else:
        question_requirements = []
        prompt = build_product_prompt(
            question=question,
            evidence_units=evidence_units,
        )
        generate = generator or generate_product_output_native
    generated = generate(
        prompt=prompt,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    raw_model_output = copy.deepcopy(generated["output"])
    generated_output = generated["output"]
    if use_question_coverage_contract:
        generated_output, coverage_state = _prepare_product_coverage_output(
            generated_output,
            question_requirements=question_requirements,
        )
    if coverage_state is None:
        verified = verify_product_claim_output(
            generated_output,
            question=question,
            evidence_units=evidence_units,
            chunks_by_id=chunks_by_id,
            requested_subjects=requested_subjects,
        )
    else:
        verified = _verify_product_coverage_claim_output(
            generated_output,
            coverage_state=coverage_state,
            question=question,
            evidence_units=evidence_units,
            chunks_by_id=chunks_by_id,
            requested_subjects=requested_subjects,
        )
    unique_claims = []
    seen_claim_texts = set()
    for claim in verified["claims"]:
        normalized_text = " ".join(str(claim["text"]).split())
        if normalized_text in seen_claim_texts:
            continue
        seen_claim_texts.add(normalized_text)
        unique_claims.append(claim)
    verified["claims"] = unique_claims
    units_by_ref = {
        str(unit["evidence_ref"]): unit
        for unit in evidence_units
    }
    cross_parent_clarification = _cross_parent_clarification(
        question=question,
        claims=verified["claims"],
        evidence_units=evidence_units,
        requested_subjects=requested_subjects,
        chunks_by_id=chunks_by_id,
    )
    if cross_parent_clarification is not None:
        verified["verification"]["cross_parent_context"] = (
            cross_parent_clarification["diagnostics"]
        )
        if cross_parent_clarification["action"] in {
            "dominant_parent",
            "compatible_detail",
        }:
            keep_claim_indexes = set(
                cross_parent_clarification["keep_claim_indexes"]
            )
            original_claims = verified["claims"]
            verified["claims"] = [
                claim
                for index, claim in enumerate(original_claims)
                if index in keep_claim_indexes
            ]
            verified["rejected_claims"].extend(
                {
                    "claim_index": index + 1,
                    "text": claim["text"],
                    "evidence_refs": claim["evidence_refs"],
                    "reasons": [
                        (
                            "weaker_cross_parent_context"
                            if cross_parent_clarification["action"]
                            == "dominant_parent"
                            else "redundant_compatible_cross_parent_context"
                        )
                    ],
                }
                for index, claim in enumerate(original_claims)
                if index not in keep_claim_indexes
            )
            verified["verification"].update(
                {
                    "reason": (
                        "dominant_cross_parent_context"
                        if cross_parent_clarification["action"]
                        == "dominant_parent"
                        else "compatible_cross_parent_detail"
                    ),
                    "raw_output_passed_without_sanitization": False,
                }
            )
        else:
            verified["rejected_claims"].extend(
                {
                    "claim_index": index,
                    "text": claim["text"],
                    "evidence_refs": list(claim["evidence_refs"]),
                    "reasons": ["ambiguous_cross_parent_context"],
                }
                for index, claim in enumerate(verified["claims"], 1)
            )
            verified["mode"] = "clarification"
            verified["claims"] = []
            verified["clarification"] = cross_parent_clarification[
                "clarification"
            ]
            verified["clarification_options"] = (
                cross_parent_clarification["options"]
            )
            verified["verification"].update(
                {
                    "reason": "ambiguous_cross_parent_context",
                    "covered_subjects": [],
                    "all_requested_subjects_covered": not requested_subjects,
                    "all_explicit_question_clauses_covered": False,
                    "clarification_contract_valid": True,
                    "raw_output_passed_without_sanitization": False,
                }
            )
    verified.setdefault("clarification_options", [])
    if coverage_state is not None:
        _apply_product_coverage_mode(
            verified,
            coverage_state=coverage_state,
        )
        _attach_product_coverage_lexical_overlap_diagnostics(
            verified,
            coverage_state=coverage_state,
            evidence_units=evidence_units,
        )
    rendered_parts = []
    rendered_list_refs = set()
    render_complete_lists = _should_render_complete_numbered_list(question)
    for claim in verified["claims"]:
        claim_list_refs = [
            evidence_ref
            for evidence_ref in claim["evidence_refs"]
            if (
                (unit := units_by_ref.get(evidence_ref)) is not None
                and unit.get("complete_list")
                and evidence_ref not in rendered_list_refs
            )
        ]
        if render_complete_lists and claim_list_refs:
            for evidence_ref in claim_list_refs:
                rendered_parts.append(units_by_ref[evidence_ref]["text"])
                rendered_list_refs.add(evidence_ref)
            continue
        rendered_parts.append(claim["text"])
    if verified["mode"] == "clarification":
        rendered_parts.append(verified["clarification"])
    rendered_table_refs = set()
    for claim in verified["claims"]:
        for evidence_ref in claim["evidence_refs"]:
            unit = units_by_ref.get(evidence_ref)
            if (
                unit is None
                or not unit.get("complete")
                or evidence_ref in rendered_table_refs
            ):
                continue
            rendered_parts.append(
                f"### {unit.get('table_label') or unit['title']}\n"
                f"{unit['text']}"
            )
            rendered_table_refs.add(evidence_ref)
    return {
        "product_free_rag_version": PRODUCT_FREE_RAG_VERSION,
        "question": question,
        **verified,
        "rendered_answer": "\n\n".join(rendered_parts),
        "candidates": [
            {
                "candidate_ref": str(index),
                "chunk_id": row["chunk_id"],
                "parent_document_id": row["parent_document_id"],
                "source_id": row.get("source_id"),
                "title": row.get("title"),
                "published_at": row.get("published_at"),
                "status": row.get("status"),
                "reranker_score": row.get("reranker_score"),
            }
            for index, row in enumerate(selected, 1)
        ],
        "evidence_unit_count": len(evidence_units),
        "evidence_pack": _snapshot_product_evidence_pack(
            evidence_units,
            chunks_by_id=chunks_by_id,
        ),
        "raw_model_output": raw_model_output,
        "generation": {
            key: value
            for key, value in generated.items()
            if key != "output"
        },
        "latency_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
    }


def _fanout_ref(prefix: str, value: Any) -> str:
    reference = str(value or "")
    return f"{prefix}{reference}" if reference else reference


def _merge_requirement_fanout_results(
    *,
    question: str,
    requirement_queries: list[str],
    child_results: list[dict[str, Any]],
    total_ms: float,
) -> dict[str, Any]:
    modes = [str(result.get("mode") or "unsupported") for result in child_results]
    clarification = "\n\n".join(
        str(result.get("clarification") or "").strip()
        for result in child_results
        if str(result.get("clarification") or "").strip()
    )
    if "clarification" in modes:
        mode = "clarification"
    elif modes and all(value == "answer" for value in modes):
        mode = "answer"
    elif modes and all(value == "unsupported" for value in modes):
        mode = "unsupported"
    else:
        mode = "partial"

    claims = []
    rejected_claims = []
    candidates = []
    evidence_pack = []
    clarification_options = []
    rendered_parts = []
    fanout_requirements = []
    generation_calls = []
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    all_citations_verified = True
    for index, (query, child) in enumerate(
        zip(requirement_queries, child_results, strict=True),
        1,
    ):
        prefix = f"F{index}"
        remapped_claims = []
        for claim in child.get("claims") or []:
            remapped = copy.deepcopy(claim)
            remapped["evidence_refs"] = [
                _fanout_ref(prefix, value)
                for value in claim.get("evidence_refs") or []
            ]
            for citation in remapped.get("citations") or []:
                citation["evidence_ref"] = _fanout_ref(
                    prefix,
                    citation.get("evidence_ref"),
                )
            remapped_claims.append(remapped)
        for rejection in child.get("rejected_claims") or []:
            remapped = copy.deepcopy(rejection)
            remapped["evidence_refs"] = [
                _fanout_ref(prefix, value)
                for value in rejection.get("evidence_refs") or []
            ]
            rejected_claims.append(remapped)
        for candidate in child.get("candidates") or []:
            remapped = copy.deepcopy(candidate)
            remapped["candidate_ref"] = _fanout_ref(
                f"{prefix}C",
                candidate.get("candidate_ref"),
            )
            remapped["fanout_requirement_index"] = index
            candidates.append(remapped)
        for unit in child.get("evidence_pack") or []:
            remapped = copy.deepcopy(unit)
            evidence_ref = unit.get("evidence_ref") or unit.get("ref")
            remapped_ref = _fanout_ref(prefix, evidence_ref)
            remapped["ref"] = remapped_ref
            remapped["evidence_ref"] = remapped_ref
            if unit.get("candidate_ref") is not None:
                remapped["candidate_ref"] = _fanout_ref(
                    f"{prefix}C",
                    unit.get("candidate_ref"),
                )
            remapped["fanout_requirement_index"] = index
            evidence_pack.append(remapped)
        clarification_options.extend(
            copy.deepcopy(child.get("clarification_options") or [])
        )
        if mode != "clarification":
            claims.extend(remapped_claims)
            if child.get("mode") in {"answer", "partial"}:
                rendered = str(child.get("rendered_answer") or "").strip()
                if rendered:
                    rendered_parts.append(rendered)
        else:
            rejected_claims.extend(
                {
                    "claim_index": claim_index,
                    "text": claim.get("text") or "",
                    "evidence_refs": claim.get("evidence_refs") or [],
                    "reasons": ["fanout_clarification_precedence"],
                }
                for claim_index, claim in enumerate(remapped_claims, 1)
            )
        generation = child.get("generation")
        if generation is not None:
            generation_calls.append(copy.deepcopy(generation))
            child_usage = generation.get("usage") or {}
            for key in usage:
                usage[key] += int(child_usage.get(key) or 0)
        child_verification = child.get("verification") or {}
        all_citations_verified = all_citations_verified and bool(
            child_verification.get("all_exposed_citations_verified", True)
        )
        fanout_requirements.append(
            {
                "requirement_index": index,
                "requirement_query": query,
                "mode": child.get("mode"),
                "claims": remapped_claims,
                "generation_called": generation is not None,
                "latency_ms": child.get("latency_ms"),
            }
        )

    generation_ms = sum(
        float((result.get("generation") or {}).get("latency_ms") or 0.0)
        for result in child_results
    )
    profile = {
        "requirement_fanout": True,
        "requirement_count": len(requirement_queries),
        "question_coverage_contract": False,
    }
    first_fingerprint = child_results[0].get("runtime_fingerprint") or {}
    runtime_fingerprint = (
        {**copy.deepcopy(first_fingerprint), "profile": profile}
        if isinstance(first_fingerprint, dict)
        else {"profile": profile}
    )
    rendered_answer = clarification if mode == "clarification" else "\n\n".join(
        rendered_parts
    )
    return {
        "product_free_rag_version": PRODUCT_FREE_RAG_VERSION,
        "question": question,
        "mode": mode,
        "model_mode": None,
        "claims": claims,
        "rejected_claims": rejected_claims,
        "clarification": clarification if mode == "clarification" else "",
        "clarification_options": clarification_options,
        "rendered_answer": rendered_answer,
        "candidates": candidates,
        "evidence_unit_count": len(evidence_pack),
        "evidence_pack": evidence_pack,
        "raw_model_output": {
            "fanout": [
                copy.deepcopy(result.get("raw_model_output"))
                for result in child_results
            ]
        },
        "generation": {
            "fanout_call_count": len(generation_calls),
            "calls": generation_calls,
            "latency_ms": round(generation_ms, 3),
            "usage": usage,
        },
        "verification": {
            "all_exposed_citations_verified": all_citations_verified,
            "qwen_called": bool(generation_calls),
            "requirement_fanout": True,
            "requirement_modes": modes,
        },
        "fanout_requirements": fanout_requirements,
        "latency": {
            "generation_ms": round(generation_ms, 3),
            "child_total_ms": round(
                sum(float(result.get("latency_ms") or 0.0) for result in child_results),
                3,
            ),
            "total_ms": round(total_ms, 3),
        },
        "latency_ms": round(total_ms, 3),
        "experimental_profile": profile,
        "runtime_fingerprint": runtime_fingerprint,
    }


class ProductFreeRAG:
    """Independent retrieve-rerank-answer path without the research planner."""

    def __init__(
        self,
        *,
        root: Path,
        model: str = "qwen3-8b:ctx8192",
        device: str | None = None,
        timeout: float = 180.0,
        use_identity_shortlist: bool = False,
        use_compact_evidence_pack: bool = False,
        use_atomic_evidence_reranker: bool = False,
        handoff_cuda_to_generation: bool = False,
        use_requirement_fanout: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.model = model
        self.device = device
        self.timeout = timeout
        self.use_identity_shortlist = use_identity_shortlist
        self.use_compact_evidence_pack = use_compact_evidence_pack
        if use_atomic_evidence_reranker and not use_compact_evidence_pack:
            raise ValueError(
                "atomic evidence reranking requires the compact evidence pack"
            )
        self.use_atomic_evidence_reranker = use_atomic_evidence_reranker
        self.handoff_cuda_to_generation = handoff_cuda_to_generation
        self.use_requirement_fanout = use_requirement_fanout
        self.temporal_by_document = {
            row["document_id"]: row
            for row in read_jsonl(self.root / GLOBAL_TEMPORAL_OVERLAY)
        }
        self._artifacts: Any = None
        self._embedder: Any = None
        self._reranker: Any = None
        self._metadata_snapshot: dict[str, Any] | None = None
        self._metadata_documents: list[dict[str, Any]] | None = None
        self._retrieval_models_offloaded = False

    def _initialize(self) -> None:
        if self._artifacts is not None:
            return
        import numpy as np
        import torch
        from sentence_transformers import CrossEncoder, SentenceTransformer

        from src.v3.retrieve_v3 import load_runtime_artifacts
        from src.v3.score_evidence_reranker import (
            MAX_LENGTH,
            MODEL_NAME,
            MODEL_REVISION,
        )

        self._artifacts = load_runtime_artifacts(self.root)
        device = self.device or (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        dense_model = self._artifacts.dense_model
        self._embedder = SentenceTransformer(
            dense_model["model_name"],
            device=device,
            local_files_only=True,
        )
        self._embedder.max_seq_length = dense_model[
            "max_sequence_length"
        ]
        self._reranker = CrossEncoder(
            MODEL_NAME,
            revision=MODEL_REVISION,
            max_length=MAX_LENGTH,
            device=device,
            local_files_only=True,
        )
        self.device = device
        self._np = np
        self._torch = torch

    def _ensure_retrieval_models_on_device(self) -> None:
        if not self._retrieval_models_offloaded:
            return
        self._embedder.to(self.device)
        self._reranker.model.to(self.device)
        self._retrieval_models_offloaded = False

    @staticmethod
    def _module_device(module: Any) -> str | None:
        device = getattr(module, "device", None)
        if device is not None:
            return str(device)
        try:
            return str(next(module.parameters()).device)
        except (AttributeError, StopIteration, TypeError):
            return None

    def record_cuda_memory_diagnostic(
        self,
        stage: str,
        hook: Callable[[dict[str, Any]], None] | None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if hook is None:
            return
        snapshot: dict[str, Any] = {
            "stage": stage,
            "captured_at_unix_ms": round(time.time() * 1000, 3),
            "process_id": os.getpid(),
            "runtime_initialized": self._artifacts is not None,
            "configured_device": self.device,
            "retrieval_models_offloaded": self._retrieval_models_offloaded,
            "embedder_object_id": (
                id(self._embedder) if self._embedder is not None else None
            ),
            "reranker_object_id": (
                id(self._reranker) if self._reranker is not None else None
            ),
            "reranker_model_object_id": (
                id(self._reranker.model)
                if self._reranker is not None
                else None
            ),
            "embedder_device": (
                self._module_device(self._embedder)
                if self._embedder is not None
                else None
            ),
            "reranker_device": (
                self._module_device(self._reranker.model)
                if self._reranker is not None
                else None
            ),
        }
        if details:
            snapshot["details"] = dict(details)
        torch = getattr(self, "_torch", None)
        cuda_available = bool(
            torch is not None and torch.cuda.is_available()
        )
        snapshot["cuda_available"] = cuda_available
        if cuda_available:
            device_index = torch.cuda.current_device()
            free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
            snapshot.update(
                {
                    "cuda_device_index": int(device_index),
                    "torch_allocated_bytes": int(
                        torch.cuda.memory_allocated(device_index)
                    ),
                    "torch_reserved_bytes": int(
                        torch.cuda.memory_reserved(device_index)
                    ),
                    "torch_max_allocated_bytes": int(
                        torch.cuda.max_memory_allocated(device_index)
                    ),
                    "torch_max_reserved_bytes": int(
                        torch.cuda.max_memory_reserved(device_index)
                    ),
                    "device_free_bytes": int(free_bytes),
                    "device_total_bytes": int(total_bytes),
                }
            )
        ollama: dict[str, Any] = {
            "query_ok": False,
            "models": [],
            "size_vram": 0,
        }
        try:
            request = Request(_ollama_api_url("api/ps"), method="GET")
            with urlopen(request, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = []
            for row in payload.get("models") or []:
                models.append(
                    {
                        "name": row.get("name") or row.get("model"),
                        "size": int(row.get("size") or 0),
                        "size_vram": int(row.get("size_vram") or 0),
                        "expires_at": row.get("expires_at"),
                    }
                )
            ollama.update(
                {
                    "query_ok": True,
                    "models": models,
                    "size_vram": sum(row["size_vram"] for row in models),
                }
            )
        except Exception as exc:
            ollama["error"] = f"{type(exc).__name__}: {exc}"
        snapshot["ollama"] = ollama
        hook(snapshot)

    def _runtime_fingerprint(
        self,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        provenance = dict(getattr(self._artifacts, "provenance", {}) or {})
        return {
            "corpus_sha": _content_address_from_path(
                provenance.get("documents_path")
            ),
            "chunk_sha": _content_address_from_path(
                provenance.get("chunks_path")
            ),
            "code_rev": (
                os.environ.get("PRODUCT_FREE_RAG_CODE_REV")
                or _read_git_revision(self.root)
            ),
            "profile": copy.deepcopy(profile),
            "bm25_manifest_sha256": provenance.get(
                "bm25_manifest_sha256"
            ),
            "dense_manifest_sha256": provenance.get(
                "dense_manifest_sha256"
            ),
            "model": self.model,
        }

    def _handoff_cuda_models_to_generation(self) -> float:
        if (
            not self.handoff_cuda_to_generation
            or self.device != "cuda"
            or self._retrieval_models_offloaded
        ):
            return 0.0
        import gc

        started = time.perf_counter()
        self._embedder.to("cpu")
        self._reranker.model.to("cpu")
        gc.collect()
        self._torch.cuda.empty_cache()
        self._torch.cuda.synchronize()
        self._retrieval_models_offloaded = True
        return (time.perf_counter() - started) * 1000

    def _encode_queries(
        self,
        queries: list[str],
        *,
        latency_breakdown: dict[str, float] | None = None,
    ) -> Any:
        initialized = time.perf_counter()
        self._initialize()
        if latency_breakdown is not None:
            latency_breakdown["initialization_ms"] += (
                time.perf_counter() - initialized
            ) * 1000
        reloaded = time.perf_counter()
        self._ensure_retrieval_models_on_device()
        if latency_breakdown is not None:
            latency_breakdown["model_reload_ms"] += (
                time.perf_counter() - reloaded
            ) * 1000
        embedded = time.perf_counter()
        encoded = self._embedder.encode(
            queries,
            batch_size=min(8, len(queries)),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        if self.device == "cuda":
            self._torch.cuda.synchronize()
        if latency_breakdown is not None:
            latency_breakdown["query_embedding_ms"] += (
                time.perf_counter() - embedded
            ) * 1000
        return self._np.asarray(encoded, dtype="<f4")

    def _score_pairs(
        self,
        pairs: list[tuple[str, str]],
    ) -> list[float]:
        from src.v3.score_evidence_reranker import BATCH_SIZE

        scores = self._reranker.predict(
            pairs,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if self.device == "cuda":
            self._torch.cuda.synchronize()
        values = self._np.asarray(scores, dtype=self._np.float64).reshape(-1)
        if len(values) != len(pairs) or not self._np.isfinite(values).all():
            raise RuntimeError("reranker scores are missing or non-finite")
        return values.tolist()

    def retrieve(
        self,
        question: str,
        *,
        requirement_queries: list[str] | None = None,
        default_as_of: str | None = None,
        diagnostics_hook: Callable[[dict[str, Any]], None] | None = None,
        latency_breakdown: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        from src.v3.retrieve_v3 import retrieve_with_embedding

        normalized = normalize_product_question(question)
        if not normalized:
            raise RuntimeError("question must not be empty")
        effective_requirement_queries = _runtime_requirement_queries(
            normalized,
            requirement_queries,
        )
        queries = list(
            dict.fromkeys(
                [
                    normalized,
                    *(
                        " ".join(query.split())
                        for query in effective_requirement_queries
                        if query.strip()
                    ),
                ]
            )
        )
        if latency_breakdown is None:
            embeddings = self._encode_queries(queries)
        else:
            embeddings = self._encode_queries(
                queries,
                latency_breakdown=latency_breakdown,
            )
        searched = time.perf_counter()
        policy = search_policy_for_product_question(
            normalized,
            default_as_of=default_as_of or date.today().isoformat(),
        )
        union_by_chunk: dict[str, dict[str, Any]] = {}
        for query_index, (query, embedding) in enumerate(
            zip(queries, embeddings, strict=True)
        ):
            hits = retrieve_with_embedding(
                query,
                embedding,
                self._artifacts,
                top_k=DEFAULT_RETRIEVAL_DEPTH,
                policy=policy,
            )
            for hit in hits:
                chunk_id = str(hit["chunk_id"])
                if chunk_id not in union_by_chunk:
                    union_by_chunk[chunk_id] = {
                        **hit,
                        "query_indexes": [query_index],
                    }
                else:
                    union_by_chunk[chunk_id]["query_indexes"].append(
                        query_index
                    )
        shortlisted_documents = []
        if self.use_identity_shortlist:
            from src.v3.product_candidate_identity import (
                candidate_row_from_chunk,
                shortlist_document_chunks,
                shortlist_identity_documents,
            )

            chunks_by_parent: dict[str, list[dict[str, Any]]] = {}
            for chunk in self._artifacts.chunks_by_id.values():
                chunks_by_parent.setdefault(
                    str(chunk["parent_document_id"]),
                    [],
                ).append(chunk)
            shortlisted_documents = shortlist_identity_documents(
                normalized,
                documents_by_id=self._artifacts.documents_by_id,
                chunks_by_parent=chunks_by_parent,
            )
            shortlisted_chunks = shortlist_document_chunks(
                normalized,
                shortlisted_documents,
                chunks_by_parent=chunks_by_parent,
            )
            for chunk in shortlisted_chunks:
                chunk_id = str(chunk["chunk_id"])
                union_by_chunk.setdefault(
                    chunk_id,
                    candidate_row_from_chunk(
                        chunk,
                        self._artifacts.documents_by_id[
                            chunk["parent_document_id"]
                        ],
                        fallback_rank=DEFAULT_RETRIEVAL_DEPTH + 1,
                    ),
                )
        union = list(union_by_chunk.values())
        if latency_breakdown is not None:
            latency_breakdown["lexical_dense_search_ms"] += (
                time.perf_counter() - searched
            ) * 1000
        reranked = time.perf_counter()
        self.record_cuda_memory_diagnostic(
            "after_retrieval_before_reranker",
            diagnostics_hook,
            details={
                "query_count": len(queries),
                "retrieval_union_count": len(union),
                "reranker_pair_count": len(union),
            },
        )
        pairs = [
            (
                normalized,
                self._artifacts.chunks_by_id[row["chunk_id"]][
                    "retrieval_text"
                ],
            )
            for row in union
        ]
        scores = self._score_pairs(pairs)
        self.record_cuda_memory_diagnostic(
            "after_retrieval_reranker",
            diagnostics_hook,
            details={"reranker_pair_count": len(pairs)},
        )
        ranked = sorted(
            (
                {
                    **row,
                    "reranker_score": round(float(score), 8),
                }
                for row, score in zip(union, scores, strict=True)
            ),
            key=lambda row: (
                -float(row["reranker_score"]),
                int(row.get("rank") or 0),
                str(row["chunk_id"]),
            ),
        )
        if latency_breakdown is not None:
            latency_breakdown["candidate_rerank_ms"] += (
                time.perf_counter() - reranked
            ) * 1000
        if self.use_identity_shortlist:
            from src.v3.product_candidate_identity import reserve_then_fill

            reserved = []
            for document in shortlisted_documents:
                parent_id = str(document["document_id"])
                candidates = [
                    row
                    for row in ranked
                    if str(row["parent_document_id"]) == parent_id
                ]
                if candidates:
                    reserved.append([candidates[0]])
            return reserve_then_fill(reserved, ranked)
        return select_parent_diverse_candidates(ranked)

    def _answer_metadata(
        self,
        question: str,
        *,
        started: float,
        requested_as_of: str | None = None,
    ) -> dict[str, Any] | None:
        from src.v3.metadata_query import (
            DEFAULT_RUNTIME_SNAPSHOT,
            load_metadata_freshness_snapshot,
            plan_metadata_query,
            render_metadata_query_result,
            resolve_metadata_freshness,
        )

        requested_as_of = requested_as_of or date.today().isoformat()
        date.fromisoformat(requested_as_of)
        plan = plan_metadata_query(
            question,
            as_of=requested_as_of,
        )
        if plan is None:
            return None
        freshness = None
        if plan.mode == "metadata":
            if self._metadata_snapshot is None:
                self._metadata_snapshot = load_metadata_freshness_snapshot(
                    root=self.root,
                    snapshot_path=DEFAULT_RUNTIME_SNAPSHOT,
                )
            freshness = resolve_metadata_freshness(
                source_id=plan.source_id,
                requested_as_of=requested_as_of,
                snapshot=self._metadata_snapshot,
            )
            if freshness.effective_as_of is not None:
                plan = replace(
                    plan,
                    as_of=freshness.effective_as_of,
                )
            if self._metadata_documents is None:
                document_artifact = next(
                    row
                    for row in self._metadata_snapshot["artifacts"]
                    if row.get("role") == "documents"
                )
                self._metadata_documents = read_jsonl(
                    self.root / str(document_artifact["path"])
                )
        legacy = render_metadata_query_result(
            question=question,
            plan=plan,
            documents=self._metadata_documents or [],
            started=started,
            freshness=freshness,
        )
        mode = {
            "full_answer": "answer",
            "partial": "partial",
            "clarification": "clarification",
            "abstain": "unsupported",
        }[legacy["response_mode"]]
        requirements = legacy.get("requirements") or []
        citations = [
            citation
            for requirement in requirements
            for citation in requirement.get("citations", [])
        ]
        evidence_refs = list(
            dict.fromkeys(
                str(citation["evidence_ref"])
                for citation in citations
            )
        )
        rendered_answer = str(legacy.get("rendered_answer") or "")
        claims = (
            [
                {
                    "text": rendered_answer,
                    "evidence_refs": evidence_refs,
                    "citations": citations,
                }
            ]
            if mode in {"answer", "partial"} and rendered_answer
            else []
        )
        latency = dict(legacy.get("latency") or {})
        latency.setdefault(
            "total_ms",
            round((time.perf_counter() - started) * 1000, 3),
        )
        return {
            "product_free_rag_version": PRODUCT_FREE_RAG_VERSION,
            "question": question,
            "mode": mode,
            "model_mode": None,
            "claims": claims,
            "rejected_claims": [],
            "clarification": (
                rendered_answer if mode == "clarification" else ""
            ),
            "rendered_answer": rendered_answer,
            "candidates": legacy.get("candidates") or [],
            "generation": None,
            "verification": {
                **legacy.get("verification", {}),
                "query_mode": "metadata",
                "qwen_called": False,
            },
            "latency": latency,
            "latency_ms": float(latency["total_ms"]),
        }

    def answer(
        self,
        question: str,
        *,
        requirement_queries: list[str] | None = None,
        requested_subjects: list[str] | None = None,
        metadata_as_of: str | None = None,
        required_parent_document_id: str | None = None,
        diagnostics_hook: Callable[[dict[str, Any]], None] | None = None,
        use_question_coverage_contract: bool = False,
    ) -> dict[str, Any]:
        if (
            not self.use_requirement_fanout
            or use_question_coverage_contract
        ):
            return self._answer_single(
                question,
                requirement_queries=requirement_queries,
                requested_subjects=requested_subjects,
                metadata_as_of=metadata_as_of,
                required_parent_document_id=required_parent_document_id,
                diagnostics_hook=diagnostics_hook,
                use_question_coverage_contract=use_question_coverage_contract,
            )

        normalized = normalize_product_question(question)
        if not normalized:
            raise RuntimeError("question must not be empty")
        from src.v3.metadata_query import plan_metadata_query

        if plan_metadata_query(
            normalized,
            as_of=metadata_as_of or date.today().isoformat(),
        ) is not None:
            return self._answer_single(
                question,
                requirement_queries=requirement_queries,
                requested_subjects=requested_subjects,
                metadata_as_of=metadata_as_of,
                required_parent_document_id=required_parent_document_id,
                diagnostics_hook=diagnostics_hook,
                use_question_coverage_contract=False,
            )
        resolved_queries = _runtime_requirement_queries(
            normalized,
            requirement_queries,
        )
        if len(resolved_queries) < 2:
            return self._answer_single(
                question,
                requirement_queries=requirement_queries,
                requested_subjects=requested_subjects,
                metadata_as_of=metadata_as_of,
                required_parent_document_id=required_parent_document_id,
                diagnostics_hook=diagnostics_hook,
                use_question_coverage_contract=False,
            )

        started = time.perf_counter()
        child_results = [
            self._answer_single(
                query,
                requirement_queries=[query],
                requested_subjects=None,
                metadata_as_of=metadata_as_of,
                required_parent_document_id=required_parent_document_id,
                diagnostics_hook=diagnostics_hook,
                use_question_coverage_contract=False,
            )
            for query in resolved_queries
        ]
        return _merge_requirement_fanout_results(
            question=normalized,
            requirement_queries=resolved_queries,
            child_results=child_results,
            total_ms=(time.perf_counter() - started) * 1000,
        )

    def _answer_single(
        self,
        question: str,
        *,
        requirement_queries: list[str] | None = None,
        requested_subjects: list[str] | None = None,
        metadata_as_of: str | None = None,
        required_parent_document_id: str | None = None,
        diagnostics_hook: Callable[[dict[str, Any]], None] | None = None,
        use_question_coverage_contract: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        latency_breakdown = {
            "initialization_ms": 0.0,
            "model_reload_ms": 0.0,
            "question_normalize_ms": 0.0,
            "query_embedding_ms": 0.0,
            "lexical_dense_search_ms": 0.0,
            "candidate_rerank_ms": 0.0,
            "evidence_atomic_rerank_ms": 0.0,
            "model_handoff_ms": 0.0,
            "generation_ms": 0.0,
            "verification_render_ms": 0.0,
            "observability_ms": 0.0,
        }
        normalized = normalize_product_question(question)
        if not normalized:
            raise RuntimeError("question must not be empty")
        metadata_result = self._answer_metadata(
            normalized,
            started=started,
            requested_as_of=metadata_as_of,
        )
        if metadata_result is not None:
            latency_breakdown["question_normalize_ms"] = (
                time.perf_counter() - started
            ) * 1000
            total_ms = float(metadata_result["latency"]["total_ms"])
            latency_breakdown["unattributed_ms"] = max(
                0.0,
                total_ms - sum(latency_breakdown.values()),
            )
            metadata_result["latency"].update(
                {
                    key: round(value, 3)
                    for key, value in latency_breakdown.items()
                }
            )
            metadata_result.setdefault("evidence_pack", [])
            metadata_result.setdefault("raw_model_output", None)
            profile = {
                "query_mode": "metadata",
                "question_coverage_contract": False,
            }
            metadata_result["experimental_profile"] = profile
            metadata_result["runtime_fingerprint"] = (
                self._runtime_fingerprint(profile)
            )
            self.record_cuda_memory_diagnostic(
                "after_question",
                diagnostics_hook,
            )
            return metadata_result
        resolved_requirement_queries = _runtime_requirement_queries(
            normalized,
            requirement_queries,
        )
        effective_requirement_queries = resolved_requirement_queries or None
        atomic_reserve_per_query = _atomic_reserve_for_requirement_queries(
            resolved_requirement_queries
        )
        effective_subjects = (
            requested_subjects
            or explicit_nominative_question_subjects(normalized)
        )
        latency_breakdown["question_normalize_ms"] = (
            time.perf_counter() - started
        ) * 1000
        initialized = time.perf_counter()
        self._initialize()
        latency_breakdown["initialization_ms"] += (
            time.perf_counter() - initialized
        ) * 1000
        reloaded = time.perf_counter()
        self._ensure_retrieval_models_on_device()
        latency_breakdown["model_reload_ms"] += (
            time.perf_counter() - reloaded
        ) * 1000
        diagnostic_started = time.perf_counter()
        self.record_cuda_memory_diagnostic(
            "before_retrieval",
            diagnostics_hook,
        )
        latency_breakdown["observability_ms"] += (
            time.perf_counter() - diagnostic_started
        ) * 1000
        selected = self.retrieve(
            normalized,
            requirement_queries=effective_requirement_queries,
            default_as_of=metadata_as_of,
            diagnostics_hook=diagnostics_hook,
            latency_breakdown=latency_breakdown,
        )
        selected = select_required_parent_candidates(
            selected,
            required_parent_document_id=required_parent_document_id,
        )
        retrieval_ms = (time.perf_counter() - started) * 1000
        clarification = clarification_for_subject_only_question(
            normalized,
            requirement_queries=effective_requirement_queries,
            selected=selected,
            chunks_by_id=self._artifacts.chunks_by_id,
            documents_by_id=self._artifacts.documents_by_id,
        )
        if clarification is not None:
            total_ms = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
            latency_breakdown["unattributed_ms"] = max(
                0.0,
                total_ms - sum(latency_breakdown.values()),
            )
            result = {
                "product_free_rag_version": PRODUCT_FREE_RAG_VERSION,
                "question": normalized,
                "mode": "clarification",
                "model_mode": None,
                "claims": [],
                "rejected_claims": [],
                "clarification": clarification,
                "rendered_answer": clarification,
                "candidates": selected,
                "evidence_unit_count": 0,
                "evidence_pack": [],
                "raw_model_output": None,
                "generation": None,
                "verification": {
                    "all_exposed_citations_verified": True,
                    "qwen_called": False,
                    "reason": "subject_only_document_identity",
                },
                "latency": {
                    "retrieval_ms": round(retrieval_ms, 3),
                    **{
                        key: round(value, 3)
                        for key, value in latency_breakdown.items()
                    },
                    "total_ms": total_ms,
                },
                "latency_ms": total_ms,
            }
            profile = {
                "identity_shortlist": self.use_identity_shortlist,
                "compact_evidence_pack": self.use_compact_evidence_pack,
                "atomic_evidence_reranker": (
                    self.use_atomic_evidence_reranker
                ),
                "cuda_model_handoff": self.handoff_cuda_to_generation,
                "question_coverage_contract": (
                    use_question_coverage_contract
                ),
            }
            result["experimental_profile"] = profile
            result["runtime_fingerprint"] = self._runtime_fingerprint(
                profile
            )
            self.record_cuda_memory_diagnostic(
                "after_question",
                diagnostics_hook,
            )
            return result
        evidence_units_override = None
        evidence_candidate_chunk_count = len(selected)
        evidence_started = time.perf_counter()
        if self.use_compact_evidence_pack:
            candidate_chunk_ids = [
                str(row["chunk_id"]) for row in selected
            ]
            if self.use_identity_shortlist:
                chunks_by_parent: dict[str, list[dict[str, Any]]] = {}
                for chunk in self._artifacts.chunks_by_id.values():
                    chunks_by_parent.setdefault(
                        str(chunk["parent_document_id"]),
                        [],
                    ).append(chunk)
                candidate_chunk_ids = expand_evidence_candidate_chunk_ids(
                    normalized,
                    selected,
                    chunks_by_parent=chunks_by_parent,
                )
            evidence_candidate_chunk_count = len(candidate_chunk_ids)
            if self.use_atomic_evidence_reranker:
                evidence_units_override = (
                    build_atomic_reranked_product_evidence_pack(
                        candidate_chunk_ids,
                        question=normalized,
                        requirement_queries=effective_requirement_queries,
                        chunks_by_id=self._artifacts.chunks_by_id,
                        documents_by_id=self._artifacts.documents_by_id,
                        temporal_by_document=self.temporal_by_document,
                        score_pairs=self._score_pairs,
                        max_units=DEFAULT_EVIDENCE_UNITS,
                        prefilter_per_query=32,
                        reserve_per_query=atomic_reserve_per_query,
                    )
                )
            else:
                evidence_units_override = build_compact_product_evidence_pack(
                    candidate_chunk_ids,
                    question=normalized,
                    requirement_queries=effective_requirement_queries,
                    chunks_by_id=self._artifacts.chunks_by_id,
                    documents_by_id=self._artifacts.documents_by_id,
                    temporal_by_document=self.temporal_by_document,
                    max_units=DEFAULT_EVIDENCE_UNITS,
                )
        self.record_cuda_memory_diagnostic(
            "after_evidence_reranker",
            diagnostics_hook,
        )
        latency_breakdown["evidence_atomic_rerank_ms"] = (
            time.perf_counter() - evidence_started
        ) * 1000
        handoff_started = time.perf_counter()
        self.record_cuda_memory_diagnostic(
            "before_handoff",
            diagnostics_hook,
        )
        self._handoff_cuda_models_to_generation()
        self.record_cuda_memory_diagnostic(
            "after_handoff",
            diagnostics_hook,
        )
        latency_breakdown["model_handoff_ms"] = (
            time.perf_counter() - handoff_started
        ) * 1000
        answer_started = time.perf_counter()
        result = answer_product_rag_from_candidates(
            question=normalized,
            requirement_queries=effective_requirement_queries,
            requested_subjects=effective_subjects,
            selected=selected,
            chunks_by_id=self._artifacts.chunks_by_id,
            documents_by_id=self._artifacts.documents_by_id,
            temporal_by_document=self.temporal_by_document,
            model=self.model,
            timeout_seconds=self.timeout,
            evidence_units_override=evidence_units_override,
            use_question_coverage_contract=use_question_coverage_contract,
        )
        answer_stage_ms = (time.perf_counter() - answer_started) * 1000
        latency_breakdown["generation_ms"] = float(
            (result.get("generation") or {}).get("latency_ms", 0.0)
        )
        latency_breakdown["verification_render_ms"] = max(
            0.0,
            answer_stage_ms - latency_breakdown["generation_ms"],
        )
        diagnostic_started = time.perf_counter()
        self.record_cuda_memory_diagnostic(
            "after_question",
            diagnostics_hook,
        )
        latency_breakdown["observability_ms"] += (
            time.perf_counter() - diagnostic_started
        ) * 1000
        total_ms = (time.perf_counter() - started) * 1000
        measured_sum = sum(latency_breakdown.values())
        latency_breakdown["unattributed_ms"] = max(
            0.0,
            total_ms - measured_sum,
        )
        result["latency"] = {
            "retrieval_ms": round(retrieval_ms, 3),
            **{
                key: round(value, 3)
                for key, value in latency_breakdown.items()
            },
            "total_ms": round(total_ms, 3),
        }
        result["latency_ms"] = round(total_ms, 3)
        result["experimental_profile"] = {
            "identity_shortlist": self.use_identity_shortlist,
            "compact_evidence_pack": self.use_compact_evidence_pack,
            "atomic_evidence_reranker": self.use_atomic_evidence_reranker,
            "atomic_prefilter_per_query": (
                32 if self.use_atomic_evidence_reranker else None
            ),
            "atomic_reserve_per_query": (
                atomic_reserve_per_query
                if self.use_atomic_evidence_reranker
                else None
            ),
            "evidence_candidate_chunk_count": (
                evidence_candidate_chunk_count
            ),
            "cuda_model_handoff": self.handoff_cuda_to_generation,
            "question_coverage_contract": use_question_coverage_contract,
        }
        result["runtime_fingerprint"] = self._runtime_fingerprint(
            result["experimental_profile"]
        )
        return result
