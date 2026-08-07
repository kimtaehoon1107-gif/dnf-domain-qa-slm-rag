# Product Free RAG 요구별 claim 계약 재평가 — 2026-08-05

## 결론

1단계는 **NO-GO**다. 요구별 claim 계약은 A6-32의 지원값을 살려 최종 결과를
`unsupported`에서 `partial`로 개선했지만, 사전 등록된 게이트를 엄격히 적용하면
A6-7과 A6-32를 모두 해결하지 못했다.

- A6-7: Q1/Q2 분리는 성공했지만 Q1 값이 `20초→18초`가 아니라
  `12초→9초`로 잘못 결합됐다.
- A6-32: `+221` 노출과 최종 partial은 성공했지만, 모델은 구매 제한을
  `unsupported_question_refs`에 넣지 않고 `제한 없음`으로 추측했다. 이 claim은
  기존 최소 검증기가 거절했고, 그 결과에 따라 서버가 Q2를 unsupported로
  내렸다.
- 두 ON 실행 모두 계약 검증 오류는 없었다.

따라서 지시서의 중단 규칙에 따라 A6 32문항 ON 및 USER10 v2는 실행하지 않았다.
런타임 기본값은 계속 `use_question_coverage_contract=False`다.

## 실험 조건

- 고정 문항: A6-7, A6-32
- OFF: `use_question_coverage_contract=False`
- ON: `use_question_coverage_contract=True`
- 나머지 설정: 동일
  - identity shortlist ON
  - compact evidence pack ON
  - atomic evidence reranker ON
  - CUDA model handoff ON
  - R1 괄호 값 결합 및 R2 표 도입문 결합 포함
- 모델: `qwen3-8b:ctx8192`
- Qwen 호출: OFF 2회 + ON 2회 = 총 4회

실행 원본:

- `reports/v3/product_coverage_contract_a6_slots7_32_off_20260805.jsonl`
- `reports/v3/product_coverage_contract_a6_slots7_32_on_20260805.jsonl`

## 1단계 — A6-7

질문:

> 6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 줄었고,
> 질풍 개화 옵션의 기본 쿨타임은 몇 초에서 몇 초로 바뀌었어?

정답 요구:

- Q1: 타이드 바운드 쿨타임 `20초→18초`
- Q2: 질풍 개화 옵션 기본 쿨타임 `12초→9초`

### OFF 답변 전문

> 타이드 바운드 쿨타임은 12초에서 9초로 줄었고, 질풍 개화 옵션의 기본
> 쿨타임은 12초에서 9초로 바뀌었다.

### ON 답변 전문

> 타이드 바운드 쿨타임이 12초에서 9초로 줄었고
>
> 질풍 개화 옵션의 기본 쿨타임은 12초에서 9초로 바뀌었어

ON 원시 claims:

```json
[
  {
    "question_ref": "Q1",
    "text": "타이드 바운드 쿨타임이 12초에서 9초로 줄었고",
    "evidence_refs": ["E1"]
  },
  {
    "question_ref": "Q2",
    "text": "질풍 개화 옵션의 기본 쿨타임은 12초에서 9초로 바뀌었어",
    "evidence_refs": ["E1"]
  }
]
```

ON 원시 `unsupported_question_refs`:

```json
[]
```

계약은 두 요구를 별도 claim으로 만들었지만, 표 도입문이 붙은 E1을 Q1에도
사용하면서 Q1 관계를 잘못 해석했다. 정답 E3의 `20초→18초`는 pack에 있었으므로
검색·pack 누락이 아니라 생성 단계의 요구-근거 결합 실패다.

**게이트 1: FAIL**

## 1단계 — A6-32

질문:

> 2025년 10월 시브의 보조장비 보주는 모험가 명성이 얼마 붙었고, 계정당 구매
> 제한은 몇 개였어?

정답 요구:

- Q1: 모험가 명성 `+221`
- Q2: 코퍼스 근거 없음 — unsupported

### OFF 답변 전문

> (노출 답변 없음 — unsupported)

OFF 원시 생성 claim은 다음처럼 지원값과 추측값을 한 문장에 합쳤고, 기존
검증기가 claim 전체를 거절했다.

> 2025년 10월 시브의 보조장비 보주는 모험가 명성 +221이 붙었고, 계정당 구매
> 제한은 1개였다.

### ON 답변 전문

> 221

최종 mode는 `partial`이다.

ON 원시 claims:

```json
[
  {
    "question_ref": "Q1",
    "text": "221",
    "evidence_refs": ["E1"]
  },
  {
    "question_ref": "Q2",
    "text": "제한 없음",
    "evidence_refs": ["E7"]
  }
]
```

ON 원시 `unsupported_question_refs`:

```json
[]
```

서버 검증 결과:

```json
{
  "accepted_question_refs": ["Q1"],
  "server_unsupported_question_refs": ["Q2"],
  "rejected_claim": {
    "text": "제한 없음",
    "reasons": ["required_factual_value_missing"]
  }
}
```

최종 사용자 결과는 안전하고 유용해졌다. 하지만 사전 등록 게이트는 모델이
구매 제한을 직접 `unsupported_question_refs`로 분리하는 것을 요구한다. 모델은
근거 없는 `제한 없음`을 먼저 주장했고 서버 검증기에 의존했으므로 엄격한
게이트는 통과하지 못했다.

**게이트 2: FAIL**

## 계약 검증

| 슬롯 | `contract_valid` | `issues` |
|---|---:|---|
| A6-7 | true | `[]` |
| A6-32 | true | `[]` |

**게이트 3: PASS**

여기서 `contract_valid=true`는 Q번호가 중복·누락 없이 형식 계약을 지켰다는
뜻이다. 각 Q의 사실 판단이 정확하다는 뜻은 아니다.

## 단계 진행 판정

사전 등록 규칙은 게이트 1 또는 2 중 최소 하나가 통과해야 2단계로 진행하도록
정했다.

| 게이트 | 결과 |
|---|---|
| 1. A6-7 두 값·두 Q 정확성 | FAIL |
| 2. A6-32 +221 + 모델 unsupported 분리 | FAIL |
| 3. 계약 위반 0건 | PASS |

게이트 1·2가 모두 실패했으므로:

- A6 32문항 ON: 실행하지 않음
- USER10 v2 ON/OFF: 실행하지 않음
- A6 공식 adjudication: 변경 없음
- 런타임 기본값: 변경 없음

## 해석과 다음 선택지

이번 결과는 계약이 쓸모없다는 뜻은 아니다. claim을 요구별로 나눈 덕분에
A6-32에서 한 요구의 오류가 다른 지원값까지 지우는 문제는 막았다. 다만 현재
계약만으로는 다음 두 문제를 해결하지 못한다.

1. 여러 근거 중 각 Q에 맞는 관계와 값을 선택하는 문제(A6-7)
2. 관련 문장이 있어도 질문한 속성의 직접 근거가 없을 때 unsupported를 고르는
   문제(A6-32 원시 출력)

따라서 기본값 전환이나 전체 재실행은 하지 않는다. 다음 라운드를 연다면
`PRODUCT_COVERAGE_SYSTEM_INSTRUCTIONS` 수정과 다른 접근을 섞지 말고, 위 두 실패
중 하나만 겨냥한 별도 소규모 A/B로 설계해야 한다.

## 회귀 확인

- 커버리지 계약 단위 테스트: 3 passed
- 전체 Product Free RAG 회귀: 125 passed
- 기존 면제 2건은 이번 변경 범위 밖이며 수정하지 않음
