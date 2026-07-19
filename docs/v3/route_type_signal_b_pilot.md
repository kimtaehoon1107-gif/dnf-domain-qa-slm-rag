# DNF RAG v3 route-type Signal B pilot 계약

## 진입 근거

Signal A 최초 집계에서 32-set decomposition recall은 8/9였지만 precision은 8/25,
63 dev answerable non-multi 과분해는 29건이었다. 따라서 Signal B의 진입 조건인
“문법 target 계수가 단순질문을 과분해함이 실측됨”을 충족했다. Signal A artifact는
`NO-GO`로 보존하고 수정하거나 덮어쓰지 않는다.

## Signal B 정의

Signal A가 `decompose`로 판정한 경우에만 적용한다. 기존 라우팅 store에서 얻은 단일
top chunk가 Kiwi로 추출한 모든 target 명사구·절의 명사 성분을 포함하면 단일 근거로
답할 수 있다고 보고 `retrieve`로 강등한다.

- target 추출은 POS 구조만 사용하며 domain field·intent keyword 목록을 사용하지 않는다.
- top chunk가 없거나 target coverage를 구조적으로 계산할 수 없으면 `decompose`를 유지한다.
- 다른 store를 추가 검색하지 않는다.
- gold chunk를 runtime 판정에 사용하지 않는다. 파일럿은 기존 라우터가 실제 반환했던
  frozen top chunk만 재사용한다.
- reject/answerability short-circuit 뒤에만 적용한다.

## 사전고정 gate

| 지표 | 통과 기준 |
|---|---:|
| 32-set decomposition recall | 7/9 이상 |
| 32-set decomposition precision | 0.80 이상 |
| 32-set route-action exact | 24/32 이상 |
| 63 dev multi_evidence recall | 4/4 |
| 63 dev answerable non-multi 과분해 | 0 |
| 63 dev false short-circuit 회귀 | 0 |
| 새 field/intent keyword rule | 0 |
| store expansion 또는 broad fallback | 0 |

Signal B가 이 gate를 통과해야만 canonical `question_router`에 승격할 수 있다. 통과하지
못하면 Signal A와 B 모두 development-only `NO-GO`로 보존하고 기존 marker router를
유지한다. 새 40-canary 질문 작성과 sealed 실행은 계속 금지한다.
