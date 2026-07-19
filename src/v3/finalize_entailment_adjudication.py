from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.prepare_entailment_adjudication import (
    audit_adjudication_reviews,
    review_text_corruption_fields,
)
from src.v3.prepare_entailment_review import REVIEW_FIELDS
from src.v3.review_entailment_app import validate_draft_structure


FINALIZER_VERSION = "entailment-natural-adjudication-finalizer-v3.1.0"
REVIEW_SCHEMA_VERSION = "entailment-natural-adjudication-reviews-v3.1"
ISSUE_SCHEMA_VERSION = "entailment-natural-review-issue-v3.1"
CORRECTION_SCHEMA_VERSION = "entailment-natural-claim-correction-v3.1"
REPAIR_PACKET_SCHEMA_VERSION = "entailment-natural-claim-repair-item-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-natural-adjudication-final-manifest-v3.1"
REPORT_SCHEMA_VERSION = "entailment-natural-adjudication-final-report-v3.1"

DEFAULT_PACKET = Path(
    "data/v3/evaluation/"
    "entailment_natural_adjudication_packet_2c82048a7ca51177278bbd9ec8782a80afae18d2f446ab0e6d365ae62de82b31.jsonl"
)
DEFAULT_DRAFT = Path(
    "outputs/v3/annotation/"
    "entailment_natural_adjudication_draft_2c82048a7ca51177278bbd9ec8782a80afae18d2f446ab0e6d365ae62de82b31.jsonl"
)
DEFAULT_SAMPLING_LEDGER = Path(
    "data/v3/evaluation/"
    "entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl"
)
DEFAULT_FINALIZER_SOURCE = Path("src/v3/finalize_entailment_adjudication.py")
DEFAULT_REVIEW_APP_SOURCE = Path("src/v3/review_entailment_app.py")
DEFAULT_CONTRACT = Path("docs/v3/entailment_claim_repair.md")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def classify_review_issues(row: dict[str, Any]) -> list[str]:
    rationale = (row.get("review_rationale") or "").lstrip().upper()
    issues = []
    if rationale.startswith("[CLAIM 오류]"):
        issues.append("claim_error")
    if rationale.startswith("[EVIDENCE 오류]"):
        issues.append("evidence_error")
    if row.get("needs_adjudication") is True and "claim_error" not in issues:
        issues.append("unresolved_adjudication")
    return issues


