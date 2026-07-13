from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from make_raft_dataset import evidence_token_recall, load_human_blocklist, normalize_space, parent_id


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(
    docs: list[dict[str, Any]],
    raft_rows: list[dict[str, Any]],
    human_blocklist: dict[str, set[str]],
    threshold: float,
) -> dict[str, Any]:
    docs_by_id = {str(doc["doc_id"]): doc for doc in docs}
    distractor_count = 0
    exact_span_occurrences = 0
    high_overlap_occurrences = 0
    human_blocked_occurrences = 0
    same_parent_occurrences = 0
    max_overlap = 0.0
    missing_docs: list[str] = []

    for row in raft_rows:
        source_qa_id = str(row.get("source_qa_id") or "")
        evidence_span = normalize_space(row.get("evidence_span"))
        expected_parent = str(row.get("expected_doc_id") or "")
        blocked = human_blocklist.get(source_qa_id, set())
        for context_doc in row.get("documents", []):
            if str(context_doc.get("role") or "") != "distractor":
                continue
            distractor_count += 1
            doc_id = str(context_doc.get("doc_id") or "")
            source_doc = docs_by_id.get(doc_id)
            if source_doc is None:
                missing_docs.append(doc_id)
                continue
            text = normalize_space(source_doc.get("text"))
            overlap = evidence_token_recall(text, evidence_span)
            max_overlap = max(max_overlap, overlap)
            if evidence_span and evidence_span in text:
                exact_span_occurrences += 1
            if evidence_span and overlap >= threshold:
                high_overlap_occurrences += 1
            if doc_id in blocked:
                human_blocked_occurrences += 1
            if expected_parent and parent_id(source_doc) == expected_parent:
                same_parent_occurrences += 1

    errors = []
    checks = {
        "missing_docs": len(set(missing_docs)),
        "exact_span_occurrences": exact_span_occurrences,
        "high_overlap_occurrences": high_overlap_occurrences,
        "human_blocked_occurrences": human_blocked_occurrences,
        "same_parent_occurrences": same_parent_occurrences,
    }
    for name, count in checks.items():
        if count:
            errors.append(f"{name}={count}")
    return {
        "status": "ok" if not errors else "error",
        "raft_rows": len(raft_rows),
        "distractor_count": distractor_count,
        "max_evidence_token_recall": max_overlap,
        "threshold": threshold,
        **checks,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit RAFT distractors for answer-like contamination.")
    parser.add_argument("--docs", type=Path, required=True)
    parser.add_argument("--raft", type=Path, required=True)
    parser.add_argument("--human-review", type=Path, default=None)
    parser.add_argument("--max-evidence-token-recall", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = audit(
        docs=read_jsonl(args.docs),
        raft_rows=read_jsonl(args.raft),
        human_blocklist=load_human_blocklist(args.human_review),
        threshold=args.max_evidence_token_recall,
    )
    report.update(
        {
            "docs": str(args.docs),
            "raft": str(args.raft),
            "raft_sha256": file_sha256(args.raft),
            "human_review": str(args.human_review) if args.human_review else None,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
