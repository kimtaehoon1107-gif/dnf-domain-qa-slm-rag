from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from prompt_format import evidence_span_visible


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
GENERIC_ANSWER_HINTS = (
    "수집된 공식 문서만으로는 해당 질문에 답하기에 충분한 근거가 없습니다.",
    "공식 문서를 근거로 답해야 합니다",
)


def normalize_space(text: Any) -> str:
    return " ".join(str(text or "").split())


def token_set(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) >= 2}


def title_overlap_ratio(question: str, title: str) -> float:
    title_tokens = token_set(title)
    if not title_tokens:
        return 0.0
    return len(token_set(question) & title_tokens) / len(title_tokens)


def parent_id(doc: dict[str, Any]) -> str:
    return str(doc.get("parent_doc_id") or doc["doc_id"])


def expected_chunk_ids(row: dict[str, Any]) -> list[str]:
    chunk_ids = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    if row.get("expected_chunk_id"):
        chunk_ids = [str(row["expected_chunk_id"])]
    return chunk_ids


def expected_parent_ids(row: dict[str, Any]) -> set[str]:
    parents = set()
    if row.get("expected_doc_id"):
        parents.add(str(row["expected_doc_id"]))
    for item in row.get("expected_evidence_doc_ids", []) or []:
        if item:
            parents.add(str(item))
    return parents


def is_generic_answer(answer: str) -> bool:
    return any(hint in answer for hint in GENERIC_ANSWER_HINTS)


def validate_qa_rows(
    rows: list[dict[str, Any]],
    id_field: str,
    chunks_by_id: dict[str, dict[str, Any]],
    title_overlap_cap: float,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for row in rows:
        row_id = str(row.get(id_field, row.get("eval_id", row.get("qa_id", "<missing-id>"))))
        answerability = str(row.get("answerability", "true")).lower()
        chunk_ids = expected_chunk_ids(row)

        if answerability == "false":
            if chunk_ids or row.get("expected_evidence_doc_ids"):
                errors.append(f"{row_id}: false row must not have expected evidence IDs")
            if row.get("citations"):
                errors.append(f"{row_id}: false row must not have citations")
            continue

        if not chunk_ids:
            errors.append(f"{row_id}: answerable/partial row has no expected_chunk_ids")
            continue

        missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in chunks_by_id]
        if missing:
            errors.append(f"{row_id}: missing expected chunks {missing}")
            continue

        span = normalize_space(row.get("evidence_span", ""))
        if not span:
            errors.append(f"{row_id}: answerable/partial row has empty evidence_span")
        elif not any(span in normalize_space(chunks_by_id[chunk_id].get("text", "")) for chunk_id in chunk_ids):
            errors.append(f"{row_id}: evidence_span not found in expected chunks")

        answer = normalize_space(row.get("gold_answer") or row.get("expected_answer") or "")
        if not answer or is_generic_answer(answer):
            errors.append(f"{row_id}: answerable/partial row has generic or empty answer")
        elif len(answer) > 200:
            warnings.append(f"{row_id}: gold answer has {len(answer)} chars > 200")

        max_overlap = max(
            title_overlap_ratio(row.get("question", ""), chunks_by_id[chunk_id].get("title", ""))
            for chunk_id in chunk_ids
        )
        if max_overlap > title_overlap_cap:
            warnings.append(f"{row_id}: title overlap {max_overlap:.4f} > {title_overlap_cap:.4f}")
    return errors, warnings


