# Question-level partial fallback A/B contract

## Purpose

Measure whether the existing question-level `partial` signal can remove mixed-question
over-claims without sending `docs_only` questions through the unstable per-requirement
answer-source classifier. This is a development-only composition of already-frozen
outputs. It changes no runtime or canonical artifact.

## Arms

- **Arm 0**: frozen groundedness-only router backbone.
- **Arm Q**: when the existing question-level classifier returns `partial`, reuse the
  already-frozen conservative partial response (`unified_runtime` for adaptive dev,
  authored-canary first run for the downgraded canary). All other questions are exactly
  Arm 0.

Arm Q does not claim that it can identify a specific non-document requirement. Its
safety contract is coarser: the response must be exact-extractive, must carry the frozen
global partial disclaimer, and must not claim that the personal judgement was resolved.

## Scoring

The frozen human evidence groups represent the document-answerable portion of mixed
questions and are used for scoring only.

- `correct_mixed_partial_chunk`: global partial disclaimer present and every official
  evidence group is cited.
- `correct_mixed_partial_span`: the chunk condition plus gold-span token recall `>= 0.5`
  for every official evidence group (the same frozen completeness threshold used by the
  authored-canary evaluation).
- `mixed_overclaim`: the mixed question is emitted without the partial safety contract.
- `mixed_missing_evidence`: the safety contract is present but one or more official
  evidence groups are missing.

This span score is reported separately from the B1 value-shape diagnostic; neither is
silently substituted for the other.

## Pre-registered strict gate

Arm Q is a strict GO only if all conditions hold:

1. `docs_only` chunk grounding remains `61/69` or better.
2. `docs_only` B1 span-value grounding remains `45/69` or better.
3. mixed over-claim becomes `0/13`.
4. both previously correct mixed-partial questions remain correct (question regression
   `0`).
5. every fallback response is exact-extractive and carries the frozen partial
   disclaimer.
6. reject `11/11` and realtime safe-abstain `2/2` remain unchanged.

Failing the strict gate preserves the artifact as development-only `NO-GO`; aggregate
improvement is not enough to promote it.

## Restrictions

- No new keyword, model call, training, retrieval, reranker, planner, corpus, gold, or
  label change.
- No runtime/canonical promotion and no sealed/frozen-blind access.
- Gold IDs and spans are scoring-only and never enter the fallback decision.

