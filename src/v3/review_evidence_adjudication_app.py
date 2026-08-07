from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.prepare_evidence_adjudication import (
    DECISIONS,
    REVIEW_FIELDS,
    DEFAULT_BUILDER_SOURCE,
    DEFAULT_CONTRACT,
    apply_review,
    finalize_evidence_adjudication,
    validate_review_row,
    validate_review_structure,
)
from src.v3.review_entailment_app import atomic_write_draft


APP_VERSION = "evidence-adjudication-review-app-v3.1.1"
DEFAULT_APP_SOURCE = Path("src/v3/review_evidence_adjudication_app.py")


DECISION_LABELS = {
    "accept_alternative": "후보도 유효한 대안 근거",
    "reject_alternative": "후보 근거 불충분",
    "confirm_search_failure": "gold를 확장하지 않고 검색 실패 확정",
}
LABEL_TO_DECISION = {label: decision for decision, label in DECISION_LABELS.items()}


def load_session(
    packet_path: Path, draft_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    packet = read_jsonl(packet_path)
    if not packet:
        raise RuntimeError("Evidence adjudication packet is empty")
    if draft_path.exists():
        rows = read_jsonl(draft_path)
        validate_review_structure(packet, rows)
        status = f"기존 draft를 불러왔습니다: {draft_path}"
    else:
        rows = copy.deepcopy(packet)
        status = "새 검수 세션입니다. 첫 저장 전에는 draft를 만들지 않습니다."
    return packet, rows, status


def review_progress(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    invalid = 0
    for row in rows:
        decision = row["review_decision"]
        if decision not in DECISIONS:
            continue
        try:
            validate_review_row(row, complete=True)
        except RuntimeError:
            invalid += 1
            continue
        counts[decision] += 1
    reviewed = sum(counts.values())
    return {
        "total": len(rows),
        "reviewed": reviewed,
        "remaining": len(rows) - reviewed,
        "invalid": invalid,
        "decision_counts": {decision: counts[decision] for decision in DECISIONS},
    }


def progress_markdown(rows: list[dict[str, Any]]) -> str:
    progress = review_progress(rows)
    counts = progress["decision_counts"]
    return (
        f"**진행:** {progress['reviewed']}/{progress['total']} · "
        f"남음 {progress['remaining']} · 대안 승인 {counts['accept_alternative']} · "
        f"후보 기각 {counts['reject_alternative']} · "
        f"검색 실패 확정 {counts['confirm_search_failure']} · "
        f"수정 필요 {progress['invalid']}"
    )


def _expected_evidence_text(row: dict[str, Any]) -> str:
    blocks = []
    for expected in row["current_expected_evidence"]:
        blocks.append(
            f"[{expected['chunk_id']}] {expected['title']}\n"
            f"{expected['canonical_url']}\n\n{expected['display_text']}"
        )
    return "\n\n---\n\n".join(blocks)


def item_view(rows: list[dict[str, Any]], index: int) -> tuple[Any, ...]:
    row = rows[index]
    metadata = json.dumps(
        {
            "case_id": row["case_id"],
            "time_scope": row["time_scope"],
            "as_of": row["as_of"],
            "source_ids": row["source_ids"],
            "mismatch_reason": row["mismatch_reason"],
            "candidate_chunk_id": row["candidate_chunk_id"],
            "candidate_title": row["candidate_title"],
            "candidate_url": row["candidate_url"],
            "candidate_status": row["candidate_status"],
            "candidate_default_exposure": row["candidate_default_exposure"],
        },
        ensure_ascii=False,
        indent=2,
    )
    decision = row["review_decision"]
    return (
        f"항목 {index + 1}/{len(rows)} · `{row['item_id']}`",
        row["question"],
        metadata,
        row["current_gold_answer"],
        row["current_evidence_span"],
        _expected_evidence_text(row),
        row["candidate_preferred_quote"],
        row["candidate_evidence_text"],
        DECISION_LABELS.get(decision),
        row["reviewer_id"] or "",
        row["decisive_excerpt"] or "",
        row["review_rationale"] or "",
    )


def save_and_move(
    packet_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    index: int,
    decision_label: str | None,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    delta: int,
    draft_path: Path,
) -> tuple[Any, ...]:
    decision = LABEL_TO_DECISION.get(decision_label or "")
    if decision is None:
        raise RuntimeError("세 가지 근거 판정 중 하나를 선택하세요.")
    updated = apply_review(
        rows,
        index,
        decision,
        reviewer_id,
        decisive_excerpt,
        rationale,
    )
    validate_review_structure(packet_rows, updated)
    draft_sha = atomic_write_draft(draft_path, updated)
    next_index = min(max(index + delta, 0), len(updated) - 1)
    return (
        updated,
        next_index,
        *item_view(updated, next_index),
        progress_markdown(updated),
        f"저장 완료 · draft SHA-256 `{draft_sha}`",
    )


def save_and_move_with_feedback(
    packet_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    index: int,
    decision_label: str | None,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    delta: int,
    draft_path: Path,
) -> tuple[Any, ...]:
    try:
        return save_and_move(
            packet_rows,
            rows,
            index,
            decision_label,
            reviewer_id,
            decisive_excerpt,
            rationale,
            delta,
            draft_path,
        )
    except RuntimeError as exc:
        current = item_view(rows, index)
        return (
            rows,
            index,
            *current[:8],
            decision_label,
            reviewer_id,
            decisive_excerpt,
            rationale,
            progress_markdown(rows),
            f"⚠️ **저장되지 않았습니다:** {exc}",
        )


def build_ui(
    root: Path,
    packet_path: Path,
    draft_path: Path,
    builder_source_path: Path,
    app_source_path: Path,
    contract_path: Path,
):
    import gradio as gr

    packet_rows, rows, load_status = load_session(packet_path, draft_path)
    initial = item_view(rows, 0)
    with gr.Blocks(title="DNF RAG v3 근거 재판정") as demo:
        gr.Markdown("# DNF RAG v3 남은 Evidence 재판정")
        gr.Markdown(
            "후보 공식 청크가 질문을 완전히 지지하는지 판정합니다. "
            "후보도 완전히 맞으면 acceptable sibling으로만 추가하고, 핵심 조건을 "
            "빠뜨리면 후보 기각을 선택하세요. routed candidates에 gold가 없으면 "
            "gold를 넓히지 말고 검색 실패로 확정합니다."
        )
        rows_state = gr.State(rows)
        index_state = gr.State(0)
        progress = gr.Markdown(progress_markdown(rows))
        item_header = gr.Markdown(initial[0])
        question = gr.Textbox(value=initial[1], label="질문", interactive=False)
        metadata = gr.Code(value=initial[2], label="판정 메타데이터", language="json")
        current_answer = gr.Textbox(
            value=initial[3], label="현재 gold answer", lines=3, interactive=False
        )
        current_span = gr.Textbox(
            value=initial[4], label="현재 expected evidence span", lines=3, interactive=False
        )
        expected_evidence = gr.Textbox(
            value=initial[5], label="현재 expected 전체 청크", lines=10, interactive=False
        )
        candidate_quote = gr.Textbox(
            value=initial[6], label="재랭커가 선택한 후보 문구", lines=5, interactive=False
        )
        candidate_evidence = gr.Textbox(
            value=initial[7], label="후보 공식 evidence 전체", lines=14, interactive=False
        )
        with gr.Row():
            decision = gr.Dropdown(
                choices=list(DECISION_LABELS.values()),
                value=initial[8],
                label="판정",
            )
            reviewer_id = gr.Textbox(value=initial[9], label="사람 reviewer ID")
        decisive_excerpt = gr.Textbox(
            value=initial[10],
            label="결정적 후보 근거 문구 (대안 승인 시 후보 evidence에서 정확히 복사)",
            lines=3,
        )
        rationale = gr.Textbox(
            value=initial[11],
            label="검수 사유 (10자 이상, 물음표 치환 손상 금지)",
            lines=4,
        )
        with gr.Row():
            previous_button = gr.Button("저장 후 이전")
            save_button = gr.Button("현재 항목 저장", variant="primary")
            next_button = gr.Button("저장 후 다음")
            export_button = gr.Button(f"{len(rows)}개 검증 및 immutable export")
        status = gr.Markdown(load_status)

        outputs = [
            rows_state,
            index_state,
            item_header,
            question,
            metadata,
            current_answer,
            current_span,
            expected_evidence,
            candidate_quote,
            candidate_evidence,
            decision,
            reviewer_id,
            decisive_excerpt,
            rationale,
            progress,
            status,
        ]
        inputs = [
            rows_state,
            index_state,
            decision,
            reviewer_id,
            decisive_excerpt,
            rationale,
        ]

        def callback(delta: int):
            def save_callback(*values):
                return save_and_move_with_feedback(
                    packet_rows,
                    *values,
                    delta=delta,
                    draft_path=draft_path,
                )

            return save_callback

        previous_button.click(callback(-1), inputs=inputs, outputs=outputs)
        save_button.click(callback(0), inputs=inputs, outputs=outputs)
        next_button.click(callback(1), inputs=inputs, outputs=outputs)

        def export_callback(current_rows):
            try:
                result = finalize_evidence_adjudication(
                    root,
                    packet_path,
                    current_rows,
                    builder_source_path,
                    app_source_path,
                    contract_path,
                )
                return "✅ export 완료\n\n```json\n" + json.dumps(
                    result, ensure_ascii=False, indent=2
                ) + "\n```"
            except RuntimeError as exc:
                return f"⚠️ **export 실패:** {exc}"

        export_button.click(export_callback, inputs=[rows_state], outputs=[status])
    return demo


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Review v3 evidence adjudication")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE)
    parser.add_argument("--app-source", type=Path, default=root / DEFAULT_APP_SOURCE)
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    parser.add_argument("--server-name", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=7861)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    app = build_ui(
        root,
        (root / args.packet).resolve() if not args.packet.is_absolute() else args.packet,
        (root / args.draft).resolve() if not args.draft.is_absolute() else args.draft,
        args.builder_source.resolve(),
        args.app_source.resolve(),
        args.contract.resolve(),
    )
    app.launch(server_name=args.server_name, server_port=args.server_port, share=False)


if __name__ == "__main__":
    main()
