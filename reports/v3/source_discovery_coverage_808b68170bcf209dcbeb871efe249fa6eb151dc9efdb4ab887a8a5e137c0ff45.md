# DNF RAG v3 공식 출처 URL discovery coverage

- discovery 기준 시각: `2026-07-17T19:20:31.0313737+09:00`
- registry: `data/v3/discovery/source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl`
- registry SHA-256: `04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a`
- manifest SHA-256: `4cbd8c441fd694ec16ad30b6b42c4c6f28326dc9a768d883399419ef87ee9ea2`

## 전체 결과

| discovered | eligible | existing covered | missing eligible | duplicate observations | coverage |
|---:|---:|---:|---:|---:|---:|
| 13214 | 982 | 181 | 801 | 610 | 0.184318 |

## 출처별 coverage

| source | 상태 | 발견 | eligible | covered | missing | duplicate | coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| `dnf_account_policy` | complete | 51 | 51 | 0 | 51 | 0 | 0.0 |
| `dnf_event` | complete | 362 | 27 | 20 | 7 | 61 | 0.740741 |
| `dnf_faq` | complete | 303 | 279 | 0 | 279 | 0 | 0.0 |
| `dnf_game_guide` | complete | 125 | 125 | 125 | 0 | 0 | 1.0 |
| `dnf_monthly_item` | complete | 147 | 14 | 0 | 14 | 0 | 0.0 |
| `dnf_notice` | complete | 10356 | 396 | 21 | 375 | 518 | 0.05303 |
| `dnf_seria_shop` | complete_for_policy_window | 79 | 72 | 0 | 72 | 12 | 0.0 |
| `dnf_update` | complete | 1791 | 18 | 15 | 3 | 1 | 0.833333 |

## pagination·scope 상태

| source | fetched / expected pages | pagination | scope | 비고 |
|---|---:|---|---|---|
| `dnf_account_policy` | 1 / 1 | True | True |  |
| `dnf_event` | 2 / 2 | True | True | Ended events were discovered through categoryType=3; URLs repeated on the current listing are deduplicated. |
| `dnf_faq` | 16 / 16 | True | True | FAQ entries are inline items; canonical_url is a deterministic synthetic locator by data-no. |
| `dnf_game_guide` | 1 / 1 | True | True |  |
| `dnf_monthly_item` | 26 / 26 | True | True | Historical monthly items were discovered through the closed Seria Shop searchKeyword route. |
| `dnf_notice` | 518 / 518 | True | True |  |
| `dnf_seria_shop` | 16 / 88 | False | True | Closed-sale pagination stopped after a full page ended before policy cutoff 2025-07-17. |
| `dnf_update` | 95 / 95 | True | True |  |

## 차단·미측정

- blocked sources: 없음
- partial sources: 없음
- 종료 이벤트와 과거 이달의 아이템 archive 경로까지 실측했다.
- FAQ는 direct detail URL이 없는 inline 항목이라 `data-no` 기반 synthetic locator를 사용했다.
- 출처별 duplicate는 각 listing 내 반복이며, 전체 duplicate에는 서로 다른 listing이 같은 canonical URL을 발견한 경우도 포함한다.

## 승격 판정

**상세 본문 수집: GO**

모든 출처의 discovery scope가 완료되어 source별 detail 수집 arm을 설계할 수 있다.

이번 실행은 URL/항목 discovery만 수행했다. 상세 본문, ChunkV3, BM25, Router, 학습은 실행하지 않았다.
