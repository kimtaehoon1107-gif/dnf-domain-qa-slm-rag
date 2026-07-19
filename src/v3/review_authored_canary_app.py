from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.collect_details import _serialize_jsonl
from src.v3.prepare_authored_canary import (
    DEFAULT_CONTRACT,
    DEFAULT_SOURCE,
    REVIEW_DECISIONS,
    apply_review,
    finalize_independent_review,
    validate_review_row,
    validate_review_structure,
)
APP_VERSION = "authored-canary-independent-review-app-v3.1.0"
DEFAULT_APP_SOURCE = Path("src/v3/review_authored_canary_app.py")

DECISION_LABELS = {
    "approve": "질문·gold·근거·시간 상태 승인",
    "reject": "하나 이상 잘못되어 기각",
}
LABEL_TO_DECISION = {label: decision for decision, label in DECISION_LABELS.items()}


def atomic_write_canary_draft(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=path.parent, prefix=path.name + ".tmp."
        ) as handle:
            handle.write(payload)
            handle.flush()
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return hashlib.sha256(payload).hexdigest()


def load_session(
    packet_path: Path, draft_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    packet = read_jsonl(packet_path)
    if not packet:
        raise RuntimeError("Authored canary candidate packet is empty")
    if draft_path.exists():
        rows = read_jsonl(draft_path)
        validate_review_structure(packet, rows)
        status = f"기존 독립 검수 draft를 불러왔습니다: {draft_path}"
    else:
        rows = copy.deepcopy(packet)
        status = "새 독립 검수 세션입니다. 첫 저장 전에는 draft를 만들지 않습니다."
    return packet, rows, status


def review_progress(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    invalid = 0
    for row in rows:
        decision = row["independent_review_decision"]
        if decision not in REVIEW_DECISIONS:
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
        "decision_counts": {decision: counts[decision] for decision in REVIEW_DECISIONS},
    }


def progress_markdown(rows: list[dict[str, Any]]) -> str:
    progress = review_progress(rows)
    counts = progress["decision_counts"]
    return (
        f"**진행:** {progress['reviewed']}/{progress['total']} · "
        f"남음 {progress['remaining']} · 승인 {counts['approve']} · "
        f"기각 {counts['reject']} · 수정 필요 {progress['invalid']}"
    )


def _evidence_text(row: dict[str, Any]) -> str:
    if not row["evidence_groups"]:
        return "이 slot은 evidence 비노출이 정답인 false/realtime 통제입니다."
    blocks = []
    for group in row["evidence_groups"]:
        expected = group["expected_evidence"][0]
        blocks.append(
            f"[{group['group_id']}]\n"
            f"결정적 span: {group['evidence_span']}\n\n"
            f"문서: {expected['title']}\n"
            f"URL: {expected['canonical_url']}\n"
            f"chunk_id: {expected['chunk_id']}\n"
            f"status/default_exposure: {expected['status']}/{expected['default_exposure']}\n"
            f"valid_from/valid_to: {expected['valid_from']}/{expected['valid_to']}\n\n"
            f"{expected['display_text']}"
        )
    return "\n\n---\n\n".join(blocks)


def item_view(rows: list[dict[str, Any]], index: int) -> tuple[Any, ...]:
    row = rows[index]
    metadata = json.dumps(
        {
            "candidate_id": row["candidate_id"],
            "slot_id": row["slot_id"],
            "source_id": row["source_id"],
            "query_kind": row["query_kind"],
            "answerability": row["answerability"],
            "time_scope": row["time_scope"],
            "as_of": row["as_of"],
            "expected_route_action": row["expected_route_action"],
            "required_evidence_group_count": row["required_evidence_group_count"],
            "dev_parent_disjoint_required": row["dev_parent_disjoint_required"],
            "dev_chunk_disjoint_required": row["dev_chunk_disjoint_required"],
            "dev_claim_disjoint_required": row["dev_claim_disjoint_required"],
            "disjointness_exception_reason": row["disjointness_exception_reason"],
            "independence_level": row["independence_level"],
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        f"항목 {index + 1}/{len(rows)} · `{row['candidate_id']}`",
        row["question_text"],
        metadata,
        row["gold_answer"],
        _evidence_text(row),
        DECISION_LABELS.get(row["independent_review_decision"]),
        row["independent_reviewer_id"] or "",
        row["independent_review_rationale"] or "",
    )


def next_review_index(
    rows: list[dict[str, Any]], current_index: int, direction: int
) -> int:
    if direction == 0:
        return current_index
    step = 1 if direction > 0 else -1
    for index in range(current_index + step, len(rows) if step > 0 else -1, step):
        if rows[index]["independent_review_decision"] is None:
            return index
    return min(max(current_index + step, 0), len(rows) - 1)


def save_and_move(
    packet_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    index: int,
    decision_label: str | None,
    reviewer_id: str,
    rationale: str,
    delta: int,
    draft_path: Path,
) -> tuple[Any, ...]:
    decision = LABEL_TO_DECISION.get(decision_label or "")
    if decision is None:
        raise RuntimeError("승인 또는 기각을 선택하세요.")
    updated = apply_review(rows, index, decision, reviewer_id, rationale)
    validate_review_structure(packet_rows, updated)
    draft_sha = atomic_write_canary_draft(draft_path, updated)
    next_index = next_review_index(updated, index, delta)
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
            rationale,
            delta,
            draft_path,
        )
    except RuntimeError as exc:
        current = item_view(rows, index)
        return (
            rows,
            index,
            *current[:5],
            decision_label,
            reviewer_id,
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
    start_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row["independent_review_decision"] is None
        ),
        0,
    )
    initial = item_view(rows, start_index)
    with gr.Blocks(title="DNF RAG v3 authored canary 독립 검수") as demo:
        gr.Markdown("# DNF RAG v3 Authored Canary 독립 검수")
        gr.Markdown(
            "이 세트는 independent holdout이 아니라 authored canary candidate입니다. "
            "질문이 원문 제목을 그대로 옮기지 않았는지, gold가 질문의 모든 요구를 "
            "지지하는지, evidence span과 날짜·status가 맞는지 확인하세요. 하나라도 "
            "틀리면 승인하지 말고 기각 사유를 남기세요. retrieval 결과는 실행하지 않습니다."
        )
        rows_state = gr.State(rows)
        index_state = gr.State(start_index)
        progress = gr.Markdown(progress_markdown(rows))
        item_header = gr.Markdown(initial[0])
        question = gr.Textbox(value=initial[1], label="작성된 질문", lines=3, interactive=False)
        metadata = gr.Code(value=initial[2], label="slot·시간·분리 메타데이터", language="json")
        gold_answer = gr.Textbox(value=initial[3], label="작성된 gold answer", lines=5, interactive=False)
        evidence = gr.Textbox(value=initial[4], label="공식 근거 및 결정적 span", lines=18, interactive=False)
        with gr.Row():
            decision = gr.Dropdown(
                choices=list(DECISION_LABELS.values()),
                value=initial[5],
                label="독립 검수 판정",
            )
            reviewer_id = gr.Textbox(value=initial[6], label="사람 reviewer ID")
        rationale = gr.Textbox(
            value=initial[7],
            label="독립 검수 사유 (10자 이상, 물음표 치환 손상 금지)",
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
            gold_answer,
            evidence,
            decision,
            reviewer_id,
            rationale,
            progress,
            status,
        ]
        inputs = [rows_state, index_state, decision, reviewer_id, rationale]

        def callback(delta: int):
            def save_callback(*values):
                return save_and_move_with_feedback(
                    packet_rows, *values, delta=delta, draft_path=draft_path
                )

            return save_callback

        previous_button.click(callback(-1), inputs=inputs, outputs=outputs)
        save_button.click(callback(0), inputs=inputs, outputs=outputs)
        next_button.click(callback(1), inputs=inputs, outputs=outputs)

        def export_callback(current_rows):
            try:
                result = finalize_independent_review(
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
    parser = argparse.ArgumentParser(description="Review authored v3 canary candidates")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--builder-source", type=Path, default=root / DEFAULT_SOURCE)
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
