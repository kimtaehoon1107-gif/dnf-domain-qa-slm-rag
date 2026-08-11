from src.v3.product_reward_kind import (
    build_reward_kind_reservation,
    build_server_reward_kind_output,
)
from src.v3.product_free_rag import answer_product_rag_from_candidates


def _fixtures(*, close_second_table: bool = True):
    first = (
        "## 레이드 클리어 보상\n"
        "레이드 클리어 시 확정적으로 다음의 아이템을 획득할 수 있습니다.\n"
        "[TABLE]\n"
        "| 아이템 명 | 싱글 | 일반 | 교환 타입 |\n"
        "| 빛의 전도 | O | O | 교환불가 |\n"
        "| 빛의 전도 | 서약 업그레이드에 사용합니다. |\n"
        "[/TABLE]\n"
        "레이드 클리어 시 정해진 확률에 따라 다음의 아이템을 획득할 수 있습니다.\n"
        "[TABLE]\n"
        "| 아이템 명 | 싱글 | 일반 | 교환 타입 |\n"
        "| 에픽 장비 | O | O | 교환불가 |\n"
    )
    second = (
        "| 아이템 명 | 싱글 | 일반 | 교환 타입 |\n"
        "| 태초 장비 | O | O | 교환불가 |\n"
        + ("[/TABLE]\n" if close_second_table else "")
    )
    chunks = {
        "reward-1": {
            "chunk_id": "reward-1",
            "parent_document_id": "raid-guide",
            "chunk_index": 1,
            "start_offset": 0,
            "display_text": first,
            "heading_path": ["레이드 보상", "레이드 클리어 보상"],
            "default_exposure": True,
            "status": "current",
        },
        "reward-2": {
            "chunk_id": "reward-2",
            "parent_document_id": "raid-guide",
            "chunk_index": 2,
            "start_offset": len(first) - 40,
            "display_text": second,
            "heading_path": ["레이드 보상", "레이드 클리어 보상"],
            "default_exposure": True,
            "status": "current",
        },
    }
    documents = {
        "raid-guide": {
            "document_id": "raid-guide",
            "source_id": "dnf_game_guide",
            "title": "테스트 레이드",
            "status": "current",
        }
    }
    return chunks, documents


def test_reward_kind_reservation_collects_complete_cross_chunk_tables():
    chunks, documents = _fixtures()

    units = build_reward_kind_reservation(
        "테스트 레이드 보상 종류 알려줘",
        parent_ids=["raid-guide"],
        chunks_by_parent={"raid-guide": list(chunks.values())},
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert [unit["evidence_ref"] for unit in units] == ["E1", "E2"]
    assert all(unit["reward_kind_complete"] for unit in units)
    assert units[0]["reward_kind_groups"] == {
        "확정 보상": ["빛의 전도"],
        "확률 보상": ["에픽 장비"],
    }
    assert units[1]["reward_kind_groups"] == {
        "확률 보상": ["태초 장비"]
    }
    for unit in units:
        source = chunks[unit["chunk_id"]]["display_text"]
        assert source[unit["start_char"] : unit["end_char"]] == unit["text"]


def test_reward_kind_reservation_accepts_natural_enumeration_wording():
    chunks, documents = _fixtures()

    for question in (
        "테스트 레이드 보상 뭐뭐 있어?",
        "테스트 레이드 보상 뭐뭐있어?",
        "테스트 레이드에는 어떤 보상이 있어?",
    ):
        units = build_reward_kind_reservation(
            question,
            parent_ids=["raid-guide"],
            chunks_by_parent={"raid-guide": list(chunks.values())},
            documents_by_id=documents,
            temporal_by_document={},
        )

        assert [unit["evidence_ref"] for unit in units] == ["E1", "E2"]
        assert build_server_reward_kind_output(question, units) is not None


def test_reward_kind_reservation_requires_a_complete_reward_table():
    chunks, documents = _fixtures(close_second_table=False)

    units = build_reward_kind_reservation(
        "테스트 레이드 보상 종류 알려줘",
        parent_ids=["raid-guide"],
        chunks_by_parent={"raid-guide": list(chunks.values())},
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert units == []


def test_reward_kind_reservation_does_not_capture_a_single_reward_fact():
    chunks, documents = _fixtures()

    units = build_reward_kind_reservation(
        "테스트 레이드의 빛의 전도 획득 여부 알려줘",
        parent_ids=["raid-guide"],
        chunks_by_parent={"raid-guide": list(chunks.values())},
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert units == []


def test_server_reward_kind_output_groups_and_deduplicates_items():
    chunks, documents = _fixtures()
    units = build_reward_kind_reservation(
        "테스트 레이드 보상 종류 알려줘",
        parent_ids=["raid-guide"],
        chunks_by_parent={"raid-guide": list(chunks.values())},
        documents_by_id=documents,
        temporal_by_document={},
    )

    output = build_server_reward_kind_output(
        "테스트 레이드 보상 종류 알려줘",
        units,
    )

    assert output == {
        "mode": "answer",
        "claims": [
            {
                "text": "확정 보상 종류는 빛의 전도입니다.",
                "evidence_refs": ["E1"],
            },
            {
                "text": "확률 보상 종류는 에픽 장비, 태초 장비입니다.",
                "evidence_refs": ["E1", "E2"],
            },
        ],
        "clarification": "",
    }


def test_reward_kind_server_path_skips_qwen_and_restores_exact_citations():
    chunks, documents = _fixtures()
    question = "테스트 레이드 보상 뭐뭐있어?"
    units = build_reward_kind_reservation(
        question,
        parent_ids=["raid-guide"],
        chunks_by_parent={"raid-guide": list(chunks.values())},
        documents_by_id=documents,
        temporal_by_document={},
    )

    def fail_generator(**_kwargs):
        raise AssertionError("Qwen must not be called")

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=[question],
        requested_subjects=None,
        selected=[
            {
                "chunk_id": unit["chunk_id"],
                "parent_document_id": "raid-guide",
                "source_id": "dnf_game_guide",
                "title": "테스트 레이드",
                "status": "current",
                "reranker_score": 1.0,
            }
            for unit in units
        ],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        model="unused",
        timeout_seconds=1,
        generator=fail_generator,
        evidence_units_override=units,
        use_server_reward_kind_rendering=True,
    )

    assert result["mode"] == "answer"
    assert result["generation"] is None
    assert result["server_rendering"] == {
        "used": True,
        "renderer": "reward_kind_v1",
        "claim_count": 2,
    }
    assert result["rejected_claims"] == []
    assert result["verification"]["all_exposed_citations_verified"] is True
    assert all(claim["citations"] for claim in result["claims"])
