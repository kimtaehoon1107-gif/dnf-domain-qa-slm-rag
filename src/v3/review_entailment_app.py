from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.prepare_entailment_review import (
    LABELS,
    RESERVED_REVIEWER_IDS,
    REVIEW_FIELDS,
    audit_completed_reviews,
)


APP_VERSION = "entailment-human-review-app-v3.1.0"
EXPORT_MANIFEST_SCHEMA_VERSION = "entailment-human-review-manifest-v3.1"
SMOKE_REPORT_SCHEMA_VERSION = "entailment-human-review-ui-smoke-v3.1"

DEFAULT_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_packet_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl"
)
DEFAULT_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_natural_review_draft_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl"
)
DEFAULT_APP_SOURCE = Path("src/v3/review_entailment_app.py")
DEFAULT_PACKET_MANIFEST = Path(
    "data/v3/evaluation/"
    "entailment_natural_review_manifest_0a318f692c2c7c3e761b06dd4a10959b4fcf25f4b59adbf9597b3fc1180eb49e.json"
)
DEFAULT_REVIEW_CONTRACT = Path("docs/v3/entailment_natural_review.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def validate_draft_structure(
    packet_rows: list[dict[str, Any]], draft_rows: list[dict[str, Any]]
) -> None:
    packet_by_id = {row["item_id"]: row for row in packet_rows}
    draft_by_id = {row.get("item_id"): row for row in draft_rows}
    if len(packet_by_id) != len(packet_rows) or len(draft_by_id) != len(draft_rows):
        raise RuntimeError("Duplicate review item_id")
    if set(packet_by_id) != set(draft_by_id):
        raise RuntimeError("Draft item IDs differ from frozen packet")
    for item_id, packet in packet_by_id.items():
        draft = draft_by_id[item_id]
        if set(draft) != set(packet):
            raise RuntimeError(f"Draft schema differs for {item_id}")
        for key in set(packet) - REVIEW_FIELDS:
            if draft[key] != packet[key]:
                raise RuntimeError(f"Draft changed immutable field {key}: {item_id}")


