import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.v3.product_evidence_pack import build_product_evidence_pack
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    build_compact_product_evidence_pack,
    explicit_question_clauses,
    explicit_nominative_question_subjects,
    explicit_question_subjects,
    kiwi_independent_requirement_queries,
    select_semantic_product_evidence_units,
    surface_requirement_queries,
)
from src.v3.diagnose_product_evidence_pack_top8_ab import (
    fill_question_only_pack,
)
from src.v3.diagnose_product_surface_retrieval_ab import (
    candidate_requirement_visibility,
)
from src.v3.diagnose_product_candidate_waterfall_missing32 import (
    classify_drop_stage,
)
from src.v3.diagnose_product_candidate_assembly_ab import (
    duplicate_aware_requirement_visibility,
)
from src.v3.product_candidate_identity import (
    explicit_temporal_interval,
    intervals_overlap,
    shortlist_identity_documents,
)
from src.v3.product_free_rag import (
    PRODUCT_SYSTEM_INSTRUCTIONS,
    ProductFreeRAG,
    answer_product_rag_from_candidates,
    build_product_coverage_lexical_overlap_diagnostic,
    build_product_prompt,
    build_product_question_requirements,
    clarification_for_subject_only_question,
    expand_evidence_candidate_chunk_ids,
    normalize_product_question,
    product_retrieval_query_variants,
    resolve_product_clarification_followup,
    rewrite_product_clarification_question,
    select_required_parent_candidates,
    search_policy_for_product_question,
    select_parent_diverse_candidates,
)
from src.v3.product_minimal_verifier import verify_product_claim_output
from src.v3.run_product_free_rag_existing32 import score_case


def test_product_retrieval_preinitialization_does_not_generate(monkeypatch):
    import src.v3.product_free_rag as product_module

    runtime = object.__new__(ProductFreeRAG)
    runtime._artifacts = None
    runtime._retrieval_models_offloaded = False
    runtime.device = "cuda"
    runtime._initialize = Mock()
    runtime._ensure_retrieval_models_on_device = Mock()
    kiwi = Mock(return_value=[])
    monkeypatch.setattr(
        product_module,
        "kiwi_independent_requirement_queries",
        kiwi,
    )

    result = runtime.preinitialize_retrieval()

    kiwi.assert_called_once_with("사전 초기화를 확인합니다.")
    runtime._initialize.assert_called_once_with()
    runtime._ensure_retrieval_models_on_device.assert_called_once_with()
    assert result["already_initialized"] is False
    assert result["qwen_called"] is False
    assert result["device"] == "cuda"


def _fixture():
    final_text = "최후의 과업 입장 명성은 108,921입니다."
    diregie_text = "디레지에 레이드 채널은 명성 63,257부터 입장 가능합니다."
    level_text = "최후의 과업 시나리오 입장 레벨은 115레벨 이상입니다."
    chunks = {
        "final": {"display_text": final_text},
        "diregie": {"display_text": diregie_text},
        "level": {"display_text": level_text},
    }
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "final",
            "title": "최후의 과업",
            "context_text": "콘텐츠 입장",
            "start_char": 0,
            "end_char": len(final_text),
            "text": final_text,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "chunk_id": "diregie",
            "title": "검은 질병의 디레지에 레이드",
            "context_text": "콘텐츠 입장",
            "start_char": 0,
            "end_char": len(diregie_text),
            "text": diregie_text,
            "complete": False,
        },
        {
            "evidence_ref": "E3",
            "chunk_id": "level",
            "title": "최후의 과업",
            "context_text": "시나리오 던전 정보",
            "start_char": 0,
            "end_char": len(level_text),
            "text": level_text,
            "complete": False,
        },
    ]
    return chunks, units


def test_product_prompt_treats_spacing_variants_and_evidence_as_candidates():
    assert "띄어쓰기가 생략되거나 달라도" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "답변 항목 목록이 아니라 후보 근거" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "하나의 claim으로 합치세요" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "한 속성만 묻는 질문에는 claim을 하나만" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "서로 다른 문서 맥락" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "question_focus" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "clarification" in PRODUCT_SYSTEM_INSTRUCTIONS
    assert "이벤트 기간이나 게시 날짜만으로 출시일을 추정하지 마세요" in (
        PRODUCT_SYSTEM_INSTRUCTIONS
    )


def test_semantic_evidence_selector_reserves_surface_queries_then_fills():
    texts = ["첫 조건 근거", "둘째 조건 근거", "전체 보충 1", "전체 보충 2"]
    units = [
        {
            "candidate_ref": str(index),
            "start_char": index,
            "title": "문서",
            "context_text": "",
            "text": value,
        }
        for index, value in enumerate(texts, 1)
    ]

    def score_pairs(pairs):
        scores = []
        for query, text in pairs:
            if query == "첫 조건":
                scores.append(10.0 if "첫 조건" in text else 0.0)
            elif query == "둘째 조건":
                scores.append(10.0 if "둘째 조건" in text else 0.0)
            else:
                scores.append(float(texts.index(text.split("근거: ")[-1])))
        return scores

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["첫 조건", "둘째 조건"],
        question="전체 질문",
        score_pairs=score_pairs,
        max_units=4,
    )

    assert [unit["text"] for unit in selected[:2]] == texts[:2]
    assert [unit["question_focus"] for unit in selected[:2]] == [
        "첫 조건",
        "둘째 조건",
    ]
    assert [unit["evidence_ref"] for unit in selected] == [
        "E1",
        "E2",
        "E3",
        "E4",
    ]


def test_semantic_evidence_selector_can_reserve_top_three_per_clause():
    texts = [
        "상자 및 구성품은 2026년 3월 26일 06시 일괄 삭제됩니다.",
        "풀세트 상자는 2026년 3월 26일 06시 일괄 삭제됩니다.",
        "2026년 1월 15일 점검 후부터 3월 26일 점검 전까지 판매됩니다.",
        "다른 상품 안내 1",
        "다른 상품 안내 2",
    ]
    units = [
        {
            "candidate_ref": str(index),
            "parent_document_id": (
                "target" if index <= 3 else f"decoy-{index}"
            ),
            "start_char": index,
            "title": "아바타 콤보 상자",
            "context_text": "판매 및 삭제 안내",
            "text": text,
        }
        for index, text in enumerate(texts, 1)
    ]
    sale_query = "아바타 콤보 상자는 언제 판매됐"
    deletion_query = "아바타 콤보 상자 언제 일괄 삭제됐어"

    def score_pairs(pairs):
        scores = []
        for query, reranker_text in pairs:
            if query == sale_query:
                if "상자 및 구성품" in reranker_text:
                    scores.append(0.99)
                elif "풀세트 상자" in reranker_text:
                    scores.append(0.98)
                elif "판매됩니다" in reranker_text:
                    scores.append(0.97)
                else:
                    scores.append(0.0)
            elif query == deletion_query:
                if "상자 및 구성품" in reranker_text:
                    scores.append(0.99)
                elif "풀세트 상자" in reranker_text:
                    scores.append(0.98)
                elif "판매됩니다" in reranker_text:
                    scores.append(0.10)
                else:
                    scores.append(0.0)
            elif "다른 상품 안내 1" in reranker_text:
                scores.append(0.90)
            elif "다른 상품 안내 2" in reranker_text:
                scores.append(0.80)
            else:
                scores.append(0.10)
        return scores

    baseline = select_semantic_product_evidence_units(
        units,
        selection_queries=[sale_query, deletion_query],
        question=f"{sale_query}고 {deletion_query}?",
        score_pairs=score_pairs,
        max_units=4,
    )
    expanded = select_semantic_product_evidence_units(
        units,
        selection_queries=[sale_query, deletion_query],
        question=f"{sale_query}고 {deletion_query}?",
        score_pairs=score_pairs,
        max_units=4,
        reserve_per_query=3,
    )

    assert not any("판매됩니다" in unit["text"] for unit in baseline)
    assert any("판매됩니다" in unit["text"] for unit in expanded)
    assert len(expanded) == 4


def test_semantic_evidence_selector_reserves_next_unseen_unit_for_colliding_query():
    units = [
        {
            "candidate_ref": str(index),
            "parent_document_id": parent,
            "start_char": index,
            "title": title,
            "context_text": "",
            "text": text,
        }
        for index, (parent, title, text) in enumerate(
            [
                ("event", "이벤트", "미카엘라 레이드 이벤트 기간"),
                (
                    "patch",
                    "업데이트",
                    "8월 6일 점검 중 미카엘라 레이드가 업데이트 됩니다.",
                ),
            ],
            1,
        )
    ]

    def score_pairs(pairs):
        scores = []
        for query, reranker_text in pairs:
            if query == "미카엘라 레이드 출시일":
                scores.append(1.0 if "이벤트 기간" in reranker_text else 0.8)
            elif query == "미카엘라 레이드 업데이트 날짜":
                scores.append(1.0 if "이벤트 기간" in reranker_text else 0.9)
            else:
                scores.append(0.0)
        return scores

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=[
            "미카엘라 레이드 출시일",
            "미카엘라 레이드 업데이트 날짜",
        ],
        question="미카엘라 레이드는 언제 출시했어?",
        score_pairs=score_pairs,
        max_units=2,
    )

    assert [unit["parent_document_id"] for unit in selected] == [
        "event",
        "patch",
    ]
    assert [unit["question_focus"] for unit in selected] == [
        "미카엘라 레이드 출시일",
        "미카엘라 레이드 업데이트 날짜",
    ]


def test_semantic_evidence_selector_prioritizes_direct_release_date_statement():
    units = [
        {
            "candidate_ref": "1",
            "parent_document_id": "event",
            "start_char": 1,
            "title": "미카엘라 이벤트",
            "context_text": "2026년 8월 6일 점검 후부터 8월 20일까지",
            "text": "미카엘라 레이드 하드 난이도 미션이 진행됩니다.",
        },
        {
            "candidate_ref": "2",
            "parent_document_id": "patch",
            "start_char": 2,
            "title": "미카엘라 업데이트",
            "context_text": "업데이트",
            "text": "8/6(목) 점검 중 업데이트 되는 내용 안내 드립니다.",
        },
    ]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["미카엘라 레이드 업데이트 날짜"],
        question="미카엘라 레이드는 언제 출시했어?",
        score_pairs=lambda pairs: [0.99, 0.10, 0.99, 0.10],
        max_units=2,
    )

    assert selected[0]["parent_document_id"] == "patch"
    assert selected[0]["question_focus"] == "미카엘라 레이드 업데이트 날짜"


def test_semantic_evidence_selector_reserves_near_top_complete_condition_list():
    units = [
        {
            "candidate_ref": "1",
            "parent_document_id": "policy",
            "start_char": 1,
            "title": "운영정책 (2020-12-04 시행)",
            "context_text": "운영정책",
            "text": "아래 사유면 길드장 권한이 위임될 수 있습니다.",
        },
        {
            "candidate_ref": "1",
            "parent_document_id": "policy",
            "start_char": 2,
            "title": "운영정책 (2020-12-04 시행)",
            "context_text": "운영정책",
            "text": "① 이용 제한 상태\n② 12개월 미접속 휴면 상태",
            "complete_list": True,
            "unit_kind": "numbered_list",
        },
    ]

    def score_pairs(pairs):
        return [
            0.99 if "아래 사유" in text else 0.97
            for _, text in pairs
        ]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["길드장 권한 위임 조건"],
        question="길드장 권한 위임 조건을 알려줘",
        score_pairs=score_pairs,
        max_units=2,
    )

    assert selected[0]["complete_list"] is True
    assert selected[0]["question_focus"] == "길드장 권한 위임 조건"


def test_semantic_evidence_selector_keeps_distinct_parent_contexts():
    units = [
        {
            "candidate_ref": str(index),
            "parent_document_id": parent,
            "start_char": index,
            "title": title,
            "context_text": "보상",
            "text": text,
        }
        for index, (parent, title, text) in enumerate(
            [
                ("contest", "디레지에 공모전", "공모전 보상 세라"),
                ("contest", "디레지에 공모전", "공모전 보상 안내"),
                ("event", "디레지에 레이드 추가 이벤트", "이벤트 보상 안내"),
                ("raid", "검은 질병의 디레지에 레이드", "레이드 보상 안내"),
            ],
            1,
        )
    ]

    def score_pairs(pairs):
        return [10.0 - index for index, _ in enumerate(pairs)]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["디레지에 보상"],
        question="디레지에 보상 알려줘",
        score_pairs=score_pairs,
        max_units=3,
    )

    assert {
        unit["parent_document_id"] for unit in selected
    } == {"contest", "event", "raid"}


def test_semantic_evidence_selector_does_not_spend_all_slots_on_parent_diversity():
    units = [
        {
            "candidate_ref": "1",
            "parent_document_id": "target",
            "start_char": index,
            "title": "장착중인 칭호가 해제되지 않아요!",
            "context_text": "1:1 문의 기재사항",
            "text": text,
        }
        for index, text in enumerate(
            [
                "아래 기재사항을 작성하여 1:1 문의를 남겨주세요.",
                "1. 서버/캐릭터명 :",
                "2. 장착중인 칭호 :",
            ],
            1,
        )
    ]
    units.extend(
        {
            "candidate_ref": str(index),
            "parent_document_id": f"decoy-{index}",
            "start_char": index,
            "title": f"다른 문의 문서 {index}",
            "context_text": "문의",
            "text": f"다른 문의 안내 {index}",
        }
        for index in range(2, 9)
    )

    def score_pairs(pairs):
        scores = []
        for query, text in pairs:
            if "평균 처리 기간" in query:
                scores.append(20.0 if "다른 문의 안내 2" in text else 0.0)
            elif "서버/캐릭터명" in text:
                scores.append(19.0)
            elif "장착중인 칭호" in text and "근거:" in text:
                scores.append(18.0)
            elif "기재사항" in text:
                scores.append(17.0)
            else:
                scores.append(10.0 - int(text.rsplit(" ", 1)[-1]))
        return scores

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["1:1 문의 정보", "평균 처리 기간"],
        question="1:1 문의에 적어야 할 정보와 평균 처리 기간",
        score_pairs=score_pairs,
        max_units=8,
    )

    selected_text = {unit["text"] for unit in selected}
    assert "1. 서버/캐릭터명 :" in selected_text
    assert "2. 장착중인 칭호 :" in selected_text
    assert len(
        {unit["parent_document_id"] for unit in selected}
    ) >= 3


def test_semantic_evidence_selector_keeps_requirement_depth_after_two_parents():
    target_texts = [
        "아래 기재사항을 작성하여 1:1 문의를 남겨주세요.",
        "[기재사항]",
        "최대한 신속히 살펴보고 조치해드리겠습니다.",
        "해당 문제는 장착중인 칭호에서 발생할 수 있습니다.",
        "동일한 칭호가 칭호북에 존재할 수 있습니다.",
        "1. 서버/캐릭터명 :",
        "2. 장착중인 칭호 :",
    ]
    units = [
        {
            "candidate_ref": "1",
            "parent_document_id": "target",
            "start_char": index,
            "title": "장착중인 칭호가 해제되지 않아요!",
            "context_text": "1:1 문의 기재사항",
            "text": text,
        }
        for index, text in enumerate(target_texts, 1)
    ]
    units.extend(
        [
            {
                "candidate_ref": "2",
                "parent_document_id": "duration-decoy",
                "start_char": 1,
                "title": "다른 문의 처리 안내",
                "context_text": "처리 기간",
                "text": "다른 문의는 90일 후 처리됩니다.",
            },
            {
                "candidate_ref": "3",
                "parent_document_id": "third-parent-decoy",
                "start_char": 1,
                "title": "무관한 문의 안내",
                "context_text": "문의",
                "text": "고객센터로 문의해 주세요.",
            },
        ]
    )

    question_scores = {
        text: float(100 - index)
        for index, text in enumerate(target_texts)
    }

    def score_pairs(pairs):
        scores = []
        for query, reranker_text in pairs:
            if "평균 처리 기간" in query:
                scores.append(
                    200.0 if "90일 후 처리" in reranker_text else 0.0
                )
                continue
            if query == "1:1 문의 정보":
                scores.append(
                    200.0 if "아래 기재사항" in reranker_text else 0.0
                )
                continue
            scores.append(
                next(
                    (
                        score
                        for text, score in question_scores.items()
                        if text in reranker_text
                    ),
                    1.0 if "고객센터로 문의" in reranker_text else 2.0,
                )
            )
        return scores

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["1:1 문의 정보", "평균 처리 기간"],
        question="1:1 문의에 적어야 할 정보와 평균 처리 기간",
        score_pairs=score_pairs,
        max_units=8,
    )

    assert "1. 서버/캐릭터명 :" in {
        unit["text"] for unit in selected
    }
    assert "2. 장착중인 칭호 :" in {
        unit["text"] for unit in selected
    }
    assert "third-parent-decoy" not in {
        unit["parent_document_id"] for unit in selected
    }


def test_semantic_evidence_selector_does_not_fill_after_one_clear_fact():
    units = [
        {
            "candidate_ref": str(index),
            "parent_document_id": parent,
            "start_char": index,
            "title": title,
            "context_text": "쿠폰 입력 안내",
            "text": text,
        }
        for index, (parent, title, text) in enumerate(
            [
                (
                    "drawing-show",
                    "레바vs낡은창고 드로잉쇼 이모티콘",
                    "모든 쿠폰은 계정당 1회 입력 가능합니다.",
                ),
                *(
                    (
                        "other-event",
                        "다른 쿠폰 이벤트",
                        f"관련 없는 쿠폰 화면 문구 {index}",
                    )
                    for index in range(1, 8)
                ),
            ],
            1,
        )
    ]

    def score_pairs(pairs):
        return [
            0.99 if "계정당 1회" in text else 0.30
            for _, text in pairs
        ]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=[
            "드로잉쇼 쿠폰은 계정당 몇 번 입력할 수 있었어?"
        ],
        question="드로잉쇼 쿠폰은 계정당 몇 번 입력할 수 있었어?",
        score_pairs=score_pairs,
        max_units=8,
    )

    assert [unit["text"] for unit in selected] == [
        "모든 쿠폰은 계정당 1회 입력 가능합니다."
    ]


