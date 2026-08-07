from __future__ import annotations

from typing import Any

from src.v3.answer_target_coverage import extract_target_token_sets
from src.v3.answer_target_router import _base_tag, _is_nominal_tag, _kiwi


FILTER_SCHEMA_VERSION = "dnf-behavioral-decomposition-filter-v3.2"
FILTER_VERSION = "strict-coverage-gain-v3.2.0"


def _chunk_nominal_terms(text: str) -> frozenset[str]:
    return frozenset(
        f"{token.form}/{_base_tag(token)}"
        for token in _kiwi().tokenize(text)
        if _is_nominal_tag(_base_tag(token))
    )


def _target_coverage_ratios(
    targets: list[frozenset[str]], hits: list[dict[str, Any]]
) -> list[float]:
    chunk_terms = [_chunk_nominal_terms(row["display_text"]) for row in hits]
    return [
        max(
            (
                len(target.intersection(terms)) / len(target)
                for terms in chunk_terms
            ),
            default=0.0,
        )
        for target in targets
    ]


def evaluate_behavioral_coverage(
    question: str,
    single_hits: list[dict[str, Any]],
    decomposed_union_hits: list[dict[str, Any]],
    *,
    threshold: float,
) -> dict[str, Any]:
    if not 0.0 < threshold <= 1.0:
        raise RuntimeError("coverage threshold must be in (0, 1]")
    targets = extract_target_token_sets(question)
    single_ratios = _target_coverage_ratios(targets, single_hits)
    decomposed_ratios = _target_coverage_ratios(targets, decomposed_union_hits)
    single_covered = sum(value >= threshold for value in single_ratios)
    decomposed_covered = sum(value >= threshold for value in decomposed_ratios)
    measurable = len(targets) >= 2
    return {
        "filter_schema_version": FILTER_SCHEMA_VERSION,
        "filter_version": FILTER_VERSION,
        "threshold": threshold,
        "target_count": len(targets),
        "single_target_coverage_ratios": [round(value, 8) for value in single_ratios],
        "decomposed_target_coverage_ratios": [
            round(value, 8) for value in decomposed_ratios
        ],
        "coverage_single": single_covered,
        "coverage_decomposed": decomposed_covered,
        "coverage_measurable": measurable,
        "commit_decomposition": measurable and decomposed_covered > single_covered,
        "strict_coverage_gain_required": True,
        "gold_identifiers_used": False,
        "expected_source_used": False,
        "new_field_or_intent_keyword_rule_count": 0,
        "store_expansion_applied": False,
    }
