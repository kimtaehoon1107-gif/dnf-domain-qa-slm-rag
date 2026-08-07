# Contextual answer-unit selection A/B

Development-only. No runtime/canonical promotion.

Decision: **DEVELOPMENT_NO_GO**

| Block | Arm 0 groups | Arm 1 groups | Arm 0 literal spans | Arm 1 literal spans | Arm 0 false-full | Arm 1 false-full |
|---|---:|---:|---:|---:|---:|---:|
| Frozen docs | 63/69 | 64/69 | 18/69 | 22/69 | 6/69 | 5/69 |
| Authored adaptive | 20/24 | 21/24 | 7/24 | 9/24 | 2/24 | 1/24 |

- frozen regressions: `['retrieval_dev_sha256_59ca7a033abaec5d72433fd9b114842276ddc4e79774e4894d13ef5e1813a344']`
- authored regressions: `[]`
- authored span improvements: `['authored_validation_v3_2_sha256_172b0d714eb57d2fb1b54401bcb2c501625543b183066bea2f2454a1b341afe9', 'authored_validation_v3_2_sha256_362a5bbd3214741bf4079f88af82319b9bb0fb126214d7e9d0ba48d4371472ea']`
- new false-full: `['retrieval_dev_sha256_59ca7a033abaec5d72433fd9b114842276ddc4e79774e4894d13ef5e1813a344']`
- exact citations: **True**
- temporal violations zero: **True**

Literal evidence-span containment is a conservative mechanical lower bound, not semantic entailment.
