# DNF RAG v3 behavioral decomposition coverage pilot 계약

## 목적과 지위

이 파일럿은 Signal A의 높은 decomposition recall을 유지하면서, 실제 검색 결과가 target
coverage를 늘릴 때만 `decompose`를 commit한다. 이전 Signal A/B 결과는 development-only
`NO-GO`로 보존하며 수정하지 않는다. semantic/LLM route judge는 이 파일럿이 무료
사전검증을 통과하지 못할 때만 다음 후보가 된다.

## 실행 순서

1. 기존 answerability/reject gate를 먼저 실행한다.
2. 변경하지 않은 Signal A가 target 2개 이상을 찾으면 speculative candidate로 둔다.
3. 현재 라우터가 고른 source/time policy를 그대로 사용해 원 질문 single 검색을 실행한다.
4. 기존 `question_decomposer`로만 child query를 만들고 기존 decomposed retriever의 결과를
   union한다. 기존 decomposer가 지원하지 않는 문법이면 새 pattern을 만들지 않고
   single retrieve를 유지한다.
5. target마다 content 형태소가 들어 있는 검색 chunk가 하나라도 있는지 계산한다.
6. `coverage_decomposed > coverage_single`일 때만 decompose를 commit한다.

검색과 coverage 판정에는 expected/gold source, document, chunk ID를 전달하지 않는다.
expected route는 검색이 끝난 뒤 집계 채점에만 사용한다. 새로운 store expansion이나
broad fallback도 추가하지 않는다.

## 형태소 coverage와 threshold 선택

target coverage ratio는 target의 nominal content 형태소 중 한 chunk에 포함된 비율의
최댓값이다. 다음 grid만 사용한다.

`0.50, 0.60, 0.70, 0.80, 0.90, 1.00`

강등 32-set에서 문항별 결과를 열지 않고 threshold별 confusion matrix와 route exact만
집계한다. 선택 순서는 다음으로 고정한다.

1. decomposition recall 0.80 이상
2. route exact 최대
3. decomposition precision 최대
4. recall 최대
5. 동률이면 더 높은 threshold

선택 후 threshold를 고정하고 63 dev는 한 번만 평가한다. 63 dev 결과를 보고 threshold를
다시 선택하지 않는다.

## GO/NO-GO gate

| 지표 | GO 기준 |
|---|---:|
| 32-set route exact | 18/32 초과 |
| 32-set decomposition recall | 8/9 이상 |
| 32-set decomposition precision | 0.60 이상 |
| 63 dev multi_evidence recall | 4/4 |
| 63 dev answerable non-multi 과분해 | 0 |
| 63 dev false short-circuit 회귀 | 0 |
| 새 field/intent keyword rule | 0 |
| 신규 store expansion/broad fallback | 0 |

precision 0.60은 Signal A의 0.32를 거의 두 배로 높이는 최소 실질 개선선으로 결과 확인
전에 고정한다. 비율은 Wilson 95% 구간과 함께 보고한다.

## Latency

- frozen full-query embedding을 사용한 single 검색 시간
- 기존 child query의 batch embedding 총시간과 candidate당 상각시간
- single + decomposed-union 검색 및 coverage 계산의 candidate별 median/p95

을 분리해 보고한다. batch embedding은 실제 서비스에서 모델을 상주시킬 수 있다는
전제의 throughput 관측이며, 검색 latency와 합쳐진 end-to-end p95로 과장하지 않는다.

## 범위 제한

Signal A와 기존 decomposer의 pattern은 변경하지 않는다. retrieval ranking, selector,
claim coverage, verify, reject/realtime 분류기, Generator, 모델 학습도 변경하지 않는다.
새 40-canary는 이 무료 사전검증을 통과한 뒤 별도 작성·사람 검수 전에는 실행하지 않는다.
frozen blind와 v2 artifact에는 접근하지 않는다.