def test_semantic_evidence_selector_does_not_trust_numeric_only_high_score():
    units = [
        {
            "candidate_ref": "1",
            "parent_document_id": "monthly-item",
            "start_char": 1,
            "title": "11월 이달의 아이템",
            "context_text": "시브의 보조장비 보주",
            "text": "2026.07.16 ~ 2026.08.27",
        },
        {
            "candidate_ref": "1",
            "parent_document_id": "monthly-item",
            "start_char": 2,
            "title": "11월 이달의 아이템",
            "context_text": "시브의 보조장비 보주",
            "text": "| 삭제일자 | 무제한 |",
        },
    ]

    def score_pairs(pairs):
        return [
            0.90 if "2026.07.16" in text else 0.30
            for _, text in pairs
        ]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=[
            "2025년 11월 시브의 보조장비 보주는 삭제 기한이 정해져 있었어?"
        ],
        question=(
            "2025년 11월 시브의 보조장비 보주는 "
            "삭제 기한이 정해져 있었어?"
        ),
        score_pairs=score_pairs,
        max_units=2,
    )

    assert [unit["text"] for unit in selected] == [
        "2026.07.16 ~ 2026.08.27",
        "| 삭제일자 | 무제한 |",
    ]


def test_semantic_evidence_selector_prefilters_pairs_per_query():
    units = [
        {
            "candidate_ref": str(index),
            "start_char": index,
            "title": "문서",
            "context_text": "입장 조건",
            "text": f"후보 근거 {index}",
        }
        for index in range(1, 41)
    ]
    observed_pairs = []

    def score_pairs(pairs):
        observed_pairs.extend(pairs)
        return [float(index) for index, _ in enumerate(pairs)]

    selected = select_semantic_product_evidence_units(
        units,
        selection_queries=["입장 조건"],
        question="입장 조건",
        score_pairs=score_pairs,
        max_units=4,
        prefilter_per_query=5,
    )

    assert len(observed_pairs) == 5
    assert len(selected) == 4


def test_product_surface_extracts_literal_clauses_and_grammatical_subject():
    question = (
        "장착 칭호가 해제되지 않을 때 1:1 문의에 적어야 할 정보와 "
        "평균 처리 기간을 알려줘."
    )

    assert explicit_question_subjects(question) == ["장착 칭호"]
    assert explicit_nominative_question_subjects(question) == ["장착 칭호"]
    assert explicit_nominative_question_subjects(
        "2025년 11월 시브의 보조장비 보주는 삭제 기한이 정해져 있었어?"
    ) == []
    assert explicit_nominative_question_subjects(
        "장비가 초월이 안돼. 왜이럴까?"
    ) == ["장비"]
    assert explicit_nominative_question_subjects(
        "새해맞이 이벤트의 칭호 전체 표를 보여줘."
    ) == []
    assert explicit_question_clauses(question) == [
        "장착 칭호가 해제되지 않을 때 1:1 문의에 적어야 할 정보",
        "평균 처리 기간을 알려줘",
    ]


def test_product_verifier_accepts_grounded_transcendence_failure_reason():
    question = "장비가 초월이 안돼. 왜이럴까?"
    evidence = (
        "계승으로 인챈트 정보를 받았거나, 융합되어있는 장비는 "
        "장비 초월을 이용할 수 없습니다."
    )
    chunks = {"transcendence": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "transcendence",
            "title": "장비 초월이 가능하지 않아요!",
            "context_text": "장비 초월 제한",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "question_relevance_score": 0.98,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": evidence,
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=question,
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=explicit_nominative_question_subjects(question),
    )

    assert verified["mode"] == "answer"
    assert verified["rejected_claims"] == []
    assert verified["verification"]["requested_subjects"] == ["장비"]


def test_product_verifier_rejects_implicit_subject_claim_from_other_document():
    title_text = "1. 서버/캐릭터명 :\n2. 장착중인 칭호 :"
    delay_text = "유형에 따라 3~5일 정도 소요될 수 있습니다."
    chunks = {
        "title": {"display_text": title_text},
        "delay": {"display_text": delay_text},
    }
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "title",
            "title": "[게임 이용] 장착중인 칭호가 해제되지 않아요!",
            "context_text": "",
            "start_char": 0,
            "end_char": len(title_text),
            "text": title_text,
        },
        {
            "evidence_ref": "E2",
            "chunk_id": "delay",
            "title": "[게임이용제한] 이용 제한 해제를 어떻게 하나요?",
            "context_text": "",
            "start_char": 0,
            "end_char": len(delay_text),
            "text": delay_text,
        },
    ]
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "문의 정보는 서버/캐릭터명과 장착중인 칭호입니다.",
                    "evidence_refs": ["E1"],
                },
                {
                    "text": "평균 처리 기간은 3~5일입니다.",
                    "evidence_refs": ["E2"],
                },
            ],
            "clarification": "",
        },
        question=(
            "장착 칭호가 해제되지 않을 때 1:1 문의에 적어야 할 정보와 "
            "평균 처리 기간을 알려줘."
        ),
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["장착 칭호"],
    )

    assert verified["mode"] == "partial"
    assert [claim["text"] for claim in verified["claims"]] == [
        "문의 정보는 서버/캐릭터명과 장착중인 칭호입니다."
    ]
    assert verified["rejected_claims"][0]["reasons"] == [
        "claim_subject_not_bound_to_evidence"
    ]


def test_product_verifier_downgrades_silently_omitted_question_clause():
    evidence = "길드장 계정이 이용제한 상태이면 권한이 위임될 수 있습니다."
    chunks = {"policy": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "policy",
            "title": "운영정책",
            "context_text": "길드장 권한 위임 조건",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "길드장 계정이 이용제한 상태이면 권한이 위임됩니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="길드장 권한 위임 조건과 처리 기간을 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["길드장 권한"],
    )

    assert verified["mode"] == "partial"
    assert (
        verified["verification"]["all_explicit_question_clauses_covered"]
        is False
    )


def test_product_verifier_downgrades_missing_kiwi_independent_clause():
    evidence = (
        "2026 아라드 패스 차원의 별자리 아바타 콤보 상자는 "
        "2026년 3월 26일 06시 일괄 삭제됩니다."
    )
    chunks = {"shop": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "shop",
            "parent_document_id": "shop-doc",
            "title": "2026 아라드 패스 차원의 별자리 아바타 콤보 상자",
            "context_text": "삭제 안내",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": evidence,
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=(
            "2026 아라드 패스 차원의 별자리 아바타 콤보 상자는 "
            "언제 판매됐고 언제 일괄 삭제됐어?"
        ),
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "partial"
    assert (
        verified["verification"]["all_explicit_question_clauses_covered"]
        is False
    )


def test_product_verifier_accepts_distinct_focused_claims_with_synonyms():
    question = (
        "해방의 열쇠 100개 상자는 무엇을 주고 언제 삭제됐어?"
    )
    focuses = kiwi_independent_requirement_queries(question)
    texts = {
        "contents": (
            "사용 시 해방의 열쇠 100개, 봉인된 자물쇠 34개를 "
            "획득할 수 있습니다."
        ),
        "deletion": "삭제일자는 2026년 7월 23일 06시입니다.",
    }
    chunks = {
        chunk_id: {"display_text": text}
        for chunk_id, text in texts.items()
    }
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": "shop-doc",
            "title": "해방의 열쇠 100개 상자",
            "context_text": "상품 정보",
            "question_focus": focus,
            "start_char": 0,
            "end_char": len(texts[chunk_id]),
            "text": texts[chunk_id],
        }
        for evidence_ref, chunk_id, focus in [
            ("E1", "contents", focuses[0]),
            ("E2", "deletion", focuses[1]),
        ]
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "해방의 열쇠 100개 상자는 해방의 열쇠 100개와 "
                        "봉인된 자물쇠 34개를 제공합니다."
                    ),
                    "evidence_refs": ["E1"],
                },
                {
                    "text": (
                        "해방의 열쇠 100개 상자는 "
                        "2026년 7월 23일 06시에 삭제됩니다."
                    ),
                    "evidence_refs": ["E2"],
                },
            ],
            "clarification": "",
        },
        question=question,
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "answer"
    assert (
        verified["verification"]["all_explicit_question_clauses_covered"]
        is True
    )


def test_product_verifier_rejects_condition_duration_as_processing_duration():
    evidence = (
        "② 길드장 계정이 12개월이상 미접속으로 인한 휴면 상태인 경우"
    )
    chunks = {"policy": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "policy",
            "title": "던전앤파이터 운영정책 (2020-12-04 시행)",
            "context_text": "운영정책",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "길드장 권한 위임 처리 기간은 12개월 이상 "
                        "미접속으로 인한 휴면 상태인 경우입니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=(
            "2020년 12월 4일 시행 운영정책에서 길드장 권한이 "
            "위임될 수 있는 조건과 처리 기간을 알려줘."
        ),
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["길드장 권한"],
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "question_relation_role_mismatch"
    ]


def test_product_verifier_accepts_direct_processing_duration_language():
    evidence = "길드장 권한 위임 요청은 접수 후 평균 3~5일 소요됩니다."
    chunks = {"policy": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "policy",
            "title": "길드장 권한 위임 안내",
            "context_text": "처리 안내",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "길드장 권한 위임 처리 기간은 평균 3~5일입니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="길드장 권한 위임 처리 기간을 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["길드장 권한"],
    )

    assert verified["rejected_claims"] == []
    assert verified["mode"] == "answer"


def test_product_verifier_accepts_explicit_single_subject_policy_condition():
    evidence = "길드장 계정이 이용제한 상태인 경우"
    chunks = {"policy": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "policy",
            "title": "던전앤파이터 운영정책 (2020-12-04 시행)",
            "context_text": "위임 조건",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "길드장 권한이 위임될 수 있는 조건은 길드장 계정이 "
                        "이용제한 상태인 경우입니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="길드장 권한이 위임될 수 있는 조건을 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["길드장 권한"],
    )

    assert verified["rejected_claims"] == []
    assert verified["mode"] == "answer"


def test_product_question_normalizes_attached_limit_and_request_tail():
    assert normalize_product_question(
        "최후의과업 입장 명성제한알려줘"
    ) == "최후의과업 입장 명성 제한 알려줘"


def test_product_verifier_accepts_two_grounded_claims_and_restores_coordinates():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "최후의 과업 입장 명성은 108,921입니다.",
                "evidence_refs": ["E1"],
            },
            {
                "text": "디레지에 입장 명성은 63,257입니다.",
                "evidence_refs": ["E2"],
            },
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="최후의 과업이랑 디레지에 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업", "디레지에"],
    )

    assert verified["mode"] == "answer"
    assert len(verified["claims"]) == 2
    assert verified["rejected_claims"] == []
    assert verified["claims"][1]["citations"][0] == {
        "evidence_ref": "E2",
        "chunk_id": "diregie",
        "start_char": 0,
        "end_char": len(chunks["diregie"]["display_text"]),
        "text": chunks["diregie"]["display_text"],
        "title": "검은 질병의 디레지에 레이드",
    }


def test_product_verifier_preserves_clean_grounded_partial_without_clarification():
    chunks, units = _fixture()
    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": "최후의 과업 입장 명성은 108,921입니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="최후의 과업 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업"],
    )

    assert verified["mode"] == "partial"
    assert verified["rejected_claims"] == []


def test_product_verifier_promotes_fully_grounded_binary_partial():
    evidence = "성장 가속 모드 상태에서는 결투장 이용이 어렵습니다."
    chunks = {"faq": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "faq",
            "parent_document_id": "growth-mode-faq",
            "title": "성장 가속 모드 캐릭터로 결투장에 입장하고 싶어요.",
            "context_text": "",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": "성장 가속 모드 캐릭터는 결투장을 이용할 수 없습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="성장 가속 모드 캐릭터로 결투장을 이용할 수 있어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "answer"


def test_product_verifier_promotes_grounded_contracted_binary_partial():
    evidence = "(일반모드는 랭킹 집계와 무관합니다.)"
    chunks = {"ranking": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "ranking",
            "title": "트리니티 이벤트",
            "context_text": "랭킹 집계",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "complete": False,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": (
                        "트리니티 이벤트의 일반모드 플레이도 랭킹 집계에 "
                        "포함되지 않았습니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="트리니티 이벤트의 일반모드 플레이도 랭킹 집계에 포함됐어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "answer"
    assert verified["rejected_claims"] == []


def test_product_verifier_promotes_grounded_deadline_binary_partial():
    evidence = "시브의 보조장비 보주는 삭제 기한이 정해져 있지 않습니다."
    chunks = {"shop": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "shop",
            "parent_document_id": "shop-doc",
            "title": "2025년 11월 시브의 보조장비 보주",
            "context_text": "삭제 기한",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": "시브의 보조장비 보주는 삭제 기한이 정해져 있지 않습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="시브의 보조장비 보주는 삭제 기한이 정해져 있었어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "answer"
    assert verified["rejected_claims"] == []


def test_product_verifier_does_not_promote_one_of_two_partial_requirements():
    evidence = "방문·전화 상담 운영 안내: 방문 상담은 이용할 수 없습니다."
    chunks = {"consulting": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "consulting",
            "title": "방문·전화 상담 운영 안내",
            "context_text": "고객상담실 운영",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": "방문 상담은 이용할 수 없습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="방문 상담 가능 여부와 전화 상담 운영시간을 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "partial"
    assert verified["model_mode"] == "partial"


def test_product_verifier_blocks_cross_parent_conflicting_number():
    texts = {
        "old": "입장 명성은 63,257입니다.",
        "new": "입장 명성은 72,000입니다.",
    }
    chunks = {
        chunk_id: {"display_text": text}
        for chunk_id, text in texts.items()
    }
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": parent,
            "title": title,
            "context_text": "입장 조건",
            "start_char": 0,
            "end_char": len(texts[chunk_id]),
            "text": texts[chunk_id],
        }
        for evidence_ref, chunk_id, parent, title in [
            ("E1", "old", "old-doc", "이전 가이드"),
            ("E2", "new", "new-doc", "현재 가이드"),
        ]
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "입장 명성은 63,257입니다.",
                    "evidence_refs": ["E1", "E2"],
                }
            ],
            "clarification": "",
        },
        question="입장 명성 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "cross_parent_structured_value_conflict"
    ]


def test_product_verifier_accepts_cross_parent_korean_scaled_currency():
    texts = {
        "numeric": "최대 적립액은 4,000원입니다.",
        "scaled": "최대 적립액은 4천원입니다.",
    }
    chunks = {
        chunk_id: {"display_text": text}
        for chunk_id, text in texts.items()
    }
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": parent,
            "title": "Npay 7% 적립 이벤트",
            "context_text": "이벤트 내용",
            "start_char": 0,
            "end_char": len(texts[chunk_id]),
            "text": texts[chunk_id],
        }
        for evidence_ref, chunk_id, parent in [
            ("E1", "numeric", "event-notice"),
            ("E2", "scaled", "event-summary"),
        ]
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "Npay 7% 이벤트의 최대 적립액은 4,000원입니다.",
                    "evidence_refs": ["E1", "E2"],
                }
            ],
            "clarification": "",
        },
        question="Npay 7% 이벤트의 최대 적립액은 얼마였어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["rejected_claims"] == []
    assert verified["mode"] == "answer"


def test_product_verifier_accepts_equivalent_count_words_across_parents():
    texts = {
        "shop": "스페셜 상자는 계정당 5회 구매할 수 있습니다.",
        "package": "스페셜 상자 (계정당 5회)",
    }
    chunks = {
        chunk_id: {"display_text": text}
        for chunk_id, text in texts.items()
    }
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": parent,
            "title": "스페셜 상자",
            "context_text": "구매 제한",
            "start_char": 0,
            "end_char": len(texts[chunk_id]),
            "text": texts[chunk_id],
        }
        for evidence_ref, chunk_id, parent in [
            ("E1", "shop", "shop-doc"),
            ("E2", "package", "package-doc"),
        ]
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "스페셜 상자는 계정당 5번 살 수 있습니다.",
                    "evidence_refs": ["E1", "E2"],
                }
            ],
            "clarification": "",
        },
        question="스페셜 상자는 계정당 몇 번 살 수 있어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["rejected_claims"] == []
    assert verified["mode"] == "answer"


def test_product_verifier_accepts_equivalent_korean_pm_time():
    evidence = "7월 8일 오후 3시 10분부터 퍼스트 서버가 오픈됩니다."
    chunks = {"update": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "update",
            "parent_document_id": "update-doc",
            "title": "7/8 퍼스트 서버 업데이트 안내",
            "context_text": "업데이트",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "7월 8일 퍼스트 서버는 15시 10분에 오픈했습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="7월 8일 퍼스트 서버는 실제로 몇 시에 오픈했어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["rejected_claims"] == []
    assert verified["mode"] == "answer"


def test_product_verifier_blocks_cross_parent_conflicting_date():
    texts = {
        "old": "적용일은 2026년 7월 1일입니다.",
        "new": "적용일은 2026년 8월 1일입니다.",
    }
    chunks = {
        chunk_id: {"display_text": text}
        for chunk_id, text in texts.items()
    }
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": parent,
            "title": title,
            "context_text": "적용일",
            "start_char": 0,
            "end_char": len(texts[chunk_id]),
            "text": texts[chunk_id],
        }
        for evidence_ref, chunk_id, parent, title in [
            ("E1", "old", "old-doc", "이전 정책"),
            ("E2", "new", "new-doc", "현재 정책"),
        ]
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "적용일은 2026년 7월 1일입니다.",
                    "evidence_refs": ["E1", "E2"],
                }
            ],
            "clarification": "",
        },
        question="정책 적용일 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "cross_parent_structured_value_conflict"
    ]


def test_product_verifier_blocks_cross_parent_conflicting_revision():
    texts = {
        "old": "revision: v2",
        "new": "revision: v3",
    }
    chunks = {
        chunk_id: {"display_text": text}
        for chunk_id, text in texts.items()
    }
    units = [
        {
            "evidence_ref": evidence_ref,
            "chunk_id": chunk_id,
            "parent_document_id": parent,
            "title": title,
            "context_text": "정책 revision",
            "revision_id": revision,
            "start_char": 0,
            "end_char": len(texts[chunk_id]),
            "text": texts[chunk_id],
        }
        for evidence_ref, chunk_id, parent, title, revision in [
            ("E1", "old", "old-doc", "이전 정책", "v2"),
            ("E2", "new", "new-doc", "현재 정책", "v3"),
        ]
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "정책 revision은 v2입니다.",
                    "evidence_refs": ["E1", "E2"],
                }
            ],
            "clarification": "",
        },
        question="정책 revision 알려줘.",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "cross_parent_structured_value_conflict"
    ]


def test_product_verifier_accepts_claim_free_clarification():
    chunks, units = _fixture()
    verified = verify_product_claim_output(
        {
            "mode": "clarification",
            "claims": [],
            "clarification": (
                "레이드 보상과 추가 이벤트 보상 중 어느 것을 묻는지 "
                "알려주세요."
            ),
        },
        question="디레지에 보상 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["디레지에"],
    )

    assert verified["mode"] == "clarification"
    assert verified["claims"] == []
    assert verified["verification"]["clarification_contract_valid"] is True


