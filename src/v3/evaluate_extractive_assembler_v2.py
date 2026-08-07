from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from kiwipiepy import Kiwi, __version__ as kiwipiepy_version
from pydantic import BaseModel, ConfigDict

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_extractive_assembler import (
    DEFAULT_CANARY,
    DEFAULT_CANARY_BASELINE_CASES,
    DEFAULT_CANARY_BASELINE_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_DEV_BASELINE_CASES,
    DEFAULT_DEV_BASELINE_MANIFEST,
    DEFAULT_ENUMERATION,
    DEFAULT_RERANK_MANIFEST,
    DEFAULT_RERANK_RESULTS,
    DEFAULT_RERANK_SCORES,
    _git_head,
    _relative,
    _sha256_bytes,
    build_cases,
)
from src.v3.evaluate_semantic_requirement_planner import call_structured, runtime_metadata


EVALUATOR_VERSION = "extractive-answer-assembler-segment-selection-v3.2"
SEGMENT_SCHEMA_VERSION = "extractive-segment-candidates-v3.2"
SELECTION_SCHEMA_VERSION = "extractive-segment-selection-v3.2"
CASE_SCHEMA_VERSION = "extractive-segment-assembled-case-v3.2"
REPORT_SCHEMA_VERSION = "extractive-segment-assembler-report-v3.2"
MANIFEST_SCHEMA_VERSION = "extractive-segment-assembler-manifest-v3.2"
DEFAULT_MODEL = "qwen3:8b"

DEFAULT_V1_PROPOSALS = Path(
    "data/v3/evidence/extractive_assembler_proposals_"
    "177b45ea9555b86afd08082b7a0a5ffbe72260f55ad35e10c03e33e7e3eac5db.jsonl"
)
DEFAULT_V1_CASES = Path(
    "data/v3/evidence/extractive_assembler_cases_"
    "c9b9ed0875aeebbe99302b6e72db2d057e7fad3afb8dee1d77a514ffbea5ec27.jsonl"
)
DEFAULT_V1_DIAGNOSTICS = Path(
    "data/v3/evidence/extractive_assembler_diagnostics_"
    "81e9c1d1f9d9ce6fd6fae57da07d9abd80c907ce58681be7c8f80c7ae7b116c8.jsonl"
)
DEFAULT_V1_REPORT = Path(
    "reports/v3/extractive_assembler_pilot_"
    "68be43f979b3d8e37dc7125a6f80d5e88dc357038eac9c3e2f9acf3a8d87e219.json"
)
DEFAULT_CONTRACT = Path("docs/v3/extractive_answer_assembler_v2_pilot.md")

SEGMENTATION_SPEC = """segment-selection-v3.2
paragraph: trim exact regions separated by one or more blank lines
sentence: kiwipiepy split_into_sents on each non-table non-empty physical line
table_row: trim each physical line containing at least two pipe delimiters
deduplication: merge identical chunk_id/start_char/end_char boundaries
span_id: sha256(chunk_id NUL start NUL end NUL exact_text), first 24 hex
"""

SEGMENT_SELECTOR_PROMPT = """You are an extractive evidence segment selector.
You receive one atomic requirement and exact candidate segments from the frozen
selected evidence. Select the smallest set of span_id values that directly
answers that requirement. Select multiple span IDs only when the answer truly
crosses segments. Never write, copy, paraphrase, or explain answer text.

Return status=supported with one or more provided span IDs, or
status=unsupported with an empty list when none of the supplied segments answers
the requirement. Never invent an ID and never repeat an ID. This unsupported
decision concerns only the supplied evidence, not personal/realtime
answerability. Return structured JSON only."""


class SegmentChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "unsupported"]
    selected_span_ids: list[str]


_DEFAULT_KIWI: Kiwi | None = None


def _default_kiwi() -> Kiwi:
    global _DEFAULT_KIWI
    if _DEFAULT_KIWI is None:
        _DEFAULT_KIWI = Kiwi()
    return _DEFAULT_KIWI


def _prompt_sha256() -> str:
    return _sha256_bytes(SEGMENT_SELECTOR_PROMPT.encode("utf-8"))


def _segmentation_sha256() -> str:
    return _sha256_bytes(SEGMENTATION_SPEC.encode("utf-8"))


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _physical_lines(text: str) -> list[tuple[int, int]]:
    output = []
    for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", text):
        if match.start() == match.end():
            continue
        start, end = match.start(), match.end()
        while end > start and text[end - 1] in "\r\n":
            end -= 1
        start, end = _trim(text, start, end)
        if start < end:
            output.append((start, end))
    return output


