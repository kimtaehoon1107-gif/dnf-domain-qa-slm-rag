# Bounded candidate-source fallback A/B

## 목적

Q3의 남은 mixed 1건은 hard route가 `dnf_event`를 후보 신호에 포함했지만 실제
검색은 `dnf_seria_shop`에만 제한해 official evidence를 놓쳤고, 개인 계산 절도
partial로 판정하지 못했다. 전 공식 source federated 검색은 이전 A/B에서 NO-GO였기
때문에 재도입하지 않는다.

## Q4 메커니즘

1. 기존 planner·hard-route·assembler 결과를 그대로 시작점으로 사용한다.
2. 기존 exact span이 planner requirement의 고정밀 value-shape를 충족하지 못할 때만
   fallback 후보가 된다. 이 검사는 지지를 증명하지 않고 부재만 탐지한다.
3. 검색 범위는 기존 `route.source_ids`와 이미 계산된
   `route.routing_signals.candidate_sources` 상위 2개 합집합으로 제한한다.
4. 기존 frozen hard-route span과 frozen federated 검색의 segment scores에서 이
   source 범위만 남긴 후보를 합집합으로 만들고, 기존 assembler threshold/K로 다시
   조립한다. 기존 근거를 버리고 fallback으로 교체하지 않는다.
5. fallback 후 value-shape를 충족하는 requirement 수가 엄격히 증가할 때만 결과를
   채택한다. 같거나 감소하면 기존 결과를 유지한다.
6. mixed safety는 기존 lexical partial과 Kiwi 구조 신호의 합집합으로 판정한다.
   구조 신호는 도메인 키워드 없이 `공식 절 + 연결어미 + 1인칭 절`만 탐지한다.
7. partial 출력은 인용된 동일 chunk의 exact context answer-unit을 보존한다.

Gold chunk·span·라벨은 2~6 결정에 사용하지 않고 채점에만 사용한다.

## 게이트

- mixed span-strict 12/13보다 개선, overclaim 0
- docs-only grounded 61/69 이상, 기존 grounded 회귀 0 지향
- 새 false-full 0
- exact slice 100%, malformed 0
- reject 11/11, realtime safe abstain 2/2 유지
- temporal/default-exposure 위반 0
- 개별 질문/필드 키워드 0, 모델 호출·학습·재색인 0

통과해도 development candidate다. 새 authored validation에서 1회 확인 전 runtime이나
canonical로 승격하지 않는다.
