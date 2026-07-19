# DNF RAG v3 BM25 vs Dense Retrieval Dev Evaluation

## Decision

- Evaluation integrity: **GO**
- Hybrid experiment entry: **GO**
- Hybrid promotion: **NOT_RUN**
- Final benchmark: **NO-GO**

## Overall metrics (55 answerable/partial rows)

| system | MRR | hit@1 | hit@5 | hit@10 | hit@20 | group recall@10 | all groups@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 0.6149 | 0.4364 | 0.8364 | 0.8727 | 0.9273 | 0.8475 | 0.8545 |
| dense | 0.6446 | 0.4727 | 0.8364 | 0.9455 | 0.9455 | 0.9322 | 0.9273 |

## Complementarity at 10

- both: 46
- BM25 only: 2
- dense only: 6
- neither: 1

## Artifacts

- results: `data/v3/retrieval/retrieval_ab_results_c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620.jsonl`
- results SHA-256: `c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620`
- query embeddings: `data/v3/retrieval/retrieval_dev_query_embeddings_323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32`
- query embeddings SHA-256: `323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442`
- manifest: `data/v3/retrieval/retrieval_ab_manifest_5d96c252d65aed8632f2a72581641150fe04f04903f283c97cfae29686abc0ca.json`
- manifest SHA-256: `5d96c252d65aed8632f2a72581641150fe04f04903f283c97cfae29686abc0ca`

The 8 unanswerable rows are retained for later answerability evaluation but are excluded from gold retrieval metrics. No hybrid weights, Router, generation, training, or frozen blind benchmark were evaluated.
