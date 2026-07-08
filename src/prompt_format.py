from __future__ import annotations

from typing import Any


DEFAULT_RAG_INSTRUCTION = (
    "제공된 공식 문서 근거만 사용해 질문에 답하라. "
    "근거가 질문에 직접 답하면 answerability를 true로 두고 해당 chunk_id를 인용하라. "
    "근거가 일부만 답하면 answerability를 partial로 두고 확인 가능한 범위만 답하라. "
    "근거가 부족하거나 질문과 무관하면 answerability를 false로 두고 citations는 비워라. "
    "false 답변에서는 공식 문서만으로는 확인할 수 없다고 답하고, 무관한 chunk_id를 인용하지 마라. "
    "답변은 answerability, citations, answer 필드를 이 순서로 줄 단위로 포함하라. "
    "citations에는 실제 사용한 chunk_id만 적고, answer는 1~2문장과 200자 이내로 간결하게 작성하라."
)


def trim_text(text: Any, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def format_documents(documents: list[dict[str, Any]], max_doc_chars: int) -> str:
    blocks = []
    for doc in documents:
        doc_id = doc.get("doc_id", "")
        title = doc.get("title", "")
        text = trim_text(doc.get("text", ""), max_doc_chars)
        # Neutral tag: gold/distractor roles must not leak into the prompt. At
        # inference every document is simply "retrieved", so training uses the
        # same tag to keep the prompt identical across train and inference.
        blocks.append(f"[retrieved] {doc_id} | {title}\n{text}")
    return "\n\n".join(blocks)


def format_prompt(question: str, documents: list[dict[str, Any]], max_doc_chars: int, instruction: str | None = None) -> str:
    evidence = format_documents(documents, max_doc_chars=max_doc_chars)
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
