# 지시서 — 요구별 claim 계약 재평가 (A6-7 · A6-32)

작성: 2026-08-05 · 대상: Codex
성격: **기존 기능 재평가. 신규 구현 아님. Qwen 호출 필요(제한적).**
선행: R1 `7367726` · R2 `ee5bb35` · 예약 재측정 `a3ebd70`

---

## 0. 발견 — 필요한 기능이 이미 구현돼 있고 꺼져 있습니다

R3'로 "요구별 claim 분리"를 새로 만들 계획이었는데, 코드를 열어보니
**이미 완성돼 있습니다.**

```python
# src/v3/product_free_rag.py:135
PRODUCT_COVERAGE_SYSTEM_INSTRUCTIONS = PRODUCT_SYSTEM_INSTRUCTIONS + """
question_requirements의 Q번호마다 정확히 한 번 판단하세요.
근거가 해당 Q의 대상과 속성을 직접 답하면 question_ref가 있는 claim을 작성하세요.
관련은 있지만 다른 혜택·조건·절차·시각·금액을 말하는 근거는 그 Q의 답으로 사용하지 마세요.
직접 답하는 근거가 없으면 값을 추측하지 말고 그 Q번호를 unsupported_question_refs에 넣으세요.
clarification이 필요하지 않다면 모든 Q번호는 claims 또는 unsupported_question_refs 중 정확히 한 곳에 있어야 합니다.
"""
```

부속 구조도 전부 있습니다.

```
question_ref: str = Field(pattern=r"^Q[1-9][0-9]*$")     # 스키마 (line 122)
unsupported_question_refs: list[str]                      # 스키마 (line 131)
build_product_question_requirements()                     # Q번호 생성 (line 218)
검증기: unknown_claim_question_ref / duplicate_claim_question_ref
       / question_ref_claimed_and_unsupported / question_refs_not_exhaustive
플래그: use_question_coverage_contract = False            # 기본 꺼짐
테스트: tests/v3/test_product_free_rag.py 에 다수 존재
```

**A6-7과 A6-32가 겪는 문제를 정확히 겨냥한 계약입니다.**

```
A6-7   두 요구를 한 claim에 뭉치고 ref 하나만 부여
A6-32  지원값 +221 과 비지원값을 한 claim에 뭉쳐 전체 제거
→ 계약이 켜지면 Q1/Q2가 각각 정확히 한 번 판정됨
```

---

## 1. 왜 꺼져 있나 — 2026-08-04 평가 결과

`question_coverage_contract=True`로 실행된 기록은 **두 세트뿐**입니다.

```
reports/v3/product_free_rag_existing32_qcoverage_lexical_shadow_adaptive_20260804.jsonl
reports/v3/product_free_rag_new_claim32_qcoverage_lexical_shadow_adaptive_20260804.jsonl
```

같은 세트의 OFF 실행과 대조한 결과(Claude 실측):

| 세트 | meaning_complete | false_full | mode 변화 |
|---|---|---|---|
| existing32 | **29/32 → 24/32 (−5)** | `[]` → `[]` | unsupported 0 → 4 |
| new_claim32 | **26/32 → 24/32 (−2)** | `[32]` → **`[]`** | unsupported 0 → 4 |

```
정확도는 떨어지고, 안전성은 올라갑니다.
unsupported가 세트당 4건씩 늘어납니다 → 과보수화
```

**이 트레이드오프 때문에 꺼진 것으로 보입니다. 합리적인 판단이었습니다.**

**A6·A5·USER10에서는 한 번도 실행된 적이 없습니다.**

---

## 2. 조건이 바뀌었습니다

8/4 평가 이후 evidence pack이 세 번 개선됐습니다.

| 변경 | 커밋 | 효과 |
|---|---|---|
| 헤더 메타데이터 필터 | (헤더 라운드) | 게시 시각·조회수 오염 제거 |
| R1 괄호 값 결합 | `7367726` | `(20초 → 18초)` 같은 값이 pack에 진입 |
| R2 표 도입문 | `ee5bb35` | 표 행에 주어 부여 |