def test_product_verifier_hides_claims_from_clarification_output():
    chunks, units = _fixture()
    verified = verify_product_claim_output(
        {
            "mode": "clarification",
            "claims": [
                {
                    "text": "디레지에 입장 명성은 63,257입니다.",
                    "evidence_refs": ["E2"],
                }
            ],
            "clarification": "어느 디레지에 콘텐츠를 묻는지 알려주세요.",
        },
        question="디레지에 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["디레지에"],
    )

    assert verified["mode"] == "clarification"
    assert verified["claims"] == []
    assert verified["rejected_claims"][0]["reasons"] == [
        "clarification_must_not_include_claims"
    ]
    assert verified["verification"]["clarification_contract_valid"] is False


def test_product_verifier_rejects_empty_clarification_message():
    chunks, units = _fixture()
    verified = verify_product_claim_output(
        {
            "mode": "clarification",
            "claims": [],
            "clarification": "",
        },
        question="디레지에 보상 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["디레지에"],
    )

    assert verified["mode"] == "unsupported"
    assert verified["claims"] == []
    assert verified["verification"]["clarification_contract_valid"] is False


def test_product_candidate_flow_renders_clarification_message():
    evidence_text = "디레지에 레이드 보상 안내"

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "clarification",
                "claims": [],
                "clarification": (
                    "레이드 보상과 추가 이벤트 보상 중 어느 것을 "
                    "묻는지 알려주세요."
                ),
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question="디레지에 보상 알려줘",
        requirement_queries=None,
        requested_subjects=["디레지에"],
        selected=[
            {
                "chunk_id": "scope",
                "parent_document_id": "scope_doc",
                "title": "검은 질병의 디레지에 레이드",
            }
        ],
        chunks_by_id={"scope": {"display_text": evidence_text}},
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=[
            {
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "scope",
                "title": "검은 질병의 디레지에 레이드",
                "context_text": "레이드 보상",
                "start_char": 0,
                "end_char": len(evidence_text),
                "text": evidence_text,
                "complete": False,
            }
        ],
    )

    assert result["mode"] == "clarification"
    assert result["claims"] == []
    assert result["rendered_answer"] == result["clarification"]


def test_product_candidate_flow_allows_one_claim_with_same_value_from_two_parents():
    texts = [
        "입장 명성은 63,257입니다.",
        "입장 명성은 63,257입니다.",
    ]
    units = [
        {
            "evidence_ref": f"E{index}",
            "candidate_ref": str(index),
            "chunk_id": f"c{index}",
            "parent_document_id": f"p{index}",
            "title": title,
            "context_text": "입장 조건",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
        }
        for index, (title, text) in enumerate(
            zip(
                ["레이드 가이드", "레이드 FAQ"],
                texts,
            ),
            1,
        )
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": "입장 명성은 63,257입니다.",
                        "evidence_refs": ["E1", "E2"],
                    }
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question="입장 명성 알려줘",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": f"c{index}",
                "parent_document_id": f"p{index}",
                "title": unit["title"],
            }
            for index, unit in enumerate(units, 1)
        ],
        chunks_by_id={
            f"c{index}": {"display_text": text}
            for index, text in enumerate(texts, 1)
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "answer"
    assert len(result["claims"]) == 1
    assert result["clarification_options"] == []


def test_product_verifier_prunes_overcitation_outside_explicit_policy_date():
    texts = [
        "① 12개월 이상 접속 기록이 없는 경우 휴면ID로 전환됩니다.",
        "① 12개월 이상 접속 기록이 없는 경우 휴면ID로 전환됩니다.",
    ]
    titles = [
        "던전앤파이터 운영정책 (2023-06-10 시행)",
        "던전앤파이터 운영정책 (2023-06-01 시행)",
    ]
    units = [
        {
            "evidence_ref": f"E{index}",
            "chunk_id": f"policy-{index}",
            "parent_document_id": f"policy-doc-{index}",
            "title": title,
            "context_text": "운영정책",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
        }
        for index, (title, text) in enumerate(zip(titles, texts), 1)
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "2023년 6월 10일 시행 운영정책에서 휴면ID 전환 "
                        "기준은 12개월 미접속이었다."
                    ),
                    "evidence_refs": ["E1", "E2"],
                }
            ],
            "clarification": "",
        },
        question=(
            "2023년 6월 10일 시행 운영정책에서 휴면ID 전환 기준은 "
            "몇 개월 미접속이었어?"
        ),
        evidence_units=units,
        chunks_by_id={
            f"policy-{index}": {"display_text": text}
            for index, text in enumerate(texts, 1)
        },
    )

    assert verified["mode"] == "answer"
    assert verified["claims"][0]["evidence_refs"] == ["E1"]
    assert verified["verification"]["pruned_evidence_refs"] == ["E2"]
    assert (
        verified["verification"]["raw_output_passed_without_sanitization"]
        is False
    )


def test_product_verifier_rejects_second_requirement_citing_price_row():
    trade_text = "| 거래타입 | 교환가능 |"
    price_text = "| 상점판매가격 | 4,000만 골드 |"
    source = f"{trade_text}\n{price_text}"
    price_start = source.index(price_text)
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "cube",
            "title": "5월 이달의 아이템",
            "context_text": "고대의 바인드 큐브 8개 상자",
            "valid_from": "2026-05-01",
            "valid_to": "2026-05-31",
            "start_char": 0,
            "end_char": len(trade_text),
            "text": trade_text,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "chunk_id": "cube",
            "title": "5월 이달의 아이템",
            "context_text": "고대의 바인드 큐브 8개 상자",
            "valid_from": "2026-05-01",
            "valid_to": "2026-05-31",
            "start_char": price_start,
            "end_char": price_start + len(price_text),
            "text": price_text,
            "complete": False,
        },
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "2026년 5월 고대의 바인드 큐브 8개 상자의 "
                        "거래 타입은 교환가능입니다."
                    ),
                    "evidence_refs": ["E1"],
                },
                {
                    "text": (
                        "2026년 5월 고대의 바인드 큐브 8개 상자의 "
                        "계정당 구매 제한은 존재하지 않습니다."
                    ),
                    "evidence_refs": ["E2"],
                },
            ],
            "clarification": "",
        },
        question=(
            "2026년 5월 고대의 바인드 큐브 8개 상자의 거래 타입과 "
            "계정당 구매 제한을 알려줘."
        ),
        evidence_units=units,
        chunks_by_id={"cube": {"display_text": source}},
    )

    assert verified["mode"] == "partial"
    assert len(verified["claims"]) == 1
    assert verified["claims"][0]["evidence_refs"] == ["E1"]
    assert verified["rejected_claims"][0]["reasons"] == [
        "negative_absence_not_in_evidence"
    ]


def test_product_candidate_flow_keeps_explicit_cross_document_roles():
    update_text = (
        "5/21(목) 정기점검 업데이트 공지는 "
        "2026년 5월 20일에 게시됐습니다."
    )
    maintenance_text = (
        "실제 5/21(목) 정기점검은 "
        "2026년 5월 21일에 적용됐습니다."
    )
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "update",
            "parent_document_id": "update_doc",
            "title": "5/21(목) 정기점검 업데이트 안내",
            "context_text": "업데이트 공지 게시",
            "start_char": 0,
            "end_char": len(update_text),
            "text": update_text,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "maintenance",
            "parent_document_id": "maintenance_doc",
            "title": "5/21(목) 정기점검 안내",
            "context_text": "실제 점검 적용",
            "start_char": 0,
            "end_char": len(maintenance_text),
            "text": maintenance_text,
            "complete": False,
        },
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": (
                            "업데이트 공지는 2026년 5월 20일에 "
                            "게시됐습니다."
                        ),
                        "evidence_refs": ["E1"],
                    },
                    {
                        "text": (
                            "실제 점검 적용일은 2026년 5월 21일입니다."
                        ),
                        "evidence_refs": ["E2"],
                    },
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question=(
            "5/21(목) 정기점검 업데이트 공지는 언제 게시됐고, "
            "실제 점검 적용은 언제야?"
        ),
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": "update",
                "parent_document_id": "update_doc",
                "title": units[0]["title"],
            },
            {
                "chunk_id": "maintenance",
                "parent_document_id": "maintenance_doc",
                "title": units[1]["title"],
            },
        ],
        chunks_by_id={
            "update": {"display_text": update_text},
            "maintenance": {"display_text": maintenance_text},
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "answer"
    assert len(result["claims"]) == 2
    assert "어느 내용을 말씀하시나요" not in result["rendered_answer"]


def test_product_verifier_blocks_unsupported_mileage_m_value():
    cap_text = (
        "던전/레이드/결투장을 통해 획득 가능한 마일리지는 "
        "일일 최대 50M입니다."
    )
    unrelated_text = "시즌7 상점 상품은 계정당 1개 구매 가능합니다."
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "cap",
            "title": "마일리지샵 2026 시즌7",
            "context_text": "플레이 마일리지 일일 최대",
            "start_char": 0,
            "end_char": len(cap_text),
            "text": cap_text,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "chunk_id": "unrelated",
            "title": "마일리지샵 2026 시즌7",
            "context_text": "판매 상품",
            "start_char": 0,
            "end_char": len(unrelated_text),
            "text": unrelated_text,
            "complete": False,
        },
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "플레이 마일리지는 일일 최대 50M입니다.",
                    "evidence_refs": ["E1"],
                },
                {
                    "text": "현재 남은 획득 가능량은 0M입니다.",
                    "evidence_refs": ["E2"],
                },
            ],
            "clarification": "",
        },
        question=(
            "마일리지샵 2026 시즌7에서 플레이로 얻을 수 있는 "
            "일일 최대 마일리지와 현재 남은 획득 가능량을 알려줘."
        ),
        evidence_units=units,
        chunks_by_id={
            "cap": {"display_text": cap_text},
            "unrelated": {"display_text": unrelated_text},
        },
    )

    assert verified["mode"] == "partial"
    assert len(verified["claims"]) == 1
    assert verified["claims"][0]["evidence_refs"] == ["E1"]
    assert verified["rejected_claims"][0]["reasons"] == [
        "factual_values_not_in_evidence"
    ]


def test_product_candidate_flow_clarifies_cross_parent_broad_answer():
    texts = [
        "디레지에 미니 콘테스트 보상은 20만 세라입니다.",
        "디레지에 레이드 추가 이벤트 주요 보상은 보주입니다.",
        "검은 질병의 디레지에 레이드 주간 보상은 1회입니다.",
    ]
    units = [
        {
            "evidence_ref": f"E{index}",
            "candidate_ref": str(index),
            "chunk_id": f"c{index}",
            "parent_document_id": f"p{index}",
            "title": title,
            "context_text": "보상",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
        }
        for index, (title, text) in enumerate(
            zip(
                [
                    "디레지에 미니 콘테스트 사전 안내",
                    "디레지에 레이드 추가 이벤트 진행 안내",
                    "검은 질병의 디레지에 레이드",
                ],
                texts,
            ),
            1,
        )
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": texts[0],
                        "evidence_refs": ["E1"],
                    },
                    {
                        "text": texts[1],
                        "evidence_refs": ["E2"],
                    },
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question="디레지에 보상 알려줘",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": f"c{index}",
                "parent_document_id": f"p{index}",
                "title": unit["title"],
            }
            for index, unit in enumerate(units, 1)
        ],
        chunks_by_id={
            f"c{index}": {"display_text": text}
            for index, text in enumerate(texts, 1)
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "clarification"
    assert result["claims"] == []
    assert "미니 콘테스트" in result["clarification"]
    assert "추가 이벤트" in result["clarification"]
    assert "검은 질병" in result["clarification"]
    assert [
        option["title"]
        for option in result["clarification_options"]
    ] == [
        "디레지에 미니 콘테스트 사전 안내",
        "디레지에 레이드 추가 이벤트 진행 안내",
        "검은 질병의 디레지에 레이드",
    ]
    assert "20만 세라" not in result["rendered_answer"]
    assert result["verification"]["reason"] == (
        "ambiguous_cross_parent_context"
    )
    assert result["verification"]["cross_parent_context"]["decision"] == (
        "clarification"
    )
    ambiguous_rejections = [
        rejection
        for rejection in result["rejected_claims"]
        if rejection["reasons"] == ["ambiguous_cross_parent_context"]
    ]
    assert [
        rejection["text"] for rejection in ambiguous_rejections
    ] == texts[:2]
    assert [
        rejection["evidence_refs"] for rejection in ambiguous_rejections
    ] == [["E1"], ["E2"]]


def test_product_candidate_flow_keeps_compatible_procedural_detail():
    texts = [
        "서비스센터 > 보안 > 간편잠금 > 비밀번호 변경 버튼을 클릭합니다.",
        "홈페이지 서비스센터의 비밀번호 변경 버튼을 클릭합니다.",
        "던파ON 간편잠금에서 비밀번호를 변경할 수 있습니다.",
        "휴대폰 인증 후 숫자 6자리 비밀번호를 입력합니다.",
    ]
    units = [
        {
            "evidence_ref": f"E{index}",
            "candidate_ref": str(index),
            "chunk_id": f"quick-{index}",
            "parent_document_id": f"quick-parent-{index}",
            "title": (
                "[간편잠금] 비밀번호 변경 안내"
                if index < 3
                else "[계정잠금] 던파ON 간편잠금 참고사항"
            ),
            "context_text": "변경 절차",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
        }
        for index, text in enumerate(texts, 1)
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {"text": text, "evidence_refs": [f"E{index}"]}
                    for index, text in enumerate(texts, 1)
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question="간편잠금 비밀번호는 어디서 어떻게 바꿔?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": unit["chunk_id"],
                "parent_document_id": unit["parent_document_id"],
                "title": unit["title"],
            }
            for unit in units
        ],
        chunks_by_id={
            unit["chunk_id"]: {"display_text": unit["text"]}
            for unit in units
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "answer"
    assert result["claims"] == [
        {**result["claims"][0], "text": texts[0]}
    ]
    assert result["clarification_options"] == []
    assert result["verification"]["cross_parent_context"]["decision"] == (
        "compatible_detail"
    )
    assert not any(
        rejection["reasons"] == ["ambiguous_cross_parent_context"]
        for rejection in result["rejected_claims"]
    )
    assert sum(
        rejection["reasons"]
        == ["redundant_compatible_cross_parent_context"]
        for rejection in result["rejected_claims"]
    ) == 3


def test_product_candidate_flow_keeps_clarification_across_revisions():
    texts = [
        "보안 설정은 홈페이지에서 변경할 수 있습니다.",
        "보안 설정은 앱에서 변경할 수 있습니다.",
    ]
    units = [
        {
            "evidence_ref": f"E{index}",
            "candidate_ref": str(index),
            "chunk_id": f"revision-{index}",
            "parent_document_id": f"revision-parent-{index}",
            "title": f"보안 설정 변경 정책 개정 {index}",
            "revision_id": f"revision-{index}",
            "context_text": "변경 방법",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
        }
        for index, text in enumerate(texts, 1)
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {"text": text, "evidence_refs": [f"E{index}"]}
                    for index, text in enumerate(texts, 1)
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question="보안 설정은 어디서 어떻게 바꿔?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": unit["chunk_id"],
                "parent_document_id": unit["parent_document_id"],
                "title": unit["title"],
            }
            for unit in units
        ],
        chunks_by_id={
            unit["chunk_id"]: {"display_text": unit["text"]}
            for unit in units
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "clarification"
    assert result["claims"] == []
    assert result["verification"]["reason"] == (
        "ambiguous_cross_parent_context"
    )


def test_product_verifier_requires_explicit_normative_evidence_only_for_recommendations():
    def verify(question, evidence, claim):
        unit = {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "normative",
            "parent_document_id": "normative-parent",
            "title": "나벨 안내",
            "context_text": "",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "complete": False,
        }
        return verify_product_claim_output(
            {
                "mode": "answer",
                "claims": [
                    {"text": claim, "evidence_refs": ["E1"]}
                ],
                "clarification": "",
            },
            question=question,
            evidence_units=[unit],
            chunks_by_id={"normative": {"display_text": evidence}},
        )

    unsupported = verify(
        "나벨 하드 클리어에 추천하는 직업 알려줘",
        "나벨 전투에서 엘디르와 아니마에게 특수 역할이 부여됩니다.",
        "나벨 하드 클리어에 추천되는 직업은 엘디르와 아니마입니다.",
    )
    probability = verify(
        "나벨 하드 아이템 드롭 확률은 몇 퍼센트야?",
        "나벨 하드 아이템 드롭 확률은 10%입니다.",
        "나벨 하드 아이템 드롭 확률은 10%입니다.",
    )
    reward = verify(
        "나벨 레이드 보상 알려줘",
        "나벨 레이드 보상은 보주입니다.",
        "나벨 레이드 보상은 보주입니다.",
    )
    recommended = verify(
        "초보자에게 추천하는 장비 알려줘",
        "이 장비는 초보자에게 추천합니다.",
        "이 장비는 초보자에게 추천됩니다.",
    )

    assert unsupported["mode"] == "unsupported"
    assert unsupported["rejected_claims"][0]["reasons"] == [
        "normative_relation_not_in_evidence"
    ]
    assert probability["mode"] == "answer"
    assert reward["mode"] == "answer"
    assert recommended["mode"] == "answer"


def test_product_candidate_flow_keeps_dominant_title_context():
    faq_text = "장비 내구도가 0이면 장비 초월을 진행할 수 없습니다."
    notice_text = "불량이용자 단속 대상 계정은 장비 초월이 제한됩니다."
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "faq",
            "parent_document_id": "faq_doc",
            "title": "[게임 이용] 장비 초월이 가능하지 않아요!",
            "context_text": "장비 초월",
            "start_char": 0,
            "end_char": len(faq_text),
            "text": faq_text,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "notice",
            "parent_document_id": "notice_doc",
            "title": "(18:00 추가) 1/8(목) 불량이용자 단속결과 안내",
            "context_text": "단속 대상",
            "start_char": 0,
            "end_char": len(notice_text),
            "text": notice_text,
            "complete": False,
        },
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {"text": faq_text, "evidence_refs": ["E1"]},
                    {"text": notice_text, "evidence_refs": ["E2"]},
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question="장비가 초월이 안돼. 왜이럴까?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": "faq",
                "parent_document_id": "faq_doc",
                "title": units[0]["title"],
            },
            {
                "chunk_id": "notice",
                "parent_document_id": "notice_doc",
                "title": units[1]["title"],
            },
        ],
        chunks_by_id={
            "faq": {"display_text": faq_text},
            "notice": {"display_text": notice_text},
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "answer"
    assert [claim["evidence_refs"] for claim in result["claims"]] == [
        ["E1"]
    ]
    assert result["clarification_options"] == []
    assert result["rejected_claims"][-1]["reasons"] == [
        "weaker_cross_parent_context"
    ]
    assert result["verification"]["cross_parent_context"]["decision"] == (
        "dominant_parent"
    )


def test_product_candidate_flow_clarifies_mixed_event_parents():
    first = "토스페이 계좌/머니로 4만원 이상 결제 시 5% 즉시 할인"
    second = "토스페이 계좌/머니로 5만원 이상 결제 시 2천원 즉시 할인"
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "event_4",
            "parent_document_id": "event_4_doc",
            "title": "(수정) 토스페이 계좌/머니 4만원 이상 결제 할인",
            "context_text": "이벤트 내용",
            "start_char": 0,
            "end_char": len(first),
            "text": first,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "event_5",
            "parent_document_id": "event_5_doc",
            "title": "토스페이 계좌/머니 5만원 이상 결제 즉시 할인",
            "context_text": "이벤트 내용",
            "start_char": 0,
            "end_char": len(second),
            "text": second,
            "complete": False,
        },
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": "최소 결제금액은 4만원입니다.",
                        "evidence_refs": ["E1"],
                    },
                    {
                        "text": "즉시 할인액은 2천원입니다.",
                        "evidence_refs": ["E2"],
                    },
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question=(
            "토스페이 계좌·머니 할인 이벤트의 최소 결제금액과 "
            "즉시 할인액은 각각 얼마야?"
        ),
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": unit["chunk_id"],
                "parent_document_id": unit["parent_document_id"],
                "title": unit["title"],
            }
            for unit in units
        ],
        chunks_by_id={
            "event_4": {"display_text": first},
            "event_5": {"display_text": second},
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
    )

    assert result["mode"] == "clarification"
    assert result["claims"] == []
    assert len(result["clarification_options"]) == 2
    assert result["verification"]["cross_parent_context"]["decision"] == (
        "clarification"
    )
    assert result["rendered_answer"] == result["clarification"]
    assert [
        {
            "text": rejection["text"],
            "evidence_refs": rejection["evidence_refs"],
        }
        for rejection in result["rejected_claims"]
        if rejection["reasons"] == ["ambiguous_cross_parent_context"]
    ] == [
        {
            "text": "최소 결제금액은 4만원입니다.",
            "evidence_refs": ["E1"],
        },
        {
            "text": "즉시 할인액은 2천원입니다.",
            "evidence_refs": ["E2"],
        },
    ]
    assert "최소 결제금액은 4만원입니다." not in result[
        "rendered_answer"
    ]
    assert "즉시 할인액은 2천원입니다." not in result[
        "rendered_answer"
    ]


