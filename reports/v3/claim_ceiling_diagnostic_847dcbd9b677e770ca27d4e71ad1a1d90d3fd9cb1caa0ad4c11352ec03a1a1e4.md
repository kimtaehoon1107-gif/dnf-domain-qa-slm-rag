# DNF RAG v3 strong-judge claim ceiling diagnostic

## Decision

- decision: **INCONCLUSIVE_API_OR_SCHEMA_FAILURE**
- evaluation role: **adaptive validation ceiling diagnostic only**
- runtime/canonical promotion: **prohibited**
- judge: `dnf-claim-ceiling-qwen2.5-7b:ctx32768` / `high`
- evaluated at: `2026-07-20T01:55:37.5341417+09:00`

## Claim completeness

| condition | complete | recovered baseline failures | support decisions | false support |
|---|---:|---:|---:|---:|
| A actual retrieval | 2/15 | 2/12 | 15/18 | 3 |
| B full common parent | 3/15 | 3/12 | 9/16 | 5 |

Baseline was 3/15. Condition A received only the actual top-10 retrieval chunks. Condition B received every canonical ChunkV3 row from the one parent document that covers all gold evidence groups. Gold data was used only after inference for scoring.

## Cost and latency

- successful calls: 15/30
- estimated API cost: $0.00000000
- mean latency: 13526.402 ms
- median latency: 11906.446 ms
- p95 latency: 22581.365 ms

No answer prose, training, new canary, runtime integration, or canonical promotion was performed.
