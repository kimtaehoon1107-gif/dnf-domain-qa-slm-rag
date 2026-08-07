# Product Free RAG 요구별 근거 예약 재측정 — 2026-08-05

## 결론

사전 등록한 두 게이트를 모두 통과해 **GO**다.

- 게이트 1: 조건 B에서 E3 `189-224`가 A6-7 첫 절에 명시적으로 예약됨
- 게이트 2: M3 대비 numeric/date/time/currency value 감소 0건
- Qwen 호출: 0
- 런타임 변경: 없음

따라서 다음 단계는 별도 라운드에서 요구별 예약을 런타임에 적용하고,
A6-7 라이브로 두 절을 확인하는 것이다.

이번 결과는 기존 S3 기각을 번복하지 않는다. 기존 S3는 A6-1·4·22의
골드 근거를 새로 pack에 들이는지 물었고 0/3이었다. 이번 진단은 R1 이후
새로 생긴 A6-7 E3를 첫 요구에 예약할 수 있는지를 측정한 별개 실험이다.

## 게이트 1 — A6-7 요구별 배정

질문은 explicit fallback에서 다음 두 절로 분해됐다.

```text
1. 6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 줄었고
2. 질풍 개화 옵션의 기본 쿨타임은 몇 초에서 몇 초로 바뀌었어
```

### 요구 1: base_cooldown_change

골드 좌표 기준 배정은 A/B 모두 E3였다.

```text
E3  chunk_sha256_b85c…  189-224
    - 타이드 바운드 - 쿨타임이 감소합니다. (20초 → 18초)
```

하지만 예약 상태는 달랐다.

```text
조건 A  첫 절 예약: E1만
        E3 question_focus: 빈 값

조건 B  첫 절 예약: E1, E2, E3
        E3 question_focus: 첫 절 전문
```

즉 E3의 단순 pack 존재가 아니라 **첫 요구에 대한 명시적 예약**이 조건 B에서
새로 발생했다. 게이트 1을 통과했다.

### 요구 2: gale_option_cooldown_change

골드 좌표 기준 배정은 A/B 모두 변함없이 E1이었다.

```text
E1  chunk_sha256_b85c…  273-430
    12초 → 9초 표 행
```

다만 관찰할 위험이 있다. E1은 첫 절의 상위 근거로 먼저 선점돼 조건 B에서도
첫 절 `question_focus`를 유지했다. 두 번째 절의 신규 예약 목록에는 E4·E5가
들어갔고 E1은 재배정되지 않았다. 이 항목은 사전 등록 게이트가 아니므로 GO를
바꾸지는 않지만, 런타임 적용 후 A6-7 라이브에서 반드시 확인해야 한다.

## 게이트 2 — value_present

측정 가능한 요구는 49개다.

| 조건 | full | partial | none |
|---|---:|---:|---:|
| M3 기준선 | 39 | 4 | 6 |
| A 현행 | 40 | 4 | 5 |
| B explicit fallback | 41 | 3 | 5 |

- M3 대비 감소: 0
- numeric/date/time/currency 감소: 0
- descriptive 감소: 0
- A→B 개선: A6-26 `contract_price_duration`, partial → full

A6-17·29는 기존 방침대로 descriptive 진단 항목으로 분리했으며 감소가 없었다.

## pack 변화

좌표 집합이 바뀐 슬롯 7개:

```text
A6-4, A6-7, A6-10, A6-12, A6-14, A6-22, A6-26
```

집합은 같고 순서만 바뀐 슬롯 3개:

```text
A6-1, A6-21, A6-23
```

값 감소가 없으므로 pack 변화 때문에 정답 값이 밀려난 사례는 없었다.

## candidate rerank 시간

32문항 합계와 평균:

| 조건 | 합계 | 평균/문항 |
|---|---:|---:|
| A 현행 | 78,188.720ms | 2,443.398ms |
| B fallback | 91,004.226ms | 2,843.882ms |
| 증가 | **12,815.506ms** | **400.485ms** |

시간은 판정 게이트가 아니며 동일 프로세스 내 v2 재측정값이다.

## 기존 S3 대상 참고

value_present A/B 결과:

- A6-1 `transfer_limits`: partial → partial
- A6-4 `report_path`: none → none
- A6-4 `privacy_request_penalty`: full → full
- A6-22 `bug_reporting_channel`: none → none
- A6-22 응답 기한: unsupported 제외 → 동일

따라서 A6-1·4·22를 복구하지 못했다는 기존 S3 결론은 그대로다. 당시 overlap
결과를 잘못 판정한 것이 아니라, 이번 A6-7 예약 질문과 대상이 다르다.

## 검증과 다음 분기

- 전체 `tests/v3`: 1,243 passed
- 기존 manifest SHA 실패: 2건
- 새 실패: 0
- 67 subtests passed
- 런타임·코퍼스·chunk ID 변경: 없음
- 생성 호출: 0

결과 분기는 `게이트 1 통과 + 게이트 2 통과`다. 다음 라운드는
`SEPARATE_REQUIREMENT_RESERVATION_RUNTIME_ROUND`이며, 이번 진단에서 런타임
적용이나 A6-7 라이브까지 앞당겨 실행하지 않았다.
