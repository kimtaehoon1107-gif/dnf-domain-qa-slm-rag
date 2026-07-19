# DNF RAG v3 route-type decomposition pilot 계약

## 지위

이 계약은 기존 `robust routing = store expansion` 계획을 대체한다. 후보 store를 두 개
이상 검색하거나 broad-search fallback을 추가하지 않는다. 이번 수정 대상은
`retrieve`와 `decompose` 사이의 route type뿐이다.

강등된 32개 authored canary는 질문·gold를 수정하지 않고 집계 사전검증에만 사용한다.
개별 실패 문항, 문항별 형태소, 선택 근거는 열어 규칙을 맞추지 않는다. 기존 sealed
결과와 모든 실패 artifact는 삭제하지 않는다.

## Signal A

Kiwi 형태소 태그로 다음 문법 구조를 센다.

- 독립 predicate와 연결어미를 가진 절의 개수
- `JC`로 연결된 서로 다른 명사구의 개수
- 절·명사구 구조에서 중복을 제거한 answer-target 개수

도메인 field·intent 단어와 의문사 표면형 목록은 사용하지 않는다. 질문별 예외,
가격·기간·삭제일 같은 field bonus, `각각·비교·함께` marker도 사용하지 않는다.
answer target이 2개 이상이면 `decompose`, 아니면 `retrieve`다.

라우팅 순서는 다음으로 고정한다.

1. 기존 answerability/reject 판정
2. false이면 `reject` 또는 `realtime_api`로 즉시 종료
3. answerable 질문에만 Signal A 적용
4. target 2개 이상이면 `decompose`, 아니면 `retrieve`

Signal A는 source 후보 수를 늘리지 않는다. Signal B인 “단일 top chunk가 모든 target을
포함하면 retrieve로 강등”은 Signal A의 과분해가 집계로 확인될 때만 별도 후보가 되며,
이번 최초 실행에는 포함하지 않는다.

## 사전고정 pilot gate

32-set 결과를 보기 전에 다음 기준을 고정한다.

| 지표 | pilot 통과 기준 |
|---|---:|
| expected decompose 9개 Signal A recall | 7/9 이상 |
| Signal A decompose precision | 0.80 이상 |
| 전체 route-action exact | 24/32 이상 |
| 질문·gold 변경 | 0 |
| 새 field/intent keyword rule | 0 |
| store expansion 또는 broad fallback | 0 |

기존 63 dev에서는 다음을 기능·회귀 gate로 사용한다.

| 지표 | 통과 기준 |
|---|---:|
| multi_evidence decomposition recall | 4/4 |
| answerable non-multi 과분해 | 0 |
| 기존 false answerability short-circuit 회귀 | 0 |

latency는 Kiwi warm-up 뒤 answerable single 질문의 median과 p95를 보고한다. 기계별
차이가 크므로 pilot 승격 수치로 사용하지 않되, 새 sealed canary에서는 baseline 대비
증가량을 함께 보고한다.

## 새 40-canary gate

pilot과 63 dev가 모두 통과한 뒤에만 별도 작성자가 기존 40개 빈 slot을 작성한다.
runtime·설정·corpus·index hash를 먼저 freeze하고 사람이 질문·gold·시간 상태를 검수한
뒤 한 번만 sealed 실행한다.

- `compound_without_surface_keywords` decomposition recall: 7/8 이상
- 전체 route-action exact: 0.85 이상
- frozen development 대비 route-type 정확도 하락: 0.05 이하
- `single_current` 과분해: 0/8
- reject/realtime evidence exposure: 0
- answerable single latency median/p95: baseline과 함께 보고

이번 라운드는 route-type 승격 gate다. CLAIM_COVERAGE를 수정하지 않으므로 전체
completeness gate가 실패하더라도 route-type 결과와 분리해 판정한다. sealed 결과를 연 뒤
Signal A를 조정하면 해당 40개도 즉시 `adaptive_validation`으로 강등하고 sealed로
재사용하지 않는다.

## 범위 제한

reject 탐지 개선, realtime 분류기, retrieval, selector, claim coverage, verify, 자연어
Generator, NLI 학습, LoRA/RAFT, 구조화 store/API는 이번 사이클 범위 밖이다. frozen
blind와 v2 artifact에도 접근하지 않는다.
