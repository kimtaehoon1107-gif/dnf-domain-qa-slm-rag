# DNF RAG v3.2 promotion canary contract

## 목적

이 canary는 표 row-level atomic fact, 전역 temporal overlay, duplicate-family metadata를
연결한 v3.2 개발 후보가 처음 보는 질문에서도 기존 dirty canonical보다 안전하고 완전한지
검증한다. 기존 32문항 authored canary는 이미 결과를 열어 본 adaptive validation이므로
재사용하지 않는다. 기존 frozen blind에도 접근하지 않는다.

이 문서는 질문·gold를 보기 전에 표본 구성, 실행 대상, 지표와 GO/NO-GO 기준을 고정한다.
현재 단계는 계약과 빈 슬롯만 freeze한다. 질문·gold 작성, 사람 검수, sealed 실행은 아직
허용되지 않는다.

## 고정 실행 대상

- Baseline: dirty canonical backbone, v3.2 candidate 기능 OFF
- Candidate: 같은 dirty canonical backbone에 표 atomic fact, global temporal overlay,
  duplicate-family overlay를 additive로 연결한 개발 후보 ON
- Planner: `qwen3:8b`, temperature 0, 고정 prompt SHA
- 검색·reranker·assembler 설정은 manifest에 기록된 기존 frozen 설정을 그대로 사용
- 두 arm의 차이는 v3.2 candidate overlay ON/OFF뿐이며 corpus, 질문, gold는 동일

## 표본 계약

- 총 40문항, 8개 공식 source마다 5문항
- source별 current single, multi-field, 구조화/표·revision·duplicate 특화 문항과
  historical/preview/expired/personal 안전 통제를 포함
- 질문 패턴·atomic claim은 63 dev와 강등된 32 authored canary에서 분리
- 가능한 경우 parent document도 분리한다. 현재 정책 revision이나 유일한 current monthly
  parent처럼 불가능한 예외는 사유를 먼저 기록한다.
- 질문·gold 작성자는 retrieval 결과, 기존 adaptive case-level 실패 artifact를 보지 않는다.
- 별도 사람이 모든 질문, requirement, evidence group, temporal 상태를 검수한다.
- 이 세트는 `separately_authored_human_reviewed_canary`이며 independent holdout이나 final
  benchmark로 부르지 않는다.

## gold 단위

각 문항은 atomic requirement와 required evidence group을 갖는다. 각 evidence group은
acceptable chunk ID, parent document ID, 원문 exact evidence span을 포함한다. 표 문항은
행의 subject·attribute·value·unit 귀속을 gold에 명시한다. current 질문은 허용 revision과
금지 revision/status도 함께 기록한다.

## 사전 고정 gate

모든 비율은 분자/분모와 Wilson 95% 구간을 함께 보고한다. 하나라도 실패하면 전체는
NO-GO다.

| 지표 | GO 기준 |
|---|---:|
| candidate all-required evidence-group coverage | baseline 이상 |
| strict question regression | 0건 |
| strict improvement | 1건 이상 |
| false-full | 0건 |
| exact citation slice | 100% |
| table row subject-attribute-value completeness | 100% |
| temporal/revision/preview/expired 누출 | 0건 |
| current 질문의 denied revision 인용 | 0건 |
| reject/realtime/personal 통제의 evidence 노출 | 0건 |
| duplicate-family 대상의 provenance 누락 | 0건 |
| source별 all-required coverage | 0-hit source 0개, 각 source 4/5 이상 |

`false-full`은 full answer로 표시했지만 하나 이상의 required evidence group 또는 요구값을
정확히 지지하지 못한 경우다. exact substring은 안전장치일 뿐 의미 지지의 충분조건으로
간주하지 않는다.

## sealed 규율

1. 이 계약, 빈 슬롯, runtime·artifact hash를 먼저 freeze한다.
2. 별도 작성자가 질문·gold를 작성한다.
3. 별도 사람이 전수 검수하고 immutable export한다.
4. 그 뒤 Baseline/OFF와 Candidate/ON을 한 번만 실행한다.
5. 결과를 열고 코드·설정·gold를 바꾸면 즉시 adaptive validation으로 강등하며 sealed로
   재사용하지 않는다.

## 현재 금지

- 질문·gold가 비어 있거나 독립 사람 검수가 끝나지 않은 상태의 점수 실행
- 기존 32 authored canary의 sealed 재사용
- frozen blind 접근
- 결과를 본 뒤 임계, K, prompt, gold 조정
- canonical/runtime 승격, 학습, 자유 생성

