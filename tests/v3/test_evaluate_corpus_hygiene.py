from __future__ import annotations

from src.v3.evaluate_corpus_hygiene import candidate_recall, exact_span_metrics


def test_candidate_recall_uses_chunk_id_membership_only() -> None:
    gold = [
        {
            "dev_id": "q1",
            "evidence_groups": [
                {"group_id": "g1", "acceptable_chunk_ids": ["a", "b"]},
                {"group_id": "g2", "acceptable_chunk_ids": ["c"]},
            ],
        }
    ]
    candidates = [{"dev_id": "q1", "candidates": [{"chunk_id": "b"}, {"chunk_id": "x"}]}]
    result = candidate_recall(gold, [], candidates, [])
    assert result["combined"]["evidence_groups_candidate_present"]["successes"] == 1
    assert result["combined"]["evidence_groups_candidate_present"]["total"] == 2
    assert result["combined"]["all_groups_candidate_present_questions"]["successes"] == 0


def test_exact_span_metrics_rechecks_original_slice() -> None:
    cases = [
        {
            "case_id": "q1",
            "selected_chunks": {"c1": "가격은 100 세라입니다."},
        }
    ]
    assembled = [
        {
            "case_id": "q1",
            "decisions": [
                {
                    "spans": [
                        {
                            "chunk_id": "c1",
                            "start_char": 4,
                            "end_char": 10,
                            "text": "100 세라",
                        }
                    ]
                }
            ],
        }
    ]
    metrics = exact_span_metrics(cases, assembled)
    assert metrics == {"valid": 1, "invalid": 0, "total": 1, "rate": 1.0}