def test_product_clarification_followup_narrows_then_resolves():
    options = [
        {
            "option_id": "C1",
            "parent_document_id": "contest",
            "title": "디레지에 미니 콘테스트 사전 안내",
        },
        {
            "option_id": "C2",
            "parent_document_id": "event",
            "title": "디레지에 레이드 추가 이벤트 진행 안내",
        },
        {
            "option_id": "C3",
            "parent_document_id": "raid",
            "title": "검은 질병의 디레지에 레이드",
        },
    ]

    narrowed = resolve_product_clarification_followup(
        "레이드 말이야.",
        options,
    )

    assert narrowed["status"] == "clarification"
    assert [
        option["option_id"] for option in narrowed["options"]
    ] == ["C2", "C3"]

    resolved = resolve_product_clarification_followup(
        "검은 질병 레이드",
        narrowed["options"],
    )

    assert resolved["status"] == "resolved"
    assert resolved["option"]["option_id"] == "C3"
    rewritten = rewrite_product_clarification_question(
        "디레지에 보상 알려줘",
        resolved["option"],
    )
    assert "디레지에 보상 알려줘" in rewritten
    assert "검은 질병의 디레지에 레이드" in rewritten


def test_product_clarification_followup_reports_no_match():
    resolved = resolve_product_clarification_followup(
        "전혀 다른 이야기",
        [
            {
                "option_id": "C1",
                "parent_document_id": "raid",
                "title": "검은 질병의 디레지에 레이드",
            }
        ],
    )

    assert resolved == {"status": "unmatched", "options": []}


def test_product_followup_restricts_candidates_to_selected_parent():
    selected = [
        {"chunk_id": "contest", "parent_document_id": "contest_doc"},
        {"chunk_id": "raid_1", "parent_document_id": "raid_doc"},
        {"chunk_id": "raid_2", "parent_document_id": "raid_doc"},
    ]

    restricted = select_required_parent_candidates(
        selected,
        required_parent_document_id="raid_doc",
    )

    assert [row["chunk_id"] for row in restricted] == [
        "raid_1",
        "raid_2",
    ]


def test_product_demo_keeps_and_resolves_clarification_state(monkeypatch):
    from app import product_free_rag_demo as demo

    options = [
        {
            "option_id": "C1",
            "parent_document_id": "event",
            "title": "디레지에 레이드 추가 이벤트 진행 안내",
        },
        {
            "option_id": "C2",
            "parent_document_id": "raid",
            "title": "검은 질병의 디레지에 레이드",
        },
    ]
    calls = []

    class FakeRuntime:
        def answer(self, question, **kwargs):
            calls.append((question, kwargs))
            if len(calls) == 1:
                return {
                    "mode": "clarification",
                    "claims": [],
                    "clarification": "어느 문서 맥락인가요?",
                    "clarification_options": options,
                    "rendered_answer": "어느 문서 맥락인가요?",
                    "candidates": [],
                }
            return {
                "mode": "answer",
                "claims": [],
                "clarification": "",
                "rendered_answer": "레이드 보상 답변",
                "candidates": [],
            }

    runtime = FakeRuntime()
    monkeypatch.setattr(demo, "_runtime", lambda pipeline: runtime)

    first = demo.answer_question(
        "디레지에 보상 알려줘",
        "product_free_rag_v1",
        None,
    )
    assert first[4]["original_question"] == "디레지에 보상 알려줘"
    assert len(calls) == 1

    second = demo.answer_question(
        "레이드 말이야.",
        "product_free_rag_v1",
        first[4],
    )
    assert json.loads(second[3])["mode"] == "clarification"
    assert len(second[4]["options"]) == 2
    assert len(calls) == 1

    third = demo.answer_question(
        "검은 질병 레이드",
        "product_free_rag_v1",
        second[4],
    )
    assert "레이드 보상 답변" in third[0]
    assert third[4] is None
    assert len(calls) == 2
    assert "디레지에 보상 알려줘" in calls[1][0]
    assert "검은 질병의 디레지에 레이드" in calls[1][0]
    assert calls[1][1]["required_parent_document_id"] == "raid"


def test_product_demo_cancels_pending_clarification(monkeypatch):
    from app import product_free_rag_demo as demo

    monkeypatch.setattr(
        demo,
        "_runtime",
        lambda pipeline: (_ for _ in ()).throw(
            AssertionError("runtime must not be called")
        ),
    )
    result = demo.answer_question(
        "취소",
        "product_free_rag_v1",
        {
            "pipeline": "product_free_rag_v1",
            "original_question": "디레지에 보상 알려줘",
            "options": [],
            "candidates": [],
        },
    )

    assert result[4] is None
    assert json.loads(result[3])["verification"]["reason"] == "cancelled"


def test_product_demo_does_not_carry_state_between_pipelines(monkeypatch):
    from app import product_free_rag_demo as demo

    calls = []

    class FakeRuntime:
        def answer(self, question):
            calls.append(question)
            return {
                "response_mode": "abstain",
                "rendered_answer": "",
                "requirements": [],
                "candidates": [],
            }

    monkeypatch.setattr(demo, "_runtime", lambda pipeline: FakeRuntime())
    result = demo.answer_question(
        "다른 질문 알려줘",
        "legacy_experimental",
        {
            "pipeline": "product_free_rag_v1",
            "original_question": "디레지에 보상 알려줘",
            "options": [],
            "candidates": [],
        },
    )

    assert calls == ["다른 질문 알려줘"]
    assert result[4] is None


def test_product_verifier_drops_unsupported_language_and_downgrades_to_partial():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "최후의 과업 입장 명성은 108,921입니다.",
                "evidence_refs": ["E1"],
            },
            {
                "text": "디레지에 입장 명성은 제공된 정보에서 확인할 수 없습니다.",
                "evidence_refs": ["E3"],
            },
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="최후의 과업이랑 디레지에 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업", "디레지에"],
    )

    assert verified["mode"] == "partial"
    assert [claim["text"] for claim in verified["claims"]] == [
        "최후의 과업 입장 명성은 108,921입니다."
    ]
    assert verified["rejected_claims"][0]["reasons"] == [
        "unsupported_language_in_claim"
    ]


def test_product_verifier_rejects_not_specified_language():
    chunks, units = _fixture()
    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "구매 제한은 명시되지 않았습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="구매 제한을 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "unsupported_language_in_claim"
    ]


def test_product_verifier_rejects_value_copied_between_subjects():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "최후의 과업 입장 명성은 108,921입니다.",
                "evidence_refs": ["E1"],
            },
            {
                "text": "디레지에 입장 명성은 108,921입니다.",
                "evidence_refs": ["E1"],
            },
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="최후의 과업이랑 디레지에 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업", "디레지에"],
    )

    assert verified["mode"] == "partial"
    assert len(verified["claims"]) == 1
    assert verified["rejected_claims"][0]["reasons"] == [
        "claim_subject_not_bound_to_evidence"
    ]


def test_product_verifier_rejects_redundant_wrong_relation_for_same_subject():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "최후의 과업 입장 명성은 108,921입니다.",
                "evidence_refs": ["E1"],
            },
            {
                "text": "최후의 과업 입장 레벨은 115레벨 이상입니다.",
                "evidence_refs": ["E3"],
            },
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="최후의 과업이랑 디레지에 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업", "디레지에"],
    )

    assert verified["mode"] == "partial"
    assert [claim["text"] for claim in verified["claims"]] == [
        "최후의 과업 입장 명성은 108,921입니다."
    ]
    assert verified["rejected_claims"][0]["reasons"] == [
        "redundant_subject_evidence_misses_question_surface"
    ]


def test_product_verifier_rejects_invented_number():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "최후의 과업 입장 명성은 108,821입니다.",
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="최후의 과업 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업"],
    )

    assert verified["mode"] == "unsupported"
    assert verified["claims"] == []
    assert verified["rejected_claims"][0]["reasons"] == [
        "factual_values_not_in_evidence"
    ]


def test_product_verifier_rejects_numeric_answer_without_a_value():
    evidence = "모든 쿠폰은 계정당 1회 입력 가능합니다."
    chunks = {"coupon": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "coupon",
            "parent_document_id": "coupon-event",
            "title": "드로잉쇼 쿠폰",
            "context_text": "쿠폰 입력 안내",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "드로잉쇼 쿠폰:",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="드로잉쇼 쿠폰은 계정당 몇 번 입력할 수 있었어?",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "required_factual_value_missing"
    ]


def test_product_verifier_scopes_numeric_requirement_to_matching_clause():
    cases = [
        (
            "20주년 칭호·오라·크리쳐 변환서는 아이템별로 몇 번 쓸 수 "
            "있었고, 변환하면 어떤 부여 항목이 삭제됐어?",
            "칭호에 부여된 마법부여와 오라에 장착된 엠블렘은 변환 시 "
            "삭제됩니다.",
        ),
        (
            "별·성단·은하 조율자의 저울은 보상을 각각 몇 회 뽑고 어떤 "
            "서약 결정을 확정으로 줘?",
            "별을 품은 조율자의 저울은 확정 보상으로 유니크 서약 결정을 "
            "줍니다.",
        ),
        (
            "7월 16일 업데이트의 흑아 태초 추출서 가격은 얼마였고 변환 "
            "뒤 어떤 옵션이 유지됐어?",
            "변환 뒤 강화/증폭/마법부여 옵션이 유지됩니다.",
        ),
    ]

    for index, (question, claim_text) in enumerate(cases, 1):
        chunk_id = f"clause-{index}"
        chunks = {chunk_id: {"display_text": claim_text}}
        units = [
            {
                "evidence_ref": "E1",
                "chunk_id": chunk_id,
                "parent_document_id": chunk_id,
                "title": question,
                "context_text": "질문의 비숫자 절",
                "start_char": 0,
                "end_char": len(claim_text),
                "text": claim_text,
            }
        ]

        verified = verify_product_claim_output(
            {
                "mode": "partial",
                "claims": [
                    {
                        "text": claim_text,
                        "evidence_refs": ["E1"],
                    }
                ],
                "clarification": "",
            },
            question=question,
            evidence_units=units,
            chunks_by_id=chunks,
        )

        assert all(
            "required_factual_value_missing" not in rejection["reasons"]
            for rejection in verified["rejected_claims"]
        ), (index, verified)
        assert [claim["text"] for claim in verified["claims"]] == [claim_text]


def test_product_verifier_still_requires_value_for_numeric_clause_in_mixed_question():
    question = (
        "흑아 태초 추출서 가격은 얼마였고 변환 뒤 어떤 옵션이 유지됐어?"
    )
    claim_text = "흑아 태초 추출서 가격을 확인할 수 있습니다."
    chunks = {"price": {"display_text": claim_text}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "price",
            "parent_document_id": "price",
            "title": "흑아 태초 추출서",
            "context_text": "가격",
            "start_char": 0,
            "end_char": len(claim_text),
            "text": claim_text,
        }
    ]

    verified = verify_product_claim_output(
        {
            "mode": "partial",
            "claims": [
                {
                    "text": claim_text,
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=question,
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "required_factual_value_missing"
    ]


def test_product_verifier_rejects_unknown_evidence_ref():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "최후의 과업 입장 명성은 108,921입니다.",
                "evidence_refs": ["E99"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="최후의 과업 입장 명성 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["최후의 과업"],
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "evidence_ref_not_provided:E99"
    ]


def test_product_verifier_rejects_explicit_question_period_mismatch():
    evidence = "2026년 7월 아라드 패스 가격은 29,700세라입니다."
    chunks = {"monthly": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "monthly",
            "title": "2026년 7월 아라드 패스",
            "context_text": "판매 정보",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "complete": False,
        }
    ]
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "2026년 1월 아라드 패스 가격은 29,700세라입니다.",
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="2026년 1월 아라드 패스 가격 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["아라드 패스"],
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "explicit_question_condition_mismatch"
    ]


def test_product_verifier_accepts_question_date_inside_evidence_validity():
    evidence = "삭제일자는 2026년 7월 16일 06시입니다."
    chunks = {"historical": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "historical",
            "title": "마일리지샵 2026 시즌6",
            "context_text": "증폭 보호권",
            "valid_from": "2026-06-04",
            "valid_to": "2026-07-16",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "complete": False,
        }
    ]
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": (
                    "마일리지샵 시즌6 증폭 보호권 삭제 시점은 "
                    "2026년 7월 16일 06시입니다."
                ),
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="2026년 6월 10일 당시 삭제 시점은?",
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=[
            "마일리지샵 시즌6 증폭 보호권"
        ],
    )

    assert verified["mode"] == "answer"
    assert verified["rejected_claims"] == []


def test_product_verifier_accepts_korean_date_matching_slash_title():
    evidence = "기본 공격 및 전직 계열 스킬 공격력이 11.7% 증가합니다."
    chunks = {"balance": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "balance",
            "title": "7/16(목) 정기점검 업데이트 안내",
            "context_text": "스트라이커(남)",
            "published_at": "2026-07-15",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "complete": False,
        }
    ]
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": (
                    "2026년 7월 16일 스트라이커(남)의 "
                    "공격력 증가율은 11.7%입니다."
                ),
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question=(
            "2026년 7월 16일 스트라이커(남)의 "
            "공격력 증가율은?"
        ),
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["스트라이커(남)"],
    )

    assert verified["mode"] == "answer"
    assert verified["rejected_claims"] == []


def test_product_verifier_rejects_question_repeated_as_answer():
    chunks, units = _fixture()
    question = "이달의 아이템은 다음 달 상품도 자동 결제돼?"
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": question,
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question=question,
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "claim_repeats_question"
    ]


