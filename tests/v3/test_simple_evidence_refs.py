from src.v3.simple_evidence_refs import (
    SimpleEvidenceRefOutput,
    build_atomic_evidence_units,
    build_simple_evidence_ref_prompt,
    build_simple_evidence_units,
    model_evidence_payload,
    resolve_evidence_refs,
    verify_simple_evidence_ref_output,
)


def _artifacts() -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    text = (
        "# NPC 장비 초월\n"
        "장비 초월은 계정 금고로 장비를 이동시키는 시스템입니다.\n"
        "### 비용\n"
        "115Lv 장비 초월 비용은 아래와 같습니다."
    )
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": text,
            "status": "current",
            "default_exposure": True,
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_game_guide",
            "source_kind": "game_guide",
            "title": "초월",
            "published_at": None,
            "valid_from": None,
            "valid_to": None,
            "revision_id": "r1",
            "status": "current",
            "default_exposure": True,
        }
    }
    temporal = {"d1": {"validity_state": "current"}}
    return chunks, documents, temporal


def test_build_simple_evidence_units_preserves_exact_coordinates() -> None:
    chunks, documents, temporal = _artifacts()

    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )

    assert [unit["evidence_ref"] for unit in units] == ["E1"]
    assert all(unit["candidate_ref"] == "1" for unit in units)
    assert units[0]["start_char"] == 0
    assert units[0]["end_char"] == len(chunks["c1"]["display_text"])
    for unit in units:
        source = chunks[unit["chunk_id"]]["display_text"]
        assert source[unit["start_char"] : unit["end_char"]] == unit["text"]


def test_atomic_units_are_exact_sentence_and_table_row_slices() -> None:
    text = (
        "# 월간 상품\n"
        "판매 기간은 5월 1일부터 5월 31일까지입니다. 다른 설명입니다.\n"
        "[TABLE]\n"
        "| 구분 | 값 |\n"
        "| 아이템명 | 해방의 열쇠 100개 상자 |\n"
        "| 삭제일 | 2026년 5월 28일 06시 |\n"
        "[/TABLE]"
    )
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": text,
            "heading_path": ["이달의 아이템"],
            "status": "current",
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_monthly_item",
            "title": "5월 이달의 아이템",
            "revision_id": "r1",
            "status": "current",
        }
    }

    units = build_atomic_evidence_units(
        ["c1"],
        question="해방의 열쇠 100개 상자는 언제 삭제돼?",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=12,
    )

    assert {unit["unit_kind"] for unit in units} == {
        "sentence",
        "table_row",
    }
    assert any(
        unit["text"] == "판매 기간은 5월 1일부터 5월 31일까지입니다."
        for unit in units
    )
    deletion = next(unit for unit in units if "삭제일" in unit["text"])
    assert "표 헤더: | 구분 | 값 |" in deletion["context_text"]
    assert "표 대상: | 아이템명 | 해방의 열쇠 100개 상자 |" in deletion[
        "context_text"
    ]
    for unit in units:
        source = chunks[unit["chunk_id"]]["display_text"]
        assert source[unit["start_char"] : unit["end_char"]] == unit["text"]


def test_atomic_units_limit_size_and_keep_each_candidate_visible() -> None:
    chunks = {}
    documents = {}
    for index in range(1, 4):
        chunks[f"c{index}"] = {
            "chunk_id": f"c{index}",
            "parent_document_id": f"d{index}",
            "display_text": "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.",
            "heading_path": [],
            "status": "current",
        }
        documents[f"d{index}"] = {
            "document_id": f"d{index}",
            "source_id": "dnf_game_guide",
            "title": f"문서 {index}",
            "status": "current",
        }

    units = build_atomic_evidence_units(
        ["c1", "c2", "c3"],
        question="둘째 문장",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=5,
    )

    assert len(units) == 5
    assert {unit["candidate_ref"] for unit in units} == {"1", "2", "3"}
    assert [unit["evidence_ref"] for unit in units] == [
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
    ]


def test_atomic_selection_handles_korean_particles_and_numbered_lines() -> None:
    text = (
        "DirectX 11 안내입니다.\n"
        "1. 일반 안내\n"
        "이러한 추이를 바탕으로 향후 DirectX 9 지원 종료를 검토합니다."
    )
    chunks = {
        "c1": {
            "chunk_id": "c1",
            "parent_document_id": "d1",
            "display_text": text,
            "heading_path": [],
            "status": "current",
        }
    }
    documents = {
        "d1": {
            "document_id": "d1",
            "source_id": "dnf_notice",
            "title": "DirectX 11 안내",
            "status": "current",
        }
    }

    units = build_atomic_evidence_units(
        ["c1"],
        question="DirectX 9 지원은 이미 종료된 상태였어?",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=2,
    )

    assert any("지원 종료를 검토" in unit["text"] for unit in units)
    all_units = build_atomic_evidence_units(
        ["c1"],
        question="일반 안내",
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document={},
        max_units=3,
    )
    assert any(unit["text"] == "1. 일반 안내" for unit in all_units)