def validate_raft(
    raft_rows: list[dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    eval_chunks: set[str],
    eval_parents: set[str],
    max_doc_chars: int,
) -> tuple[list[str], list[str], dict[str, int | float | None]]:
    errors: list[str] = []
    warnings: list[str] = []
    visibility_total = 0
    visibility_hits = 0
    for row in raft_rows:
        row_id = str(row.get("raft_id", "<missing-raft-id>"))
        answerability = str(row.get("answerability", "true")).lower()
        documents = row.get("documents", []) or []
        document_ids = [str(doc.get("doc_id")) for doc in documents if doc.get("doc_id")]
        citations = [str(item) for item in row.get("citations", []) or [] if item]

        missing_docs = [doc_id for doc_id in document_ids if doc_id not in chunks_by_id]
        if missing_docs:
            errors.append(f"{row_id}: missing context documents {missing_docs}")
        missing_citations = [doc_id for doc_id in citations if doc_id not in chunks_by_id]
        if missing_citations:
            errors.append(f"{row_id}: missing citations {missing_citations}")

        if set(document_ids) & eval_chunks:
            errors.append(f"{row_id}: context includes held-out eval chunk")
        if set(citations) & eval_chunks:
            errors.append(f"{row_id}: citation includes held-out eval chunk")
        doc_parents = {parent_id(chunks_by_id[doc_id]) for doc_id in document_ids if doc_id in chunks_by_id}
        if doc_parents & eval_parents:
            errors.append(f"{row_id}: context includes held-out eval parent")

        if answerability == "false":
            if citations:
                errors.append(f"{row_id}: false row has citations")
            if any(str(doc.get("role")) == "gold" for doc in documents):
                errors.append(f"{row_id}: false row has gold evidence")
        else:
            if not str(row.get("source_qa_id") or "").strip():
                errors.append(f"{row_id}: answerable/partial row has no source_qa_id")
            if not citations:
                errors.append(f"{row_id}: answerable/partial row has no citation")
            if not any(str(doc.get("role")) == "gold" for doc in documents):
                warnings.append(f"{row_id}: answerable/partial row has no gold context role")
            span = normalize_space(row.get("evidence_span", ""))
            if not span:
                errors.append(f"{row_id}: answerable/partial RAFT row has no evidence_span")
            else:
                visibility_total += 1
                gold_documents = [doc for doc in documents if str(doc.get("doc_id")) in citations]
                visible = evidence_span_visible(
                    question=str(row.get("question", "")),
                    documents=gold_documents,
                    evidence_span=span,
                    max_doc_chars=max_doc_chars,
                )
                visibility_hits += int(visible)
                if not visible:
                    errors.append(f"{row_id}: gold evidence is not visible in the {max_doc_chars}-char prompt window")
    return errors, warnings, {
        "rows": visibility_total,
        "visible_rows": visibility_hits,
        "visible_rate": visibility_hits / visibility_total if visibility_total else None,
        "max_doc_chars": max_doc_chars,
    }


def gold_position_balance(raft_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[int] = Counter()
    rows_with_gold_position = 0
    rows_without_gold_position = 0
    for row in raft_rows:
        if str(row.get("answerability", "true")).lower() == "false":
            continue
        document_ids = [
            str(doc.get("doc_id")) for doc in row.get("documents", []) or [] if doc.get("doc_id")
        ]
        citations = [str(item) for item in row.get("citations", []) or [] if item]
        positions = [document_ids.index(citation) + 1 for citation in citations if citation in document_ids]
        if positions:
            rows_with_gold_position += 1
            counts.update(positions)
        else:
            rows_without_gold_position += 1
    total = sum(counts.values())
    max_share = max(counts.values(), default=0) / total if total else None
    return {
        "rows_with_gold_position": rows_with_gold_position,
        "rows_without_gold_position": rows_without_gold_position,
        "total_gold_positions": total,
        "position_counts": {str(position): count for position, count in sorted(counts.items())},
        "max_position_share": max_share,
    }


def duplicate_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = Counter(normalize_space(row.get(key, "")).lower() for row in rows if row.get(key))
    return {value: count for value, count in counter.items() if count > 1}


def cross_duplicate_questions(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> set[str]:
    """Questions appearing verbatim in both lists (e.g. eval vs train) — this is
    leakage even when the rows have no expected chunk/parent (as with template
    -generated false/refusal rows), which the parent/chunk overlap checks below
    cannot see."""
    left_questions = {normalize_space(row.get("question", "")).lower() for row in left if row.get("question")}
    right_questions = {normalize_space(row.get("question", "")).lower() for row in right if row.get("question")}
    return left_questions & right_questions


def extra_eval_ids(paths: list[Path]) -> tuple[set[str], set[str], list[str], list[dict[str, Any]]]:
    chunks: set[str] = set()
    parents: set[str] = set()
    loaded_paths: list[str] = []
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        loaded_paths.append(str(path))
        path_rows = read_jsonl(path)
        rows.extend(path_rows)
        for row in path_rows:
            chunks.update(expected_chunk_ids(row))
            parents.update(expected_parent_ids(row))
    return chunks, parents, loaded_paths, rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate expanded DNF domain eval/train/RAFT data.")
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl"))
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/domain_eval_set_expanded.jsonl"))
    parser.add_argument("--train-qa", type=Path, default=Path("data/processed/domain_train_qa_expanded.jsonl"))
    parser.add_argument("--raft", type=Path, default=Path("data/processed/domain_raft_sample_expanded.jsonl"))
    parser.add_argument("--title-overlap-cap", type=float, default=0.35)
    parser.add_argument("--max-doc-chars", type=int, default=900)
    parser.add_argument(
        "--max-gold-position-share",
        type=float,
        default=0.5,
        help="Fail when one context position contains more than this share of RAFT gold citations.",
    )
    parser.add_argument(
        "--legacy-eval-set",
        type=Path,
        nargs="*",
        default=[
            Path("data/processed/official_eval_set.jsonl"),
            Path("data/processed/fresh_paraphrase_eval_set.jsonl"),
            Path("data/review/blind_test_v1_candidate.jsonl"),
            Path("data/eval/blind_test_v1.jsonl"),
        ],
        help="Additional held-out eval set(s) that domain train/RAFT must not overlap with.",
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/domain_dataset_validation_report.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks = read_jsonl(args.chunks)
    eval_rows = read_jsonl(args.eval_set)
    train_rows = read_jsonl(args.train_qa)
    raft_rows = read_jsonl(args.raft) if args.raft.exists() else []

    chunks_by_id = {str(chunk["doc_id"]): chunk for chunk in chunks}
    eval_chunks = {chunk_id for row in eval_rows for chunk_id in expected_chunk_ids(row)}
    train_chunks = {chunk_id for row in train_rows for chunk_id in expected_chunk_ids(row)}
    eval_parents = {parent for row in eval_rows for parent in expected_parent_ids(row)}
    train_parents = {parent for row in train_rows for parent in expected_parent_ids(row)}

    errors: list[str] = []
    warnings: list[str] = []
    eval_errors, eval_warnings = validate_qa_rows(eval_rows, "eval_id", chunks_by_id, args.title_overlap_cap)
    train_errors, train_warnings = validate_qa_rows(train_rows, "qa_id", chunks_by_id, args.title_overlap_cap)
    errors.extend(eval_errors)
    errors.extend(train_errors)
    warnings.extend(eval_warnings)
    warnings.extend(train_warnings)

    parent_overlap = eval_parents & train_parents
    chunk_overlap = eval_chunks & train_chunks
    if parent_overlap:
        errors.append(f"train/eval parent overlap: {sorted(parent_overlap)[:10]}")
    if chunk_overlap:
        errors.append(f"train/eval chunk overlap: {sorted(chunk_overlap)[:10]}")

    # Catches leakage that parent/chunk overlap cannot see, e.g. template
    # -generated false/refusal rows that have no expected chunk or parent at all.
    question_overlap = cross_duplicate_questions(eval_rows, train_rows)
    if question_overlap:
        errors.append(f"train/eval verbatim question overlap: {len(question_overlap)} questions")

    legacy_chunks, legacy_parents, loaded_legacy_eval_sets, legacy_rows = extra_eval_ids(args.legacy_eval_set)
    legacy_train_overlap = train_parents & legacy_parents
    if legacy_train_overlap:
        errors.append(
            f"domain train overlaps extra eval set parents ({loaded_legacy_eval_sets}): "
            f"{sorted(legacy_train_overlap)[:10]}"
        )

    legacy_train_question_overlap = cross_duplicate_questions(legacy_rows, train_rows)
    if legacy_train_question_overlap:
        errors.append(
            f"domain train overlaps extra eval set questions ({loaded_legacy_eval_sets}): "
            f"{len(legacy_train_question_overlap)} questions"
        )

    raft_visibility = {"rows": 0, "visible_rows": 0, "visible_rate": None, "max_doc_chars": args.max_doc_chars}
    raft_gold_positions = gold_position_balance(raft_rows)
    if raft_rows:
        raft_errors, raft_warnings, raft_visibility = validate_raft(
            raft_rows,
            chunks_by_id,
            eval_chunks | legacy_chunks,
            eval_parents | legacy_parents,
            args.max_doc_chars,
        )
        errors.extend(raft_errors)
        warnings.extend(raft_warnings)
        max_gold_share = raft_gold_positions["max_position_share"]
        if max_gold_share is not None and max_gold_share > args.max_gold_position_share:
            errors.append(
                "RAFT gold position imbalance: "
                f"max share {max_gold_share:.4f} > {args.max_gold_position_share:.4f}"
            )

    raft_document_ids = {
        str(doc.get("doc_id"))
        for row in raft_rows
        for doc in row.get("documents", []) or []
        if doc.get("doc_id")
    }
    raft_document_parents = {
        parent_id(chunks_by_id[doc_id])
        for doc_id in raft_document_ids
        if doc_id in chunks_by_id
    }
    raft_legacy_chunk_overlap = raft_document_ids & legacy_chunks
    raft_legacy_parent_overlap = raft_document_parents & legacy_parents

    raft_question_overlap = cross_duplicate_questions(eval_rows, raft_rows) if raft_rows else set()
    if raft_question_overlap:
        errors.append(f"RAFT/eval verbatim question overlap: {len(raft_question_overlap)} questions")
    raft_legacy_question_overlap = cross_duplicate_questions(legacy_rows, raft_rows) if raft_rows else set()
    if raft_legacy_question_overlap:
        errors.append(
            f"RAFT overlaps extra eval set questions ({loaded_legacy_eval_sets}): "
            f"{len(raft_legacy_question_overlap)} questions"
        )

    eval_question_dupes = duplicate_values(eval_rows, "question")
    train_question_dupes = duplicate_values(train_rows, "question")
    if eval_question_dupes:
        warnings.append(f"duplicate eval questions: {len(eval_question_dupes)}")
    if train_question_dupes:
        warnings.append(f"duplicate train questions: {len(train_question_dupes)}")

    report = {
        "status": "fail" if errors else "ok",
        "chunks": len(chunks),
        "eval_rows": len(eval_rows),
        "train_rows": len(train_rows),
        "raft_rows": len(raft_rows),
        "eval_answerability_counts": dict(Counter(str(row.get("answerability", "")) for row in eval_rows)),
        "train_answerability_counts": dict(Counter(str(row.get("answerability", "")) for row in train_rows)),
        "raft_answerability_counts": dict(Counter(str(row.get("answerability", "")) for row in raft_rows)),
        "raft_gold_evidence_visibility": raft_visibility,
        "raft_gold_position_balance": raft_gold_positions,
        "eval_expected_chunks": len(eval_chunks),
        "train_expected_chunks": len(train_chunks),
        "train_eval_parent_overlap": len(parent_overlap),
        "train_eval_chunk_overlap": len(chunk_overlap),
        "train_eval_question_overlap": len(question_overlap),
        "raft_eval_question_overlap": len(raft_question_overlap),
        "legacy_eval_set": loaded_legacy_eval_sets[0] if loaded_legacy_eval_sets else "",
        "legacy_eval_sets": loaded_legacy_eval_sets,
        "legacy_eval_rows": len(legacy_rows),
        "legacy_eval_chunks": len(legacy_chunks),
        "legacy_eval_parents": len(legacy_parents),
        "domain_train_legacy_eval_parent_overlap": len(legacy_train_overlap),
        "domain_train_legacy_eval_question_overlap": len(legacy_train_question_overlap),
        "raft_context_legacy_eval_chunk_overlap": len(raft_legacy_chunk_overlap),
        "raft_context_legacy_eval_parent_overlap": len(raft_legacy_parent_overlap),
        "raft_legacy_eval_question_overlap": len(raft_legacy_question_overlap),
        "errors": errors,
        "warnings": warnings[:100],
        "warning_count": len(warnings),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise RuntimeError(f"Dataset validation failed with {len(errors)} errors.")


if __name__ == "__main__":
    main()
