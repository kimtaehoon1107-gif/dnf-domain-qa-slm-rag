from src.v3.evaluate_contextual_answer_unit_ab import (
    choose_contextual_decisions,
    contextual_certificate,
    contextual_certificate_dominates,
    contextual_retrieval_text,
)


def _chunk(text: str, heading: str = "") -> dict:
    return {
        "chunk_id": "chunk-1",
        "parent_document_id": "parent-1",
        "display_text": text,
        "heading_path": [heading] if heading else [],
    }


def _segment(text: str, needle: str, kind: str = "sentence") -> dict:
    start = text.rindex(needle)
    return {
        "span_id": "span-1",
        "chunk_id": "chunk-1",
        "start_char": start,
        "end_char": start + len(needle),
        "text": needle,
        "kind": kind,
    }


def test_local_value_free_labels_bind_price_without_copying_neighbor_value():
    text = "아라드 로얄 패스\n29,800 세라\n로얄 패스\n캐릭터 추가 지정권\n9,800 세라"
    segment = _segment(text, "9,800 세라")

    context = contextual_retrieval_text(
        _chunk(text), segment, document_title="아라드패스 2026 시즌3"
    )

    assert "캐릭터 추가 지정권" in context
    assert "로얄 패스" in context
    assert "29,800 세라" not in context
    assert context.endswith("9,800 세라")


def test_table_row_gets_document_section_and_header_but_not_prior_value_row():
    text = (
        "신규 결제수단 퀵계좌이체 오픈 안내\n■ 이용 한도\n[TABLE]\n"
        "| 구분 | 금액 |\n26,160\n| 1회(만원) | 50 |\n| 1일(만원) | 200 |"
    )
    segment = _segment(text, "| 1일(만원) | 200 |", "table_row")

    context = contextual_retrieval_text(
        _chunk(text, "공지사항"), segment, document_title="신규 결제수단 퀵계좌이체 오픈 안내"
    )

    assert "퀵계좌이체" in context
    assert "■ 이용 한도" in context
    assert "| 구분 | 금액 |" in context
    assert "26,160" not in context
    assert "| 1회(만원) | 50 |" not in context
    assert context.endswith("| 1일(만원) | 200 |")


def test_table_month_limit_is_normalized_only_in_retrieval_context():
    text = "■ 이용 한도\n| 구분 | 금액 |\n| 1월(만원) | 500 |"
    segment = _segment(text, "| 1월(만원) | 500 |", "table_row")

    context = contextual_retrieval_text(
        _chunk(text), segment, document_title="신규 결제수단 안내"
    )

    assert context.endswith("| 1개월(만원) | 500 |")
    assert segment["text"] == "| 1월(만원) | 500 |"


def test_inline_heading_binds_answer_bearing_bullet():
    text = "# 광휘의 행로\n설명이 이어집니다.\n- 명성 58,950 이상의 캐릭터로 탐사를 진행할 수 있습니다."
    segment = _segment(text, "- 명성 58,950 이상의 캐릭터로 탐사를 진행할 수 있습니다.")

    context = contextual_retrieval_text(
        _chunk(text, "업데이트"), segment, document_title="5/21 정기점검 업데이트"
    )

    assert "광휘의 행로" in context
    assert context.endswith(segment["text"])


def test_previous_answer_sentence_is_not_reused_as_local_label():
    answer = "캐릭터의 점화 게이지가 높아질수록 몬스터의 무력화 게이지가 더 많이 차감됩니다."
    target = "중단된 게이지 상승은 일정 시간이 지난 뒤 다시 상승하기 시작합니다."
    text = f"# 점화\n{answer}\n{target}"
    segment = _segment(text, target)

    context = contextual_retrieval_text(
        _chunk(text, "전투 시스템"), segment, document_title="전투 시스템"
    )

    assert answer not in context
    assert "점화" in context
    assert context.endswith(target)


def test_contextual_certificate_prefers_bound_value_over_heading():
    requirement = {
        "requirement_id": "r1",
        "subject": "퀵계좌이체",
        "relation": "1일 결제 한도",
        "value_type": "amount",
    }
    chunks = {"chunk-1": _chunk("# 이용 한도\n| 1일(만원) | 200 |")}
    baseline = {
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "heading",
                "chunk_id": "chunk-1",
                "text": "# 이용 한도",
                "reranker_score": 0.9,
            }
        ],
    }
    alternative = {
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "value",
                "chunk_id": "chunk-1",
                "text": "| 1일(만원) | 200 |",
                "answer_unit_context": "퀵계좌이체\n이용 한도\n| 구분 | 금액 |\n| 1일(만원) | 200 |",
                "kind": "table_row",
                "reranker_score": 0.5,
            }
        ],
    }

    baseline_certificate = contextual_certificate(requirement, baseline, chunks)
    alternative_certificate = contextual_certificate(requirement, alternative, chunks)

    assert contextual_certificate_dominates(
        alternative_certificate, baseline_certificate
    ) is True


def test_higher_reranker_score_alone_does_not_commit_replacement():
    baseline = {
        "supported_exact": True,
        "answer_bearing": True,
        "shape_vetoed": False,
        "best": {
            "bound": True,
            "shape_safe": True,
            "subject_coverage": 1.0,
            "reranker_score": 0.2,
        },
    }
    alternative = {
        **baseline,
        "best": {**baseline["best"], "reranker_score": 0.9},
    }

    assert contextual_certificate_dominates(alternative, baseline) is False


def test_prose_cannot_jump_parent_but_table_row_can():
    requirement = {
        "requirement_id": "r1",
        "subject": "퀵계좌이체 서비스",
        "relation": "1일 결제 한도",
        "value_type": "amount",
    }
    chunks = {
        "old": {
            **_chunk("퀵계좌이체 1일 결제 한도는 100만원입니다."),
            "chunk_id": "old",
            "parent_document_id": "parent-old",
        },
        "baseline-distractor": {
            **_chunk("일반 안내"),
            "chunk_id": "baseline-distractor",
            "parent_document_id": "parent-new",
        },
        "new": {
            **_chunk("| 1일(만원) | 200 |"),
            "chunk_id": "new",
            "parent_document_id": "parent-new",
        },
    }
    baseline = {
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "old",
                "chunk_id": "old",
                "text": "퀵계좌이체 1일 결제 한도는 100만원입니다.",
                "reranker_score": 0.1,
            },
            {
                "span_id": "baseline-distractor",
                "chunk_id": "baseline-distractor",
                "text": "일반 안내",
                "reranker_score": 0.01,
            },
        ],
    }
    prose = {
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "new-prose",
                "chunk_id": "new",
                "text": "1일 결제 한도는 200만원입니다.",
                "answer_unit_context": "퀵계좌이체 서비스 1일 결제 한도는 200만원입니다.",
                "kind": "sentence",
                "reranker_score": 0.9,
            }
        ],
    }
    table = {
        "status": "supported_exact",
        "spans": [
            {
                "span_id": "new-table",
                "chunk_id": "new",
                "text": "| 1일(만원) | 200 |",
                "answer_unit_context": "퀵계좌이체 서비스 이용 한도 | 1일(만원) | 200 |",
                "kind": "table_row",
                "reranker_score": 0.9,
            }
        ],
    }

    prose_choice, _ = choose_contextual_decisions(
        [requirement], [baseline], {"notice": [prose]}, chunks
    )
    table_choice, _ = choose_contextual_decisions(
        [requirement], [baseline], {"notice": [table]}, chunks
    )

    assert prose_choice == [baseline]
    assert table_choice == [table]
