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


AUDITOR_VERSION = "authored-validation-v3.2-failure-audit-v1.0"
SCHEMA_VERSION = "authored-validation-v3.2-failure-audit-case-v1"
DEFAULT_RESULTS = Path(
    "data/v3/evaluation/authored_validation_v3_2_results_"
    "7825374fd4fbf72d426d68dc3f401803de5036a3753f9d92f267f36c03062415.jsonl"
)
DEFAULT_Q4_AUDIT = Path(
    "reports/v3/q4_docs_false_full_audit_"
    "d921344401a5ec2b2e90d6a91d193803c0ce566e2d08f53f942469f3880210c5.json"
)
DEFAULT_CONTRACT = Path("docs/v3/authored_validation_v3_2_failure_audit.md")


CLASSIFICATIONS: dict[str, dict[str, Any]] = {
    "authored_validation_v3_2_sha256_1d39b270356513cdb4253f033e20f082f9ae900bc72df6d61467e44728cf6b7d": {
        "stage": "MEASUREMENT",
        "rationale": "FAQ cites the exact same official 40-slot/400-Sera and 56-slot/800-Sera rows as the shop document; strict gold contains only the shop duplicate.",
        "equivalent_sibling_chunk_ids": ["chunk_sha256_b2f6e4b7973ed004d667c9b752147a6c03726109657d8f309c157cc9312226db"],
    },
    "authored_validation_v3_2_sha256_40d289dd5270c3f966a5803e73f2d0e082299e42ab3d8fafd07ad03e1704f870": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "rationale": "The route chose shop rather than the event parent containing both prices; headings and purchase guidance were cited without either value.",
    },
    "authored_validation_v3_2_sha256_83b1e5e40c10b5200d6d31ce129c20a37f6d058ec8bd4ee89a01e8c19b72e5e5": {
        "stage": "RETRIEVAL",
        "rationale": "Monthly-item was correctly routed, but the event body containing the period and both buff values never reached selected evidence; the system honestly returned partial.",
    },
    "authored_validation_v3_2_sha256_90331aa9b7b5f37f49407ecd60f8aadaf6bb9875a4c633e8cb7a8bcc7aea2abc": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "rationale": "The route chose update instead of game guide and cited unrelated level/awakening text as a full answer.",
    },
    "authored_validation_v3_2_sha256_afa90335c1c66670cab47342d634d092b29598a571a80c31df3e5f890442bbf8": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "rationale": "The route chose update instead of the dated notice and cited unrelated fixed issues without the affected jobs or client-patch resolution.",
    },
    "authored_validation_v3_2_sha256_b5962b72942b9d1ebdfd611d489f7e73df51bb65d167710ad43dab70db0b1e24": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "rationale": "The route chose generic FAQ withdrawal guidance instead of the shop product containing price, account limit, and withdrawal eligibility; the system honestly returned partial.",
    },
    "authored_validation_v3_2_sha256_c0c2d4091eda6655d6e8f0bdbc01a155e39e637642f903e8da2d288fd6cac599": {
        "stage": "SELECTION_SUPPORT",
        "rationale": "The chosen game-guide chunk contains both exact gold facts, but the assembler cited only the heading and exploration-type text.",
        "equivalent_sibling_chunk_ids": ["chunk_sha256_96aad618428b25d25835e640f79d23f936d4d5404ccaf27781d1b619456cd270"],
    },
    "authored_validation_v3_2_sha256_c8803a9d34cc39551e80708aa46733e0483fa27c8e5f29a75f2f85154b44874a": {
        "stage": "ROUTING_SOURCE_SCOPE",
        "rationale": "The route chose generic FAQ transfer limits instead of the Quick Transfer notice and presented different limits as a full answer.",
    },
}


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def validate_classifications() -> None:
    if len(CLASSIFICATIONS) != 8:
        raise RuntimeError("Authored validation failure audit must contain eight cases")
    allowed = {"ROUTING_SOURCE_SCOPE", "RETRIEVAL", "SELECTION_SUPPORT", "MEASUREMENT"}
    for case_id, item in CLASSIFICATIONS.items():
        if item["stage"] not in allowed or not item["rationale"]:
            raise RuntimeError(f"Invalid classification: {case_id}")


