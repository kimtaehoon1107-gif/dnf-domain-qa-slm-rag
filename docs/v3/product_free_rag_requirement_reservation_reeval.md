# 지시서 — 요구별 근거 예약 재측정 (A6-7)

작성: 2026-08-05 · 대상: Codex
성격: **진단 전용. 런타임 수정 금지. Qwen 호출 0회.**
선행: R1 괄호 결합(`7367726`) · R2 표 도입문(`ee5bb35`) 적용 완료

---

## 0. ⚠️ 이건 기존 기각 판정의 번복이 아닙니다

절 분해 진단(`product_free_rag_clause_decomposition_diagnostic_20260805.md`)에서
S3가 **0/3으로 기각**됐고, 그 판정은 사전 등록 기준대로 옳게 실행됐습니다.
**그 결론은 유효합니다.**

이 문서는 **다른 질문**을 묻습니다.

```
기존 질문 (기각됨)
  explicit fallback이 A6-1·4·22의 골드 근거를 최종 후보/pack에 새로 들여오는가?
  → 0/3. 기각.

이번 질문 (신규)
  요구별 근거 예약이 A6-7의 E3를 첫 번째 요구에 바인딩하는가?
  → 당시엔 E3 자체가 존재하지 않아 물을 수 없었던 질문
```

**목표를 옮기는 것이 아닙니다.** 기존 질문의 답은 "아니오"로 확정돼 있고,
이번은 당시 측정 불가능했던 별개 항목입니다. 보고서에도 이 구분을 명시
하십시오.

---

## 1. 무엇이 바뀌었나

| 항목 | S3 당시 | 지금 |
|---|---|---|
| 판정 지표 | overlap (겹침) — 값 누락을 숨김 | **value_present** 사용 가능 |
| `(20초 → 18초)` | 주어 없는 고아 단편, pack 탈락 | **E3로 pack에 존재** (R1) |
| 표 도입문 | 없음 | **E1 context에 존재** (R2) |

### A6-7의 현재 상태

```
evidence_pack
  [E1] table_row 273-430   '| [타이드 바운드] … 기본 쿨타임 12초로 변경 … | … 9초 로 변경 … |'
       ctx: '… 표 도입: - '질풍' 스킬 개화 옵션이 변경됩니다.'
  [E3] sentence  189-224   '- 타이드 바운드 - 쿨타임이 감소합니다. (20초 → 18초)'
       ctx: '업데이트 > 개선 및 변경 사항'

claims (Qwen 출력)
  "타이드 바운드 쿨타임은 12초에서 9초로 줄었고, 질풍 개화 옵션의 기본 쿨타임은 12초에서 9초로 바뀌었다."
  refs = ['E1']            ← 두 요구를 한 claim에 합치고 E3를 쓰지 않음
```

**두 정답 근거가 모두 pack에 있는데 모델이 E1만 씁니다.**

### 예약 로직이 꺼져 있습니다

```python
# src/v3/product_free_rag.py:1898 부근
kiwi_queries = kiwi_independent_requirement_queries(normalized)
effective_requirement_queries = kiwi_queries or None
atomic_reserve_per_query = 3 if len(kiwi_queries) > 1 else 1
```

A6-7은 `kiwi_n = 0`입니다. 따라서:

```
requirement_queries      = None     ← 질문 전체가 한 덩어리 검색 표면
atomic_reserve_per_query = 1        ← 요구별 근거 예약 없음
```

`explicit_question_clauses()`는 A6-7을 **정확히 2절로 분해**합니다.

```
E: '6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 줄었고'
E: '질풍 개화 옵션의 기본 쿨타임은 몇 초에서 몇 초로 바뀌었어'
```

---

## 2. 실험 설계

**기존 shadow 스크립트를 재사용하십시오.** 새로 만들지 마십시오.

```
[조건 A 현행]
  requirement_queries      = kiwi_queries or None
  atomic_reserve_per_query = 3 if len(kiwi_queries) > 1 else 1

[조건 B shadow]
  requirement_queries      = kiwi_queries or explicit_question_clauses(q)
  atomic_reserve_per_query = 절 수에 맞춰 계산
```

**런타임을 바꾸지 말고 진단 스크립트 안에서만 구성하십시오. Qwen 호출 0회.**

### 측정 대상

```
필수
  · A6-7 요구별 evidence 배정 결과
      요구1 base_cooldown_change      에 어떤 unit이 배정되는가
      요구2 gale_option_cooldown_change 에 어떤 unit이 배정되는가
  · A6 32문항 전체의 value_present  (M3 기준선: 측정가능 49 중 full 39 / partial 4 / none 6)
  · pack 진입 unit 집합 변화
  · candidate_rerank_ms 증가분

참고 (기존 S3 대상 재측정)
  · A6-1 · A6-4 · A6-22 를 value_present로 다시 측정
    → S3는 overlap으로 쟀으므로 숫자가 달라질 수 있음
    → 이건 fallback의 효과가 아니라 지표 교체 효과임. 혼동하지 말 것
```

