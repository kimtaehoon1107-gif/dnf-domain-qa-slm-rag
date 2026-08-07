# DNF RAG v3 behavioral decomposition coverage pilot

- decision: **NO-GO**
- selected threshold: 1.0
- canary route exact: {'successes': 18, 'total': 32, 'rate': 0.5625, 'wilson_95_percent': [0.39325591, 0.71834669]}
- canary decomposition: {'true_positive': 0, 'false_positive': 0, 'false_negative': 9, 'precision': {'successes': 0, 'total': 0, 'rate': 0.0, 'wilson_95_percent': [0.0, 0.0]}, 'recall': {'successes': 0, 'total': 9, 'rate': 0.0, 'wilson_95_percent': [0.0, 0.29914505]}}
- dev overdecomposition: 0
- dev multi recall: 0/4
- latency: {'canary_32': {'single_search_and_plan': {'count': 32, 'median_ms': 37.6558, 'p95_ms': 66.3762, 'max_ms': 1952.6021}, 'signal_a_candidate_dual_search_filter': {'count': 25, 'median_ms': 35.5521, 'p95_ms': 66.3767, 'max_ms': 1952.6032}, 'all_rows_observed_total': {'count': 32, 'median_ms': 37.6561, 'p95_ms': 66.3767, 'max_ms': 1952.6032}, 'child_embedding_batch': {'child_query_count': 0, 'candidate_count_with_supported_decomposition': 0, 'batch_embedding_total_ms': 0.0, 'batch_embedding_amortized_per_candidate_ms': 0.0, 'bit_reproducible': False}, 'latency_is_observational_not_bit_reproducible': True}, 'development_63': {'single_search_and_plan': {'count': 63, 'median_ms': 35.3681, 'p95_ms': 52.1794, 'max_ms': 77.1878}, 'signal_a_candidate_dual_search_filter': {'count': 33, 'median_ms': 39.9244, 'p95_ms': 3828.88575, 'max_ms': 3881.21875}, 'all_rows_observed_total': {'count': 63, 'median_ms': 35.3686, 'p95_ms': 3627.74635, 'max_ms': 3881.21875}, 'child_embedding_batch': {'child_query_count': 8, 'candidate_count_with_supported_decomposition': 4, 'batch_embedding_total_ms': 13557.0362, 'batch_embedding_amortized_per_candidate_ms': 3389.25905, 'bit_reproducible': False}, 'latency_is_observational_not_bit_reproducible': True}}
- expected/gold identifiers used by runtime coverage: no
- new keyword rules: 0
- new store expansion: no
