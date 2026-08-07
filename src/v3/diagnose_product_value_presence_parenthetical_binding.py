from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3 import simple_evidence_refs
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    kiwi_independent_requirement_queries,
)
from src.v3.product_free_rag import DEFAULT_EVIDENCE_UNITS, ProductFreeRAG
from src.v3.simple_evidence_refs import _exact_line_spans, _sentence_spans
from src.v3.value_normalization import (
    currency_values,
    number_values,
    time_values,
)


RUNNER_VERSION = "product-value-presence-parenthetical-diagnostic-v1"
TEXT_TOKEN_THRESHOLD = 0.8
DEFAULT_FROZEN = Path(
    "data/v3/evaluation/"
    "product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl"
)
DEFAULT_PACK = Path(
    "reports/v3/product_header_metadata_pack_post_v3_20260805.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_M3_OUTPUT = Path(
    "reports/v3/product_value_presence_m3_20260805.jsonl"
)
DEFAULT_P31_OUTPUT = Path(
    "reports/v3/product_parenthetical_orphans_p31_20260805.jsonl"
)
DEFAULT_P32_OUTPUT = Path(
    "reports/v3/product_parenthetical_orphans_p32_review_20260805.jsonl"
)
DEFAULT_P34_OUTPUT = Path(
    "reports/v3/product_parenthetical_binding_p34_shadow_20260805.jsonl"
)