def test_product_verifier_rejects_adjacent_fact_for_missing_question_surface():
    evidence = "이달의 아이템은 상점 판매 후 재구입이 가능합니다."
    chunks = {"monthly": {"display_text": evidence}}
    units = [
        {
            "evidence_ref": "E1",
            "chunk_id": "monthly",
            "title": "7월 이달의 아이템",
            "context_text": "특별 아이템",
            "start_char": 0,
            "end_char": len(evidence),
            "text": evidence,
            "complete": False,
        }
    ]
    output = {
        "mode": "partial",
        "claims": [
            {
                "text": evidence,
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question=(
            "이달의 아이템은 한 번 구매하면 "
            "다음 달 상품도 자동 결제돼?"
        ),
        evidence_units=units,
        chunks_by_id=chunks,
        requested_subjects=["이달의 아이템"],
    )

    assert verified["mode"] == "unsupported"
    assert verified["rejected_claims"][0]["reasons"] == [
        "claim_does_not_address_question_surface"
    ]


def test_product_verifier_requires_complete_evidence_for_all_question():
    chunks, units = _fixture()
    output = {
        "mode": "answer",
        "claims": [
            {
                "text": "확인된 초월 종류는 장비 초월입니다.",
                "evidence_refs": ["E1"],
            }
        ],
        "clarification": "",
    }

    verified = verify_product_claim_output(
        output,
        question="초월 종류 전부 알려줘",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["mode"] == "partial"
    assert verified["verification"]["complete_evidence_required"] is True
    assert verified["verification"]["complete_evidence_present"] is False


def test_product_verifier_does_not_treat_one_kind_as_full_collection():
    verified = verify_product_claim_output(
        {
            "mode": "unsupported",
            "claims": [],
            "clarification": "",
        },
        question="선택한 한 종류의 엠블렘을 몇 개 받아?",
        evidence_units=[],
        chunks_by_id={},
    )

    assert verified["verification"]["complete_evidence_required"] is False


def test_product_evidence_pack_keeps_each_requirement_fact_with_exact_coordinates():
    final_text = (
        "<최후의 과업> 은 모든 요일에 입장 가능합니다.\n"
        "<최후의 과업> 채널은 모험가 명성 108,921부터 입장이 가능합니다."
    )
    diregie_text = (
        "'남아있는 작은 빛줄기' 퀘스트 클리어 시 "
        "<디레지에 레이드> 채널에 입장할 수 있습니다.\n"
        "- <디레지에 레이드> 채널은 명성 63,257 부터 입장이 가능합니다."
    )
    chunks = {
        "final": {
            "chunk_id": "final",
            "parent_document_id": "final_doc",
            "display_text": final_text,
            "heading_path": ["콘텐츠 입장"],
            "status": "current",
        },
        "diregie": {
            "chunk_id": "diregie",
            "parent_document_id": "diregie_doc",
            "display_text": diregie_text,
            "heading_path": ["콘텐츠 입장"],
            "status": "current",
        },
    }
    documents = {
        "final_doc": {
            "document_id": "final_doc",
            "source_id": "dnf_update",
            "title": "최후의 과업 업데이트",
            "status": "current",
        },
        "diregie_doc": {
            "document_id": "diregie_doc",
            "source_id": "dnf_game_guide",
            "title": "검은 질병의 디레지에 레이드",
            "status": "current",
        },
    }

    units = build_product_evidence_pack(
        ["final", "diregie"],
        question="최후의 과업이랑 디레지에 입장명성 알려줘",
        requirement_queries=[
            "최후의 과업 입장 명성",
            "디레지에 입장 명성",
        ],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=8,
    )

    assert len(units) <= 8
    assert any("108,921" in unit["text"] for unit in units)
    assert any("63,257" in unit["text"] for unit in units)
    assert [unit["evidence_ref"] for unit in units] == [
        f"E{index}" for index in range(1, len(units) + 1)
    ]
    for unit in units:
        source = chunks[unit["chunk_id"]]["display_text"]
        assert source[unit["start_char"] : unit["end_char"]] == unit["text"]


def test_atomic_product_pack_keeps_short_numbered_list_as_one_exact_unit():
    text = (
        "아래 사유에 해당하면 길드장 권한이 위임될 수 있습니다.\n"
        "① 길드장 계정이 이용제한 상태인 경우\n"
        "② 길드장 계정이 12개월 이상 미접속으로 휴면 상태인 경우"
    )
    chunks = {
        "policy": {
            "chunk_id": "policy",
            "parent_document_id": "policy-doc",
            "display_text": text,
            "heading_path": ["운영정책"],
            "status": "current",
        }
    }
    documents = {
        "policy-doc": {
            "document_id": "policy-doc",
            "source_id": "dnf_policy",
            "title": "던전앤파이터 운영정책",
            "status": "current",
        }
    }

    def score_pairs(pairs):
        return [
            0.99 if "①" in evidence and "②" in evidence else 0.1
            for _, evidence in pairs
        ]

    units = build_atomic_reranked_product_evidence_pack(
        ["policy"],
        question="길드장 권한 위임 조건을 알려줘",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        score_pairs=score_pairs,
        max_units=8,
        prefilter_per_query=32,
    )

    grouped = next(
        unit for unit in units if unit.get("unit_kind") == "numbered_list"
    )
    assert grouped["text"] == (
        "① 길드장 계정이 이용제한 상태인 경우\n"
        "② 길드장 계정이 12개월 이상 미접속으로 휴면 상태인 경우"
    )
    assert grouped["complete_list"] is True
    assert grouped["list_item_count"] == 2
    assert "길드장 권한이 위임" in grouped["context_text"]
    assert text[grouped["start_char"] : grouped["end_char"]] == grouped["text"]


def test_compact_pack_recovers_numbered_list_context_across_chunk_boundary():
    introduction = (
        "[3-3] 회사는 고객의 정상적인 활동이나 고객 간의 사적인 분쟁에 "
        "개입하지 않는 것을 원칙으로 합니다. 단, 아래와 같은 경우에는 "
        "해당 행위를 경고하거나 게임이용을 제한할 수 있습니다."
    )
    numbered_list = (
        "① 비인가 프로그램 사용 등 원활한 게임 진행에 부정적 영향을 "
        "준다고 판단될 경우\n"
        "② 불특정 다수의 고객에게 피해를 입히는 경우\n"
        "③ 게임 질서를 어지럽히거나 실정법을 위반한다고 판단될 경우"
    )
    chunks = {
        "previous": {
            "chunk_id": "previous",
            "parent_document_id": "policy-doc",
            "chunk_index": 2,
            "start_offset": 1500,
            "end_offset": 3259,
            "display_text": f"{introduction}\n{numbered_list}",
            "heading_path": ["운영정책"],
            "status": "expired",
        },
        "orphaned-list": {
            "chunk_id": "orphaned-list",
            "parent_document_id": "policy-doc",
            "chunk_index": 3,
            "start_offset": 3111,
            "end_offset": 4870,
            "display_text": f"{numbered_list}\n[3-4] 회사의 의무",
            "heading_path": ["운영정책"],
            "status": "expired",
        },
    }
    documents = {
        "policy-doc": {
            "document_id": "policy-doc",
            "source_id": "dnf_account_policy",
            "title": "던전앤파이터 운영정책 (2023-04-06 시행)",
            "status": "expired",
        }
    }

    units = build_compact_product_evidence_pack(
        ["orphaned-list"],
        question="회사가 사적인 분쟁에 개입할 수 있는 예외 조건은 뭐야?",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=8,
    )

    grouped = next(
        unit for unit in units if unit.get("unit_kind") == "numbered_list"
    )
    assert introduction in grouped["context_text"]
    assert grouped["chunk_id"] == "orphaned-list"
    source = chunks["orphaned-list"]["display_text"]
    assert source[grouped["start_char"] : grouped["end_char"]] == numbered_list


def test_product_evidence_pack_prioritizes_relation_rows_for_one_subject():
    target_text = (
        "[TABLE]\n"
        "| 아이템명 | 증폭 보호권 | 다른 상품 |\n"
        "| 가격 | 1500M | 350M |\n"
        "| 구매 제한 | 계정당 1회 | 무제한 |\n"
        "| 삭제일자 | 2026년 7월 16일 06시 | 같은 날 |\n"
        "[/TABLE]"
    )
    decoy_text = (
        "[TABLE]\n"
        "| 아이템명 | 다른 증폭서 |\n"
        "| 구매 제한 | 무제한 |\n"
        "[/TABLE]"
    )
    chunks = {
        "target": {
            "chunk_id": "target",
            "parent_document_id": "target_doc",
            "display_text": target_text,
            "heading_path": ["시즌6 판매 상품"],
            "status": "expired",
        },
        "decoy": {
            "chunk_id": "decoy",
            "parent_document_id": "decoy_doc",
            "display_text": decoy_text,
            "heading_path": ["다른 상점"],
            "status": "current",
        },
    }
    documents = {
        "target_doc": {
            "document_id": "target_doc",
            "source_id": "dnf_seria_shop",
            "title": "마일리지샵 2026 시즌6",
            "status": "expired",
        },
        "decoy_doc": {
            "document_id": "decoy_doc",
            "source_id": "dnf_seria_shop",
            "title": "다른 상점",
            "status": "current",
        },
    }
    requirements = [
        "마일리지샵 시즌6 증폭 보호권 가격",
        "마일리지샵 시즌6 증폭 보호권 구매 제한",
        "마일리지샵 시즌6 증폭 보호권 삭제 시점",
    ]

    units = build_product_evidence_pack(
        ["target", "decoy"],
        question="증폭 보호권의 가격, 구매 제한, 삭제 시점은?",
        requirement_queries=requirements,
        requested_subjects=["마일리지샵 시즌6 증폭 보호권"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=8,
    )

    assert len(units) <= 6
    assert "1500M" in units[0]["text"]
    assert "계정당 1회" in units[1]["text"]
    assert "2026년 7월 16일" in units[2]["text"]


def test_product_candidate_selection_caps_each_parent_at_two():
    ranked = [
        {
            "chunk_id": f"c{index}",
            "parent_document_id": "dominant" if index < 5 else f"d{index}",
            "reranker_score": 1.0 - (index / 100),
        }
        for index in range(10)
    ]

    selected = select_parent_diverse_candidates(
        ranked,
        depth=8,
        max_per_parent=2,
    )

    assert len(selected) == 7
    assert sum(
        row["parent_document_id"] == "dominant" for row in selected
    ) == 2


def test_product_candidate_flow_calls_generator_once_and_verifies_claims():
    chunks, _ = _fixture()
    chunks["final"].update(
        {
            "chunk_id": "final",
            "parent_document_id": "final_doc",
            "heading_path": ["콘텐츠 입장"],
            "status": "current",
        }
    )
    chunks["diregie"].update(
        {
            "chunk_id": "diregie",
            "parent_document_id": "diregie_doc",
            "heading_path": ["콘텐츠 입장"],
            "status": "current",
        }
    )
    documents = {
        "final_doc": {
            "document_id": "final_doc",
            "source_id": "dnf_update",
            "title": "최후의 과업 업데이트",
            "status": "current",
        },
        "diregie_doc": {
            "document_id": "diregie_doc",
            "source_id": "dnf_game_guide",
            "title": "검은 질병의 디레지에 레이드",
            "status": "current",
        },
    }
    calls = []

    def fake_generator(*, prompt, model, timeout_seconds):
        calls.append(prompt)
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": "최후의 과업 입장 명성은 108,921입니다.",
                        "evidence_refs": ["E1"],
                    },
                    {
                        "text": "디레지에 입장 명성은 63,257입니다.",
                        "evidence_refs": ["E2"],
                    },
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        }

    result = answer_product_rag_from_candidates(
        question="최후의 과업이랑 디레지에 입장명성 알려줘",
        requirement_queries=[
            "최후의 과업 입장 명성",
            "디레지에 입장 명성",
        ],
        requested_subjects=["최후의 과업", "디레지에"],
        selected=[
            {"chunk_id": "final", "parent_document_id": "final_doc"},
            {"chunk_id": "diregie", "parent_document_id": "diregie_doc"},
        ],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
    )

    assert len(calls) == 1
    assert result["mode"] == "answer"
    assert len(result["claims"]) == 2
    assert result["generation"]["usage"]["input_tokens"] == 10
    assert result["claims"][1]["citations"][0]["chunk_id"] == "diregie"


def test_product_search_policy_uses_only_explicit_question_date():
    historical = search_policy_for_product_question(
        "2025년 4월 26일 시행 정책의 제재를 알려줘",
        default_as_of="2026-07-16",
    )
    current = search_policy_for_product_question(
        "디레지에 입장 명성 알려줘",
        default_as_of="2026-07-16",
    )

    assert historical.as_of == "2025-04-26"
    assert historical.default_exposure_only is False
    assert historical.allowed_statuses is None
    assert current.as_of == "2026-07-16"
    assert current.default_exposure_only is True


def test_product_search_policy_resolves_completed_bare_month_to_archive():
    historical = search_policy_for_product_question(
        "7월 스페셜 클론 레어 아바타 상점 판매가 알려줘",
        default_as_of="2026-08-11",
    )
    current = search_policy_for_product_question(
        "8월 이달의 아이템 알려줘",
        default_as_of="2026-08-11",
    )

    assert historical.as_of is None
    assert historical.default_exposure_only is False
    assert historical.allowed_statuses is None
    assert current.as_of == "2026-08-11"
    assert current.default_exposure_only is True


def test_product_clarifies_retrieved_subject_identity_not_explicit_relation():
    selected = [{"parent_document_id": "diregie", "chunk_id": "chunk"}]
    chunks = {"chunk": {"heading_path": ["디레지에 레이드"]}}
    documents = {"diregie": {"title": "콘텐츠 가이드"}}

    assert clarification_for_subject_only_question(
        "디레지에 알려줘",
        requirement_queries=None,
        selected=selected,
        chunks_by_id=chunks,
        documents_by_id=documents,
    ) is not None
    assert clarification_for_subject_only_question(
        "디레지에 입장 명성 알려줘",
        requirement_queries=None,
        selected=selected,
        chunks_by_id=chunks,
        documents_by_id=documents,
    ) is None


def test_product_complete_tables_are_hidden_from_model_and_rendered_by_server():
    text = (
        "115Lv 장비 초월 비용은 아래와 같습니다.\n"
        "[TABLE]\n"
        "| 장비 종류 | 비용 |\n"
        "| 무기 | 1,000 |\n"
        "| 방어구 | 2,000 |\n"
        "[/TABLE]\n"
        "서약 결정 초월 비용은 아래와 같습니다.\n"
        "[TABLE]\n"
        "| 구분 | 비용 |\n"
        "| 유니크 | 3,000 |\n"
        "| 에픽 | 4,000 |\n"
        "[/TABLE]"
    )
    chunks = {
        "tables": {
            "chunk_id": "tables",
            "parent_document_id": "table_doc",
            "display_text": text,
            "heading_path": ["NPC 장비 초월", "비용"],
            "status": "current",
        }
    }
    documents = {
        "table_doc": {
            "document_id": "table_doc",
            "source_id": "dnf_game_guide",
            "title": "초월",
            "status": "current",
        }
    }
    question = "115Lv 장비 초월 비용표와 서약 결정 초월 비용표 전부 알려줘"
    requirements = [
        "115Lv 장비 초월 비용",
        "서약 결정 초월 비용",
    ]
    units = build_product_evidence_pack(
        ["tables"],
        question=question,
        requirement_queries=requirements,
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=8,
    )

    assert [unit["evidence_ref"] for unit in units] == ["T1", "T2"]
    assert all(unit["complete"] for unit in units)
    prompt = build_product_prompt(
        question=question,
        evidence_units=units,
    )
    assert "완전한 2행 표" in prompt
    assert "1,000" not in prompt
    assert "4,000" not in prompt

    comparison_prompt = build_product_prompt(
        question=question,
        evidence_units=units,
        require_distinct_comparison_rows=True,
    )
    assert "각 행은 항목명을 포함한 하나의 별도 claim" in comparison_prompt
    assert "두 값이 같아도 생략하지 말고" in comparison_prompt
    assert "질문하지 않은 다른 열의 값은 쓰지 마세요" in comparison_prompt
    assert "O/X/- 행은 각 축마다" in comparison_prompt
    assert "각 행 첫 열의 항목명을 그대로 포함하세요" in comparison_prompt
    assert "각 행은 항목명을 포함한 하나의 별도 claim" not in prompt

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": (
                            "115Lv 장비 초월 비용은 완전한 2행 표이고, "
                            "서약 결정 초월 비용도 완전한 2행 표입니다."
                        ),
                        "evidence_refs": ["T1", "T2"],
                    }
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        }

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=requirements,
        requested_subjects=["115Lv 장비 초월", "서약 결정 초월"],
        selected=[
            {
                "chunk_id": "tables",
                "parent_document_id": "table_doc",
            }
        ],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
    )

    assert result["mode"] == "answer"
    assert "| 무기 | 1,000 |" in result["rendered_answer"]
    assert "| 에픽 | 4,000 |" in result["rendered_answer"]


def test_compact_pack_keeps_both_quoted_parallel_tables():
    text = (
        "특별 보상\n"
        "[TABLE]\n"
        "| 칭호명 | 이달의 행운아 |\n"
        "| 거래타입 | 교환 불가 |\n"
        "| 기간 | 무제한 |\n"
        "[/TABLE]\n"
        "숨겨진 시험 - 운명의 선택을 받은 자\n"
        "[TABLE]\n"
        "| 칭호명 | 운명의 선택을 받은 자 |\n"
        "| 거래타입 | 교환 불가 |\n"
        "| 기간 | 무제한 |\n"
        "[/TABLE]"
    )
    chunks = {
        "tables": {
            "chunk_id": "tables",
            "parent_document_id": "event",
            "display_text": text,
            "heading_path": ["특별 보상"],
            "status": "expired",
        }
    }
    documents = {
        "event": {
            "document_id": "event",
            "source_id": "dnf_monthly_item",
            "title": "새해맞이 이달의 아이템 이벤트",
            "status": "expired",
        }
    }

    units = build_compact_product_evidence_pack(
        ["tables"],
        question=(
            "새해맞이 이벤트의 '이달의 행운아'와 "
            "'운명의 선택을 받은 자' 칭호 전체 표 두 개를 보여줘."
        ),
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert [unit["evidence_ref"] for unit in units] == ["T1", "T2"]
    assert "이달의 행운아" in units[0]["text"]
    assert "운명의 선택을 받은 자" in units[1]["text"]


def test_product_complete_numbered_list_is_rendered_exactly_by_server():
    list_text = (
        "① 길드장 계정이 이용제한 상태인 경우\n"
        "② 길드장 계정이 12개월 이상 미접속으로 휴면 상태인 경우"
    )
    chunks = {
        "policy": {
            "chunk_id": "policy",
            "parent_document_id": "policy-doc",
            "display_text": list_text,
        }
    }
    evidence_units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "policy",
            "parent_document_id": "policy-doc",
            "start_char": 0,
            "end_char": len(list_text),
            "text": list_text,
            "title": "던전앤파이터 운영정책",
            "context_text": "길드장 권한 위임 조건",
            "unit_kind": "numbered_list",
            "complete_list": True,
            "list_item_count": 2,
        }
    ]
    paraphrase = (
        "길드장 권한 위임 조건은 이용제한 상태이거나 "
        "12개월 이상 미접속으로 휴면 상태인 경우입니다."
    )

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {"text": paraphrase, "evidence_refs": ["E1"]}
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

    result = answer_product_rag_from_candidates(
        question="길드장 권한 위임 조건을 알려줘",
        requirement_queries=["길드장 권한 위임 조건"],
        requested_subjects=["길드장 권한"],
        selected=[
            {"chunk_id": "policy", "parent_document_id": "policy-doc"}
        ],
        chunks_by_id=chunks,
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=evidence_units,
    )

    assert result["mode"] == "answer"
    assert result["rendered_answer"] == list_text
    assert paraphrase not in result["rendered_answer"]


def test_product_single_list_item_request_keeps_model_claim():
    list_text = (
        "① 길드장 계정이 이용제한 상태인 경우\n"
        "② 길드장 계정이 12개월 이상 미접속으로 휴면 상태인 경우"
    )
    chunks = {
        "policy": {
            "chunk_id": "policy",
            "parent_document_id": "policy-doc",
            "display_text": list_text,
        }
    }
    evidence_units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "policy",
            "parent_document_id": "policy-doc",
            "start_char": 0,
            "end_char": len(list_text),
            "text": list_text,
            "title": "던전앤파이터 운영정책",
            "context_text": "길드장 권한 위임 조건",
            "unit_kind": "numbered_list",
            "complete_list": True,
            "list_item_count": 2,
        }
    ]
    one_item = "길드장 권한 위임 조건 한 가지는 이용제한 상태인 경우입니다."

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [{"text": one_item, "evidence_refs": ["E1"]}],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

    result = answer_product_rag_from_candidates(
        question="길드장 권한 위임 조건 한 가지만 알려줘",
        requirement_queries=["길드장 권한 위임 조건 한 가지"],
        requested_subjects=["길드장 권한"],
        selected=[
            {"chunk_id": "policy", "parent_document_id": "policy-doc"}
        ],
        chunks_by_id=chunks,
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=evidence_units,
    )

    assert result["mode"] == "answer"
    assert result["rendered_answer"] == one_item
    assert "②" not in result["rendered_answer"]


