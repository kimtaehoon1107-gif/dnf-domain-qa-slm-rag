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


AUDITOR_VERSION = "federated-quota-regression-adjudication-v3.1.0"
CASE_SCHEMA_VERSION = "federated-quota-regression-adjudication-case-v3.1"
REPORT_SCHEMA_VERSION = "federated-quota-regression-adjudication-report-v3.1"
MANIFEST_SCHEMA_VERSION = "federated-quota-regression-adjudication-manifest-v3.1"

CLASSIFICATIONS = frozenset(
    {
        "NAVIGATION_CONTAMINATION",
        "PERSONAL_SUBJECTIVE_LABEL",
        "EQUIVALENT_OFFICIAL",
        "PARTIAL_SUPPORT",
        "REAL_WRONG",
    }
)
MECHANICAL_CLASSIFICATIONS = frozenset(
    {"NAVIGATION_CONTAMINATION", "PERSONAL_SUBJECTIVE_LABEL"}
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
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_FEDERATED_CASES = Path(
    "data/v3/evidence/federated_retrieval_ab_cases_"
    "c9921d0e7570ba77a40e7be94d85951f9419a2fe8847fc81c49891780f51f28f.jsonl"
)
DEFAULT_FEDERATED_REPORT = Path(
    "reports/v3/federated_retrieval_ab_"
    "0e48bfbc2d69d6b524b98b83c79d0ff296540ba05374e72cd1ec6f0616a5172c.json"
)


PROPOSALS: dict[str, dict[str, Any]] = {
    "authored_canary_sha256_bdca3e909e293adac753b2ee3d48c983b39dfb048aeb1491ca617c40fe2f058c": {
        "classification": "PARTIAL_SUPPORT",
        "rationale": "The quota citations support the three-device limit but do not support the OTP-authenticate, re-register, then contact-support sequence.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_144296d937ab23d899b3375c994f2e6568b4a9febb2beb18a68de0a89465c047": {
        "classification": "PERSONAL_SUBJECTIVE_LABEL",
        "rationale": "The question asks whether a character choice is best for the user's account; the frozen row is partial and the subjective/personal portion is not document-answerable.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_276285e742e29bcaf73ac83f7d7d663ed35324bc0d73cd0c5416020951fb15d2": {
        "classification": "NAVIGATION_CONTAMINATION",
        "rationale": "The citation matches a revision-selector date and generic policy labels, not the 2022 sanction row requested by the question.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_2d3c912b022e4d5719ea8be0c7f379cdb1016553074a424b0961309668d1f166": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "Current official anti-phishing chunks independently warn that external/private-channel transactions can be scams and require caution; human confirmation is still required.",
        "sibling_suffixes": ["6a909263", "bb8447f3"],
    },
    "retrieval_dev_sha256_420bbef6b2bc275336fa84efd968b94eba7143a6d445203607eeab6b7dfafdf2": {
        "classification": "REAL_WRONG",
        "rationale": "The cited chunks mention other removed elements or generic guide headings and do not state that the kraken tentacle was removed from the boss-map background.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_59ca7a033abaec5d72433fd9b114842276ddc4e79774e4894d13ef5e1813a344": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "A current official anti-phishing chunk identifies separate payment windows as a high-risk demand; equivalence to the older verification/reporting guidance needs human confirmation.",
        "sibling_suffixes": ["bb8447f3"],
    },
    "retrieval_dev_sha256_64d1cca28aa1cff2106d80948722fd600fc754bc741f900c508878fa8dcc68b6": {
        "classification": "REAL_WRONG",
        "rationale": "The selected shop and FAQ chunks do not give the 1,500 Sera price and exchangeable transaction type for the ten-coin item.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_710a27a0b12799a13b8c438918dccbdc7f3d057fb0568112b0d5538a171bee60": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "A current official notice gives Police 112/182 and KISA 118, covering the frozen reporting/contact fact through a different official chunk.",
        "sibling_suffixes": ["eec2b24a"],
    },
    "retrieval_dev_sha256_7a21edccb2b54a7b27b20dd4d39e75b59d30736ba162c3f1f4c0fc687c9c7fb1": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "The current policy recovery section explicitly says a confirmed offending account receives permanent game-use restriction, matching the requested sanction.",
        "sibling_suffixes": ["83e49362"],
    },
    "retrieval_dev_sha256_8c5b2427c17a8558f6798e416e7e2c70d3c5e3209b577cdc18c9fe47d5948c5f": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "Different official shop/event chunks state the same tropical-package and Arad Pass end dates; only the fully supporting content chunks are proposed.",
        "sibling_suffixes": ["b3ab5c7d", "20591850"],
    },
    "retrieval_dev_sha256_9b2293077ca24ac8aa5779b5cf39ef32daad85740f8a3baf4bfbc5cbf8813d2a": {
        "classification": "NAVIGATION_CONTAMINATION",
        "rationale": "The apparent sale period comes from a shop listing/navigation tail attached to another content chunk; it is not accepted as evidence.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_c60c1c016613a625972ef00723f331521b8c1f638da9b4c582c00cdbf8a56a45": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "The current policy directly states that abnormal assets are recovered regardless of intent or awareness, semantically matching the frozen policy fact.",
        "sibling_suffixes": ["98a8b382"],
    },
    "retrieval_dev_sha256_d9e83e70677e5c46c0001cfb60afbebe320f1e4f6a8e02a0dc6c2bddd9b39fdc": {
        "classification": "NAVIGATION_CONTAMINATION",
        "rationale": "The cited July label is drawn from shop listing/navigation text and does not state the requested August 13 deletion time.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_dcdaaad819576ff6baa88a3c665180d25ecb977c10901f002a990f9c079f4d60": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "The current Seria-shop chunk gives the exact July 2026 deletion time while the frozen June gold remains cited; the older July distractor is not proposed.",
        "sibling_suffixes": ["670c84c0"],
    },
    "retrieval_dev_sha256_e8fca9ea0e3ae1f800d681598491561e51d78bef22ec111bc0f1c98a2923e759": {
        "classification": "REAL_WRONG",
        "rationale": "The citations mention generic fatigue headings and a post-completion availability period, not that training simulation consumes no fatigue.",
        "sibling_suffixes": [],
    },
    "retrieval_dev_sha256_f445f9f8c954555863d745271d649b3a355eabae395f907a575dcf21fa4c6342": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "The official event chunk states the complete June 4 through August 13 Arad Pass period and is a candidate acceptable sibling to the shop chunk.",
        "sibling_suffixes": ["fe4aaafb"],
    },
    "retrieval_dev_sha256_fcfa74c5247ce198bc388a079c17b06aa35b6aea0b3c09b091230a17b746a43e": {
        "classification": "EQUIVALENT_OFFICIAL",
        "rationale": "A current official anti-phishing chunk explicitly says to stop when phone or authentication numbers are requested; human confirmation against the older scenario wording is required.",
        "sibling_suffixes": ["f83fcd4b"],
    },
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _resolve_suffixes(chunk_ids: list[str], suffixes: list[str]) -> list[str]:
    resolved = []
    for suffix in suffixes:
        matches = [chunk_id for chunk_id in chunk_ids if chunk_id.endswith(suffix)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one cited chunk ending in {suffix}, got {matches}")
        resolved.append(matches[0])
    return resolved


def regression_case_ids(report: dict[str, Any]) -> set[str]:
    baseline_false = set(report["arms"]["arm_a"]["false_full_case_ids"])
    quota_false = set(report["arms"]["federated_quota"]["false_full_case_ids"])
    return quota_false - baseline_false


def build_adjudication_rows(
    *,
    report: dict[str, Any],
    evaluation_rows: list[dict[str, Any]],
    enumeration_rows: list[dict[str, Any]],
    federated_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_ids = regression_case_ids(report)
    if target_ids != set(PROPOSALS):
        raise RuntimeError("Frozen quota regression IDs changed")
    evaluations = {row["dev_id"]: row for row in evaluation_rows}
    enumerations = {row["case_id"]: row for row in enumeration_rows}
    federated = {row["case_id"]: row for row in federated_rows}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    output = []
    for case_id in sorted(target_ids):
        evaluation = evaluations[case_id]
        quota = federated[case_id]["federated_quota"]
        cited_ids = quota["cited_chunk_ids"]
        proposal = PROPOSALS[case_id]
        classification = proposal["classification"]
        if classification not in CLASSIFICATIONS:
            raise RuntimeError(f"Invalid classification: {classification}")
        siblings = _resolve_suffixes(cited_ids, proposal["sibling_suffixes"])
        if bool(siblings) != (classification == "EQUIVALENT_OFFICIAL"):
            raise RuntimeError(f"Sibling proposal contract violated: {case_id}")
        original_gold = []
        for group in evaluation["evidence_groups"]:
            original_gold.append(
                {
                    "group_id": group["group_id"],
                    "evidence_span": group["evidence_span"],
                    "acceptable_chunks": [
                        {
                            "chunk_id": chunk_id,
                            "parent_document_id": chunks_by_id[chunk_id]["parent_document_id"],
                            "source_id": chunks_by_id[chunk_id]["source_id"],
                            "text": chunks_by_id[chunk_id]["display_text"],
                        }
                        for chunk_id in group["acceptable_chunk_ids"]
                    ],
                }
            )
        citations = [
            {
                "chunk_id": chunk_id,
                "parent_document_id": chunks_by_id[chunk_id]["parent_document_id"],
                "source_id": chunks_by_id[chunk_id]["source_id"],
                "text": chunks_by_id[chunk_id]["display_text"],
                "proposed_acceptable_sibling": chunk_id in siblings,
            }
            for chunk_id in cited_ids
        ]
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case_id,
                "dataset": federated[case_id]["dataset"],
                "question": evaluation["question"],
                "frozen_answerability": evaluation["answerability"],
                "requirements": [
                    {
                        key: requirement[key]
                        for key in (
                            "requirement_id",
                            "subject",
                            "relation",
                            "value_type",
                            "subject_group",
                        )
                    }
                    for requirement in enumerations[case_id]["requirements"]
                ],
                "original_gold": original_gold,
                "federated_quota_citations": citations,
                "classification": classification,
                "classification_status": (
                    "confirmed_mechanical"
                    if classification in MECHANICAL_CLASSIFICATIONS
                    else "provisional_requires_human_or_strong_judge"
                ),
                "rationale": proposal["rationale"],
                "proposed_acceptable_sibling_chunk_ids": siblings,
                "sibling_proposal_applied": False,
                "original_gold_changed": False,
                "label_or_question_changed": False,
                "weak_4b_semantic_judge_used": False,
                "semantic_model_used": None,
                "canonical_or_runtime_promoted": False,
            }
        )
    return output


def summarize(report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["classification"] for row in rows)
    equivalent = counts["EQUIVALENT_OFFICIAL"]
    baseline_grounded = report["arms"]["arm_a"]["answerable"]["grounded_answer"][
        "successes"
    ]
    quota_grounded = report["arms"]["federated_quota"]["answerable"][
        "grounded_answer"
    ]["successes"]
    quota_false = report["arms"]["federated_quota"]["answerable"][
        "false_full_answer"
    ]["successes"]
    baseline_regressions = report["arms"]["federated_quota"]["answerable"][
        "baseline_grounded_regression_count"
    ]
    return {
        "case_count": len(rows),
        "classification_counts": {
            label: counts[label] for label in sorted(CLASSIFICATIONS)
        },
        "strict": {
            "baseline_grounded": baseline_grounded,
            "quota_grounded": quota_grounded,
            "quota_false_full": quota_false,
            "new_false_full_regressions": len(rows),
            "baseline_grounded_gross_regressions": baseline_regressions,
            "original_acceptable_set_net_grounded_loss": baseline_grounded
            - quota_grounded,
        },
        "provisional_if_all_equivalent_candidates_are_confirmed": {
            "equivalent_candidate_count": equivalent,
            "quota_grounded": quota_grounded + equivalent,
            "quota_false_full": quota_false - equivalent,
            "new_false_full_regressions": len(rows) - equivalent,
        },
        "strict_net_loss_remains_unchanged_without_applied_siblings": baseline_grounded
        - quota_grounded,
        "semantic_review_required_count": len(rows)
        - sum(counts[label] for label in MECHANICAL_CLASSIFICATIONS),
        "sibling_proposal_applied_count": 0,
    }


def _markdown(report: dict[str, Any], rows: list[dict[str, Any]]) -> bytes:
    summary = report["summary"]
    strict = summary["strict"]
    provisional = summary["provisional_if_all_equivalent_candidates_are_confirmed"]
    lines = [
        "# Federated quota 17-case adjudication proposal",
        "",
        "- Decision: **PROVISIONAL_REVIEW_REQUIRED_NO_PROMOTION**",
        f"- Strict quota: grounded **{strict['quota_grounded']}/82**, false-full **{strict['quota_false_full']}/82**.",
        f"- Strict baseline-grounded gross regressions: **{strict['baseline_grounded_gross_regressions']}**; original acceptable-set net grounded loss remains **{strict['original_acceptable_set_net_grounded_loss']}** (73→63).",
        f"- Provisional only, if all equivalent-official candidates are independently confirmed: grounded **{provisional['quota_grounded']}/82**, false-full **{provisional['quota_false_full']}/82**, new regressions **{provisional['new_false_full_regressions']}**.",
        "- Original gold, labels, and questions were not changed. No sibling proposal was applied.",
        "- No semantic model was used; in particular, no weak 4B matcher was used.",
        "",
        "| # | id | class | status | sibling proposal | rationale |",
        "|---:|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, 1):
        siblings = ", ".join(chunk_id[-8:] for chunk_id in row["proposed_acceptable_sibling_chunk_ids"]) or "-"
        lines.append(
            f"| {index} | {row['case_id'][-8:]} | {row['classification']} | {row['classification_status']} | {siblings} | {row['rationale']} |"
        )
    lines.extend(
        [
            "",
            "`EQUIVALENT_OFFICIAL`, `PARTIAL_SUPPORT`, and `REAL_WRONG` are proposals for a human or independent strong judge, not final labels. Strict metrics remain canonical.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def adjudicate_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "adaptive_dev": root / DEFAULT_DEV,
        "authored_canary": root / DEFAULT_CANARY,
        "planner_enumeration": root / DEFAULT_ENUMERATION,
        "chunks": root / DEFAULT_CHUNKS,
        "federated_cases": root / DEFAULT_FEDERATED_CASES,
        "federated_report": root / DEFAULT_FEDERATED_REPORT,
        "auditor_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    frozen_report = json.loads(inputs["federated_report"].read_text(encoding="utf-8"))
    rows = build_adjudication_rows(
        report=frozen_report,
        evaluation_rows=read_jsonl(inputs["adaptive_dev"])
        + read_jsonl(inputs["authored_canary"]),
        enumeration_rows=read_jsonl(inputs["planner_enumeration"]),
        federated_rows=read_jsonl(inputs["federated_cases"]),
        chunks=read_jsonl(inputs["chunks"]),
    )
    summary = summarize(frozen_report, rows)
    result_report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "evaluation_role": "development_only_independent_adjudication_proposal",
        "decision": "PROVISIONAL_REVIEW_REQUIRED_NO_PROMOTION",
        "summary": summary,
        "equivalent_official_candidates": [
            {
                "case_id": row["case_id"],
                "question": row["question"],
                "proposed_acceptable_sibling_chunk_ids": row[
                    "proposed_acceptable_sibling_chunk_ids"
                ],
                "applied": False,
            }
            for row in rows
            if row["classification"] == "EQUIVALENT_OFFICIAL"
        ],
        "scope": {
            "gold_label_or_question_changed": False,
            "sibling_proposal_applied": False,
            "canonical_or_runtime_promoted": False,
            "weak_4b_semantic_judge_used": False,
            "model_run": False,
            "training_run": False,
            "sealed_canary_run": False,
            "frozen_blind_accessed": False,
        },
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "source_commit": _git_head(root),
    }
    evidence_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    row_bytes = _serialize_jsonl(rows, lambda row: row["case_id"])
    row_sha = _sha256_bytes(row_bytes)
    row_path = evidence_dir / f"federated_quota_regression_adjudication_{row_sha}.jsonl"
    write_immutable(row_path, row_bytes)
    result_report["artifacts"] = {
        "adjudication_sheet": {
            "path": _relative(root, row_path),
            "sha256": row_sha,
            "row_count": len(rows),
        }
    }
    report_bytes = _canonical_json_bytes(result_report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"federated_quota_regression_adjudication_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(result_report, rows)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"federated_quota_regression_adjudication_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "inputs": result_report["inputs"],
        "classification_contract": {
            "classifications": sorted(CLASSIFICATIONS),
            "mechanical_confirmable": sorted(MECHANICAL_CLASSIFICATIONS),
            "semantic_proposals_require_human_or_strong_judge": [
                "EQUIVALENT_OFFICIAL",
                "PARTIAL_SUPPORT",
                "REAL_WRONG",
            ],
            "strict_metrics_replaced": False,
            "gold_changed": False,
            "siblings_applied": False,
        },
        "artifacts": {
            "adjudication_sheet": result_report["artifacts"]["adjudication_sheet"],
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "source_commit": result_report["source_commit"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"federated_quota_regression_adjudication_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise RuntimeError(f"Inputs changed during adjudication: {changed}")
    return {
        "summary": summary,
        "sheet_path": str(row_path),
        "sheet_sha256": row_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "input_hash_mismatch_count": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose adjudication for quota regressions")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(adjudicate_and_freeze(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
