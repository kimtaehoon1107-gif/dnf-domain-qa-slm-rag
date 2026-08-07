from __future__ import annotations

from typing import Any

from kiwipiepy import Kiwi

from src.v3.select_evidence import classify_answerability


CLASSIFIER_VERSION = "mixed-answerability-kiwi-structure-v3.2.0"
_FIRST_PERSON_PRONOUNS = {"나", "저", "우리"}
_PERSON_CASE_TAGS = {"JKG", "JKS", "JX"}
_PREDICATE_PREFIXES = ("VV", "VA", "XSV", "XSA")
_CONTENT_PREFIXES = ("NN", "VV", "VA")
_KIWI: Kiwi | None = None


def _kiwi() -> Kiwi:
    global _KIWI
    if _KIWI is None:
        _KIWI = Kiwi()
    return _KIWI


def analyze_first_person_clause(query: str) -> dict[str, Any]:
    """Detect a separate first-person clause without domain keyword rules.

    The signal requires an official-looking content clause before a connective
    ending and a later first-person predicate clause. It does not classify a
    single personal question by itself and never names game fields or intents.
    """

    tokens = list(_kiwi().tokenize(query))
    for index, token in enumerate(tokens):
        if token.tag != "NP" or token.form not in _FIRST_PERSON_PRONOUNS:
            continue
        marker = next(
            (
                item
                for item in tokens[index : index + 3]
                if item.tag in _PERSON_CASE_TAGS
                and item.start in {token.start, token.start + token.len}
            ),
            None,
        )
        if marker is None:
            continue
        before = tokens[:index]
        after = tokens[index:]
        has_connective = any(item.tag == "EC" for item in before)
        has_prior_content = (
            sum(item.tag.startswith(_CONTENT_PREFIXES) for item in before) >= 2
        )
        has_personal_predicate = any(
            item.tag.startswith(_PREDICATE_PREFIXES) for item in after
        )
        if has_connective and has_prior_content and has_personal_predicate:
            return {
                "detected": True,
                "clause_start": token.start,
                "pronoun": token.form,
                "case_tag": marker.tag,
                "classifier_version": CLASSIFIER_VERSION,
                "domain_keyword_rule_count": 0,
            }
    return {
        "detected": False,
        "clause_start": None,
        "pronoun": None,
        "case_tag": None,
        "classifier_version": CLASSIFIER_VERSION,
        "domain_keyword_rule_count": 0,
    }


def classify_answerability_v3_2(query: str) -> dict[str, Any]:
    base = classify_answerability(query)
    structure = analyze_first_person_clause(query)
    if base["label"] == "true" and structure["detected"]:
        return {
            "label": "partial",
            "reason": "official_fact_plus_structural_first_person_clause",
            "base": base,
            "structure": structure,
        }
    return {**base, "base": base, "structure": structure}
