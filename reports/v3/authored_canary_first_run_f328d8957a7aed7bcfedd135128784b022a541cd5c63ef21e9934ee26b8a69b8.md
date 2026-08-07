# DNF RAG v3 authored canary first sealed run

- decision: **NO-GO**
- evaluation role: authored canary, independently reviewed; not an independent holdout
- failure details: sealed and not inspected

## Preregistered gates

- retrieval_all_required_at_least_0_90: **FAIL**
- selected_evidence_group_hit_at_least_0_85: **FAIL**
- cited_evidence_group_hit_at_least_0_85: **FAIL**
- claim_completeness_at_least_0_90: **FAIL**
- strict_regression_zero: **FAIL**
- strict_improvement_at_least_one: **FAIL**
- minimum_source_retrieval_at_least_0_66: **FAIL**
- zero_hit_source_none: **PASS**
- temporal_revision_violation_zero: **FAIL**
- false_realtime_evidence_exposure_zero: **FAIL**
- partial_disclaimer_5_of_5: **FAIL**

The sample contains only four authored cases per source; Wilson intervals and numerators are in the JSON report.
