# Question-level partial fallback A/B (development only)

Arm Q composes already-frozen partial outputs only when the existing question-level
classifier returns `partial`. No model call, runtime change, or promotion occurred.

## Result

Decision: **DEVELOPMENT_NO_GO** (strict gate passed: `False`).

| Metric | Arm 0 | Arm Q |
|---|---:|---:|
| docs_only chunk grounded | 61/69 | 61/69 |
| docs_only span-value grounded | 45/69 | 45/69 |
| mixed correct partial (chunk) | 2/13 | 10/13 |
| mixed correct partial (span) | 2/13 | 7/13 |
| mixed overclaim | 10/13 | 0/13 |
| mixed missing evidence | 1/13 | 3/13 |

## Conversion and regression

- baseline overclaims: 10
- converted to correct partial: 9
- converted to honest partial with missing evidence: 1
- unresolved overclaims: 0
- previously correct mixed-question regressions: 1
- regression case IDs: `['authored_canary_sha256_5edb1f1854d2a8b2d7e71e485e0cc9d0c89bb55a1187c7239b6684c758fe265b']`

## Question-level signal

`{'docs_only': {'true': 69}, 'docs_only_official_fact_without_current_evidence': {'true': 3}, 'mixed': {'partial': 12, 'true': 1}, 'non_docs_only': {'false': 8, 'true': 2}}`

## Strict gate

- docs_chunk_nonregression: `True`
- docs_span_value_nonregression: `True`
- mixed_overclaim_zero: `True`
- existing_correct_mixed_question_regression_zero: `False`
- fallback_exact_extractive_all: `True`
- fallback_partial_disclaimer_all: `True`
- reject_unchanged_11_of_11: `True`
- realtime_unchanged_2_of_2: `True`

The fallback is not promoted. Aggregate safety improves, but any strict
question regression keeps this arm development-only NO-GO.
