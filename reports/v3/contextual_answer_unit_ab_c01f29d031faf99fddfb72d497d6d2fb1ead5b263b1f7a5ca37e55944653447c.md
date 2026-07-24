# Contextual answer-unit selection A/B

Development-only. No runtime/canonical promotion.

Decision: **DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED**

| Block | Arm 0 groups | Arm 1 groups | Arm 0 literal spans | Arm 1 literal spans | Arm 0 false-full | Arm 1 false-full |
|---|---:|---:|---:|---:|---:|---:|
| Frozen docs | 63/69 | 63/69 | 18/69 | 20/69 | 6/69 | 6/69 |
| Authored adaptive | 20/24 | 21/24 | 7/24 | 9/24 | 2/24 | 1/24 |

- frozen regressions: `[]`
- authored regressions: `[]`
- authored span improvements: `['authored_validation_v3_2_sha256_172b0d714eb57d2fb1b54401bcb2c501625543b183066bea2f2454a1b341afe9', 'authored_validation_v3_2_sha256_c8803a9d34cc39551e80708aa46733e0483fa27c8e5f29a75f2f85154b44874a']`
- new false-full: `[]`
- exact citations: **True**
- temporal violations zero: **True**

Literal evidence-span containment is a conservative mechanical lower bound, not semantic entailment.
