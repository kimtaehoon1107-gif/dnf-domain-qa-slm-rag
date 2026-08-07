from __future__ import annotations

import re
from typing import Any

from src.v3.answer_target_router import _base_tag, _is_nominal_tag, _kiwi


SUBJECT_ANCHORED_RETRIEVAL_VERSION = "simple-subject-anchored-retrieval-v1"
COORDINATOR_FORMS = frozenset({"과", "와", "랑"})
SUBJECT_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


def _trim_question_tail(text: str) -> str:
    tokens = list(_kiwi().tokenize(text))
    nominal_seen = False
    for token in tokens:
        tag = _base_tag(token)
        nominal_seen = nominal_seen or _is_nominal_tag(tag)
        if nominal_seen and tag in {"JKO", "JX", "JKS"}:
            return text[: int(token.start)].strip()
    return text.strip().rstrip("?？. ")


def _official_anchor(
    question: str,
    subject: str,
    entity_index: dict[str, dict[str, Any]],
) -> str | None:
    candidates = [
        phrase
        for phrase in entity_index
        if phrase in question and subject.startswith(phrase)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda phrase: (-len(phrase), phrase))[0]


def extract_subject_anchored_queries(
    question: str,
    entity_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Extract a high-confidence possessive subject and one to three query surfaces."""

    normalized = " ".join(str(question or "").split())
    possessive = normalized.find("의")
    if possessive <= 0:
        return None
    subject = normalized[:possessive].strip()
    if not subject or len(subject) > 40:
        return None
    official_anchor = _official_anchor(normalized, subject, entity_index)
    if official_anchor is None:
        return None

    body = _trim_question_tail(normalized[possessive + 1 :])
    if not body:
        return None
    coordinator_spans = []
    for token in _kiwi().tokenize(body):
        tag = _base_tag(token)
        if tag == "JC" or (
            tag == "JKB" and str(token.form) in COORDINATOR_FORMS
        ):
            coordinator_spans.append(
                (int(token.start), int(token.start) + int(token.len))
            )
    separated = body
    for start, end in reversed(coordinator_spans):
        separated = separated[:start] + "," + separated[end:]
    surfaces = [
        value.strip(" ,")
        for value in separated.split(",")
        if value.strip(" ,")
    ]
    if not 1 <= len(surfaces) <= 3 or any(len(value) > 80 for value in surfaces):
        return None
    return {
        "version": SUBJECT_ANCHORED_RETRIEVAL_VERSION,
        "subject": subject,
        "official_anchor": official_anchor,
        "surfaces": surfaces,
        "queries": [f"{subject} {surface}" for surface in surfaces],
    }


def build_planner_relation_queries(
    subject: str,
    requirements: list[dict[str, Any]],
) -> list[str]:
    """Preserve reviewed planner relations instead of shortening them to surfaces."""

    queries = []
    for requirement in requirements:
        relation = " ".join(
            str(requirement.get("relation") or "").replace("_", " ").split()
        )
        if not relation:
            raise RuntimeError("planner relation must not be empty")
        queries.append(
            relation if relation.startswith(subject) else f"{subject} {relation}"
        )
    return queries


def candidate_supports_subject(
    subject: str,
    *,
    chunk: dict[str, Any],
    document: dict[str, Any],
) -> bool:
    """Require the subject in title/heading/body, with density for one-token subjects."""

    tokens = SUBJECT_TOKEN.findall(subject)
    if not tokens:
        return False
    title = str(document.get("title") or "")
    headings = " ".join(chunk.get("heading_path") or [])
    context = f"{title}\n{headings}\n{chunk['retrieval_text']}"
    counts = [context.count(token) for token in tokens]
    if not all(counts):
        return False
    if len(tokens) > 1:
        return True
    token = tokens[0]
    return counts[0] >= 2 or token in title or token in headings


def subject_supported_hits(
    subject: str,
    hits: list[dict[str, Any]],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for hit in hits:
        chunk = chunks_by_id[hit["chunk_id"]]
        document = documents_by_id[chunk["parent_document_id"]]
        if candidate_supports_subject(
            subject,
            chunk=chunk,
            document=document,
        ):
            output.append(hit)
    return output


def reciprocal_rank_fuse(
    ranked_groups: list[list[dict[str, Any]]],
    *,
    rank_constant: int = 10,
) -> list[dict[str, Any]]:
    if rank_constant < 1:
        raise RuntimeError("rank_constant must be positive")
    scores: dict[str, float] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}
    best_rank: dict[str, int] = {}
    for group in ranked_groups:
        for rank, row in enumerate(group, 1):
            chunk_id = row["chunk_id"]
            rows_by_id.setdefault(chunk_id, row)
            best_rank[chunk_id] = min(best_rank.get(chunk_id, rank), rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (
                rank_constant + rank
            )
    return [
        {
            **rows_by_id[chunk_id],
            "query_fusion_score": round(scores[chunk_id], 8),
        }
        for chunk_id in sorted(
            rows_by_id,
            key=lambda value: (
                -scores[value],
                best_rank[value],
                value,
            ),
        )
    ]


def merge_subject_anchored_candidates(
    baseline: list[dict[str, Any]],
    anchored_groups: list[list[dict[str, Any]]],
    *,
    subject: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    maximum: int = 8,
) -> list[dict[str, Any]]:
    if maximum < len(baseline):
        raise RuntimeError("maximum must preserve every baseline candidate")
    matched = subject_supported_hits(
        subject,
        baseline,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
    )
    matched_ids = {row["chunk_id"] for row in matched}
    mismatched = [row for row in baseline if row["chunk_id"] not in matched_ids]
    ordered = [*matched]
    seen = {row["chunk_id"] for row in ordered}
    for group in anchored_groups:
        first = next((row for row in group if row["chunk_id"] not in seen), None)
        if first is not None:
            ordered.append(first)
            seen.add(first["chunk_id"])
    for row in mismatched:
        if row["chunk_id"] not in seen:
            ordered.append(row)
            seen.add(row["chunk_id"])
    return ordered[:maximum]


def enforce_subject_citation_support(
    result: dict[str, Any],
    *,
    subject: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Fail closed when a supported requirement cites a different subject."""

    requirements = []
    audits_by_index = {
        int(row["requirement_index"]): dict(row)
        for row in result.get("verification", {}).get("requirements", [])
    }
    for row in result.get("requirements", []):
        checked = {
            **row,
            "citations": [dict(citation) for citation in row.get("citations", [])],
        }
        if checked.get("status") == "supported_exact":
            mismatched = []
            for citation in checked["citations"]:
                chunk = chunks_by_id[citation["chunk_id"]]
                document = documents_by_id[chunk["parent_document_id"]]
                if not candidate_supports_subject(
                    subject,
                    chunk=chunk,
                    document=document,
                ):
                    mismatched.append(citation["chunk_id"])
            if mismatched:
                checked["status"] = "unsupported"
                checked["answer"] = ""
                checked["citations"] = []
                index = int(checked["requirement_index"])
                audit = audits_by_index.setdefault(
                    index,
                    {
                        "requirement_index": index,
                        "model_status": "supported",
                        "failure_reasons": [],
                    },
                )
                audit["exposed_status"] = "unsupported"
                audit.setdefault("failure_reasons", []).append(
                    "citation_subject_mismatch"
                )
                audit["subject_mismatched_chunk_ids"] = mismatched
        requirements.append(checked)

    supported_count = sum(
        row.get("status") == "supported_exact" for row in requirements
    )
    if supported_count == 0:
        response_mode = "abstain"
    elif supported_count == len(requirements):
        response_mode = "full_answer"
    else:
        response_mode = "partial_answer"
    rendered_answer = "\n".join(
        f"- {row['answer']} "
        + " ".join(
            f"[{citation['chunk_id']}]"
            for citation in row.get("citations", [])
        )
        for row in requirements
        if row.get("status") == "supported_exact"
    )
    return {
        **result,
        "response_mode": response_mode,
        "requirements": requirements,
        "rendered_answer": rendered_answer,
        "verification": {
            **result.get("verification", {}),
            "requirements": [
                audits_by_index[index] for index in sorted(audits_by_index)
            ],
            "subject_citation_check": True,
        },
    }