계약의 실패 방식은 **"직접 답하는 근거가 없으면 unsupported"**입니다.
당시 pack에 값이 없었으면 계약은 **정확하지만 쓸모없게** unsupported를
냈을 것입니다.

```
M3 기준선(R1·R2 이전)   full 39 / partial 4 / none 6
A_current(R1·R2 이후)   full 40 / partial 4 / none 5
```

**pack이 나아졌으니 계약의 동작도 달라질 수 있습니다.**

그리고 8/4 평가의 `meaning_complete`는 **자동 채점기 수치**입니다. A6에서
그 채점기가 **12건을 오판**한 것이 확인됐습니다. `29→24`가 진짜 5점 하락인지
채점기 잡음인지 **당시엔 구분할 수 없었습니다.** 지금은 `value_present`가
있습니다.

---

## 3. ⚠️ 이 라운드는 Qwen 호출이 필요합니다

지금까지 라운드는 전부 `Qwen 0회`였습니다. **이번은 불가능합니다.**
프롬프트·출력 스키마가 바뀌므로 저장 출력 replay로는 검증할 수 없습니다.

### A6에 Qwen을 부르는 것에 대한 규율

```
허용하는 이유
  · A6 공식 결과(사람 판정 19/32, final_no_go)는 이미 확정·불변 기록임
  · A6는 결과를 열람한 시점부터 adaptive 진단셋임
금지
  · 이 라운드의 어떤 숫자도 "A6 성능"으로 부르지 말 것
  · 공식 adjudication 파일을 수정하지 말 것
  · 새 blind 점수를 주장하지 말 것
```

### 호출을 최소화하십시오 — 2문항 먼저

```
1단계  A6-7 · A6-32 두 문항만 ON/OFF 각 1회 = Qwen 4회
2단계  1단계가 유망할 때만 A6 32문항 ON 1회 = Qwen 32회
3단계  2단계가 유망할 때만 USER10 v2 10문항
```

**1단계에서 실패하면 2·3단계를 하지 마십시오.**

---

## 4. 실험 설계

```
[조건 OFF] use_question_coverage_contract = False   ← 현행
[조건 ON ] use_question_coverage_contract = True

다른 모든 설정 동일 (identity_shortlist, compact_evidence_pack,
atomic_evidence_reranker, cuda_model_handoff, 헤더 필터, R1, R2)
```

**런타임 기본값을 바꾸지 마십시오.** 플래그로만 실행합니다.

### 1단계 판정 기준 (사전 등록)

| # | 게이트 | 기준 |
|---|---|---|
| 1 | **A6-7** | 두 절이 각각 다른 Q에 배정되고, Q1이 `20초→18초`, Q2가 `12초→9초` |
| 2 | **A6-32** | `+221`이 노출되고 구매 제한은 `unsupported_question_refs`로 분리 |
| 3 | 계약 위반 | `question_refs_not_exhaustive` 등 검증 오류 0건 |

**게이트 1·2 중 최소 1건 통과해야 2단계로 갑니다.**

### 2단계 판정 기준 (사전 등록)

| # | 게이트 | 기준 |
|---|---|---|
| 4 | `value_present` | R1·R2 기준선(40/4/5) 대비 **감소 0건** (numeric·date·time·currency 기준) |
| 5 | false-full | A6 기준 `[6]` 대비 **증가 0건** |
| 6 | unsupported 증가 | 새로 unsupported가 된 요구를 **전건 목록화**하고, 각각 `value_present`로 근거 유무 판정 |

**게이트 6이 이번 라운드의 핵심입니다.** 8/4 평가에서 unsupported가 4건씩
늘었는데, 그게 **정당한 보류**였는지 **과차단**이었는지 당시엔 알 수 없었습니다.

