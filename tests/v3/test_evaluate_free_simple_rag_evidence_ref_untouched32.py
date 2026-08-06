from src.v3.evaluate_free_simple_rag_evidence_ref_untouched32 import (
    build_question_level_verified_output,
)


def test_question_level_adapter_reuses_answer_only_for_supported_requirements():
    sealed = {
        "requirements": [
            {
                "requirement_id": "price",
                "relation": "price",
                "expected_status": "supported",
            },
            {
                "requirement_id": "processing_time",
                "relation": "processing_time",
                "expected_status": "unsupported",
            },
        ]
    }
    citation = {
        "chunk_id": "chunk_1",
        "start_char": 0,
        "end_char": 10,
        "text": "가격은 100원",
    }
    result = {
        "question_time_scope": "current",
        "model_response_mode": "full_answer",
        "response_mode": "partial_answer",
        "rendered_answer": "- 가격은 100원입니다.",
        "requirements": [
            {
                "status": "supported_exact",
                "answer": "가격은 100원",
                "citations": [citation],
            }
        ],
    }

    adapted = build_question_level_verified_output(sealed, result)

    assert adapted["requirements"][0]["status"] == "supported_exact"
    assert adapted["requirements"][0]["answer"] == "가격은 100원"
    assert adapted["requirements"][0]["citations"] == [citation]
    assert adapted["requirements"][1]["status"] == "unsupported"
    assert adapted["requirements"][1]["answer"] == ""
    assert adapted["verification"][
        "unsupported_overclaim_requires_human_review"
    ]
