# 지시서 — 요구별 fan-out 생성 실험 (A안)

작성: 2026-08-06 · 대상: Codex
성격: **구조 실험. 단계적 확대. 실패 시 즉시 중단.**
선행: pending 적용 + adaptive replay (`3e3ee9b`), slot 25 반복 (`79626a3`)

---

## 0. 왜 하는가

현재 구조의 단일 병목은 **"Qwen 1회 호출"**입니다.

```
절1로 검색 ─┐
절2로 검색 ─┼→ pack 8개 하나로 합침 → Qwen 1회 → claims → verifier
전체로 검색 ─┘                          ↑
                                 여기서 요구가 다시 뭉침
```

검색·pack 단계까지는 요구를 분리해서 다루는데, **생성에서 한 덩어리가 됩니다.**

### 실제로 깨진 사례

```
[A6-7]  두 요구 → claim 1개, refs=['E1']
        → 어느 요구가 틀렸는지 구분 불가. 통째로 통과하거나 통째로 삭제

[A6-32] 지원값(+221) + 비지원값(구매 제한)이 한 claim
        → 비지원값 때문에 +221까지 삭제 → mode=unsupported
```

**요구 ↔ claim 매핑이 사라져 검증 단위가 무너집니다.**

### 이미 기각된 대안

```
요구별 claim 계약 (프롬프트 강제)   4eb06cf   NO-GO
  형식 오류 0건, 그러나 8B 모델이 "근거 없음 선언"을 이행하지 않음
  A6-32에서 여전히 "제한 없음"이라고 추측
```

**프롬프트로는 안 됩니다. 구조로 강제해야 합니다.**

---

## 1. 설계

```
[현행]
  질의 = [전체, 절1, 절2] → 검색 → pack 8개 → Qwen ×1 → claims → verifier

[fan-out]
  절1 → 검색 → pack A → Qwen 호출① → 요구1 결과
  절2 → 검색 → pack B → Qwen 호출② → 요구2 결과
                                      ↓
                                  병합 → mode 결정
```

### 발동 조건

```
절이 2개 이상일 때만 fan-out
절이 1개면 현행 그대로 (변경 없음)
```

절 분해는 **현행 그대로** 씁니다 (`_runtime_requirement_queries`: Kiwi → 정규식 폴백).
**절 분해 개선은 이번 범위 밖입니다.** 한 번에 한 변수만 바꿉니다.

### pack 구성

```
절마다 독립 pack을 만든다
  · max_units 는 절 수로 나누지 말고 절당 충분히 (예: 절당 6~8)
  · 각 pack 안의 ref 번호는 그 호출 안에서만 유효 (E1, E2, …)
  · 인용 좌표 복원은 호출별로 수행 후 병합
```

### 병합과 모드 결정

```
모든 절이 answer          → answer
일부 절만 answer          → partial
모든 절이 unsupported     → unsupported
어느 절이든 clarification → clarification (기존 규칙 유지)
```

**요구별 결과를 세기만 하면 됩니다.** 현행처럼 사후 추정하지 않습니다.

### ⚠️ 비교형 질문 주의

```
"일반 거푸집과 강철 거푸집 … 교환 타입은 어떻게 달라?"
                                        ↑ 두 대상을 비교해야 답할 수 있음
```

절을 쪼개면 각 호출이 상대를 모릅니다. **비교·대조 질문은 fan-out에서 제외**해야 할 수 있습니다.

1단계 결과를 보고 판단하십시오. **미리 규칙을 만들지 마십시오.**

---

## 2. 단계 — 실패하면 즉시 중단

```
F0  Kiwi 절 경계 필터 위치 수정 + 전건 replay   Qwen 0회      약 30분   ← 선행
F1  fan-out 구현 + A6-7 · A6-32 두 문항        Qwen 4회      약 10분
F2  (F1 통과 시) USER10 v2 10문항               Qwen 20회     약 15분
F3  (F2 통과 시) A6 32문항 adaptive             Qwen 64회 이상 약 40분
```

**F0가 통과해야 F1의 절 분해를 믿을 수 있습니다. F1에서 실패하면 F2·F3를 하지 마십시오.**

---

