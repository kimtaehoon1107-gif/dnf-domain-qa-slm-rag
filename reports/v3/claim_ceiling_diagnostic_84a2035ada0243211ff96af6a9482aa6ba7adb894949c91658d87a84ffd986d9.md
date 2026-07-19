# DNF RAG v3 strong-judge claim ceiling diagnostic

## Decision

- decision: **INCONCLUSIVE_API_OR_SCHEMA_FAILURE**
- evaluation role: **adaptive validation ceiling diagnostic only**
- runtime/canonical promotion: **prohibited**
- judge: `qwen2.5:7b-instruct` / `high`
- evaluated at: `2026-07-20T01:49:00.8841207+09:00`

## Claim completeness

| condition | complete | recovered baseline failures | support decisions | false support |
|---|---:|---:|---:|---:|
| A actual retrieval | 1/15 | 1/12 | 8/24 | 0 |
| B full common parent | 2/15 | 2/12 | 8/31 | 8 |

Baseline was 3/15. Condition A received only the actual top-10 retrieval chunks. Condition B received every canonical ChunkV3 row from the one parent document that covers all gold evidence groups. Gold data was used only after inference for scoring.

## Cost and latency

- successful calls: 23/30
- estimated API cost: $0.00000000
- mean latency: 9038.991 ms
- median latency: 8282.711 ms
- p95 latency: 18372.199 ms

No answer prose, training, new canary, runtime integration, or canonical promotion was performed.
