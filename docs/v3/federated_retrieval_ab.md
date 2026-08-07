# Federated retrieval A/B contract

## Role

This is a development-only A/B that tests whether removing the frozen hard
source filter recovers the seven retrieval-bound false-full cases. It does not
promote a router, retriever, assembler, or runtime configuration.

## Frozen inputs

- The 95-question answerability population, human evidence groups, semantic
  requirement enumeration, chunk-diverse assembler threshold/K, and the
  3,599-chunk BM25+BGE-M3 indexes remain unchanged.
- Existing requirement-query embeddings are reused. The planner and embedding
  model are not rerun.
- Gold chunk, parent, and source identifiers are available only after retrieval
  and assembly for scoring and failure attribution.

## Arms

- Baseline: the frozen hard-route backbone (`grounded=73/82`,
  `false-full=9/82`).
- `federated_quota`: execute every frozen requirement query against each
  official source with the hard source choice removed, keep up to three hygienic
  hits per source, and combine source-local ranks with RRF. Raw scores from
  different source lists are never merged.
- `federated_global`: execute the same query once against the integrated index
  without a source filter and keep the global hygienic top 10.

Both new variants feed the unchanged bge-reranker-v2-m3 segment scorer and the
unchanged chunk-diverse exact-extractive assembler.

## Hygiene

- Current/default searches require `default_exposure=true`, `status=current`,
  `review_required=false`, and the existing `valid_from`/`valid_to` as-of check.
- Historical/preview controls retain the already frozen temporal policy; no new
  temporal intent rule is introduced.
- The existing account-policy temporal overlay restricts policy candidates to
  the resolved revision set. When the frozen route did not identify a policy
  request, only the current policy revision is eligible.
- Candidate hygiene deduplicates document `content_hash`, caps a parent at two
  chunks, and applies the source quota before RRF.

## Failure attribution

Every unrecovered target and every new false-full receives exactly one earliest
stage label:

1. `ENUM_MISS`
2. `SOURCE_SCOPE_MISS`
3. `RETRIEVAL_MISS`
4. `ATTRIBUTE_MISMATCH`
5. `ASSEMBLY_MISS`

## Hard gates

A variant can receive an adoption recommendation only if it recovers at least
one of the seven retrieval-bound false-full cases as grounded while preserving:

- grounded answers at least `73/82`;
- new false-full `0`;
- contextual temporal/revision/preview/expired exposure violations `0`;
- exact substring validity `100%`;
- same-parent controls `7/7`;
- reject controls `11/11`;
- realtime safe-abstain controls `2/2`;
- no increase in mean selected spans or the non-acceptable citation proxy.

The sealed benchmark, frozen blind, training, reindexing, planner changes,
assembler co-tuning, soft routing, and runtime promotion are outside scope.
