from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def safe_div(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def min_gold_rank(row: dict[str, Any]) -> int | None:
    expected = [str(item) for item in row.get("expected_chunk_ids", []) if item]
    retrieved = [str(item) for item in row.get("retrieved_chunk_ids", []) if item]
    ranks = [retrieved.index(chunk_id) + 1 for chunk_id in expected if chunk_id in retrieved]
    return min(ranks) if ranks else None


def citation_ranks(row: dict[str, Any]) -> list[int]:
    retrieved = [str(item) for item in row.get("retrieved_chunk_ids", []) if item]
    ranks = []
    for citation in row.get("parsed_citations", []) or []:
        citation = str(citation)
        if citation in retrieved:
            ranks.append(retrieved.index(citation) + 1)
    return ranks


def expected_chunk_set(row: dict[str, Any]) -> set[str]:
    return {str(item) for item in row.get("expected_chunk_ids", []) if item}


def parsed_citation_set(row: dict[str, Any]) -> set[str]:
    return {str(item) for item in row.get("parsed_citations", []) or [] if item}


def citation_precision(row: dict[str, Any]) -> float:
    predicted = parsed_citation_set(row)
    if not predicted:
        return 0.0
    return len(expected_chunk_set(row) & predicted) / len(predicted)


def citation_recall(row: dict[str, Any]) -> float:
    expected = expected_chunk_set(row)
    if not expected:
        return 0.0
    return len(expected & parsed_citation_set(row)) / len(expected)


def summarize_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    details = data.get("details", [])
    answerable = [row for row in details if row.get("expected_chunk_ids") or row.get("expected_evidence_doc_ids")]
    false_rows = [row for row in details if row.get("expected_answerability") == "false"]

    answerability_correct = [
        row for row in details if row.get("parsed_answerability") == row.get("expected_answerability")
    ]
    exact_citation = [row for row in answerable if row.get("parsed_citation_hit")]
    label_and_exact_citation = [
        row
        for row in answerable
        if row.get("parsed_answerability") == row.get("expected_answerability") and row.get("parsed_citation_hit")
    ]
    any_citation = [row for row in answerable if row.get("parsed_citations")]
    wrong_citation = [row for row in any_citation if not row.get("parsed_citation_hit")]
    chunk_citation_rows = [row for row in answerable if expected_chunk_set(row)]
    exact_set_match_rows = [
        row for row in chunk_citation_rows if parsed_citation_set(row) == expected_chunk_set(row)
    ]
    strict_precision_sum = sum(citation_precision(row) for row in chunk_citation_rows)
    strict_recall_sum = sum(citation_recall(row) for row in chunk_citation_rows)
    false_no_citation = [row for row in false_rows if not row.get("parsed_citations")]
    retrieved_answerable = [row for row in answerable if row.get("retrieval_expected_hit")]
    over_refused_retrieved = [
        row
        for row in retrieved_answerable
        if row.get("expected_answerability") in {"true", "partial"} and row.get("parsed_answerability") == "false"
    ]

    by_gold_rank: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "exact_citation": 0, "answerability_correct": 0})
    for row in answerable:
        rank = min_gold_rank(row)
        bucket = f"rank_{rank}" if rank is not None else "missing"
        by_gold_rank[bucket]["total"] += 1
        if row.get("parsed_citation_hit"):
            by_gold_rank[bucket]["exact_citation"] += 1
        if row.get("parsed_answerability") == row.get("expected_answerability"):
            by_gold_rank[bucket]["answerability_correct"] += 1

    citation_rank_counter = Counter()
    for row in any_citation:
        ranks = citation_ranks(row)
        citation_rank_counter.update(f"rank_{rank}" for rank in ranks)
        if not ranks:
            citation_rank_counter["not_retrieved"] += 1

    examples = {
        "wrong_citation": [
            {
                "eval_id": row.get("eval_id"),
                "question": row.get("question"),
                "expected_chunk_ids": row.get("expected_chunk_ids"),
                "parsed_citations": row.get("parsed_citations"),
                "retrieved_chunk_ids": row.get("retrieved_chunk_ids"),
            }
            for row in wrong_citation[:5]
        ],
        "over_refused_retrieved": [
            {
                "eval_id": row.get("eval_id"),
                "question": row.get("question"),
                "expected_answerability": row.get("expected_answerability"),
                "expected_chunk_ids": row.get("expected_chunk_ids"),
                "retrieved_chunk_ids": row.get("retrieved_chunk_ids"),
            }
            for row in over_refused_retrieved[:5]
        ],
    }

    return {
        "source": str(path),
        "rows": len(details),
        "answerable_or_partial_rows": len(answerable),
        "false_rows": len(false_rows),
        "answerability_accuracy": safe_div(len(answerability_correct), len(details)),
        "exact_citation_on_answerable": safe_div(len(exact_citation), len(answerable)),
        "answerability_and_exact_citation_on_answerable": safe_div(len(label_and_exact_citation), len(answerable)),
        "citation_metric_rows": len(chunk_citation_rows),
        "citation_precision_macro": safe_div(strict_precision_sum, len(chunk_citation_rows)),
        "citation_recall_macro": safe_div(strict_recall_sum, len(chunk_citation_rows)),
        "citation_exact_set_match": safe_div(len(exact_set_match_rows), len(chunk_citation_rows)),
        "wrong_citation_given_any_citation": safe_div(len(wrong_citation), len(any_citation)),
        "false_no_citation_rate": safe_div(len(false_no_citation), len(false_rows)),
        "over_refusal_when_gold_retrieved": safe_div(len(over_refused_retrieved), len(retrieved_answerable)),
        "retrieved_answerable_rows": len(retrieved_answerable),
        "by_gold_rank": dict(by_gold_rank),
        "predicted_citation_rank_counts": dict(citation_rank_counter),
        "examples": examples,
    }


def parse_report_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Expected LABEL=PATH")
    label, path = value.split("=", 1)
    return label, Path(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze tuned-SLM failure modes from saved eval reports.")
    parser.add_argument("--report", action="append", type=parse_report_arg, required=True, help="LABEL=report.json")
    parser.add_argument("--output", type=Path, default=Path("outputs/tuned_slm_diagnostic_report.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summaries = {label: summarize_report(path) for label, path in args.report}
    report = {"reports": summaries}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
