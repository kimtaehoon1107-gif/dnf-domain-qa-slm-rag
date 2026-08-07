# Router, generation protocol, and identity verifier round — 2026-07-26

## Evaluation role

This round is an adaptive diagnostic based on already inspected generalization-64
failures. It does not replace the sealed one-shot headline result (`37/64`) and
must not be presented as a new generalization score.

## Changes

### Product retrieval path

- Kept the frozen canonical router unchanged.
- Added high-confidence source refinement only to `simple_domain_rag`.
- A single routed source now executes retrieval instead of stopping at
  `decompose` or `clarify`.
- Explicit source routes restrict the pool to that source.
- One pre-router reranked candidate may be appended as a bounded fallback.
- Inferred routes without an explicit signal retain the previous all-source
  baseline.

Retrieval-only replay over the 64 reviewed questions:

| Metric | Previous stored candidates | Adaptive router diagnostic |
|---|---:|---:|
| All requirements have an acceptable candidate | 54/64 | 62/64 |
| Newly covered slots | — | 3, 6, 11, 13, 23, 47, 60, 62 |
| Regressed slots | — | 0 |
| Still uncovered | 10 slots | 8, 41 |

The seven misses identified in the input analysis (3, 6, 11, 13, 23, 60, 62)
all had an acceptable chunk at reranker rank 1. Slot 42 retained its previous
acceptable candidate at bounded fallback rank 6.

### Local Qwen generation protocol

- Local Ollama calls use the native `/api/chat` API.
- `think=false`, `num_ctx=8192`, and `num_predict=512` are explicit.
- Raw content, reasoning content, finish reason, actual token usage, latency,
  request size, and per-requirement schema errors are recorded.
- One invalid requirement is downgraded to `unsupported` without discarding
  valid siblings.
- Requests over 12,000 characters fail closed before a model call.

Targeted adaptive smoke with `qwen3-8b:ctx8192`:

| Slot | Result |
|---|---|
| 21 | Recovered: 40% / 10%, 70 output tokens, no reasoning content |
| 40 | Semantically correct official FAQ answer; automatic gold lacks that equivalent evidence |
| 41 | Safely abstained before HTTP call (`15936 > 12000` request characters) |

The tested local calls no longer consumed 4,000 output tokens in hidden
reasoning. Slot 41 is not fixed: requirement-aware evidence reduction is still
needed to answer it.

### Month/year identity verifier

- When the requested subject explicitly names a year or month and the selected
  document title explicitly names a different year or month, the requirement
  is rejected with `subject_identity_conflict`.
- Matching identities and evidence without an explicit conflicting identity
  remain eligible.

Verifier-only replay (no retrieval or model calls):

- Slot 62: blocked a June question answered from an August date.
- Slot 63: blocked the August item name selected from a July document.
- Source-reviewed actual false-full: `1 -> 0`.
- Automatic frozen-gold false-full flags: `3 -> 2`; the remaining slots 31 and
  47 are known acceptable-evidence omissions, not confirmed semantic errors.
- The adaptive `45/64` value count is unchanged and remains a non-promotable
  diagnostic.

## Verification

- Focused tests: 48 passed, 7 subtests passed.
- Full v3 tests: 696 passed, 54 subtests passed.
- Legacy tests: 72 passed.
- `git diff --check`: passed.
- Frozen canonical router source was not changed; no frozen artifact SHA was
  rewritten.

## Decision

- Product-path source routing: diagnostic GO, not a generalization promotion.
- Native Ollama protocol: GO for bounded, observable output; input reduction
  remains open.
- Month/year identity hard reject: verifier replay GO.
- Overall production promotion: NO-GO until an untouched evaluation set
  validates the combined pipeline.

Next work should target the two remaining retrieval misses (8 and 41) and
requirement-aware evidence-unit reduction. Relation-ontology fail-closed should
wait until the relation registry is complete; applying it now would overreject
many unregistered requirements.
