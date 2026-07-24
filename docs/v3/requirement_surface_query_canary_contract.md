# Requirement surface-query authored canary contract

## 목적

이 세트는 `entity-coordinated-surface-query-v3.3.1`이 처음 보는 공식 문서 질문에서도
두 요구의 한국어 표면 표현을 안전하게 복원하는지 확인하는 기능 전용 canary다. 일반 QA
성능이나 최종 제품 성능을 주장하는 benchmark가 아니다. 기존 adaptive dev, 강등된 canary,
기존 authored validation을 다시 점수 내는 데 사용하지 않는다.

현재 단계에서는 계약과 빈 슬롯을 먼저 content-addressed artifact로 고정한다. 질문·gold는
그 뒤 별도 packet으로 작성하고 사용자가 전수 검수한다. immutable reviewed export 전에는
Baseline/OFF와 Candidate/ON을 실행하지 않는다.

## 고정 비교 대상

- Baseline/OFF: 현재 개발 백본에서 surface-query 기능을 끈 상태
- Candidate/ON: 동일 백본에 `entity-coordinated-surface-query-v3.3.1`만 켠 상태
- planner, corpus, BM25+BGE-M3 검색, `bge-reranker-v2-m3`, chunk-diverse assembler,
  temporal 설정은 두 arm에서 동일하게 유지한다.
- threshold, K, source routing, gold, 질문은 결과를 본 뒤 바꾸지 않는다.

## 32-slot 표본

8개 공식 source마다 네 슬롯을 둔다.

1. `positive_coordination_a`: 한 official entity에 귀속된 두 atomic requirement, 기능 적용 예상
2. `positive_coordination_b`: 다른 문서·사실의 두 atomic requirement, 기능 적용 예상
3. `single_requirement_control`: 한 requirement, 기능 우회 예상
4. `three_requirement_control`: 세 requirement, 기능 우회 예상

positive와 control은 같은 사실을 다른 요구 수로 묻는 paired metamorphic 구조다. 따라서 이
세트는 독립적인 지식 benchmark가 아니라 feature application/bypass와 회귀를 검사한다.
가능한 source에서는 기존 63 dev, 강등된 32, authored validation 24의 parent와 분리한다.
현재 revision parent가 하나뿐인 운영정책과 current parent가 하나뿐인 이달의 아이템은
명시적 예외로 남기며, 이 두 source의 결과를 parent-generalization 근거로 사용하지 않는다.

## 사람 검수

- 작성 수준: `codex_authored_user_full_review_required`
- independent holdout 또는 sealed benchmark라는 표현을 사용하지 않는다.
- 사용자는 질문 자연성, atomic requirement, entity 귀속, exact evidence span, 현재성,
  expected apply/bypass를 전수 승인 또는 기각한다.
- 기각 row가 하나라도 있거나 미검수 row가 있으면 immutable reviewed export와 실행을 막는다.
- 검수 완료 뒤 질문·gold를 바꾸면 새 packet으로 다시 freeze해야 한다.

## 사전 고정 gate

모든 수치는 분자/분모와 작은 표본 한계를 함께 보고한다. 하나라도 실패하면 NO-GO다.

| 지표 | GO 기준 |
|---|---:|
| candidate all-required evidence coverage | baseline 이상 |
| strict question regression | 0 |
| literal evidence-span regression | 0 |
| strict 또는 literal improvement | 1건 이상 |
| positive expected application | 16/16 |
| control expected bypass | 16/16 |
| bypass row 출력 변동 | 0 |
| false-full | 0 |
| exact citation slice | 100% |
| 새 irrelevant/surplus citation | 0 |
| requirement citation precision | baseline 이상 |
| temporal/revision/preview/expired 누출 | 0 |
| source별 positive all-required coverage | 각 source 1/2 이상, 0-hit source 0 |

현재 target 사례에서 정답 두 문장 외 표 행 두 개가 추가 선택됐으므로, 단순 recall 개선만으로
통과시키지 않는다. `irrelevant/surplus citation`과 citation precision은 hard gate다.

## sibling adjudication 분리

광휘의 행로 guide 근거는 기존 update gold를 대체하지 않는다. 별도 사람 검수 sheet에서
`EQUIVALENT_OFFICIAL`로 승인된 경우에만 acceptable sibling으로 추가할 수 있다. strict 원지표와
adjudicated 지표를 함께 보존하며, 모델이 선택했다는 이유로 gold를 이동하지 않는다.

## sealed 규율

1. 이 계약과 빈 32-slot plan을 먼저 freeze한다.
2. authored candidate packet을 생성한다.
3. 사용자가 32개를 전수 검수하고 immutable export한다.
4. 그 뒤 OFF/ON을 한 번만 실행한다.
5. 결과를 열어 코드·설정·질문·gold를 고치면 즉시 adaptive validation으로 강등한다.

## 금지

- 검수 완료 전 점수 실행
- 기존 frozen blind 접근
- 기존 gold 교체 또는 sibling 자동 적용
- 개별 실패 문항에 맞춘 relation/field 키워드 추가
- threshold/K 동시 튜닝
- runtime/canonical 자동 승격
