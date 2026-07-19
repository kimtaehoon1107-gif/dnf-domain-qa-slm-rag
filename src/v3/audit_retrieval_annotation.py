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


AUDITOR_VERSION = "retrieval-annotation-audit-v3.1.0"
PACKET_SCHEMA_VERSION = "retrieval-annotation-review-packet-v3.1"
TARGET_DEV_ID = (
    "retrieval_dev_sha256_"
    "e4bc819d8e9ad56128bf2989f4626f20907e78b37024c46f3eaac22e2300a7b5"
)
ALTERNATIVE_CHUNK_IDS = (
    "chunk_sha256_e6bfe29030739e9ca468b622239faea074a71a8888c4e75bafbedeff98a8b382",
    "chunk_sha256_1960d95cdc46b60f92e7c84ccee3442bcf2cdab41edf38a544b6a0b4cfcdfd78",
    "chunk_sha256_86d787681c270206c5815811e81cc3b069729ea04f47e2e103196e0ccca5bc3c",
)

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_RETRIEVAL_RESULTS = Path(
    "data/v3/retrieval/"
    "retrieval_ab_results_c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _excerpt(text: str, terms: tuple[str, ...], radius: int = 360) -> str:
    normalized = " ".join(text.split())
    positions = [normalized.find(term) for term in terms if normalized.find(term) >= 0]
    start = max(0, min(positions, default=0) - 80)
    return normalized[start : start + radius]


def build_review_packet(
    dev_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dev_by_id = {row["dev_id"]: row for row in dev_rows}
    retrieval_by_id = {row["dev_id"]: row for row in retrieval_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    if TARGET_DEV_ID not in dev_by_id or TARGET_DEV_ID not in retrieval_by_id:
        raise RuntimeError("Target annotation case is absent from frozen inputs")
    target = dev_by_id[TARGET_DEV_ID]
    retrieval = retrieval_by_id[TARGET_DEV_ID]
    ranked_ids = {
        system: [row["chunk_id"] for row in retrieval["systems"][system]["hits"]]
        for system in ("bm25", "dense")
    }
    alternatives = []
    roles = (
        "current_policy_consequence",
        "current_faq_scope",
        "current_enforcement_notice",
    )
    for chunk_id, role in zip(ALTERNATIVE_CHUNK_IDS, roles):
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            raise RuntimeError(f"Alternative evidence chunk is absent: {chunk_id}")
        document = documents_by_id[chunk["parent_document_id"]]
        alternatives.append(
            {
                "role": role,
                "chunk_id": chunk_id,
                "document_id": chunk["parent_document_id"],
                "title": document["title"],
                "canonical_url": document["canonical_url"],
                "source_id": document["source_id"],
                "status": document["status"],
                "default_exposure": document["default_exposure"],
                "bm25_rank": ranked_ids["bm25"].index(chunk_id) + 1
                if chunk_id in ranked_ids["bm25"]
                else None,
                "dense_rank": ranked_ids["dense"].index(chunk_id) + 1
                if chunk_id in ranked_ids["dense"]
                else None,
                "evidence_excerpt": _excerpt(
                    chunk["display_text"],
                    ("비인가 프로그램", "불법 프로그램", "이용제한"),
                ),
                "agent_assessment": "plausible_alternative_official_evidence",
            }
        )
    return [
        {
            "packet_schema_version": PACKET_SCHEMA_VERSION,
            "auditor_version": AUDITOR_VERSION,
            "dev_id": TARGET_DEV_ID,
            "question": target["question"],
            "current_answerability": target["answerability"],
            "current_gold_groups": target["evidence_groups"],
            "alternative_official_evidence": alternatives,
            "ambiguity_class": "underspecified_question_multiple_valid_official_answers",
            "agent_recommendation": "rewrite_question_and_refreeze_after_human_review",
            "recommended_question": "계정을 타인에게 빌려줬다가 사기나 비인가 프로그램 사용에 이용되면 정상 참작을 받을 수 있어?",
            "recommend_add_alternatives_to_same_gold": False,
            "human_review_status": "pending",
            "dev_set_mutated": False,
            "training_allowed": False,
            "final_benchmark_eligible": False,
        }
    ]


def audit_packet(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row = rows[0] if rows else {}
    gates = {
        "one_review_case": len(rows) == 1,
        "three_alternative_official_chunks": len(
            row.get("alternative_official_evidence", [])
        )
        == 3,
        "human_review_pending": row.get("human_review_status") == "pending",
        "dev_set_not_mutated": row.get("dev_set_mutated") is False,
        "training_leak_0": row.get("training_allowed") is False,
        "final_benchmark_leak_0": row.get("final_benchmark_eligible") is False,
    }
    return {"gates": gates, "gate_pass": all(gates.values())}


def _markdown(report: dict[str, Any]) -> str:
    case = report["review_case"]
    alternatives = "\n".join(
        f"- `{row['role']}`: {row['title']} (BM25={row['bm25_rank']}, dense={row['dense_rank']})"
        for row in case["alternative_official_evidence"]
    )
    return f"""# v3 Retrieval Annotation Evidence Audit

## Decision

- Annotation ambiguity: **CONFIRMED_BY_AGENT_AUDIT**
- Human review: **PENDING**
- Dev-set refreeze: **NO-GO**
- Final benchmark: **NO-GO**

## Case

- Question: {case['question']}
- Ambiguity: `{case['ambiguity_class']}`
- Recommendation: `{case['agent_recommendation']}`
- Recommended rewrite: {case['recommended_question']}

## Alternative official evidence

{alternatives}

The current frozen dev row was not changed. An agent audit cannot substitute for the required human approval.

## Artifact

- packet: `{report['artifact']['packet_path']}`
- packet SHA-256: `{report['artifact']['packet_sha256']}`
"""


def build_and_freeze(
    root: Path,
    dev_path: Path,
    retrieval_results_path: Path,
    chunks_path: Path,
    documents_path: Path,
) -> dict[str, Any]:
    inputs = {
        "dev_set": dev_path,
        "retrieval_results": retrieval_results_path,
        "chunks": chunks_path,
        "documents": documents_path,
    }
    hashes = {name: file_sha256(path) for name, path in inputs.items()}
    packet = build_review_packet(
        read_jsonl(dev_path),
        read_jsonl(retrieval_results_path),
        read_jsonl(chunks_path),
        read_jsonl(documents_path),
    )
    audit = audit_packet(packet)
    if not audit["gate_pass"]:
        raise RuntimeError("Annotation review packet audit failed")
    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    packet_bytes = _serialize_jsonl(packet, lambda row: row["dev_id"])
    packet_sha = _sha256_bytes(packet_bytes)
    packet_path = evaluation_dir / f"retrieval_annotation_review_packet_{packet_sha}.jsonl"
    write_immutable(packet_path, packet_bytes)
    manifest = {
        "manifest_schema_version": PACKET_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": hashes[name]}
            for name, path in inputs.items()
        },
        "packet": {
            "path": _relative(root, packet_path),
            "sha256": packet_sha,
            "row_count": 1,
        },
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"retrieval_annotation_review_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": PACKET_SCHEMA_VERSION,
        "decision": {
            "annotation_ambiguity": "CONFIRMED_BY_AGENT_AUDIT",
            "human_review": "PENDING",
            "dev_set_refreeze": "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "review_case": packet[0],
        "audit": audit,
        "artifact": {
            "packet_path": _relative(root, packet_path),
            "packet_sha256": packet_sha,
            "manifest_path": _relative(root, manifest_path),
            "manifest_sha256": manifest_sha,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"retrieval_annotation_audit_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"retrieval_annotation_audit_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Freeze the v3 retrieval annotation review packet")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--retrieval-results", type=Path, default=root / DEFAULT_RETRIEVAL_RESULTS
    )
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.retrieval_results.resolve(),
        args.chunks.resolve(),
        args.documents.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