def build_cases(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validate_classifications()
    failures = {row["case_id"]: row for row in results if not row["score"]["all_groups_hit"]}
    if set(failures) != set(CLASSIFICATIONS):
        raise RuntimeError("Frozen authored validation failure IDs changed")
    output = []
    for case_id in sorted(failures):
        source = failures[case_id]
        classification = CLASSIFICATIONS[case_id]
        citations = [
            {
                "requirement": requirement["requirement"],
                "status": requirement["status"],
                "citations": [
                    {
                        "chunk_id": citation["chunk_id"],
                        "source_id": citation["source_id"],
                        "parent_document_id": citation["parent_document_id"],
                        "text": citation["text"],
                    }
                    for citation in requirement.get("citations", [])
                ],
            }
            for requirement in source["runtime"]["requirements"]
        ]
        output.append(
            {
                "case_schema_version": SCHEMA_VERSION,
                "case_id": case_id,
                "question": source["question"],
                "expected_source_id": source["source_id"],
                "route": source["runtime"]["route"],
                "response_mode": source["runtime"]["response_mode"],
                "strict_score": source["score"],
                "system_citations": citations,
                "gold_evidence": source["evaluation"]["evidence_groups"],
                "earliest_failure_stage": classification["stage"],
                "rationale": classification["rationale"],
                "equivalent_sibling_proposal": classification.get(
                    "equivalent_sibling_chunk_ids", []
                ),
                "gold_changed": False,
                "proposal_applied": False,
            }
        )
    return output


def summarize(cases: list[dict[str, Any]], q4_summary: dict[str, Any]) -> dict[str, Any]:
    stages = Counter(row["earliest_failure_stage"] for row in cases)
    measurement = stages["MEASUREMENT"]
    strict_pass = 24 - len(cases)
    strict_false_full = sum(row["strict_score"]["false_full"] for row in cases)
    return {
        "before_q4_six": q4_summary["stage_counts"],
        "new_strict": {
            "all_groups_covered": {"successes": strict_pass, "total": 24},
            "false_full": {"successes": strict_false_full, "total": 24},
            "failure_stage_counts_after_direct_audit": dict(sorted(stages.items())),
        },
        "new_provisional_adjudicated": {
            "all_groups_covered": {"successes": strict_pass + measurement, "total": 24},
            "false_full": {"successes": strict_false_full - measurement, "total": 24},
            "equivalent_official_candidates_pending": measurement,
        },
        "actual_error_count_excluding_measurement": len(cases) - measurement,
        "dominant_pattern_repeated": stages["ROUTING_SOURCE_SCOPE"] >= 4,
        "gold_or_sibling_changed": False,
    }


def _markdown(report: dict[str, Any], cases: list[dict[str, Any]]) -> bytes:
    summary = report["summary"]
    lines = [
        "# Authored validation v3.2 failure audit",
        "",
        "The set is adaptive validation after this inspection; strict gold is unchanged.",
        "",
        f"- strict: **{summary['new_strict']['all_groups_covered']['successes']}/24**, false-full **{summary['new_strict']['false_full']['successes']}/24**",
        f"- provisional adjudicated: **{summary['new_provisional_adjudicated']['all_groups_covered']['successes']}/24**, false-full **{summary['new_provisional_adjudicated']['false_full']['successes']}/24**",
        f"- before Q4 six stages: **{json.dumps(summary['before_q4_six'], ensure_ascii=False)}**",
        f"- new stages: **{json.dumps(summary['new_strict']['failure_stage_counts_after_direct_audit'], ensure_ascii=False)}**",
        "",
        "| # | stage | response | question | rationale |",
        "|---:|---|---|---|---|",
    ]
    for index, row in enumerate(cases, 1):
        lines.append(
            f"| {index} | {row['earliest_failure_stage']} | {row['response_mode']} | "
            f"{row['question']} | {row['rationale']} |"
        )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def audit_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "results": root / DEFAULT_RESULTS,
        "q4_audit": root / DEFAULT_Q4_AUDIT,
        "contract": root / DEFAULT_CONTRACT,
        "auditor_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    q4_report = json.loads(inputs["q4_audit"].read_text(encoding="utf-8"))
    cases = build_cases(read_jsonl(inputs["results"]))
    report = {
        "report_schema_version": "authored-validation-v3.2-failure-audit-report-v1",
        "auditor_version": AUDITOR_VERSION,
        "evaluation_role": "adaptive_validation_post_run_diagnostic",
        "decision": "NO_GO_ROUTING_SOURCE_SCOPE_REPEATED",
        "summary": summarize(cases, q4_report["summary"]),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "source_commit": _git_head(root),
    }
    case_bytes = _serialize_jsonl(cases, lambda row: row["case_id"])
    case_sha = hashlib.sha256(case_bytes).hexdigest()
    case_path = root / "data/v3/evaluation" / f"authored_validation_v3_2_failure_audit_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    report["artifact"] = {"path": _relative(root, case_path), "sha256": case_sha, "row_count": len(cases)}
    report_bytes = _canonical_json_bytes(report)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = root / "reports/v3" / f"authored_validation_v3_2_failure_audit_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report, cases)
    markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
    markdown_path = root / "reports/v3" / f"authored_validation_v3_2_failure_audit_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": "authored-validation-v3.2-failure-audit-manifest-v1",
        "auditor_version": AUDITOR_VERSION,
        "inputs": report["inputs"],
        "artifacts": {
            "cases": report["artifact"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "source_commit": report["source_commit"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = root / "data/v3/evaluation" / f"authored_validation_v3_2_failure_audit_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    if [name for name in before if before[name] != after[name]]:
        raise RuntimeError("Failure-audit inputs changed")
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
    parser = argparse.ArgumentParser(description="Audit authored validation v3.2 failures")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(audit_and_freeze(parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
