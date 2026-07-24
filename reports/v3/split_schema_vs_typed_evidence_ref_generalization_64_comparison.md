# 64문항 paired 비교: 이전 split-schema vs Typed evidence-ref

## 평가 범위

두 Arm은 동일한 human-reviewed sealed 64문항, 동일한
`subject_arm_full` 후보 스냅샷, 동일한 Qwen3 8B `ctx8192`, 동일한
`as_of=2026-07-22`, 동일한 자동 scorer를 사용했다.

달라진 축은 생성 출력과 verifier다.

```text
이전 split-schema:
비표 answer + exact quote / 표 table_row_ref
→ exact quote·answer-token·table-row verifier

Typed evidence-ref:
비표 typed value + evidence_ref / 표 table-row branch
→ relation·temporal-role·boolean verifier
```

Typed Arm 결과를 먼저 연 뒤 실행했으므로 split-schema 실행은 최초 blind
one-shot이 아니라, 사전에 존재하던 동결 Arm을 사용한 사후 comparator다.

## 자동 채점

| 지표 | 이전 split-schema | Typed evidence-ref | 차이 |
|---|---:|---:|---:|
| 후보 완전 보유 | 54/64 | 54/64 | 0 |
| 값 기준 완전 정답 | **38/64** | 37/64 | split +1 |
| 승인된 직접 근거까지 모두 적중 | **36/64** | 31/64 | split +5 |
| 오답 | 7 | 7 | 0 |
| 답변 없음 | **19** | 20 | split -1 |
| 실제 false-full | 2 | **1** | typed -1 |
| verifier overreject | **8** | 14 | split -6 |
| generator 값 선택 오류 | 5 | **3** | typed -2 |
| 생성 오류 | 5 | **3** | typed -2 |
| 인용 좌표 정확성 | 100% | 100% | 동일 |
| 평균 지연 | **15.36초** | 24.20초 | split 36.5% 빠름 |
| p50 | **14.71초** | 21.23초 | split 30.7% 빠름 |
| p95 | **26.53초** | 44.67초 | split 40.6% 빠름 |
| 전체 토큰 | **266,252** | 273,998 | split 7,746 적음 |

두 Arm 모두 `false-full=0`, `generation_error=0`, 완전 정답 85%라는
사전 GO 조건을 통과하지 못했다.

## 문항별 이동

```text
두 Arm 모두 정답: 26
split만 정답:     12
typed만 정답:     11
둘 다 미정답:     15
```

split-schema만 정답:

```text
2, 5, 7, 10, 12, 15, 34, 40, 52, 53, 54, 55
```

Typed evidence-ref만 정답:

```text
4, 18, 33, 41, 44, 47, 49, 50, 57, 63, 64
```

실제 false-full:

```text
split-schema: 31, 55
Typed:        47
```

생성 오류:

```text
split-schema: 9, 21, 39, 47, 61
Typed:        21, 39, 55
```

## 난이도별 값 기준 정답

| 난이도 | 이전 split-schema | Typed evidence-ref |
|---|---:|---:|
| temporal role | 3/8 | **7/8** |
| boolean direction | **5/8** | 4/8 |
| sibling relation | 4/8 | 4/8 |
| multi requirement | 5/8 | 5/8 |
| table attribute | **5/8** | 3/8 |
| revision selection | **5/8** | 4/8 |
| unsupported/partial | **4/8** | 3/8 |
| direct fact | 7/8 | 7/8 |

Typed 방식은 temporal role에서 크게 우세했지만, verifier overreject 때문에
boolean·표·revision·unsupported 문항의 답변률이 낮았다. 이전 split-schema는
직접 근거 적중률과 속도가 더 좋았지만 unsupported false-full과 생성 오류가 더
많았다.

## 결론

새 64문항에서는 adaptive 32에서 관찰했던 Typed 방식의 큰 우세가 재현되지
않았다.

```text
정답률·직접 근거·속도:
이전 split-schema가 근소하거나 명확하게 우세

false-full·생성 안정성·temporal role:
Typed evidence-ref가 우세
```

제품의 최우선 조건이 false-full 0이면 둘 다 승격할 수 없다. split-schema는
더 빠르고 덜 과잉 거절하지만 안전성이 더 나쁘고, Typed는 상대적으로 안전하지만
과잉 거절과 지연이 크다. 따라서 이 결과만으로 어느 Arm도 최종 모델로 선택하지
않는다.

이 세트에서 규칙을 수정하면 이후에는 adaptive validation으로만 사용하고,
일반화 성능 주장은 새로운 holdout에서 다시 확인해야 한다.