```
새 unsupported 요구에 대해
  value_present = full   →  ❌ 과차단 (근거가 있는데 보류)
  value_present = none   →  ✅ 정당한 보류
```

이 비율이 이 기능의 채택 여부를 결정합니다.

---

## 5. 하지 말 것

1. **새 claim 분리 로직을 구현하지 마십시오.** 이미 있습니다.
2. **`PRODUCT_COVERAGE_SYSTEM_INSTRUCTIONS` 문구를 고치지 마십시오.**
   먼저 있는 그대로 재평가합니다. 문구 수정은 결과를 본 뒤 별도 판단입니다.
3. **런타임 기본값(`use_question_coverage_contract=False`)을 바꾸지 마십시오.**
   플래그 실행만 합니다.
4. **1단계 실패 시 2단계로 넘어가지 마십시오.**
5. **A6 공식 adjudication 결과를 수정하지 마십시오.**
6. **R1·R2·헤더 필터를 되돌리지 마십시오.**
7. **다른 가드**(`_cross_parent_*`, `_normative_relation_supported`, 채점기)를
   건드리지 마십시오.
8. **도메인 어휘 허용목록 금지.**

### 회귀 면제 2건

```
test_run_unified_runtime::test_full_replay_is_content_addressed_and_reproducible
test_retrieve_decomposed::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings
```

2026-07-29부터 있던 기존 실패. 고치지 마십시오.

---

## 6. 보고 양식

```
[1단계 — A6-7 · A6-32]
  각 문항 OFF / ON 답변 전문
  ON에서의 claims (question_ref 포함) · unsupported_question_refs
  게이트 1·2·3 결과
  Qwen 호출 수

[2단계 — A6 32문항 ON]  (1단계 통과 시에만)
  value_present 전체, A_current(40/4/5) 대비 증감
  값 유형별 분리 (numeric·date·time·currency / descriptive)
  false-full 슬롯 목록
  ★ 새로 unsupported가 된 요구 전건 + 각각의 value_present
     → 과차단 N건 / 정당한 보류 M건
  계약 검증 오류 건수

[3단계 — USER10 v2]  (2단계 통과 시에만)
  10문항 OFF / ON 비교

[공통]
  Qwen 호출 수 (단계별)
  런타임 기본값 변경 (없어야 함)
  회귀 통과 수
```

---

## 7. 결과별 분기 — 미리 정하고 시작

```
1단계 실패
  → 계약으로는 A6-7·A6-32를 못 고침
  → 계약 문구 수정 또는 다른 접근을 별도 라운드로
  → 8/4 평가의 "정확도 하락" 판정이 새 조건에서도 유효함을 확인한 것

1단계 통과 · 2단계 게이트 6에서 과차단 다수
  → 채택 불가. 8/4 판정 재확인
  → 다만 A6-7·32는 고쳐졌으므로 계약을 그 유형에만 좁게 적용할지 검토

1단계·2단계 모두 통과
  → 런타임 기본값 전환 검토 (별도 라운드, 라이브 재검증 필요)
  → 이 경우 8/4의 정확도 하락은 pack 품질 문제였다는 뜻
```

---

## 8. 이후 순서 (범위 밖)

```
R4  value_present 값 유형별 분리 설계 (A6-17·29 위양성)
R5  W6 5분할 새 지표로 재도출
      A6-1  W6 "근거는 이미 pack에 있음" → 실제 partial
      A6-26 사람 판정 "생성 누락" → 실제로는 pack에 값 없음
─────
별도  tail 지연 원인 (hook OFF에서도 p95 101초)  ← 제품 승격 게이트가 여기서 막힘
     A6-4 / A6-22
     frozen manifest 테스트 2건 (7/29부터 red)

[보류] 요구별 근거 예약 fallback (a3ebd70 진단 완료)
       이득 +1 요구 / 비용 +400ms·pack 7문항 변경
       재검토 조건: 지연 기준선이 신뢰 가능해진 뒤
```
