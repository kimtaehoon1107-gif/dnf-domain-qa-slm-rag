from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)
from src.v3.prepare_entailment_review import RESERVED_REVIEWER_IDS


BUILDER_VERSION = "evidence-adjudication-builder-v3.1.1"
PACKET_SCHEMA_VERSION = "evidence-adjudication-item-v3.1"
OVERLAY_SCHEMA_VERSION = "evidence-adjudication-overlay-v3.1"
MANIFEST_SCHEMA_VERSION = "evidence-adjudication-manifest-v3.1"
REPORT_SCHEMA_VERSION = "evidence-adjudication-report-v3.1"

DECISIONS = (
    "accept_alternative",
    "reject_alternative",
    "confirm_search_failure",
)
REVIEW_FIELDS = {
    "review_decision",
    "reviewer_type",
    "reviewer_id",
    "reviewed_at",
    "decisive_excerpt",
    "review_rationale",
}

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CASES = Path(
    "data/v3/evidence/claim_reranker_cases_"
    "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a.jsonl"
)
DEFAULT_REPORT = Path(
    "reports/v3/claim_reranker_runtime_"
    "f37db5f17f3d20553d14922471c5bf7415ff942b12746dfad6d831a6a0ef1df9.json"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/prepare_evidence_adjudication.py")
DEFAULT_APP_SOURCE = Path("src/v3/review_evidence_adjudication_app.py")
DEFAULT_CONTRACT = Path("docs/v3/evidence_adjudication.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _empty_review_fields(row: dict[str, Any]) -> None:
    for field in REVIEW_FIELDS:
        row[field] = None


def review_text_corruption_fields(row: dict[str, Any]) -> list[str]:
    corrupted = []
    for field in ("review_rationale", "decisive_excerpt"):
        value = row.get(field)
        if isinstance(value, str) and value.count("?") >= 5:
            corrupted.append(field)
    return corrupted


def build_evidence_adjudication_packet(
    dev_rows: list[dict[str, Any]],
    reranker_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    report: dict[str, Any],
    report_sha256: str,
) -> list[dict[str, Any]]:
    dev_by_id = {row["dev_id"]: row for row in dev_rows}
    reranker_by_id = {row["case_id"]: row for row in reranker_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    pending: list[tuple[int, str, dict[str, Any]]] = []
    for mismatch in report["strict_mismatches"]:
        case = reranker_by_id[mismatch["case_id"]]
        for group_id in mismatch["missing_group_ids"]:
            pending.append((case["query_ordinal"], group_id, mismatch))

    packet = []
    for item_ordinal, (_, group_id, mismatch) in enumerate(sorted(pending), 1):
        case_id = mismatch["case_id"]
        dev = dev_by_id[case_id]
        reranker = reranker_by_id[case_id]
        group = next(
            row for row in dev["evidence_groups"] if row["group_id"] == group_id
        )
        chosen_ids = set(mismatch["chosen_chunk_ids"])
        ranked = reranker["reranker"]["ranked_candidates"]
        candidate = next(row for row in ranked if row["chunk_id"] in chosen_ids)
        chunk = chunks_by_id[candidate["chunk_id"]]
        document = documents_by_id[chunk["parent_document_id"]]
        expected_evidence = []
        for chunk_id in group["acceptable_chunk_ids"]:
            expected_chunk = chunks_by_id[chunk_id]
            expected_document = documents_by_id[expected_chunk["parent_document_id"]]
            expected_evidence.append(
                {
                    "chunk_id": chunk_id,
                    "parent_document_id": expected_chunk["parent_document_id"],
                    "title": expected_document["title"],
                    "canonical_url": expected_document["canonical_url"],
                    "display_text": expected_chunk["display_text"],
                }
            )
        identity = _canonical_json_bytes(
            {
                "report_sha256": report_sha256,
                "case_id": case_id,
                "group_id": group_id,
                "candidate_chunk_id": candidate["chunk_id"],
                "expected_chunk_ids": group["acceptable_chunk_ids"],
            }
        )
        row = {
            "review_item_schema_version": PACKET_SCHEMA_VERSION,
            "item_id": f"evidence_adjudication_sha256_{_sha256_bytes(identity)}",
            "item_ordinal": item_ordinal,
            "case_id": case_id,
            "query_ordinal": reranker["query_ordinal"],
            "question": dev["question"],
            "answerability": dev["answerability"],
            "time_scope": dev["time_scope"],
            "as_of": dev["as_of"],
            "source_ids": dev["source_ids"],
            "evidence_group_id": group_id,
            "current_gold_answer": dev["gold_answer"],
            "current_evidence_span": group["evidence_span"],
            "current_acceptable_chunk_ids": group["acceptable_chunk_ids"],
            "current_expected_evidence": expected_evidence,
            "candidate_chunk_id": candidate["chunk_id"],
            "candidate_parent_document_id": chunk["parent_document_id"],
            "candidate_title": document["title"],
            "candidate_url": document["canonical_url"],
            "candidate_source_id": chunk["source_id"],
            "candidate_source_kind": chunk["source_kind"],
            "candidate_status": chunk["status"],
            "candidate_default_exposure": chunk["default_exposure"],
            "candidate_preferred_quote": candidate["preferred_quote"],
            "candidate_evidence_text": chunk["display_text"],
            "mismatch_reason": mismatch["reason"],
            "source_report_sha256": report_sha256,
        }
        _empty_review_fields(row)
        packet.append(row)
    return packet


def validate_review_structure(
    packet_rows: list[dict[str, Any]], reviewed_rows: list[dict[str, Any]]
) -> None:
    packet_by_id = {row["item_id"]: row for row in packet_rows}
    reviewed_by_id = {row.get("item_id"): row for row in reviewed_rows}
    if len(packet_by_id) != len(packet_rows) or len(reviewed_by_id) != len(reviewed_rows):
        raise RuntimeError("Duplicate evidence adjudication item_id")
    if set(packet_by_id) != set(reviewed_by_id):
        raise RuntimeError("Evidence adjudication draft item IDs differ from packet")
    for item_id, packet in packet_by_id.items():
        reviewed = reviewed_by_id[item_id]
        if set(packet) != set(reviewed):
            raise RuntimeError(f"Evidence adjudication schema changed: {item_id}")
        for key in set(packet) - REVIEW_FIELDS:
            if packet[key] != reviewed[key]:
                raise RuntimeError(f"Immutable field changed: {key}: {item_id}")


def validate_review_row(row: dict[str, Any], *, complete: bool) -> None:
    decision = row["review_decision"]
    if decision is None and not complete:
        return
    if decision not in DECISIONS:
        raise RuntimeError("근거 판정 셋 중 하나를 선택하세요.")
    if row["mismatch_reason"] == "acceptable_chunk_not_in_routed_candidates" and (
        decision != "confirm_search_failure"
    ):
        raise RuntimeError("routed candidates에 gold가 없으면 검색 실패로 유지해야 합니다.")
    reviewer_id = (row["reviewer_id"] or "").strip()
    if not reviewer_id or reviewer_id.casefold() in RESERVED_REVIEWER_IDS:
        raise RuntimeError("실제 사람 reviewer ID를 입력하세요.")
    if row["reviewer_type"] != "human" or not row["reviewed_at"]:
        raise RuntimeError("사람 검수 메타데이터가 완전하지 않습니다.")
    if len((row["review_rationale"] or "").strip()) < 10:
        raise RuntimeError("검수 사유를 10자 이상 입력하세요.")
    corrupted_fields = review_text_corruption_fields(row)
    if corrupted_fields:
        raise RuntimeError(
            "검수 문장에 물음표 치환 인코딩 손상이 있습니다: "
            + ", ".join(corrupted_fields)
        )
    excerpt = (row["decisive_excerpt"] or "").strip()
    if decision == "accept_alternative" and not excerpt:
        raise RuntimeError("대안 승인에는 후보 evidence의 결정적 문구가 필요합니다.")
    if decision == "confirm_search_failure" and row["mismatch_reason"] != (
        "acceptable_chunk_not_in_routed_candidates"
    ):
        raise RuntimeError("검색 실패 확정은 routed candidates에 gold가 없을 때만 가능합니다.")
    if excerpt and _normalized_text(excerpt) not in _normalized_text(
        row["candidate_evidence_text"]
    ):
        raise RuntimeError("결정적 문구가 후보 evidence에 정확히 존재하지 않습니다.")


def apply_review(
    rows: list[dict[str, Any]],
    index: int,
    decision: str,
    reviewer_id: str,
    decisive_excerpt: str,
    rationale: str,
    *,
    reviewed_at: str | None = None,
) -> list[dict[str, Any]]:
    if not 0 <= index < len(rows):
        raise RuntimeError("Evidence adjudication index is out of range")
    output = copy.deepcopy(rows)
    output[index].update(
        {
            "review_decision": decision,
            "reviewer_type": "human",
            "reviewer_id": reviewer_id.strip(),
            "reviewed_at": reviewed_at or datetime.now().astimezone().isoformat(),
            "decisive_excerpt": decisive_excerpt.strip() or None,
            "review_rationale": rationale.strip(),
        }
    )
    validate_review_row(output[index], complete=True)
    return output


def build_overlay(reviewed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlay = []
    for row in sorted(reviewed_rows, key=lambda value: value["item_ordinal"]):
        validate_review_row(row, complete=True)
        decision = row["review_decision"]
        approved = decision == "accept_alternative"
        overlay.append(
            {
                "overlay_schema_version": OVERLAY_SCHEMA_VERSION,
                "source_review_item_id": row["item_id"],
                "case_id": row["case_id"],
                "evidence_group_id": row["evidence_group_id"],
                "candidate_chunk_id": row["candidate_chunk_id"],
                "decision": decision,
                "approved": approved,
                "acceptable_sibling_addition": approved,
                "search_failure_confirmed": decision == "confirm_search_failure",
                "alternative_evidence_span": row["decisive_excerpt"] if approved else None,
                "reviewer_type": "human",
                "reviewer_id": row["reviewer_id"],
                "reviewed_at": row["reviewed_at"],
                "review_rationale": row["review_rationale"],
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return overlay


def prepare_evidence_adjudication(
    root: Path,
    documents_path: Path,
    chunks_path: Path,
    dev_set_path: Path,
    cases_path: Path,
    report_path: Path,
    builder_source_path: Path,
    app_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report_sha = file_sha256(report_path)
    if report["artifacts"]["cases_sha256"] != file_sha256(cases_path):
        raise RuntimeError("Reranker report and cases artifact do not match")
    packet = build_evidence_adjudication_packet(
        read_jsonl(dev_set_path),
        read_jsonl(cases_path),
        read_jsonl(chunks_path),
        read_jsonl(documents_path),
        report,
        report_sha,
    )
    if not packet:
        raise RuntimeError("Claim reranker report has no strict mismatch to review")
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    packet_bytes = _serialize_jsonl(packet, lambda row: row["item_ordinal"])
    packet_sha = _sha256_bytes(packet_bytes)
    packet_path = evaluation_dir / f"evidence_adjudication_packet_{packet_sha}.jsonl"
    write_immutable(packet_path, packet_bytes)
    draft_path = (
        root
        / "outputs/v3/annotation"
        / f"evidence_adjudication_draft_{packet_sha}.jsonl"
    )
    inputs = {
        "documents": documents_path,
        "chunks": chunks_path,
        "adaptive_retrieval_dev": dev_set_path,
        "reranker_cases": cases_path,
        "reranker_report": report_path,
        "builder_source": builder_source_path,
        "review_app_source": app_source_path,
        "contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "packet": {
            "path": _relative(root, packet_path),
            "sha256": packet_sha,
            "row_count": len(packet),
        },
        "runtime": {
            "draft_path": _relative(root, draft_path),
            "draft_is_mutable": True,
            "packet_is_read_only": True,
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "scoring_allowed_before_review": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"evidence_adjudication_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    command = (
        "python src/v3/review_evidence_adjudication_app.py "
        f"--packet {_relative(root, packet_path)} "
        f"--draft {_relative(root, draft_path)}"
    )
    report_row = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "decision": {
            "evidence_adjudication": "PENDING",
            "reranker_replay": "NO-GO",
            "production_evidence_selector": "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "packet_sha256": packet_sha,
        "manifest_sha256": manifest_sha,
        "row_count": len(packet),
        "next_command": command,
    }
    report_bytes = _canonical_json_bytes(report_row)
    report_sha = _sha256_bytes(report_bytes)
    setup_report_path = reports_dir / f"evidence_adjudication_setup_{report_sha}.json"
    write_immutable(setup_report_path, report_bytes)
    return {
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha,
        "draft_path": str(draft_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(setup_report_path),
        "report_sha256": report_sha,
        "row_count": len(packet),
        "next_command": command,
    }


def finalize_evidence_adjudication(
    root: Path,
    packet_path: Path,
    reviewed_rows: list[dict[str, Any]],
    builder_source_path: Path,
    app_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    packet_rows = read_jsonl(packet_path)
    validate_review_structure(packet_rows, reviewed_rows)
    for row in reviewed_rows:
        validate_review_row(row, complete=True)
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    reviewed_bytes = _serialize_jsonl(reviewed_rows, lambda row: row["item_ordinal"])
    reviewed_sha = _sha256_bytes(reviewed_bytes)
    reviewed_path = evaluation_dir / f"evidence_adjudication_reviews_{reviewed_sha}.jsonl"
    write_immutable(reviewed_path, reviewed_bytes)
    overlay = build_overlay(reviewed_rows)
    overlay_bytes = _serialize_jsonl(overlay, lambda row: row["case_id"])
    overlay_sha = _sha256_bytes(overlay_bytes)
    overlay_path = evaluation_dir / f"evidence_adjudication_overlay_{overlay_sha}.jsonl"
    write_immutable(overlay_path, overlay_bytes)
    inputs = {
        "packet": packet_path,
        "builder_source": builder_source_path,
        "review_app_source": app_source_path,
        "contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "reviews": {
            "path": _relative(root, reviewed_path),
            "sha256": reviewed_sha,
            "row_count": len(reviewed_rows),
            "reviewer_ids": sorted({row["reviewer_id"] for row in reviewed_rows}),
        },
        "evaluation_overlay": {
            "path": _relative(root, overlay_path),
            "sha256": overlay_sha,
            "row_count": len(overlay),
            "decision_counts": {
                decision: sum(row["decision"] == decision for row in overlay)
                for decision in DECISIONS
            },
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "evaluation_only": True,
            "gold_replacement_allowed": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"evidence_adjudication_final_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "decision": {
            "human_evidence_adjudication": "GO",
            "reranker_replay": "PENDING",
            "production_evidence_selector": "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "reviews_sha256": reviewed_sha,
        "overlay_sha256": overlay_sha,
        "manifest_sha256": manifest_sha,
        "decision_counts": manifest["evaluation_overlay"]["decision_counts"],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"evidence_adjudication_final_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    return {
        "reviews_path": str(reviewed_path),
        "reviews_sha256": reviewed_sha,
        "overlay_path": str(overlay_path),
        "overlay_sha256": overlay_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "decision_counts": manifest["evaluation_overlay"]["decision_counts"],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Prepare v3 evidence adjudication")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument("--cases", type=Path, default=root / DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=root / DEFAULT_REPORT)
    parser.add_argument("--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE)
    parser.add_argument("--app-source", type=Path, default=root / DEFAULT_APP_SOURCE)
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = prepare_evidence_adjudication(
        args.root.resolve(),
        args.documents.resolve(),
        args.chunks.resolve(),
        args.dev_set.resolve(),
        args.cases.resolve(),
        args.report.resolve(),
        args.builder_source.resolve(),
        args.app_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
