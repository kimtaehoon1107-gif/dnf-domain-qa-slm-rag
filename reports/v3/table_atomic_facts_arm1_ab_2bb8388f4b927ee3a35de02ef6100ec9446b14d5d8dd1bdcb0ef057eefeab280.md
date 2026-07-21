# v3.2 Table Row Atomic Facts — Arm 1 A/B

Decision: **GO_V3_2_CANONICAL_CANDIDATE_ONLY_SEALED_CANARY_REQUIRED**. This remains development-only and is not promoted.

## Corpus and integrity

- Row-child facts: 4,017 facts / 1,056 rows / 101 tables.
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
Generic `초월 가격` complete table views: **2**.
`서약 결정 초월 유니크 가격` all-rarity table recovery: **True**.
Expected frozen source chunk recovered by either probe: **True**.

### `초월 가격`

Seed rows: 115Lv 장비 초월 무기 태초 — 순례의 인장 — 4,500; 서약 결정 초월 유니크 — 솔리드 소울 — 1개

### 115Lv 장비 초월 비용은 아래와 같습니다.

| 구분 | 레어리티별 소울 | 상급 원소 결정 | 순례의 인장 | 보이드 소울 |
| --- | --- | --- | --- | --- |
| 무기 레어 | 75 | 9 | 20 | - |
| 무기 유니크 | 60 | 36 | 38 | 2 |
| 무기 레전더리 | 30 | 180 | 375 | 98 |
| 무기 에픽 | 30 | 432 | 1,125 | 225 |
| 무기 태초 | 8 | 432 | 4,500 | 750 |
| 방어구 악세서리 레어 | 50 | 9 | 13 | - |
| 방어구 악세서리 유니크 | 40 | 36 | 25 | 1 |
| 방어구 악세서리 레전더리 | 20 | 180 | 250 | 65 |
| 방어구 악세서리 에픽 | 20 | 540 | 750 | 150 |
| 방어구 악세서리 태초(악세서리) | 5 | 540 | 3,000 | 500 |
| 특수장비 레어 | 50 | 9 | 13 | - |
| 특수장비 유니크 | 40 | 36 | 25 | 1 |
| 특수장비 레전더리 | 20 | 180 | 250 | 65 |
| 특수장비 에픽 | 20 | 810 | 750 | 150 |

각 행은 원본 표의 exact slice이며, 행 선택 시 부모 표 문맥을 함께 표시합니다.

### 서약 결정 초월 비용은 아래와 같습니다.

| 구분 | 광휘의 소울 | 상급 원소 결정 | 순례의 인장 / 골드 | 솔리드 소울 |
| --- | --- | --- | --- | --- |
| 유니크 | 25개 | 36개 | 순례의 인장 25개 or 125,000골드 | 1개 |
| 레전더리 | 60개 | 180개 | 순례의 인장 250개 or 1,250,000골드 | 65개 |
| 에픽 | 200개 | 810개 | 순례의 인장 750개 or 3,750,000골드 | 150개 |
| 태초 | 500개 | 810개 | 순례의 인장 3,000개 or 15,000,000골드 | 500개 |

각 행은 원본 표의 exact slice이며, 행 선택 시 부모 표 문맥을 함께 표시합니다.

### `서약 결정 초월 유니크 가격`

Seed rows: 서약 결정 초월 유니크 — 순례의 인장 / 골드 — 순례의 인장 25개 or 125,000골드; 서약 결정 초월 유니크 — 순례의 인장 / 골드 — 순례의 인장 25개 or 125,000골드; 서약 결정 초월 획득 방식 — 광휘의 소울 결정 — 서약 결정 해체

### 서약 결정 초월 비용은 아래와 같습니다.

| 구분 | 광휘의 소울 | 상급 원소 결정 | 순례의 인장 / 골드 | 솔리드 소울 |
| --- | --- | --- | --- | --- |
| 유니크 | 25개 | 36개 | 순례의 인장 25개 or 125,000골드 | 1개 |
| 레전더리 | 60개 | 180개 | 순례의 인장 250개 or 1,250,000골드 | 65개 |
| 에픽 | 200개 | 810개 | 순례의 인장 750개 or 3,750,000골드 | 150개 |
| 태초 | 500개 | 810개 | 순례의 인장 3,000개 or 15,000,000골드 | 500개 |

각 행은 원본 표의 exact slice이며, 행 선택 시 부모 표 문맥을 함께 표시합니다.


## Interpretation

Frozen sibling-attribute recoveries: 0/2. Those two audited failures are prose/selection cases, so Arm 1 does not claim to solve them.
Passing this development gate creates only a v3.2 candidate. A new sealed canary is still required before canonical promotion.
