# Lightweight semantic-support verifier A/B

- recommendation: **REJECT_BOTH_VERIFIERS_NO_SAFE_OPERATING_POINT**
- baseline: grounded 73/82, false-full 9/82, reject 11/11, realtime safe-abstain 2/2

| component | bar | grounded | false-full | honest partial | cross-parent | reject | realtime safe | pair P/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bge_support_pair | none | - | - | - | - | - | - | - |
| mdeberta_nli_support | none | - | - | - | - | - | - | - |

## Full fixed-bar curve

| component | bar | grounded | false-full | honest partial | overreject | cross-parent | pair precision | pair recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bge_support_pair | 0.0 | 73/82 | 9/82 | 0/82 | 0/82 | 0/2 | 0.3275 | 1.0000 |
| bge_support_pair | 0.001 | 72/82 | 10/82 | 0/82 | 0/82 | 0/2 | 0.3471 | 0.9692 |
| bge_support_pair | 0.005 | 72/82 | 9/82 | 0/82 | 1/82 | 0/2 | 0.3738 | 0.9231 |
| bge_support_pair | 0.01 | 69/82 | 10/82 | 0/82 | 1/82 | 1/2 | 0.3881 | 0.8538 |
| bge_support_pair | 0.02 | 63/82 | 12/82 | 0/82 | 5/82 | 1/2 | 0.4089 | 0.7769 |
| bge_support_pair | 0.05 | 55/82 | 10/82 | 2/82 | 13/82 | 1/2 | 0.4555 | 0.6692 |
| bge_support_pair | 0.1 | 47/82 | 8/82 | 3/82 | 20/82 | 1/2 | 0.4841 | 0.5846 |
| bge_support_pair | 0.2 | 44/82 | 7/82 | 3/82 | 23/82 | 0/2 | 0.5075 | 0.5231 |
| bge_support_pair | 0.3 | 39/82 | 6/82 | 4/82 | 31/82 | 0/2 | 0.5229 | 0.4385 |
| bge_support_pair | 0.5 | 27/82 | 7/82 | 3/82 | 43/82 | 0/2 | 0.5065 | 0.3000 |
| bge_support_pair | 0.7 | 18/82 | 7/82 | 3/82 | 54/82 | 0/2 | 0.5532 | 0.2000 |
| bge_support_pair | 0.8 | 15/82 | 5/82 | 1/82 | 61/82 | 0/2 | 0.5882 | 0.1538 |
| bge_support_pair | 0.9 | 9/82 | 4/82 | 1/82 | 68/82 | 0/2 | 0.5652 | 0.1000 |
| bge_support_pair | 0.95 | 6/82 | 1/82 | 1/82 | 74/82 | 0/2 | 0.8000 | 0.0615 |
| bge_support_pair | 0.99 | 0/82 | 0/82 | 0/82 | 82/82 | 0/2 | 0.0000 | 0.0000 |
| mdeberta_nli_support | 0.0 | 73/82 | 9/82 | 0/82 | 0/82 | 0/2 | 0.3275 | 1.0000 |
| mdeberta_nli_support | 0.01 | 72/82 | 10/82 | 0/82 | 0/82 | 1/2 | 0.3255 | 0.9615 |
| mdeberta_nli_support | 0.05 | 69/82 | 13/82 | 0/82 | 0/82 | 1/2 | 0.3313 | 0.8538 |
| mdeberta_nli_support | 0.1 | 65/82 | 16/82 | 1/82 | 0/82 | 1/2 | 0.3323 | 0.8000 |
| mdeberta_nli_support | 0.2 | 60/82 | 15/82 | 1/82 | 5/82 | 1/2 | 0.3464 | 0.7462 |
| mdeberta_nli_support | 0.3 | 57/82 | 14/82 | 0/82 | 7/82 | 1/2 | 0.3543 | 0.6923 |
| mdeberta_nli_support | 0.5 | 50/82 | 13/82 | 0/82 | 12/82 | 0/2 | 0.3575 | 0.5692 |
| mdeberta_nli_support | 0.7 | 40/82 | 16/82 | 0/82 | 18/82 | 0/2 | 0.3758 | 0.4538 |
| mdeberta_nli_support | 0.8 | 34/82 | 13/82 | 2/82 | 27/82 | 0/2 | 0.3871 | 0.3692 |
| mdeberta_nli_support | 0.9 | 24/82 | 13/82 | 1/82 | 39/82 | 0/2 | 0.3617 | 0.2615 |
| mdeberta_nli_support | 0.95 | 17/82 | 11/82 | 3/82 | 46/82 | 0/2 | 0.3433 | 0.1769 |
| mdeberta_nli_support | 0.99 | 8/82 | 2/82 | 3/82 | 66/82 | 0/2 | 0.5500 | 0.0846 |

The pair P/R curve is a scoring-only question-level acceptable-chunk proxy, not a requirement-group gold mapping.
No canonical/runtime promotion, sealed run, training, keyword rule, or answer-source classifier change occurred.
