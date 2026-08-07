# v3.2 table sidecar top-5/10/20 comparison

This diagnostic compares the frozen parent candidate pool with an additive table-row
sidecar at fused depths 5, 10, and 20. Parent candidates are always retained, so the
experiment measures incremental evidence-group recall without allowing row children
to evict canonical candidates.

The frozen BGE-M3 table embeddings and BM25 sidecar are reused. Only requirement
query embeddings are computed; there is no training, re-indexing, gold-aware search,
or runtime promotion. Gold chunk IDs are used after retrieval for mechanical scoring.

This is a candidate-recall depth diagnostic, not a final answer-quality benchmark.
Any chosen depth still requires a sealed answer-level evaluation before promotion.