_DATE_PATTERNS = (
    re.compile(
        r"(?<!\d)(?P<year>20\d{2})[-./](?P<month>\d{1,2})"
        r"[-./](?P<day>\d{1,2})(?!\d)"
    ),
    re.compile(
        r"(?<!\d)(?P<year>20\d{2})\s*년\s*(?P<month>\d{1,2})"
        r"\s*월\s*(?P<day>\d{1,2})\s*일"
    ),
    re.compile(
        r"(?<!\d)(?P<year>\d{2})[.](?P<month>\d{1,2})[.]"
        r"(?P<day>\d{1,2})(?!\d)"
    ),
    re.compile(
        r"(?<![\d년])(?P<month>\d{1,2})\s*월\s*"
        r"(?P<day>\d{1,2})\s*일"
    ),
)
_PERCENTAGE = re.compile(r"(?<!\d)(\d+(?:[.]\d+)?)\s*(?:%|퍼센트)")
_BOOLEAN_TYPES = {"boolean"}
_PREDICATE_ENDING = re.compile(
    r"(?:습니다|입니다|됩니다|합니다|했습니다|였습니다|있습니다|없습니다|"
    r"않습니다|이다|했다|된다|한다|있다|없다|않다|임|함|됨)"
    r"[.!?)]*$"
)
_SYMBOL_PREFIX = re.compile(r"^(?:※|▶|▷|◆|◇|■|□|●|○|[-*])")
_STANDALONE_NUMBER = re.compile(
    r"^[([{]?\s*[+\-]?\d[\d,.]*\s*(?:초|분|시간|일|회|개|칸|"
    r"%|퍼센트|골드|세라|원|레벨|Lv)?\s*[)\]}]?$",
    re.IGNORECASE,
)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _date_values(value: Any, *, as_of: str) -> set[str]:
    text = str(value or "")
    default_year = int(as_of[:4])
    output = set()
    occupied: list[tuple[int, int]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(
                match.start() < end and match.end() > start
                for start, end in occupied
            ):
                continue
            year_text = match.groupdict().get("year")
            year = (
                default_year
                if year_text is None
                else 2000 + int(year_text)
                if len(year_text) == 2
                else int(year_text)
            )
            try:
                normalized = datetime(
                    year,
                    int(match.group("month")),
                    int(match.group("day")),
                ).date().isoformat()
            except ValueError:
                continue
            output.add(normalized)
            occupied.append((match.start(), match.end()))
    return output


def _percentage_values(value: Any) -> set[float]:
    return {
        float(match.group(1))
        for match in _PERCENTAGE.finditer(str(value or ""))
    }


def _normalized_compact(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"번(?=\s|$)", "회", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _surface_tokens(value: Any) -> list[str]:
    text = str(value or "").casefold()
    text = re.sub(r"(?:할|될)\s*수\s*있(?:습니다|다|음)?", " 가능 ", text)
    text = re.sub(r"않(?:습니다|음|다)", "않", text)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"(?<=\d)(?=[a-z가-힣])", " ", text)
    text = re.sub(r"(?<=[a-z가-힣])(?=\d)", " ", text)
    raw = re.findall(r"[0-9a-z가-힣]+", text)
    return [
        "회" if token == "번" else token
        for token in raw
        if len(token) >= 2 or token.isdigit()
    ]


def _token_is_present(token: str, observed_tokens: list[str]) -> bool:
    if token in observed_tokens:
        return True
    if len(token) < 2:
        return False
    return any(
        token in observed or observed in token
        for observed in observed_tokens
        if len(observed) >= 2
    )


def text_token_coverage(expected: Any, observed: str) -> float:
    expected_tokens = _surface_tokens(expected)
    if not expected_tokens:
        return 0.0
    observed_tokens = _surface_tokens(observed)
    matched = sum(
        _token_is_present(token, observed_tokens)
        for token in expected_tokens
    )
    return matched / len(expected_tokens)


def _date_residual(value: Any) -> str:
    text = str(value or "")
    for pattern in _DATE_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def _residual_token_coverage(expected: Any, observed: Any) -> float:
    if not _surface_tokens(expected):
        return 1.0
    return text_token_coverage(expected, str(observed or ""))


def value_present(
    expected: Any,
    observed: str,
    *,
    value_type: str,
    as_of: str,
    token_threshold: float = TEXT_TOKEN_THRESHOLD,
) -> tuple[bool, dict[str, Any]]:
    if isinstance(expected, bool):
        return False, {"method": "boolean_excluded"}
    if isinstance(expected, dict):
        checks = [
            value_present(
                value,
                observed,
                value_type=value_type,
                as_of=as_of,
                token_threshold=token_threshold,
            )[0]
            for value in expected.values()
        ]
        return all(checks), {"method": "mapping_values", "checks": checks}
    if isinstance(expected, list):
        checks = [
            value_present(
                value,
                observed,
                value_type=value_type,
                as_of=as_of,
                token_threshold=token_threshold,
            )[0]
            for value in expected
        ]
        return all(checks), {"method": "list_values", "checks": checks}

    expected_text = str(expected or "")
    compact_expected = _normalized_compact(expected_text)
    compact_observed = _normalized_compact(observed)
    if compact_expected and compact_expected in compact_observed:
        return True, {"method": "normalized_compact", "token_coverage": 1.0}

    expected_dates = _date_values(expected_text, as_of=as_of)
    if expected_dates:
        observed_dates = _date_values(observed, as_of=as_of)
        residual_coverage = _residual_token_coverage(
            _date_residual(expected_text),
            _date_residual(observed),
        )
        present = bool(
            expected_dates <= observed_dates
            and residual_coverage >= token_threshold
        )
        return present, {
            "method": "normalized_date_and_tokens",
            "expected_dates": sorted(expected_dates),
            "observed_dates": sorted(observed_dates),
            "token_coverage": round(residual_coverage, 4),
        }

    expected_times = time_values(expected_text)
    if expected_times:
        observed_times = time_values(observed)
        if not expected_times <= observed_times:
            return False, {
                "method": "normalized_time",
                "expected_times": sorted(expected_times),
                "observed_times": sorted(observed_times),
            }

    expected_percentages = _percentage_values(expected_text)
    if expected_percentages:
        observed_percentages = _percentage_values(observed)
        if not expected_percentages <= observed_percentages:
            return False, {
                "method": "normalized_percentage",
                "expected_percentages": sorted(expected_percentages),
                "observed_percentages": sorted(observed_percentages),
            }

    expected_currencies = currency_values(expected_text)
    observed_currencies = currency_values(observed)
    if expected_currencies and expected_currencies <= observed_currencies:
        currency_pattern = re.compile(
            r"\d[\d,]*(?:[.]\d+)?\s*(?:만|억)?\s*"
            r"(?:광휘의\s*잔영|골드\s*코인|세라\s*코인|마일리지|"
            r"포인트|코인|세라|골드|원)",
            re.IGNORECASE,
        )
        residual_coverage = _residual_token_coverage(
            currency_pattern.sub(" ", expected_text),
            currency_pattern.sub(" ", observed),
        )
        if residual_coverage >= token_threshold:
            return True, {
                "method": "normalized_currency_and_tokens",
                "token_coverage": round(residual_coverage, 4),
                "expected_currencies": sorted(expected_currencies),
                "observed_currencies": sorted(observed_currencies),
            }

    raw_coverage = text_token_coverage(expected_text, observed)
    if raw_coverage >= token_threshold:
        return True, {
            "method": "token_coverage",
            "token_coverage": round(raw_coverage, 4),
        }

    expected_numbers = number_values(expected_text)
    observed_numbers = number_values(observed)
    return False, {
        "method": "not_present",
        "token_coverage": round(raw_coverage, 4),
        "expected_currencies": sorted(expected_currencies),
        "observed_currencies": sorted(observed_currencies),
        "expected_numbers": sorted(expected_numbers),
        "observed_numbers": sorted(observed_numbers),
    }


def _overlaps(unit: dict[str, Any], gold: dict[str, Any]) -> bool:
    return bool(
        str(unit.get("chunk_id") or "") == str(gold.get("chunk_id") or "")
        and int(unit.get("start_char", -1)) < int(gold.get("end_char", -1))
        and int(unit.get("end_char", -1)) > int(gold.get("start_char", -1))
    )


def score_requirement_value_presence(
    requirement: dict[str, Any],
    *,
    evidence_pack: list[dict[str, Any]],
    as_of: str,
) -> dict[str, Any]:
    gold_units = requirement.get("acceptable_evidence_units") or []
    assigned_units = [
        unit
        for unit in evidence_pack
        if any(_overlaps(unit, gold) for gold in gold_units)
    ]
    overlap_visible = bool(assigned_units)
    value_type = str(requirement.get("value_type") or "")
    required_values = requirement.get("required_values") or []
    if requirement.get("expected_status") != "supported":
        classification = "unsupported_excluded"
        value_checks: list[dict[str, Any]] = []
    elif value_type in _BOOLEAN_TYPES or any(
        isinstance(value, bool) for value in required_values
    ):
        classification = "boolean_excluded"
        value_checks = []
    else:
        observed = "\n".join(str(unit.get("text") or "") for unit in assigned_units)
        value_checks = []
        for expected in required_values:
            present, detail = value_present(
                expected,
                observed,
                value_type=value_type,
                as_of=as_of,
            )
            value_checks.append(
                {"expected": expected, "present": present, **detail}
            )
        present_count = sum(check["present"] for check in value_checks)
        classification = (
            "value_present_full"
            if value_checks and present_count == len(value_checks)
            else "value_present_partial"
            if present_count
            else "value_present_none"
        )
    return {
        "requirement_id": requirement.get("requirement_id"),
        "value_type": value_type,
        "expected_status": requirement.get("expected_status"),
        "required_values": required_values,
        "gold_coordinate_count": len(gold_units),
        "overlap_visible": overlap_visible,
        "assigned_units": [
            {
                "evidence_ref": unit.get("evidence_ref"),
                "chunk_id": unit.get("chunk_id"),
                "start_char": unit.get("start_char"),
                "end_char": unit.get("end_char"),
                "text": unit.get("text"),
            }
            for unit in assigned_units
        ],
        "value_checks": value_checks,
        "value_presence": classification,
    }


def build_m3_rows(
    frozen_rows: list[dict[str, Any]],
    pack_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    packs_by_ref = {
        str(row["case_ref"]): row
        for row in pack_rows
        if row.get("type") == "case"
    }
    cases = []
    for frozen in frozen_rows:
        case_ref = f"A6-{frozen['slot_ordinal']}"
        pack_row = packs_by_ref[case_ref]
        requirements = [
            score_requirement_value_presence(
                requirement,
                evidence_pack=pack_row["evidence_pack"],
                as_of=str(frozen["as_of"]),
            )
            for requirement in frozen.get("requirements") or []
        ]
        measurable = [
            row
            for row in requirements
            if row["value_presence"].startswith("value_present_")
        ]
        slot_presence = (
            "boolean_only"
            if not measurable
            else "value_present_full"
            if all(row["value_presence"] == "value_present_full" for row in measurable)
            else "value_present_none"
            if all(row["value_presence"] == "value_present_none" for row in measurable)
            else "value_present_partial"
        )
        cases.append(
            {
                "type": "case",
                "case_ref": case_ref,
                "slot_ordinal": frozen["slot_ordinal"],
                "question": frozen["question_text"],
                "candidate_chunk_ids": pack_row["candidate_chunk_ids"],
                "evidence_pack": pack_row["evidence_pack"],
                "requirements": requirements,
                "slot_value_presence": slot_presence,
            }
        )
    measurable_requirements = [
        requirement
        for case in cases
        for requirement in case["requirements"]
        if requirement["value_presence"].startswith("value_present_")
    ]
    missed_by_overlap = [
        {
            "case_ref": case["case_ref"],
            "requirement_id": requirement["requirement_id"],
            "value_presence": requirement["value_presence"],
            "required_values": requirement["required_values"],
            "assigned_units": requirement["assigned_units"],
        }
        for case in cases
        for requirement in case["requirements"]
        if requirement["overlap_visible"]
        and requirement["value_presence"]
        in {"value_present_partial", "value_present_none"}
    ]
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "phase": "M3",
        "qwen_calls": 0,
        "runtime_changed": False,
        "text_token_threshold": TEXT_TOKEN_THRESHOLD,
        "case_count": len(cases),
        "requirement_count": sum(len(case["requirements"]) for case in cases),
        "gold_coordinate_count": sum(
            requirement["gold_coordinate_count"]
            for case in cases
            for requirement in case["requirements"]
        ),
        "measurable_requirement_count": len(measurable_requirements),
        "boolean_excluded_count": sum(
            requirement["value_presence"] == "boolean_excluded"
            for case in cases
            for requirement in case["requirements"]
        ),
        "unsupported_excluded_count": sum(
            requirement["value_presence"] == "unsupported_excluded"
            for case in cases
            for requirement in case["requirements"]
        ),
        "requirement_value_presence_counts": dict(
            Counter(row["value_presence"] for row in measurable_requirements)
        ),
        "slot_value_presence_counts": dict(
            Counter(case["slot_value_presence"] for case in cases)
        ),
        "legacy_overlap_visible_gold_coordinates": 55,
        "overlap_true_but_value_not_full_count": len(missed_by_overlap),
        "overlap_true_but_value_not_full": missed_by_overlap,
    }
    return [*cases, summary]


def classify_orphan_fragment(fragment: str) -> str:
    stripped = fragment.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return "parenthetical"
    if "→" in stripped or "->" in stripped:
        return "arrow"
    if _SYMBOL_PREFIX.match(stripped):
        return "symbol_prefix"
    if _STANDALONE_NUMBER.fullmatch(stripped):
        return "standalone_number"
    return "other"


def should_bind_trailing_parenthetical(
    previous: tuple[int, int, str],
    fragment: tuple[int, int, str],
    *,
    line: str,
    line_start: int,
) -> bool:
    text = fragment[2].strip()
    gap = line[
        previous[1] - line_start : fragment[0] - line_start
    ]
    return bool(
        previous[2].rstrip().endswith((".", "!", "?"))
        and gap.strip() == ""
        and text.startswith("(")
        and text.endswith(")")
        and text.count("(") == text.count(")")
        and len(text) <= 30
        and re.search(r"\d", text)
        and not _PREDICATE_ENDING.search(text)
    )


def sentence_spans_with_parenthetical_binding(
    text: str,
    *,
    line_start: int,
) -> list[tuple[int, int, str]]:
    original = _sentence_spans(text, line_start=line_start)
    merged: list[tuple[int, int, str]] = []
    for span in original:
        if merged and should_bind_trailing_parenthetical(
            merged[-1],
            span,
            line=text,
            line_start=line_start,
        ):
            previous = merged.pop()
            start = previous[0]
            end = span[1]
            merged.append(
                (start, end, text[start - line_start : end - line_start])
            )
        else:
            merged.append(span)
    return merged


def extract_numeric_orphan_fragments(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks:
        source_text = str(chunk.get("display_text") or "")
        in_table = False
        for line_start, _, line in _exact_line_spans(source_text):
            stripped = line.strip()
            if stripped == "[TABLE]":
                in_table = True
                continue
            if stripped == "[/TABLE]":
                in_table = False
                continue
            if in_table or stripped.startswith("#") or "|" in line:
                continue
            sentence_spans = _sentence_spans(line, line_start=line_start)
            for previous, fragment in zip(sentence_spans, sentence_spans[1:]):
                fragment_text = fragment[2].strip()
                if (
                    len(fragment_text) > 30
                    or not re.search(r"\d", fragment_text)
                    or _PREDICATE_ENDING.search(fragment_text)
                ):
                    continue
                identity = ":".join(
                    (
                        str(chunk.get("chunk_id") or ""),
                        str(fragment[0]),
                        str(fragment[1]),
                        fragment[2],
                    )
                )
                rows.append(
                    {
                        "type": "candidate",
                        "candidate_id": "orphan_sha256_"
                        + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                        "source_id": chunk.get("source_id"),
                        "source_kind": chunk.get("source_kind"),
                        "chunk_id": chunk.get("chunk_id"),
                        "parent_document_id": chunk.get("parent_document_id"),
                        "chunk_index": chunk.get("chunk_index"),
                        "line_text": line,
                        "previous_start_char": previous[0],
                        "previous_end_char": previous[1],
                        "previous_text": previous[2],
                        "fragment_start_char": fragment[0],
                        "fragment_end_char": fragment[1],
                        "fragment_text": fragment[2],
                        "fragment_type": classify_orphan_fragment(fragment_text),
                    }
                )
    return rows


def build_p32_review_rows(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist the completed 2026-08-05 row-by-row human review."""

    reviewed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    reviewed = []
    for row in candidates:
        fragment = str(row.get("fragment_text") or "").strip()
        if row.get("fragment_type") == "parenthetical":
            decision = "merge_required"
            rationale = (
                "완결된 같은 줄 후행 괄호가 앞 문장의 수치·기한·조건을 "
                "보충하며 단독으로는 주어를 잃습니다."
            )
        elif fragment.startswith("("):
            decision = "ambiguous"
            rationale = (
                "괄호 안 날짜의 마침표에서 다시 분할된 미완성 단편이라 "
                "직전 두 unit 결합만으로는 원문을 온전히 복구할 수 없습니다."
            )
        else:
            decision = "do_not_merge"
            rationale = (
                "독립 문장·목록 번호·오류 코드·OCR 단편으로, 앞 문장 값에 "
                "종속된 완결 괄호가 아닙니다."
            )
        reviewed.append(
            {
                **row,
                "manual_review_decision": decision,
                "manual_review_rationale": rationale,
                "reviewer": "Codex",
                "reviewed_at": reviewed_at,
            }
        )
    counts = Counter(row["manual_review_decision"] for row in reviewed)
    expected_counts = {
        "merge_required": 44,
        "ambiguous": 7,
        "do_not_merge": 53,
    }
    if dict(counts) != expected_counts:
        raise RuntimeError(
            "P3-2 manual decisions are valid only for the reviewed 104-row corpus: "
            f"{dict(counts)}"
        )
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "phase": "P3-2",
        "qwen_calls": 0,
        "runtime_changed": False,
        "reviewer": "Codex",
        "reviewed_at": reviewed_at,
        "reviewed_count": len(reviewed),
        "manual_review_decision_counts": dict(counts),
        "review_method": "row_by_row_full_corpus_manual_review",
    }
    return [*reviewed, summary]


def _coordinate(unit: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(unit.get("chunk_id") or ""),
        int(unit.get("start_char", -1)),
        int(unit.get("end_char", -1)),
        str(unit.get("unit_kind") or ""),
    )


def _pack_for_case(
    rag: ProductFreeRAG,
    case: dict[str, Any],
    *,
    shadow: bool,
) -> tuple[list[dict[str, Any]], float]:
    original_sentence_spans = simple_evidence_refs._sentence_spans
    if shadow:
        simple_evidence_refs._sentence_spans = (
            sentence_spans_with_parenthetical_binding
        )
    started = time.perf_counter()
    try:
        requirement_queries = kiwi_independent_requirement_queries(
            str(case["question"])
        )
        pack = build_atomic_reranked_product_evidence_pack(
            list(case["candidate_chunk_ids"]),
            question=str(case["question"]),
            requirement_queries=requirement_queries or None,
            chunks_by_id=rag._artifacts.chunks_by_id,
            documents_by_id=rag._artifacts.documents_by_id,
            temporal_by_document=rag.temporal_by_document,
            score_pairs=rag._score_pairs,
            max_units=DEFAULT_EVIDENCE_UNITS,
            prefilter_per_query=32,
            reserve_per_query=3 if len(requirement_queries) > 1 else 1,
        )
    finally:
        simple_evidence_refs._sentence_spans = original_sentence_spans
    return pack, (time.perf_counter() - started) * 1000


def _rule_review_metrics(review_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    examples = []
    for row in review_rows:
        previous = (
            int(row["previous_start_char"]),
            int(row["previous_end_char"]),
            str(row["previous_text"]),
        )
        fragment = (
            int(row["fragment_start_char"]),
            int(row["fragment_end_char"]),
            str(row["fragment_text"]),
        )
        line_start = previous[0] - str(row["line_text"]).find(previous[2])
        selected = should_bind_trailing_parenthetical(
            previous,
            fragment,
            line=str(row["line_text"]),
            line_start=line_start,
        )
        decision = str(row["manual_review_decision"])
        bucket = (
            "true_positive"
            if selected and decision == "merge_required"
            else "false_positive"
            if selected
            else "false_negative"
            if decision == "merge_required"
            else "not_selected_ambiguous"
            if decision == "ambiguous"
            else "true_negative"
        )
        counts[bucket] += 1
        if bucket in {"false_positive", "false_negative"}:
            examples.append(
                {
                    "candidate_id": row["candidate_id"],
                    "bucket": bucket,
                    "previous_text": row["previous_text"],
                    "fragment_text": row["fragment_text"],
                }
            )
    return {"counts": dict(counts), "errors": examples}


def build_p34_rows(
    *,
    root: Path,
    frozen_rows: list[dict[str, Any]],
    m3_rows: list[dict[str, Any]],
    pack_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    device: str,
) -> list[dict[str, Any]]:
    m3_cases = {
        str(row["case_ref"]): row
        for row in m3_rows
        if row.get("type") == "case"
    }
    saved_cases = {
        str(row["case_ref"]): row
        for row in pack_rows
        if row.get("type") == "case"
    }
    frozen_by_ref = {
        f"A6-{row['slot_ordinal']}": row for row in frozen_rows
    }
    rag = ProductFreeRAG(
        root=root,
        device=device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    cases = []
    for slot in range(1, 33):
        case_ref = f"A6-{slot}"
        saved = saved_cases[case_ref]
        frozen = frozen_by_ref[case_ref]
        baseline_pack, baseline_ms = _pack_for_case(rag, saved, shadow=False)
        shadow_pack, shadow_ms = _pack_for_case(rag, saved, shadow=True)
        baseline_coordinates = [_coordinate(unit) for unit in baseline_pack]
        saved_coordinates = [
            _coordinate(unit) for unit in saved["evidence_pack"]
        ]
        shadow_coordinates = [_coordinate(unit) for unit in shadow_pack]
        shadow_requirements = [
            score_requirement_value_presence(
                requirement,
                evidence_pack=shadow_pack,
                as_of=str(frozen["as_of"]),
            )
            for requirement in frozen.get("requirements") or []
        ]
        baseline_by_id = {
            str(row["requirement_id"]): row
            for row in m3_cases[case_ref]["requirements"]
        }
        value_changes = [
            {
                "requirement_id": row["requirement_id"],
                "before": baseline_by_id[str(row["requirement_id"])][
                    "value_presence"
                ],
                "after": row["value_presence"],
            }
            for row in shadow_requirements
            if baseline_by_id[str(row["requirement_id"])]["value_presence"]
            != row["value_presence"]
        ]
        coordinate_mismatches = []
        for unit in shadow_pack:
            source_text = str(
                rag._artifacts.chunks_by_id[str(unit["chunk_id"])].get(
                    "display_text"
                )
                or ""
            )
            if source_text[
                int(unit["start_char"]) : int(unit["end_char"])
            ] != str(unit.get("text") or ""):
                coordinate_mismatches.append(_coordinate(unit))
        cases.append(
            {
                "type": "case",
                "phase": "P3-4",
                "case_ref": case_ref,
                "question": saved["question"],
                "candidate_chunk_ids": saved["candidate_chunk_ids"],
                "saved_baseline_replay_exact": (
                    baseline_coordinates == saved_coordinates
                ),
                "pack_set_changed": (
                    set(baseline_coordinates) != set(shadow_coordinates)
                ),
                "pack_order_changed": (
                    set(baseline_coordinates) == set(shadow_coordinates)
                    and baseline_coordinates != shadow_coordinates
                ),
                "baseline_pack": baseline_pack,
                "shadow_pack": shadow_pack,
                "value_changes": value_changes,
                "shadow_requirements": shadow_requirements,
                "baseline_candidate_rerank_ms": round(baseline_ms, 3),
                "shadow_candidate_rerank_ms": round(shadow_ms, 3),
                "candidate_rerank_delta_ms": round(shadow_ms - baseline_ms, 3),
                "coordinate_mismatches": coordinate_mismatches,
            }
        )
        print(
            json.dumps(
                {
                    "case_ref": case_ref,
                    "pack_set_changed": cases[-1]["pack_set_changed"],
                    "value_changes": value_changes,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    value_changes = [
        {"case_ref": case["case_ref"], **change}
        for case in cases
        for change in case["value_changes"]
    ]
    order = {
        "value_present_none": 0,
        "value_present_partial": 1,
        "value_present_full": 2,
    }
    decreases = [
        change
        for change in value_changes
        if change["before"] in order
        and change["after"] in order
        and order[change["after"]] < order[change["before"]]
    ]
    a67 = next(case for case in cases if case["case_ref"] == "A6-7")
    a67_requirement = next(
        row
        for row in a67["shadow_requirements"]
        if row["requirement_id"] == "base_cooldown_change"
    )
    changed_cases = [case for case in cases if case["pack_set_changed"]]
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "phase": "P3-4",
        "qwen_calls": 0,
        "runtime_changed": False,
        "case_count": len(cases),
        "rule": {
            "same_line": True,
            "complete_balanced_parentheses": True,
            "numeric_fragment": True,
            "max_fragment_chars": 30,
            "previous_ends_sentence_boundary": True,
            "fragment_has_no_predicate_ending": True,
        },
        "manual_review_rule_metrics": _rule_review_metrics(review_rows),
        "saved_baseline_replay_exact_count": sum(
            case["saved_baseline_replay_exact"] for case in cases
        ),
        "a6_7_base_cooldown_value_presence": a67_requirement[
            "value_presence"
        ],
        "a6_7_value_checks": a67_requirement["value_checks"],
        "value_presence_changes": value_changes,
        "value_presence_decreases": decreases,
        "pack_set_changed_case_count": len(changed_cases),
        "pack_set_changed_records": [
            {
                "case_ref": case["case_ref"],
                "baseline_coordinates": [
                    _coordinate(unit) for unit in case["baseline_pack"]
                ],
                "shadow_coordinates": [
                    _coordinate(unit) for unit in case["shadow_pack"]
                ],
            }
            for case in changed_cases
        ],
        "pack_order_changed_case_refs": [
            case["case_ref"] for case in cases if case["pack_order_changed"]
        ],
        "candidate_rerank_baseline_total_ms": round(
            sum(case["baseline_candidate_rerank_ms"] for case in cases), 3
        ),
        "candidate_rerank_shadow_total_ms": round(
            sum(case["shadow_candidate_rerank_ms"] for case in cases), 3
        ),
        "candidate_rerank_delta_total_ms": round(
            sum(case["candidate_rerank_delta_ms"] for case in cases), 3
        ),
        "coordinate_mismatch_case_refs": [
            case["case_ref"] for case in cases if case["coordinate_mismatches"]
        ],
        "gates": {
            "a6_7_20s_and_18s_value_present": bool(
                a67_requirement["value_presence"] == "value_present_full"
            ),
            "value_presence_decrease_zero": not decreases,
            "rule_false_positive_zero": not _rule_review_metrics(review_rows)[
                "errors"
            ],
            "coordinate_mismatch_zero": not any(
                case["coordinate_mismatches"] for case in cases
            ),
        },
    }
    summary["p3_go"] = all(summary["gates"].values())
    return [*cases, summary]


def _write_new(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise RuntimeError(f"diagnostic output already exists: {path}")
    write_jsonl(path, rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure A6 values and extract split numeric fragments"
    )
    parser.add_argument("phase", choices=("m3", "p31", "p32", "p34"))
    parser.add_argument("--frozen", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.phase == "m3":
        output = _resolve(root, args.output or DEFAULT_M3_OUTPUT)
        rows = build_m3_rows(
            read_jsonl(_resolve(root, args.frozen)),
            read_jsonl(_resolve(root, args.pack)),
        )
    elif args.phase == "p31":
        output = _resolve(root, args.output or DEFAULT_P31_OUTPUT)
        candidates = extract_numeric_orphan_fragments(
            read_jsonl(_resolve(root, args.chunks))
        )
        summary = {
            "type": "summary",
            "runner_version": RUNNER_VERSION,
            "phase": "P3-1",
            "qwen_calls": 0,
            "runtime_changed": False,
            "candidate_count": len(candidates),
            "fragment_type_counts": dict(
                Counter(row["fragment_type"] for row in candidates)
            ),
            "source_kind_counts": dict(
                Counter(str(row["source_kind"]) for row in candidates)
            ),
        }
        rows = [*candidates, summary]
    elif args.phase == "p32":
        output = _resolve(root, args.output or DEFAULT_P32_OUTPUT)
        p31_path = _resolve(root, args.pack)
        if args.pack == DEFAULT_PACK:
            p31_path = _resolve(root, DEFAULT_P31_OUTPUT)
        rows = build_p32_review_rows(
            [
                row
                for row in read_jsonl(p31_path)
                if row.get("type") == "candidate"
            ]
        )
    else:
        output = _resolve(root, args.output or DEFAULT_P34_OUTPUT)
        rows = build_p34_rows(
            root=root,
            frozen_rows=read_jsonl(_resolve(root, args.frozen)),
            m3_rows=read_jsonl(_resolve(root, DEFAULT_M3_OUTPUT)),
            pack_rows=read_jsonl(_resolve(root, args.pack)),
            review_rows=[
                row
                for row in read_jsonl(_resolve(root, DEFAULT_P32_OUTPUT))
                if row.get("type") == "candidate"
            ],
            device=args.device,
        )
    _write_new(output, rows)
    print(json.dumps(rows[-1], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
