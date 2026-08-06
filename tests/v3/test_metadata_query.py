import json
from pathlib import Path

import pytest

from src.v3.metadata_query import (
    DEFAULT_RUNTIME_SNAPSHOT,
    MetadataFreshness,
    execute_metadata_query,
    load_metadata_freshness_snapshot,
    plan_event_metadata_query,
    plan_metadata_query,
    render_metadata_query_result,
    resolve_metadata_freshness,
)


def _document(
    document_id: str,
    title: str,
    *,
    valid_from: str,
    valid_to: str,
    source_id: str = "dnf_event",
    default_exposure: bool = True,
) -> dict:
    return {
        "document_id": document_id,
        "source_id": source_id,
        "title": title,
        "published_at": valid_from,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "current",
        "default_exposure": default_exposure,
        "review_required": False,
        "canonical_url": f"https://example.test/{document_id}",
    }


def test_active_event_list_filters_dates_and_other_sources() -> None:
    plan = plan_event_metadata_query(
        "지금 진행 중 이벤트 알려줘",
        as_of="2026-07-30",
    )

    assert plan is not None
    assert plan.operation == "list_all"
    rows = execute_metadata_query(
        plan,
        documents=[
            _document("active", "진행 이벤트", valid_from="2026-07-16", valid_to="2026-08-06"),
            _document("expired", "종료 이벤트", valid_from="2026-06-01", valid_to="2026-07-29"),
            _document("future", "예정 이벤트", valid_from="2026-08-01", valid_to="2026-08-30"),
            _document(
                "notice",
                "공지",
                source_id="dnf_notice",
                valid_from="2026-07-16",
                valid_to="2026-08-06",
            ),
        ],
    )

    assert [row["document_id"] for row in rows] == ["active"]


def test_active_event_count_uses_metadata_without_qwen() -> None:
    plan = plan_event_metadata_query(
        "현재 진행 중 이벤트 몇 개야?",
        as_of="2026-07-30",
    )
    assert plan is not None
    result = render_metadata_query_result(
        question="현재 진행 중 이벤트 몇 개야?",
        plan=plan,
        documents=[
            _document("a", "이벤트 A", valid_from="2026-07-01", valid_to="2026-08-01"),
            _document("b", "이벤트 B", valid_from="2026-07-02", valid_to="2026-08-02"),
        ],
        started=0.0,
    )

    assert result["requirements"][0]["value"] == 2
    assert result["verification"]["qwen_called"] is False


def test_latest_start_preserves_same_date_ties() -> None:
    plan = plan_event_metadata_query(
        "가장 최근 시작한 이벤트 알려줘",
        as_of="2026-07-30",
    )
    assert plan is not None
    rows = execute_metadata_query(
        plan,
        documents=[
            _document("a", "이벤트 A", valid_from="2026-07-16", valid_to="2026-08-01"),
            _document("b", "이벤트 B", valid_from="2026-07-16", valid_to="2026-08-02"),
            _document("old", "과거 이벤트", valid_from="2026-07-09", valid_to="2026-08-03"),
            _document("future", "예정 이벤트", valid_from="2026-08-01", valid_to="2026-08-31"),
        ],
    )

    assert {row["document_id"] for row in rows} == {"a", "b"}


def test_ambiguous_latest_requests_clarification() -> None:
    plan = plan_event_metadata_query(
        "제일 최신 이벤트 알려줘",
        as_of="2026-07-30",
    )

    assert plan is not None
    assert plan.mode == "clarification"
    assert "최근 등록" in str(plan.clarification)
    assert "최근 시작" in str(plan.clarification)


def test_event_content_question_stays_on_existing_rag() -> None:
    assert (
        plan_event_metadata_query(
            "최근 이벤트 보상은 뭐야?",
            as_of="2026-07-30",
        )
        is None
    )


@pytest.mark.parametrize(
    "question",
    [
        (
            "새해맞이 이벤트의 '이달의 행운아'와 "
            "'운명의 선택을 받은 자' 칭호 전체 표 두 개를 보여줘."
        ),
        "새해맞이 이벤트 전체 표 보여줘",
        "이벤트 보상 전체 알려줘",
        "공지의 점검 대상 전체 표를 보여줘",
    ],
)
def test_document_internal_complete_requests_stay_on_existing_rag(
    question: str,
) -> None:
    assert plan_metadata_query(question, as_of="2026-07-31") is None


@pytest.mark.parametrize(
    "question",
    [
        "현재 이벤트 전체 목록 알려줘",
        "전체 이벤트 알려줘",
        "이벤트 목록을 보여줘",
        "수집된 이벤트를 모두 알려줘",
    ],
)
def test_high_confidence_collection_list_commands_use_metadata(
    question: str,
) -> None:
    plan = plan_metadata_query(question, as_of="2026-07-31")

    assert plan is not None
    assert plan.mode == "metadata"
    assert plan.source_id == "dnf_event"
    assert plan.operation == "list_all"


def test_latest_update_uses_published_at() -> None:
    plan = plan_metadata_query(
        "제일 최신 업데이트 알려줘",
        as_of="2026-07-30",
    )

    assert plan is not None
    assert plan.source_id == "dnf_update"
    assert plan.operation == "latest"
    assert plan.sort_field == "published_at"


