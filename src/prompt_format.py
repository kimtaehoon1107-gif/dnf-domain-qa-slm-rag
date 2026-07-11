from __future__ import annotations

import re
from typing import Any


LEGACY_RAG_INSTRUCTION = (
    "제공된 공식 문서 근거만 사용해 질문에 답하라. "
    "근거가 질문에 직접 답하면 answerability를 true로 두고 해당 chunk_id를 인용하라. "
    "근거가 일부만 답하면 answerability를 partial로 두고 확인 가능한 범위만 답하라. "
    "근거가 부족하거나 질문과 무관하면 answerability를 false로 두고 citations는 비워라. "
    "false 답변에서는 공식 문서만으로는 확인할 수 없다고 답하고, 무관한 chunk_id를 인용하지 마라. "
    "답변은 answerability, citations, answer 필드를 이 순서로 줄 단위로 포함하라. "
    "citations에는 실제 사용한 chunk_id만 적고, answer는 1~2문장과 200자 이내로 간결하게 작성하라."
)
REQUEST_MIX_RAG_INSTRUCTION = (
    "제공된 공식 문서 근거만 사용해 질문에 답하라. "
    "근거가 질문에 직접 답하면 answerability를 true로 두고 해당 chunk_id를 인용하라. "
    "근거가 질문의 사실 일부만 뒷받침하거나, 질문이 문서로 확인 가능한 사실과 개인 판단·선택·계정별 결정을 함께 요구하면 "
    "answerability를 partial로 두고 확인 가능한 사실만 답하며 개인 결정은 대신하지 마라. "
    "근거가 부족하거나 질문과 무관하면 answerability를 false로 두고 citations는 비워라. "
    "false 답변에서는 공식 문서만으로는 확인할 수 없다고 답하고, 무관한 chunk_id를 인용하지 마라. "
    "답변은 answerability, citations, answer 필드를 이 순서로 줄 단위로 포함하라. "
    "citations에는 실제 사용한 chunk_id만 적고, answer는 1~2문장과 200자 이내로 간결하게 작성하라."
)
RAG_INSTRUCTIONS = {
    "legacy": LEGACY_RAG_INSTRUCTION,
    "request_mix": REQUEST_MIX_RAG_INSTRUCTION,
}
DEFAULT_RAG_INSTRUCTION = LEGACY_RAG_INSTRUCTION


def instruction_for_mode(mode: str) -> str:
    try:
        return RAG_INSTRUCTIONS[mode]
    except KeyError as exc:
        raise ValueError(f"Unknown instruction mode: {mode}") from exc
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
DEFAULT_WINDOW_OVERLAP_RATIO = 0.5
QUERY_STOPWORDS = {
    "공식",
    "문서",
    "문서가",
    "문서에서",
    "관련",
    "내용",
    "내용은",
    "핵심",
    "뭐야",
    "대해",
    "알려줘",
    "설명",
    "설명한",
    "어떻게",
}
KOREAN_SUFFIXES = ("에서는", "에서", "으로", "에게", "한테", "까지", "부터", "처럼", "보다", "관련", "사항은", "사항", "에는", "하는", "되는", "으로", "돼", "해", "할", "한", "된", "은", "는", "이", "가", "을", "를", "에", "도", "만", "와", "과", "로")


def normalize_space(text: Any) -> str:
    return " ".join(str(text or "").split())


def query_terms(question: str) -> set[str]:
    terms = set()
    for raw_token in TOKEN_PATTERN.findall(question):
        token = raw_token.lower()
        if token in QUERY_STOPWORDS:
            continue
        normalized = token
        for suffix in KOREAN_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
                normalized = normalized[: -len(suffix)]
                break
        if normalized not in QUERY_STOPWORDS and (len(normalized) >= 2 or normalized.isdigit()):
            terms.add(normalized)
    return terms


def window_score(question: str, window: str) -> tuple[int, int]:
    lowered = window.lower()
    matched = [term for term in query_terms(question) if term in lowered]
    return sum(len(term) * len(term) for term in matched), len(matched)


