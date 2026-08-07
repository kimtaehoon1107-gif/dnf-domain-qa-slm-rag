# Semantic Requirement Planner provisional evaluation

- Decision: **PENDING_HUMAN_ADJUDICATION**
- Primary population: 95 unique questions
- Claim-ceiling 15 is a non-additive stress slice of the downgraded 32.

## Primary metrics

- micro recall: 57/146 (0.390411)
- micro precision: 57/154 (0.37013)
- all requirements recalled: 32/95 (0.336842)
- over-enumerated questions: 66/95 (0.694737)
- docs false positives: 12
- docs false negatives: 0

## Gates

- micro_requirement_recall_gte_0_90: False
- micro_requirement_precision_gte_0_85: False
- over_enumerated_question_rate_lte_0_10: False
- docs_false_positive_zero: False
- all_requirements_recalled_rate_gte_0_85: False
- human_adjudication_complete: False

## Human adjudication

- planned: 80
- completed: 0
- judge-human agreement: pending
- judge false match / false nonmatch: pending

Automatic matcher metrics are provisional. This report cannot issue a
reranker-pilot GO until the named human review overlay is completed.
