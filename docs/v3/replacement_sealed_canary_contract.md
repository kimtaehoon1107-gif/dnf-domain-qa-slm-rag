# DNF RAG v3 replacement sealed authored canary 계약

## 지위와 목적

기존 32개 authored canary는 첫 sealed 실행 결과를 보존한 채
`adaptive_validation_diagnostic_only`로 강등됐다. 질문·gold·집계 artifact는 수정하거나
삭제하지 않으며, 다시 sealed benchmark로 사용하지 않는다.

이 계약은 강건 라우팅 접근의 일반화를 검증할 **새 authored canary**의 표본과 gate만
고정한다. 아직 질문·gold를 작성하지 않는다. 기존 adaptive 32개와 63개 dev를 본
주체는 질문이나 gold를 작성할 수 없다. 별도 작성자와 사람 검수자가 참여하더라도
이를 independent holdout이라 부르지 않고 `separately_authored_human_reviewed_canary`로
기록한다. 기존 frozen blind는 계속 접근하지 않는다.

## 선행 순서

1. 새 키워드 규칙 없이 불확실성 기반 multi-store 검색 또는 confidence-gated broad
   fallback 중 하나를 독립 A/B 접근으로 구현한다.
2. 기존 adaptive dev에서 기능·회귀만 확인하되, 강등된 32개 실패 문항을 보고
   규칙을 맞추지 않는다.
3. 실행 코드·설정·corpus·index hash를 freeze한다.
4. 그 hash를 보지 않아도 되는 별도 작성자가 아래 빈 slot에 질문·gold를 작성한다.
5. 사용자 또는 별도 사람이 질문, 모든 required evidence group, 시간·revision 상태를
   검수한다.
6. immutable export 후 한 번만 sealed 실행한다.

실패 사례를 열어 접근을 수정하면 이 새 세트도 즉시 `adaptive_validation`으로
강등하며 sealed 평가에 재사용하지 않는다.

## 표본 구성

- 총 40개, 8개 공식 출처마다 5개
- 출처별 `single_current`, `compound_without_surface_keywords`, `partial`,
  `ambiguous_route`, `source_safety` 각 1개
- 복합 질문은 `각각`, `비교`, `함께` 없이 모든 요구 slot을 포함
- `ambiguous_route`는 출처명을 직접 말하지 않거나 둘 이상의 store가 그럴듯한 질문
- source safety에는 historical, comparison, preview, false, realtime 통제를 포함
- 질문 패턴과 atomic claim은 63 dev 및 강등된 32개와 분리
- parent document도 가능한 모든 slot에서 두 세트와 분리한다. current 운영정책과
  current 이달의 아이템처럼 corpus상 불가능한 예외는 사전에 명시하고 chunk·claim
  분리는 유지한다.
- 질문·gold 작성자는 retrieval 결과와 강등된 case-level artifact를 볼 수 없다.

## 사전고정 지표와 GO/NO-GO

모든 비율은 분자·분모 및 Wilson 95% 구간을 함께 보고한다. 표본이 작아 source별
4~5개라는 한계를 명시한다.

| 지표 | GO gate |
|---|---:|
| route action exact | 0.85 이상 |
| 같은 코드의 frozen development 대비 route 하락 | 0.05 이하 |
| retrieval all-required evidence recall | 0.90 이상 |
| selected evidence-group hit | 0.85 이상 |
| cited evidence-group hit | 0.85 이상 |
| claim completeness | 0.90 이상 |
| 기존 canonical baseline 대비 strict regression | 0건 |
| strict improvement | 1건 이상 |
| 출처별 최저 all-required retrieval | 0.66 이상, 0-hit 출처 없음 |
| temporal/revision violation | 0건 |
| false/realtime evidence exposure | 0건 |
| partial disclaimer | 8/8 |

하나라도 실패하면 전체 결과는 `NO-GO`다. 출처별·stratum별 결과와 fallback 사용률도
진단 지표로 보고하되, 결과를 본 뒤 gate를 바꾸지 않는다.

## 범위 제한

이 계약 freeze는 라우터·retriever·selector·reranker를 수정하지 않는다. 자연어
Generator, NLI 추가학습, LoRA/RAFT, 구조화 store/API, final blind 평가도 수행하지
않는다. 강건 라우팅 gate가 통과하기 전에는 CLAIM_COVERAGE의 의미 기반 slot
coverage나 VERIFY의 구조적 차단 구현을 먼저 쌓지 않는다.
