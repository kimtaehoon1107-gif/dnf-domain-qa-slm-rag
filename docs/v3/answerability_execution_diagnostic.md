# Answerability execution diagnostic contract

## Purpose

This is an offline, development-only measurement. It does not change or
promote the router, answerability gate, planner, retrieval, decomposition,
reranker, or assembler. The frozen 63-question adaptive development set and
the downgraded 32-question authored canary are the only evaluation inputs.

The diagnostic asks three separate questions:

1. Can `reject` be detected after retrieval from generic evidence-availability
   and score signals without a classifier?
2. Can `realtime_api` be distinguished from document-answerable questions by
   the same non-lexical signals?
3. Does a mechanical requirement-to-parent coverage trigger recover the two
   audited cross-parent cases while preserving the seven audited same-parent
   cases?

`reject` and `realtime_api` use different denominators and are never merged.

## Frozen labels and signals

The 95-row independent answerability ground truth defines three target groups:

- `answerable_docs`: `true` and `partial` questions;
- `reject`: false questions, except canary rows already labelled
  `realtime_api` in the frozen stage attribution;
- `realtime_api`: the two frozen realtime canary controls.

Only generic numeric signals already present in the frozen requirement
reranker artifacts may be measured: candidate count, requirement count,
distinct top chunks, per-requirement top score, and top-to-second margin. The
threshold sweep is aggregate diagnostics only. It is not a runtime rule and
must not inspect or emit question text, gold answer text, or evidence spans.

The planner's existing categorical `value_type` is also measured as a
structural signal. `subject`, `relation`, and `subject_group` are free text;
matching their content would recreate a lexical/semantic classifier and is
therefore not treated as a mechanical rule. The diagnostic records whether the
planner schema already contains an explicit answer-source, freshness, or
personal-state field.

The current lexical front gate is measured as a retained baseline. The prior
fixed-model answerability A/B report is used only to quantify the known
front-gate false-negative risk; it is not rerun or promoted.

## Parent coverage counterfactual

For each requirement, candidate chunk IDs are mapped to their frozen parent
document IDs. A question is mechanically single-parent-coverable only when the
intersection of the per-requirement parent sets is non-empty. This is a proxy:
parent membership does not prove that a candidate semantically supports the
requirement.

The report must show selected-candidate coverage and an aggregate score
threshold grid. A threshold is not acceptable merely because it recovers a
cross-parent case if it breaks a same-parent case. Existing behavioral
decomposition results are reported separately so that a trigger is not
mistaken for successful downstream decomposition.

## Cost accounting

Always-on versus answerability-gated planner cost is reported as invocation
count and a linear estimate from the already-frozen planner wall clock. The
estimate is not a new latency benchmark and is not bit reproducible. The much
cheaper Signal A analyzer latency is context only and is not substituted for
semantic planner latency.

## Scope

No keyword or field list may be added. No classifier is trained or promoted.
No model, embedding, retrieval, or new canary run is allowed. The diagnostic
may conclude that a semantic or typed answer-source decision is unavoidable,
but implementing it requires a later authorized cycle. Frozen blind, v2,
`AGENTS.md`, the v3 handoff, `src/outputs`, and raw snapshots are out of scope.
