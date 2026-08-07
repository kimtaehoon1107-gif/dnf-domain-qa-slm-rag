import pytest

from src.v3.llm_query_plan import (
    LlmQueryPlan,
    validate_llm_query_plan,
)


@pytest.mark.parametrize(
    "plan",
    [
        LlmQueryPlan(
            mode="metadata",
            collection="events",
            operation="list_all",
            active_only=True,
        ),
        LlmQueryPlan(
            mode="metadata",
            collection="updates",
            operation="latest",
            sort_field="published_at",
        ),
        LlmQueryPlan(
            mode="metadata_then_rag",
            collection="updates",
            operation="latest",
            sort_field="published_at",
            content_query="강화 관련 변경점",
        ),
        LlmQueryPlan(
            mode="semantic_rag",
            collection="guides",
        ),
        LlmQueryPlan(
            mode="clarification",
            collection="events",
            clarification="어떤 최신 기준인지 알려주세요.",
        ),
    ],
)
def test_valid_query_plans(plan: LlmQueryPlan) -> None:
    validate_llm_query_plan(plan)


@pytest.mark.parametrize(
    ("plan", "reason"),
    [
        (
            LlmQueryPlan(
                mode="metadata",
                collection="guides",
                operation="latest",
                sort_field="published_at",
            ),
            "metadata_collection_not_supported",
        ),
        (
            LlmQueryPlan(
                mode="metadata",
                collection="updates",
                operation="latest",
                sort_field="valid_from",
            ),
            "metadata_sort_field_not_allowed",
        ),
        (
            LlmQueryPlan(
                mode="metadata",
                collection="updates",
                operation="count",
                active_only=True,
            ),
            "active_only_requires_events",
        ),
        (
            LlmQueryPlan(
                mode="metadata_then_rag",
                collection="notices",
                operation="latest",
                sort_field="published_at",
            ),
            "metadata_then_rag_content_query_required",
        ),
        (
            LlmQueryPlan(
                mode="clarification",
                collection="events",
            ),
            "clarification_text_required",
        ),
    ],
)
def test_invalid_query_plans_fail_closed(
    plan: LlmQueryPlan,
    reason: str,
) -> None:
    with pytest.raises(RuntimeError, match=reason):
        validate_llm_query_plan(plan)
