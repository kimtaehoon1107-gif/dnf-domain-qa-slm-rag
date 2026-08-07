# DNF RAG v3 Account-policy Temporal Policy

## Decision

- temporal overlay: **GO**
- current policy retrieval filter: **GO**
- historical mode: **GO**
- comparison mode: **GO**
- six-row revision-conflict human review: **CANCELLED**
- Generator / final benchmark: **NO-GO**

## Coverage

- policy revisions: 51
- current revision: `2026-03-15`
- historical boundary cases: 51
- historical resolution errors: 0
- comparison pair cases: 50
- comparison pair errors: 0
- current-mode regression questions: 6
- empty current-mode results: 0
- superseded/current-policy leaks: 0
- old claim-origin leaks: 0

The original DocumentV3 and ChunkV3 artifacts remain immutable. The temporal
overlay computes closed validity intervals, current-revision state,
`superseded_by`, and `last_verified_at`. Allowed parent document IDs are applied
before BM25 and dense ranking. Superseded revisions remain available only through
explicit historical or comparison modes.

The cancelled six-row packet is preserved for provenance but is not a current-QA
evaluation set and requires no further human labeling.