## 2-1. F0 — Kiwi 절 경계 필터 위치 수정 🔴 선행

### 문제

```python
# 현재 — 자르고 나서 거른다
boundaries = [
    b for b in _clause_boundaries(tokens)
    if str(tokens[b].form) == "고"
]
```

`_clause_boundaries`는 **모든 연결어미(EC)**를 순차 검사하며 경계를 찾고,
경계를 찾을 때마다 `segment_start`를 앞으로 옮깁니다.

```python
if _segment_is_independent(left) and _segment_can_answer(right):
    boundaries.append(index)
    segment_start = index + 1        # ← 여기가 옮겨짐
```

그래서 `"고"`보다 앞에 있는 `면` · `어야` · `게` · `려면`이 먼저 경계로 인정되면
`segment_start`가 옮겨지고, 정작 `"고"` 차례에는 왼쪽 조각이 짧아져
`_segment_is_independent`를 통과하지 못합니다.

**결과: 자를 수 있는 `"고"`가 실제로 있는데 놓칩니다. S2 진단 기준 8건.**

### 수정

**필터를 바깥이 아니라 안으로 옮깁니다.**

```python
def _clause_boundaries(tokens, allowed_forms=None):
    boundaries = []
    segment_start = 0
    for index, token in enumerate(tokens):
        if _base_tag(token) != "EC":
            continue
        if allowed_forms and str(token.form) not in allowed_forms:
            continue                                    # ← 추가되는 한 줄
        left = tokens[segment_start:index]
        right = tokens[index + 1:]
        if _segment_is_independent(left) and _segment_can_answer(right):
            boundaries.append(index)
            segment_start = index + 1
    return boundaries
```

호출부는 `allowed_forms={"고"}`를 넘깁니다.

```
product_evidence_pack.py:167  _kiwi_independent_clause_parts
product_evidence_pack.py:191  _kiwi_shared_topic_anchor
```

`allowed_forms=None`이 기본값이므로 **다른 호출부**
(`answer_target_router.py:141`, `answer_target_coverage.py:55`)는
**동작이 바뀌지 않습니다.**

### Claude 사전 측정 — 8/8 복구

| 사례 | EC 토큰 | 현행 | 수정 후 |
|---|---|---:|---:|
| A6-4 | `['면','어야','고']` | 0 | **1** |
| A6-7 | `['게','고']` | 0 | **1** |
| A6-10 | `['려면','어야','고','며']` | 0 | **1** |
| A6-16 | `['다면','어야','고']` | 0 | **1** |
| A6-21 | `['어야','고','어','면']` | 0 | **1** |
| A6-22 | `['면','어야','고']` | 0 | **1** |
| A6-26 | `['게','고','면']` | 0 | **1** |
| EXISTING32-19 | `['게','고','어도']` | 0 | **1** |

쪼개진 절도 정상입니다. 조건절이 독립 절로 잘려나가지 않습니다.

```
[A6-22]  "게임에서 버그를 발견하면 어디에 제보해야 하"
         ", 제보 뒤 답변까지 걸리는 기한은 정확히 며칠이야"
```

### F0 게이트 (사전 등록)

| # | 기준 |
|---|---|
| 1 | 위 8건이 `kiwi_n = 0 → 2` 로 복구 |
| 2 | 저장 출력 전건 replay에서 `value_present` **감소 0건** (numeric·date·time·currency 기준) |
| 3 | 다른 호출부(`answer_target_router`, `answer_target_coverage`) 동작 **불변** |
| 4 | 회귀 전건 green (면제 2건 제외) |
| 5 | 202문항 전수에서 `kiwi_n` 변화를 전건 기록 |

**게이트 2가 핵심입니다.** 절이 더 잘게 쪼개지면 pack 구성이 바뀔 수 있습니다.

### ⚠️ F0에서 주의할 것

`verifier`의 절 커버리지 판정이 Kiwi 성공 여부에 따라 기준을 바꿉니다.

```python
# product_minimal_verifier.py:819-822
distinctive_fragments = fragments - common_fragments if kiwi_clauses else fragments
minimum_fragment_matches = 1 if kiwi_clauses else 2
```

