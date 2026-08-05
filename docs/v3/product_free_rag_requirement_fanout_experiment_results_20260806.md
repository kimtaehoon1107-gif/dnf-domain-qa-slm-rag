# Product Free RAG 요구별 fan-out 실험 결과

작성: 2026-08-06  
평가 성격: adaptive 구조 진단, blind·공식 A6 아님

## 결론

요구별 fan-out은 두 문항 모두에서 요구 격리를 완성하지 못했다. A6-7은 첫
호출이 정답 외 오답을 추가했고, A6-32는 두 번째 호출이 `unsupported` 대신
첫 번째 명성 답을 반복했다. 엄격 F1 핵심 게이트는 0/2다.

인용 좌표는 모두 정확했지만 A6-7 총 지연이 30초 게이트를 0.219초
초과했다. 사전 등록한 중단 규칙에 따라 F2와 F3는 실행하지 않았다.

런타임 기본값은 바꾸지 않았다. `use_requirement_fanout=False`가 기본이며,
실험 플래그를 명시적으로 켠 경우에만 fan-out이 발동한다.

## F0 — Kiwi 절 경계 필터 위치

### 변경과 롤백

- 실험 커밋: `2bbc4f2` (`allowed_forms={"고"}`를 경계 검사 안으로 이동)
- 롤백 커밋: `85abb3e`
- 최종 런타임: F0 변경 없음

### 202문항 전수 변화

- 전체 gap: 82 → 74
- A6 gap: 11 → 4
- EXISTING32 gap: 19 → 18
- `kiwi_requirement_queries`가 바뀐 문항: 11/202
- 목표 gap을 복구한 문항: 8/8

| 문항 | `kiwi_n` | gap | 판정 |
|---|---:|---:|---|
| A6-4 | 0 → 2 | 해소 | 목표 복구 |
| A6-7 | 0 → 2 | 해소 | 목표 복구 |
| A6-10 | 0 → 2 | 해소 | 목표 복구 |
| A6-16 | 0 → 2 | 해소 | 목표 복구 |
| A6-21 | 0 → 2 | 해소 | 목표 복구 |
| A6-22 | 0 → 2 | 해소 | 목표 복구 |
| A6-26 | 0 → 2 | 해소 | 목표 복구 |
| EXISTING32-19 | 0 → 2 | 해소 | 목표 복구 |
| A5-13 | 0 → 2 | 불변 | 과분해·실제 회귀 |
| SEALED64-29 | 0 → 2 | 불변 | 비목표 변화 |
| SEALED64-42 | 0 → 2 | 불변 | 비목표 변화 |

나머지 191문항은 `kiwi_requirement_queries`와 `kiwi_n`이 불변이다. 202건
각 행은 다음 두 원본 artifact에 기록했다.

- 변경 전: `reports/v3/product_free_rag_requirement_fanout_f0_before_20260806.jsonl`
- 변경 후: `reports/v3/product_free_rag_requirement_fanout_f0_after_20260806.jsonl`

### 값·모드 재생

A6 32문항의 저장된 검색 후보에서 atomic pack을 다시 계산했다. Qwen 호출은
0회였다.

- 측정 가능한 requirement: 49
- numeric·date·time·currency `value_present` 감소: 0
- descriptive diagnostic 감소: 0
- 모드 변경: A6-26 한 건, `answer → partial` (악화)
- 저장 결과와 F0 이전 verifier replay의 기존 drift: A6-30 한 건
  (`answer → unsupported`), F0 전후에는 불변

Artifact:

- 값 재생: `reports/v3/product_free_rag_requirement_fanout_f0_value_after_20260806.jsonl`
- 모드 재생: `reports/v3/product_free_rag_requirement_fanout_f0_mode_replay_20260806.jsonl`

### 회귀와 F0 게이트

`아이템 잠금 해제 때 등록된 OTP로 인증하면 72시간을 기다리지 않고 바로
풀 수 있어?`에서 `않고`가 새 경계로 오인됐다. 관계 질의가 세 조각으로
깨지면서 기존 의미 회귀 테스트가 실패했다.

| 게이트 | 결과 |
|---|---|
| 목표 8건 0 → 2 복구 | 통과 |
| numeric·date·time·currency 감소 0 | 통과 |
| 기본 router·coverage 호출 동작 불변 | 통과 |
| 전체 회귀 green, 면제 2건 제외 | **실패** |
| 202문항 전수 변화 기록 | 통과 |
| 모드 변경 개별 판정 | **A6-26 악화** |

결론: 필터 위치 변경은 8건을 복구하지만 비목표 과분해와 mode 악화를
만들어 NO-GO로 판정하고 롤백했다. F1은 지시서대로 기존 절 분해를 사용했다.

## 구현 — opt-in requirement fan-out

