from __future__ import annotations

from src.v3.document_title_binding import (
    bind_parent_ids_by_title_mention,
    build_title_token_idf,
)


def _documents() -> dict[str, dict[str, str]]:
    documents = {
        "diregie-guide": {"title": "검은 질병의 디레지에 레이드"},
        "diregie-event": {"title": "디레지에 업데이트 기념 이벤트"},
        "nabel-guide": {"title": "만들어진 신 나벨"},
        "arad-pass": {"title": "아라드 패스 2026 시즌3"},
    }
    documents.update(
        {
            f"update-{index}": {"title": f"{index}월 업데이트 안내"}
            for index in range(1, 20)
        }
    )
    return documents


def test_rare_subject_mention_keeps_matching_parents() -> None:
    documents = _documents()
    selected, audit = bind_parent_ids_by_title_mention(
        "디레지에 하드 입장 명성은?",
        parent_ids=("arad-pass", "diregie-guide", "diregie-event"),
        documents_by_id=documents,
        title_token_idf=build_title_token_idf(documents),
        minimum_idf=2.0,
    )

    assert selected == ("diregie-guide", "diregie-event")
    assert audit["applied"] is True
    assert {
        token
        for row in audit["selected"]
        for token in row["matched_tokens"]
    } == {"디레지에"}


def test_common_title_term_does_not_bind() -> None:
    documents = _documents()
    parent_ids = ("update-1", "update-2", "arad-pass")

    selected, audit = bind_parent_ids_by_title_mention(
        "업데이트 내용 알려줘",
        parent_ids=parent_ids,
        documents_by_id=documents,
        title_token_idf=build_title_token_idf(documents),
        minimum_idf=3.0,
    )

    assert selected == parent_ids
    assert audit["applied"] is False
    assert audit["reason"] == "no_distinctive_title_mention"


def test_no_title_mention_is_fail_neutral() -> None:
    documents = _documents()
    parent_ids = ("diregie-guide", "nabel-guide", "arad-pass")

    selected, audit = bind_parent_ids_by_title_mention(
        "강화 확률 알려줘",
        parent_ids=parent_ids,
        documents_by_id=documents,
        title_token_idf=build_title_token_idf(documents),
    )

    assert selected == parent_ids
    assert audit["applied"] is False


def test_particle_suffix_still_matches_title_subject() -> None:
    documents = _documents()

    selected, audit = bind_parent_ids_by_title_mention(
        "나벨은 입장 명성이 몇이야?",
        parent_ids=("arad-pass", "nabel-guide"),
        documents_by_id=documents,
        title_token_idf=build_title_token_idf(documents),
        minimum_idf=2.0,
    )

    assert selected == ("nabel-guide",)
    assert audit["applied"] is True
