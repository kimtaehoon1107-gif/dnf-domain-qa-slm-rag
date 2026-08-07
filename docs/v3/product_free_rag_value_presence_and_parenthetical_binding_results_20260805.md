# Product Free RAG 값 존재·괄호 결합 진단 결과

작성: 2026-08-05  
결론: **M단계 완료 / P단계 GO / 런타임 적용 없음**

## 실행 범위

- 런타임 코드는 수정하지 않았다.
- Qwen 호출은 0회다.
- A6 저장 candidate와 현재 BGE 재랭커로 evidence pack만 재구성했다.
- 판정 기준은 기존 좌표 overlap이 아니라 요구별 `value_present`다.

## M1·M2 — `value_present` 측정기

요구에 배정되는 unit은 같은 `chunk_id`에서 골드 좌표와 겹치는 pack unit이다.
배정된 unit 텍스트를 합친 뒤 `required_values`의 각 값을 따로 검사한다.

- 전부 존재: `value_present_full`
- 일부 존재: `value_present_partial`
- 하나도 없음: `value_present_none`
- 불리언: 의미 판정이 별도로 필요하므로 이번 합산에서 제외
- unsupported: 값 존재 대상에서 제외

숫자·통화·시각 정규화는 `src/v3/value_normalization.py`의
`number_values`, `currency_values`, `time_values`를 재사용했다. 날짜는 A6의
ISO/한글/2자리 연도 표기를 같은 ISO 날짜로 정규화했다. 서술형 값은 쉼표와
띄어쓰기, `번 → 회`, 가능 표현과 부정 종결을 정규화한 뒤 토큰 포함률
**0.8**을 사용했다. 대상과 값의 결합을 보존하기 위해 숫자만 같고 대상 토큰이
없는 표 행은 통과시키지 않았다.

회귀 예시는 모두 통과했다.

- `2025-09-11 점검 후` ↔ `25.09.11 점검 후`
- `숫자 6자리` ↔ `6자리 숫자`
- `264칸` ↔ `264 칸`
- `2,000만 골드` ↔ `2000만 골드`

## M3 — A6 새 기준선

| 항목 | 결과 |
|---|---:|
| A6 슬롯 | 32 |
| 전체 요구 | 61 |
| 골드 좌표 | 62 |
| 측정 가능한 supported 비불리언 요구 | 49 |
| `value_present_full` | 39 |
| `value_present_partial` | 4 |
| `value_present_none` | 6 |
| 불리언 별도 분류 | 8 |
| unsupported 제외 | 4 |

슬롯 기준은 full 21, partial 7, none 3, boolean-only 1이다. 이 수치는
요구 단위이므로 기존의 좌표 overlap `55/62`와 직접 같은 분모의 점수가 아니다.
앞으로 성공 판정에는 `value_present`를 사용한다.

### overlap은 true지만 값이 완전하지 않았던 전건

| 슬롯·요구 | 판정 | 원인 |
|---|---|---|
| A6-1 `transfer_limits` | partial | 표의 4개 한도 중 2개 행만 pack에 존재 |
| A6-7 `base_cooldown_change` | none | `(20초 → 18초)`가 별도 고아 unit으로 분리 |
| A6-13 `mypin_properties` | partial | `연 5회 재발급` 문장 미진입 |
| A6-17 `mold_trade_types` | partial | 일반 거푸집 문장 미진입 |
| A6-26 `contract_price_duration` | partial | 가격 표 행 미진입 |
| A6-29 `august_special_box_prices` | none | 가격 행에는 두 상품 주어가 없어 값-대상 결합 부재 |

원인 분류는 괄호 분리 1, 표 분리 3, 그 외 pack 선택 2다.

## P3-1 — 숫자 고아 단편 전수 추출

첫 광역 추출은 198건이었다. 이 중 94건은 `[TABLE]` 표식 없이 파이프(`|`)
형태로 남은 표 행이 문장처럼 분리된 것으로, 표 파서 문제이므로 이 모집단에서
분리했다. 최종 사람 검토 모집단은 **104건**이다.

