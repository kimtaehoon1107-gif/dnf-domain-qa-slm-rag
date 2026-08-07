from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


AUDITOR_VERSION = "q4-docs-false-full-audit-v3.2.0"
CASE_SCHEMA_VERSION = "q4-docs-false-full-audit-case-v3.2"
REPORT_SCHEMA_VERSION = "q4-docs-false-full-audit-report-v3.2"
MANIFEST_SCHEMA_VERSION = "q4-docs-false-full-audit-manifest-v3.2"

STAGES = frozenset({"ROUTING_SOURCE_SCOPE", "RETRIEVAL", "SELECTION_SUPPORT", "MEASUREMENT"})

DEFAULT_Q4 = Path(
    "data/v3/evidence/bounded_candidate_source_fallback_cases_"
    "3a84adb80f06e1145a9313544bb5be2520c19836a3aea9ba887214be73c02b2d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_ASSEMBLER = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_RERANK_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/q4_docs_false_full_audit.md")


CLASSIFICATIONS: dict[str, dict[str, str]] = {
    "authored_canary_sha256_2c12d3f6f7776cb4b3d2ced9240885a3a71c62a5f8e6574dd663a15e2fdbdf18": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "semantic_type": "D_CROSS_PARENT_MISS",
        "rationale": "The hard route selected notice, while the two required policy revisions live in separate account-policy parents; revision dates were cited instead of both revision bodies.",
    },
    "authored_canary_sha256_30b37acd07ef814d9ab7a0d25f8c44726e98921f8c75b4d3199d83bcbea7a391": {
        "stage": "SELECTION_SUPPORT",
        "semantic_type": "A_WRONG_ATTRIBUTE",
        "rationale": "The learning-condition chunk was available in the frozen reranker candidates, but three duplicate 'give up profession' headings were marked as support; only the 10,000-gold requirement was answered.",
    },
    "authored_canary_sha256_310899aa4d43a71faa2e5b59cfaa547bdf3fa2f3d44cd94a42c5393ce2b85358": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "semantic_type": "B_RETRIEVAL_MISS",
        "rationale": "The hard route selected game guide although the 60-month deletion rule is in FAQ; unrelated item-deletion dates were cited.",
    },
    "authored_canary_sha256_5338b6ae6d4f8447569abe58de4e61dfead412888b1ffb5456c0876661bb6a42": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "semantic_type": "B_RETRIEVAL_MISS",
        "rationale": "The hard route selected event although the maintenance time, ended event, and compensation are in one notice parent; event timestamps and reward text were cited.",
    },
    "authored_canary_sha256_82a1ce0196fad29ac156e6a2b549185353778c833e35a46e9ed57b02501100e0": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "semantic_type": "B_RETRIEVAL_MISS",
        "rationale": "The hard route selected FAQ instead of the notice containing the DirectX 9 comparison; generic DirectX 11 requirement text was marked as a complete answer.",
    },
    "retrieval_dev_sha256_e4bc819d8e9ad56128bf2989f4626f20907e78b37024c46f3eaac22e2300a7b5": {
        "stage": "RETRIEVAL",
        "semantic_type": "B_RETRIEVAL_MISS",
        "rationale": "The route included notice, but the reviewed account-lending precaution never reached the candidate pool; nearby policy penalties were cited instead.",
    },
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def validate_classifications() -> None:
    if len(CLASSIFICATIONS) != 6:
        raise RuntimeError("Q4 docs false-full audit must contain exactly six cases")
    for case_id, item in CLASSIFICATIONS.items():
        if item["stage"] not in STAGES or not item.get("semantic_type") or not item.get("rationale"):
            raise RuntimeError(f"Invalid classification: {case_id}")


