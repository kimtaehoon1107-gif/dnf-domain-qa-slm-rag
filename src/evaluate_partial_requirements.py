from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from evaluate_generated_answer_quality import answer_text
from io_utils import read_jsonl


NORMALIZED_TEXT_PATTERN = re.compile(r"[^0-9a-z가-힣]+")
ABSTENTION_HINTS = (
    "알 수 없",
    "확인할 수 없",
    "확정할 수 없",
    "판단할 수 없",
    "정할 수 없",
    "결정할 수 없",
    "추천할 수 없",
    "근거가 없",
    "정보가 없",
    "모르기 때문",
    "모르므로",
    "몰라",
)


def normalize_match_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = text.replace("月", "월").replace("日", "일")
    return NORMALIZED_TEXT_PATTERN.sub("", text)


def phrase_present(answer: str, phrase: str) -> bool:
    normalized_phrase = normalize_match_text(phrase)
    return bool(normalized_phrase and normalized_phrase in normalize_match_text(answer))


def fact_group_matches(answer: str, alternatives: list[str]) -> bool:
    return any(phrase_present(answer, alternative) for alternative in alternatives)


def abstention_detected(answer: str) -> bool:
    return any(phrase_present(answer, hint) for hint in ABSTENTION_HINTS)


def validate_annotations(
    eval_rows: list[dict[str, Any]], annotations: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    eval_ids = {str(row.get("eval_id")) for row in eval_rows}
    by_id: dict[str, dict[str, Any]] = {}
    for annotation in annotations:
        eval_id = str(annotation.get("eval_id") or "")
        if not eval_id or eval_id in by_id:
            raise ValueError(f"Missing or duplicate requirement annotation eval_id: {eval_id}")
        if eval_id not in eval_ids:
            raise ValueError(f"Requirement annotation is not in eval set: {eval_id}")
        requirements = annotation.get("requirements") or []
        grounded = [item for item in requirements if item.get("type") == "grounded"]
        unsupported = [item for item in requirements if item.get("type") == "unsupported"]
        if not grounded or not unsupported:
            raise ValueError(f"Partial row requires grounded and unsupported slots: {eval_id}")
        requirement_ids = [str(item.get("requirement_id") or "") for item in requirements]
        if any(not item for item in requirement_ids) or len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError(f"Missing or duplicate requirement_id: {eval_id}")
        for item in grounded:
            groups = item.get("required_fact_groups") or []
            if not groups or any(not isinstance(group, list) or not group for group in groups):
                raise ValueError(f"Grounded slot has no fact groups: {item.get('requirement_id')}")
            if not item.get("expected_chunk_ids"):
                raise ValueError(f"Grounded slot has no citation target: {item.get('requirement_id')}")
        for item in unsupported:
            if not item.get("target_phrases"):
                raise ValueError(f"Unsupported slot has no target phrases: {item.get('requirement_id')}")
        by_id[eval_id] = annotation
    missing = sorted(eval_ids - set(by_id))
    if missing:
        raise ValueError(f"Eval rows missing requirement annotations: {missing[:5]}")
    return by_id


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate(
    report: dict[str, Any],
    eval_rows: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    annotations_by_id = validate_annotations(eval_rows, annotations)
    details = report.get("details") or []
    report_by_id = {str(row.get("eval_id")): row for row in details}
    missing_report_rows = sorted(set(annotations_by_id) - set(report_by_id))
    if missing_report_rows:
        raise ValueError(f"Model report is missing eval rows: {missing_report_rows[:5]}")

    grounded_total = grounded_answered = grounded_cited = grounded_over_refused = 0
    unsupported_total = unsupported_abstained = unsupported_over_answered = unsupported_omitted = 0
    row_joint = 0
    scored_rows = []

    for eval_row in eval_rows:
        eval_id = str(eval_row["eval_id"])
        annotation = annotations_by_id[eval_id]
        detail = report_by_id[eval_id]
        answer = answer_text(detail)
        predicted_label = str(detail.get("parsed_answerability") or "").lower()
        predicted_citations = {str(item) for item in detail.get("parsed_citations", []) if item}
        refusal = abstention_detected(answer)
        grounded_results = []
        unsupported_results = []

        for requirement in annotation["requirements"]:
            requirement_type = requirement["type"]
            if requirement_type == "grounded":
                grounded_total += 1
                group_matches = [
                    fact_group_matches(answer, alternatives)
                    for alternatives in requirement["required_fact_groups"]
                ]
                answered = all(group_matches)
                expected_citations = {
                    str(item) for item in requirement.get("expected_chunk_ids", []) if item
                }
                citation_hit = bool(predicted_citations & expected_citations)
                over_refused = bool(refusal and not answered)
                grounded_answered += int(answered)
                grounded_cited += int(answered and citation_hit)
                grounded_over_refused += int(over_refused)
                grounded_results.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "description": requirement.get("description", ""),
                        "fact_group_matches": group_matches,
                        "answered": answered,
                        "citation_hit": citation_hit,
                        "success": bool(answered and citation_hit),
                        "over_refused": over_refused,
                    }
                )
            elif requirement_type == "unsupported":
                unsupported_total += 1
                topic_mentioned = any(
                    phrase_present(answer, phrase)
                    for phrase in requirement.get("target_phrases", [])
                )
                abstained = bool(topic_mentioned and refusal)
                over_answered = bool(topic_mentioned and not refusal)
                omitted = not topic_mentioned
                unsupported_abstained += int(abstained)
                unsupported_over_answered += int(over_answered)
                unsupported_omitted += int(omitted)
                unsupported_results.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "description": requirement.get("description", ""),
                        "topic_mentioned": topic_mentioned,
                        "abstained": abstained,
                        "over_answered": over_answered,
                        "omitted": omitted,
                        "success": abstained,
                    }
                )

        all_grounded_answered = all(item["answered"] for item in grounded_results)
        citations_complete = all(item["citation_hit"] for item in grounded_results)
        all_unsupported_abstained = all(item["abstained"] for item in unsupported_results)
        joint = bool(
            predicted_label == "partial"
            and all_grounded_answered
            and citations_complete
            and all_unsupported_abstained
        )
        row_joint += int(joint)
        failure_types = []
        if not detail.get("retrieval_expected_hit"):
            failure_types.append("retrieval_miss")
        if predicted_label != "partial":
            failure_types.append("answerability_not_partial")
        if not all_grounded_answered:
            failure_types.append("grounded_slot_missing")
        if not citations_complete:
            failure_types.append("citation_missing")
        if any(item["over_refused"] for item in grounded_results):
            failure_types.append("grounded_over_refusal")
        if any(item["over_answered"] for item in unsupported_results):
            failure_types.append("unsupported_over_answer")
        if any(item["omitted"] for item in unsupported_results):
            failure_types.append("unsupported_omitted")
        scored_rows.append(
            {
                "eval_id": eval_id,
                "predicted_answerability": predicted_label,
                "retrieval_expected_hit": detail.get("retrieval_expected_hit"),
                "refusal_detected": refusal,
                "predicted_citations": sorted(predicted_citations),
                "grounded_requirements": grounded_results,
                "unsupported_requirements": unsupported_results,
                "all_grounded_answered": all_grounded_answered,
                "grounded_citations_complete": citations_complete,
                "all_unsupported_abstained": all_unsupported_abstained,
                "partial_requirement_joint_success": joint,
                "failure_types": failure_types,
            }
        )

    row_total = len(scored_rows)
    return {
        "report_schema_version": 1,
        "source_adapter": report.get("adapter_dir"),
        "source_eval_set": report.get("eval_set"),
        "rows": row_total,
        "definitions": {
            "grounded_slot_answered": "Every required fact group has at least one normalized phrase match.",
            "unsupported_slot_abstained": "The answer mentions the unsupported request topic and contains an abstention expression.",
            "grounded_slot_over_refused": "An abstention is present while the grounded slot is not answered.",
            "unsupported_slot_over_answered": "The unsupported topic is mentioned without an abstention expression.",
            "partial_requirement_joint_success": "Predicted partial + all grounded slots answered and cited + all unsupported slots explicitly abstained.",
        },
        "summary": {
            "grounded_slots": grounded_total,
            "grounded_slot_answer_rate": safe_ratio(grounded_answered, grounded_total),
            "grounded_slot_answer_and_citation_rate": safe_ratio(grounded_cited, grounded_total),
            "grounded_slot_over_refusal_rate": safe_ratio(grounded_over_refused, grounded_total),
            "unsupported_slots": unsupported_total,
            "unsupported_slot_abstention_rate": safe_ratio(
                unsupported_abstained, unsupported_total
            ),
            "unsupported_slot_over_answer_rate": safe_ratio(
                unsupported_over_answered, unsupported_total
            ),
            "unsupported_slot_omission_rate": safe_ratio(unsupported_omitted, unsupported_total),
            "partial_requirement_joint_success_rate": safe_ratio(row_joint, row_total),
        },
        "counts": {
            "grounded_slots_answered": grounded_answered,
            "grounded_slots_answered_and_cited": grounded_cited,
            "grounded_slots_over_refused": grounded_over_refused,
            "unsupported_slots_abstained": unsupported_abstained,
            "unsupported_slots_over_answered": unsupported_over_answered,
            "unsupported_slots_omitted": unsupported_omitted,
            "partial_requirement_joint_success": row_joint,
        },
        "details": scored_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Partial responses by requirement slot.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate(
        json.loads(args.report.read_text(encoding="utf-8")),
        read_jsonl(args.eval_set),
        read_jsonl(args.annotations),
    )
    result["source_report"] = str(args.report)
    result["source_annotations"] = str(args.annotations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
