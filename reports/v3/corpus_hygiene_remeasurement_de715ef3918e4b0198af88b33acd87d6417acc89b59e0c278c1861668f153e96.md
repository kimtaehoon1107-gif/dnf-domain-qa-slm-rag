# DNF RAG v3 corpus hygiene remeasurement

- Decision: **NO_GO** (development only; no promotion)
- Retrieval-only rows changed: 560/3599
- Grounded answers: 73/82 -> 72/82
- False full answers: 9/82 -> 10/82
- New false full answers: 1
- Exact spans: 396/396
- Federated temporal violations: 0
- Legacy canary temporal/realtime (pre-existing): 4/5 -> 4/5

The entire development baseline was replayed because changing retrieval_text required new BM25 and BGE-M3 indexes. Dirty artifacts remain preserved, and this report does not promote the clean corpus.
