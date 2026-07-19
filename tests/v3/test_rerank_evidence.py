from __future__ import annotations

import inspect
import unittest

from src.v3.claim_aware_reranker import rerank_evidence


def _candidate(rank: int, chunk_id: str, text: str) -> dict[str, object]:
    return {
        "selected_rank": rank,
        "retrieval_rank": rank,
        "chunk_id": chunk_id,
        "parent_document_id": f"doc_{chunk_id}",
        "source_id": "dnf_seria_shop",
        "source_kind": "shop_product",
        "status": "current",
        "default_exposure": True,
        "review_required": False,
        "display_text": text,
    }


class EvidenceRerankerRuleTest(unittest.TestCase):
    def test_api_cannot_receive_gold_labels(self) -> None:
        parameters = inspect.signature(rerank_evidence).parameters
        self.assertNotIn("gold", parameters)
        self.assertNotIn("acceptable_chunk_ids", parameters)
        self.assertNotIn("evidence_span", parameters)

    def test_compound_shop_fields_beat_higher_ranked_wrong_item(self) -> None:
        candidates = [
            _candidate(
                1,
                "wrong",
                "스위트 폭스 건 | 31 골드 코인 | 교환불가 | 무제한",
            ),
            _candidate(
                2,
                "answer",
                "골드 코인 10개 | 1,500 세라 | 교환가능",
            ),
        ]
        reranked = rerank_evidence(
            "골드 코인 10개 가격과 거래 타입은?", candidates
        )

        self.assertEqual(reranked[0]["chunk_id"], "answer")
        self.assertIn("1,500 세라", reranked[0]["preferred_quote"])
        self.assertIn("교환가능", reranked[0]["preferred_quote"])

    def test_complete_policy_clause_beats_generic_penalty_table(self) -> None:
        candidates = [
            _candidate(
                1,
                "generic",
                "버그 이용으로 얻은 관련 비정상 재화는 모두 회수됩니다.",
            ),
            _candidate(
                3,
                "answer",
                "운영정책 위반으로 습득한 재화는 비정상 재화임을 인지했는지 "
                "여부와 무관하게 회수될 수 있습니다.",
            ),
        ]
        reranked = rerank_evidence(
            "운영정책 위반으로 얻은 재화는 비정상 재화인지 몰랐어도 회수될 수 있어?",
            candidates,
        )

        self.assertEqual(reranked[0]["chunk_id"], "answer")
        self.assertIn("인지했는지", reranked[0]["preferred_quote"])

    def test_preferred_quote_is_exact_and_output_is_deterministic(self) -> None:
        candidates = [
            _candidate(1, "image_only", "상점 설치 버튼 클릭 [IMAGE_ALT] 화면"),
            _candidate(
                2,
                "complete",
                "전문직업(J) → 상점 설치 클릭 → 수수료 입력 → 원하는 위치를 "
                "선택하면 마법부여 상점이 설치됩니다.",
            ),
        ]
        first = rerank_evidence("마법부여 상점 설치 방법과 위치는?", candidates)
        second = rerank_evidence("마법부여 상점 설치 방법과 위치는?", candidates)

        self.assertEqual(first, second)
        self.assertEqual(first[0]["chunk_id"], "complete")
        self.assertIn(first[0]["preferred_quote"], candidates[1]["display_text"])
        self.assertEqual([row["rerank_rank"] for row in first], [1, 2])

    def test_only_large_high_confidence_bge_gain_overrides_original_rank(self) -> None:
        candidates = [
            {**_candidate(1, "baseline", "외부 거래 사기 주의 요약"), "reranker_score": 0.45},
            {
                **_candidate(
                    3,
                    "strong",
                    "외부 메신저 거래를 유도해 아이템과 현금을 갈취하는 방식입니다.",
                ),
                "reranker_score": 0.90,
            },
        ]
        reranked = rerank_evidence("외부 메신저 거래 유도 사기 주의사항은?", candidates)
        self.assertEqual(reranked[0]["chunk_id"], "strong")
        self.assertEqual(reranked[0]["promotion_reason"], "strong_bge_relevance_gain")

        candidates[1]["reranker_score"] = 0.70
        reranked = rerank_evidence("외부 메신저 거래 유도 사기 주의사항은?", candidates)
        self.assertEqual(reranked[0]["chunk_id"], "baseline")

    def test_unauthorized_program_warning_prefers_consequence_over_count(self) -> None:
        candidates = [
            _candidate(
                1,
                "notice",
                "비인가 프로그램 사용 (471건)\n"
                "작업장과 계정도용 등이 포함된 수치입니다.\n"
                + "일반 단속 안내입니다.\n" * 8
                + "허용되지 않은 비인가 프로그램 이용 시 제재될 수 있습니다.",
            )
        ]
        reranked = rerank_evidence("비인가 프로그램 사용 주의사항은 뭐야?", candidates)

        self.assertIn("제재될 수 있습니다", reranked[0]["preferred_quote"])


if __name__ == "__main__":
    unittest.main()