def build_issue_ledger(
    reviewed_rows: list[dict[str, Any]], sampling_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sampling_by_item = {row["item_id"]: row for row in sampling_rows}
    if len(sampling_by_item) != len(sampling_rows):
        raise RuntimeError("Duplicate item_id in sampling ledger")
    issues = []
    for row in reviewed_rows:
        issue_types = classify_review_issues(row)
        if not issue_types:
            continue
        primary_item_id = row["adjudication_of_item_id"]
        provenance = sampling_by_item.get(primary_item_id)
        if provenance is None:
            raise RuntimeError(f"Missing sampling provenance: {primary_item_id}")
        actions = []
        if "claim_error" in issue_types:
            actions.append("replace_claim_revision_and_re_review_relationship")
        if "evidence_error" in issue_types:
            actions.append("exclude_from_scoring_and_rebuild_after_parser_fix")
        if "unresolved_adjudication" in issue_types:
            actions.append("human_resolution_required")
        identity = {
            "adjudication_item_id": row["item_id"],
            "primary_item_id": primary_item_id,
            "issue_types": issue_types,
            "review_rationale": row["review_rationale"],
        }
        issues.append(
            {
                "issue_schema_version": ISSUE_SCHEMA_VERSION,
                "issue_id": f"entailment_issue_sha256_{_sha256_bytes(_canonical_json_bytes(identity))}",
                "adjudication_item_id": row["item_id"],
                "primary_item_id": primary_item_id,
                "dev_id": provenance["dev_id"],
                "sampling_stratum": provenance["stratum"],
                "evidence_chunk_id": row["evidence_chunk_id"],
                "question": row["question"],
                "original_claim_text": row["claim_text"],
                "adjudicated_label": row["review_label"],
                "issue_types": issue_types,
                "human_rationale": row["review_rationale"],
                "required_actions": actions,
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return sorted(issues, key=lambda row: row["issue_id"])


def _proposed_claim(rows: list[dict[str, Any]]) -> tuple[str, str]:
    questions = {row["question"] for row in rows}
    if len(questions) != 1:
        raise RuntimeError("Claim repair group has multiple questions")
    question = questions.pop()
    if question == "일렁이는 군도 보스 맵 배경에서 무엇이 제거됐어?":
        marker = "일렁이는 군도 던전의 보스 맵 배경에서"
        candidates = []
        for row in rows:
            for line in row["evidence_text"].splitlines():
                if marker in line:
                    candidates.append(line[line.index(marker) :].strip())
        if len(set(candidates)) != 1:
            raise RuntimeError("Cannot derive one island claim correction from evidence")
        return candidates[0], "exact_question_scoped_evidence_line"
    if question == "외부 결제 요구 주의사항은 뭐야?":
        excerpts = {
            _normalize_space(row["decisive_excerpt"])
            for row in rows
            if isinstance(row.get("decisive_excerpt"), str)
            and row["decisive_excerpt"].strip()
        }
        if len(excerpts) != 1:
            raise RuntimeError("Payment claim correction requires the human decisive excerpt")
        return excerpts.pop(), "human_selected_decisive_excerpt_with_named_contacts"
    raise RuntimeError(f"No deterministic claim repair rule for: {question}")


def build_claim_corrections(
    reviewed_rows: list[dict[str, Any]], issue_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    reviewed_by_id = {row["item_id"]: row for row in reviewed_rows}
    claim_issues = [row for row in issue_rows if "claim_error" in row["issue_types"]]
    by_dev: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in claim_issues:
        by_dev[issue["dev_id"]].append(issue)
    corrections = []
    for dev_id, issues in sorted(by_dev.items()):
        source_rows = [reviewed_by_id[row["adjudication_item_id"]] for row in issues]
        originals = {row["claim_text"] for row in source_rows}
        questions = {row["question"] for row in source_rows}
        if len(originals) != 1 or len(questions) != 1:
            raise RuntimeError(f"Claim repair group disagrees for {dev_id}")
        proposed_claim, derivation = _proposed_claim(source_rows)
        original_claim = originals.pop()
        if proposed_claim == original_claim:
            raise RuntimeError(f"Claim repair did not change the claim: {dev_id}")
        identity = {
            "dev_id": dev_id,
            "original_claim_text": original_claim,
            "proposed_claim_text": proposed_claim,
        }
        corrections.append(
            {
                "claim_correction_schema_version": CORRECTION_SCHEMA_VERSION,
                "claim_correction_id": f"claim_correction_sha256_{_sha256_bytes(_canonical_json_bytes(identity))}",
                "dev_id": dev_id,
                "question": questions.pop(),
                "original_claim_text": original_claim,
                "proposed_claim_text": proposed_claim,
                "derivation": derivation,
                "source_issue_ids": sorted(row["issue_id"] for row in issues),
                "source_relationship_count": len(issues),
                "status": "human_review_required",
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
        )
    return corrections


def build_claim_repair_packet(
    reviewed_rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reviewed_by_id = {row["item_id"]: row for row in reviewed_rows}
    correction_by_dev = {row["dev_id"]: row for row in corrections}
    claim_issues = sorted(
        (row for row in issue_rows if "claim_error" in row["issue_types"]),
        key=lambda row: (row["dev_id"], row["adjudication_item_id"]),
    )
    packet = []
    for ordinal, issue in enumerate(claim_issues, 1):
        source = reviewed_by_id[issue["adjudication_item_id"]]
        correction = correction_by_dev[issue["dev_id"]]
        row = copy.deepcopy(source)
        identity = {
            "repair_of_adjudication_item_id": source["item_id"],
            "claim_correction_id": correction["claim_correction_id"],
            "evidence_chunk_id": source["evidence_chunk_id"],
        }
        row.update(
            {
                "review_item_schema_version": REPAIR_PACKET_SCHEMA_VERSION,
                "item_id": f"entailment_claim_repair_sha256_{_sha256_bytes(_canonical_json_bytes(identity))}",
                "item_ordinal": ordinal,
                "claim_text": correction["proposed_claim_text"],
                "repair_of_adjudication_item_id": source["item_id"],
                "repair_of_primary_item_id": source["adjudication_of_item_id"],
                "claim_repair": {
                    "claim_correction_id": correction["claim_correction_id"],
                    "original_claim_text": correction["original_claim_text"],
                    "proposed_claim_text": correction["proposed_claim_text"],
                    "derivation": correction["derivation"],
                    "prior_adjudicated_label": source["review_label"],
                    "prior_human_rationale": source["review_rationale"],
                },
            }
        )
        for field in REVIEW_FIELDS:
            row[field] = None
        packet.append(row)
    return packet


def freeze_adjudication_and_claim_repair(
    root: Path,
    packet_path: Path,
    draft_path: Path,
    sampling_ledger_path: Path,
    finalizer_source_path: Path,
    review_app_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    packet_rows = read_jsonl(packet_path)
    reviewed_rows = read_jsonl(draft_path)
    validate_draft_structure(packet_rows, reviewed_rows)
    audit = audit_adjudication_reviews(packet_rows, reviewed_rows)
    text_corruption = [
        {"item_id": row["item_id"], "fields": review_text_corruption_fields(row)}
        for row in reviewed_rows
        if review_text_corruption_fields(row)
    ]
    human_complete = (
        audit["gates"]["row_count_matches_packet"]
        and audit["gates"]["validation_errors_0"]
        and audit["gates"]["all_rows_reviewed"]
        and not text_corruption
    )
    if not human_complete:
        raise RuntimeError(
            f"Adjudication human review is incomplete: audit={audit}, corruption={text_corruption}"
        )

    sampling_rows = read_jsonl(sampling_ledger_path)
    issue_rows = build_issue_ledger(reviewed_rows, sampling_rows)
    corrections = build_claim_corrections(reviewed_rows, issue_rows)
    repair_rows = build_claim_repair_packet(reviewed_rows, issue_rows, corrections)
    if not repair_rows:
        raise RuntimeError("Expected at least one claim repair relationship")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    reviewed_bytes = _serialize_jsonl(reviewed_rows, lambda row: row["item_ordinal"])
    reviewed_sha = _sha256_bytes(reviewed_bytes)
    reviewed_path = evaluation_dir / f"entailment_natural_adjudication_reviews_{reviewed_sha}.jsonl"
    write_immutable(reviewed_path, reviewed_bytes)

    issue_bytes = _serialize_jsonl(issue_rows, lambda row: row["issue_id"])
    issue_sha = _sha256_bytes(issue_bytes)
    issue_path = evaluation_dir / f"entailment_natural_review_issues_{issue_sha}.jsonl"
    write_immutable(issue_path, issue_bytes)

    correction_bytes = _serialize_jsonl(
        corrections, lambda row: row["claim_correction_id"]
    )
    correction_sha = _sha256_bytes(correction_bytes)
    correction_path = evaluation_dir / f"entailment_claim_corrections_{correction_sha}.jsonl"
    write_immutable(correction_path, correction_bytes)

    repair_bytes = _serialize_jsonl(repair_rows, lambda row: row["item_ordinal"])
    repair_sha = _sha256_bytes(repair_bytes)
    repair_path = evaluation_dir / f"entailment_claim_repair_packet_{repair_sha}.jsonl"
    write_immutable(repair_path, repair_bytes)
    repair_draft_path = (
        root
        / "outputs/v3/annotation"
        / f"entailment_claim_repair_draft_{repair_sha}.jsonl"
    )

    issue_counts = Counter(
        issue_type for row in issue_rows for issue_type in row["issue_types"]
    )
    inputs = {
        "adjudication_packet": packet_path,
        "adjudication_draft": draft_path,
        "sampling_ledger": sampling_ledger_path,
        "finalizer_source": finalizer_source_path,
        "review_app_source": review_app_source_path,
        "claim_repair_contract": contract_path,
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": file_sha256(path)}
            for name, path in inputs.items()
        },
        "adjudication_reviews": {
            "path": _relative(root, reviewed_path),
            "sha256": reviewed_sha,
            "row_count": len(reviewed_rows),
            "label_counts": audit["label_counts"],
            "human_review_complete": human_complete,
        },
        "issue_ledger": {
            "path": _relative(root, issue_path),
            "sha256": issue_sha,
            "row_count": len(issue_rows),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "claim_corrections": {
            "path": _relative(root, correction_path),
            "sha256": correction_sha,
            "row_count": len(corrections),
            "status": "human_review_required",
        },
        "claim_repair_packet": {
            "path": _relative(root, repair_path),
            "sha256": repair_sha,
            "row_count": len(repair_rows),
            "draft_path": _relative(root, repair_draft_path),
        },
        "decisions": {
            "adjudication_human_review": "GO",
            "merge_into_primary_40": "NO-GO",
            "claim_repair_review": "PENDING",
            "evidence_parser_repair": "REQUIRED",
            "contradiction_supplement": "DEFERRED",
            "natural_verifier_evaluation": "NO-GO",
            "generator_entry": "NO-GO",
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "sampling_ledger_opened_only_after_primary_review": True,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"entailment_adjudication_final_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    next_command = (
        "python src/v3/review_entailment_app.py "
        f"--packet {_relative(root, repair_path)} "
        f"--draft {_relative(root, repair_draft_path)}"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "finalizer_version": FINALIZER_VERSION,
        "decisions": manifest["decisions"],
        "adjudication_reviews_sha256": reviewed_sha,
        "adjudication_label_counts": audit["label_counts"],
        "issue_ledger_sha256": issue_sha,
        "issue_counts": dict(sorted(issue_counts.items())),
        "unique_claim_correction_count": len(corrections),
        "claim_repair_relationship_count": len(repair_rows),
        "claim_repair_packet_sha256": repair_sha,
        "manifest_sha256": manifest_sha,
        "next_command": next_command,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_adjudication_final_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Entailment Adjudication Finalization

## Decision

- 15-row human adjudication: **GO**
- Merge into the primary 40 rows: **NO-GO**
- Claim repair review: **PENDING**
- Evidence parser repair: **REQUIRED**
- Natural Verifier / Generator: **NO-GO**

## Human labels

- support: {audit['label_counts'].get('support', 0)}
- contradiction: {audit['label_counts'].get('contradiction', 0)}
- insufficient: {audit['label_counts'].get('insufficient', 0)}

The human review identified {issue_counts['claim_error']} claim-error relationships across {len(corrections)} unique claims and {issue_counts['evidence_error']} evidence-provenance errors. The original rows remain immutable. Corrected claim revisions must be reviewed on the same {len(repair_rows)} relationships before merge. Evidence-error rows remain excluded until parser/chunk provenance is rebuilt.

Run:

`{next_command}`
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_adjudication_final_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    return {
        "adjudication_reviews_path": str(reviewed_path),
        "adjudication_reviews_sha256": reviewed_sha,
        "issue_ledger_path": str(issue_path),
        "issue_ledger_sha256": issue_sha,
        "claim_corrections_path": str(correction_path),
        "claim_corrections_sha256": correction_sha,
        "claim_repair_packet_path": str(repair_path),
        "claim_repair_packet_sha256": repair_sha,
        "claim_repair_draft_path": str(repair_draft_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decisions": manifest["decisions"],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Freeze completed v3 adjudication and prepare claim repair review"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--packet", type=Path, default=root / DEFAULT_PACKET)
    parser.add_argument("--draft", type=Path, default=root / DEFAULT_DRAFT)
    parser.add_argument(
        "--sampling-ledger", type=Path, default=root / DEFAULT_SAMPLING_LEDGER
    )
    parser.add_argument(
        "--finalizer-source", type=Path, default=root / DEFAULT_FINALIZER_SOURCE
    )
    parser.add_argument(
        "--review-app-source", type=Path, default=root / DEFAULT_REVIEW_APP_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = freeze_adjudication_and_claim_repair(
        args.root.resolve(),
        args.packet.resolve(),
        args.draft.resolve(),
        args.sampling_ledger.resolve(),
        args.finalizer_source.resolve(),
        args.review_app_source.resolve(),
        args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