- 구현 커밋: `503bc4b`
- 플래그: `use_requirement_fanout`, 기본값 `False`
- 발동: 메타데이터 경로가 아니고, coverage 계약이 꺼져 있으며,
  `_runtime_requirement_queries` 결과가 2개 이상일 때
- 절당 구성: 기존 검색 → compact atomic evidence pack 최대 8개 → Qwen 1회
- 인용: 호출 내부 `E1`을 병합 시 `F1E1`, `F2E1`처럼 다시 매핑하고 원문
  좌표를 그대로 보존
- 병합: 전부 answer면 answer, 전부 unsupported면 unsupported, 혼합이면
  partial, 하나라도 clarification이면 clarification
- 단일 요구: 기존 `_answer_single` 경로를 그대로 호출

전체 v3 회귀는 1267 passed였다. 실패 2건은 지시서에 명시된 기존 SHA
면제 항목뿐이다.

## F1 — A6-7과 A6-32

실행 artifact:

- 최초 자동 판정 포함 원본:
  `reports/v3/product_free_rag_requirement_fanout_f1_20260806.jsonl`
- 엄격 저장 출력 재채점:
  `reports/v3/product_free_rag_requirement_fanout_f1_strict_rescore_20260806.jsonl`

### A6-7

질문:

> 6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 줄었고,
> 질풍 개화 옵션의 기본 쿨타임은 몇 초에서 몇 초로 바뀌었어?

기존 답변:

> 타이드 바운드 쿨타임은 12초에서 9초로 줄었습니다.  
> 질풍 개화 옵션의 기본 쿨타임은 12초에서 9초로 바뀌었습니다.

fan-out 절 1 결과:

1. `타이드 바운드 쿨타임이 기본 12초에서 9초로 줄었습니다.` — F1E1
2. `타이드 바운드 쿨타임이 20초에서 18초로 줄었습니다.` — F1E3

fan-out 절 2 결과:

1. `질풍 개화 옵션의 기본 쿨타임은 12초에서 9초로 바뀌었어` — F2E1

정답 `20→18`, `12→9`는 모두 복구했지만 절 1이 타이드 바운드에
`12→9`를 추가로 잘못 귀속했다. “Q1은 20→18만, Q2는 12→9”라는 요구
격리 게이트를 통과하지 못했다.

- 핵심 게이트: 실패
- 인용 좌표: 통과
- Qwen 호출: 2
- 총 지연: 30,218.685ms — 실패

### A6-32

질문:

> 2025년 10월 시브의 보조장비 보주는 모험가 명성이 얼마 붙었고,
> 계정당 구매 제한은 몇 개였어?

기존 답변: `unsupported`, 노출 답변 없음.

fan-out 절 1:

> 2025년 10월 시브의 보조장비 보주는 모험가 명성 +221 붙음 — F1E1

fan-out 절 2:

> 2025년 10월 시브의 보조장비 보주는 모험가 명성 +221를 제공합니다. — F2E1

최종 출력은 `partial`이고 구매 제한을 추측해 노출하지는 않았다. 그러나 절
2가 `unsupported`가 되지 않고 절 1의 명성 답을 반복했다. 요구 단위 격리가
완료되지 않았으므로 사전 등록한 엄격 게이트는 실패다.

- 핵심 게이트: 실패
- 인용 좌표: 통과
- Qwen 호출: 2
- 총 지연: 15,113.293ms — 통과

### F1 종합

| 게이트 | 결과 |
|---|---|
| A6-7 요구 격리 | 실패 |
| A6-32 supported/unsupported 격리 | 실패 |
| 인용 좌표 복원 | 통과 |
| 각 문항 30초 이하 | 실패 |
| 총 Qwen 호출 | 4 |

초기 자동 체크는 A6-7에서 필요한 값이 “존재하는지만” 봐서 오답 추가를
놓쳤다. 저장 출력 엄격 재채점에서는 요구별 금지 값과 `unsupported` 상태를
함께 검사하도록 고쳤으며, 추가 Qwen 호출은 없었다.

## 중단 결정

F1 핵심 2건이 모두 실패했다. 지시서의 사전 등록 규칙에 따라:

- F2 USER10: 미실행
- F3 adaptive A6 32: 미실행
- fan-out 런타임 승격: 미채택
- 기존 `product_free_rag_v1` 기본 경로: 유지

실험 결론은 “한 호출에 복수 요구를 넣는 문제”만이 병목은 아니라는 것이다.
요구별 독립 호출로도 8B 모델은 관련 표 행의 인접 값을 같은 대상에 잘못
귀속하거나, 지원되지 않은 요구에서 이미 답한 사실을 반복했다. 구조 분리는
일부 정답 회수에는 도움이 됐지만 요구 격리를 보장하지 못했다.
