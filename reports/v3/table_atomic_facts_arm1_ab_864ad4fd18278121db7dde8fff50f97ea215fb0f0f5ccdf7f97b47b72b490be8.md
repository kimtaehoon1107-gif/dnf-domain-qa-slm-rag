# v3.2 Table Row Atomic Facts — Arm 1 A/B

Decision: **GO_V3_2_CANONICAL_CANDIDATE_ONLY_SEALED_CANARY_REQUIRED**. This remains development-only and is not promoted.

## Corpus and integrity

- Row-child facts: 3,665 facts / 990 rows / 101 tables.
- Exact row/value offsets: 100.00%; mismatches 0.
- Gold content loss: 0; dirty canonical hash unchanged: True.
- Parent candidate ordering is frozen; row children are sidecar-unioned, so parent rank perturbations are structurally zero.

## Frozen 95 A/B

| Metric | Dirty baseline | Arm 1 |
|---|---:|---:|
| Grounded answers | 73/82 | 73/82 |
| False-full | 9/82 | 9/82 |
| Reject correct | 11/11 | 11/11 |
| Realtime safe abstain | 2/2 | 2/2 |

Candidate recall regressions: 0. New false-full: 0. Temporal leaks: 0.

## Transcendence probe

Generic `초월 가격` value-row recovery: **True**.
Expected frozen source chunk recovered by either probe: **True**.

- `초월 가격`: 115Lv 장비 초월 무기 태초 — 순례의 인장 — 4,500; 서약 결정 초월 유니크 — 솔리드 소울 — 1개
- `서약 결정 초월 유니크 가격`: 서약 결정 초월 유니크 — 순례의 인장 / 골드 — 순례의 인장 25개 or 125,000골드; 서약 결정 초월 유니크 — 순례의 인장 / 골드 — 순례의 인장 25개 or 125,000골드; 서약 결정 초월 획득 방식 — 광휘의 소울 결정 — 서약 결정 해체

## Interpretation

Frozen sibling-attribute recoveries: 0/2. Those two audited failures are prose/selection cases, so Arm 1 does not claim to solve them.
Passing this development gate creates only a v3.2 candidate. A new sealed canary is still required before canonical promotion.