def test_latest_notice_phrase_uses_published_at() -> None:
    plan = plan_metadata_query(
        "가장 최근에 올라온 공지 알려줘",
        as_of="2026-07-30",
    )

    assert plan is not None
    assert plan.source_id == "dnf_notice"
    assert plan.operation == "latest"
    assert plan.sort_field == "published_at"


def test_latest_update_excludes_future_documents() -> None:
    plan = plan_metadata_query(
        "최신 업데이트 알려줘",
        as_of="2026-07-30",
    )
    assert plan is not None
    rows = execute_metadata_query(
        plan,
        documents=[
            _document(
                "current",
                "현재 업데이트",
                source_id="dnf_update",
                valid_from="2026-07-15",
                valid_to="",
            ),
            _document(
                "future",
                "미래 업데이트",
                source_id="dnf_update",
                valid_from="2026-08-01",
                valid_to="",
            ),
        ],
    )

    assert [row["document_id"] for row in rows] == ["current"]


def test_update_content_question_stays_on_existing_rag() -> None:
    assert (
        plan_metadata_query(
            "최신 업데이트에서 강화 내용 알려줘",
            as_of="2026-07-30",
        )
        is None
    )


def test_current_update_does_not_reuse_event_active_filter() -> None:
    assert (
        plan_metadata_query(
            "현재 업데이트 알려줘",
            as_of="2026-07-30",
        )
        is None
    )


def test_collected_update_count_is_unambiguous() -> None:
    plan = plan_metadata_query(
        "수집된 업데이트는 총 몇 개야?",
        as_of="2026-07-30",
    )

    assert plan is not None
    assert plan.source_id == "dnf_update"
    assert plan.operation == "count"
    assert plan.active_only is False


def test_freshness_bounds_current_request_to_verified_coverage() -> None:
    freshness = resolve_metadata_freshness(
        source_id="dnf_event",
        requested_as_of="2026-07-31",
        snapshot={
            "source_coverage": {
                "dnf_event": {
                    "coverage_as_of": "2026-07-17",
                    "status": "complete",
                }
            }
        },
    )

    assert freshness.status == "bounded_to_snapshot"
    assert freshness.requested_as_of == "2026-07-31"
    assert freshness.coverage_as_of == "2026-07-17"
    assert freshness.effective_as_of == "2026-07-17"


def test_freshness_preserves_historical_request_within_coverage() -> None:
    freshness = resolve_metadata_freshness(
        source_id="dnf_update",
        requested_as_of="2026-07-01",
        snapshot={
            "source_coverage": {
                "dnf_update": {
                    "coverage_as_of": "2026-07-17",
                    "status": "complete",
                }
            }
        },
    )

    assert freshness.status == "verified_to_requested"
    assert freshness.effective_as_of == "2026-07-01"


def test_freshness_missing_source_is_unavailable() -> None:
    freshness = resolve_metadata_freshness(
        source_id="dnf_update",
        requested_as_of="2026-07-31",
        snapshot={"source_coverage": {}},
    )

    assert freshness.status == "unavailable"
    assert freshness.effective_as_of is None


def test_bounded_metadata_result_is_partial_and_discloses_cutoff() -> None:
    plan = plan_event_metadata_query(
        "지금 진행 중 이벤트 알려줘",
        as_of="2026-07-17",
    )
    assert plan is not None
    result = render_metadata_query_result(
        question="지금 진행 중 이벤트 알려줘",
        plan=plan,
        documents=[
            _document(
                "active",
                "진행 이벤트",
                valid_from="2026-07-16",
                valid_to="2026-08-06",
            )
        ],
        started=0.0,
        freshness=MetadataFreshness(
            source_id="dnf_event",
            requested_as_of="2026-07-31",
            coverage_as_of="2026-07-17",
            effective_as_of="2026-07-17",
            source_status="complete",
            status="bounded_to_snapshot",
        ),
    )

    assert result["response_mode"] == "partial"
    assert "2026-07-17까지 수집·검증된" in result["rendered_answer"]
    assert "2026-07-31 현재 상태는 보장하지 않습니다" in result[
        "rendered_answer"
    ]
    assert result["verification"]["freshness_status"] == (
        "bounded_to_snapshot"
    )


def test_runtime_snapshot_is_tied_to_registry_coverage(
    tmp_path: Path,
) -> None:
    root = Path.cwd()
    snapshot = load_metadata_freshness_snapshot(
        root=root,
        snapshot_path=DEFAULT_RUNTIME_SNAPSHOT,
    )
    assert snapshot["source_coverage"]["dnf_event"][
        "coverage_as_of"
    ] == "2026-07-17"

    invalid = json.loads(json.dumps(snapshot))
    invalid["source_coverage"]["dnf_event"][
        "coverage_as_of"
    ] = "2026-07-18"
    invalid_path = tmp_path / "invalid_snapshot.json"
    invalid_path.write_text(
        json.dumps(invalid, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="Source coverage exceeds registry",
    ):
        load_metadata_freshness_snapshot(
            root=root,
            snapshot_path=invalid_path,
        )
