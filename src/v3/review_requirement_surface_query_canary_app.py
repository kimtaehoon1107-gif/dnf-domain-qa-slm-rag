from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


APP_VERSION = "requirement-surface-query-canary-review-app-v1.2.0"
DEFAULT_PACKET = Path(
    "data/v3/evaluation/requirement_surface_query_canary_candidate_"
    "8c2db240572c315c72724a3c05fc83dcd23c718dabaffd1b76e530924b486d95.jsonl"
)
ALLOWED_DECISIONS = {"approve", "reject"}
REQUIRED_REVIEW_COUNT = 32
BLOCKED_EXECUTION_FIELDS = (
    "sealed_scoring_allowed",
    "final_benchmark_eligible",
    "independent_holdout_claim_allowed",
    "training_allowed",
)
KST = timezone(timedelta(hours=9))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write_draft(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=path.parent, prefix=path.name + ".tmp."
        ) as handle:
            handle.write(payload)
            handle.flush()
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return _sha256_bytes(payload)


def validate_draft_structure(
    packet_rows: list[dict[str, Any]], draft_rows: list[dict[str, Any]]
) -> None:
    if len(packet_rows) != len(draft_rows):
        raise RuntimeError("Review draft row count differs from candidate packet")
    packet_by_id = {row["candidate_id"]: row for row in packet_rows}
    draft_by_id = {row.get("candidate_id"): row for row in draft_rows}
    if set(packet_by_id) != set(draft_by_id):
        raise RuntimeError("Review draft candidate IDs differ from packet")
    mutable = {
        "human_review_decision",
        "human_reviewer_id",
        "human_reviewed_at",
        "human_review_rationale",
    }
    for candidate_id, packet in packet_by_id.items():
        draft = draft_by_id[candidate_id]
        if set(packet) != set(draft):
            raise RuntimeError(f"Review draft schema changed: {candidate_id}")
        for key in set(packet) - mutable:
            if packet[key] != draft[key]:
                raise RuntimeError(f"Immutable candidate field changed: {key}")


def apply_review(
    rows: list[dict[str, Any]],
    index: int,
    *,
    decision: str,
    reviewer_id: str,
    rationale: str,
) -> list[dict[str, Any]]:
    if decision not in ALLOWED_DECISIONS:
        raise RuntimeError("승인 또는 기각을 선택하세요.")
    reviewer_id = reviewer_id.strip()
    if not reviewer_id:
        raise RuntimeError("검수자 ID를 입력하세요.")
    rationale = rationale.strip()
    if decision == "reject" and not rationale:
        raise RuntimeError("기각 사유를 입력하세요.")
    updated = copy.deepcopy(rows)
    row = updated[index]
    row["human_review_decision"] = decision
    row["human_reviewer_id"] = reviewer_id
    row["human_reviewed_at"] = datetime.now(KST).isoformat()
    row["human_review_rationale"] = rationale or "질문·요구·근거·적용/우회 기대를 확인함"
    return updated


def review_progress(rows: list[dict[str, Any]]) -> dict[str, int]:
    approved = sum(row["human_review_decision"] == "approve" for row in rows)
    rejected = sum(row["human_review_decision"] == "reject" for row in rows)
    return {"approved": approved, "rejected": rejected, "pending": len(rows) - approved - rejected}


def review_export_ready(rows: list[dict[str, Any]]) -> bool:
    progress = review_progress(rows)
    return (
        len(rows) == REQUIRED_REVIEW_COUNT
        and progress
        == {"approved": REQUIRED_REVIEW_COUNT, "rejected": 0, "pending": 0}
    )