---

## 3. 판정 기준 (사전 등록)

| # | 게이트 | 기준 |
|---|---|---|
| 1 | **A6-7 요구1에 E3 배정** | 조건 B에서 요구1의 배정 unit에 E3(189-224)가 포함 |
| 2 | value_present 감소 | **0건** (M3 기준선 대비) |
| 3 | pack 집합 변경 | 변경된 record 전부 목록 보고 |
| 4 | 지연 | `candidate_rerank_ms` 증가분 수치 기록 (판정 기준 아님) |

**게이트 1이 이 실험의 유일한 성공 조건입니다.**

### 값 유형 분리 필수

`value_present`는 복합 서술형 골드에 위양성을 냅니다(A6-17·29 사례).

```
numeric / date / time / currency  →  게이트 2에 사용
descriptive (복합 서술형)          →  별도 보고. 게이트에서 제외
```

---

## 4. 결과별 분기 — 미리 정하고 시작하십시오

```
게이트 1 통과 + 게이트 2 통과
  → 요구별 예약을 런타임에 적용 (별도 라운드)
  → 생성 구조 수정을 하지 않아도 됨. 검색·pack 레이어에서 해결
  → 적용 후 A6-7 라이브로 두 절 검증

게이트 1 실패
  → ★ 원인이 생성 구조임이 확정됨
     두 정답 근거가 pack에 있고, 요구별 예약까지 해도 모델이 E1을 재사용한다면
     남은 곳은 생성·claim 분리뿐임
  → 다음 라운드는 claim 요구별 분리 (A6-7 + A6-32 동시 대상)

게이트 1 통과 + 게이트 2 실패
  → 요구별 예약이 다른 슬롯의 근거를 밀어냄
  → 감소한 슬롯 전건 보고. 예약 수를 줄여 재측정
```

**게이트 1이 실패해도 이 실험은 성공입니다.** 두 번의 독립적 실패로
"생성 구조가 원인"이 증명되며, 다음 라운드가 훨씬 좁아집니다.

---

## 5. 하지 말 것

1. **런타임 코드를 고치지 마십시오.** 조건 B는 진단 스크립트 안에서만.
2. **Qwen을 부르지 마십시오.**
3. **`display_text` / `chunk_id`를 바꾸지 마십시오.**
4. **R1·R2를 되돌리지 마십시오.** 두 커밋은 순이득이 확인됐습니다.
   - R1 `7367726`: value_present none→full, 감소 0
   - R2 `ee5bb35`: pack 집합·순서 변경 0, 저장 1,302건 불변
5. **기존 S3 기각 판정을 "틀렸다"고 기술하지 마십시오.** 조건이 달라진
   별개 질문입니다.
6. **도메인 어휘 허용목록 금지.**
7. **다른 가드**(`_cross_parent_*`, `_normative_relation_supported`,
   헤더 필터, 채점기)를 건드리지 마십시오.

### 회귀 면제 2건

```
test_run_unified_runtime::test_full_replay_is_content_addressed_and_reproducible
test_retrieve_decomposed::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings
```

2026-07-29부터 있던 기존 실패. 이번 작업과 무관하며 고치지 마십시오.

---

## 6. 보고 양식

```
[게이트 1]
  A6-7 요구1 배정 unit 목록 (조건 A / 조건 B)
  E3(189-224) 포함 여부
  A6-7 요구2 배정 unit 목록 (변화 없어야 정상)

[게이트 2]
  value_present 전체 (full/partial/none), M3 기준선 대비 증감
  값 유형별 분리: numeric·date·time·currency / descriptive
  감소한 요구 전건 (있으면 전문)

[게이트 3·4]
  pack 집합 변경 record 목록
  candidate_rerank_ms 조건 A / 조건 B

[참고]
  A6-1 · A6-4 · A6-22 의 value_present (조건 A / 조건 B)
  ※ S3의 overlap 결과와 직접 비교하지 말 것 — 지표가 다름

[공통]
  Qwen 호출 수 (0)
  런타임 변경 (없어야 함)
  회귀 통과 수
  결과별 분기 4개 중 어디에 해당하는지
```

---

## 7. 이후 순서 (이 문서 범위 밖)

```
게이트 1 통과 시
  R3  요구별 예약 런타임 적용 → A6-7 라이브 두 절 검증

게이트 1 실패 시
  R3' claim 요구별 분리 (A6-7 + A6-32)
      Qwen 출력을 요구 단위로 쪼개 검증
      relation 이름 목록 확대 방식 금지

공통 후속
  R4  value_present 값 유형별 분리 설계 (A6-17·29 위양성)
  R5  W6 5분할을 새 지표로 재도출
        A6-1  : W6 "근거는 이미 pack에 있음" → 실제 value_present partial
        A6-26 : 사람 판정 "생성 누락" → 실제로는 pack에 값 없음
        → 남은 로드맵이 전부 W6 분류 기반이므로 순서가 바뀔 수 있음
  이후 A6-4 / A6-22 / tail 지연 / frozen manifest 2건
```
