from __future__ import annotations

from types import SimpleNamespace

from src.v3.simple_rag_rc1 import RC1_VERSION, SimpleRAGRC1


class FakeBase:
    def __init__(self, result: dict) -> None:
        self.result = result
        self._artifacts = SimpleNamespace(
            chunks_by_id={
                "chunk-1": {
                    "parent_document_id": "doc-1",
                    "display_text": (
                        "# [7월 이달의 아이템]\n"
                        "| 삭제일자 | 2026년 8월 13일 |"
                    ),
                }
            },
            documents_by_id={
                "doc-1": {
                    "document_id": "doc-1",
                    "source_id": "dnf_monthly_item",
                    "title": "7월 이달의 아이템",
                    "published_at": "2026-07-01",
                    "status": "expired",
                }
            },
        )

    def answer(self, question: str) -> dict:
        return self.result


def _baseline_result() -> dict:
    return {
        "simple_rag_version": "dnf-simple-domain-rag-v2",
        "question": "[2월]스페셜 상자는 언제 삭제됐어?",
        "response_mode": "full_answer",
        "requirements": [
            {
                "requirement_index": 1,
                "question_part": "삭제일",
                "status": "supported_exact",
                "answer": "2026년 8월 13일",
                "citations": [
                    {
                        "chunk_id": "chunk-1",
                        "parent_document_id": "doc-1",
                        "source_id": "dnf_monthly_item",
                        "text": "삭제일자 | 2026년 8월 13일",
                    }
                ],
            }
        ],
        "rendered_answer": "- 2026년 8월 13일 [chunk-1]",
        "verification": {
            "requirements": [
                {
                    "requirement_index": 1,
                    "model_status": "supported",
                    "exposed_status": "supported_exact",
                    "failure_reasons": [],
                }
            ]
        },
        "candidates": [
            {
                "candidate_ref": "1",
                "chunk_id": "chunk-1",
                "parent_document_id": "doc-1",
                "source_id": "dnf_monthly_item",
                "reranker_score": 1.0,
            }
        ],
        "generation": {"model": "qwen3-8b:ctx8192"},
        "latency_ms": 1000.0,
    }


def test_rc1_blocks_explicit_sibling_month_and_reports_reason(tmp_path) -> None:
    runtime = SimpleRAGRC1(
        root=tmp_path,
        base=FakeBase(_baseline_result()),
    )

    result = runtime.answer("[2월]스페셜 상자는 언제 삭제됐어?")

    assert result["rc1_version"] == RC1_VERSION
    assert result["response_mode"] == "abstain"
    assert result["requirements"][0]["answer"] == ""
    assert result["rc1"]["guard_failures"] == [
        {
            "requirement_index": 1,
            "failure_reasons": [
                "explicit_subject_period_identity_mismatch"
            ],
            "guard_details": {
                "explicit_subject_period_identity_mismatch": {
                    "year": None,
                    "month": 2,
                }
            },
        }
    ]
    assert result["candidates"][0]["title"] == "7월 이달의 아이템"
    assert result["rc1"]["non_promoted_features"]["typed_evidence_ref"] is False


def test_rc1_keeps_safe_abstention_without_initialized_artifacts(tmp_path) -> None:
    base = FakeBase(
        {
            "response_mode": "abstain",
            "requirements": [],
            "rendered_answer": "",
            "verification": {},
        }
    )
    base._artifacts = None
    runtime = SimpleRAGRC1(root=tmp_path, base=base)

    result = runtime.answer("근거 없는 질문")

    assert result["response_mode"] == "abstain"
    assert result["rc1"]["guard_failures"] == []
