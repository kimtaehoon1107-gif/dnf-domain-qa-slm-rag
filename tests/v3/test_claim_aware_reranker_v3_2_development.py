from __future__ import annotations

import unittest

from src.v3.claim_aware_reranker_v3_2_development import rerank_evidence


def _candidate(rank: int, chunk_id: str, text: str) -> dict[str, object]:
    return {
        "selected_rank": rank,
        "retrieval_rank": rank,
        "chunk_id": chunk_id,
        "parent_document_id": f"doc_{chunk_id}",
        "source_id": "dnf_faq",
        "source_kind": "faq",
        "status": "current",
        "default_exposure": True,
        "review_required": False,
        "display_text": text,
    }


class DevelopmentOnlyContactDeadlineTest(unittest.TestCase):
    def test_direct_deadline_experiment_is_preserved_but_separate(self) -> None:
        ranked = rerank_evidence(
            "청약철회는 구입 후 며칠 안에 문의해야 하고 언제 불가능해?",
            [
                _candidate(
                    1,
                    "separate",
                    "문의 접수 후 검토합니다. 구입일로부터 7일이 지나면 철회가 불가합니다.",
                ),
                _candidate(
                    2,
                    "direct",
                    "구입일로부터 7일 내 문의해야 하며 사용한 상품은 철회가 불가합니다.",
                ),
            ],
        )

        self.assertEqual(ranked[0]["chunk_id"], "direct")
        self.assertTrue(ranked[0]["development_only"])


if __name__ == "__main__":
    unittest.main()
