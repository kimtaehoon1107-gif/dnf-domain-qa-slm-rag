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


AUDITOR_VERSION = "false-full-nine-case-audit-v3.1.0"
CASE_SCHEMA_VERSION = "false-full-case-audit-v3.1"
REPORT_SCHEMA_VERSION = "false-full-audit-report-v3.1"
MANIFEST_SCHEMA_VERSION = "false-full-audit-manifest-v3.1"

TYPE_LABELS = frozenset(
    {
        "A_WRONG_ATTRIBUTE",
        "B_RETRIEVAL_MISS",
        "C_MEASUREMENT_ARTIFACT",
        "D_CROSS_PARENT_MISS",
    }
)
SEVERITY_LABELS = frozenset({"catchable", "subtle"})
FORM_LABELS = frozenset(
    {"wrong_value_presented", "unsupported_requirement_marked_full"}
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
DEFAULT_RERANK_RESULTS = Path(
    "data/v3/evidence/requirement_reranker_ab_results_"
    "db7dbd2281687c07aebf88dc43a07bd90cf280e690188c06a79cf9e3a2b04913.jsonl"
)
DEFAULT_RERANK_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_BACKBONE = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_BACKBONE_MANIFEST = Path(
    "data/v3/router/router_backbone_answer_source_ab_manifest_"
    "1dc7f770f17b5426ef434b8a10ecd7395b6705cb0cf9a4626bc4ca8527d81e29.json"
)
DEFAULT_TAXONOMY = Path(
    "data/v3/router/routing_bottleneck_taxonomy_"
    "905182d088873485059415d4dcbda95f15db42c091392c7b3d21dfeefd734679.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_VERIFIER_REPORT = Path(
    "reports/v3/semantic_support_verifier_ab_"
    "f76a137b79cec2ae1004a6b12ff8ad8b0c7b16d7d59b74faa2fb451723988358.json"
)
DEFAULT_VERIFIER_MANIFEST = Path(
    "data/v3/evidence/semantic_support_verifier_manifest_"
    "d7fcbb9a3d488fde261ee76a790beb8676f73500ea1f6121889d411ee98d4001.json"
)
DEFAULT_CONTRACT = Path("docs/v3/false_full_audit.md")


CLASSIFICATIONS: dict[str, dict[str, str]] = {
    "retrieval_dev_sha256_e4bc819d8e9ad56128bf2989f4626f20907e78b37024c46f3eaac22e2300a7b5": {
        "type": "B_RETRIEVAL_MISS",
        "severity": "subtle",
        "form": "unsupported_requirement_marked_full",
        "comparison": "The reviewed phishing/account-lending precaution is absent; policy penalties and suspicious-currency handling are plausible nearby facts but not the frozen required warning.",
        "summary": "비인가 프로그램: 필수 피싱·계정대여 주의 근거가 후보에 없고 관련 운영정책 문장만 인용됨.",
    },
    "authored_canary_sha256_175b6c3b7164a9ef08782d08691f164a1d8fadc015c3c25efd6d92392881c3fa": {
        "type": "B_RETRIEVAL_MISS",
        "severity": "catchable",
        "form": "unsupported_requirement_marked_full",
        "comparison": "The 11.7% and 12.3% balance chunk is absent; only patch headings and timestamps are cited.",
        "summary": "남격투가 밸런스: 11.7%·12.3% 청크가 후보에 없고 패치 제목·시각만 인용됨.",
    },
    "authored_canary_sha256_2c12d3f6f7776cb4b3d2ced9240885a3a71c62a5f8e6574dd663a15e2fdbdf18": {
        "type": "D_CROSS_PARENT_MISS",
        "severity": "catchable",
        "form": "unsupported_requirement_marked_full",
        "comparison": "The two policy revisions require distinct parents; neither revision body is present and revision dates are treated as a completed comparison.",
        "summary": "정책 전후 비교: 서로 다른 revision parent가 필요한데 시행일만으로 비교가 완료된 것처럼 처리됨.",
    },
    "authored_canary_sha256_30b37acd07ef814d9ab7a0d25f8c44726e98921f8c75b4d3199d83bcbea7a391": {
        "type": "A_WRONG_ATTRIBUTE",
        "severity": "catchable",
        "form": "unsupported_requirement_marked_full",
        "comparison": "The learning-condition chunk is in candidates, but the learning requirement cites the adjacent 'give up profession' heading; the 10,000-gold requirement is supported.",
        "summary": "전문직업: 배우기 조건 청크가 있었지만 첫 요구에 '전문직업 포기하기' 헤더를 인용함.",
    },
    "authored_canary_sha256_310899aa4d43a71faa2e5b59cfaa547bdf3fa2f3d44cd94a42c5393ce2b85358": {
        "type": "B_RETRIEVAL_MISS",
        "severity": "catchable",
        "form": "wrong_value_presented",
        "comparison": "The 60-month FAQ chunk is absent; a fixed item deletion date and a three-day expiring-item UI notice are cited instead.",
        "summary": "충전 세라: 60개월 FAQ가 후보에 없고 다른 아이템 삭제일·3일 알림을 인용함.",
    },
    "authored_canary_sha256_5338b6ae6d4f8447569abe58de4e61dfead412888b1ffb5456c0876661bb6a42": {
        "type": "B_RETRIEVAL_MISS",
        "severity": "subtle",
        "form": "wrong_value_presented",
        "comparison": "The maintenance notice and compensation section are absent; an event publication time and unrelated reward/date spans look superficially plausible.",
        "summary": "7월 16일 점검: 04:30~10:00·종료 이벤트 보상 근거가 없고 게시시각·다른 이벤트 보상을 인용함.",
    },
    "authored_canary_sha256_7138af09ff1516a92031af64d4a09b627fb23cddf7cc5a5b2f5e16c592e957b0": {
        "type": "A_WRONG_ATTRIBUTE",
        "severity": "subtle",
        "form": "unsupported_requirement_marked_full",
        "comparison": "Both gold chunks are candidates, but the daily-participation requirement selects a weekly 19-hour example and same-wording account-unit spans from other event parents.",
        "summary": "PC방 꿀타임: gold는 후보에 있었지만 일일 참여 단위 대신 주간 19시간·다른 이벤트 계정 단위를 인용함.",
    },
    "authored_canary_sha256_82a1ce0196fad29ac156e6a2b549185353778c833e35a46e9ed57b02501100e0": {
        "type": "B_RETRIEVAL_MISS",
        "severity": "catchable",
        "form": "unsupported_requirement_marked_full",
        "comparison": "The 'nearly identical to DirectX 9' chunk is absent; generic DirectX 11 requirement text is cited without the requested comparison.",
        "summary": "DirectX 11: 'DirectX 9과 거의 동일' 근거가 후보에 없고 일반적인 DX11 필요 문장만 인용함.",
    },
    "authored_canary_sha256_9e2c7f69dd204fd5229a8e21b441b7d2c07b3e4ba5eb73ee5b40f5867f4bb875": {
        "type": "B_RETRIEVAL_MISS",
        "severity": "catchable",
        "form": "unsupported_requirement_marked_full",
        "comparison": "The event chunk containing the 50M daily cap is absent; a shop duplicate supports expiry only, while 'season limited' is cited for the cap and the personal calculation is not enumerated.",
        "summary": "마일리지 시즌7: 50M 한도 근거가 없고 소멸일만 맞는 shop 중복본과 '시즌한정'을 인용함.",
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


def validate_classifications(classifications: dict[str, dict[str, str]]) -> None:
    if len(classifications) != 9:
        raise RuntimeError("The frozen false-full audit must contain exactly nine cases")
    for case_id, item in classifications.items():
        if item.get("type") not in TYPE_LABELS:
            raise RuntimeError(f"Invalid primary type: {case_id}")
        if item.get("severity") not in SEVERITY_LABELS:
            raise RuntimeError(f"Invalid severity: {case_id}")
        if item.get("form") not in FORM_LABELS:
            raise RuntimeError(f"Invalid form: {case_id}")
        if not item.get("comparison") or not item.get("summary"):
            raise RuntimeError(f"Missing audit rationale: {case_id}")


def build_audit_cases(
    *,
    backbone_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    assembler_rows: list[dict[str, Any]],
    rerank_result_rows: list[dict[str, Any]],
    rerank_score_rows: list[dict[str, Any]],
    taxonomy_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    validate_classifications(CLASSIFICATIONS)
    false_full = {
        row["case_id"]: row
        for row in backbone_rows
        if row["arm0"]["score"]["false_full_answer"]
    }
    if set(false_full) != set(CLASSIFICATIONS):
        raise RuntimeError("Frozen false-full IDs changed")
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    assemblers = {row["case_id"]: row for row in assembler_rows}
    rerank_results = {row["case_id"]: row for row in rerank_result_rows}
    rerank_scores = {row["case_id"]: row for row in rerank_score_rows}
    taxonomy = {row["case_id"]: row for row in taxonomy_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    output = []
    for case_id in sorted(false_full):
        evaluation = evaluations[case_id]
        enumeration = enumerations[case_id]
        assembler = assemblers[case_id]
        candidate_ids = {
            candidate["chunk_id"]
            for requirement in rerank_scores[case_id]["requirements"]
            for candidate in requirement["candidates"]
        }
        system_citations = []
        for requirement, decision in zip(
            enumeration["requirements"], assembler["decisions"], strict=True
        ):
            system_citations.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "subject": requirement["subject"],
                    "relation": requirement["relation"],
                    "status": decision["status"],
                    "spans": [
                        {
                            "chunk_id": span["chunk_id"],
                            "parent_document_id": chunks_by_id[span["chunk_id"]]["parent_document_id"],
                            "text": span["text"],
                        }
                        for span in decision["spans"]
                    ],
                }
            )
        gold_evidence = []
        for group in evaluation["evidence_groups"]:
            acceptable = []
            for chunk_id in group["acceptable_chunk_ids"]:
                chunk = chunks_by_id[chunk_id]
                acceptable.append(
                    {
                        "chunk_id": chunk_id,
                        "parent_document_id": chunk["parent_document_id"],
                        "text": chunk["display_text"],
                    }
                )
            gold_evidence.append(
                {
                    "group_id": group["group_id"],
                    "candidate_present": bool(set(group["acceptable_chunk_ids"]) & candidate_ids),
                    "acceptable": acceptable,
                }
            )
        audit = CLASSIFICATIONS[case_id]
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": false_full[case_id]["dataset"],
                "question": evaluation["question"],
                "planner_requirements": enumeration["requirements"],
                "system_citations": system_citations,
                "gold_evidence": gold_evidence,
                "retrieval_bound_group_ids": rerank_results[case_id]["retrieval_bound_group_ids"],
                "prior_routing_taxonomy": taxonomy.get(case_id, {}).get("failure_type"),
                "classification": audit["type"],
                "severity": audit["severity"],
                "form": audit["form"],
                "direct_comparison": audit["comparison"],
                "one_line_summary": audit["summary"],
                "gold_ids_used_for_diagnosis_only": True,
                "runtime_rule_created": False,
            }
        )
    return output


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts = Counter(row["classification"] for row in cases)
    severity_counts = Counter(row["severity"] for row in cases)
    form_counts = Counter(row["form"] for row in cases)
    return {
        "case_count": len(cases),
        "type_counts": {label: type_counts[label] for label in sorted(TYPE_LABELS)},
        "severity_counts": {label: severity_counts[label] for label in sorted(SEVERITY_LABELS)},
        "form_counts": {label: form_counts[label] for label in sorted(FORM_LABELS)},
        "true_hardcore_wrong_attribute_count": type_counts["A_WRONG_ATTRIBUTE"],
        "actual_error_count_excluding_measurement_artifact": len(cases) - type_counts["C_MEASUREMENT_ARTIFACT"],
    }


def _markdown(report: dict[str, Any], cases: list[dict[str, Any]]) -> bytes:
    counts = report["summary"]
    lines = [
        "# False-full nine-case audit",
        "",
        f"- runtime decision: **{report['decision']}**",
        f"- A/B/C/D: **{counts['type_counts']['A_WRONG_ATTRIBUTE']} / {counts['type_counts']['B_RETRIEVAL_MISS']} / {counts['type_counts']['C_MEASUREMENT_ARTIFACT']} / {counts['type_counts']['D_CROSS_PARENT_MISS']}**",
        f"- true hardcore wrong-attribute cases: **{counts['true_hardcore_wrong_attribute_count']}**",
        f"- catchable/subtle: **{counts['severity_counts']['catchable']} / {counts['severity_counts']['subtle']}**",
        "",
        "| # | dataset | type | severity | form | one-line comparison |",
        "|---:|---|---|---|---|---|",
    ]
    for index, row in enumerate(cases, 1):
        lines.append(
            f"| {index} | {row['dataset']} | {row['classification']} | {row['severity']} | {row['form']} | {row['one_line_summary']} |"
        )
    lines.extend(
        [
            "",
            "`C_MEASUREMENT_ARTIFACT=0`: no case was removed merely because a nearby or duplicate document stated a similar value; subject and requested attribute still had to be supported.",
            "",
            "No question, gold, label, planner output, retrieval result, router, verifier, or assembler was changed.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def audit_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "planner_enumeration": root / DEFAULT_ENUMERATION,
        "assembler_cases": root / DEFAULT_ASSEMBLER,
        "requirement_reranker_results": root / DEFAULT_RERANK_RESULTS,
        "requirement_reranker_scores": root / DEFAULT_RERANK_SCORES,
        "router_backbone_cases": root / DEFAULT_BACKBONE,
        "router_backbone_manifest": root / DEFAULT_BACKBONE_MANIFEST,
        "routing_taxonomy": root / DEFAULT_TAXONOMY,
        "chunks": root / DEFAULT_CHUNKS,
        "verifier_report": root / DEFAULT_VERIFIER_REPORT,
        "verifier_manifest": root / DEFAULT_VERIFIER_MANIFEST,
        "contract": root / DEFAULT_CONTRACT,
        "auditor_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in input_paths.items()}
    backbone_manifest = json.loads(input_paths["router_backbone_manifest"].read_text(encoding="utf-8"))
    if backbone_manifest["artifacts"]["cases"]["sha256"] != before["router_backbone_cases"]:
        raise RuntimeError("Router backbone lineage mismatch")
    verifier_manifest = json.loads(input_paths["verifier_manifest"].read_text(encoding="utf-8"))
    if verifier_manifest["artifacts"]["report"]["sha256"] != before["verifier_report"]:
        raise RuntimeError("Verifier lineage mismatch")

    cases = build_audit_cases(
        backbone_rows=read_jsonl(input_paths["router_backbone_cases"]),
        evaluation_rows=read_jsonl(input_paths["adaptive_dev"]) + read_jsonl(input_paths["downgraded_canary"]),
        enumeration_rows=read_jsonl(input_paths["planner_enumeration"]),
        assembler_rows=read_jsonl(input_paths["assembler_cases"]),
        rerank_result_rows=read_jsonl(input_paths["requirement_reranker_results"]),
        rerank_score_rows=read_jsonl(input_paths["requirement_reranker_scores"]),
        taxonomy_rows=read_jsonl(input_paths["routing_taxonomy"]),
        chunks=read_jsonl(input_paths["chunks"]),
    )
    summary = summarize(cases)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "evaluation_role": "development_only_false_full_ceiling_diagnostic",
        "decision": "DIAGNOSTIC_COMPLETE_RUNTIME_REMAINS_NO_GO",
        "summary": summary,
        "ceiling_interpretation": {
            "observed_false_full": 9,
            "measurement_artifacts": summary["type_counts"]["C_MEASUREMENT_ARTIFACT"],
            "real_errors": summary["actual_error_count_excluding_measurement_artifact"],
            "true_hardcore_wrong_attribute": summary["true_hardcore_wrong_attribute_count"],
            "upstream_retrieval": summary["type_counts"]["B_RETRIEVAL_MISS"],
            "cross_parent": summary["type_counts"]["D_CROSS_PARENT_MISS"],
            "runtime_ceiling_claim": "The nine observed false-full cases are all real under the frozen gold; only two are post-retrieval wrong-attribute hard cases.",
        },
        "case_summaries": [
            {
                "case_id": row["case_id"],
                "classification": row["classification"],
                "severity": row["severity"],
                "form": row["form"],
                "summary": row["one_line_summary"],
            }
            for row in cases
        ],
        "scope": {
            "questions_gold_or_labels_changed": False,
            "runtime_code_changed": False,
            "canonical_or_runtime_promoted": False,
            "model_or_training_run": False,
            "sealed_canary_run": False,
            "frozen_blind_accessed": False,
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in input_paths.items()
        },
        "source_commit": _git_head(root),
    }
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    case_bytes = _serialize_jsonl(cases, lambda row: row["case_id"])
    case_sha = _sha256_bytes(case_bytes)
    case_path = evidence_dir / f"false_full_case_audit_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    report["artifacts"] = {
        "cases": {"path": _relative(root, case_path), "sha256": case_sha, "row_count": len(cases)}
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"false_full_audit_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report, cases)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"false_full_audit_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "inputs": report["inputs"],
        "classification_contract": {
            "types": sorted(TYPE_LABELS),
            "severity": sorted(SEVERITY_LABELS),
            "forms": sorted(FORM_LABELS),
            "exactly_one_primary_type_per_case": True,
            "gold_ids_used_for_diagnosis_only": True,
        },
        "artifacts": {
            "cases": report["artifacts"]["cases"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "source_commit": report["source_commit"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"false_full_audit_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    after = {name: file_sha256(path) for name, path in input_paths.items()}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise RuntimeError(f"Inputs changed during false-full audit: {changed}")
    return {
        "summary": summary,
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
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Audit the frozen nine false-full cases")
    parser.add_argument("--root", type=Path, default=root)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = audit_and_freeze(parse_args().root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

