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
from src.v3.prepare_entailment_review import REVIEW_FIELDS


BUILDER_VERSION = "entailment-revision-conflict-builder-v3.1.0"
PACKET_SCHEMA_VERSION = "entailment-revision-conflict-review-item-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-revision-conflict-manifest-v3.1"
REPORT_SCHEMA_VERSION = "entailment-revision-conflict-report-v3.1"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CONTENTS = Path(
    "data/v3/normalized/"
    "document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_RESOLVED_MANIFEST = Path(
    "data/v3/evaluation/"
    "entailment_natural_resolved_manifest_d4a71c67b3b3b766f1e23553917165e046b8b566c7a8a9d9c3e281d98359a387.json"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/prepare_entailment_contradiction_review.py")
DEFAULT_CONTRACT = Path("docs/v3/entailment_revision_conflict_review.md")


CANDIDATE_SPECS = (
    {
        "question": "피해 복구 서비스를 신청한 계정의 거래정지 의무 기간은 얼마야?",
        "origin_valid_from": "2013-01-25",
        "evidence_valid_from": "2013-05-23",
        "claim_text": "피해 복구 서비스를 신청한 계정은 해킹의 위험도가 높은 상태로 진단되어 계정의 안전한 보호를 위해 '거래정지' 가 30일간 의무 적용되며, 30일 이후에는 초본을 이용한 본인인증 완료 시 해제되어 정상적인 게임 이용이 가능합니다.",
        "evidence_anchor": "'거래정지' 가 3일간 의무 적용되며, 3일 이후에는 본인인증 후 거래제한이 해제",
        "conflict_dimension": "mandatory_trade_restriction_duration",
    },
    {
        "question": "해킹 피해 복구 신청은 해킹 발생 후 며칠 이내여야 해?",
        "origin_valid_from": "2014-09-15",
        "evidence_valid_from": "2015-02-05",
        "claim_text": "피해 복구용 DB 관리 정책 상, 해킹 발생 후 50일이 경과하기 전에 피해 복구 서비스 신청이 접수된 경우에 한하여 복구가 가능하며, 해킹 발생 후 50일이 경과된 경우 복구가 불가능합니다.",
        "evidence_anchor": "해킹 발생 후 60일이 경과하기 전에 피해 복구 서비스 신청이 접수된 경우",
        "conflict_dimension": "recovery_request_deadline",
    },
    {
        "question": "길드 탈퇴 후 재가입 가능 시점은 언제야?",
        "origin_valid_from": "2017-09-21",
        "evidence_valid_from": "2017-11-24",
        "claim_text": "던전앤파이터에서 제공하는 길드 가입방식 및 조건에 따라 길드를 생성하거나, 생성되어 있는 길드에 가입 및 탈퇴할 수 있습니다. 단, 길드 탈퇴 시 3일(72시간) 이후부터 재가입이 가능합니다.",
        "evidence_anchor": "길드 탈퇴 시 오전 06시 피로도 초기화 이후부터 재가입이 가능합니다.",
        "conflict_dimension": "guild_rejoin_wait",
    },
    {
        "question": "커뮤니티 이용제한의 단계별 게시물 등록 제한 기간은 어떻게 돼?",
        "origin_valid_from": "2018-06-29",
        "evidence_valid_from": "2018-08-10",
        "claim_text": "커뮤니티 이용제한 * 이용제한 조건에 해당하거나, 게시판 성격에 맞지 않는 글은 삭제됩니다. | 타인비방, 욕설, 도배, 미풍양속을 저해하는 내용 타인에게 불쾌감을 주는 내용 중복(도배)글 게시 | 게시물1일 등록제한 | 게시물3일 등록제한 | 게시물5일 등록제한 | 게시물30일 등록제한 | 게시물영구 등록제한",
        "evidence_anchor": "게시물3일 등록제한 | 게시물7일 등록제한 | 게시물30일 등록제한 | 게시물100일 등록제한 | 게시물영구 등록제한",
        "conflict_dimension": "community_post_restriction_schedule",
    },
    {
        "question": "우편정책 위반의 단계별 게임 이용제한 기간은 어떻게 돼?",
        "origin_valid_from": "2023-09-21",
        "evidence_valid_from": "2023-10-07",
        "claim_text": "우편정책 위반 | 10일 게임 이용제한 | 30일 게임 이용제한 | 100일 게임 이용제한 | 영구 게임 이용제한",
        "evidence_anchor": "우편정책 위반 | 3일 게임 이용제한 | 10일 게임 이용제한 | 30일 게임 이용제한 | 100일 게임 이용제한",
        "conflict_dimension": "mail_policy_restriction_schedule",
    },
    {
        "question": "사기 시도 및 사기로 피해를 입힌 경우 단계별 이용제한은 어떻게 돼?",
        "origin_valid_from": "2024-11-16",
        "evidence_valid_from": "2025-04-26",
        "claim_text": "사기 시도 및 사기로 타인에게 피해를 입힌 경우 (관련재화 회수) | 100일 게임 이용제한 | 1년 게임 이용제한 | 3년 게임 이용제한 | 영구 게임 이용제한",
        "evidence_anchor": "사기 시도 및 사기로 타인에게 피해를 입힌 경우 (관련재화 회수) | 100일 게임 이용제한 및 회원가입 차단 | 영구 게임 이용제한",
        "conflict_dimension": "fraud_restriction_schedule",
    },
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalize(value: str) -> str:
    return " ".join(value.split())


def build_packet(
    documents: list[dict[str, Any]],
    contents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    documents_by_revision = {
        (row["source_id"], row["valid_from"]): row for row in documents
    }
    contents_by_document = {row["document_id"]: row for row in contents}
    if len(contents_by_document) != len(contents):
        raise RuntimeError("Duplicate document content row")

    packet = []
    for spec in CANDIDATE_SPECS:
        origin = documents_by_revision.get(
            ("dnf_account_policy", spec["origin_valid_from"])
        )
        evidence_document = documents_by_revision.get(
            ("dnf_account_policy", spec["evidence_valid_from"])
        )
        if origin is None or evidence_document is None:
            raise RuntimeError(f"Missing policy revision for spec: {spec}")
        origin_content = contents_by_document.get(origin["document_id"])
        if origin_content is None:
            raise RuntimeError(f"Missing origin content: {origin['document_id']}")
        if _normalize(spec["claim_text"]) not in _normalize(origin_content["text"]):
            raise RuntimeError(
                f"Claim is not an exact origin-document excerpt: {spec['conflict_dimension']}"
            )
        evidence_hits = [
            row
            for row in chunks
            if row["parent_document_id"] == evidence_document["document_id"]
            and _normalize(spec["evidence_anchor"])
            in _normalize(row["display_text"])
        ]
        if not evidence_hits:
            raise RuntimeError(
                f"Evidence anchor not found: {spec['conflict_dimension']}"
            )
        evidence = min(
            evidence_hits,
            key=lambda row: (
                _normalize(row["display_text"]).find(
                    _normalize(spec["evidence_anchor"])
                ),
                len(row["display_text"]),
                row["chunk_id"],
            ),
        )
        if origin["lineage_id"] != evidence_document["lineage_id"]:
            raise RuntimeError("Revision comparison crossed policy lineages")
        identity = {
            "origin_document_id": origin["document_id"],
            "evidence_chunk_id": evidence["chunk_id"],
            "claim_text": spec["claim_text"],
        }
        packet.append(
            {
                "review_item_schema_version": PACKET_SCHEMA_VERSION,
                "item_id": f"entailment_revision_conflict_sha256_{_sha256_bytes(_canonical_json_bytes(identity))}",
                "item_ordinal": None,
                "question": spec["question"],
                "claim_text": spec["claim_text"],
                "claim_as_of": origin["valid_from"],
                "claim_time_scope": "cross_revision_proposition_comparison",
                "evidence_chunk_id": evidence["chunk_id"],
                "evidence_document_id": evidence_document["document_id"],
                "evidence_title": evidence_document["title"],
                "evidence_url": evidence_document["canonical_url"],
                "evidence_source_id": evidence["source_id"],
                "evidence_status": evidence["status"],
                "evidence_valid_from": evidence["valid_from"],
                "evidence_valid_to": evidence["valid_to"],
                "evidence_text": evidence["display_text"],
                "revision_comparison": {
                    "origin_document_id": origin["document_id"],
                    "origin_url": origin["canonical_url"],
                    "origin_revision_id": origin["revision_id"],
                    "origin_valid_from": origin["valid_from"],
                    "evidence_revision_id": evidence_document["revision_id"],
                    "evidence_valid_from": evidence_document["valid_from"],
                    "lineage_id": origin["lineage_id"],
                    "conflict_dimension": spec["conflict_dimension"],
                    "claim_is_exact_official_excerpt": True,
                    "expected_label_in_packet": False,
                },
                **{field: None for field in REVIEW_FIELDS},
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return [
        {**row, "item_ordinal": ordinal}
        for ordinal, row in enumerate(sorted(packet, key=lambda row: row["item_id"]))
    ]


def audit_packet(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gates = {
        "row_count_6": len(rows) == 6,
        "unique_item_ids": len({row["item_id"] for row in rows}) == len(rows),
        "ordinals_contiguous": [row["item_ordinal"] for row in rows]
        == list(range(len(rows))),
        "reviews_pending": all(row["review_label"] is None for row in rows),
        "cross_revision_only": all(
            row["revision_comparison"]["origin_revision_id"]
            != row["revision_comparison"]["evidence_revision_id"]
            for row in rows
        ),
        "same_lineage_only": len(
            {row["revision_comparison"]["lineage_id"] for row in rows}
        )
        == 1,
        "expected_labels_hidden": all(
            row["revision_comparison"]["expected_label_in_packet"] is False
            for row in rows
        ),
        "training_leak_0": not any(row["training_allowed"] for row in rows),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in rows
        ),
    }
    return {"gates": gates, "gate_pass": all(gates.values())}


def prepare_review(
    root: Path,
    documents_path: Path,
    contents_path: Path,
    chunks_path: Path,
    resolved_manifest_path: Path,
    builder_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    rows = build_packet(
        read_jsonl(documents_path), read_jsonl(contents_path), read_jsonl(chunks_path)
    )
    audit = audit_packet(rows)
    if not audit["gate_pass"]:
        raise RuntimeError(f"Revision-conflict packet integrity failed: {audit}")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    packet_bytes = _serialize_jsonl(rows, lambda row: row["item_ordinal"])
    packet_sha = _sha256_bytes(packet_bytes)
    packet_path = (
        evaluation_dir / f"entailment_revision_conflict_packet_{packet_sha}.jsonl"
    )
    write_immutable(packet_path, packet_bytes)
    draft_path = (
        root
        / "outputs/v3/annotation"
        / f"entailment_revision_conflict_draft_{packet_sha}.jsonl"
    )
    inputs = {
        "documents": documents_path,
        "document_contents": contents_path,
        "chunks": chunks_path,
        "resolved_natural_manifest": resolved_manifest_path,
        "builder_source": builder_source_path,
        "review_contract": contract_path,
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
            "row_count": len(rows),
            "draft_path": _relative(root, draft_path),
            "audit": audit,
        },
        "decisions": {
            "packet_integrity": "GO",
            "human_review": "PENDING",
            "three_class_natural_verifier_evaluation": "NO-GO",
            "generator_entry": "NO-GO",
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "natural_distribution_prevalence_claim": False,
            "default_current_retrieval_exposure": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = (
        evaluation_dir
        / f"entailment_revision_conflict_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)
    next_command = (
        "python src/v3/review_entailment_app.py "
        f"--packet {_relative(root, packet_path)} "
        f"--draft {_relative(root, draft_path)}"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "packet_sha256": packet_sha,
        "manifest_sha256": manifest_sha,
        "row_count": len(rows),
        "decisions": manifest["decisions"],
        "next_command": next_command,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_revision_conflict_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Revision-conflict Review Packet

## Decision

- Packet integrity: **GO**
- Human review: **PENDING**
- Three-class natural Verifier evaluation: **NO-GO**
- Generator / final benchmark: **NO-GO**

Six exact official policy excerpts are paired with a later revision of the same
policy lineage that changed the same rule. No expected label is stored in the
packet. Human review must distinguish explicit conflict from omission.

This is a revision-conflict supplement, not a natural-distribution sample and not
a source of current-policy answers.

Run:

`{next_command}`
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_revision_conflict_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha,
        "draft_path": str(draft_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Prepare human review of natural policy revision conflicts"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--contents", type=Path, default=root / DEFAULT_CONTENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument(
        "--resolved-manifest", type=Path, default=root / DEFAULT_RESOLVED_MANIFEST
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = prepare_review(
        args.root.resolve(),
        args.documents.resolve(),
        args.contents.resolve(),
        args.chunks.resolve(),
        args.resolved_manifest.resolve(),
        args.builder_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