def render_row(row: dict[str, Any]) -> str:
    requirement_lines = [
        f"- `{req['requirement_id']}` **{req['subject']} — {req['relation']}** "
        f"(표면: `{req['surface']}`, 값 유형: `{req['value_type']}`)"
        for req in row["requirements"]
    ]
    evidence_lines = []
    for group in row["evidence_groups"]:
        lines = [
            f"- `{group['group_id']}` → `{group['requirement_id']}`",
            f"  - exact span: `{group['evidence_span']}`",
            f"  - acceptable chunks: `{', '.join(group['acceptable_chunk_ids'])}`",
        ]
        locator = group.get("evidence_locator")
        if locator and locator["kind"] == "table_atomic_value_cell":
            lines.append(
                "  - atomic value cell: "
                f"`{locator['attribute']}` · offsets "
                f"`{locator['start_offset']}:{locator['end_offset']}` · "
                f"fact `{locator['fact_id']}`"
            )
        elif locator and locator["kind"] == "chunk_exact_slice":
            lines.append(
                "  - exact chunk slice: "
                f"`{locator['source_chunk_id']}` · offsets "
                f"`{locator['start_offset']}:{locator['end_offset']}`"
            )
        evidence_lines.extend(lines)
    duplicate_lines = []
    for duplicate in row.get("duplicate_current_evidence", []):
        duplicate_lines.append(
            f"- `{duplicate['group_id']}` `{duplicate['evidence_span']}`"
        )
        duplicate_lines.extend(
            "  - "
            f"[{match['title']}]({match['canonical_url']}) · "
            f"{match.get('published_at') or '날짜 없음'} · `{match['match_kind']}`"
            for match in duplicate["matches"]
        )
    if not duplicate_lines:
        duplicate_lines = ["- 다른 current 문서의 동일 근거 없음"]
    exception = row["parent_disjointness_exception_reason"] or "없음"
    return "\n".join(
        [
            f"### {row['slot_ordinal']}/32 · {row['source_id']} · {row['stratum']}",
            "",
            f"**질문:** {row['question_text']}",
            "",
            f"**기대 동작:** `{row['expected_surface_query_action']}` / 작성 요구로 계산한 동작: "
            f"`{row['actual_surface_query_action_from_authored_requirements']}`",
            "",
            f"**문서:** [{row['title']}]({row['canonical_url']})",
            "",
            "**Atomic requirements**",
            "",
            *requirement_lines,
            "",
            "**Evidence groups**",
            "",
            *evidence_lines,
            "",
            "**Current-document duplicate scan**",
            "",
            *duplicate_lines,
            "",
            f"**Sibling 검수 플래그:** `{row.get('sibling_review_required', False)}` / "
            f"처리: `{row.get('duplicate_resolution') or '해당 없음'}`",
            "",
            f"**기존 평가 parent 분리 예외:** {exception}",
        ]
    )