def test_existing32_score_adapter_requires_mode_and_supported_value():
    text = "입장 명성은 108,921입니다."
    sealed = {
        "slot_ordinal": 1,
        "candidate_id": "case-1",
        "question_text": "입장 명성은?",
        "as_of": "2026-07-31",
        "expected_response_mode": "full_answer",
        "requirements": [
            {
                "requirement_id": "entry_fame",
                "expected_status": "supported",
                "value_type": "number",
                "required_values": [108921],
                "relation": "entry_fame",
                "acceptable_evidence_units": [
                    {
                        "chunk_id": "chunk-1",
                        "start_char": 0,
                        "end_char": len(text),
                        "text": text,
                    }
                ],
            }
        ],
    }
    result = {
        "mode": "answer",
        "rendered_answer": text,
        "claims": [
            {
                "text": text,
                "citations": [
                    {
                        "chunk_id": "chunk-1",
                        "start_char": 0,
                        "end_char": len(text),
                        "text": text,
                    }
                ],
            }
        ],
        "candidates": [{"chunk_id": "chunk-1"}],
        "verification": {"all_exposed_citations_verified": True},
    }

    scored = score_case(
        sealed,
        result,
        chunks_by_id={"chunk-1": {"display_text": text}},
    )

    assert scored["meaning_complete"] is True
    assert scored["retrieval_all_supported_visible"] is True
    assert scored["all_exposed_citations_exact"] is True


def test_existing32_score_adapter_marks_partial_answer_as_false_full_candidate():
    sealed = {
        "slot_ordinal": 4,
        "candidate_id": "case-4",
        "question_text": "가능 여부와 운영시간은?",
        "as_of": "2026-07-31",
        "expected_response_mode": "partial_answer",
        "requirements": [
            {
                "requirement_id": "visit_available",
                "expected_status": "supported",
                "value_type": "boolean",
                "required_values": [False],
                "relation": "visit_available",
                "acceptable_evidence_units": [],
            },
            {
                "requirement_id": "telephone_hours",
                "expected_status": "unsupported",
                "value_type": "text",
                "required_values": [],
                "relation": "telephone_hours",
                "acceptable_evidence_units": [],
            },
        ],
    }
    result = {
        "mode": "answer",
        "rendered_answer": "방문 상담은 이용할 수 없습니다.",
        "claims": [],
        "candidates": [],
        "verification": {"all_exposed_citations_verified": True},
    }

    scored = score_case(sealed, result, chunks_by_id={})

    assert scored["meaning_complete"] is False
    assert scored["false_full_candidate"] is True


def test_product_pack_honors_explicit_max_units():
    text = "\n".join(
        [
            "대상 입장 명성은 100입니다.",
            "대상 주간 입장 제한은 1회입니다.",
            "대상 보상 횟수는 2회입니다.",
            "대상 삭제 시각은 오전 6시입니다.",
        ]
    )
    chunks = {
        "chunk": {
            "chunk_id": "chunk",
            "parent_document_id": "document",
            "display_text": text,
            "heading_path": ["대상 안내"],
            "status": "current",
        }
    }
    documents = {
        "document": {
            "document_id": "document",
            "source_id": "dnf_update",
            "title": "대상 안내",
            "status": "current",
        }
    }
    question = "대상 입장 명성과 주간 입장 제한, 보상 횟수, 삭제 시각 알려줘"
    baseline = build_product_evidence_pack(
        ["chunk"],
        question=question,
        requirement_queries=None,
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=8,
    )

    filled = fill_question_only_pack(
        baseline,
        candidate_chunk_ids=["chunk"],
        question=question,
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=4,
    )

    assert len(baseline) == 4
    assert len(filled) == 4
    assert [unit["text"] for unit in filled] == [
        unit["text"] for unit in baseline
    ]
    assert len({unit["text"] for unit in filled}) == 4


def test_answer_from_candidates_accepts_diagnostic_evidence_override():
    text = "대상 입장 명성은 108,921입니다."
    chunks = {"chunk": {"display_text": text}}
    override = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "chunk",
            "title": "대상",
            "context_text": "입장 조건",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
        }
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        assert "108,921" in prompt
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": text,
                        "evidence_refs": ["E1"],
                    },
                    {
                        "text": text,
                        "evidence_refs": ["E1"],
                    },
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        }

    result = answer_product_rag_from_candidates(
        question="대상 입장 명성은?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": "chunk",
                "parent_document_id": "document",
            }
        ],
        chunks_by_id=chunks,
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=override,
    )

    assert result["mode"] == "answer"
    assert result["evidence_unit_count"] == 1
    assert len(result["claims"]) == 1
    assert result["rendered_answer"] == text
    assert len(result["raw_model_output"]["claims"]) == 2
    assert result["evidence_pack"] == [
        {
            "ref": "E1",
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "chunk",
            "parent_document_id": "",
            "source_id": None,
            "title": "대상",
            "heading_path": [],
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "revision_id": None,
            "status": None,
            "start_offset": 0,
            "end_offset": len(text),
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "context_text": "입장 조건",
            "question_focus": "",
            "question_relevance_score": None,
            "unit_kind": "",
            "complete": False,
            "complete_list": False,
        }
    ]
    resolvable_refs = {unit["ref"] for unit in result["evidence_pack"]}
    assert {
        ref
        for claim in [*result["claims"], *result["rejected_claims"]]
        for ref in claim["evidence_refs"]
    } <= resolvable_refs


def test_answer_from_candidates_blocks_claims_from_low_relevance_pool():
    text = "이달의 아이템은 상점 판매 후 재구입이 가능합니다."
    chunks = {"chunk": {"display_text": text}}
    override = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "chunk",
            "title": "이달의 아이템",
            "context_text": "",
            "start_char": 0,
            "end_char": len(text),
            "text": text,
            "complete": False,
            "question_relevance_score": 0.01,
        }
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": "다음 달 상품도 자동 결제됩니다.",
                        "evidence_refs": ["E1"],
                    }
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {},
        }

    result = answer_product_rag_from_candidates(
        question="한 번 구매하면 다음 달 상품도 자동 결제돼?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": "chunk",
                "parent_document_id": "document",
                "reranker_score": 0.01,
            }
        ],
        chunks_by_id=chunks,
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=override,
    )

    assert result["mode"] == "unsupported"
    assert result["claims"] == []
    assert result["rejected_claims"][0]["reasons"] == [
        "evidence_relevance_below_threshold"
    ]


def test_answer_from_candidates_keeps_direct_atomic_evidence_from_low_pool():
    direct = (
        "장비 초월에는 초월하는 장비 아이템에 따라 "
        "소울류 아이템과 다른 재료 아이템이 사용됩니다."
    )
    adjacent = (
        "솔리드 소울 레시피 사용 시 레전더리 소울 2개와 "
        "50,000 골드가 소모됩니다."
    )
    chunks = {
        "direct": {"display_text": direct},
        "adjacent": {"display_text": adjacent},
    }
    override = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "direct",
            "title": "초월",
            "context_text": "장비 초월",
            "start_char": 0,
            "end_char": len(direct),
            "text": direct,
            "complete": False,
            "question_relevance_score": 0.91,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "adjacent",
            "title": "최후의 과업",
            "context_text": "솔리드 소울 레시피",
            "start_char": 0,
            "end_char": len(adjacent),
            "text": adjacent,
            "complete": False,
            "question_relevance_score": 0.02,
        },
    ]

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {"text": direct, "evidence_refs": ["E1"]},
                    {"text": adjacent, "evidence_refs": ["E2"]},
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {},
        }

    result = answer_product_rag_from_candidates(
        question="초월에 소모하는 재료 알려줘.",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {
                "chunk_id": "direct",
                "parent_document_id": "transcendence",
                "reranker_score": 0.081,
            },
            {
                "chunk_id": "adjacent",
                "parent_document_id": "final-task",
                "reranker_score": 0.03,
            },
        ],
        chunks_by_id=chunks,
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=override,
    )

    assert result["mode"] == "answer"
    assert [claim["text"] for claim in result["claims"]] == [direct]
    assert result["rejected_claims"][0]["reasons"] == [
        "evidence_relevance_below_threshold"
    ]


def test_surface_requirement_queries_split_only_explicit_surface_conjunctions():
    queries = surface_requirement_queries(
        "그래플러(남)와 넨마스터(여)의 증가율, 적용 날짜를 알려줘"
    )

    assert queries[0].startswith("그래플러(남)와")
    assert "그래플러(남) 증가율" in queries
    assert "넨마스터(여)의 증가율" in queries
    assert "적용 날짜를 알려줘" in queries


def test_surface_requirement_queries_keep_separate_question_sentences():
    queries = surface_requirement_queries(
        "모바일 경매장에서 직접 거래할 수 있어? "
        "직접 거래가 안 된다면 어떤 정보를 확인할 수 있어?"
    )

    assert any(
        query == "모바일 경매장에서 직접 거래할 수 있어"
        for query in queries
    )
    assert any(
        query == "직접 거래가 안 된다면 어떤 정보를 확인할 수 있어"
        for query in queries
    )


def test_surface_requirement_queries_split_quoted_parallel_table_names():
    question = (
        "새해맞이 이벤트의 '이달의 행운아'와 "
        "'운명의 선택을 받은 자' 칭호 전체 표 두 개를 보여줘."
    )

    queries = surface_requirement_queries(question)

    assert any("이달의 행운아" in query for query in queries[1:])
    assert any("운명의 선택을 받은 자" in query for query in queries[1:])


def test_product_question_requirements_label_only_surface_clauses():
    requirements = build_product_question_requirements(
        "데일리샷 제휴 특별 패키지의 출시 시각과 "
        "특별 할인 쿠폰 금액을 알려줘."
    )

    assert requirements == [
        {
            "question_ref": "Q1",
            "text": "데일리샷 제휴 특별 패키지의 출시 시각",
        },
        {
            "question_ref": "Q2",
            "text": "특별 할인 쿠폰 금액을 알려줘",
        },
    ]


def test_product_question_requirements_use_kiwi_for_independent_clauses():
    requirements = build_product_question_requirements(
        "구성품은 무엇을 주고 판매 종료 후 삭제되는지 알려줘."
    )

    assert requirements == [
        {"question_ref": "Q1", "text": "구성품 무엇을 주는지"},
        {
            "question_ref": "Q2",
            "text": "구성품 판매 종료 후 삭제되는지 알려줘",
        },
    ]


def test_product_coverage_contract_derives_partial_and_calls_qwen_once():
    question = (
        "데일리샷 제휴 특별 패키지의 출시 시각과 "
        "특별 할인 쿠폰 금액을 알려줘."
    )
    launch = (
        "'데일리샷' 제휴 특별 패키지 출시 일자는 "
        "8월 14일 10:00시 입니다."
    )
    unrelated = (
        "데일리샷 신규 회원 가입 시 현금처럼 사용 가능한 "
        "3,000 포인트를 제공합니다."
    )
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "launch",
            "parent_document_id": "dailyshot",
            "title": "데일리샷 제휴 특별 패키지",
            "context_text": "출시 안내",
            "start_char": 0,
            "end_char": len(launch),
            "text": launch,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "benefit",
            "parent_document_id": "dailyshot",
            "title": "데일리샷 신규 회원 혜택",
            "context_text": "가입 혜택",
            "start_char": 0,
            "end_char": len(unrelated),
            "text": unrelated,
            "complete": False,
        },
    ]
    calls = []

    def fake_generator(*, prompt, model, timeout_seconds):
        calls.append(prompt)
        return {
            "output": {
                "claims": [
                    {
                        "question_ref": "Q1",
                        "text": "출시 시각은 8월 14일 10:00시입니다.",
                        "evidence_refs": ["E1"],
                    },
                    {
                        "question_ref": "Q2",
                        "text": "특별 할인 쿠폰 금액을 알려줘",
                        "evidence_refs": ["E2"],
                    },
                ],
                "unsupported_question_refs": [],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {},
        }

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {"chunk_id": "launch", "parent_document_id": "dailyshot"},
            {"chunk_id": "benefit", "parent_document_id": "dailyshot"},
        ],
        chunks_by_id={
            "launch": {"display_text": launch},
            "benefit": {"display_text": unrelated},
        },
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=units,
        use_question_coverage_contract=True,
    )

    assert len(calls) == 1
    assert '"question_ref": "Q1"' in calls[0]
    assert '"question_ref": "Q2"' in calls[0]
    assert result["mode"] == "partial"
    assert len(result["claims"]) == 1
    coverage = result["verification"]["question_coverage_contract"]
    assert coverage["contract_valid"] is True
    assert coverage["accepted_question_refs"] == ["Q1"]
    assert coverage["server_unsupported_question_refs"] == ["Q2"]
    assert result["verification"]["per_question_ref_checks"] == [
        {"question_ref": "Q1", "accepted": True, "reasons": []},
        {
            "question_ref": "Q2",
            "accepted": False,
            "reasons": ["claim_repeats_question"],
        },
    ]


def test_product_coverage_contract_derives_answer_for_two_supported_clauses():
    question = (
        "판매 기간은 언제부터 언제까지였고 "
        "판매 종료 후 삭제됐는지 알려줘."
    )
    evidence = (
        "판매 기간은 2025년 1월 1일부터 2025년 1월 31일까지이며, "
        "판매 종료 후 삭제됩니다."
    )
    unit = {
        "evidence_ref": "E1",
        "candidate_ref": "1",
        "chunk_id": "sale",
        "parent_document_id": "sale-doc",
        "title": "판매 안내",
        "context_text": "판매 기간 및 삭제",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "complete": False,
    }

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "claims": [
                    {
                        "question_ref": "Q1",
                        "text": (
                            "판매 기간은 2025년 1월 1일부터 "
                            "2025년 1월 31일까지입니다."
                        ),
                        "evidence_refs": ["E1"],
                    },
                    {
                        "question_ref": "Q2",
                        "text": "판매 종료 후 삭제됩니다.",
                        "evidence_refs": ["E1"],
                    },
                ],
                "unsupported_question_refs": [],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {},
        }

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=None,
        requested_subjects=None,
        selected=[{"chunk_id": "sale", "parent_document_id": "sale-doc"}],
        chunks_by_id={"sale": {"display_text": evidence}},
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=[unit],
        use_question_coverage_contract=True,
    )

    assert result["mode"] == "answer"
    coverage = result["verification"]["question_coverage_contract"]
    assert coverage["accepted_question_refs"] == ["Q1", "Q2"]
    assert coverage["server_unsupported_question_refs"] == []


def test_product_coverage_contract_safely_rejects_missing_question_ref():
    question = "출시 시각과 할인 금액을 알려줘."
    evidence = "출시 시각은 10:00시입니다."

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "claims": [
                    {
                        "question_ref": "Q1",
                        "text": "출시 시각은 10:00시입니다.",
                        "evidence_refs": ["E1"],
                    }
                ],
                "unsupported_question_refs": [],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=None,
        requested_subjects=None,
        selected=[{"chunk_id": "launch", "parent_document_id": "doc"}],
        chunks_by_id={"launch": {"display_text": evidence}},
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=[
            {
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "launch",
                "parent_document_id": "doc",
                "title": "출시 안내",
                "context_text": "출시 시각",
                "start_char": 0,
                "end_char": len(evidence),
                "text": evidence,
                "complete": False,
            }
        ],
        use_question_coverage_contract=True,
    )

    assert result["mode"] == "unsupported"
    coverage = result["verification"]["question_coverage_contract"]
    assert coverage["contract_valid"] is False
    assert "question_refs_not_exhaustive" in coverage["issues"]


def test_coverage_lexical_overlap_flags_slot12_q2_privacy_consent():
    evidence = (
        "이벤트와 관련된 개인정보 수집 및 이용 동의, "
        "동의 거절 시 사전예약이 불가합니다."
    )

    diagnostic = build_product_coverage_lexical_overlap_diagnostic(
        question_ref="Q2",
        question_text="정확한 연령 확인 절차를 알려줘",
        evidence_refs=["E5"],
        evidence_units=[{"evidence_ref": "E5", "text": evidence}],
    )

    assert diagnostic["union_matched_tokens"] == []
    assert diagnostic["union_ratio"] == 0.0
    assert diagnostic["zero_overlap_signal"] is True


def test_coverage_lexical_overlap_flags_slot4_q2_signup_points():
    evidence = (
        "데일리샷 신규 회원 가입 시 현금처럼 사용 가능한 "
        "3,000 포인트를 제공합니다."
    )

    diagnostic = build_product_coverage_lexical_overlap_diagnostic(
        question_ref="Q2",
        question_text="특별 할인 쿠폰 금액을 알려줘",
        evidence_refs=["E1"],
        evidence_units=[{"evidence_ref": "E1", "text": evidence}],
    )

    assert diagnostic["union_matched_tokens"] == []
    assert diagnostic["union_ratio"] == 0.0
    assert diagnostic["zero_overlap_signal"] is True


def test_coverage_lexical_overlap_keeps_slot12_q1_supported_signal():
    evidence = "- 단, 14세 미만 계정은 참여할 수 없습니다."

    diagnostic = build_product_coverage_lexical_overlap_diagnostic(
        question_ref="Q1",
        question_text=(
            "인파이터(여)·제국기사 사전예약에 14세 미만 계정이 "
            "참여할 수 있었는지"
        ),
        evidence_refs=["E1"],
        evidence_units=[{"evidence_ref": "E1", "text": evidence}],
    )

    assert round(diagnostic["union_ratio"], 2) == 0.43
    assert diagnostic["zero_overlap_signal"] is False


def test_coverage_lexical_overlap_reproduces_slot27_counterexample():
    question_text = (
        "2026 아라드 패스 차원의 별자리 아바타 콤보 상자는 "
        "언제 판매됐는지"
    )
    sale_evidence = (
        "2026 년 01 월 15 일 점검 후부터 "
        "2026 년 03 월 26일 점검 전까지"
    )
    deletion_evidence = (
        "2026 아라드 패스 차원의 별자리 아바타 콤보 상자 및 "
        "구성 품은 2026년 03월 26일 06시 일괄 삭제됩니다."
    )

    sale = build_product_coverage_lexical_overlap_diagnostic(
        question_ref="Q1",
        question_text=question_text,
        evidence_refs=["E1"],
        evidence_units=[{"evidence_ref": "E1", "text": sale_evidence}],
    )
    deletion = build_product_coverage_lexical_overlap_diagnostic(
        question_ref="Q1",
        question_text=question_text,
        evidence_refs=["E2"],
        evidence_units=[
            {"evidence_ref": "E2", "text": deletion_evidence}
        ],
    )

    assert round(sale["union_ratio"], 2) == 0.11
    assert round(deletion["union_ratio"], 2) == 0.78
    assert sale["union_ratio"] < deletion["union_ratio"]


