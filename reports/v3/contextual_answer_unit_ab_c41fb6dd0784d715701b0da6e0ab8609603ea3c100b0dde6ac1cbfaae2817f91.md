# Contextual answer-unit selection A/B

Development-only. No runtime/canonical promotion.

Decision: **DEVELOPMENT_NO_GO**

| Block | Arm 0 groups | Arm 1 groups | Arm 0 literal spans | Arm 1 literal spans | Arm 0 false-full | Arm 1 false-full |
|---|---:|---:|---:|---:|---:|---:|
| Frozen docs | 63/69 | 60/69 | 18/69 | 20/69 | 6/69 | 9/69 |
| Authored adaptive | 20/24 | 20/24 | 7/24 | 8/24 | 2/24 | 2/24 |

- frozen regressions: `['authored_canary_sha256_44d1a04f850cb2e1c969d4ee3effac8da138b1fdce85fa8209b5123d96ebb5f9', 'retrieval_dev_sha256_d9e83e70677e5c46c0001cfb60afbebe320f1e4f6a8e02a0dc6c2bddd9b39fdc', 'retrieval_dev_sha256_f445f9f8c954555863d745271d649b3a355eabae395f907a575dcf21fa4c6342']`
- authored regressions: `[]`
- authored span improvements: `['authored_validation_v3_2_sha256_172b0d714eb57d2fb1b54401bcb2c501625543b183066bea2f2454a1b341afe9']`
- new false-full: `['authored_canary_sha256_44d1a04f850cb2e1c969d4ee3effac8da138b1fdce85fa8209b5123d96ebb5f9', 'retrieval_dev_sha256_d9e83e70677e5c46c0001cfb60afbebe320f1e4f6a8e02a0dc6c2bddd9b39fdc', 'retrieval_dev_sha256_f445f9f8c954555863d745271d649b3a355eabae395f907a575dcf21fa4c6342']`
- exact citations: **True**
- temporal violations zero: **True**

Literal evidence-span containment is a conservative mechanical lower bound, not semantic entailment.
