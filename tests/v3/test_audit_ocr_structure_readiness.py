from __future__ import annotations

from src.v3.audit_ocr_structure_readiness import audit_readiness


def _visual_chunk() -> dict:
    return {
        "chunk_id": "visual_chunk",
        "offset_source": "visual_ocr",
        "review_required": True,
        "default_exposure": False,
        "evidence_quality": "unverified_ocr",
    }


def test_text_only_ocr_without_visual_gold_is_not_ready() -> None:
    audit = audit_readiness(
        [{"ocr_text": "이벤트 기간"}],
        [{"ocr_text": "이벤트 기간", "ocr_status": "success"}],
        [_visual_chunk()],
        [],
    )

    assert audit["assets_with_layout_coordinates"] == 0
    assert audit["visual_gold_group_count"] == 0
    assert audit["executable_ab"] is False
    assert audit["decision"] == "SKIP_NO_GO_MISSING_LAYOUT_AND_EVAL_GOLD"


def test_layout_and_visual_gold_make_ab_executable_without_changing_safety() -> None:
    audit = audit_readiness(
        [{"ocr_text": "이벤트 기간"}],
        [{"ocr_text": "이벤트 기간", "word_boxes": [[0, 0, 10, 10]]}],
        [_visual_chunk()],
        [
            {
                "dev_id": "case",
                "evidence_groups": [
                    {"group_id": "evidence_1", "acceptable_chunk_ids": ["visual_chunk"]}
                ],
            }
        ],
    )

    assert audit["executable_ab"] is True
    assert audit["safety"]["all_visual_chunks_default_exposure_false"] is True
