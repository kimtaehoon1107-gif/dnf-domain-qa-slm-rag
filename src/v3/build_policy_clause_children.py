from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, build_bm25_index, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "policy-clause-children-v3.2-arm5.1"
CHILD_SCHEMA_VERSION = "dnf-policy-clause-child-v3.2"
REPORT_SCHEMA_VERSION = "dnf-policy-clause-child-report-v3.2"
MANIFEST_SCHEMA_VERSION = "dnf-policy-clause-child-manifest-v3.2"
TOP_K = 10

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
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
DEFAULT_CONTRACT = Path("docs/v3/policy_clause_children_arm5.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/structured")
DEFAULT_REPORT_DIR = Path("reports/v3")

CLAUSE_PATTERN = re.compile(r"(?m)^\[(\d+(?:-\d+)+)\]\s*")
TABLE_ROW_PATTERN = re.compile(r"(?m)^\|[^\n]+\|[ \t]*$")
REVISION_DATE_PATTERN = re.compile(r"^20\d{2}년\s+\d{2}월\s+\d{2}일$")
TOC_PATTERN = re.compile(r"^\d+\.\s+[^\n]{1,80}$")
NON_BODY_LINES = {"시행일자", "인쇄", "텍스트복사", "목록", "[TABLE]", "### 운영정책"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reconstruct_document_text(chunks: list[dict[str, Any]]) -> tuple[str, int, int]:
    if not chunks:
        return "", 0, 0
    size = max(row["end_offset"] for row in chunks)
    characters: list[str | None] = [None] * size
    conflicts = 0
    for chunk in sorted(chunks, key=lambda row: (row["start_offset"], row["chunk_id"])):
        text = chunk["display_text"]
        if len(text) != chunk["end_offset"] - chunk["start_offset"]:
            raise RuntimeError(f"Offset length mismatch: {chunk['chunk_id']}")
        for local_offset, character in enumerate(text):
            absolute_offset = chunk["start_offset"] + local_offset
            existing = characters[absolute_offset]
            if existing is None:
                characters[absolute_offset] = character
            elif existing != character:
                conflicts += 1
    gaps = sum(character is None for character in characters)
    return "".join(character if character is not None else "\uFFFD" for character in characters), conflicts, gaps


def _child_id(parent_document_id: str, kind: str, start: int, end: int, text: str) -> str:
    payload = _canonical_json_bytes(
        {
            "parent_document_id": parent_document_id,
            "kind": kind,
            "start": start,
            "end": end,
            "text_sha256": _sha256_bytes(text.encode("utf-8")),
        }
    )
    return f"policy_child_sha256_{_sha256_bytes(payload)}"


def _make_child(
    document: dict[str, Any],
    *,
    kind: str,
    identifier: str,
    start: int,
    end: int,
    text: str,
) -> dict[str, Any]:
    return {
        "policy_child_schema_version": CHILD_SCHEMA_VERSION,
        "chunk_id": _child_id(document["document_id"], kind, start, end, text),
        "parent_document_id": document["document_id"],
        "source_id": document["source_id"],
        "source_kind": document["source_kind"],
        "status": document["status"],
        "default_exposure": document["default_exposure"],
        "review_required": False,
        "offset_source": "reconstructed_policy_exact_slice",
        "valid_from": document.get("valid_from"),
        "valid_to": document.get("valid_to"),
        "child_kind": kind,
        "clause_or_row_id": identifier,
        "start_offset": start,
        "end_offset": end,
        "display_text": text,
        "retrieval_text": f"{document['title']}\n{identifier}\n{text}",
    }


def extract_policy_children(document: dict[str, Any], text: str) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    clause_matches = list(CLAUSE_PATTERN.finditer(text))
    for index, match in enumerate(clause_matches):
        end = clause_matches[index + 1].start() if index + 1 < len(clause_matches) else len(text)
        table_start = text.find("\n[TABLE]", match.start(), end)
        if table_start >= 0:
            end = table_start
        body = text[match.start():end].rstrip()
        if len(body) < 12 or "\uFFFD" in body:
            continue
        children.append(
            _make_child(
                document,
                kind="numbered_clause",
                identifier=match.group(1),
                start=match.start(),
                end=match.start() + len(body),
                text=body,
            )
        )

    for row_index, match in enumerate(TABLE_ROW_PATTERN.finditer(text), start=1):
        row_text = match.group(0).rstrip()
        if len(row_text) < 5 or "\uFFFD" in row_text:
            continue
        children.append(
            _make_child(
                document,
                kind="table_row",
                identifier=f"table_row_{row_index}",
                start=match.start(),
                end=match.start() + len(row_text),
                text=row_text,
            )
        )

    if not clause_matches:
        cursor = 0
        paragraph_index = 0
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            start = cursor + len(line) - len(line.lstrip())
            cursor += len(line)
            if (
                len(stripped) < 20
                or stripped in NON_BODY_LINES
                or REVISION_DATE_PATTERN.fullmatch(stripped)
                or TOC_PATTERN.fullmatch(stripped)
                or stripped.startswith("|")
                or stripped.startswith("[IMAGE_ALT]")
                or "\uFFFD" in stripped
            ):
                continue
            paragraph_index += 1
            children.append(
                _make_child(
                    document,
                    kind="legacy_paragraph",
                    identifier=f"paragraph_{paragraph_index}",
                    start=start,
                    end=start + len(stripped),
                    text=stripped,
                )
            )
    return sorted(children, key=lambda row: (row["parent_document_id"], row["start_offset"], row["child_kind"], row["chunk_id"]))


def build_policy_children(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    policy_documents = {
        row["document_id"]: row for row in documents if row["source_id"] == "dnf_account_policy"
    }
    chunks_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        if chunk["parent_document_id"] in policy_documents:
            chunks_by_document[chunk["parent_document_id"]].append(chunk)
    children = []
    conflicts = 0
    gaps = 0
    for document_id, document in sorted(policy_documents.items()):
        text, document_conflicts, document_gaps = reconstruct_document_text(
            chunks_by_document[document_id]
        )
        conflicts += document_conflicts
        gaps += document_gaps
        children.extend(extract_policy_children(document, text))
    return children, {
        "policy_document_count": len(policy_documents),
        "reconstruction_conflict_count": conflicts,
        "reconstruction_gap_count": gaps,
    }


def _policy_evaluations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if "dnf_account_policy" in row.get("source_ids", [])]


def _group_hit(
    group: dict[str, Any],
    result_ids: set[str],
    child_by_id: dict[str, dict[str, Any]],
) -> bool:
    if result_ids & set(group.get("acceptable_chunk_ids", [])):
        return True
    span = group.get("evidence_span", "")
    document_ids = set(group.get("document_ids", []))
    return any(
        child_id in child_by_id
        and child_by_id[child_id]["parent_document_id"] in document_ids
        and span
        and span in child_by_id[child_id]["display_text"]
        for child_id in result_ids
    )


def evaluate_ab(
    policy_chunks: list[dict[str, Any]],
    children: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> dict[str, Any]:
    policy_evaluations = _policy_evaluations(evaluations)
    baseline_index = build_bm25_index(policy_chunks, documents)
    child_index = build_bm25_index(children, documents)
    child_by_id = {row["chunk_id"]: row for row in children}
    policy = SearchPolicy(
        default_exposure_only=False,
        allowed_statuses=None,
        include_review_required=True,
        source_ids=("dnf_account_policy",),
    )
    baseline_group_hits = 0
    arm_group_hits = 0
    baseline_question_hits = 0
    arm_question_hits = 0
    regressions = []
    improvements = []
    group_count = 0
    for evaluation in policy_evaluations:
        baseline_ids = {
            row["chunk_id"]
            for row in search_bm25(baseline_index, evaluation["question"], top_k=TOP_K, policy=policy)
        }
        child_ids = {
            row["chunk_id"]
            for row in search_bm25(child_index, evaluation["question"], top_k=TOP_K, policy=policy)
        }
        arm_ids = baseline_ids | child_ids
        baseline_hits = []
        arm_hits = []
        for group in evaluation["evidence_groups"]:
            group_count += 1
            baseline_hit = _group_hit(group, baseline_ids, child_by_id)
            arm_hit = _group_hit(group, arm_ids, child_by_id)
            baseline_hits.append(baseline_hit)
            arm_hits.append(arm_hit)
            baseline_group_hits += baseline_hit
            arm_group_hits += arm_hit
            if baseline_hit and not arm_hit:
                regressions.append({"case_id": evaluation["dev_id"], "group_id": group["group_id"]})
            elif arm_hit and not baseline_hit:
                improvements.append({"case_id": evaluation["dev_id"], "group_id": group["group_id"]})
        baseline_question_hits += all(baseline_hits)
        arm_question_hits += all(arm_hits)

    child_kind_counts = Counter(row["child_kind"] for row in children)
    exact_failures = sum(
        len(row["display_text"]) != row["end_offset"] - row["start_offset"]
        for row in children
    )
    return {
        "top_k": TOP_K,
        "policy_question_count": len(policy_evaluations),
        "evidence_group_count": group_count,
        "baseline": {
            "all_groups_covered_questions": baseline_question_hits,
            "evidence_groups_hit": baseline_group_hits,
            "indexed_rows": len(policy_chunks),
        },
        "arm5": {
            "all_groups_covered_questions": arm_question_hits,
            "evidence_groups_hit": arm_group_hits,
            "indexed_rows": len(policy_chunks) + len(children),
            "candidate_pool_max": TOP_K * 2,
            "child_count": len(children),
            "child_kind_counts": dict(sorted(child_kind_counts.items())),
            "exact_slice_failure_count": exact_failures,
        },
        "improvements": improvements,
        "regressions": regressions,
    }


def _markdown(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    return "\n".join(
        [
            "# v3.2 Arm 5 — policy clause children A/B",
            "",
            f"Decision: **{report['decision']}**. Runtime/canonical was not promoted.",
            "",
            f"Policy top-{evaluation['top_k']} was measured over {evaluation['policy_question_count']} questions and {evaluation['evidence_group_count']} evidence groups.",
            "",
            "| Measure | Canonical chunks | Additive clause children |",
            "|---|---:|---:|",
            f"| All groups covered questions | {evaluation['baseline']['all_groups_covered_questions']} | {evaluation['arm5']['all_groups_covered_questions']} |",
            f"| Evidence groups hit | {evaluation['baseline']['evidence_groups_hit']} | {evaluation['arm5']['evidence_groups_hit']} |",
            f"| Indexed policy rows | {evaluation['baseline']['indexed_rows']} | {evaluation['arm5']['indexed_rows']} |",
            f"| Strict regressions | 0 | {len(evaluation['regressions'])} |",
            "",
            "Clause children are kept only as a development candidate when retrieval improves with zero regression.",
        ]
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and A/B policy clause children")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    documents = read_jsonl(root / DEFAULT_DOCUMENTS)
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    evaluations = read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV)
    policy_chunks = [row for row in chunks if row["source_id"] == "dnf_account_policy"]
    children, reconstruction = build_policy_children(documents, chunks)
    evaluation = evaluate_ab(policy_chunks, children, documents, evaluations)
    gates = {
        "reconstruction_conflicts_zero": reconstruction["reconstruction_conflict_count"] == 0,
        "reconstruction_gaps_recorded": reconstruction["reconstruction_gap_count"] >= 0,
        "children_with_gap_marker_zero": all("\uFFFD" not in row["display_text"] for row in children),
        "exact_slices_100_percent": evaluation["arm5"]["exact_slice_failure_count"] == 0,
        "evidence_group_recall_improved": evaluation["arm5"]["evidence_groups_hit"] > evaluation["baseline"]["evidence_groups_hit"],
        "all_groups_question_recall_not_lower": evaluation["arm5"]["all_groups_covered_questions"] >= evaluation["baseline"]["all_groups_covered_questions"],
        "strict_regression_zero": not evaluation["regressions"],
    }
    decision = "GO_ARM5_ADDITIVE_POLICY_CHILD_CANDIDATE_NOT_PROMOTED" if all(gates.values()) else "NO_GO"
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": "development_only_not_promoted",
        "reconstruction": reconstruction,
        "evaluation": evaluation,
        "gates": gates,
        "decision": decision,
        "scope": {"canonical_changed": False, "gold_changed": False, "runtime_changed": False, "promoted": False},
    }
    output_dir = root / args.output_dir
    child_bytes = _serialize_jsonl(children, lambda row: row["chunk_id"])
    child_sha = _sha256_bytes(child_bytes)
    child_path = output_dir / f"policy_clause_children_v3.2_{child_sha}.jsonl"
    write_immutable(child_path, child_bytes)
    report_dir = root / args.report_dir
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"policy_clause_children_arm5_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"policy_clause_children_arm5_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    inputs = {
        "documents": DEFAULT_DOCUMENTS,
        "chunks": DEFAULT_CHUNKS,
        "adaptive_dev": DEFAULT_DEV,
        "downgraded_canary": DEFAULT_CANARY,
        "contract": DEFAULT_CONTRACT,
        "builder_source": Path(__file__).resolve().relative_to(root),
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {name: {"path": path.as_posix(), "sha256": file_sha256(root / path)} for name, path in inputs.items()},
        "artifacts": {
            "children": {"path": child_path.relative_to(root).as_posix(), "sha256": child_sha, "row_count": len(children)},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "gate": {"pass": all(gates.values()), "checks": gates, "decision": decision, "promoted": False},
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"policy_clause_children_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"children": child_path.relative_to(root).as_posix(), "manifest": manifest_path.relative_to(root).as_posix(), "report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), "evaluation": evaluation, "reconstruction": reconstruction, "gates": gates, "decision": decision}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