**Kiwi가 성공하면 판정이 느슨해집니다.** 8건이 복구되면 그 문항들의
`answer` / `partial` 판정이 바뀔 수 있습니다.

→ F0 replay에서 **모드가 바뀐 문항을 전건 목록화**하고, 각각이 개선인지
악화인지 판정하십시오.

### F0 결과별 분기

```
게이트 전부 통과       → F1 진행
게이트 2 실패(감소 발생) → 감소 건 전문 보고 후 F0 롤백. F1은 현행 절 분해로 진행
게이트 1 실패          → Claude 측정과 불일치. 원인 규명 후 보고
```

---

## 3. F1 게이트 (사전 등록)

| # | 문항 | 기준 |
|---|---|---|
| 1 | **A6-7** | 두 절이 **각각 다른 claim**으로 분리되고, Q1이 `20초→18초`, Q2가 `12초→9초` |
| 2 | **A6-32** | `+221`이 노출되고 구매 제한은 **미노출** (unsupported 처리) |
| 3 | 인용 | 좌표 복원 정상, 호출별 ref가 병합 후에도 정확히 매핑 |
| 4 | 지연 | 두 문항 각각 30초 이하 |

**게이트 1·2 중 최소 1건을 통과해야 F2로 갑니다.**

게이트 1이 실패하면 — **모델이 단일 요구 호출에서도 근거를 잘못 고른다는 뜻**이고, 그건 A6-7 종료 판정(8B 한계)이 fan-out으로도 안 풀린다는 확인입니다.

---

## 4. F2 게이트 (사전 등록)

USER10 v2는 **단일 요구 질문 위주**라 fan-out이 거의 발동하지 않아야 합니다.

```
□ 절이 1개인 문항은 답변·mode 완전 불변
□ 악화 0건
□ p95 30초 이하
```

**"안 바뀌어야 할 것이 안 바뀌는지"를 보는 단계입니다.**

---

## 5. F3 게이트 (사전 등록)

```
□ adaptive 24/32 대비 악화 0건
□ false-full 0 · overclaim 0 유지
□ 인용 좌표 32/32
□ p50 / p95 기록 (30초 게이트 확인)
□ ★ 요구별 결과 표: 각 문항의 절 수 / 절별 answer·unsupported
```

마지막 항목이 이 실험의 핵심 산출물입니다. **요구 단위 정확도**를 처음으로 직접 측정하게 됩니다.

---

## 6. 지연 예산

```
현재      warm p50  7.5초 / p95 11.6초 / 여유 18.4초  (통제 측정 46e7880)
생성 비중  4~8초
fan-out   절 2개면 생성 ×2 → p50 예상 13~20초 / p95 예상 20~28초
게이트    30초 → 통과 예상
```

**절이 3개 이상인 문항은 초과할 수 있습니다.** 실측해서 기록하십시오.

---

## 7. 하지 말 것

1. **F0 외의 절 분해 변경을 하지 마십시오.**
   - 허용: `_clause_boundaries`에 `allowed_forms` 파라미터 추가 (F0)
   - 금지: 연결어미 목록 확장(`면`·`며`·`지만` 등 추가), 정규식 separator 변경,
     명사 병렬 처리 추가
   - 이유: S2 분석상 명사 병렬 64건은 문법적으로 절이 1개이며 정규식이 이미
     처리 중입니다. 건드리면 F1의 원인 분리가 불가능해집니다.
2. **F0와 F1을 같은 커밋에 넣지 마십시오.** 별도 커밋으로 분리하십시오.
3. **비교형 질문 판정 규칙을 미리 만들지 마십시오.** F1 결과를 보고 판단.
3. **F1 실패 시 F2·F3로 넘어가지 마십시오.**
4. **런타임 기본값을 바꾸지 마십시오.** 플래그로 켜고 끄게 구현하십시오.
5. **frozen set·공식 adjudication을 수정하지 마십시오.**
6. **F3 숫자를 blind로 부르지 마십시오.** adaptive입니다.
7. **coverage 계약(`use_question_coverage_contract`)을 켜지 마십시오.** NO-GO 유지.
8. **의미 청킹을 시도하지 마십시오.** `chunk_id`가 바뀌어 전 평가셋이 무효화됩니다.

