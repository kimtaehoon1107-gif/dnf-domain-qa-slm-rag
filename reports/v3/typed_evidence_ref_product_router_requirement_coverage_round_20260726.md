# Product router + requirement evidence coverage full-64 diagnostic

## Evaluation role

This is an adaptive diagnostic over the already inspected 64-case set. It
does not replace the official sealed one-shot result (`37/64`) and must not be
presented as a new generalization score.

```text
model: qwen3-8b:ctx8192
retrieval: current SimpleDomainRAG product router
prompt selection: per-requirement evidence reservation
generation: native Ollama, think=false, num_ctx=8192, num_predict=512
new retrieval executions: 64
new model calls: 64
```

## Changes

The evidence reducer now:

- scores public subject terms per requirement;
- uses a small bilingual relation-token lexicon only for prompt ranking;
- reserves up to two high-scoring units from the best candidate for every
  requirement before shared-budget selection;
- preserves exact source coordinates and the existing 12,000-character
  fail-closed limit.

No required value, acceptable evidence, or gold field is used by the prompt
selector.

A reproducible retrieval-only runner was added:

```text
src/v3/build_product_router_generalization_64_diagnostic.py
```

## Retrieval result

| Metric | Stored candidate pools | Product router |
|---|---:|---:|
| Strict frozen-gold candidate coverage | 54/64 | **62/64** |
| Regressed covered slots | — | **0** |
| Strict uncovered slots | 10 | **8, 41** |

Slots 8 and 41 contain direct official equivalent evidence and are frozen-gold
acceptable-evidence omissions. Therefore the product-meaning candidate
coverage is consistent with `64/64`, but that human-reviewed interpretation
is adaptive and not a new held-out result.

## End-to-end result

| Metric | Stored-pool reduced run | Requirement coverage + product router |
|---|---:|---:|
| Gold-value complete | 44/64 | **50/64 (78.1%)** |
| Approved direct evidence | 34/64 | **44/64** |
| Strict candidate coverage | 54/64 | **62/64** |
| Generation errors | 0 | **0** |
| All citation slices exact | yes | **yes** |
| Mean latency | 5.41s | **9.07s** |
| p50 latency | 4.96s | **8.08s** |
| p95 latency | 6.88s | **13.64s** |
| Input tokens | 111,191 | **127,429** |

Automatic outcomes:

```text
correct: 50
incorrect: 10
no_response: 4
```

The per-requirement coverage mechanism restored the previously dropped
evidence in slots 4, 25, 38, and 43. In the stored-pool full run it reached
`47/64`, direct evidence `38/64`, and generation errors `0`.

The final product-router run recovered additional missing-source cases,
including slots 3, 11, 13, and 23.

## Safety interpretation

The automatic unsupported false-full flag is slot 31. Its answer (`preset
limit 10`) is directly supported by an official Seria Shop row, so this is a
frozen-gold omission rather than an actual unsupported-answer false-full.

```text
automatic frozen-gold unsupported false-full: 1
source-reviewed actual unsupported false-full: 0
```

That narrow metric must not be confused with overall semantic safety. Eight
failed cases still exposed an incorrect or incomplete supported value:

```text
1, 6, 30, 47, 51, 60, 61, 63
```

Examples:

- Slot 1 selected the `2026-03-15` mobile-policy date instead of the
  `2026-05-28` Sera terms date.
- Slot 6 selected the current `2026-03-15` policy date instead of the
  historical `2025-11-01` announced change date.
- Slots 60, 61, and 63 selected a sibling special-item price
  (`2,000만 골드`) instead of the monthly item's shop price
  (`4,000만 골드`).

Therefore `actual unsupported false-full 0` is not a production-safety claim.

## Remaining failures

The 14 failed cases separate cleanly:

```text
generator/value or evidence selection: 10
verifier overreject:                 4
true final-answer retrieval failure: 0 confirmed
```

The two strict retrieval misses, slots 8 and 41, were answered correctly from
equivalent official evidence.

Repeated general failure groups:

- policy subject/revision identity: slots 1 and 6;
- multi-value completion: slots 12 and 20;
- sibling table/attribute binding: slots 51, 60, 61, and 63;
- boolean/relation overreject: slots 2 and 34;
- temporal/subject overreject: slots 5 and 62.

## Tests

```text
focused: 34 passed, 7 subtests passed
v3: 702 passed, 54 subtests passed
legacy: 72 passed
git diff --check: passed
```

## Verdict

```text
product-router retrieval recall: diagnostic GO
per-requirement evidence preservation: diagnostic GO
combined adaptive score: best observed, 50/64
production/generalization promotion: NO-GO
official sealed score: unchanged at 37/64
```

The combined arm is materially better, but it still has wrong supported values
and two end-to-end regressions against the stored-pool `47/64` run (slots 61
and 63). The next general improvement should bind monthly-item
subject/attribute/value rows before generation and enforce policy
subject/revision identity. It should not add more slot-specific rules to this
64-case set.

## Artifacts

```text
router candidate pools:
outputs/v3/diagnostics/product_router_generalization_64_candidate_pools_20260726.jsonl
sha256:
31427d24a83a23f74adbd276204166f74514e0fc77931cfff5c7660d478229a5

router summary:
reports/v3/product_router_generalization_64_candidate_pools_20260726.json
sha256:
a571f1bead09efd0f16cd0097b2f5f34c9da359059388fce94d2685bb654e8a5

end-to-end cases:
outputs/v3/diagnostics/typed_evidence_ref_product_router_full64_20260726.jsonl
sha256:
515ca70fa0893898faafd189493a0a0c61bbbfa8a35b9e8444681ee10d31ab69

end-to-end summary:
reports/v3/typed_evidence_ref_product_router_full64_20260726.json
sha256:
5390fc05871ac9f993fa5ea2f0a8d817de16a235c042528d292213f11627d98b
```
