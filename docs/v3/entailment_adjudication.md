# DNF RAG v3 Natural Entailment Adjudication Contract

## Scope

The completed 40-row primary review remains immutable. Adjudication is a second,
separate human pass over rows whose primary decision explicitly set
`needs_adjudication=true`, plus rows whose saved human rationale or decisive
excerpt has clear question-mark encoding corruption. It does not reopen other
rows and does not assign labels automatically.

## Artifacts

- The primary draft is copied byte-for-byte to a content-addressed checkpoint.
- The adjudication packet contains only pending or text-repair rows and preserves the primary
  label, rationale, decisive excerpt, reviewer, and timestamp under
  `primary_review`.
- `adjudication_reasons` records whether each row was selected for a primary
  ambiguity, saved-text corruption, or both.
- Adjudication review fields start empty and are written only to a separate mutable
  draft under `outputs/v3/annotation`.
- The original primary draft is never modified by this workflow.

The reviewer UI does not load the sampling ledger or model predictions. Omission
remains `insufficient`, not `contradiction`. A contradiction must explicitly
conflict with a material part of the claim for its stated time scope.

## Merge gate

Every adjudication row must have a valid human label, rationale, reviewer ID,
timezone-bearing timestamp, no remaining adjudication flag, and an exact evidence
excerpt for `support` or `contradiction`. The resolved rows may then replace only
the review fields of their linked primary rows.

The merged 40-row set is not scoring-ready unless all original natural-review
gates pass. In particular, a missing contradiction class must not be repaired by
relabeling an insufficient row. A separate naturally mined contradiction
supplement requires its own blind human review.
