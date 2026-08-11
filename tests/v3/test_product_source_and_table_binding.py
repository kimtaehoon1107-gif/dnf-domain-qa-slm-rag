from src.v3.build_bm25 import SearchPolicy
from src.v3.product_candidate_identity import shortlist_identity_documents
from src.v3.product_evidence_pack import (
    build_compact_product_evidence_pack,
    select_semantic_product_evidence_units,
)
from src.v3.product_free_rag import (
    answer_product_rag_from_candidates,
    build_product_prompt,
    expand_evidence_candidate_chunk_ids,
)
from src.v3.product_minimal_verifier import verify_product_claim_output


def _identity_chunk(
    *,
    source_kind: str,
    status: str,
    default_exposure: bool,
    valid_from: str | None,
) -> dict:
    return {
        "chunk_id": f"{source_kind}-chunk",
        "parent_document_id": f"{source_kind}-document",
        "source_id": "dnf_update",
        "source_kind": source_kind,
        "status": status,
        "default_exposure": default_exposure,
        "review_required": False,
        "valid_from": valid_from,
        "valid_to": None,
        "heading_path": ["무너진 성자 미카엘라 레이드 보상"],
        "retrieval_text": "미카엘라 레이드 보상 종류",
    }


def test_identity_shortlist_applies_the_same_search_policy_as_retrieval():
    live = _identity_chunk(
        source_kind="game_guide",
        status="current",
        default_exposure=True,
        valid_from="2026-08-06",
    )
    preview = _identity_chunk(
        source_kind="preview_patch",
        status="unknown",
        default_exposure=False,
        valid_from=None,
    )
    documents = {
        "game_guide-document": {
            "document_id": "game_guide-document",
            "title": "무너진 성자 미카엘라",
            "published_at": "2026-08-06",
        },
        "preview_patch-document": {
            "document_id": "preview_patch-document",
            "title": "7/29 퍼스트 서버 미카엘라 업데이트",
            "published_at": "2026-07-29",
        },
    }
    chunks = {
        "game_guide-document": [live],
        "preview_patch-document": [preview],
    }

    current = shortlist_identity_documents(
        "미카엘라 레이드 보상 종류 알려줘",
        documents_by_id=documents,
        chunks_by_parent=chunks,
        policy=SearchPolicy(as_of="2026-08-11"),
        limit=4,
    )
    historical = shortlist_identity_documents(
        "2026년 7월 29일 퍼스트 서버 미카엘라 업데이트 알려줘",
        documents_by_id=documents,
        chunks_by_parent=chunks,
        policy=SearchPolicy(
            default_exposure_only=False,
            allowed_statuses=None,
            as_of="2026-07-29",
        ),
        limit=4,
    )

    assert [row["document_id"] for row in current] == [
        "game_guide-document"
    ]
    assert [row["document_id"] for row in historical] == [
        "preview_patch-document"
    ]


def test_raid_kind_question_does_not_reserve_an_equipment_kind_table():
    preview_text = (
        "## 신규 장비 종류\n"
        "[TABLE]\n"
        "| 장비 종류 | 설명 |\n"
        "| 축성 방어구 | 신규 장비 |\n"
        "[/TABLE]"
    )
    live_text = (
        "## 콘텐츠 정보\n"
        "[TABLE]\n"
        "| 구분 | 내용 |\n"
        "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |\n"
        "[/TABLE]"
    )
    chunks = {
        "preview": {
            "chunk_id": "preview",
            "parent_document_id": "preview-document",
            "display_text": preview_text,
            "heading_path": [
                "무너진 성자 미카엘라 레이드 보상",
                "신규 장비 종류",
            ],
            "status": "unknown",
        },
        "live": {
            "chunk_id": "live",
            "parent_document_id": "live-document",
            "display_text": live_text,
            "heading_path": ["무너진 성자 미카엘라", "콘텐츠 정보"],
            "status": "current",
        },
    }
    documents = {
        "preview-document": {
            "document_id": "preview-document",
            "source_id": "dnf_update",
            "title": "7/29 퍼스트 서버 업데이트 안내",
            "status": "unknown",
        },
        "live-document": {
            "document_id": "live-document",
            "source_id": "dnf_game_guide",
            "title": "무너진 성자 미카엘라",
            "status": "current",
        },
    }

    for question in (
        "미카엘라 레이드 종류 뭐뭐가 있어?",
        "미카엘라 레이드의 종류는 뭐뭐가 있어?",
    ):
        units = build_compact_product_evidence_pack(
            ["preview", "live"],
            question=question,
            chunks_by_id=chunks,
            documents_by_id=documents,
            temporal_by_document={},
        )

        assert not any(
            unit.get("complete")
            and "장비 종류" in str(unit.get("table_label") or "")
            for unit in units
        )
        assert any(
            "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |" in unit["text"]
            for unit in units
        )