def finalize_review(
    *, root: Path, packet_path: Path, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    root = root.resolve()
    packet_path = packet_path.resolve()
    packet = read_jsonl(packet_path)
    validate_draft_structure(packet, rows)
    progress = review_progress(rows)
    if not review_export_ready(rows):
        raise RuntimeError(
            f"32개 전부 승인되어야 export할 수 있습니다: {progress}"
        )

    reviewed = []
    for source in sorted(rows, key=lambda row: row["slot_ordinal"]):
        row = copy.deepcopy(source)
        row["review_schema_version"] = "requirement-surface-query-human-reviewed-v1"
        row["review_status"] = "user_full_review_approved"
        for field in BLOCKED_EXECUTION_FIELDS:
            if row.get(field) is not False:
                raise RuntimeError(f"Reviewed export must keep {field}=false")
        reviewed.append(row)
    payload = _serialize_jsonl(reviewed, lambda row: row["slot_ordinal"])
    payload_sha = _sha256_bytes(payload)
    output_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_reviewed_{payload_sha}.jsonl"
    )
    write_immutable(output_path, payload)

    manifest = {
        "manifest_schema_version": "requirement-surface-query-reviewed-manifest-v1",
        "app_version": APP_VERSION,
        "candidate_packet": {
            "path": packet_path.relative_to(root).as_posix(),
            "sha256": file_sha256(packet_path),
        },
        "reviewed_export": {
            "path": output_path.relative_to(root).as_posix(),
            "sha256": payload_sha,
            "row_count": len(reviewed),
        },
        "review": {
            "progress": progress,
            "reviewer_ids": sorted({row["human_reviewer_id"] for row in reviewed}),
            "independent_holdout_claim_allowed": False,
        },
        "execution": {
            "sealed_run_count_allowed": 0,
            "sealed_scoring_allowed": False,
            "sealed_run_performed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_reviewed_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    return {
        "reviewed_path": str(output_path),
        "reviewed_sha256": payload_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "sealed_run_performed": False,
    }


def build_app(*, root: Path, packet_path: Path, draft_path: Path) -> Any:
    import gradio as gr

    packet = read_jsonl(packet_path)
    if not packet:
        raise RuntimeError("Candidate packet is empty")
    if draft_path.exists():
        rows = read_jsonl(draft_path)
        validate_draft_structure(packet, rows)
    else:
        rows = copy.deepcopy(packet)

    def view(state_rows: list[dict[str, Any]], index: int) -> tuple[Any, ...]:
        index = max(0, min(int(index), len(state_rows) - 1))
        row = state_rows[index]
        progress = review_progress(state_rows)
        decision = row["human_review_decision"]
        return (
            index,
            render_row(row),
            decision,
            row["human_reviewer_id"] or "",
            row["human_review_rationale"] or "",
            f"승인 {progress['approved']} · 기각 {progress['rejected']} · 대기 {progress['pending']}",
        )

    def move(state_rows: list[dict[str, Any]], index: int, delta: int) -> tuple[Any, ...]:
        return view(state_rows, int(index) + delta)

    def save(
        state_rows: list[dict[str, Any]],
        index: int,
        decision: str,
        reviewer_id: str,
        rationale: str,
    ) -> tuple[Any, ...]:
        try:
            updated = apply_review(
                state_rows,
                int(index),
                decision=decision,
                reviewer_id=reviewer_id,
                rationale=rationale,
            )
            draft_sha = atomic_write_draft(draft_path, updated)
            rendered = view(updated, int(index) + 1)
            return (updated, *rendered, f"저장됨 · draft SHA {draft_sha[:12]}…")
        except Exception as exc:
            rendered = view(state_rows, int(index))
            return (state_rows, *rendered, f"오류: {exc}")

    def export(state_rows: list[dict[str, Any]]) -> str:
        try:
            result = finalize_review(root=root, packet_path=packet_path, rows=state_rows)
            return "검수 export 완료: " + json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"export 차단: {exc}"

    with gr.Blocks(title="Requirement surface-query canary 검수") as app:
        gr.Markdown(
            "# Requirement surface-query canary 전수 검수\n"
            "32개 전부 승인되기 전에는 sealed 평가가 실행되지 않습니다. "
            "이 세트는 authored feature canary이며 independent holdout이 아닙니다."
        )
        state = gr.State(rows)
        index = gr.State(0)
        content = gr.Markdown(render_row(rows[0]))
        decision = gr.Radio(
            choices=[("승인", "approve"), ("기각", "reject")],
            label="검수 결정",
        )
        reviewer = gr.Textbox(label="검수자 ID")
        rationale = gr.Textbox(label="검수 메모/기각 사유", lines=3)
        progress = gr.Markdown("승인 0 · 기각 0 · 대기 32")
        status = gr.Markdown()
        with gr.Row():
            previous = gr.Button("이전")
            save_button = gr.Button("저장 후 다음", variant="primary")
            next_button = gr.Button("다음")
            export_button = gr.Button("32개 승인본 immutable export")
        view_outputs = [index, content, decision, reviewer, rationale, progress]
        previous.click(lambda r, i: move(r, i, -1), [state, index], view_outputs)
        next_button.click(lambda r, i: move(r, i, 1), [state, index], view_outputs)
        save_button.click(
            save,
            [state, index, decision, reviewer, rationale],
            [state, *view_outputs, status],
        )
        export_button.click(export, [state], [status])
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--port", type=int, default=7862)
    args = parser.parse_args()
    root = args.root.resolve()
    packet = args.packet if args.packet.is_absolute() else root / args.packet
    packet_sha = file_sha256(packet)
    draft = args.draft or (
        root
        / "outputs/v3/annotation"
        / f"requirement_surface_query_canary_review_draft_{packet_sha}.jsonl"
    )
    if not draft.is_absolute():
        draft = root / draft
    build_app(root=root, packet_path=packet, draft_path=draft).launch(
        server_name="127.0.0.1", server_port=args.port
    )


if __name__ == "__main__":
    main()
