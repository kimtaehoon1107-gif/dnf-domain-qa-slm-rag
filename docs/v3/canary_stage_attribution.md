# DNF RAG v3 canary stage-attribution 진단

## 지위

첫 sealed 실행을 마친 32개 authored canary는 질문·gold와 집계 artifact를 그대로
보존한 채 `adaptive_validation_diagnostic_only`로 강등했다. 이 세트는 v3 dev-fit
규칙의 일반화 baseline이며 sealed benchmark로 재사용하지 않는다. 실패 문항별
패치, gold 변경, 새 reranker 규칙 추가는 수행하지 않았다.

Canonical attribution은 row artifact
`a132069a231a64225bfe78b86fbfa3e81dbc9cf9fc538df8469d5e33ef4dce35`, manifest
`9e25fe54e91bfd133febc44de355b5df7beab370153769196cc9cc905bb3251c`, JSON report
`aea9decd7b8df794e9e04100d74d25ca571893fb47f6b746e0327cc19edf820a`다. 분석 중 생성된
manifest `36ffe57b...`와 report `4196fc99...`는 row attribution은 같지만 5건 이상
보조 bucket 표기가 빠진 중간본이므로 삭제하지 않고 `superseded_noncanonical`로
보존한다.

최초 실패 순서는 `ROUTING → RETRIEVAL → SELECTION → CLAIM_COVERAGE → VERIFY`로
고정했다. 한 문항 또는 evidence group은 가장 먼저 실패한 단계에만 귀속했으며
하류 실패를 이중계상하지 않았다.

## 최초 실패 히스토그램

괄호는 Wilson 95% 구간이다. 32문항과 출처별 3~4문항은 원인 확정에 작은
표본이므로 5건 미만 bucket은 힌트로만 사용한다.

| bucket | 전체 32문항 | required evidence 보유 27문항 | evidence group 50개 |
|---|---:|---:|---:|
| ROUTING | 14, 43.75% (28.17–60.67%) | 9, 33.33% (18.64–52.18%) | 23, 46.00% (32.97–59.60%) |
| RETRIEVAL | 3, 9.38% (3.24–24.22%) | 3, 11.11% (3.85–28.06%) | 4, 8.00% (3.15–18.84%) |
| SELECTION | 0, 0% (0–10.72%) | 0, 0% (0–12.46%) | 0, 0% (0–7.13%) |
| CLAIM_COVERAGE | 6, 18.75% (8.89–35.31%) | 6, 22.22% (10.61–40.76%) | 8, 16.00% (8.34–28.51%) |
| VERIFY | 0, 0% (0–10.72%) | 0, 0% (0–12.46%) | 1, 2.00% (0.35–10.50%) |
| PASS | 9, 28.13% (15.56–45.37%) | 9, 33.33% (18.64–52.18%) | 14, 28.00% (17.47–41.67%) |

VERIFY가 문항 기준 0인 것은 temporal·false/realtime 문제가 없었다는 뜻이 아니다.
그 문항들은 대부분 그보다 앞선 ROUTING 또는 CLAIM_COVERAGE에서 먼저 실패했으므로
VERIFY에 재집계하지 않은 결과다. sealed case artifact는 VERIFY 위반을 문항 수준으로만
제공하므로, group 표에서는 그 문항 안의 상류 통과 group에 VERIFY를 붙였다는 한계가
있다.

## 유형 태그와 지배 원인

- ROUTING 14건: 표면 키워드 없는 multi 8건과 zero-evidence control 5건이 핵심
  태그다. 8개 출처 전반에 분산돼 특정 문항이나 한 출처만의 문제가 아니다.
- CLAIM_COVERAGE 6건: historical 3건, partial 2건이 포함된 5건 이상 보조 신호다.
- RETRIEVAL 3건: 공지·이벤트·FAQ 각 1건으로 5건 미만 힌트다.
- SELECTION과 문항 수준 VERIFY는 최초 실패 0건이다.

따라서 지배 원인은 `ROUTING`이다. 첫 수정 후보는 불확실성 기반 multi-store 검색 또는
confidence-gated broad-search fallback이며, 라우팅 gate 전 selector·claim·verify를
먼저 변경하지 않는다.

## 출처별 retrieval 원인 메모

원시 all-required retrieval 최저 출처는 공지로 1/3이다. 라우팅이 맞은 subset에서도
1/2이므로 공지의 chunk 경계와 한국어 형태소 candidate recall은 후속 구조 점검
후보다. 다만 분모가 2라 확정 원인은 아니다. FAQ도 라우팅 정답 subset 1/2이고 이벤트는
2/3이므로 함께 점검하되, 이 진단만으로 chunker나 tokenizer를 변경하지 않는다.

운영정책·업데이트는 라우팅 정답 subset에서 각각 2/2, 3/3이었다. 이들의 원시 저하는
candidate retrieval 자체보다 앞선 라우팅 영향이므로 retrieval 수정 근거로 쓰지 않는다.

## bucket별 접근 교체와 gate

| bucket | 금지하는 fix | 후속 접근 | 새 canary gate |
|---|---|---|---|
| ROUTING | intent 키워드 추가 | 불확실성 기반 multi-store 또는 confidence fallback | route exact 0.85 이상, frozen dev 대비 하락 0.05 이하 |
| RETRIEVAL | 실패 chunk를 gold에 추가 | route-exact 저점 출처의 chunking·형태소 recall 구조 감사 | 출처별 최저 retrieval 0.66 이상, 0-hit 없음 |
| SELECTION | 문항별 selector bonus | 의미 기반 요구 coverage와 evidence 다양성 | selected group hit 0.85 이상 |
| CLAIM_COVERAGE | 가격·기간 같은 요구 키워드 추가 | 모든 복합 slot을 강제하는 의미/entailment coverage | completeness 0.90 이상, cited hit 0.85 이상, regression 0 |
| VERIFY | 시세·날씨 등 키워드 확장 | status·revision·route 기반 구조적 차단 | temporal/revision 0, false/realtime exposure 0 |

이번 사이클의 runtime 접근 변경은 0건이고 새 dev-fit 규칙도 0개다. 새 40-slot 계약만
사전고정했으며, 강건 라우팅 구현과 runtime/input hash freeze 전에는 질문·gold 작성과
sealed 실행 모두 NO-GO다.