def test_kind_table_requires_the_question_proper_noun_identity():
    shiroco_text = (
        "## 보상 종류\n"
        "[TABLE]\n"
        "| 구분 | 보상 |\n"
        "| 보스 처치 | 사념의 씨앗 |\n"
        "[/TABLE]"
    )
    michaela_text = (
        "## 콘텐츠 정보\n"
        "[TABLE]\n"
        "| 구분 | 내용 |\n"
        "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |\n"
        "[/TABLE]"
    )
    chunks = {
        "shiroco": {
            "chunk_id": "shiroco",
            "parent_document_id": "shiroco-document",
            "display_text": shiroco_text,
            "heading_path": ["무형의 시로코 레이드", "보상 종류"],
            "status": "current",
        },
        "michaela": {
            "chunk_id": "michaela",
            "parent_document_id": "michaela-document",
            "display_text": michaela_text,
            "heading_path": ["무너진 성자 미카엘라", "콘텐츠 정보"],
            "status": "current",
        },
    }
    documents = {
        "shiroco-document": {
            "document_id": "shiroco-document",
            "source_id": "dnf_game_guide",
            "title": "무형의 시로코 레이드",
            "status": "current",
        },
        "michaela-document": {
            "document_id": "michaela-document",
            "source_id": "dnf_game_guide",
            "title": "무너진 성자 미카엘라",
            "status": "current",
        },
    }

    units = build_compact_product_evidence_pack(
        ["shiroco", "michaela"],
        question="미카엘라 레이드 보상 종류 알려줘.",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert not any(
        unit.get("complete")
        and unit.get("title") == "무형의 시로코 레이드"
        for unit in units
    )


def test_raid_kind_reserves_a_difficulty_row_ahead_of_higher_scored_noise():
    units = [
        {
            "candidate_ref": "1",
            "chunk_id": "live",
            "parent_document_id": "michaela",
            "title": "무너진 성자 미카엘라",
            "context_text": "콘텐츠 정보 > 표 헤더: | 구분 | 내용 |",
            "start_char": 0,
            "end_char": 25,
            "text": "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |",
            "unit_kind": "table_row",
        },
        *[
            {
                "candidate_ref": str(index + 2),
                "chunk_id": f"noise-{index}",
                "parent_document_id": "michaela",
                "title": "무너진 성자 미카엘라",
                "context_text": "신규 장비 종류",
                "start_char": index * 10 + 30,
                "end_char": index * 10 + 39,
                "text": f"| 축성 장비 {index} | 설명 |",
                "unit_kind": "table_row",
                "complete_list": index == 0,
            }
            for index in range(9)
        ],
    ]

    def noise_first_scores(pairs):
        return [0.99 if "축성 장비" in text else 0.01 for _, text in pairs]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["미카엘라 레이드 종류 뭐뭐가 있어?"],
        question="미카엘라 레이드 종류 뭐뭐가 있어?",
        score_pairs=noise_first_scores,
        max_units=8,
        prefilter_per_query=4,
    )

    assert selected[0]["text"] == "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |"


