# DNF RAG v3 Entailment Claim Repair Contract

## Purpose

Human adjudication can identify a frozen claim that is not independently usable,
mixes facts not asked by the question, or otherwise needs correction. The frozen
claim and its completed human review are never edited in place. A correction is a
new content-addressed revision and every affected claim–evidence relationship is
reviewed again.

## Issue markers

- A rationale beginning with `[CLAIM 오류]` creates a claim repair issue.
- A rationale beginning with `[EVIDENCE 오류]` creates a provenance/parser issue.
- A checked adjudication flag without either marker remains an unresolved human
  issue.

Issue extraction happens only after the primary and adjudication reviews finish.
The hidden sampling ledger may then be opened only to attach `dev_id` and sampling
stratum provenance; it cannot alter the human labels.

## Claim correction

The repair set contains two unique claims across five reviewed relationships.
The initial packet contained four relationships; a `dev_id` coverage audit found
and added one same-claim hard-candidate relationship as a one-row follow-up.
Proposed text is derived only from the human-selected official evidence:

- the exact question-scoped line for the island background change;
- the human decisive excerpt that includes the named reporting contacts for the
  phishing warning.

The proposal is not a gold label. Review fields start empty, and a human must
relabel every corrected claim–evidence relationship. The original claim, prior
label, and rationale remain visible as provenance.

Coverage is checked by `dev_id`, not only by rows that carried the original human
issue marker. Every sampled relationship for a corrected dev claim must use the
new claim revision and receive a fresh human label. A missing relationship blocks
resolved-view promotion and is added as a separate follow-up packet; completed
repair reviews are never repeated or overwritten.

## Evidence errors

Rows marked `[EVIDENCE 오류]` are preserved but excluded from scoring. They cannot
be repaired by changing an NLI label. Their parent/body provenance must be rebuilt
after parser and chunk-boundary correction, followed by a fresh review item.

No artifact in this workflow is allowed for training or final benchmark claims.