def test_model_payload_does_not_expose_coordinates_or_chunk_ids() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )

    payload = model_evidence_payload(units)

    assert payload
    assert set(payload[0]) == {
        "evidence_ref",
        "candidate_ref",
        "title",
        "context",
        "text",
    }


def test_resolve_evidence_refs_restores_exact_citations_and_deduplicates() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    units_by_ref = {unit["evidence_ref"]: unit for unit in units}
    selected_ref = units[0]["evidence_ref"]

    citations, failures = resolve_evidence_refs(
        [selected_ref, selected_ref],
        evidence_units_by_ref=units_by_ref,
        chunks_by_id=chunks,
    )

    assert failures == []
    assert len(citations) == 1
    citation = citations[0]
    assert citation["evidence_ref"] == selected_ref
    assert (
        chunks["c1"]["display_text"][
            citation["start_char"] : citation["end_char"]
        ]
        == citation["text"]
    )


def test_resolve_evidence_refs_rejects_unknown_and_stale_coordinates() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    units_by_ref = {unit["evidence_ref"]: dict(unit) for unit in units}
    units_by_ref["E1"]["start_char"] = 1

    citations, failures = resolve_evidence_refs(
        ["E404", "E1"],
        evidence_units_by_ref=units_by_ref,
        chunks_by_id=chunks,
    )

    assert citations == []
    assert failures == [
        "evidence_ref_not_provided:E404",
        "evidence_coordinate_mismatch:E1",
    ]


def test_evidence_ref_schema_rejects_invalid_support_shapes() -> None:
    for payload in (
        {
            "question_time_scope": "current",
            "result": {
                "status": "supported",
                "answer": "장비 초월",
                "evidence_refs": [],
            },
        },
        {
            "question_time_scope": "current",
            "result": {
                "status": "unsupported",
                "answer": "장비 초월",
                "evidence_refs": ["E1"],
            },
        },
    ):
        try:
            SimpleEvidenceRefOutput.model_validate(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid support shape was accepted")


def test_prompt_exposes_evidence_refs_without_source_coordinates() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )

    prompt = build_simple_evidence_ref_prompt(
        question="초월은 무슨 종류가 있어?",
        as_of="2026-07-29",
        evidence_units=units,
    )

    assert '"evidence_ref": "E1"' in prompt
    assert '"start_char"' not in prompt
    assert '"chunk_id"' not in prompt


def test_verifier_resolves_supported_refs_and_recomputes_full_answer() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )
    selected_ref = units[0]["evidence_ref"]

    verified = verify_simple_evidence_ref_output(
        {
            "question_time_scope": "current",
            "result": {
                "status": "supported",
                "answer": "장비 초월",
                "evidence_refs": [selected_ref],
            },
        },
        question="초월 종류",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["model_response_mode"] == "full_answer"
    assert verified["response_mode"] == "full_answer"
    assert verified["requirements"][0]["status"] == "supported_exact"
    assert verified["requirements"][0]["citations"][0]["evidence_ref"] == selected_ref


def test_verifier_fails_requirement_closed_for_unknown_ref() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )

    verified = verify_simple_evidence_ref_output(
        {
            "question_time_scope": "current",
            "result": {
                "status": "supported",
                "answer": "장비 초월",
                "evidence_refs": ["E404"],
            },
        },
        question="초월 종류",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["response_mode"] == "abstain"
    assert verified["requirements"][0]["answer"] == ""
    assert verified["verification"]["requirements"][0]["failure_reasons"] == [
        "evidence_ref_not_provided:E404"
    ]


def test_verifier_preserves_model_partial_when_ref_is_valid() -> None:
    chunks, documents, temporal = _artifacts()
    units = build_simple_evidence_units(
        ["c1"],
        chunks_by_id=chunks,
        documents_by_id=documents,
        temporal_by_document=temporal,
    )

    verified = verify_simple_evidence_ref_output(
        {
            "question_time_scope": "current",
            "result": {
                "status": "partial",
                "answer": "장비 초월",
                "evidence_refs": ["E1"],
            },
        },
        question="초월 종류와 비용",
        evidence_units=units,
        chunks_by_id=chunks,
    )

    assert verified["response_mode"] == "partial_answer"
