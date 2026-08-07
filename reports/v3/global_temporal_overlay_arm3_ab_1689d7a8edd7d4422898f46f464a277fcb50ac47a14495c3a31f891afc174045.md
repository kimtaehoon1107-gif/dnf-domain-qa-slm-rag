# v3.2 Arm 3 — Global temporal overlay A/B

Decision: **GO_ARM3_ADDITIVE_METADATA_CANDIDATE_NOT_PROMOTED**. This is an additive metadata candidate; runtime/canonical was not promoted.

| Measure | Before | Arm 3 |
|---|---:|---:|
| Documents with a uniform validity contract | 51 policy revisions | 980 documents |
| Current-eval gold groups denied | n/a | 0 |
| Frozen current citations denied | n/a | 0 |
| Unverified documents with fabricated last_verified_at | n/a | 0 |

## Validity states

- `active_window`: 32
- `current_revision`: 1
- `current_unverified`: 838
- `expired`: 55
- `preview`: 3
- `superseded`: 1
- `superseded_revision`: 50

`current_unverified` is not treated as recently verified. It remains searchable with a warning so old but still authoritative security notices are not removed merely because of publication age.
