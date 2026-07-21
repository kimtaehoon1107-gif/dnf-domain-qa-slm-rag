# DNF RAG v3 BM25 vs Dense Retrieval Dev Evaluation

## Decision

- Evaluation integrity: **GO**
- Hybrid experiment entry: **GO**
- Hybrid promotion: **NOT_RUN**
- Final benchmark: **NO-GO**

## Overall metrics (55 answerable/partial rows)

| system | MRR | hit@1 | hit@5 | hit@10 | hit@20 | group recall@10 | all groups@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 0.6271 | 0.4545 | 0.8545 | 0.9091 | 0.9455 | 0.9153 | 0.9091 |
| dense | 0.6464 | 0.4727 | 0.8545 | 0.9455 | 0.9455 | 0.9322 | 0.9273 |

## Complementarity at 10

- both: 48
- BM25 only: 2
- dense only: 4
- neither: 1

## Artifacts

- results: `data/v3/retrieval/retrieval_ab_results_c096c114dab9d5fb08e29f9dfc088ee64f908564c7f572a6d6d8770621d8454e.jsonl`
- results SHA-256: `c096c114dab9d5fb08e29f9dfc088ee64f908564c7f572a6d6d8770621d8454e`
- query embeddings: `data/v3/retrieval/retrieval_dev_query_embeddings_323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32`
- query embeddings SHA-256: `323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442`
- manifest: `data/v3/retrieval/retrieval_ab_manifest_2e8dd6b365c2dc1c2bbb0b8463fdded53bbee00e910b89c542d84af89684de28.json`
- manifest SHA-256: `2e8dd6b365c2dc1c2bbb0b8463fdded53bbee00e910b89c542d84af89684de28`

The 8 unanswerable rows are retained for later answerability evaluation but are excluded from gold retrieval metrics. No hybrid weights, Router, generation, training, or frozen blind benchmark were evaluated.