def select_query_window(text: Any, question: str, max_chars: int, title: str = "") -> str:
    normalized = normalize_space(text)
    if max_chars <= 0:
        return ""
    if len(normalized) <= max_chars:
        return normalized

    stride = max(1, int(max_chars * (1.0 - DEFAULT_WINDOW_OVERLAP_RATIO)))
    starts = list(range(0, max(1, len(normalized) - max_chars + 1), stride))
    final_start = max(0, len(normalized) - max_chars)
    if not starts or starts[-1] != final_start:
        starts.append(final_start)

    windows = [(start, normalized[start : start + max_chars]) for start in starts]
    title_lower = normalize_space(title).lower()
    terms = {term for term in query_terms(question) if term not in title_lower}
    if not terms:
        terms = query_terms(question)
    term_document_frequency = {
        term: sum(term in window.lower() for _, window in windows)
        for term in terms
    }
    scored = []
    for start, window in windows:
        lowered = window.lower()
        matched = [term for term in terms if term in lowered]
        score = sum(
            len(term) * len(term) * (len(windows) - term_document_frequency[term] + 1)
            for term in matched
        )
        matches = len(matched)
        scored.append((score, matches, -start, start, window))
    _, _, _, start, selected = max(scored)
    prefix = "..." if start > 0 else ""
    suffix = "..." if start + max_chars < len(normalized) else ""
    return f"{prefix}{selected.strip()}{suffix}"


def evidence_span_visible(
    question: str,
    documents: list[dict[str, Any]],
    evidence_span: Any,
    max_doc_chars: int,
) -> bool:
    span = normalize_space(evidence_span)
    if not span:
        return False
    return any(
        span
        in normalize_space(
            select_query_window(
                doc.get("text", ""),
                question=question,
                max_chars=max_doc_chars,
                title=str(doc.get("title", "")),
            )
        )
        for doc in documents
    )


def trim_text(text: Any, max_chars: int) -> str:
    return select_query_window(text, question="", max_chars=max_chars)


def format_documents(documents: list[dict[str, Any]], max_doc_chars: int, question: str = "") -> str:
    blocks = []
    for doc in documents:
        doc_id = doc.get("doc_id", "")
        title = doc.get("title", "")
        text = select_query_window(
            doc.get("text", ""),
            question=question,
            max_chars=max_doc_chars,
            title=str(title),
        )
        # Neutral tag: gold/distractor roles must not leak into the prompt. At
        # inference every document is simply "retrieved", so training uses the
        # same tag to keep the prompt identical across train and inference.
        blocks.append(f"[retrieved] {doc_id} | {title}\n{text}")
    return "\n\n".join(blocks)


def format_prompt(question: str, documents: list[dict[str, Any]], max_doc_chars: int, instruction: str | None = None) -> str:
    evidence = format_documents(documents, max_doc_chars=max_doc_chars, question=question)
    return (
        "### Instruction\n"
        f"{instruction or DEFAULT_RAG_INSTRUCTION}\n\n"
        "### Question\n"
        f"{question}\n\n"
        "### Evidence\n"
        f"{evidence}\n\n"
        "### Answer\n"
    )


def format_completion(row: dict[str, Any]) -> str:
    answerability = row.get("answerability", "")
    citations = ", ".join(str(item) for item in row.get("citations", []))
    return (
        f"answerability: {answerability}\n"
        f"citations: {citations}\n"
        f"answer: {row['answer']}"
    )


def format_prompt_and_completion(row: dict[str, Any], max_doc_chars: int) -> tuple[str, str]:
    prompt = format_prompt(
        question=row["question"],
        documents=row["documents"],
        max_doc_chars=max_doc_chars,
        instruction=row.get("instruction") or DEFAULT_RAG_INSTRUCTION,
    )
    return prompt, format_completion(row)


def format_training_text(row: dict[str, Any], max_doc_chars: int) -> str:
    prompt, completion = format_prompt_and_completion(row, max_doc_chars=max_doc_chars)
    return prompt + completion