def load_session(
    packet_path: Path, draft_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    packet_rows = read_jsonl(packet_path)
    if not packet_rows:
        raise RuntimeError("Frozen review packet is empty")
    if draft_path.exists():
        draft_rows = read_jsonl(draft_path)
        validate_draft_structure(packet_rows, draft_rows)
        status = f"기존 draft를 불러왔습니다: {draft_path}"
    else:
        draft_rows = copy.deepcopy(packet_rows)
        status = "새 검수 세션입니다. 첫 저장 전에는 파일을 만들지 않습니다."
    return packet_rows, draft_rows, status


def atomic_write_draft(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_jsonl(rows, lambda row: row["item_ordinal"])
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
    return _sha256_bytes(payload)


def _validate_form(
    row: dict[str, Any],
    label: str | None,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    needs_adjudication: bool,
) -> None:
    if label not in LABELS:
        raise RuntimeError("support / contradiction / insufficient 중 하나를 선택하세요.")
    normalized_reviewer = reviewer_id.strip()
    if (
        not normalized_reviewer
        or normalized_reviewer.casefold() in RESERVED_REVIEWER_IDS
    ):
        raise RuntimeError("실제 사람 reviewer ID를 입력하세요.")
    if len(rationale.strip()) < 10:
        raise RuntimeError("검수 사유를 10자 이상 입력하세요.")
    if not isinstance(needs_adjudication, bool):
        raise RuntimeError("adjudication 여부가 올바르지 않습니다.")
    excerpt = decisive_excerpt.strip()
    if label in {"support", "contradiction"} and not excerpt:
        raise RuntimeError("support/contradiction에는 evidence의 정확한 문구가 필요합니다.")
    if excerpt and _normalized_text(excerpt) not in _normalized_text(row["evidence_text"]):
        raise RuntimeError("근거 문구가 evidence_text에 정확히 존재하지 않습니다.")


def apply_review(
    rows: list[dict[str, Any]],
    index: int,
    label: str | None,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    needs_adjudication: bool,
    *,
    reviewed_at: str | None = None,
) -> list[dict[str, Any]]:
    if not 0 <= index < len(rows):
        raise RuntimeError("Review index is out of range")
    output = copy.deepcopy(rows)
    row = output[index]
    _validate_form(
        row,
        label,
        reviewer_id,
        decisive_excerpt,
        rationale,
        needs_adjudication,
    )
    row.update(
        {
            "review_label": label,
            "reviewer_type": "human",
            "reviewer_id": reviewer_id.strip(),
            "reviewed_at": reviewed_at or datetime.now().astimezone().isoformat(),
            "decisive_excerpt": decisive_excerpt.strip() or None,
            "review_rationale": rationale.strip(),
            "needs_adjudication": needs_adjudication,
        }
    )
    return output


def review_progress(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(
        row["review_label"] for row in rows if row["review_label"] in LABELS
    )
    reviewed_count = sum(labels.values())
    adjudication_count = sum(row["needs_adjudication"] is True for row in rows)
    return {
        "total": len(rows),
        "reviewed": reviewed_count,
        "remaining": len(rows) - reviewed_count,
        "label_counts": {label: labels[label] for label in LABELS},
        "adjudication_pending": adjudication_count,
    }


def progress_markdown(rows: list[dict[str, Any]]) -> str:
    progress = review_progress(rows)
    return (
        f"**진행:** {progress['reviewed']}/{progress['total']} · "
        f"남음 {progress['remaining']} · "
        f"support {progress['label_counts']['support']} · "
        f"contradiction {progress['label_counts']['contradiction']} · "
        f"insufficient {progress['label_counts']['insufficient']} · "
        f"adjudication {progress['adjudication_pending']}"
    )


def item_view(rows: list[dict[str, Any]], index: int) -> tuple[Any, ...]:
    row = rows[index]
    metadata_values = {
        "title": row["evidence_title"],
        "url": row["evidence_url"],
        "source_id": row["evidence_source_id"],
        "status": row["evidence_status"],
        "valid_from": row["evidence_valid_from"],
        "valid_to": row["evidence_valid_to"],
        "claim_as_of": row["claim_as_of"],
        "claim_time_scope": row["claim_time_scope"],
    }
    if "primary_review" in row:
        metadata_values["primary_review"] = row["primary_review"]
    if "adjudication_reasons" in row:
        metadata_values["adjudication_reasons"] = row["adjudication_reasons"]
    if "claim_repair" in row:
        metadata_values["claim_repair"] = row["claim_repair"]
    metadata = json.dumps(metadata_values, ensure_ascii=False, indent=2)
    return (
        f"항목 {index + 1}/{len(rows)} · `{row['item_id']}`",
        row["question"],
        row["claim_text"],
        metadata,
        row["evidence_text"],
        row["review_label"],
        row["reviewer_id"] or "",
        row["decisive_excerpt"] or "",
        row["review_rationale"] or "",
        bool(row["needs_adjudication"]),
    )


def save_and_move(
    packet_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    index: int,
    label: str | None,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    needs_adjudication: bool,
    delta: int,
    draft_path: Path,
) -> tuple[Any, ...]:
    updated = apply_review(
        rows,
        index,
        label,
        reviewer_id,
        decisive_excerpt,
        rationale,
        needs_adjudication,
    )
    validate_draft_structure(packet_rows, updated)
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
    label: str | None,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    needs_adjudication: bool,
    delta: int,
    draft_path: Path,
    skip_value: Any,
) -> tuple[Any, ...]:
    try:
        return save_and_move(
            packet_rows,
            rows,
            index,
            label,
            reviewer_id,
            decisive_excerpt,
            rationale,
            needs_adjudication,
            delta,
            draft_path,
        )
    except RuntimeError as exc:
        # Preserve all form fields so the reviewer can correct only the invalid
        # value. A failed validation never writes the draft or changes the item.
        return (
            rows,
            index,
            *([skip_value] * 10),
            progress_markdown(rows),
            f"⚠️ **저장되지 않았습니다:** {exc}",
        )


def finalize_reviews(
    root: Path,
    packet_path: Path,
    rows: list[dict[str, Any]],
    app_source_path: Path,
) -> dict[str, Any]:
    packet_rows = read_jsonl(packet_path)
    validate_draft_structure(packet_rows, rows)
    audit = audit_completed_reviews(packet_rows, rows)
    if not audit["ready_for_scoring"]:
        details = audit["errors"][:5]
        raise RuntimeError(
            "사람 검수가 아직 scoring 가능 상태가 아닙니다: "
            f"remaining={len(rows) - sum(audit['label_counts'].values())}, "
            f"adjudication={audit['adjudication_pending_count']}, errors={details}"
        )
    evaluation_dir = root / "data/v3/evaluation"
    reviewed_bytes = _serialize_jsonl(rows, lambda row: row["item_ordinal"])
    reviewed_sha = _sha256_bytes(reviewed_bytes)
    reviewed_path = evaluation_dir / f"entailment_natural_human_reviews_{reviewed_sha}.jsonl"
    write_immutable(reviewed_path, reviewed_bytes)
    manifest = {
        "manifest_schema_version": EXPORT_MANIFEST_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "inputs": {
            "packet": {
                "path": _relative(root, packet_path),
                "sha256": file_sha256(packet_path),
            },
            "app_source": {
                "path": _relative(root, app_source_path),
                "sha256": file_sha256(app_source_path),
            },
        },
        "reviews": {
            "path": _relative(root, reviewed_path),
            "sha256": reviewed_sha,
            "row_count": len(rows),
            "reviewer_ids": sorted({row["reviewer_id"] for row in rows}),
            "label_counts": audit["label_counts"],
        },
        "completion_audit": audit,
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "natural_distribution_prevalence_claim": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"entailment_natural_human_review_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "reviews_path": str(reviewed_path),
        "reviews_sha256": reviewed_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "completion_audit": audit,
    }


def freeze_smoke_report(
    root: Path,
    packet_path: Path,
    packet_manifest_path: Path,
    app_source_path: Path,
    review_contract_path: Path,
    draft_path: Path,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    packet_rows = read_jsonl(packet_path)
    progress = review_progress(packet_rows)
    gates = {
        "packet_count_40": len(packet_rows) == 40,
        "packet_hash_matches_filename": file_sha256(packet_path)
        == packet_path.stem.rsplit("_", 1)[1],
        "labels_initially_pending": progress["reviewed"] == 0,
        "draft_under_outputs_v3": _relative(root, draft_path).startswith("outputs/v3/"),
        "immutable_export_under_data_v3": True,
        "localhost_default": True,
        "share_default_false": True,
        "sampling_ledger_not_loaded": True,
        "model_predictions_not_loaded": True,
        "validator_required_before_export": True,
    }
    if not all(gates.values()):
        raise RuntimeError("Entailment review UI smoke gates failed")
    inputs = {
        "packet": packet_path,
        "packet_manifest": packet_manifest_path,
        "app_source": app_source_path,
        "review_contract": review_contract_path,
    }
    report = {
        "report_schema_version": SMOKE_REPORT_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "decision": {
            "ui_contract": "GO",
            "human_review": "PENDING",
            "natural_verifier_evaluation": "NO-GO",
            "production_verifier": "NO-GO",
            "generator_entry": "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "runtime_contract": {
            "server_name_default": "127.0.0.1",
            "server_port_default": 7861,
            "share_default": False,
            "draft_path": _relative(root, draft_path),
            "draft_is_mutable": True,
            "packet_is_read_only": True,
            "export_is_content_addressed": True,
            "export_requires_ready_for_scoring": True,
        },
        "initial_progress": progress,
        "gates": gates,
        "not_performed": [
            "human_label_assignment",
            "model_scoring",
            "generator_integration",
            "final_blind_evaluation",
        ],
    }
    reports_dir = artifact_root / "reports/v3"
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_review_ui_smoke_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Entailment Human Review UI Smoke

## Decision

- UI contract: **GO**
- Human review: **PENDING**
- Natural Verifier evaluation: **NO-GO**
- Production Verifier / Generator: **NO-GO**

The UI loads 40 frozen review rows, does not load the sampling ledger or model predictions, writes only a mutable draft under `outputs/v3`, and requires `ready_for_scoring=true` before immutable export. Validation failures preserve the form and show the exact reason in the status area.

Run locally with:

`python src/v3/review_entailment_app.py`

The default server is `127.0.0.1:7861`; sharing is disabled unless explicitly requested.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_review_ui_smoke_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
    }


def build_ui(
    root: Path,
    packet_path: Path,
    draft_path: Path,
    app_source_path: Path,
):
    import gradio as gr

    packet_rows, rows, load_status = load_session(packet_path, draft_path)
    initial = item_view(rows, 0)
    is_adjudication = all(
        "adjudication_of_item_id" in row or "claim_repair" in row for row in rows
    )
    with gr.Blocks(title="DNF RAG v3 사람 검수") as demo:
        heading = (
            "# DNF RAG v3 자연 claim–evidence 재판정"
            if is_adjudication
            else "# DNF RAG v3 자연 claim–evidence 사람 검수"
        )
        gr.Markdown(heading)
        gr.Markdown(
            "표본 출처와 모델 예측은 숨겨져 있습니다. omission은 contradiction이 아니라 insufficient입니다."
        )
        if is_adjudication:
            gr.Markdown(
                "시간·문서 메타데이터의 1차 판단과 재검수 사유를 참고하되, 아래 판정·근거·사유는 새로 입력하세요."
            )
        rows_state = gr.State(rows)
        index_state = gr.State(0)
        progress = gr.Markdown(progress_markdown(rows))
        item_header = gr.Markdown(initial[0])
        question = gr.Textbox(value=initial[1], label="질문", interactive=False)
        claim = gr.Textbox(value=initial[2], label="검증할 claim", interactive=False)
        metadata = gr.Code(value=initial[3], label="시간·문서 메타데이터", language="json")
        evidence = gr.Textbox(
            value=initial[4], label="공식 evidence", lines=18, interactive=False
        )
        with gr.Row():
            label = gr.Dropdown(
                choices=list(LABELS), value=initial[5], label="판정"
            )
            reviewer_id = gr.Textbox(value=initial[6], label="사람 reviewer ID")
            needs_adjudication = gr.Checkbox(
                value=initial[9], label="추가 adjudication 필요"
            )
        decisive_excerpt = gr.Textbox(
            value=initial[7],
            label="결정적 근거 문구 (support/contradiction 필수, evidence에서 정확히 복사)",
            lines=3,
        )
        rationale = gr.Textbox(
            value=initial[8], label="검수 사유 (10자 이상)", lines=4
        )
        with gr.Row():
            previous_button = gr.Button("저장 후 이전")
            save_button = gr.Button("현재 항목 저장", variant="primary")
            next_button = gr.Button("저장 후 다음")
            export_button = gr.Button(
                f"{len(rows)}개 검증 및 immutable export",
                visible=not is_adjudication,
            )
        status = gr.Markdown(load_status)

        view_outputs = [
            rows_state,
            index_state,
            item_header,
            question,
            claim,
            metadata,
            evidence,
            label,
            reviewer_id,
            decisive_excerpt,
            rationale,
            needs_adjudication,
            progress,
            status,
        ]
        save_inputs = [
            rows_state,
            index_state,
            label,
            reviewer_id,
            decisive_excerpt,
            rationale,
            needs_adjudication,
        ]

        def callback(delta: int):
            def save_callback(*values):
                return save_and_move_with_feedback(
                    packet_rows,
                    *values,
                    delta=delta,
                    draft_path=draft_path,
                    skip_value=gr.skip(),
                )

            return save_callback

        previous_button.click(callback(-1), inputs=save_inputs, outputs=view_outputs)
        save_button.click(callback(0), inputs=save_inputs, outputs=view_outputs)
        next_button.click(callback(1), inputs=save_inputs, outputs=view_outputs)

        def export_callback(current_rows):
            result = finalize_reviews(
                root, packet_path, current_rows, app_source_path
            )
            return (
                "Export 완료: "
                f"`{result['reviews_path']}` · SHA-256 `{result['reviews_sha256']}`"
            )

        export_button.click(export_callback, inputs=[rows_state], outputs=[status])
    return demo


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run v3 natural entailment review UI")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--packet", type=Path, default=root / DEFAULT_PACKET)
    parser.add_argument("--draft", type=Path, default=root / DEFAULT_DRAFT)
    parser.add_argument("--app-source", type=Path, default=root / DEFAULT_APP_SOURCE)
    parser.add_argument(
        "--packet-manifest", type=Path, default=root / DEFAULT_PACKET_MANIFEST
    )
    parser.add_argument(
        "--review-contract", type=Path, default=root / DEFAULT_REVIEW_CONTRACT
    )
    parser.add_argument("--server-name", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--freeze-smoke", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    packet_path = args.packet.resolve()
    draft_path = args.draft.resolve()
    app_source_path = args.app_source.resolve()
    if args.freeze_smoke:
        result = freeze_smoke_report(
            root,
            packet_path,
            args.packet_manifest.resolve(),
            app_source_path,
            args.review_contract.resolve(),
            draft_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    packet_rows, rows, status = load_session(packet_path, draft_path)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "app_version": APP_VERSION,
                    "packet_path": _relative(root, packet_path),
                    "packet_sha256": file_sha256(packet_path),
                    "draft_path": _relative(root, draft_path),
                    "draft_exists": draft_path.exists(),
                    "packet_count": len(packet_rows),
                    "progress": review_progress(rows),
                    "load_status": status,
                    "sampling_ledger_loaded": False,
                    "model_predictions_loaded": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    demo = build_ui(root, packet_path, draft_path, app_source_path)
    demo.launch(
        server_name=args.server_name,
        server_port=args.port,
        share=args.share,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
