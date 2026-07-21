# v3.2 Arm 4 — duplicate-family overlay A/B

Decision: **GO_ARM4_ADDITIVE_METADATA_CANDIDATE_NOT_RUNTIME_APPLIED**. Runtime/canonical was not promoted.

| Measure | Before | Arm 4 |
|---|---:|---:|
| Structured families | 0 | 7 |
| Members with source role | 0 | 14 |
| Attribute preference entries | 0 | 77 |
| Gold document loss | 0 | 0 |
| Runtime behavior changed | False | False |

The frozen candidate pools contain family members in 21 cases and 36 requirements; 10 requirements contain multiple members of one family.

This arm improves relationship provenance only. It deliberately does not claim that title equality proves semantic identity, and it does not deduplicate or rerank candidates.
