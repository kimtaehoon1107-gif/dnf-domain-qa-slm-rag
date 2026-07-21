from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable


AUDITOR_VERSION = "ocr-structure-readiness-v3.2-arm7.0"
REPORT_SCHEMA_VERSION = "dnf-ocr-structure-readiness-report-v3.2"
MANIFEST_SCHEMA_VERSION = "dnf-ocr-structure-readiness-manifest-v3.2"

DEFAULT_VISUAL_EVIDENCE = Path(
    "data/v3/visual_evidence/visual_document_evidence_"
    "c7362de31d59ee1f0877477caa8c5d4848fdbdf40719b5c64cdb861c29469d38.jsonl"
)
DEFAULT_ASSET_LEDGER = Path(
    "data/v3/visual_evidence/visual_asset_ledger_"
    "9b871e8ed168bb155c183165713c944afbed09e72b68c8ea4a633541bcc82df8.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/ocr_structure_readiness_arm7.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/visual_evidence")
DEFAULT_REPORT_DIR = Path("reports/v3")

LAYOUT_FIELD_TOKENS = ("bbox", "bounding", "coordinate", "polygon", "word_boxes", "line_boxes")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _has_layout_fields(row: dict[str, Any]) -> bool:
    return any(
        token in key.lower()
        for key in row
        for token in LAYOUT_FIELD_TOKENS
    )


def audit_readiness(
    evidence: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> dict[str, Any]:
    nonempty_assets = [row for row in assets if row.get("ocr_text")]
    layout_assets = [row for row in nonempty_assets if _has_layout_fields(row)]
    visual_chunks = [row for row in chunks if row.get("offset_source") == "visual_ocr"]
    visual_chunk_ids = {row["chunk_id"] for row in visual_chunks}
    visual_gold_groups = []
    for evaluation in evaluations:
        for group in evaluation.get("evidence_groups", []):
            visual_ids = sorted(visual_chunk_ids & set(group.get("acceptable_chunk_ids", [])))
            if visual_ids:
                visual_gold_groups.append(
                    {"case_id": evaluation["dev_id"], "group_id": group["group_id"], "chunk_ids": visual_ids}
                )
    security_warning_documents = sum(
        "보안 경고 알림" in row.get("ocr_text", "") for row in evidence
    )
    safety = {
        "all_visual_chunks_review_required": all(row["review_required"] for row in visual_chunks),
        "all_visual_chunks_default_exposure_false": all(not row["default_exposure"] for row in visual_chunks),
        "all_visual_chunks_unverified": all(row["evidence_quality"] == "unverified_ocr" for row in visual_chunks),
    }
    preconditions = {
        "layout_coordinates_available": bool(layout_assets),
        "reviewed_visual_gold_available": bool(visual_gold_groups),
        "safety_boundary_intact": all(safety.values()),
    }
    executable_ab = all(preconditions.values())
    return {
        "visual_document_count": len(evidence),
        "asset_count": len(assets),
        "ocr_nonempty_asset_count": len(nonempty_assets),
        "assets_with_layout_coordinates": len(layout_assets),
        "visual_ocr_chunk_count": len(visual_chunks),
        "visual_gold_group_count": len(visual_gold_groups),
        "visual_gold_groups": visual_gold_groups,
        "documents_with_shared_security_warning_ocr": security_warning_documents,
        "safety": safety,
        "preconditions": preconditions,
        "executable_ab": executable_ab,
        "decision": "READY_FOR_STRUCTURE_AB" if executable_ab else "SKIP_NO_GO_MISSING_LAYOUT_AND_EVAL_GOLD",
    }


def _markdown(report: dict[str, Any]) -> str:
    audit = report["audit"]
    return "\n".join(
        [
            "# v3.2 Arm 7 — OCR structure readiness",
            "",
            f"Decision: **{audit['decision']}**.",
            "",
            "| Readiness measure | Count |",
            "|---|---:|",
            f"| Visual documents | {audit['visual_document_count']} |",
            f"| Non-empty OCR assets | {audit['ocr_nonempty_asset_count']} |",
            f"| Assets with layout coordinates | {audit['assets_with_layout_coordinates']} |",
            f"| Visual OCR chunks | {audit['visual_ocr_chunk_count']} |",
            f"| Existing reviewed visual gold groups | {audit['visual_gold_group_count']} |",
            f"| Documents containing shared security-warning OCR | {audit['documents_with_shared_security_warning_ocr']} |",
            "",
            "No OCR structure transform was implemented because improvement cannot be measured and row/column attribution cannot be verified from text-only OCR. Existing OCR remains review-required and non-default.",
        ]
    ) + "\n"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    evidence = read_jsonl(root / DEFAULT_VISUAL_EVIDENCE)
    assets = read_jsonl(root / DEFAULT_ASSET_LEDGER)
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    evaluations = read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV)
    audit = audit_readiness(evidence, assets, chunks, evaluations)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "status": "development_only_not_promoted",
        "audit": audit,
        "scope": {"ocr_rerun": False, "image_snapshots_read": False, "structured_facts_emitted": False, "runtime_changed": False, "promoted": False},
    }
    report_dir = root / DEFAULT_REPORT_DIR
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"ocr_structure_readiness_arm7_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"ocr_structure_readiness_arm7_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    inputs = {"visual_evidence": DEFAULT_VISUAL_EVIDENCE, "asset_ledger": DEFAULT_ASSET_LEDGER, "chunks": DEFAULT_CHUNKS, "adaptive_dev": DEFAULT_DEV, "downgraded_canary": DEFAULT_CANARY, "contract": DEFAULT_CONTRACT, "auditor_source": Path(__file__).resolve().relative_to(root)}
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {name: {"path": path.as_posix(), "sha256": file_sha256(root / path)} for name, path in inputs.items()},
        "artifacts": {"report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha}, "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha}},
        "gate": {"pass": audit["executable_ab"], "checks": audit["preconditions"], "decision": audit["decision"], "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / DEFAULT_OUTPUT_DIR / f"ocr_structure_readiness_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"manifest": manifest_path.relative_to(root).as_posix(), "report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), "audit": audit}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
