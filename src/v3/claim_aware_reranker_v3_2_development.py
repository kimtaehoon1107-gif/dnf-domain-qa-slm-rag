from __future__ import annotations

import re
from typing import Any

from src.v3.claim_aware_reranker import rerank_evidence as rerank_v3_1


CLAIM_RERANKER_VERSION = "dnf-v3-claim-aware-reranker-v3.2.0-development-only"
CONTACT_DEADLINE_PATTERN = re.compile(
    r"(?:\d[\d,]*\s*일\s*(?:내|이내).{0,30}문의|"
    r"문의.{0,30}\d[\d,]*\s*일\s*(?:내|이내))"
)


def rerank_evidence(
    question: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Preserve the superseded 57/59 contact-deadline experiment.

    This module is development-only and is not imported by the canonical
    evaluator. It exists so the v3.2 experiment is not erased when v3.1 is
    restored as the reproducible 56/59 baseline.
    """
    ranked = rerank_v3_1(question, candidates)
    deadline_question = "문의" in question and any(
        marker in question for marker in ("며칠", "이내", "안에", "기한")
    )
    output = []
    for row in ranked:
        direct = bool(
            deadline_question
            and CONTACT_DEADLINE_PATTERN.search(row["preferred_quote"])
        )
        output.append(
            {
                **row,
                "claim_reranker_version": CLAIM_RERANKER_VERSION,
                "development_only": True,
                "contact_deadline_direct": direct,
            }
        )
    output.sort(
        key=lambda row: (
            -int(row["contact_deadline_direct"]),
            row["rerank_rank"],
            row["chunk_id"],
        )
    )
    return [
        {**row, "rerank_rank": rank}
        for rank, row in enumerate(output, start=1)
    ]