def test_raid_kind_expansion_adds_the_difficulty_sibling_chunk():
    equipment = {
        "chunk_id": "equipment",
        "parent_document_id": "michaela",
        "retrieval_text": "미카엘라 레이드 신규 장비 종류 축성 방어구",
        "display_text": "## 신규 장비 종류\n축성 방어구",
        "review_required": False,
    }
    difficulty = {
        "chunk_id": "difficulty",
        "parent_document_id": "michaela",
        "retrieval_text": (
            "무너진 성자 미카엘라 콘텐츠 정보 난이도 "
            "싱글 매칭 일반 하드"
        ),
        "display_text": (
            "## 콘텐츠 정보\n[TABLE]\n"
            "| 구분 | 내용 |\n"
            "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |\n"
            "[/TABLE]"
        ),
        "review_required": False,
    }
    distractors = [
        {
            "chunk_id": f"equipment-{index}",
            "parent_document_id": "michaela",
            "retrieval_text": (
                f"미카엘라 레이드 종류 신규 장비 종류 {index}"
            ),
            "display_text": f"## 신규 장비 종류\n축성 방어구 {index}",
            "review_required": False,
        }
        for index in range(4)
    ]

    expanded = expand_evidence_candidate_chunk_ids(
        "미카엘라 레이드 종류 뭐뭐가 있어?",
        [
            {
                "chunk_id": "equipment",
                "parent_document_id": "michaela",
            }
        ],
        chunks_by_parent={"michaela": [equipment, difficulty, *distractors]},
    )

    assert expanded == ["equipment", "difficulty"]


def _material_units() -> tuple[list[dict], dict[str, dict]]:
    corrupted = (
        "| 축성 디레지에 잠식 세트/고유 에픽 방어구 | "
        "에픽 소울: 1개 | 여명의 빛망울: 240개 | "
        "골드: 1,000,000골드 | 순례의 인장: 200개 |"
    )
    normal = (
        "| 축성 세트/고유 에픽 방어구 | "
        "에픽 소울: 4개 | 여명의 빛망울: 360개 | "
        "골드: 2,500,000골드 | 순례의 인장: 500개 |"
    )
    source = f"{corrupted}\n{normal}"
    context = "축성 방어구 업그레이드 > 표 헤더: | 장비 | 소모 재료 |"
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "materials",
            "parent_document_id": "guide",
            "title": "무너진 성자 미카엘라",
            "context_text": context,
            "start_char": 0,
            "end_char": len(corrupted),
            "text": corrupted,
            "unit_kind": "table_row",
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "1",
            "chunk_id": "materials",
            "parent_document_id": "guide",
            "title": "무너진 성자 미카엘라",
            "context_text": context,
            "start_char": len(corrupted) + 1,
            "end_char": len(source),
            "text": normal,
            "unit_kind": "table_row",
        },
    ]
    return units, {"materials": {"display_text": source}}


def test_sibling_quantity_rows_require_a_distinguishing_row_subject():
    units, chunks = _material_units()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": (
                    "축성 방어구 업그레이드 재료는 에픽 소울 1개, "
                    "여명의 빛망울 240개, 1,000,000골드 또는 "
                    "순례의 인장 200개입니다."
                ),
                "evidence_refs": ["E1"],
            },
            {
                "text": (
                    "축성 방어구 업그레이드 재료는 에픽 소울 4개, "
                    "여명의 빛망울 360개, 2,500,000골드 또는 "
                    "순례의 인장 500개입니다."
                ),
                "evidence_refs": ["E2"],
            },
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="축성 방어구 업그레이드 재료 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert [claim["evidence_refs"] for claim in verified["claims"]] == [["E2"]]
    assert verified["rejected_claims"][0]["evidence_refs"] == ["E1"]
    assert "table_row_subject_mismatch" in verified["rejected_claims"][0][
        "reasons"
    ]
    assert verified["mode"] == "partial"


def test_table_row_prompt_requires_the_first_cell_subject():
    units, _ = _material_units()

    prompt = build_product_prompt(
        question="축성 방어구 업그레이드 재료 알려줘.",
        evidence_units=units,
    )

    assert "표 행 근거를 사용할 때 각 claim에 첫 번째 셀의 항목명을" in prompt


