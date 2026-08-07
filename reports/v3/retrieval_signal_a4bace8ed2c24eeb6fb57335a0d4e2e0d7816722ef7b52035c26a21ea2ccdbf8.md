# DNF RAG v3 Structured Parent-Lead Signal

## Decision

- Experiment integrity: **GO**
- Retrieval candidate promotion: **GO**
- Final benchmark: **NO-GO**

## Overall

| system | MRR | hit@10 | all groups@10 | group recall@10 |
|---|---:|---:|---:|---:|
| dense | 0.6446 | 0.9455 | 0.9273 | 0.9322 |
| best fixed hybrid | 0.7085 | 0.9636 | 0.9455 | 0.9492 |
| signal candidate | 0.7093 | 0.9818 | 0.9818 | 0.9831 |

## Promotion gates

- PASS: `hit_at_10_improves_best_hybrid`
- PASS: `all_groups_at_10_improves_best_hybrid`
- PASS: `group_recall_at_10_improves_best_hybrid`
- PASS: `mrr_not_regressed_from_best_hybrid`
- PASS: `source_regression_from_best_hybrid_0`
- PASS: `worst_source_improves_best_hybrid`
- PASS: `hit_at_10_above_dense`
- PASS: `all_groups_at_10_above_dense`

Structured-field queries: 7
Injected lead chunks: 7
Remaining human-review cases: 1

The candidate is promoted only for v3 development retrieval. Final benchmark eligibility remains blocked until the remaining annotation review and a separately frozen benchmark are completed.

## Artifacts

- results: `data/v3/retrieval/retrieval_signal_results_c8f5c902f237ef70b4add45ee63815bd1cdafeb84741c86c1bd634b1df02127e.jsonl`
- manifest: `data/v3/retrieval/retrieval_signal_manifest_65e0a1e210aae40c2a610e69a1cf79f90ef79e8b39bd9e971c2e9029fc9358ca.json`
