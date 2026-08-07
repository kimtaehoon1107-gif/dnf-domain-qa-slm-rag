from __future__ import annotations

from src.v3.evaluate_simple_domain_rag import summarize_cases


def _case(
    *,
    covered: bool,
    literal: bool,
    false_full: bool,
    table: bool = False,
    requirements: int = 1,
    response_mode: str = "full_answer",
) -> dict:
    return {
        "candidate_id": f"case-{covered}-{literal}-{false_full}-{table}",
        "is_table_source": table,
        "gold_requirement_count": requirements,
        "score": {
            "candidate_all_groups_covered": covered,
            "all_groups_hit": literal,
            "all_evidence_spans_hit": literal,
            "false_full": false_full,
            "requirement_count_match": True,
            "question_time_scope_match": True,
            "exact_citation_slices": True,
            "relevant_citation_count": int(literal),
            "citation_count": 1,
            "generation_error": None,
        },
        "result": {
            "response_mode": response_mode,
            "latency_ms": 10,
            "generation": {
                "usage": {"input_tokens": 100, "output_tokens": 10}
            },
        },
    }


def test_summarize_cases_reports_coverage_literal_and_false_full() -> None:
    summary = summarize_cases(
        [
            _case(covered=True, literal=True, false_full=False),
            _case(
                covered=True,
                literal=False,
                false_full=True,
                table=True,
                requirements=3,
            ),
            _case(
                covered=False,
                literal=False,
                false_full=False,
                response_mode="abstain",
            ),
        ]
    )

    assert summary["candidate_all_groups_covered"]["successes"] == 2
    assert summary["all_evidence_spans_hit"]["successes"] == 1
    assert summary["literal_when_candidate_covered"]["total"] == 2
    assert summary["false_full"]["successes"] == 1
    assert summary["segments"]["table_sources"]["cases"] == 1
    assert summary["response_modes"] == {"abstain": 1, "full_answer": 2}
    assert summary["input_tokens"] == 300