def test_single_target_vertical_table_does_not_treat_relation_as_subject():
    subject = "[7월]스페셜 클론 레어 아바타 풀세트 상자"
    context = (
        "[7월 이달의 아이템] > 표 헤더: | 구분 | 이달의 아이템 | "
        f"> 표 대상: | 아이템명 | {subject} |"
    )
    price = "| 상점판매가격 | 4,000만 골드 |"
    trade = "| 거래타입 | 교환가능 |"
    source = f"{price}\n{trade}"
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "monthly-item",
            "parent_document_id": "july-item",
            "title": "7월 이달의 아이템",
            "context_text": context,
            "start_char": 0,
            "end_char": len(price),
            "text": price,
            "unit_kind": "table_row",
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "1",
            "chunk_id": "monthly-item",
            "parent_document_id": "july-item",
            "title": "7월 이달의 아이템",
            "context_text": context,
            "start_char": len(price) + 1,
            "end_char": len(source),
            "text": trade,
            "unit_kind": "table_row",
        },
    ]
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": f"{subject}의 상점판매가격은 4,000만 골드입니다.",
                "evidence_refs": ["E1"],
            },
            {
                "text": f"{subject}의 거래타입은 교환가능입니다.",
                "evidence_refs": ["E2"],
            },
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question=(
            "7월 스페셜 클론 레어 아바타 풀세트 상자의 "
            "상점판매가와 거래 타입은?"
        ),
        evidence_units=units,
        chunks_by_id={"monthly-item": {"display_text": source}},
    )

    assert [claim["evidence_refs"] for claim in verified["claims"]] == [
        ["E1"],
        ["E2"],
    ]
    assert verified["rejected_claims"] == []


def test_complete_category_row_can_verify_a_low_score_kind_answer():
    evidence = "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |"
    unit = {
        "evidence_ref": "E1",
        "candidate_ref": "1",
        "chunk_id": "difficulty",
        "parent_document_id": "michaela",
        "title": "무너진 성자 미카엘라",
        "context_text": "콘텐츠 정보 > 표 헤더: | 구분 | 내용 |",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "unit_kind": "table_row",
        "complete_category": True,
        "question_relevance_score": 0.01,
    }
    correct = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "미카엘라 레이드 난이도는 싱글, 매칭, 일반, "
                        "하드입니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드 종류 뭐뭐가 있어?",
        evidence_units=[unit],
        chunks_by_id={"difficulty": {"display_text": evidence}},
    )
    incomplete = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "미카엘라 레이드 난이도는 일반, 하드입니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드 종류 뭐뭐가 있어?",
        evidence_units=[unit],
        chunks_by_id={"difficulty": {"display_text": evidence}},
    )

    assert correct["mode"] == "answer"
    assert len(correct["claims"]) == 1
    assert incomplete["claims"] == []
    assert "content_kind_values_incomplete" in incomplete[
        "rejected_claims"
    ][0]["reasons"]


def test_complete_category_answer_prunes_other_parent_kind_guesses():
    difficulty = "| 난이도 | 싱글 | 매칭 | 일반 | 하드 |"
    system = "계율의 사슬"
    evidence_units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "difficulty",
            "parent_document_id": "live-guide",
            "title": "무너진 성자 미카엘라",
            "context_text": "콘텐츠 정보 > 표 헤더: | 구분 | 내용 |",
            "start_char": 0,
            "end_char": len(difficulty),
            "text": difficulty,
            "unit_kind": "table_row",
            "complete_category": True,
            "question_relevance_score": 0.01,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "system",
            "parent_document_id": "preview-guide",
            "title": "미리 만나는 무너진 성자 미카엘라",
            "context_text": "레이드의 핵심 시스템",
            "start_char": 0,
            "end_char": len(system),
            "text": system,
            "unit_kind": "sentence",
        },
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        del prompt, timeout_seconds
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": (
                            "미카엘라 레이드 난이도는 싱글, 매칭, "
                            "일반, 하드입니다."
                        ),
                        "evidence_refs": ["E1"],
                    },
                    {
                        "text": "미카엘라 레이드 종류는 계율의 사슬입니다.",
                        "evidence_refs": ["E2"],
                    },
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {},
        }

    result = answer_product_rag_from_candidates(
        question="미카엘라 레이드 종류 뭐뭐가 있어?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": "difficulty",
                "parent_document_id": "live-guide",
            },
            {
                "chunk_id": "system",
                "parent_document_id": "preview-guide",
            },
        ],
        chunks_by_id={
            "difficulty": {"display_text": difficulty},
            "system": {"display_text": system},
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=evidence_units,
    )

    assert result["mode"] == "answer"
    assert [claim["evidence_refs"] for claim in result["claims"]] == [["E1"]]
    assert "outside_complete_category" in result["rejected_claims"][-1][
        "reasons"
    ]
    assert result["clarification_options"] == []
