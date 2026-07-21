# Router backbone mixed-answerability metrics (v3.2)

Development-only re-scoring of the frozen 95 questions on two axes. No runtime, gold,
or frozen report changed. Legacy collapsed metrics are preserved as `legacy_proxy`.

## Legacy proxy (collapsed answerable_docs = 82, unchanged)

| Metric | Value |
|---|---:|
| Grounded | 73/82 |
| False full | 9/82 |
| False partial | 2/82 |
| Honest partial | 0/82 |

## Two-axis corrected view

Profile counts: {'docs_only': 69, 'docs_only_official_fact_without_current_evidence': 3, 'mixed': 13, 'non_docs_only': 10}.

### docs_only (69)

| Metric | Value |
|---|---:|
| Grounded (chunk) | 61/69 |
| Grounded (span-value strict) | 45/69 |
| False partial | 0/69 |
| False full | 8/69 |

### mixed (13)

| Metric | Value |
|---|---:|
| Correct mixed-partial | 2/13 |
| Correct mixed-partial (span strict) | 2/13 |
| Mixed over-claim (safety) | 10/13 |
| Mixed over-reject | 0/13 |
| Mixed missing evidence | 1/13 |
| Primary label counts | {'correct_mixed_partial': 2, 'mixed_missing_evidence': 1, 'mixed_overclaim': 10} |

Reject correct: 11/11. Realtime safe abstain: 2/2.

Legacy grounded counts mixed over-claims as correct and correct mixed-partials as
false_partial. The two-axis view separates them; it re-scores existing behavior and
promotes nothing.
