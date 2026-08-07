# DNF RAG v3 Evidence Reranker A/B

## Decision

- A/B integrity: **GO**
- Adaptive reranker development candidate: **GO**
- Production Evidence Selector: **NO-GO**
- Generator entry: **NO-GO**
- Final benchmark: **NO-GO**

## A/B

| arm | all-groups hit | group recall micro | annotated precision | noise | avg selected |
|---|---:|---:|---:|---:|---:|
| baseline | 0.981818 | 0.983051 | 0.129754 | 0.870246 | 8.127273 |
| reranker top-3 | 0.945455 | 0.932203 | 0.333333 | 0.666667 | 3.0 |
| reranker top-8 | 0.981818 | 0.983051 | 0.131818 | 0.868182 | 8.0 |
| adaptive 3/8 | 0.981818 | 0.983051 | 0.29 | 0.71 | 3.636364 |

Adaptive selection uses top-8 only for explicit multi-evidence markers or a reranker top score below 0.1; otherwise it uses top-3. This rule was selected on the development set and has no independent holdout evidence.

## Observed scoring cost

- pairs: 550
- inference seconds: 19.282104
- pairs/second: 28.523859
- peak CUDA bytes: 2374138368

This is batched evaluation throughput, not online p50/p95 request latency.

## Limits

The BGE model is a relevance reranker, not an entailment or contradiction verifier. The adaptive arm preserves development recall and improves sparse-annotation precision, but its precision remains below the production gate.

## Artifacts

- results: `data/v3/evidence/evidence_reranker_ab_results_49d4e5b75339582c0aad9f6b35bc9d9cb5aa63a671c55ec46de5c023bb04a56f.jsonl`
- manifest: `data/v3/evidence/evidence_reranker_ab_manifest_d0f1a2e89fd98da965af1b8a48687a20b777b60ec24082f003ea73ca6039a1f2.json`