def test_coverage_lexical_overlap_records_each_ref_and_union():
    diagnostic = build_product_coverage_lexical_overlap_diagnostic(
        question_ref="Q2",
        question_text="특별 쿠폰 금액을 알려줘",
        evidence_refs=["E1", "E2"],
        evidence_units=[
            {"evidence_ref": "E1", "text": "특별 쿠폰 지급 안내입니다."},
            {"evidence_ref": "E2", "text": "쿠폰 금액을 안내합니다."},
        ],
    )

    assert [
        item["evidence_ref"] for item in diagnostic["evidence_overlap"]
    ] == ["E1", "E2"]
    assert diagnostic["evidence_overlap"][0]["matched_tokens"] == [
        "쿠폰",
        "특별",
    ]
    assert diagnostic["evidence_overlap"][1]["matched_tokens"] == [
        "금액을",
        "쿠폰",
    ]
    assert set(diagnostic["union_matched_tokens"]) == {
        "특별",
        "쿠폰",
        "금액을",
    }
    assert diagnostic["union_ratio"] == 1.0
    assert diagnostic["zero_overlap_signal"] is False


def test_coverage_lexical_overlap_shadow_does_not_block_zero_overlap_claim():
    question = "특별 할인 쿠폰 금액을 알려줘."
    evidence = (
        "데일리샷 신규 회원 가입 시 현금처럼 사용 가능한 "
        "3,000 포인트를 제공합니다."
    )
    unit = {
        "evidence_ref": "E1",
        "candidate_ref": "1",
        "chunk_id": "benefit",
        "parent_document_id": "dailyshot",
        "title": "데일리샷 신규 회원 혜택",
        "context_text": "가입 혜택",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "complete": False,
    }

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "claims": [
                    {
                        "question_ref": "Q1",
                        "text": "특별 할인 쿠폰 금액은 3,000 포인트입니다.",
                        "evidence_refs": ["E1"],
                    }
                ],
                "unsupported_question_refs": [],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {"chunk_id": "benefit", "parent_document_id": "dailyshot"}
        ],
        chunks_by_id={"benefit": {"display_text": evidence}},
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=[unit],
        use_question_coverage_contract=True,
    )

    assert result["mode"] == "answer"
    assert len(result["claims"]) == 1
    lexical = result["verification"][
        "question_coverage_lexical_overlap"
    ]
    assert lexical["diagnostic_only"] is True
    assert lexical["affects_claim_acceptance"] is False
    assert lexical["affects_evidence_selection"] is False
    assert lexical["zero_overlap_question_refs"] == ["Q1"]
    assert lexical["latency_ms"] >= 0.0


def test_default_product_path_does_not_run_coverage_lexical_overlap():
    question = "출시 시각은 언제야?"
    evidence = "출시 시각은 10:00시입니다."

    def fake_generator(*, prompt, model, timeout_seconds):
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": "출시 시각은 10:00시입니다.",
                        "evidence_refs": ["E1"],
                    }
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
        }

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=None,
        requested_subjects=None,
        selected=[{"chunk_id": "launch", "parent_document_id": "doc"}],
        chunks_by_id={"launch": {"display_text": evidence}},
        documents_by_id={},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=[
            {
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "launch",
                "parent_document_id": "doc",
                "title": "출시 안내",
                "context_text": "출시 시각",
                "start_char": 0,
                "end_char": len(evidence),
                "text": evidence,
                "complete": False,
            }
        ],
        use_question_coverage_contract=False,
    )

    assert "question_coverage_lexical_overlap" not in result["verification"]


def test_server_availability_rendering_skips_qwen_and_restores_citation():
    question = "임의 레이드 하드와 일반의 보상 차이 알려줘."
    evidence = "| 원석 | 하드: O | 일반: - |"
    unit = {
        "evidence_ref": "E1",
        "candidate_ref": "1",
        "chunk_id": "reward",
        "parent_document_id": "raid",
        "title": "임의 레이드",
        "context_text": "보상 표",
        "start_char": 0,
        "end_char": len(evidence),
        "text": evidence,
        "unit_kind": "table_row",
        "complete": False,
        "availability_subject": "원석",
        "availability_values": {"하드": True, "일반": False},
    }

    def fail_generator(**kwargs):
        raise AssertionError(f"Qwen must not run: {kwargs}")

    result = answer_product_rag_from_candidates(
        question=question,
        requirement_queries=None,
        requested_subjects=None,
        selected=[{"chunk_id": "reward", "parent_document_id": "raid"}],
        chunks_by_id={"reward": {"display_text": evidence}},
        documents_by_id={"raid": {"title": "임의 레이드"}},
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fail_generator,
        evidence_units_override=[unit],
        enable_availability_comparison=True,
        use_server_availability_rendering=True,
    )

    assert result["mode"] == "answer"
    assert result["generation"] is None
    assert result["server_rendering"] == {
        "used": True,
        "renderer": "availability_comparison_v1",
        "claim_count": 1,
    }
    assert result["claims"][0]["text"] == (
        "원석: 하드 획득 가능, 일반 획득 불가."
    )
    citation = result["claims"][0]["citations"][0]
    assert citation["evidence_ref"] == "E1"
    assert citation["chunk_id"] == "reward"
    assert citation["start_char"] == 0
    assert citation["end_char"] == len(evidence)
    assert citation["text"] == evidence


def test_surface_requirement_queries_keep_relation_coordination_separate():
    question = (
        "2026년 1월 아라드 패스 2026 시즌1 보상 상자의 "
        "판매 기간과 일괄 삭제 시각은 언제였어?"
    )

    queries = surface_requirement_queries(question)

    assert any(query.endswith("보상 상자의 판매 기간") for query in queries)
    assert any("보상 상자 일괄 삭제 시각" in query for query in queries)
    assert all("판매 기간 삭제 시각" not in query for query in queries)


def test_surface_requirement_queries_split_kiwi_independent_verb_clauses():
    question = (
        "2026 아라드 패스 차원의 별자리 아바타 콤보 상자는 "
        "언제 판매됐고 언제 일괄 삭제됐어?"
    )

    clauses = explicit_question_clauses(question)
    queries = surface_requirement_queries(question)

    assert len(clauses) == 2
    assert "언제 판매됐" in clauses[0]
    assert "언제 일괄 삭제됐어" in clauses[1]
    assert any(
        "차원의 별자리 아바타 콤보 상자" in query
        and "언제 판매됐" in query
        and "일괄 삭제" not in query
        for query in queries[1:]
    )
    assert any(
        "차원의 별자리 아바타 콤보 상자" in query
        and "언제 일괄 삭제됐어" in query
        for query in queries[1:]
    )


def test_kiwi_requirement_queries_complete_open_verb_stems():
    sale_queries = kiwi_independent_requirement_queries(
        "아바타 콤보 상자는 언제 판매됐고 언제 삭제됐어?"
    )
    contents_queries = kiwi_independent_requirement_queries(
        "해방의 열쇠 상자는 무엇을 주고 언제 삭제됐어?"
    )

    assert sale_queries[0].endswith("언제 판매됐는지")
    assert contents_queries[0].endswith("무엇을 주는지")


def test_product_retrieval_unions_kiwi_independent_clause_queries(monkeypatch):
    question = (
        "2026 아라드 패스 차원의 별자리 아바타 콤보 상자는 "
        "언제 판매됐고 언제 일괄 삭제됐어?"
    )
    searched_queries = []
    artifacts = SimpleNamespace(chunks_by_id={}, documents_by_id={})

    def fake_retrieve_with_embedding(
        query,
        embedding,
        loaded_artifacts,
        *,
        top_k,
        policy,
    ):
        index = len(searched_queries)
        chunk_id = f"chunk-{index}"
        artifacts.chunks_by_id[chunk_id] = {"retrieval_text": query}
        searched_queries.append(query)
        return [
            {
                "chunk_id": chunk_id,
                "parent_document_id": f"parent-{index}",
                "rank": 1,
            }
        ]

    monkeypatch.setattr(
        "src.v3.retrieve_v3.retrieve_with_embedding",
        fake_retrieve_with_embedding,
    )
    rag = ProductFreeRAG.__new__(ProductFreeRAG)
    rag._artifacts = artifacts
    rag.use_identity_shortlist = False
    rag._encode_queries = lambda queries: [None] * len(queries)
    rag._score_pairs = lambda pairs: [1.0] * len(pairs)
    rag.record_cuda_memory_diagnostic = lambda *args, **kwargs: None

    rag.retrieve(question, default_as_of="2026-07-31")

    assert searched_queries == [
        question,
        (
            "2026 아라드 패스 차원의 별자리 아바타 콤보 상자 "
            "언제 판매됐는지"
        ),
        (
            "2026 아라드 패스 차원의 별자리 아바타 콤보 상자 "
            "언제 일괄 삭제됐어"
        ),
    ]


def test_product_retrieval_keeps_one_query_without_kiwi_clause(monkeypatch):
    searched_queries = []
    artifacts = SimpleNamespace(chunks_by_id={}, documents_by_id={})

    def fake_retrieve_with_embedding(
        query,
        embedding,
        loaded_artifacts,
        *,
        top_k,
        policy,
    ):
        chunk_id = "single"
        artifacts.chunks_by_id[chunk_id] = {"retrieval_text": query}
        searched_queries.append(query)
        return [
            {
                "chunk_id": chunk_id,
                "parent_document_id": "single-parent",
                "rank": 1,
            }
        ]

    monkeypatch.setattr(
        "src.v3.retrieve_v3.retrieve_with_embedding",
        fake_retrieve_with_embedding,
    )
    rag = ProductFreeRAG.__new__(ProductFreeRAG)
    rag._artifacts = artifacts
    rag.use_identity_shortlist = False
    rag._encode_queries = lambda queries: [None] * len(queries)
    rag._score_pairs = lambda pairs: [1.0] * len(pairs)
    rag.record_cuda_memory_diagnostic = lambda *args, **kwargs: None

    rag.retrieve("디레지에 입장 명성 알려줘", default_as_of="2026-07-31")

    assert searched_queries == ["디레지에 입장 명성 알려줘"]


def test_product_retrieval_expands_release_date_relation_without_domain_alias():
    variants = product_retrieval_query_variants(
        "미카엘라 레이드는 언제 출시했어?"
    )

    assert len(variants) == 1
    assert "미카엘라 레이드" in variants[0]
    assert "업데이트 되는 내용" in variants[0]
    assert "출시" not in variants[0]
    assert product_retrieval_query_variants(
        "미카엘라 레이드 보상 알려줘"
    ) == []
    assert normalize_product_question(
        "축성 방어구 제작 제료 알려줘"
    ) == "축성 방어구 제작 재료 알려줘"
    assert product_retrieval_query_variants(
        "축성 방어구 제작 제료 알려줘"
    ) == []
    assert product_retrieval_query_variants(
        "축성 방어구 제작 재료 알려줘"
    ) == []


def test_product_retrieval_uses_release_date_variant_for_search_and_reranking(
    monkeypatch,
):
    searched_queries = []
    reranker_pairs = []
    artifacts = SimpleNamespace(chunks_by_id={}, documents_by_id={})

    def fake_retrieve_with_embedding(
        query,
        embedding,
        loaded_artifacts,
        *,
        top_k,
        policy,
    ):
        chunk_id = "release"
        artifacts.chunks_by_id[chunk_id] = {
            "retrieval_text": "미카엘라 레이드 8월 6일 업데이트"
        }
        searched_queries.append(query)
        return [
            {
                "chunk_id": chunk_id,
                "parent_document_id": "release-parent",
                "rank": 1,
            }
        ]

    def fake_score_pairs(pairs):
        reranker_pairs.extend(pairs)
        return [1.0] * len(pairs)

    monkeypatch.setattr(
        "src.v3.retrieve_v3.retrieve_with_embedding",
        fake_retrieve_with_embedding,
    )
    rag = ProductFreeRAG.__new__(ProductFreeRAG)
    rag._artifacts = artifacts
    rag.use_identity_shortlist = False
    rag._encode_queries = lambda queries: [None] * len(queries)
    rag._score_pairs = fake_score_pairs
    rag.record_cuda_memory_diagnostic = lambda *args, **kwargs: None

    rag.retrieve("미카엘라 레이드는 언제 출시했어?", default_as_of="2026-08-11")

    assert searched_queries[0] == "미카엘라 레이드는 언제 출시했어?"
    assert "미카엘라 레이드는 업데이트 되는 내용?" in searched_queries
    assert [pair[0] for pair in reranker_pairs] == [
        "미카엘라 레이드는 언제 출시했어?",
        "미카엘라 레이드는 업데이트 되는 내용?",
    ]


def test_release_date_claim_rejects_event_window_without_release_relation():
    evidence = (
        "미카엘라 레이드 하드 난이도 미션에 참여하면 "
        "캐릭터 미션도 함께 완료됩니다."
    )
    result = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "미카엘라 레이드는 2026년 8월 6일 점검 후 출시했습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드는 언제 출시했어?",
        evidence_units=[
            {
                "evidence_ref": "E1",
                "chunk_id": "event",
                "start_char": 0,
                "end_char": len(evidence),
                "text": evidence,
                "title": "미카엘라 클리어 미션 이벤트",
                "context_text": (
                    "2026년 8월 6일 점검 후부터 8월 20일 점검 전까지 "
                    "진행되는 이벤트"
                ),
                "published_at": "2026-08-06",
                "valid_from": "2026-08-06",
                "valid_to": "2026-08-20",
                "question_relevance_score": 0.9,
            }
        ],
        chunks_by_id={
            "event": {
                "chunk_id": "event",
                "display_text": evidence,
            }
        },
        requested_subjects=None,
    )

    assert result["claims"] == []
    assert result["rejected_claims"][0]["reasons"] == [
        "question_relation_role_mismatch"
    ]


def test_release_date_claim_accepts_explicit_update_date_evidence():
    evidence = (
        "미카엘라 레이드는 2026년 8월 6일(목) 점검 중 "
        "업데이트 되는 내용입니다."
    )
    result = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "미카엘라 레이드는 2026년 8월 6일 업데이트됐습니다.",
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드는 언제 출시했어?",
        evidence_units=[
            {
                "evidence_ref": "E1",
                "chunk_id": "patch-note",
                "start_char": 0,
                "end_char": len(evidence),
                "text": evidence,
                "title": "시즌 11 Act 3. 무너진 성자 미카엘라",
                "context_text": "업데이트 안내",
                "published_at": "2026-08-06",
                "question_relevance_score": 0.9,
            }
        ],
        chunks_by_id={
            "patch-note": {
                "chunk_id": "patch-note",
                "display_text": evidence,
            }
        },
        requested_subjects=None,
    )

    assert [claim["text"] for claim in result["claims"]] == [
        "미카엘라 레이드는 2026년 8월 6일 업데이트됐습니다."
    ]
    assert result["rejected_claims"] == []


def test_release_date_claim_rebinds_event_ref_to_direct_update_evidence():
    patch_text = (
        "미카엘라 레이드는 2026년 8월 6일(목) 점검 중 "
        "업데이트 되는 내용입니다."
    )
    event_text = "미카엘라 레이드 하드 난이도 미션이 진행됩니다."
    result = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": "미카엘라 레이드는 2026년 8월 6일 출시했습니다.",
                    "evidence_refs": ["E2"],
                }
            ],
            "clarification": "",
        },
        question="미카엘라 레이드는 언제 출시했어?",
        evidence_units=[
            {
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": "patch-note",
                "start_char": 0,
                "end_char": len(patch_text),
                "text": patch_text,
                "title": "시즌 11 Act 3. 무너진 성자 미카엘라",
                "context_text": "업데이트 안내",
                "published_at": "2026-08-05",
                "question_relevance_score": 0.9,
            },
            {
                "evidence_ref": "E2",
                "candidate_ref": "2",
                "chunk_id": "event",
                "start_char": 0,
                "end_char": len(event_text),
                "text": event_text,
                "title": "미카엘라 클리어 미션 이벤트",
                "context_text": (
                    "2026년 8월 6일 점검 후부터 8월 20일까지"
                ),
                "published_at": "2026-08-06",
                "question_relevance_score": 0.9,
            },
        ],
        chunks_by_id={
            "patch-note": {
                "chunk_id": "patch-note",
                "display_text": patch_text,
            },
            "event": {
                "chunk_id": "event",
                "display_text": event_text,
            },
        },
        requested_subjects=None,
    )

    assert result["rejected_claims"] == []
    assert result["claims"][0]["evidence_refs"] == ["E1"]
    assert result["claims"][0]["citations"][0]["text"] == patch_text
    assert result["verification"]["rebound_evidence_refs"] == [
        {"claim_index": 1, "from": ["E2"], "to": ["E1"]}
    ]


def test_kiwi_clause_split_does_not_split_one_descriptive_phrase():
    question = "빠르고 강한 장비의 특징을 알려줘."

    assert explicit_question_clauses(question) == [
        "빠르고 강한 장비의 특징을 알려줘"
    ]


def test_surface_requirement_queries_reserve_explicit_date_clause():
    queries = surface_requirement_queries(
        "2020년 12월 4일 시행 운영정책에서 길드장 권한이 "
        "위임될 수 있는 조건과 처리 기간을 알려줘."
    )

    assert any(
        query.startswith("2020년 12월 4일")
        and "위임될 수 있는 조건" in query
        for query in queries[1:]
    )
    assert any(
        query.startswith("시행 운영정책")
        and "위임될 수 있는 조건" in query
        for query in queries[1:]
    )


def test_explicit_question_clauses_remove_dangling_coordination_particle():
    clauses = explicit_question_clauses(
        "2026년 1월 마일리지샵 2026 시즌4 열쇠 상자의 판매 기간과, "
        "상자에서 나온 열쇠의 거래 타입을 알려줘."
    )

    assert clauses[0].endswith("판매 기간")


def test_surface_requirement_queries_can_fill_eight_evidence_slots():
    queries = surface_requirement_queries(
        "대상의 가격, 구매 제한, 삭제 시점, 거래 타입, 사용 기간은?"
    )

    assert len(queries) == 6
    assert "대상 구매 제한" in queries
    assert "대상 사용 기간은" in queries