def _paragraphs(text: str) -> list[tuple[int, int]]:
    output = []
    start = 0
    for match in re.finditer(r"(?:\r?\n[ \t]*){2,}", text):
        left, right = _trim(text, start, match.start())
        if left < right:
            output.append((left, right))
        start = match.end()
    left, right = _trim(text, start, len(text))
    if left < right:
        output.append((left, right))
    return output


def segment_chunk(
    chunk_id: str, text: str, *, kiwi: Kiwi | None = None
) -> list[dict[str, Any]]:
    kiwi = kiwi or _default_kiwi()
    boundaries: dict[tuple[int, int], set[str]] = {}

    def add(kind: str, start: int, end: int) -> None:
        start, end = _trim(text, start, end)
        if start < end:
            boundaries.setdefault((start, end), set()).add(kind)

    for start, end in _paragraphs(text):
        add("paragraph", start, end)
    for start, end in _physical_lines(text):
        line = text[start:end]
        if line.count("|") >= 2:
            add("table_row", start, end)
            continue
        for sentence in kiwi.split_into_sents(line):
            add("sentence", start + sentence.start, start + sentence.end)

    output = []
    seen_ids: dict[str, tuple[int, int]] = {}
    for (start, end), kinds in sorted(boundaries.items()):
        exact = text[start:end]
        digest = hashlib.sha256(
            f"{chunk_id}\0{start}\0{end}\0{exact}".encode("utf-8")
        ).hexdigest()[:24]
        span_id = f"span_{digest}"
        if span_id in seen_ids and seen_ids[span_id] != (start, end):
            raise RuntimeError(f"Segment ID collision: {span_id}")
        seen_ids[span_id] = (start, end)
        output.append(
            {
                "span_id": span_id,
                "chunk_id": chunk_id,
                "start_char": start,
                "end_char": end,
                "text": exact,
                "kinds": sorted(kinds),
            }
        )
    if text.strip() and not output:
        raise RuntimeError(f"Non-empty chunk produced no segments: {chunk_id}")
    return output