### 회귀 면제 2건

```
test_run_unified_runtime::test_full_replay_is_content_addressed_and_reproducible
test_retrieve_decomposed::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings
```

2026-07-29부터 있던 기존 실패. 고치지 마십시오.

---

## 8. 보고 양식

```
[F0]
  변경 파일과 커밋 해시 (F1과 별도 커밋)
  8건의 kiwi_n  before → after
  202문항 전수 kiwi_n 변화표
  value_present  기준선 대비 증감 (값 유형별 분리)
  ★ 모드(answer/partial)가 바뀐 문항 전건 + 각각 개선/악화 판정
  다른 호출부 동작 불변 확인
  게이트 1~5 결과

[구현]
  플래그명 / 발동 조건 / pack 구성 방식 / 병합·모드 규칙
  커밋 해시

[F1]
  A6-7   현행 답변 / fan-out 답변 (전문)
         절별 claim과 evidence_refs
  A6-32  현행 답변 / fan-out 답변 (전문)
  게이트 1~4 결과
  Qwen 호출 수 / 문항별 지연

[F2]  (F1 통과 시)
  10문항 현행 vs fan-out
  절이 1개인 문항의 불변 여부
  악화 문항 (있으면 전문)

[F3]  (F2 통과 시)
  32문항 결과, adaptive 24/32 대비 증감
  ★ 요구별 결과 표 (문항 / 절 수 / 절별 answer·unsupported)
  false-full / overclaim / 인용 / p50 / p95
  악화 문항 (있으면 전문)

[공통]
  회귀 통과 수
  런타임 기본값 변경 여부 (없어야 함)
```

---

## 9. 결과별 분기 — 미리 정하고 시작

```
F0 게이트 2 실패 (value_present 감소)
  → F0 롤백. F1은 현행 절 분해로 진행
  → "절 경계 필터 위치 수정은 8건을 복구하지만 다른 곳을 악화시킨다"로 기록

F1 게이트 1·2 모두 실패
  → fan-out으로도 안 풀림. 8B 모델의 근거 선택 한계 재확인
  → 즉시 중단. 포트폴리오에 "구조 대안도 실패"로 기록
  → 이것도 유의미한 결과임

F1 통과 · F2에서 단일 요구 문항이 바뀜
  → fan-out이 안 바뀌어야 할 것을 바꿈. 발동 조건 재검토

F1·F2 통과 · F3 악화 0
  → 구조 개선 성공. 런타임 채택 검토 (별도 라운드)
  → 포트폴리오에 "구조적 해법 확인"으로 기록

F3에서 지연 초과
  → 정확도 이득과 지연 손실을 함께 보고. 채택 여부는 사용자 판단
```

---

## 10. 이 실험의 가치

**성공하든 실패하든 포트폴리오에 쓸 결론이 나옵니다.**

```
성공  "단일 호출로 복수 요구를 처리하는 구조의 한계를 확인하고,
       요구별 fan-out으로 검증 단위를 복원했다"

실패  "프롬프트 계약과 구조 분리 두 방향 모두 시도했으나
       8B 모델의 근거 선택 한계가 상위 제약이었다"
```

**둘 다 '추측하지 않고 측정했다'는 서술입니다.**

---

## 11. 이 실험 이후

```
성공이든 실패든 → 포트폴리오 작업으로 이동
추가 구조 실험은 열지 않는다
```

남은 미해결 항목은 "규명된 한계"로 기록합니다.

```
[미해결] 절 분해 실패 82/202 — 명사 병렬 64건이 주류. 연결어미 확장으로는 8건만 해당
[미해결] 의미 청킹 — 미시도. chunk_id 무효화 때문에 새 코퍼스 버전 필요
[미해결] slot 22 관계 오연결 — 검색을 고쳐도 12/4 오연결은 남음
[미해결] slot 25 verifier 과차단 — 표면 유사도로 근거 신뢰도를 판정하는 설계 한계
[종료]   A6-7 계열 — 5번 개입 실패
[NO-GO]  요구별 claim 계약 — 8B가 "모른다" 선언을 이행하지 않음
```
