# v3.2 Arm 5 — policy clause children

## Suitability

Replacing the 607 canonical policy chunks would invalidate offsets and gold IDs. The
safe experiment is additive: reconstruct each policy revision from exact overlapping
chunk offsets, then add numbered-clause, legacy-paragraph, and table-row children.

## Contract

- Canonical policy chunks remain unchanged and searchable.
- Every child is an exact slice of the reconstructed parent revision.
- A child records parent document ID, child kind, clause/row identifier, and exact start/end offsets.
- Revision selectors, table-of-contents headings, and navigation-only lines are not emitted as legacy paragraphs.
- Current and superseded revisions remain separate documents; temporal filtering is not changed by this arm.
- Parent top-10 is preserved. Child top-10 is searched independently and late-unioned;
  children never compete with or evict canonical parent candidates in this arm.
- The A/B indexes are in-memory and development-only. No index or runtime is promoted.

## Gate

At policy top-10, the additive arm must improve all-required evidence-group recall with
zero strict regression. Reconstruction conflicts and exact-slice failures must be zero;
canonical documents, chunks, and gold IDs must remain unchanged.
