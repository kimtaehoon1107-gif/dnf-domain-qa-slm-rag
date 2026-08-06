import pytest

from src.v3.free_minimal_direct import choose_direct_entry_fame


def _choose(
    question: str,
    *,
    title: str,
    display_text: str,
):
    return choose_direct_entry_fame(
        question,
        selected_hits=[{"chunk_id": "chunk_1"}],
        chunks_by_id={
            "chunk_1": {
                "chunk_id": "chunk_1",
                "parent_document_id": "document_1",
                "heading_path": ["콘텐츠 입장"],
                "display_text": display_text,
            }
        },
        documents_by_id={
            "document_1": {
                "document_id": "document_1",
                "source_id": "dnf_game_guide",
                "title": title,
                "revision_id": "revision_1",
            }
        },
    )


@pytest.mark.parametrize(
    "question",
    [
        "최후의과업 입장명성 알려줘",
        "최후의과업 명성제한은?",
        "최후의과업 필요 명성은?",
        "최후의과업 입장컷은?",
        "최후의과업 명성컷 알려줘",
    ],
)
def test_direct_entry_fame_selects_final_task_aliases(
    question: str,
) -> None:
    selected = _choose(
        question,
        title="최후의 과업",
        display_text=(
            "최후의 과업 채널은 모험가 명성 108,921부터 "
            "입장이 가능합니다."
        ),
    )

    assert selected is not None
    assert selected["value"] == "108,921"
    assert selected["citation"]["text"] == (
        "최후의 과업 채널은 모험가 명성 108,921부터 "
        "입장이 가능합니다."
    )


def test_direct_entry_fame_selects_diregie_table_row() -> None:
    selected = _choose(
        "디레지에 입장명성 알려줘",
        title="디레지에 레이드",
        display_text="| 구분 | 정보 |\n| 입장 명성 | 63,257 |",
    )

    assert selected is not None
    assert selected["value"] == "63,257"
    assert selected["citation"]["text"] == "| 입장 명성 | 63,257 |"


def test_direct_entry_fame_rejects_wrong_parent_identity() -> None:
    selected = _choose(
        "디레지에 입장명성 알려줘",
        title="최후의 과업",
        display_text=(
            "최후의 과업 채널은 모험가 명성 108,921부터 "
            "입장이 가능합니다."
        ),
    )

    assert selected is None