| 유형 | 건수 |
|---|---:|
| 그 외 | 57 |
| 완결 괄호형 | 44 |
| 기호 접두형 | 2 |
| 단독 숫자형 | 1 |
| 화살표형 | 0 |

출처별로 account policy 34, event 22, FAQ 15, game guide 13,
general notice 9, shop product 9, maintenance 1, patch note 1건이다.

## P3-2 — 사람 전수 검토

검토자: Codex  
검토 시각: 2026-08-05 17:30:06 +09:00

| 판정 | 건수 | 설명 |
|---|---:|---|
| 결합해야 함 | 44 | 앞 문장의 수치·기한·조건인 완결 후행 괄호 |
| 결합하면 안 됨 | 53 | 독립 문장, 목록 번호, 오류 코드, OCR 단편 |
| 애매함 | 7 | chunk 경계에서 괄호와 날짜 문장이 미완성으로 잘림 |

104건 전부에 행별 판정과 근거를 저장했다. 애매한 7건은 이번 규칙이 선택하지
않으며, chunk 경계 문맥 문제로 별도 취급한다.

## P3-3 — 검토 후 도출한 구조 규칙

다음 조건을 모두 만족할 때만 shadow에서 앞 sentence unit과 결합했다.

1. 두 unit이 같은 줄에 있고 사이에는 공백만 있다.
2. 앞 unit은 `.`, `!`, `?`로 끝난다.
3. 뒤 unit은 여는 괄호로 시작하고 닫는 괄호로 끝난다.
4. 괄호 수가 균형을 이루고 숫자를 포함한다.
5. 뒤 unit 길이는 30자 이하다.
6. 뒤 unit에 독립 서술어 종결이 없다.

스킬명·아이템명·문서명·특정 숫자는 사용하지 않았다. 사람 판정과 비교하면
true positive 44, true negative 53, 보류 미선택 7, false positive 0,
false negative 0이다.

## P3-4 — shadow 결과

| 게이트 | 결과 |
|---|---|
| A6-7 `20초`·`18초` 모두 존재 | PASS (`none → full`) |
| M3 기준선 대비 `value_present` 감소 | PASS (0건) |
| 사람 검토 비대상 오선택 | PASS (0건) |
| 좌표-원문 불일치 | PASS (0건) |
| 저장 baseline 재현 | PASS (32/32) |

값 판정이 바뀐 요구는 A6-7 하나뿐이다.

pack 좌표 집합이 바뀐 슬롯은 2개다.

- A6-7: `189:212` 문장과 `213:224` 괄호가 `189:224`로 결합됐다.
  다른 7개 pack unit은 유지됐다.
- A6-13: `81:113` 문장과 `114:123` 괄호가 `81:123`으로 결합됐다.
  중복 한 칸이 비면서 공동인증서 문장 하나가 E8에 들어왔지만
  `mypin_properties`는 여전히 `연 5회 재발급`이 없어 partial이며 감소는 없다.

paired 32-pack 측정에서 candidate rerank 합계는 baseline 40,505.534ms,
shadow 38,584.240ms로 -1,921.298ms(-4.74%)였다. 평균은 각각
1,265.798ms와 1,205.758ms다. 지연은 게이트가 아니며 한 번의 paired
측정이므로 성능 향상으로 해석하지 않는다.

## 회귀와 최종 판정

- 관련 회귀: **154 passed**
- `tests/v3` 전체: **1233 passed, 기존 실패 2, 67 subtests passed**
- 기존 실패 2건은 지시서에 명시된 frozen manifest SHA 불일치와 동일하다.
- 새 실패: 0
- Qwen 호출: 0
- 런타임 변경: 없음

따라서 **P단계는 GO**다. 이번 문서 범위에서는 진단·측정만 했으므로 현재
`product_free_rag_v1` 동작은 바뀌지 않았다. 다음 별도 라운드는 이 결합 규칙을
런타임에 적용하고, 그 위에 표 주어 바인딩을 다시 얹어 A6-7 두 절을 함께
검증하는 것이다.
