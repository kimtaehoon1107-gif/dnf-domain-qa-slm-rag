from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ANSWERABLE_LABELS = {"true", "partial"}


def force_reranker_top1(report: dict[str, Any]) -> dict[str, Any]:
    output = dict(report)
    details = []
    changed_rows = 0
    cited_rows = 0
    exact_hits = 0
    for source in report.get("details") or []:
        row = dict(source)
        predicted_label = str(row.get("parsed_answerability") or "").lower()
        retrieved = [str(item) for item in row.get("retrieved_chunk_ids") or [] if item]
        forced = [retrieved[0]] if predicted_label in ANSWERABLE_LABELS and retrieved else []
        original = [str(item) for item in row.get("parsed_citations") or [] if item]
        changed_rows += int(forced != original)
        cited_rows += int(bool(forced))
        expected = {str(item) for item in row.get("expected_chunk_ids") or [] if item}
        hit = bool(set(forced) & expected)
        exact_hits += int(hit)
        row["model_parsed_citations"] = original
        row["parsed_citations"] = forced
        row["parsed_citation_hit"] = hit
        row["parsed_citation_in_retrieved"] = bool(set(forced) <= set(retrieved))
        details.append(row)
    output["source_summary"] = report.get("summary")
    output["summary"] = {
        "citation_policy": "predicted true/partial -> reranker top-1; predicted false -> no citation",
        "rows": len(details),
        "changed_rows": changed_rows,
        "cited_rows": cited_rows,
        "exact_citation_hits": exact_hits,
    }
    output["citation_policy"] = "reranker_top1_by_predicted_answerability"
    output["details"] = details
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a deterministic citation-selection policy.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    output = force_reranker_top1(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
