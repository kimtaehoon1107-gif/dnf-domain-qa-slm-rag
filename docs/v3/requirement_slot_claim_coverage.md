# DNF RAG v3 requirement-slot claim coverage pilot

## 지위와 범위

이 문서는 Round 4 무료 사전검증의 사전 고정 계약이다. Signal A의 Kiwi 기반
answer-target 구조 분석은 변경하지 않고 slot 열거기로 재사용한다. 기존 검색 결과만
입력으로 사용하며 router, decomposition, retrieval, 기존 canonical claim reranker는
변경하지 않는다. 출력은 canonical chunk의 연속 원문 인용과 고정 template만 허용하고
자유형 생성은 사용하지 않는다.

## Runtime 계약

1. 기존 answerability/route action이 `reject`, `realtime_api`, `clarify`이면 기존 출력을
   그대로 반환한다.
2. Signal A가 두 개 이상의 target을 열거하지 않으면 기존 단일-field 출력을 그대로
   반환한다.
3. 다중 target이면 기존 retrieval artifact의 chunk만 사용한다. gold chunk, document,
   source ID와 evidence span은 runtime 함수에 전달하지 않는다.
4. target별 명사형 content morph와 exact extractive quote의 morph overlap을 계산한다.
   quote에는 질문에 없던 content morph가 하나 이상 있어야 answer-value proxy를
   통과한다. domain field/intent keyword 목록은 사용하지 않는다.
5. 한 parent 안에서 가장 많은 slot을 덮는 parent를 선택한다. 각 covered slot은 해당
   parent의 canonical chunk에서 뽑은 연속 quote와 citation을 하나씩 가진다.
6. 모든 slot이 covered이면 `full`, 일부만 covered이면 `partial`이다. missing slot은
   질문에서 추출한 morph label과 고정 문구 `검색된 공식 문서에서 확인할 수 없습니다.`로
   표시한다. 근거가 없는 slot에는 citation을 붙이지 않는다.
7. 기존 answerability가 `partial`이면 기존 공식정보 한정 disclaimer를 유지한다.

## 사전 고정 임계 선택

- overlap threshold grid: `0.50, 0.60, 0.70, 0.80, 0.90, 1.00`
- 32-set aggregate만 임계 선택에 사용한다. 개별 실패 질문을 보거나 문항별로
  조정하지 않는다.
- runtime 안전 gate를 먼저 적용한다: exact-extractive/citation verification failure 0,
  strict unsupported slot citation 0, false-partial 0, 단일-field citation regression 0.
- 안전 gate를 만족하는 설정 중 다음 순서로 고른다.
  1. same-parent multi-field claim-complete case 최대
  2. same-parent multi-field cited evidence-group hit 최대
  3. evaluation-only Signal A slot recall 최대
  4. evaluation-only Signal A slot precision 최대
  5. 더 높은 threshold
- 안전 gate를 만족하는 threshold가 없으면 동일 우선순위로 diagnostic threshold만
  고르되 결과는 자동 NO-GO다.
- 선택 후 63 dev를 한 번만 실행한다. 63 dev 결과로 threshold를 다시 바꾸지 않는다.

## 지표 정의와 GO gate

- cited coverage: required evidence group 중 새 citation이 acceptable chunk를 맞힌 수.
- claim completeness: required group 전부가 인용되고 각 group의 gold span token recall이
  0.50 이상인 문항 수.
- runtime false-citation: exact quote, citation lineage, source/time/revision 검증에 실패한
  claim 수.
- strict unsupported slot citation: 평가 시 slot과 정렬된 required group 중 어느
  acceptable chunk에도 속하지 않는 citation 수.
- false-partial: runtime이 missing slot을 선언했지만 평가상 모든 required group이 이미
  새 citation으로 충족된 문항 수.
- partial disclaimer accuracy: answerability `partial` 문항의 기존 disclaimer 보존과
  missing slot별 고정 불가 문구의 정확성을 별도로 측정한다.

GO는 32-set same-parent multi-field에서 cited coverage와 claim completeness가 모두
현재 canonical baseline보다 증가하고, 32와 63에서 단일-field citation regression,
runtime false-citation, strict unsupported slot citation, false-partial이 모두 0일 때만
가능하다. 63 dev에는 same-parent multi-group 문항이 없으므로 해당 개선율은
`not_measured`로 보고하고 전체 canonical citation regression 0을 요구한다.

이 gate를 통과하기 전 새 40-canary를 작성하거나 실행하지 않는다. 실패 artifact는
development-only NO-GO로 보존한다.

## Aggregate-only 문법 정제 1회

최초 v3.1.0 무료 실행은 selected threshold 0.50에서 same-parent cited group이
19→17/35, complete row가 3→2/15로 악화했고, 32-set false-partial 7건과
single-field regression 2건을 만들었다. 이 artifact는 development-only NO-GO로
보존한다.

개별 질문을 열지 않은 구조 집계에서 clause-only Signal A 후보는 32-set에서
multi 5 대 single/zero 10, 63 dev에서 multi 0 대 single/zero 26이었다. 반면 32-set의
coordinated-nominal 후보 10건은 모두 multi였다. 따라서 지시가 허용한
`수식어 vs 답명사` 문법 정제를 다음 한 번으로 사전 고정한다.

- Signal A 전체를 변경하지 않고 coordinated nominal target만 runtime slot으로
  활성화한다. clause signal은 보존하되 claim-output activation에는 사용하지 않는다.
- 기존 canonical citation과 claim은 절대 교체하거나 제거하지 않는 augment-only로
  바꾼다.
- 기존 citation이 가리키는 parent가 retrieval pool에 있으면 그 parent 안에서만 새
  slot claim을 찾는다.
- 새 claim verifier가 실패하면 새 출력을 fail-open하지 않고 canonical baseline을
  그대로 반환한다.
- threshold grid, 선택 순서, GO gate는 최초 계약에서 변경하지 않는다.

이 정제는 domain field/intent keyword를 추가하지 않으며 동일 32 aggregate를 한 번
재실행한다. 다시 실패하면 추가 형태소 조정 없이 NO-GO로 종료한다.
