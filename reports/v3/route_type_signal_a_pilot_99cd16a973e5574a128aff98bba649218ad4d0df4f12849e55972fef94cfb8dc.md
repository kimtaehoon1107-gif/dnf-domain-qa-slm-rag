# DNF RAG v3 route-type Signal A pilot

- decision: **NO-GO**
- baseline route exact: {'successes': 18, 'total': 32, 'rate': 0.5625}
- Signal A canary route exact: {'successes': 10, 'total': 32, 'rate': 0.3125}
- Signal A decomposition precision: {'successes': 8, 'total': 25, 'rate': 0.32}
- Signal A decomposition recall: {'successes': 8, 'total': 9, 'rate': 0.88888889}
- dev decomposition: {'true_positive': 4, 'false_positive': 29, 'false_negative': 0, 'precision': {'successes': 4, 'total': 33, 'rate': 0.12121212}, 'recall': {'successes': 4, 'total': 4, 'rate': 1.0}}
- latency: {'sample_count': 51, 'warm_cache': True, 'rounds_per_question': 1, 'median_ms': 0.3029, 'p95_ms': 0.6769, 'maximum_ms': 0.7949, 'hard_gate': False, 'observation_is_content_addressed_but_not_bit_reproducible': True}
- store expansion implemented: no
- new dev-fit keyword rules: 0
- individual failure cases inspected: no
