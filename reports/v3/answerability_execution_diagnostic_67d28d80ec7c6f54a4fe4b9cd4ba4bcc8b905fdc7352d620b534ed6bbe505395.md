# Answerability execution diagnostic

- decision: **DIAGNOSTIC_COMPLETE_MECHANICAL_REJECT_PARTIAL_SEMANTIC_REALTIME_REQUIRED**
- population: docs 82 / reject 11 / realtime 2
- current front reject exact: 6/11
- current front realtime exact: 0/2
- post-search candidate_count < 2 reject: 9/11; answerable false reject 2/82
- realtime at zero answerable FP: 0/2
- selected-parent trigger: cross 0/2; same preserved 7/7
- best threshold without same-parent regression: 0.005 -> cross 1/2, same 7/7
- existing downstream cross-parent recovery: 0/2
- planner invocations gated/always-on: 87/95 (+8)

Conclusion: post-search evidence availability can safely catch most reject cases, but current generic mechanical signals cannot safely identify realtime/personal requests. Parent membership is also insufficient as semantic requirement coverage.

No routing, answerability, planner, retrieval, decomposition, reranker, assembler, label, or runtime artifact was changed or promoted.