def build_cases(
    q4_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    rerank_score_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    validate_classifications()
    false_full = {
        row["case_id"]: row
        for row in q4_rows
        if (row.get("q4_docs_score") or {}).get("false_full_answer")
    }
    if set(false_full) != set(CLASSIFICATIONS):
        raise RuntimeError("Frozen Q4 docs false-full IDs changed")
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    rerank_scores = {row["case_id"]: row for row in rerank_score_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    output = []
    for case_id in sorted(false_full):
        q4 = false_full[case_id]
        evaluation = evaluations[case_id]
        enumeration = enumerations[case_id]
        assembler = assemblers[case_id]
        candidate_ids = {
            candidate["chunk_id"]
            for requirement in rerank_scores[case_id]["requirements"]
            for candidate in requirement["candidates"]
        }
        citations = []
        for requirement, decision in zip(
            enumeration["requirements"], assembler["decisions"], strict=True
        ):
            citations.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "subject": requirement["subject"],
                    "relation": requirement["relation"],
                    "status": decision["status"],
                    "spans": [
                        {
                            "chunk_id": span["chunk_id"],
                            "source_id": chunks_by_id[span["chunk_id"]]["source_id"],
                            "parent_document_id": chunks_by_id[span["chunk_id"]]["parent_document_id"],
                            "text": span["text"],
                        }
                        for span in decision.get("spans", [])
                    ],
                }
            )
        evidence = []
        for group in evaluation["evidence_groups"]:
            acceptable = []
            for chunk_id in group["acceptable_chunk_ids"]:
                chunk = chunks_by_id[chunk_id]
                acceptable.append(
                    {
                        "chunk_id": chunk_id,
                        "source_id": chunk["source_id"],
                        "parent_document_id": chunk["parent_document_id"],
                        "evidence_span": group["evidence_span"],
                    }
                )
            evidence.append(
                {
                    "group_id": group["group_id"],
                    "candidate_present": bool(set(group["acceptable_chunk_ids"]) & candidate_ids),
                    "selected_present": bool(
                        set(group["acceptable_chunk_ids"]) & set(q4["selected_chunk_ids"])
                    ),
                    "acceptable": acceptable,
                }
            )
        classification = CLASSIFICATIONS[case_id]
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": q4["dataset"],
                "question": evaluation["question"],
                "gold_answer": evaluation.get("gold_answer"),
                "route_source_ids": q4["route_source_ids"],
                "bounded_source_ids": q4["bounded_source_ids"],
                "fallback_triggered": q4["fallback_triggered"],
                "fallback_committed": q4["fallback_committed"],
                "planner_requirements": enumeration["requirements"],
                "system_citations": citations,
                "gold_evidence": evidence,
                "earliest_failure_stage": classification["stage"],
                "semantic_type": classification["semantic_type"],
                "rationale": classification["rationale"],
                "gold_used_for_diagnosis_only": True,
                "runtime_rule_created": False,
            }
        )
    return output


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    stage_counts = Counter(row["earliest_failure_stage"] for row in cases)
    semantic_counts = Counter(row["semantic_type"] for row in cases)
    return {
        "case_count": len(cases),
        "stage_counts": {stage: stage_counts[stage] for stage in sorted(STAGES)},
        "semantic_type_counts": dict(sorted(semantic_counts.items())),
        "candidate_missing_case_count": sum(
            any(not group["candidate_present"] for group in row["gold_evidence"])
            for row in cases
        ),
        "measurement_artifact_count": stage_counts["MEASUREMENT"],
    }


def _markdown(report: dict[str, Any], cases: list[dict[str, Any]]) -> bytes:
    lines = [
        "# Q4 docs-only false-full six-case audit",
        "",
        f"- decision: **{report['decision']}**",
        f"- stage counts: **{json.dumps(report['summary']['stage_counts'], ensure_ascii=False)}**",
        f"- measurement artifacts: **{report['summary']['measurement_artifact_count']}**",
        "",
        "| # | question | earliest stage | semantic type | rationale |",
        "|---:|---|---|---|---|",
    ]
    for index, row in enumerate(cases, 1):
        lines.append(
            f"| {index} | {row['question']} | {row['earliest_failure_stage']} | "
            f"{row['semantic_type']} | {row['rationale']} |"
        )
    lines.extend(
        [
            "",
            "Gold was used only to audit the frozen run. No question-specific runtime rule was created.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def audit_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "q4_cases": root / DEFAULT_Q4,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "enumeration": root / DEFAULT_ENUMERATION,
        "assembler": root / DEFAULT_ASSEMBLER,
        "rerank_scores": root / DEFAULT_RERANK_SCORES,
        "chunks": root / DEFAULT_CHUNKS,
        "contract": root / DEFAULT_CONTRACT,
        "auditor_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    cases = build_cases(
        read_jsonl(inputs["q4_cases"]),
        read_jsonl(inputs["adaptive_dev"]) + read_jsonl(inputs["downgraded_canary"]),
        read_jsonl(inputs["enumeration"]),
        read_jsonl(inputs["assembler"]),
        read_jsonl(inputs["rerank_scores"]),
        read_jsonl(inputs["chunks"]),
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "evaluation_role": "development_only_pre_new_set_error_baseline",
        "decision": "AUDIT_COMPLETE_NEW_SET_COMPARISON_PENDING",
        "summary": summarize(cases),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": digest}
            for name, path in inputs.items()
            for digest in [before[name]]
        },
        "source_commit": _git_head(root),
        "scope": {
            "runtime_changed": False,
            "questions_gold_or_labels_changed": False,
            "frozen_blind_accessed": False,
        },
    }
    case_bytes = _serialize_jsonl(cases, lambda row: row["case_id"])
    case_sha = _sha256_bytes(case_bytes)
    case_path = root / "data/v3/evidence" / f"q4_docs_false_full_audit_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    report["artifacts"] = {
        "cases": {"path": _relative(root, case_path), "sha256": case_sha, "row_count": len(cases)}
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / f"q4_docs_false_full_audit_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report, cases)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = root / "reports/v3" / f"q4_docs_false_full_audit_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "inputs": report["inputs"],
        "artifacts": {
            "cases": report["artifacts"]["cases"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "source_commit": report["source_commit"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evidence" / f"q4_docs_false_full_audit_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise RuntimeError(f"Audit inputs changed: {changed}")
    return {
        "summary": report["summary"],
        "cases_path": str(case_path),
        "cases_sha256": case_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "input_hash_mismatch_count": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the six remaining Q4 docs false-full cases")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(audit_and_freeze(parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

