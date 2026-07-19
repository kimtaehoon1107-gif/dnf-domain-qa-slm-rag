# DNF RAG v3 same-parent / cross-parent 무료 진단

## 판정

최종 판정은 **혼합**이다. 전역 LLM decomposition은 NO-GO이며, same-parent 질문은
requirement-slot claim coverage로 처리하고 실제 cross-parent 질문에만 decomposition을
제한하는 방향이 타당하다.

숫자를 보기 전에 실패 복합질문을 주 판정 분모로, 두 평가셋 전체 복합질문을 보조
분모로 고정했다. 두 분모가 서로 다른 threshold band에 속하면 보수적으로 혼합을
선택하도록 사전 고정했다.

## 전체 복합질문

| 평가셋 | 복합질문 | single-document-coverable | cross-document |
|---|---:|---:|---:|
| 강등 32-set | 17 | 15 (88.24%) | 2 (11.76%) |
| 63 dev | 4 | 0 (0%) | 4 (100%) |
| 합계 | 21 | 15 (71.43%) | 6 (28.57%) |

강등 32-set의 cross-document 2건은 모두 같은 source 안의 서로 다른 parent다. 63 dev의
cross-document 4건은 같은 source 안의 cross-parent 2건과 실제 cross-source 2건이다.
따라서 전체 21건에서 실제 cross-source는 2건뿐이다.

## 실패 복합질문 교차 분석

| attribution subset | attribution 문항 | 계약상 복합 | same-parent | cross-parent |
|---|---:|---:|---:|---:|
| ROUTING + expected decompose | 9 | 9 | 7 (77.78%) | 2 (22.22%) |
| CLAIM_COVERAGE | 6 | 4 | 4 (100%) | 0 |
| 복합질문 합계 | 15 | 13 | 11 (84.62%) | 2 (15.38%) |

CLAIM_COVERAGE 6건 중 2건은 required evidence group이 1개이므로 이번에 사전 고정한
복합질문 정의에서 제외했다. 남은 실패 복합질문 13건은 84.62%가 same-parent이므로 주
판정만 보면 decomposition 중단 구간이다. 그러나 전체 복합질문은 71.43%로 혼합
구간이므로 사전 고정한 충돌 규칙에 따라 최종 판정은 혼합이다.

## 출처 분포

강등 32-set에서 이벤트 3/3, 세리아 상점 3/3, 이달의 아이템 2/2, 업데이트 2/2,
가이드 1/1, 공지 1/1이 same-parent였다. 운영정책은 2/3, FAQ는 1/2가 same-parent였다.

실패 복합질문 13건에서는 이벤트 2/2, 이달의 아이템 2/2, 세리아 상점 2/2,
가이드·공지·업데이트 각 1/1이 same-parent였다. 운영정책과 FAQ만 각각 1건의
cross-parent가 있었으며 둘 다 cross-source가 아니라 동일 source 내부의 다른
parent였다.

63 dev의 복합질문은 4건뿐이라 일반화 근거로는 작다. 출처 관여 기준으로 운영정책과
FAQ가 각각 2건, 이달의 아이템과 세리아 상점이 각각 1건이며, multi-source 질문은
여러 출처에 중복 집계된다.

## 범위 및 검증

- 기존 acceptable/gold chunk label과 canonical chunk→parent 매핑만 사용했다.
- 3,599개 chunk_id가 모두 고유했으며 acceptable chunk 매핑 누락은 0건이다.
- 질문, gold, router, decomposition, retrieval, claim 코드를 변경하지 않았다.
- 모델, 임베딩, 검색, 새 canary를 실행하지 않았다.
- 개별 질문이나 gold 텍스트는 보고서에 포함하지 않았다.
- frozen blind, v2, AGENTS.md, handoff, src/outputs에 접근하거나 수정하지 않았다.

다음 round는 전역 decomposition 재시도가 아니다. same-parent의 모든 required slot을
한 parent 안에서 선택·인용하는 claim-coverage 접근을 먼저 설계하고, cross-parent로
판정된 경우에만 판단과 sub-query 생성을 결합한 decomposition 후보를 별도 분기로
검증해야 한다.