def build_segment_rows(
    cases: list[dict[str, Any]], *, kiwi: Kiwi | None = None
) -> list[dict[str, Any]]:
    kiwi = kiwi or _default_kiwi()
    output = []
    for case in cases:
        segments = []
        for chunk_id in case["selected_chunk_ids"]:
            segments.extend(
                segment_chunk(chunk_id, case["selected_chunks"][chunk_id], kiwi=kiwi)
            )
        if len({row["span_id"] for row in segments}) != len(segments):
            raise RuntimeError(f"Duplicate segment ID in case: {case['case_id']}")
        output.append(
            {
                "segment_schema_version": SEGMENT_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "segments": segments,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _without_ws(value: str) -> str:
    return re.sub(r"\s+", "", value)


def classify_non_substring(case: dict[str, Any], decision: dict[str, Any]) -> str:
    proposed = decision.get("proposed_span") or ""
    cited_chunk = decision.get("cited_chunk_id")
    cited_text = case["selected_chunks"].get(cited_chunk, "")
    other_texts = [
        text
        for chunk_id, text in case["selected_chunks"].items()
        if chunk_id != cited_chunk
    ]
    if any(proposed in text for text in other_texts) or any(
        _normalize_ws(proposed) in _normalize_ws(text)
        for text in other_texts
        if _normalize_ws(proposed)
    ):
        return "wrong_chunk"
    if _normalize_ws(proposed) and _normalize_ws(proposed) in _normalize_ws(cited_text):
        return "whitespace_only"
    compact_proposal = _without_ws(proposed)
    compact_source = _without_ws(cited_text)
    blocks = [
        block
        for block in difflib.SequenceMatcher(
            None, compact_proposal, compact_source, autojunk=False
        ).get_matching_blocks()
        if block.size >= 8
    ]
    coverage = (
        sum(block.size for block in blocks) / len(compact_proposal)
        if compact_proposal
        else 0.0
    )
    if len(blocks) >= 2 and coverage >= 0.85:
        return "multi_segment"
    return "paraphrase"


def diagnose_v1(
    cases: list[dict[str, Any]],
    v1_proposals: list[dict[str, Any]],
    v1_assembled: list[dict[str, Any]],
    v1_diagnostics: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases_by_id = {row["case_id"]: row for row in cases}
    proposals_by_id = {row["case_id"]: row for row in v1_proposals}
    output = []
    categories: Counter[str] = Counter()
    for assembled in v1_assembled:
        case_id = assembled["case_id"]
        case = cases_by_id[case_id]
        proposal = proposals_by_id[case_id]
        for assembled_decision, raw_decision in zip(
            assembled["decisions"], proposal["decisions"], strict=True
        ):
            if assembled_decision["status"] == "invalid_non_substring":
                category = classify_non_substring(case, raw_decision)
                categories[category] += 1
                output.append(
                    {
                        "case_id": case_id,
                        "requirement_id": assembled_decision["requirement_id"],
                        "v1_failure_category": category,
                    }
                )
            elif assembled_decision["status"] == "invalid_model_output":
                output.append(
                    {
                        "case_id": case_id,
                        "requirement_id": assembled_decision["requirement_id"],
                        "v1_failure_category": "malformed_requirement_output",
                    }
                )
    wrong_or_incomplete = [
        row
        for row in v1_diagnostics
        if row.get("extraction_failure_type")
        == "valid_span_wrong_chunk_or_incomplete_groups"
    ]
    partial = 0
    no_group = 0
    for row in wrong_or_incomplete:
        cited = [group for group in row["groups"] if group["assembler_cited"]]
        category = (
            "valid_span_partial_group_coverage"
            if cited
            else "valid_span_no_gold_group_coverage"
        )
        partial += bool(cited)
        no_group += not bool(cited)
        output.append(
            {
                "case_id": row["case_id"],
                "requirement_id": None,
                "v1_failure_category": category,
            }
        )
    non_substring_total = sum(categories.values())
    summary = {
        "non_substring_total": non_substring_total,
        "non_substring_categories": dict(sorted(categories.items())),
        "whitespace_only_recovery": {
            "successes": categories["whitespace_only"],
            "total": non_substring_total,
            "rate": round(categories["whitespace_only"] / non_substring_total, 6)
            if non_substring_total
            else None,
        },
        "malformed_requirement_count": sum(
            row["v1_failure_category"] == "malformed_requirement_output"
            for row in output
        ),
        "valid_span_wrong_or_incomplete_question_count": len(wrong_or_incomplete),
        "valid_span_partial_group_coverage_question_count": partial,
        "valid_span_no_gold_group_coverage_question_count": no_group,
        "design_decision": "segment_id_selection_with_multiple_ids",
    }
    return summary, sorted(
        output,
        key=lambda row: (row["case_id"], row["requirement_id"] or "", row["v1_failure_category"]),
    )


def _segments_for_requirement(
    case: dict[str, Any], segment_row: dict[str, Any], requirement_index: int
) -> list[dict[str, Any]]:
    attribution = next(
        row
        for row in case["requirement_attribution"]
        if row["requirement_index"] == requirement_index
    )
    ordered_chunks = list(attribution["ordered_chunk_ids"])
    ordered_chunks.extend(
        chunk_id
        for chunk_id in case["selected_chunk_ids"]
        if chunk_id not in ordered_chunks
    )
    chunk_order = {chunk_id: index for index, chunk_id in enumerate(ordered_chunks)}
    return sorted(
        segment_row["segments"],
        key=lambda row: (
            chunk_order[row["chunk_id"]],
            row["start_char"],
            row["end_char"],
            row["span_id"],
        ),
    )


def selector_prompt(
    case: dict[str, Any],
    requirement: dict[str, Any],
    requirement_index: int,
    segments: list[dict[str, Any]],
) -> str:
    payload = {
        "question": case["question"],
        "requirement": {
            "requirement_index": requirement_index,
            "subject": requirement["subject"],
            "relation": requirement["relation"],
            "value_type": requirement["value_type"],
            "subject_group": requirement["subject_group"],
        },
        "segments": [
            {
                "id": row["span_id"],
                "kind": row["kinds"],
                "text": row["text"],
            }
            for row in segments
        ],
    }
    return "Select exact evidence segment IDs for this requirement:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def _selection_errors(choice: dict[str, Any], valid_ids: set[str]) -> list[str]:
    ids = choice["selected_span_ids"]
    errors = []
    if choice["status"] == "supported" and not ids:
        errors.append("supported_without_span_id")
    if choice["status"] == "unsupported" and ids:
        errors.append("unsupported_with_span_id")
    if len(ids) != len(set(ids)):
        errors.append("duplicate_span_id")
    if any(span_id not in valid_ids for span_id in ids):
        errors.append("unknown_span_id")
    return errors


def run_segment_selector(
    cases: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    *,
    model: str,
    timeout: float,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    segments_by_id = {row["case_id"]: row for row in segment_rows}
    callable_count = sum(len(case["requirements"]) for case in cases if case["evidence_groups"])
    ordinal = 0
    selections = []
    logs = []
    for case in cases:
        decisions = []
        if not case["evidence_groups"]:
            decisions = [
                {
                    "requirement_index": index,
                    "status": "unsupported",
                    "selected_span_ids": [],
                    "model_output_errors": [],
                    "not_evaluated_no_gold_evidence_groups": True,
                }
                for index in range(1, len(case["requirements"]) + 1)
            ]
        else:
            for index, requirement in enumerate(case["requirements"], 1):
                candidates = _segments_for_requirement(
                    case, segments_by_id[case["case_id"]], index
                )
                started = time.perf_counter()
                try:
                    parsed, log = caller(
                        model=model,
                        system_prompt=SEGMENT_SELECTOR_PROMPT,
                        user_prompt=selector_prompt(
                            case, requirement, index, candidates
                        ),
                        output_type=SegmentChoice,
                        timeout=timeout,
                    )
                except Exception as error:
                    decisions.append(
                        {
                            "requirement_index": index,
                            "status": "unsupported",
                            "selected_span_ids": [],
                            "model_output_errors": [
                                f"model_call_error:{type(error).__name__}"
                            ],
                        }
                    )
                    logs.append(
                        {
                            "case_id": case["case_id"],
                            "requirement_index": index,
                            "latency_ms": round(
                                (time.perf_counter() - started) * 1000, 3
                            ),
                            "model_call_error": type(error).__name__,
                        }
                    )
                    ordinal += 1
                    continue
                raw = parsed.model_dump()
                valid_ids = {row["span_id"] for row in candidates}
                decisions.append(
                    {
                        "requirement_index": index,
                        **raw,
                        "model_output_errors": _selection_errors(raw, valid_ids),
                    }
                )
                logs.append(
                    {
                        "case_id": case["case_id"],
                        "requirement_index": index,
                        **log,
                    }
                )
                ordinal += 1
                if ordinal % 20 == 0 or ordinal == callable_count:
                    print(
                        f"segment requirements {ordinal}/{callable_count}",
                        file=sys.stderr,
                        flush=True,
                    )
        selections.append(
            {
                "selection_schema_version": SELECTION_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "decisions": decisions,
            }
        )
    return sorted(selections, key=lambda row: row["case_id"]), logs


def assemble_segment_selections(
    cases: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    selections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    segments_by_case = {row["case_id"]: row["segments"] for row in segment_rows}
    selections_by_case = {row["case_id"]: row for row in selections}
    output = []
    for case in cases:
        segment_by_id = {
            row["span_id"]: row for row in segments_by_case[case["case_id"]]
        }
        decisions = []
        for requirement, raw in zip(
            case["requirements"],
            selections_by_case[case["case_id"]]["decisions"],
            strict=True,
        ):
            if raw["model_output_errors"]:
                decisions.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "status": "invalid_model_output",
                        "spans": [],
                        "model_output_errors": raw["model_output_errors"],
                        "unsupported_message": "문서에서 확인 불가",
                    }
                )
                continue
            if raw["status"] == "unsupported":
                decisions.append(
                    {
                        "requirement_id": requirement["requirement_id"],
                        "status": "unsupported",
                        "spans": [],
                        "model_output_errors": [],
                        "unsupported_message": "문서에서 확인 불가",
                    }
                )
                continue
            spans = []
            mapping_error = False
            for span_id in raw["selected_span_ids"]:
                segment = segment_by_id[span_id]
                source = case["selected_chunks"][segment["chunk_id"]]
                extracted = source[segment["start_char"] : segment["end_char"]]
                if extracted != segment["text"]:
                    mapping_error = True
                    break
                spans.append(
                    {
                        "span_id": span_id,
                        "chunk_id": segment["chunk_id"],
                        "start_char": segment["start_char"],
                        "end_char": segment["end_char"],
                        "text": extracted,
                    }
                )
            decisions.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "status": "invalid_segment_mapping"
                    if mapping_error
                    else "supported_exact",
                    "spans": [] if mapping_error else spans,
                    "model_output_errors": [],
                    "unsupported_message": "문서에서 확인 불가"
                    if mapping_error
                    else None,
                }
            )
        output.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "decisions": decisions,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def score_cases_v2(
    cases: list[dict[str, Any]], assembled_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    assembled_by_id = {row["case_id"]: row for row in assembled_rows}
    output = []
    for case in cases:
        assembled = assembled_by_id[case["case_id"]]
        valid_decisions = [
            row for row in assembled["decisions"] if row["status"] == "supported_exact"
        ]
        cited_chunk_ids = {
            span["chunk_id"] for row in valid_decisions for span in row["spans"]
        }
        selected_ids = set(case["selected_chunk_ids"])
        retrieval_bound_ids = set(case["retrieval_bound_group_ids"])
        groups = []
        for group in case["evidence_groups"]:
            acceptable = set(group["acceptable_chunk_ids"])
            selected_bound = bool(selected_ids & acceptable)
            groups.append(
                {
                    "group_id": group["group_id"],
                    "retrieval_bound": group["group_id"] in retrieval_bound_ids,
                    "selection_bound": group["group_id"] not in retrieval_bound_ids
                    and not selected_bound,
                    "selected_bound": selected_bound,
                    "baseline_cited": group["group_id"]
                    in case["baseline_cited_group_ids"],
                    "assembler_cited": bool(cited_chunk_ids & acceptable),
                }
            )
        bound_groups = [group for group in groups if group["selected_bound"]]
        gate_eligible = bool(groups) and len(bound_groups) == len(groups)
        acceptable_ids = {
            chunk_id
            for group in case["evidence_groups"]
            for chunk_id in group["acceptable_chunk_ids"]
        }
        valid_gold_requirements = sum(
            any(span["chunk_id"] in acceptable_ids for span in row["spans"])
            for row in valid_decisions
        )
        output.append(
            {
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "source_ids": case["source_ids"],
                "requirement_count": len(case["requirements"]),
                "supported_requirement_count": len(valid_decisions),
                "gold_chunk_requirement_count": valid_gold_requirements,
                "all_planner_requirements_cited": valid_gold_requirements
                == len(case["requirements"]),
                "selected_span_count": sum(len(row["spans"]) for row in valid_decisions),
                "unsupported_requirement_count": sum(
                    row["status"] == "unsupported" for row in assembled["decisions"]
                ),
                "malformed_requirement_count": sum(
                    row["status"] == "invalid_model_output"
                    for row in assembled["decisions"]
                ),
                "invalid_segment_count": sum(
                    row["status"] == "invalid_segment_mapping"
                    for row in assembled["decisions"]
                ),
                "groups": groups,
                "gate_eligible": gate_eligible,
                "all_groups_baseline_cited": all(
                    group["baseline_cited"] for group in groups
                )
                if gate_eligible
                else None,
                "all_groups_assembler_cited": all(
                    group["assembler_cited"] for group in groups
                )
                if gate_eligible
                else None,
            }
        )
    return sorted(output, key=lambda row: row["case_id"])


def aggregate_v2(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_rows = [row for row in rows if row["groups"]]
    eligible_rows = [row for row in evidence_rows if row["gate_eligible"]]
    all_groups = [group for row in evidence_rows for group in row["groups"]]
    bound_groups = [group for group in all_groups if group["selected_bound"]]
    improvements = sum(
        not group["baseline_cited"] and group["assembler_cited"]
        for group in bound_groups
    )
    regressions = sum(
        group["baseline_cited"] and not group["assembler_cited"]
        for group in bound_groups
    )
    question_improvements = sum(
        not row["all_groups_baseline_cited"] and row["all_groups_assembler_cited"]
        for row in eligible_rows
    )
    question_regressions = sum(
        row["all_groups_baseline_cited"] and not row["all_groups_assembler_cited"]
        for row in eligible_rows
    )
    requirement_total = sum(row["requirement_count"] for row in evidence_rows)
    supported_total = sum(row["supported_requirement_count"] for row in evidence_rows)
    gold_total = sum(row["gold_chunk_requirement_count"] for row in evidence_rows)
    span_total = sum(row["selected_span_count"] for row in evidence_rows)
    malformed_total = sum(row["malformed_requirement_count"] for row in evidence_rows)
    invalid_total = sum(row["invalid_segment_count"] for row in evidence_rows)
    return {
        "row_count": len(rows),
        "evidence_bearing_question_count": len(evidence_rows),
        "gate_eligible_question_count": len(eligible_rows),
        "all_human_gold_evidence_group_citation": {
            "baseline_successes": sum(group["baseline_cited"] for group in all_groups),
            "assembler_successes": sum(group["assembler_cited"] for group in all_groups),
            "total": len(all_groups),
        },
        "selected_bound_evidence_group_citation": {
            "baseline_successes": sum(group["baseline_cited"] for group in bound_groups),
            "assembler_successes": sum(group["assembler_cited"] for group in bound_groups),
            "total": len(bound_groups),
        },
        "all_groups_cited_questions": {
            "baseline_successes": sum(
                row["all_groups_baseline_cited"] for row in eligible_rows
            ),
            "assembler_successes": sum(
                row["all_groups_assembler_cited"] for row in eligible_rows
            ),
            "total": len(eligible_rows),
        },
        "per_requirement_segment_coverage": {
            "successes": supported_total,
            "total": requirement_total,
            "rate": round(supported_total / requirement_total, 6)
            if requirement_total
            else None,
        },
        "per_requirement_gold_chunk_citation": {
            "successes": gold_total,
            "total": requirement_total,
            "rate": round(gold_total / requirement_total, 6)
            if requirement_total
            else None,
        },
        "all_planner_requirements_cited_questions": {
            "successes": sum(
                row["all_planner_requirements_cited"] for row in eligible_rows
            ),
            "total": len(eligible_rows),
        },
        "span_validity": {
            "exact_slices": span_total,
            "invalid": invalid_total,
            "rate": round(span_total / (span_total + invalid_total), 6)
            if span_total + invalid_total
            else None,
        },
        "malformed_requirement_count": malformed_total,
        "comparison": {
            "evidence_group_improvement_count": improvements,
            "evidence_group_regression_count": regressions,
            "all_groups_question_improvement_count": question_improvements,
            "all_groups_question_regression_count": question_regressions,
        },
        "failure_boundaries": {
            "retrieval_bound_question_count": sum(
                any(group["retrieval_bound"] for group in row["groups"])
                for row in evidence_rows
            ),
            "retrieval_bound_evidence_group_count": sum(
                group["retrieval_bound"] for group in all_groups
            ),
            "selection_bound_question_count": sum(
                any(group["selection_bound"] for group in row["groups"])
                for row in evidence_rows
            ),
            "selection_bound_evidence_group_count": sum(
                group["selection_bound"] for group in all_groups
            ),
            "segment_misselection_question_count": sum(
                not row["all_groups_assembler_cited"] for row in eligible_rows
            ),
            "segment_misselection_evidence_group_count": sum(
                group["selected_bound"] and not group["assembler_cited"]
                for group in all_groups
            ),
            "unsupported_requirement_count": sum(
                row["unsupported_requirement_count"] for row in evidence_rows
            ),
        },
        "selected_span_count": span_total,
        "mean_spans_per_supported_requirement": round(span_total / supported_total, 6)
        if supported_total
        else None,
    }


def gate_v2(metrics: dict[str, Any]) -> dict[str, Any]:
    combined = metrics["combined"]
    dev = metrics["adaptive_dev_63"]
    checks = {
        "dev_evidence_group_hits_exceed_47_of_59": dev[
            "all_human_gold_evidence_group_citation"
        ]["assembler_successes"]
        > 47,
        "strict_evidence_group_regression_zero": combined["comparison"][
            "evidence_group_regression_count"
        ]
        == 0,
        "strict_question_regression_zero": combined["comparison"][
            "all_groups_question_regression_count"
        ]
        == 0,
        "all_groups_question_count_improves": combined["all_groups_cited_questions"][
            "assembler_successes"
        ]
        > combined["all_groups_cited_questions"]["baseline_successes"],
        "invalid_segment_zero": combined["span_validity"]["invalid"] == 0,
        "malformed_requirement_zero": combined["malformed_requirement_count"] == 0,
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "pass": passed,
        "decision": "GO_NEW_SEALED_CANARY"
        if passed
        else "NO_GO_SEGMENT_ASSEMBLER_CAUSE_ANALYSIS",
    }


def latency_metrics(logs: list[dict[str, Any]]) -> dict[str, Any]:
    requirement_values = sorted(float(row["latency_ms"]) for row in logs)
    by_case: dict[str, float] = {}
    for row in logs:
        by_case[row["case_id"]] = by_case.get(row["case_id"], 0.0) + float(
            row["latency_ms"]
        )
    question_values = sorted(by_case.values())

    def describe(values: list[float]) -> dict[str, Any]:
        return {
            "count": len(values),
            "median_ms": round(statistics.median(values), 3) if values else None,
            "p95_ms": round(values[min(len(values) - 1, int(len(values) * 0.95))], 3)
            if values
            else None,
            "total_ms": round(sum(values), 3),
        }

    return {
        "per_requirement": describe(requirement_values),
        "per_question_sum": describe(question_values),
        "prompt_tokens": sum(int(row.get("prompt_tokens", 0)) for row in logs),
        "completion_tokens": sum(int(row.get("completion_tokens", 0)) for row in logs),
    }


def _markdown(report: dict[str, Any]) -> bytes:
    dev = report["metrics"]["adaptive_dev_63"]
    combined = report["metrics"]["combined"]
    v1 = report["v1_failure_diagnosis"]
    lines = [
        "# Extractive Assembler v2 segment-selection pilot",
        "",
        f"- Decision: **{report['decision']}**",
        f"- V1 non-substring: {v1['non_substring_categories']}",
        f"- Dev evidence groups: 47/59 -> {dev['all_human_gold_evidence_group_citation']['assembler_successes']}/59",
        f"- Fully cited eligible questions: {combined['all_groups_cited_questions']['baseline_successes']}/{combined['all_groups_cited_questions']['total']} -> {combined['all_groups_cited_questions']['assembler_successes']}/{combined['all_groups_cited_questions']['total']}",
        f"- Exact slices: {combined['span_validity']['exact_slices']}; invalid: {combined['span_validity']['invalid']}",
        f"- Malformed requirements: {combined['malformed_requirement_count']}",
        f"- Improvements/regressions (group): {combined['comparison']['evidence_group_improvement_count']}/{combined['comparison']['evidence_group_regression_count']}",
        f"- Upstream retrieval/selection questions: {combined['failure_boundaries']['retrieval_bound_question_count']}/{combined['failure_boundaries']['selection_bound_question_count']}",
        "",
        "The model selected IDs only. Gold IDs were scoring-only and no answer",
        "text, entailment, answerability, or free-form generation was produced.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = 240.0,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "enumeration": root / DEFAULT_ENUMERATION,
        "canary_32": root / DEFAULT_CANARY,
        "dev_63": root / DEFAULT_DEV,
        "reranker_results": root / DEFAULT_RERANK_RESULTS,
        "reranker_scores": root / DEFAULT_RERANK_SCORES,
        "reranker_manifest": root / DEFAULT_RERANK_MANIFEST,
        "dev_baseline_cases": root / DEFAULT_DEV_BASELINE_CASES,
        "dev_baseline_manifest": root / DEFAULT_DEV_BASELINE_MANIFEST,
        "canary_baseline_cases": root / DEFAULT_CANARY_BASELINE_CASES,
        "canary_baseline_manifest": root / DEFAULT_CANARY_BASELINE_MANIFEST,
        "chunks": root / DEFAULT_CHUNKS,
        "v1_proposals": root / DEFAULT_V1_PROPOSALS,
        "v1_assembled_cases": root / DEFAULT_V1_CASES,
        "v1_diagnostics": root / DEFAULT_V1_DIAGNOSTICS,
        "v1_report": root / DEFAULT_V1_REPORT,
        "contract": root / DEFAULT_CONTRACT,
        "model_caller_source": root / "src/v3/evaluate_semantic_requirement_planner.py",
        "v1_evaluator_source": root / "src/v3/evaluate_extractive_assembler.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    cases = build_cases(
        read_jsonl(input_paths["canary_32"]),
        read_jsonl(input_paths["dev_63"]),
        read_jsonl(input_paths["enumeration"]),
        read_jsonl(input_paths["reranker_results"]),
        read_jsonl(input_paths["reranker_scores"]),
        read_jsonl(input_paths["canary_baseline_cases"]),
        read_jsonl(input_paths["dev_baseline_cases"]),
        read_jsonl(input_paths["chunks"]),
    )
    v1_summary, v1_rows = diagnose_v1(
        cases,
        read_jsonl(input_paths["v1_proposals"]),
        read_jsonl(input_paths["v1_assembled_cases"]),
        read_jsonl(input_paths["v1_diagnostics"]),
    )
    segment_rows = build_segment_rows(cases)
    model_meta = runtime_metadata(model, timeout)
    selections, call_logs = run_segment_selector(
        cases, segment_rows, model=model, timeout=timeout
    )
    assembled = assemble_segment_selections(cases, segment_rows, selections)
    diagnostics = score_cases_v2(cases, assembled)
    metrics = {
        "combined": aggregate_v2(diagnostics),
        "downgraded_canary_32": aggregate_v2(
            [row for row in diagnostics if row["dataset"] == "downgraded_canary_32"]
        ),
        "adaptive_dev_63": aggregate_v2(
            [row for row in diagnostics if row["dataset"] == "adaptive_dev_63"]
        ),
    }
    gate_result = gate_v2(metrics)
    latency = latency_metrics(call_logs)

    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"

    def freeze_jsonl(prefix: str, rows: list[dict[str, Any]]) -> tuple[Path, str]:
        payload = _serialize_jsonl(rows, lambda row: row["case_id"])
        digest = _sha256_bytes(payload)
        path = evidence_dir / f"{prefix}_{digest}.jsonl"
        write_immutable(path, payload)
        return path, digest

    v1_payload = _serialize_jsonl(
        v1_rows,
        lambda row: (row["case_id"], row["requirement_id"] or "", row["v1_failure_category"]),
    )
    v1_sha = _sha256_bytes(v1_payload)
    v1_path = evidence_dir / f"extractive_assembler_v1_failure_types_{v1_sha}.jsonl"
    write_immutable(v1_path, v1_payload)
    segments_path, segments_sha = freeze_jsonl(
        "extractive_assembler_v2_segments", segment_rows
    )
    selections_path, selections_sha = freeze_jsonl(
        "extractive_assembler_v2_selections", selections
    )
    assembled_path, assembled_sha = freeze_jsonl(
        "extractive_assembler_v2_cases", assembled
    )
    diagnostics_path, diagnostics_sha = freeze_jsonl(
        "extractive_assembler_v2_diagnostics", diagnostics
    )

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_32_plus_63",
        "decision": gate_result["decision"],
        "gate": gate_result,
        "v1_failure_diagnosis": v1_summary,
        "metrics": metrics,
        "latency": latency,
        "segmentation": {
            "version": SEGMENT_SCHEMA_VERSION,
            "spec_sha256": _segmentation_sha256(),
            "kiwipiepy_version": kiwipiepy_version,
            "candidate_count": sum(len(row["segments"]) for row in segment_rows),
        },
        "model": {
            **model_meta,
            "prompt_sha256": _prompt_sha256(),
            "task": "single_requirement_segment_id_selection_only",
        },
        "contract": {
            "gold_ids_available_to_model": False,
            "answer_text_generated": False,
            "multiple_segment_ids_allowed": True,
            "one_model_call_per_requirement": True,
            "exact_text_source": "deterministic_offset_slice",
            "retrieval_and_selection_bound_excluded_from_gate": True,
        },
        "scope": {
            "assembler_only": True,
            "entailment_judge": "parked",
            "answerability": "parked",
            "freeform_generation": False,
            "training": False,
            "new_keyword_rules": False,
            "retrieval_changed": False,
            "reranker_changed": False,
            "planner_changed": False,
            "new_canary": False,
            "frozen_blind_accessed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"extractive_assembler_v2_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"extractive_assembler_v2_pilot_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    artifacts = {
        "v1_failure_types": (v1_path, v1_sha, len(v1_rows)),
        "segments": (segments_path, segments_sha, len(segment_rows)),
        "selections": (selections_path, selections_sha, len(selections)),
        "assembled_cases": (assembled_path, assembled_sha, len(assembled)),
        "diagnostics": (diagnostics_path, diagnostics_sha, len(diagnostics)),
        "report": (report_path, report_sha, None),
        "report_markdown": (markdown_path, markdown_sha, None),
    }
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "model": report["model"],
        "segmentation": report["segmentation"],
        "artifacts": {
            name: {
                "path": _relative(root, value[0]),
                "sha256": value[1],
                **({"row_count": value[2]} if value[2] is not None else {}),
            }
            for name, value in artifacts.items()
        },
        "decision": gate_result["decision"],
        "gold_available_to_model": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"extractive_assembler_v2_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during assembler v2 pilot: {name}")
    return {
        "decision": gate_result["decision"],
        "gate": gate_result,
        "v1_failure_diagnosis": v1_summary,
        "metrics": metrics,
        "latency": latency,
        "segmentation": report["segmentation"],
        "model": report["model"],
        "artifacts": {
            name: {"path": str(value[0]), "sha256": value[1]}
            for name, value in artifacts.items()
        },
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the exact segment-ID extractive assembler v2 pilot"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--evaluated-at")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        model=args.model,
        timeout=args.timeout,
        evaluated_at=args.evaluated_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
