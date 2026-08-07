from copy import deepcopy

from src.v3.requirement_entity_anchor import (
    anchor_requirement_subject,
    build_official_entity_index,
)


def _index():
    documents = [
        {
            "document_id": "guide-path",
            "source_id": "dnf_game_guide",
            "title": "광휘의 행로",
        },
        {
            "document_id": "guide-remnant",
            "source_id": "dnf_game_guide",
            "title": "광휘의 잔영",
        },
    ]
    chunks = [
        {
            "parent_document_id": "guide-path",
            "heading_path": ["광휘의 행로", "탐사 종류"],
        }
    ]
    return build_official_entity_index(documents, chunks)


def test_longest_exact_official_phrase_expands_truncated_subject():
    requirement = {
        "requirement_id": "r1",
        "subject": "광휘",
        "relation": "minimum_reputation",
    }

    anchored = anchor_requirement_subject(
        "광휘의 행로 탐사에 필요한 최소 명성은?", requirement, _index()
    )

    assert anchored["subject"] == "광휘의 행로"
    assert anchored["planner_subject"] == "광휘"
    assert anchored["entity_anchor"]["document_ids"] == ["guide-path"]


def test_question_exact_match_prevents_sibling_entity_collision():
    anchored = anchor_requirement_subject(
        "광휘의 행로 탐사 수를 알려줘.",
        {"requirement_id": "r1", "subject": "광휘"},
        _index(),
    )

    assert anchored["subject"] == "광휘의 행로"
    assert anchored["subject"] != "광휘의 잔영"


def test_exact_official_subject_receives_verified_anchor():
    requirement = {
        "requirement_id": "r1",
        "subject": "광휘의 행로",
        "relation": "minimum_reputation",
    }

    anchored = anchor_requirement_subject(
        "광휘의 행로 탐사에 필요한 최소 명성은?", requirement, _index()
    )

    assert anchored["subject"] == "광휘의 행로"
    assert anchored["planner_subject"] == "광휘의 행로"
    assert anchored["entity_anchor"]["phrase"] == "광휘의 행로"
    assert anchored["entity_anchor"]["match_type"] == "exact_official_phrase_in_question"


def test_subject_is_not_expanded_when_full_phrase_is_absent_from_question():
    requirement = {"requirement_id": "r1", "subject": "광휘"}

    anchored = anchor_requirement_subject("광휘 관련 재료는?", requirement, _index())

    assert anchored == requirement


def test_anchor_does_not_mutate_planner_requirement():
    requirement = {"requirement_id": "r1", "subject": "광휘"}
    before = deepcopy(requirement)

    anchor_requirement_subject("광휘의 행로는?", requirement, _index())

    assert requirement == before
