from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import write_jsonl
from src.v3.product_evidence_pack import (
    _product_header_metadata_kind_is_filtered,
    _product_header_metadata_spans,
)
from src.v3.retrieve_v3 import load_runtime_artifacts


DEFAULT_OUTPUT = Path(
    "reports/v3/product_header_metadata_saved_output_scan_20260805.jsonl"
)
RUNNER_VERSION = "product-header-metadata-saved-output-scan-v1"


def _jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                row["_line_number"] = line_number
                yield row


def _payload(row: dict[str, Any]) -> dict[str, Any] | None:
    result = row.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(row.get("claims"), list) and isinstance(
        row.get("evidence_pack"), list
    ):
        return row
    return None


def _header_kind(
    citation: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    question: str,
) -> str | None:
    chunk = chunks_by_id.get(str(citation.get("chunk_id") or ""))
    if chunk is None:
        return None
    start = int(citation.get("start_char", -1))
    end = int(citation.get("end_char", -1))
    for span_start, span_end, kind in _product_header_metadata_spans(chunk):
        if (
            start >= span_start
            and end <= span_end
            and _product_header_metadata_kind_is_filtered(kind, question)
        ):
            return kind
    return None


def _header_refs(
    payload: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    question: str,
) -> dict[str, dict[str, Any]]:
    result = {}
    for unit in payload.get("evidence_pack") or []:
        kind = _header_kind(
            unit,
            chunks_by_id=chunks_by_id,
            question=question,
        )
        if kind:
            result[str(unit.get("evidence_ref") or unit.get("ref"))] = {
                "header_kind": kind,
                "chunk_id": unit.get("chunk_id"),
                "start_char": unit.get("start_char"),
                "end_char": unit.get("end_char"),
                "text": unit.get("text") or "",
            }
    return result


def _claim_header_citations(
    claim: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
    question: str,
) -> list[dict[str, Any]]:
    found = []
    for citation in claim.get("citations") or []:
        kind = _header_kind(
            citation,
            chunks_by_id=chunks_by_id,
            question=question,
        )
        if kind:
            found.append({**citation, "header_kind": kind})
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan saved Product outputs for header evidence use"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"scan output already exists: {output}")
    artifacts = load_runtime_artifacts(root)
    paths = sorted(
        {
            *root.glob("reports/v3/**/*.jsonl"),
            *root.glob("outputs/v3/**/*.jsonl"),
        }
    )
    rows = []
    scanned_cases = 0
    for path in paths:
        if path.resolve() == output.resolve():
            continue
        for source_row in _jsonl_rows(path):
            payload = _payload(source_row)
            if payload is None:
                continue
            scanned_cases += 1
            question = str(
                payload.get("question") or source_row.get("question") or ""
            )
            header_refs = _header_refs(
                payload,
                chunks_by_id=artifacts.chunks_by_id,
                question=question,
            )
            exposed = []
            for claim in payload.get("claims") or []:
                citations = _claim_header_citations(
                    claim,
                    chunks_by_id=artifacts.chunks_by_id,
                    question=question,
                )
                cited_refs = [
                    str(ref) for ref in claim.get("evidence_refs") or []
                ]
                referenced_header = [
                    {"evidence_ref": ref, **header_refs[ref]}
                    for ref in cited_refs
                    if ref in header_refs
                ]
                if citations or referenced_header:
                    exposed.append(
                        {
                            "claim_text": claim.get("text") or "",
                            "evidence_refs": cited_refs,
                            "header_citations": citations,
                            "referenced_header_units": referenced_header,
                        }
                    )
            rejected = []
            for claim in payload.get("rejected_claims") or []:
                citations = _claim_header_citations(
                    claim,
                    chunks_by_id=artifacts.chunks_by_id,
                    question=question,
                )
                cited_refs = [
                    str(ref) for ref in claim.get("evidence_refs") or []
                ]
                referenced_header = [
                    {"evidence_ref": ref, **header_refs[ref]}
                    for ref in cited_refs
                    if ref in header_refs
                ]
                if citations or referenced_header:
                    rejected.append(
                        {
                            "claim_text": claim.get("text") or "",
                            "evidence_refs": cited_refs,
                            "header_citations": citations,
                            "referenced_header_units": referenced_header,
                        }
                    )
            if not header_refs and not exposed and not rejected:
                continue
            rows.append(
                {
                    "type": "case",
                    "source_path": path.relative_to(root).as_posix(),
                    "source_line": source_row["_line_number"],
                    "slot": source_row.get("slot_ordinal", source_row.get("slot")),
                    "question": question,
                    "rendered_answer": payload.get("rendered_answer") or "",
                    "header_units_in_pack": list(header_refs.values()),
                    "exposed_claims_using_header": exposed,
                    "rejected_claims_using_header": rejected,
                    "answer_would_change": bool(exposed),
                }
            )
    unique_questions = sorted(
        {row["question"] for row in rows if row["question"]}
    )
    changed_questions = sorted(
        {
            row["question"]
            for row in rows
            if row["question"] and row["answer_would_change"]
        }
    )
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "qwen_calls": 0,
        "files_scanned": len(paths),
        "answer_cases_scanned": scanned_cases,
        "header_evidence_records": len(rows),
        "header_evidence_unique_questions": len(unique_questions),
        "answer_change_records": sum(row["answer_would_change"] for row in rows),
        "answer_change_unique_questions": len(changed_questions),
        "unique_questions": unique_questions,
        "changed_questions": changed_questions,
        "human_effect_review_required": bool(changed_questions),
    }
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
