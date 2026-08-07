# DNF RAG v3 Revision-conflict Review Contract

## Scope

This supplement measures whether the Verifier can recognize an explicit conflict
between two naturally authored official policy revisions. It does not estimate
the natural frequency of contradiction and is never used as a current-policy
answer source.

Each claim is an exact excerpt from an older account-policy revision. Evidence is
a chunk from a later revision in the same `lineage_id` that discusses the same
rule. The packet stores no expected label. `claim_as_of` identifies the claim's
origin revision, and the evidence effective date is shown beside it. In this
supplement the human task compares the literal propositions across revisions; it
does not decide which revision is currently in force.

## Human labels

- `contradiction`: evidence explicitly gives an incompatible value, duration,
  schedule, or condition for the same rule.
- `support`: evidence entails every material part of the claim.
- `insufficient`: evidence omits the material part or discusses a different rule;
  omission is not contradiction.

For support or contradiction, `decisive_excerpt` must be copied exactly from
`evidence_text`. All six rows require an independent human rationale and may be
flagged for adjudication.

## Isolation

The supplement has `training_allowed=false`, `final_benchmark_eligible=false`,
and `default_current_retrieval_exposure=false`. It may be combined with the
38-row natural evaluation view only for a clearly named supplemental three-class
Verifier measurement. It must not be merged into natural-distribution counts or
default current retrieval.
