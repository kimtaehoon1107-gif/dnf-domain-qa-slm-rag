from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "equivalent-official-sibling-review-v1.0.0"
TARGET_DEV_ID = (
    "authored_validation_v3_2_sha256_"
    "c0c2d4091eda6655d6e8f0bdbc01a155e39e637642f903e8da2d288fd6cac599"
)
PROPOSED_DOCUMENT_ID = (
    "document_sha256_e73cf51dad5c8d0378ad907a290b61dfabeb3e55e9b38f041fcad091b8f1e9df"
)
PROPOSED_CHUNK_ID = (
    "chunk_sha256_96aad618428b25d25835e640f79d23f936d4d5404ccaf27781d1b619456cd270"
)

DEFAULT_SOURCE = Path("src/v3/prepare_equivalent_official_sibling_review.py")
DEFAULT_AUTHORED_VALIDATION = Path(
    "data/v3/evaluation/authored_validation_v3_2_"
    "52c1b84ef7ab0f9bee29931c46f9febf0970492216b6742e8f5337282af4181e.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_AB_CASES = Path(
    "data/v3/evidence/requirement_surface_query_ab_cases_"
    "760070c9dbadc0f474ba7c9e36bb9ddd4ece12db42c0a71dfd4f238384cbb01e.jsonl"
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_review_row(
    authored_rows: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    target = next((row for row in authored_rows if row["dev_id"] == TARGET_DEV_ID), None)
    if target is None:
        raise RuntimeError("Target authored validation row is missing")
    documents_by_id = {row["document_id"]: row for row in documents}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    document = documents_by_id[PROPOSED_DOCUMENT_ID]
    chunk = chunks_by_id[PROPOSED_CHUNK_ID]
    if chunk["parent_document_id"] != document["document_id"]:
        raise RuntimeError("Proposed chunk/document lineage mismatch")

    proposed_groups = []
    for group in target["evidence_groups"]:
        span = group["evidence_span"]
        start = chunk["display_text"].find(span)
        if start < 0:
            raise RuntimeError(f"Proposed official guide does not contain exact span: {span}")
        proposed_groups.append(
            {
                "group_id": group["group_id"],
                "evidence_span": span,
                "proposed_acceptable_chunk_id": chunk["chunk_id"],
                "proposed_document_id": document["document_id"],
                "start_char": start,
                "end_char": start + len(span),
                "exact_substring": True,
            }
        )

    identity = _canonical_json_bytes(
        {
            "target_dev_id": target["dev_id"],
            "original_evidence_groups": target["evidence_groups"],
            "proposed_groups": proposed_groups,
        }
    )
    return {
        "review_schema_version": "equivalent-official-sibling-review-v1",
        "review_id": f"equivalent_official_review_sha256_{_sha256_bytes(identity)}",
        "question": target["question"],
        "target_dev_id": target["dev_id"],
        "classification_proposal": "EQUIVALENT_OFFICIAL_PROPOSED_NOT_APPLIED",
        "proposal_reason": (
            "현재 공식 guide가 기존 update gold와 동일한 두 exact fact를 함께 진술한다. "
            "모델 선택과 무관하게 사람이 의미 동등성과 현재성을 검수해야 한다."
        ),
        "original_gold": {
            "source_ids": target["source_ids"],
            "document_ids": target["gold_document_ids"],
            "chunk_ids": target["gold_chunk_ids"],
            "evidence_groups": target["evidence_groups"],
        },
        "proposed_sibling": {
            "source_id": document["source_id"],
            "source_kind": document["source_kind"],
            "title": document["title"],
            "canonical_url": document["canonical_url"],
            "status": document["status"],
            "default_exposure": document["default_exposure"],
            "document_id": document["document_id"],
            "chunk_id": chunk["chunk_id"],
            "evidence_groups": proposed_groups,
        },
        "strict_gold_changed": False,
        "acceptable_sibling_applied": False,
        "adjudicated_metric_available": False,
        "human_review_decision": None,
        "human_reviewer_id": None,
        "human_reviewed_at": None,
        "human_review_rationale": None,
        "allowed_decisions": ["approve_equivalent_official", "reject", "needs_revision"],
    }


def freeze_review(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "builder_source": root / DEFAULT_SOURCE,
        "authored_validation": root / DEFAULT_AUTHORED_VALIDATION,
        "documents": root / DEFAULT_DOCUMENTS,
        "chunks": root / DEFAULT_CHUNKS,
        "surface_query_ab_cases": root / DEFAULT_AB_CASES,
    }
    missing = [name for name, path in inputs.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing sibling review inputs: {missing}")
    before = {name: file_sha256(path) for name, path in inputs.items()}

    row = build_review_row(
        read_jsonl(inputs["authored_validation"]),
        read_jsonl(inputs["documents"]),
        read_jsonl(inputs["chunks"]),
    )
    payload = _serialize_jsonl([row], lambda item: item["review_id"])
    payload_sha = _sha256_bytes(payload)
    output_path = root / "data/v3/evaluation" / (
        f"equivalent_official_sibling_review_{payload_sha}.jsonl"
    )
    write_immutable(output_path, payload)

    manifest = {
        "manifest_schema_version": "equivalent-official-sibling-review-manifest-v1",
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "review_sheet": {
            "path": _relative(root, output_path),
            "sha256": payload_sha,
            "row_count": 1,
        },
        "state": {
            "human_review": "PENDING",
            "strict_gold_changed": False,
            "acceptable_sibling_applied": False,
            "scoring_change_allowed_now": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / (
        f"equivalent_official_sibling_review_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    md = "\n".join(
        [
            "# 광휘의 행로 equivalent-official sibling 검수",
            "",
            f"- 질문: {row['question']}",
            f"- 기존 gold source: {', '.join(row['original_gold']['source_ids'])}",
            f"- 제안 source: {row['proposed_sibling']['source_id']}",
            f"- 제안 문서: {row['proposed_sibling']['title']}",
            f"- URL: {row['proposed_sibling']['canonical_url']}",
            "- 상태: 사람 검수 대기, gold 변경/적용 없음",
            "",
            "## 제안 exact spans",
            "",
            *[
                f"- `{group['group_id']}`: {group['evidence_span']}"
                for group in row["proposed_sibling"]["evidence_groups"]
            ],
            "",
            "승인 시에도 기존 gold는 유지하고 acceptable sibling만 추가하며 strict와 adjudicated 지표를 병행합니다.",
            "",
        ]
    ).encode("utf-8")
    md_sha = _sha256_bytes(md)
    md_path = root / "reports/v3" / f"equivalent_official_sibling_review_{md_sha}.md"
    write_immutable(md_path, md)

    for name, path in inputs.items():
        if file_sha256(path) != before[name]:
            raise RuntimeError(f"Input changed while freezing sibling review: {name}")
    return {
        "review_path": str(output_path),
        "review_sha256": payload_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(md_path),
        "report_sha256": md_sha,
        "human_review": "PENDING",
        "acceptable_sibling_applied": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(freeze_review(root=args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
