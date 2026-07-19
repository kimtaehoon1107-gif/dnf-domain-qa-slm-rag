# DNF RAG v3 공식 출처 URL discovery coverage

- discovery 기준 시각: `2026-07-17T18:03:52.4291730+09:00`
- registry: `data/v3/discovery/source_registry_4dfbb79b4db2d8332d41a27abe68e18dfbb01028ebb545f2af0a2e7895987bc9.jsonl`
- registry SHA-256: `4dfbb79b4db2d8332d41a27abe68e18dfbb01028ebb545f2af0a2e7895987bc9`
- manifest SHA-256: `9f6372680ea31a5c7a0f63ff362e069070017470557640a0f603d1cc34944114`

## 전체 결과

| discovered | eligible | existing covered | missing eligible | duplicate observations | coverage |
|---:|---:|---:|---:|---:|---:|
| 12747 | 979 | 181 | 798 | 532 | 0.184883 |

## 출처별 coverage

| source | 상태 | 발견 | eligible | covered | missing | duplicate | coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| `dnf_account_policy` | complete | 51 | 51 | 0 | 51 | 0 | 0.0 |
| `dnf_event` | partial | 24 | 24 | 20 | 4 | 0 | 0.833333 |
| `dnf_faq` | complete | 303 | 279 | 0 | 279 | 0 | 0.0 |
| `dnf_game_guide` | complete | 125 | 125 | 125 | 0 | 0 | 1.0 |
| `dnf_monthly_item` | partial | 1 | 1 | 0 | 1 | 0 | 0.0 |
| `dnf_notice` | complete | 10356 | 396 | 21 | 375 | 518 | 0.05303 |
| `dnf_seria_shop` | complete_for_policy_window | 96 | 85 | 0 | 85 | 12 | 0.0 |
| `dnf_update` | complete | 1791 | 18 | 15 | 3 | 1 | 0.833333 |

## pagination·scope 상태

| source | fetched / expected pages | pagination | scope | 비고 |
|---|---:|---|---|---|
| `dnf_account_policy` | 1 / 1 | True | True |  |
| `dnf_event` | 1 / 1 | True | False | Official listing exposes current/coupon events; no ended-event archive or pagination was linked. |
| `dnf_faq` | 16 / 16 | True | True | FAQ entries are inline items; canonical_url is a deterministic synthetic locator by data-no. |
| `dnf_game_guide` | 1 / 1 | True | True |  |
| `dnf_monthly_item` | 1 / 1 | True | False | Landing page exposes the current monthly item only; no historical archive was linked. |
| `dnf_notice` | 518 / 518 | True | True |  |
| `dnf_seria_shop` | 16 / 88 | False | True | Closed-sale pagination stopped after a full page ended before policy cutoff 2025-07-17. |
| `dnf_update` | 95 / 95 | True | True |  |

## 차단·미측정

- blocked sources: 없음
- partial sources: dnf_event, dnf_monthly_item
- 이벤트 종료 archive와 과거 이달의 아이템 archive는 공식 listing에서 링크를 발견하지 못해 partial로 기록했다.
- FAQ는 direct detail URL이 없는 inline 항목이라 `data-no` 기반 synthetic locator를 사용했다.
- 출처별 duplicate는 각 listing 내 반복이며, 전체 duplicate에는 서로 다른 listing이 같은 canonical URL을 발견한 경우도 포함한다.

## 승격 판정

**상세 본문 수집: NO-GO**

전체 공식 코퍼스의 상세 수집으로 승격하지 않는다. blocked/partial scope를 먼저 해소하거나 명시적으로 제외 승인한 뒤 source별 수집 arm을 시작해야 한다.

이번 실행은 URL/항목 discovery만 수행했다. 상세 본문, ChunkV3, BM25, Router, 학습은 실행하지 않았다.