def test_explicit_question_subjects_only_uses_visible_surface_structure():
    assert explicit_question_subjects(
        "최후의 과업이랑 디레지에 입장명성 알려줘"
    ) == ["최후의 과업", "디레지에"]
    assert explicit_question_subjects(
        "2026년 7월 16일 밸런스 패치에서 "
        "스트라이커(남)와 그래플러(남)의 공격력 증가율을 알려줘"
    ) == ["스트라이커(남)", "그래플러(남)"]
    assert explicit_question_subjects(
        "이달의 아이템은 한 번 구매하면 다음 달 상품도 자동 결제돼?"
    ) == ["이달의 아이템"]
    assert explicit_question_subjects(
        "DirectX 11 추가 최적화 뒤 메모리 사용량은 어느 수준이야?"
    ) == []
    assert explicit_question_subjects(
        "DirectX 11 추가 최적화 뒤 메모리 사용량은 "
        "DirectX 9과 견줘 어느 수준까지 개선됐어?"
    ) == []


def test_compact_pack_keeps_two_units_for_one_surface_question():
    text = "\n".join(
        (
            "<최후의 과업>은 모든 요일에 입장 가능합니다.",
            "최후의 과업 입장 명성은 108,921입니다.",
        )
    )
    chunks = {
        "chunk": {
            "chunk_id": "chunk",
            "parent_document_id": "document",
            "display_text": text,
            "heading_path": ["최후의 과업 입장 정보"],
            "status": "current",
        }
    }
    documents = {
        "document": {
            "document_id": "document",
            "source_id": "dnf_update",
            "title": "최후의 과업 업데이트",
            "status": "current",
        }
    }

    units = build_compact_product_evidence_pack(
        ["chunk"],
        question="최후의과업 입장 명성제한알려줘",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert len(units) == 2
    assert {unit["text"] for unit in units} == set(text.splitlines())


def test_product_verifier_allows_binary_claim_to_repeat_question_value():
    text = "파티플레이뿐만 아니라 1인 플레이 시에도 동일하게 적용됩니다."
    unit = {
        "evidence_ref": "E1",
        "candidate_ref": "1",
        "chunk_id": "faq",
        "parent_document_id": "faq_doc",
        "title": "1인 플레이에도 등장 확률이 증가하나요?",
        "context_text": "가브리엘의 상점",
        "start_char": 0,
        "end_char": len(text),
        "text": text,
        "complete": False,
    }

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "등장 확률 개선(14%)은 1인 플레이에도 "
                        "동일하게 적용됩니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=(
            "가브리엘의 상점 등장 확률 개선(14%)은 1인 플레이로 "
            "진행해도 동일하게 적용돼?"
        ),
        evidence_units=[unit],
        chunks_by_id={"faq": {"display_text": text}},
    )

    assert verified["mode"] == "answer"
    assert verified["rejected_claims"] == []


def test_product_verifier_rebinds_exact_value_to_provided_evidence():
    introduction = "2026년 1월 해방의 열쇠 100개 상자 판매 안내입니다."
    deletion = "삭제일자는 2026년 1월 22일 06시입니다."
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "intro",
            "parent_document_id": "key_doc",
            "title": "2026년 1월 해방의 열쇠 100개 상자",
            "context_text": "판매 안내",
            "start_char": 0,
            "end_char": len(introduction),
            "text": introduction,
            "complete": False,
            "question_relevance_score": 0.9,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "1",
            "chunk_id": "deletion",
            "parent_document_id": "key_doc",
            "title": "2026년 1월 해방의 열쇠 100개 상자",
            "context_text": "삭제일자",
            "start_char": 0,
            "end_char": len(deletion),
            "text": deletion,
            "complete": False,
            "question_relevance_score": 0.95,
        },
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "2026년 1월 해방의 열쇠 100개 상자는 "
                        "2026년 1월 22일 06시에 삭제됩니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=(
            "2026년 1월에 판매한 해방의 열쇠 100개 상자는 "
            "언제 삭제됐어?"
        ),
        evidence_units=units,
        chunks_by_id={
            "intro": {"display_text": introduction},
            "deletion": {"display_text": deletion},
        },
    )

    assert verified["mode"] == "answer"
    assert verified["claims"][0]["evidence_refs"] == ["E2"]
    assert verified["verification"]["rebound_evidence_refs"] == [
        {"claim_index": 1, "from": ["E1"], "to": ["E2"]}
    ]


def test_product_verifier_rebinds_claim_to_matching_policy_date():
    condition = "길드장 계정이 이용 제한 상태인 경우 권한이 위임됩니다."
    units = [
        {
            "evidence_ref": "E1",
            "candidate_ref": "1",
            "chunk_id": "old-policy",
            "title": "던전앤파이터 운영정책 (2018-12-02 시행)",
            "context_text": "길드장 권한 위임 조건",
            "start_char": 0,
            "end_char": len(condition),
            "text": condition,
            "complete": False,
        },
        {
            "evidence_ref": "E2",
            "candidate_ref": "2",
            "chunk_id": "requested-policy",
            "title": "던전앤파이터 운영정책 (2020-12-04 시행)",
            "context_text": "길드장 권한 위임 조건",
            "start_char": 0,
            "end_char": len(condition),
            "text": condition,
            "complete": False,
        },
    ]

    verified = verify_product_claim_output(
        {
            "mode": "answer",
            "claims": [
                {
                    "text": (
                        "2020년 12월 4일 시행 운영정책에서 길드장 "
                        "계정이 이용 제한 상태인 경우 권한이 위임됩니다."
                    ),
                    "evidence_refs": ["E1"],
                }
            ],
            "clarification": "",
        },
        question=(
            "2020년 12월 4일 시행 운영정책에서 길드장 권한 위임 "
            "조건을 알려줘."
        ),
        evidence_units=units,
        chunks_by_id={
            "old-policy": {"display_text": condition},
            "requested-policy": {"display_text": condition},
        },
    )

    assert verified["mode"] == "answer"
    assert verified["claims"][0]["evidence_refs"] == ["E2"]
    assert verified["verification"]["rebound_evidence_refs"] == [
        {"claim_index": 1, "from": ["E1"], "to": ["E2"]}
    ]


def test_evidence_candidate_expansion_adds_one_sibling_per_parent():
    selected = [
        {"chunk_id": "selected", "parent_document_id": "policy"}
    ]
    chunks_by_parent = {
        "policy": [
            {
                "chunk_id": "selected",
                "parent_document_id": "policy",
                "retrieval_text": "채팅 정책 최근 1년 초기화",
                "review_required": False,
            },
            {
                "chunk_id": "gold",
                "parent_document_id": "policy",
                "retrieval_text": "채팅 관련 제재 누적일은 최대 30일",
                "review_required": False,
            },
            {
                "chunk_id": "other",
                "parent_document_id": "policy",
                "retrieval_text": "다른 운영 정책",
                "review_required": False,
            },
        ]
    }

    chunk_ids = expand_evidence_candidate_chunk_ids(
        "채팅 관련 제재 누적일은 최대 며칠이야?",
        selected,
        chunks_by_parent=chunks_by_parent,
    )

    assert chunk_ids == ["selected", "gold"]


def test_evidence_candidate_expansion_skips_cleaned_listing_tail():
    selected = [
        {"chunk_id": "selected", "parent_document_id": "shop"}
    ]
    chunks_by_parent = {
        "shop": [
            {
                "chunk_id": "selected",
                "parent_document_id": "shop",
                "display_text": "상품 삭제 시각",
                "retrieval_text": "상품 삭제 시각",
                "review_required": False,
            },
            {
                "chunk_id": "cleaned-tail",
                "parent_document_id": "shop",
                "display_text": (
                    "상품 판매 기간\n텍스트복사\n목록\n"
                    + "목록 오염 데이터 " * 40
                ),
                "retrieval_text": "상품 판매 기간",
                "review_required": False,
            },
            {
                "chunk_id": "clean-sibling",
                "parent_document_id": "shop",
                "display_text": "상품 판매 기간은 4월부터 6월까지입니다.",
                "retrieval_text": (
                    "상품 판매 기간은 4월부터 6월까지입니다."
                ),
                "review_required": False,
            },
        ]
    }

    chunk_ids = expand_evidence_candidate_chunk_ids(
        "상품 판매 기간은 언제야?",
        selected,
        chunks_by_parent=chunks_by_parent,
    )

    assert chunk_ids == ["selected", "clean-sibling"]


def test_compact_pack_prefers_matching_identity_over_sibling_relation():
    chunks = {
        "schedule": {
            "chunk_id": "schedule",
            "parent_document_id": "final-update",
            "display_text": "\n".join(
                (
                    "<최후의 과업>은 모든 요일에 입장 가능합니다.",
                    (
                        "<최후의 과업> 채널은 모험가 명성 "
                        "108,921부터 입장이 가능합니다."
                    ),
                )
            ),
            "heading_path": ["최후의 과업", "콘텐츠 입장"],
            "status": "current",
        },
        "sibling-fame": {
            "chunk_id": "sibling-fame",
            "parent_document_id": "coordinator",
            "display_text": "| 입장 명성 | 13,632 |",
            "heading_path": ["최후의 조율자", "콘텐츠 입장"],
            "status": "current",
        },
        "final-fame": {
            "chunk_id": "final-fame",
            "parent_document_id": "final-guide",
            "display_text": "| 입장 명성 | 108,921 |",
            "heading_path": ["최후의 과업", "콘텐츠 정보"],
            "status": "current",
        },
    }
    documents = {
        "final-update": {
            "document_id": "final-update",
            "source_id": "dnf_update",
            "title": "최후의 과업 업데이트",
            "status": "current",
        },
        "coordinator": {
            "document_id": "coordinator",
            "source_id": "dnf_game_guide",
            "title": "[115] 최후의 조율자",
            "status": "current",
        },
        "final-guide": {
            "document_id": "final-guide",
            "source_id": "dnf_game_guide",
            "title": "[115] 최후의 과업",
            "status": "current",
        },
    }

    units = build_compact_product_evidence_pack(
        ["schedule", "sibling-fame", "final-fame"],
        question="최후의과업 입장 명성제한알려줘",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert len(units) == 4
    assert all("108,921" in unit["text"] for unit in units[:2])
    assert all("13,632" not in unit["text"] for unit in units[:2])


def test_compact_pack_uses_available_capacity():
    text = "\n".join(
        f"대상 속성 {index} 값은 {index}입니다."
        for index in range(1, 9)
    )
    chunks = {
        "chunk": {
            "chunk_id": "chunk",
            "parent_document_id": "document",
            "display_text": text,
            "heading_path": ["대상 안내"],
            "status": "current",
        }
    }
    documents = {
        "document": {
            "document_id": "document",
            "source_id": "dnf_update",
            "title": "대상 안내",
            "status": "current",
        }
    }

    units = build_compact_product_evidence_pack(
        ["chunk"],
        question="대상 속성 1과 속성 2, 속성 3을 알려줘",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
    )

    assert len(units) == 8
    assert any("속성 1" in unit["text"] for unit in units)
    assert any("속성 2" in unit["text"] for unit in units)
    assert any("속성 3" in unit["text"] for unit in units)


def test_candidate_requirement_visibility_requires_each_supported_requirement():
    sealed = {
        "requirements": [
            {
                "requirement_id": "first",
                "expected_status": "supported",
                "acceptable_evidence_units": [{"chunk_id": "chunk-1"}],
            },
            {
                "requirement_id": "second",
                "expected_status": "supported",
                "acceptable_evidence_units": [{"chunk_id": "chunk-2"}],
            },
            {
                "requirement_id": "missing",
                "expected_status": "unsupported",
                "acceptable_evidence_units": [],
            },
        ]
    }

    partial = candidate_requirement_visibility(
        sealed,
        [{"chunk_id": "chunk-1"}],
    )
    complete = candidate_requirement_visibility(
        sealed,
        [{"chunk_id": "chunk-1"}, {"chunk_id": "chunk-2"}],
    )

    assert partial["all_supported_visible"] is False
    assert partial["visible_requirement_count"] == 1
    assert complete["all_supported_visible"] is True


def test_candidate_waterfall_classifies_the_actual_drop_stage():
    assert (
        classify_drop_stage(
            union_visible=False,
            reranker_top8_visible=False,
            parent_top8_visible=False,
        )
        == "initial_union_missing"
    )
    assert (
        classify_drop_stage(
            union_visible=True,
            reranker_top8_visible=False,
            parent_top8_visible=False,
        )
        == "reranker_below_final_cut"
    )
    assert (
        classify_drop_stage(
            union_visible=True,
            reranker_top8_visible=True,
            parent_top8_visible=False,
        )
        == "parent_cap_or_final_assembly"
    )


def test_identity_shortlist_treats_explicit_month_as_an_interval():
    interval = explicit_temporal_interval(
        "2026년 5월 고대의 바인드 큐브 상자를 알려줘"
    )

    assert interval == ("2026-05-01", "2026-05-31")
    assert intervals_overlap(
        interval,
        valid_from="2026-04-30",
        valid_to="2026-05-28",
    )
    assert explicit_temporal_interval(
        "7월 스페셜 클론 레어 아바타 상자를 알려줘",
        reference_date="2026-07-31",
    ) == ("2026-07-01", "2026-07-31")


def test_identity_shortlist_prefers_matching_month_label():
    documents = {
        "monthly": {
            "document_id": "monthly",
            "title": "5월 이달 의 아이템",
            "published_at": "2026-04-30",
        },
        "event": {
            "document_id": "event",
            "title": "고대의 바인드 큐브 행사",
            "published_at": "2026-05-01",
        },
    }
    chunks = {
        "monthly": [
            {
                "review_required": False,
                "valid_from": "2026-04-30",
                "valid_to": "2026-05-28",
                "heading_path": ["고대의 바인드 큐브 8개 상자"],
            }
        ],
        "event": [
            {
                "review_required": False,
                "valid_from": "2026-05-01",
                "valid_to": "2026-05-31",
                "heading_path": ["고대의 바인드 큐브"],
            }
        ],
    }

    result = shortlist_identity_documents(
        "2026년 5월 고대의 바인드 큐브 8개 상자를 알려줘",
        documents_by_id=documents,
        chunks_by_parent=chunks,
    )

    assert result[0]["document_id"] == "monthly"
    assert result[0]["period_label_match"] is True


def test_duplicate_aware_visibility_accepts_same_parent_overlap_text():
    sealed = {
        "requirements": [
            {
                "requirement_id": "delegation_conditions",
                "expected_status": "supported",
                "required_values": ["12개월 이상 미접속"],
                "acceptable_evidence_units": [
                    {
                        "chunk_id": "gold",
                        "document_id": "policy",
                        "text": "12개월 이상 미접속 상태인 경우 위임됩니다.",
                    }
                ],
            }
        ]
    }
    candidates = [
        {
            "chunk_id": "overlap",
            "parent_document_id": "policy",
            "display_text": "12개월이상 미접속 상태인 경우 위임됩니다.",
        }
    ]

    visibility = duplicate_aware_requirement_visibility(
        sealed,
        candidates,
    )

    assert visibility["all_supported_visible"] is True
    assert visibility["requirements"][0]["overlap_equivalent"] is True


def _preview_notice_result(
    *,
    accepted_chunk_id: str,
    claim_text: str | None = None,
    source_kind_on_document: bool = False,
):
    evidence_by_chunk = {
        "preview": "퍼스트 서버에서 광휘의 잔재 하드 보상은 90개입니다.",
        "live": "라이브 서버에서 광휘의 잔재 하드 보상은 90개입니다.",
    }
    evidence = evidence_by_chunk[accepted_chunk_id]

    def fake_generator(*, prompt, model, timeout_seconds):
        del prompt, timeout_seconds
        return {
            "output": {
                "mode": "answer",
                "claims": [
                    {
                        "text": claim_text or evidence,
                        "evidence_refs": ["E1"],
                    }
                ],
                "clarification": "",
            },
            "model": model,
            "provider": "test",
            "latency_ms": 1.0,
            "usage": {},
        }

    return answer_product_rag_from_candidates(
        question="광휘의 잔재 하드 보상은 몇 개야?",
        requirement_queries=None,
        requested_subjects=None,
        selected=[
            {"chunk_id": "preview", "parent_document_id": "preview-doc"},
            {"chunk_id": "live", "parent_document_id": "live-doc"},
        ],
        chunks_by_id={
            "preview": {
                "display_text": evidence_by_chunk["preview"],
                "source_kind": (
                    None if source_kind_on_document else "preview_patch"
                ),
            },
            "live": {
                "display_text": evidence_by_chunk["live"],
                "source_kind": "guide",
            },
        },
        documents_by_id={
            "preview-doc": {
                "source_kind": (
                    "preview_patch" if source_kind_on_document else None
                )
            }
        },
        temporal_by_document={},
        model="test-model",
        timeout_seconds=10,
        generator=fake_generator,
        evidence_units_override=[
            {
                "evidence_ref": "E1",
                "candidate_ref": "1",
                "chunk_id": accepted_chunk_id,
                "parent_document_id": f"{accepted_chunk_id}-doc",
                "title": "미카엘라 레이드 보상",
                "context_text": "난이도별 보상",
                "start_char": 0,
                "end_char": len(evidence),
                "text": evidence,
                "complete": False,
            }
        ],
    )


def test_preview_notice_is_server_rendered_for_accepted_preview_citation():
    result = _preview_notice_result(accepted_chunk_id="preview")

    notice = (
        "퍼스트 서버(테스트 서버) 기준 정보입니다. "
        "라이브 서버 적용 시 변경될 수 있습니다."
    )
    assert result["mode"] == "answer"
    assert result["rendered_answer"].startswith(notice)
    assert result["verification"]["preview_source_notice_required"] is True
    assert result["verification"]["preview_evidence_refs"] == ["E1"]


def test_preview_candidate_does_not_trigger_notice_when_live_citation_is_used():
    result = _preview_notice_result(accepted_chunk_id="live")

    assert "퍼스트 서버(테스트 서버) 기준 정보입니다." not in result[
        "rendered_answer"
    ]
    assert result["verification"]["preview_source_notice_required"] is False
    assert result["verification"]["preview_evidence_refs"] == []


def test_rejected_preview_claim_does_not_trigger_notice():
    result = _preview_notice_result(
        accepted_chunk_id="preview",
        claim_text="퍼스트 서버에서 광휘의 잔재 하드 보상은 91개입니다.",
    )

    assert result["claims"] == []
    assert result["rejected_claims"]
    assert "퍼스트 서버(테스트 서버) 기준 정보입니다." not in result[
        "rendered_answer"
    ]
    assert result["verification"]["preview_source_notice_required"] is False
    assert result["verification"]["preview_evidence_refs"] == []


def test_preview_notice_accepts_document_level_source_kind_metadata():
    result = _preview_notice_result(
        accepted_chunk_id="preview",
        source_kind_on_document=True,
    )

    assert result["verification"]["preview_source_notice_required"] is True
    assert result["rendered_answer"].startswith(
        "퍼스트 서버(테스트 서버) 기준 정보입니다."
    )
