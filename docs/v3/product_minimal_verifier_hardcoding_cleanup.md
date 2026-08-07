# 지시서 — Product minimal verifier 하드코딩 정리 (2단계 분리 실행)

작성: 2026-08-04 · 대상: Codex · 상태: 원인 확정, 단계 분리 요청
대상 파일: `src/v3/product_minimal_verifier.py`
선행 문서: `docs/v3/product_free_rag_a5_failure_analysis_fix_priorities.md`

---

## 0. 전제 — 이 라운드의 목표

verifier가 **동시에 두 방향으로 틀린** 상태를 고칩니다.

```
정답인데 표현이 달라 차단:      A5 slot 3, 7, 8, 15, 22
숫자만 맞으면 관계가 틀려도 허용: A5 slot 4, 12
```

목표는 "하드코딩을 없애는 것"이 아니라 **하드코딩이 최종 의미 판정을 하지
못하게 만드는 것**입니다. 안전장치는 유지합니다.

### 유지할 것 (삭제·약화 금지)

- 사용한 `E`/`T` 번호가 실제 제공된 근거인지
- 답의 숫자·날짜·시각·금액·단위가 인용 근거에 존재하는지
- 질문에 명시된 연도·월·revision 일치
- `전부·전체` 질문의 완전한 표/목록 근거 요구
- 인용 좌표와 원문 바이트 일치
- 검색 20 / reranker 8 / parent당 2 같은 실험 파라미터

숫자 검사를 없애면 `108,921 → 108,821` 같은 오류를 놓칩니다. **특히 A5 slot 32는
verifier가 옳게 막은 사례**입니다(모델이 표의 A/B→C/D 매핑을 실제로 잘못
읽었고, 차단이 정답이었음 — A5 원본 확인 완료). 이걸 "과잉거절"로 오분류해
풀어주면 false-full이 증가합니다.

---

## 1. 확정된 근본 원인 (코드로 재현 확인)

`_required_factual_value_present`(라인 314)가 **질문 전체**에 `몇/얼마`가 하나라도
있으면 **모든 claim**에 숫자를 요구합니다.

```python
def _required_factual_value_present(question: str, claim_text: str) -> bool:
    if _NUMERIC_QUESTION.search(question) is None:   # 질문 전체 기준
        return True
    return bool(_numeric_values(claim_text) or ...)  # 모든 claim이 숫자 필요
```

직접 실행 결과:

| 문항 | claim1(숫자 있음) | claim2(정답이나 숫자 없음) |
|---|---|---|
| slot 3 | 통과 | **차단** |
| slot 8 | 통과 | **차단** |

**정정**: 이전 지시서에서 Claude가 이 현상을 "value_type=list 추출 실패 / 한국어
조사 처리 문제"로 진단했으나 **틀렸습니다.** 리스트나 조사와 무관하며, 숫자
요구가 질문 수준에서 claim 수준으로 새는 구조적 버그입니다.

**적용 범위**: 이 원인은 slot **3, 7, 8**에 해당합니다. slot 15
(`cross_parent_structured_value_conflict`), slot 22
(`factual_values_not_in_evidence`)는 **사유 코드가 다른 별개 버그**이므로 이
수정으로 풀리지 않습니다.

---

## 2. STEP 1 — 절 단위 숫자 검사 (여기서 한 번 끊고 측정)

```
현재: 질문 전체에 몇/얼마 → 모든 claim에 숫자 요구
변경: 질문 절 단위로 판정

"가격은 얼마고, 유지되는 옵션은?"
  Q1 가격은 얼마     → 숫자 필요
  Q2 유지되는 옵션   → 숫자 불필요
```

절 분리는 이미 있는 `explicit_question_clauses` / Kiwi 독립 절 로직을
재사용하고, 새 분석기를 추가하지 않습니다.

### STEP 1 직후 측정 (STEP 2 시작 전에 반드시)

```
- A5 slot 3, 7, 8 targeted 재현 → 차단이 풀리는가
- existing32 / new_claim32 회귀 → 29/32, 27/32 유지되는가
- 새 false-full 0 확인
```

**이 측정을 건너뛰고 STEP 2로 넘어가지 마세요.** 두 단계를 같이 켜면 어느 쪽이
효과를 냈는지 분리가 불가능합니다(이 프로젝트에서 반복된 실패 패턴).

STEP 1만으로 3·7·8이 풀리면, STEP 2의 의미 검사가 감당할 범위가 **4·12 두 건**
으로 좁아져 검증이 훨씬 쉬워집니다.

---

## 2-1. STEP 1 실행 결과 (2026-08-04) 및 측정 방법 정정

### 결과 (Claude 재현 확인 완료)

```
A5 3·7·8 저장 출력 재생: 모두 복구  ✅ (지시서 예측대로)
A5 15 (cross_parent_structured_value_conflict): 유지  ✅ (별개 버그, 예측대로)
A5 22 (factual_values_not_in_evidence): 유지          ✅ (별개 버그, 예측대로)
existing32: 29/32, false-full 0, 인용 32/32
new_claim32: 26/32 (이전 27/32), false-full [32] 신규 발생
Product 회귀: 160 passed
```

**STEP 1 자체는 성공**입니다. 목표한 3·7·8을 정확히 복구했고 부작용 범위도
예측과 일치합니다.

### ★ slot 32 원인 규명 정정 — "Qwen 변동"이 아닙니다

STEP 1 보고서는 slot 32 false-full을 "Qwen이 이번 실행에서 새로운 오답을
생성한 변동"으로 설명했습니다. **결론(STEP 1 탓 아님)은 맞지만 이유는
틀렸습니다.**

1. `_required_factual_value_present`는 `question`과 `claim_text`만 받아 bool을
   반환하는 **순수 검증 함수**입니다. 생성 프롬프트에 영향을 줄 수 없습니다
   (함수 시그니처로 증명 — 추정 아님).
2. 그런데 두 실행의 `input_tokens`가 실제로 달랐습니다:
   ```
   slot 32: 3049 → 3016 토큰
   input_tokens가 달라진 슬롯: 7, 8, 16, 21, 26, 32  (6개)
   ```
3. **입력이 달라졌으므로 비결정성이 아닙니다.** STEP 1이 프롬프트를 못 바꾸는데
   프롬프트가 바뀌었다는 것은, 8/3 baseline 이후 **다른 코드(Q1/Q2 계약·lexical
   계측)가 들어가면서 기준선이 이동**했다는 뜻입니다.
4. 즉 현재 `27/32 → 26/32` 비교는 **한 변수가 아니라 여러 변수가 바뀐 상태의
   비교**이며, 사전 등록 기준 판정에 그대로 쓸 수 없습니다.

### ★ 측정 방법 변경 — verifier 변경은 저장 출력 replay로 A/B할 것

STEP 1은 순수 검증 함수 변경이므로 **Qwen을 다시 호출할 이유가 없습니다.**

```
이번에 한 것:  코드 수정 → 32문항 live 재실행 → 이전 live 결과와 비교
               문제: baseline drift가 섞여 순수 효과 측정 불가

앞으로 할 것:  저장된 Qwen 출력을 구/신 verifier에 각각 통과시켜 비교
               → 노이즈 0, Qwen 호출 0, verifier 효과만 순수 측정
```

**A5 3·7·8에는 이미 "저장 출력 재생"을 적용했습니다** — 같은 방법을 32문항
세트에도 적용하면 slot 32 같은 잡음이 애초에 생기지 않습니다. STEP 2·3의
verifier 변경도 전부 이 방식으로 측정하세요.

live 실행은 프롬프트·검색·evidence pack이 실제로 바뀌는 변경(STEP 3의 BGE 검사
투입 등)에만 사용합니다.

### ★ slot 32를 STEP 3 검증 케이스로 등록할 것 (버리지 말 것)

두 실행의 실제 출력을 비교하면 slot 32는 잡음이 아니라 **가치 있는 실증
사례**입니다.

```
이전: "계정당 구매 제한이 없습니다"
      → negative_absence_not_in_evidence 가드가 차단 → partial ✅

이번: "구매 제한이 있으며, 교환가능 아이템입니다" (거래타입 근거 인용)
      → 어떤 가드도 잡지 못함 → answer ❌ false-full
```

**모델은 두 번 다 똑같이 틀렸습니다**(구매 제한 정보가 문서에 없는데 답하려 함).
차이는 **어투뿐**입니다. 부정형은 부정 전용 가드에 걸렸고, 긍정형은 통과했습니다.

즉 **이전의 "통과"는 의미 이해가 아니라 어투가 우연히 가드에 걸린 결과**였고,
이는 adaptive 점수(27/32, 29/32) 자체가 어투 운에 좌우된다는 증거입니다.

**BGE 사전 실측 — STEP 3가 이걸 잡습니다:**

| 질문 절 `계정당 구매 제한` ↔ | BGE |
|---|---:|
| 이번에 통과된 오답 근거 (교환가능 아이템입니다) | **0.0001** |
| 이번에 통과된 오답 근거 (거래타입 교환가능) | **0.0002** |
| (참고) 진짜 구매제한 근거 | **0.9652** |

이로써 false-full 차단 대상이 **slot 4·12·32 세 건 모두 0.000~0.003**으로
일관됩니다. slot 32를 STEP 3 필수 검증 케이스에 추가하세요.

---

## 3. STEP 2 — 단어 목록 휴리스틱을 shadow로 전환

다음은 일반화 위험이 큽니다. **삭제가 아니라 shadow 전환**부터 합니다.

- 처리 기간 관련 단어 목록
- `제한 없음` 관련 단어 목록
- 질문·claim 토큰 겹침 점수 `0.1`
- 단순 표면 단어 겹침
- parent가 다르면 구조화 값 충돌로 보는 규칙 (라인 973 부근)

```
현재: 불일치 → claim 차단
변경: 불일치 → shadow 로그만 기록, 차단하지 않음
```

### ★ 필수 집계 — shadow 전환한 각 휴리스틱이 원래 무엇을 막고 있었는가

```
휴리스틱별로:
  - 실제 오답을 막은 건수
  - 정답을 막은 건수(오탐)
```

**정답만 막고 진짜 오답은 하나도 못 막은 휴리스틱은 shadow가 아니라 삭제
대상**입니다. 이 집계 없이는 shadow 코드가 영원히 쌓이기만 합니다.

---

## 3-0. ★ STEP 2 사전 규모 측정 결과 (Claude, 2026-08-04)

STEP 2를 시작하기 전에 **각 가드가 실제로 몇 건을 막고 있는지** 저장된 5개
실행(A5 32 + existing32 ×2 + new_claim32 ×2 = 질문 160회분)의
`rejected_claims`를 사유 코드별로 집계했습니다.

> **집계 해석 주의:** 아래 건수는 가드별 실제 발동 수의 **하한값**입니다.
> verifier의 `if not reasons and ...` short-circuit 체인 때문에 한 claim이 여러
> 조건을 위반해도 먼저 걸린 사유 하나만 기록되고 뒤 가드는 실행되지 않습니다.
> 따라서 특히 뒤쪽의 처리기간·제한없음·cross-parent 건수는 "그 이상 없었다"가
> 아니라 "최소 이만큼은 관측됐다"로 읽어야 합니다.

| 사유 코드 | 건수 | 해당 휴리스틱 | 판정 |
|---|---:|---|---|
| `unsupported_language_in_claim` | 8 | 「확인할 수 없습니다」류 목록 | 대상 아님 |
| `evidence_relevance_below_threshold` | 4 | **토큰 겹침 `0.1`** | **이미 비차단** |
| `ambiguous_cross_parent_context` | 4 | cross-parent 모호성 | ⭐ 조사 대상 |
| `cross_parent_structured_value_conflict` | 3 | cross-parent 충돌 | ⭐ 조사 대상 |
| `required_factual_value_missing` | 3 | 숫자 게이트 | ✅ STEP 1로 해결 |
| `factual_values_not_in_evidence` | 2 | 숫자·날짜 근거 검증 | 유지 대상 |
| `explicit_question_condition_mismatch` | 2 | 명시 조건 | 유지 대상 |
| `negative_absence_not_in_evidence` | 1 | **「제한 없음」 단어목록** | ⭐ 조사 대상 |
| `question_relation_role_mismatch` | **0** | **「처리기간」 단어목록** | **죽은 코드** |

### 발견 ① 「처리기간」 단어목록은 완전한 죽은 코드

```python
_PROCESSING_DURATION_CLAIM   = r"(?:처리|소요)\s*(?:기간|시간)"
_PROCESSING_DURATION_EVIDENCE = r"(?:처리|소요|완료|걸리|영업\s*일)"
→ 사유 코드 question_relation_role_mismatch
→ 질문 160회 실행에서 발동 0건
```

**한 번도 아무것도 막은 적이 없습니다.** shadow 전환 없이 **삭제 후보 1순위**
입니다(지시서 3절의 "막은 claim 0건 → 삭제 대상" 규칙에 해당).

### 발견 ② 토큰 겹침 `0.1`은 이미 차단하지 않습니다

```python
_NON_BLOCKING_REJECTION_REASONS = {
    "claim_does_not_address_question_surface",
    "evidence_relevance_below_threshold",   ← 이미 포함됨
}
```

4건 기록됐으나 전부 **로그만 남기고 통과**시킵니다. STEP 2에서 "shadow로
전환"할 대상이 아니라 **"이미 shadow임을 확인"만** 하면 됩니다.

### 발견 ③ 실제 사람 판정 대상은 8건뿐

```
cross-parent 계열 (충돌 3 + 모호성 4)  = 7건
「제한 없음」 단어목록                  = 1건  ← new_claim32 slot32의 "없습니다"
──────────────────────────────────────────
정답/오답 사람 판정 대상                = 8건
```

앞서 3절에 적은 "82 claim 전수 측정"은 lexical 실험 규모를 그대로 옮긴
것이었습니다. **실제 차단 규모는 8건**이므로 STEP 2는 훨씬 저렴합니다.

### ★ 결론 — STEP 2 범위 재정의

```
기존 계획: 휴리스틱 5종을 각각 shadow 전환 후 82 claim 전수 측정
재정의:    ① cross-parent 계열 7건 정밀도 조사   ← 진짜 초점
           ② 「처리기간」 단어목록 삭제 (0건, 죽은 코드)
           ③ 토큰겹침 0.1이 이미 비차단임을 확인만
           ④ 「제한 없음」 1건 판정 (slot32 케이스)
```

**cross-parent 가드가 A5 slot 15(정답을 차단한 오탐)를 만든 바로 그
가드**입니다. STEP 2의 핵심은 "단어목록 정리"가 아니라 **cross-parent 정밀도
조사**로 좁혀집니다.

---

## 3-1. STEP 2 세부 설계 (2026-08-04 추가)

### 측정 도구: STEP 1의 replay 하니스를 그대로 확장

STEP 1에서 만든 `src/v3/replay_product_minimal_verifier_step1.py`가 이미
**저장 claim 160개에 구/신 verifier를 각각 적용하는 paired A/B** 구조입니다.
STEP 2도 같은 하니스를 확장해 **Qwen 호출 0회 / 검색 호출 0회**로 측정합니다.

```
입력: 동일한 저장 claim 160개
      (a5_adaptive 58 / existing32 53 / new_claim32 47 / 보충 2)
```

### ★ 실행 순서 (3-0 측정 결과 반영)

```
① 「처리기간」 단어목록 삭제
   _PROCESSING_DURATION_CLAIM / _PROCESSING_DURATION_EVIDENCE
   _claim_relation_role_supported 및 호출부 2곳(라인 903, 1049 부근)
   → 삭제 후 replay: 판정 변화 0건이어야 함 (원래 0건 차단이므로)

② 토큰 겹침 0.1이 이미 비차단임을 확인만
   _NON_BLOCKING_REJECTION_REASONS에 evidence_relevance_below_threshold 포함 확인
   → 코드 변경 없음, 확인 결과만 기록

③ cross-parent 계열 7건 정밀도 조사   ← 이번 STEP 2의 핵심
   cross_parent_structured_value_conflict 3건 + ambiguous_cross_parent_context 4건
   각 claim이 실제 오답인지 정답인지 사람이 판정
   → 막은 오답 N / 막은 정답 M / 정밀도

④ 「제한 없음」 단어목록 1건 판정
   negative_absence_not_in_evidence (new_claim32 slot32)
   → 이 1건은 오답 차단이 맞지만, 같은 오해를 긍정형으로 표현하면 못 잡음
     (2-1절 slot32 분석 참고) → "부분적으로만 작동"으로 기록
```

**여전히 하나씩 진행하세요.** ①과 ③을 동시에 건드리면 replay 판정 변화가
어느 쪽 때문인지 섞입니다.

### 산출물 형식 (권장)

| 휴리스틱 | 막은 claim | 실제 오답 | 정답 오탐 | 정밀도 | 판정 |
|---|---:|---:|---:|---:|---|
| 처리기간 단어목록 | **0** (측정 완료) | 0 | 0 | — | **삭제** |
| 토큰겹침 0.1 | 4 (이미 비차단) | — | — | — | **현상 유지** |
| cross-parent 충돌 | 3 | | | | |
| cross-parent 모호성 | 4 | | | | |
| 제한없음 단어목록 | 1 | | | | |

판정 규칙:
```
막은 오답 0건 + 막은 정답 ≥1건  → 삭제 대상 (순수 해악)
막은 오답 ≥1건                  → shadow 유지 후 STEP 3 결과와 함께 재판단
막은 claim 0건                   → 삭제 대상 (죽은 코드)
```

### 이 단계에서 기대하는 것

- **A5 slot 15**는 `cross_parent_structured_value_conflict`에 걸렸고, 그 claim
  (`마법부여 카드와 보주는 1회 거래 시 거래 타입이 계정귀속으로 변경됩니다`)은
  **공식 원문 그대로인 정답**입니다. 즉 이 가드의 확인된 오탐 1건입니다.
  나머지 cross-parent 6건의 정답/오답 비율이 이 가드의 운명을 결정합니다.
- **A5 slot 22**는 `factual_values_not_in_evidence`(숫자·날짜 근거 검증)에
  걸렸습니다. 이건 **유지 대상 안전장치**이므로 STEP 2에서 끄지 마세요.
  slot 22는 "복구가 불가능하다" ≡ "복구가 가능하지 않습니다"라는 **부정 표현
  동의어 미인식** 문제이며, 별도 항목(지시서 5절 STEP 순서 참고)입니다.

### 하지 말 것 (STEP 2 한정)

- 휴리스틱 여러 개를 한 번에 끄고 합산 결과만 보기
- live 32문항 재실행으로 측정하기 (baseline drift — 2-1절 참고)
- 정밀도 집계 없이 "일반화에 나쁘니까" 바로 삭제하기
- STEP 3(BGE 의미 검사)을 같이 켜기 — 효과 분리 불가

---

## 3-2. STEP 2 Codex 재검증 결과 (2026-08-04)

저장 출력 5개, 질문 160개를 Qwen·검색 호출 없이 재집계했다. 3-0절의 사유 코드
건수는 재현됐지만, **「처리기간」을 죽은 코드로 본 결론은 반례 때문에 철회**한다.

여기서 재현한 처리기간 1건·제한없음 1건·cross-parent 7건 역시
`if not reasons` short-circuit 뒤에 남은 **관측 하한값**이다. 앞 가드가 같은
claim을 먼저 거절한 경우는 이 표에 포함되지 않으므로, 이 수치를 각 가드의 전체
발동량이나 완전한 recall로 해석하지 않는다.

```
처리기간 정규식 표면 trigger: 최근 160문항에 3 claim
question_relation_role_mismatch: 최근 160문항에서는 0건
과거 adaptive 실제 오답 차단: 1건 (existing32 slot 24)
회귀 테스트: 1건 존재
```

과거 slot 24에서 모델은 `12개월 이상 미접속`이라는 위임 **조건**을 처리
**기간**이라고 답했다. 가드는 이를 올바르게 차단했다. 따라서 최근 선택 표본의
사유 코드 0건만 보고 함수·호출부·테스트를 삭제하면 알려진 false-full을 되살린다.
삭제하지 않았고 blocking 상태를 유지했다.

나머지 판정은 다음과 같다.

| 휴리스틱 | 막은 claim | 실제 오답 | 정답 오탐 | 정밀도 | 판정 |
|---|---:|---:|---:|---:|---|
| 처리기간 단어목록 | 최근 0, 과거 1 | 1 | 0 | 100% | 유지 |
| 토큰겹침 0.1 | 4 (이미 비차단) | — | — | — | 기존 shadow 유지 |
| cross-parent 충돌 | 3 | 2 | 1 | 66.7% | 대체 검증 전 blocking 유지 |
| cross-parent 모호성 | 4 | 판정 불가 | 판정 불가 | — | 원시 claim 유실, shadow 금지 |
| 제한없음 단어목록 | 1 | 1 | 0 | 100% | 유지, 긍정형 우회는 STEP 3 |

cross-parent 모호성 4건은 clarification 변환 때 원시 claim text가 빈 문자열로
덮여 저장되어 claim 단위 정밀도를 산출할 수 없었다. 이 로직은 대상 파일이던
`product_minimal_verifier.py`가 아니라 `product_free_rag.py`의
`_cross_parent_clarification`에 있다.

산출물:

- `src/v3/audit_product_minimal_verifier_step2.py`
- `reports/v3/product_minimal_verifier_step2_heuristic_audit_20260804.jsonl`
- `reports/v3/product_minimal_verifier_hardcoding_cleanup_step2_20260804.md`

**STEP 2 판정**: 이번 표본에서 바로 삭제하거나 비차단 shadow로 바꿀 blocking
가드는 없다. blocking 코드 변경은 0건이며, 다음은 STEP 3 BGE 의미 검사를
차단 없는 shadow로 측정한다.

---

## 3-2. ★ STEP 2 실행 결과 (2026-08-04) — 전 가드 유지 판정

Claude 재현 확인 완료. **모든 blocking guard 유지가 옳은 결정입니다.**

| 가드 | 실측 | 판정 |
|---|---|---|
| 처리기간 단어목록 | 오답 1건 차단 (과거 adaptive) | **유지** |
| cross-parent 충돌 | 오답 2 / 정답 오탐 1 → **정밀도 66.7%** | 유지 |
| cross-parent 모호성 | 4건 전부 원문 유실 → 판정 불가 | 보류 |
| 「제한 없음」 | 오답 1건 정확히 차단 | 유지 |
| 토큰 겹침 `0.1` | 4건, 이미 비차단 | 현상 유지 |

Qwen·검색 호출 0회, 회귀 168 passed.

### ★ 정정 — 「처리기간」은 죽은 코드가 아니었습니다

3-0절에서 Claude가 `question_relation_role_mismatch` 0건을 근거로 "죽은 코드,
삭제 후보 1순위"라고 판정했으나 **틀렸습니다.** 리포트 5개만 샘플링해
`existing32_final_adaptive_replay_20260803.jsonl`을 누락했고, 거기에 실제
차단 사례가 있었습니다:

```
질문: "2020년 12월 4일 시행 운영정책에서 길드장 권한이 위임될 수 있는
       조건과 처리 기간을 알려줘."
차단된 claim: "처리 기간은 12개월 이상 미접속으로 인한 휴면 상태인 경우입니다."
→ 12개월 미접속은 위임 조건이지 처리 기간이 아님. 차단이 정답.
```

**3-0절의 "발견 ① 죽은 코드" 판정은 무효입니다.** 이 가드는 유지합니다.
(교훈: 사유 코드 집계는 저장 리포트 **전체**를 대상으로 해야 합니다.)

### cross-parent 66.7%를 지금 끄면 안 되는 이유

정밀도가 낮지만(오탐 1건 = A5 slot 15), **지금 끄면 오답 2건이 즉시 새어
나오고 그 자리를 메울 STEP 3가 아직 없습니다.** STEP 3의 BGE 검사가 전수
측정을 통과한 뒤에 이 가드의 운명을 재판단하는 순서가 맞습니다.

---

## 4. STEP 3 — BGE 기반 질문 절 ↔ 근거 의미 일치 shadow

새 모델을 추가하지 않고 **기존 BGE reranker**를 재사용합니다.

### 사전 실측 (Claude, 2026-08-04) — 유망하나 편향 표본

| 케이스 | 기대 | BGE 점수 |
|---|---|---:|
| A5 slot4 Q2 "특별 할인 쿠폰 금액" ↔ 신규가입 3,000포인트 | 차단 | **0.0028** |
| A5 slot12 Q2 "정확한 연령 확인 절차" ↔ 개인정보 동의 | 차단 | **0.0001** |
| **new_claim32 slot32 "계정당 구매 제한" ↔ 교환가능 아이템** | **차단** | **0.0001** |
| **new_claim32 slot32 "계정당 구매 제한" ↔ 거래타입 교환가능** | **차단** | **0.0002** |
| A5 slot8 Q2 "어떤 옵션이 유지됐어" ↔ 강화/증폭/마법부여 | 통과 | **0.5909** |
| A5 slot3 Q2 "어떤 부여 항목이 삭제됐어" ↔ 마법부여·엠블렘 | 통과 | **0.9613** |
| (참고) "계정당 구매 제한" ↔ 진짜 구매제한 표 행 | 통과 | **0.9652** |

200배 이상 분리됩니다. lexical overlap이 실패한 지점(조사 불일치, 표 행에
대상명 미반복)을 cross-encoder는 의미로 처리하므로 원리적으로도 타당합니다.
false-full 차단 대상 3건(A5 slot4·12, new_claim32 slot32)이 모두
`0.000~0.003` 대역으로 일관됩니다.

### ⚠️ 반드시 지킬 것 — 편향 표본 경고

**이 7건은 이미 알려진 실패에서 뽑은 편향 표본입니다.** 직전 lexical overlap
실험도 micro 4건에서 0.43~0.67 vs 0.00으로 깨끗했으나, 전수에서 정밀도
**10.7%**였습니다. **전수 측정 전에는 차단기로 승격하지 마세요.**

---

## 4-0. ★ STEP 3 착수 전 필수 3항목 (Claude, 2026-08-04 추가)

### ① 선행 수정 — 거절된 claim의 원문을 보존할 것

STEP 2에서 `ambiguous_cross_parent_context` 4건을 **판정하지 못한 이유**가
서버가 거절 시 claim 원문을 지웠기 때문입니다. 실측:

```
거절된 claim 18건 중 원문이 빈 문자열인 것 2건 (+모호성 케이스 다수)
→ audit adjudication = "claim_text_unavailable_case_level_mixed_signal"
```

**이 상태로 STEP 3에 들어가면 같은 문제가 반복됩니다.** BGE 검사는 claim
원문과 인용 근거를 대조하는 것이라, 원문이 없으면 채점 자체가 불가능합니다.

```
수정: rejected_claims[].text 에 원시 claim 문자열을 항상 보존
      (차단 여부와 무관하게 기록 — 노출이 아니라 감사 로그 목적)
```

**STEP 3 구현 전에 이 수정을 먼저 하고, 그 뒤 측정을 시작하세요.**

### ② 측정 규모 정정 — STEP 3는 STEP 2와 반대로 큽니다

```
STEP 2 대상: 차단된 claim만          →  8건   (3-0절에서 확인)
STEP 3 대상: 승인된 claim 전부       → 142건  ← 실측
```

BGE 검사는 **"통과된 답변 중 관계가 틀린 것을 찾는"** 것이므로, 승인 claim
142건을 전부 채점하고 **낮은 점수가 나온 것만 사람이 판정**하는 구조입니다.
3-0절의 "실제 규모는 8건" 정정은 STEP 2에만 해당하며, **STEP 3에서는 전수
측정이 맞습니다.**

(집계 근거: A5 adaptive replay + existing32/new_claim32 step1 실행의
`result.claims` 합계 142, `rejected_claims` 합계 18)

### ③ ★ 임계값을 측정 대상에서 고르지 말 것

지금까지 BGE 실측은 **7/7 깨끗**합니다(차단측 `0.0001~0.0028`, 통과측
`0.59~0.97`). 그러나 lexical도 4/4 깨끗했다가 전수에서 10.7%였습니다.

**반드시 이 순서로:**

```
1. 승인 claim 142건에 BGE 점수만 매긴다 — 임계값을 정하지 않는다
2. 점수 분포를 먼저 본다
   - 0.0 근처와 0.9 근처로 갈리는가?
   - 중간대(0.1~0.5)가 두꺼운가?
3. 중간대가 두꺼우면 → 이 방법도 실패. lexical과 같은 결론으로 종료
4. 명확히 갈리면 → 그때 임계값을 정하고,
   "보지 않은 패러프레이즈"로 별도 검증
```

**분포부터 보고 임계값은 나중에.** 이 순서를 어기면 "측정 대상에 맞춰 임계값을
맞추는" adaptive overfit이 됩니다 — 이 프로젝트가 반복해서 겪은 실패입니다.

### 설계 제약 — 질문 절만 사용, 전체 질문 금지

slot 27 사례에서 BGE는 **판매** 질의에 대해 삭제 문장(0.9922)을 정답 판매
문장(0.9885)보다 높게 줬습니다. 그때 질의에는 긴 상품명이 통째로 들어 있었습니다.
이번 4건이 깨끗한 것은 질의가 `"특별 할인 쿠폰 금액"` 같은 **짧은 관계 중심 절**
이기 때문일 가능성이 큽니다.

```
사용:     관계 중심 절 (예: "특별 할인 쿠폰 금액")
사용 금지: 긴 주어가 포함된 전체 질문
```

---

## 4-1. STEP 3 선행 수정 실행 결과 (Codex, 2026-08-04)

`product_free_rag.py`의 cross-parent clarification 변환부가 기존 승인 claim을
지우기 전에 원시 text와 evidence refs를 `rejected_claims`에 복사하도록 수정했다.

```
수정 전: text="", evidence_refs=[]
수정 후: text=<원시 claim>, evidence_refs=<모델이 선택한 E 번호>
```

거절 claim은 감사 로그에만 남고 사용자에게는 노출되지 않는다. 최종 `claims`는
계속 빈 목록이며 `rendered_answer`에는 기존 clarification 선택지만 렌더링된다.
디레지에 broad 질문과 토스페이 혼합 문서 케이스에서 원문·근거 번호 보존과 UI
비노출을 모두 확인했다.

```
Product 회귀: 168 passed
Qwen 호출: 0
검색 호출: 0
live 평가: 0
```

기존 보고서의 빈 문자열을 사후 추정해 수정하지는 않았다. 이후 실행부터 원문이
보존된다. 상세 기록은
`reports/v3/product_minimal_verifier_rejected_claim_preservation_20260804.md`다.

---

## 5. 진행 순서

```
1. _required_factual_value_present 절 단위 전환                       ✅ 완료
2. ★ STEP 1 단독 측정                                                ✅ 완료(3·7·8 복구)
2-1. ★ 저장 출력 replay로 STEP 1 재측정                              ✅ 완료 — STEP 1 GO
     (claim 160, qwen 0회, 변경 5건 전부 3·7·8 복구, 잘못 강화 0건)
2-2. ★ STEP 2 사전 규모 측정                                         ✅ 완료 (3-0절)
     → 실제 차단 규모 8건, 토큰겹침 0.1은 이미 비차단
     → ⚠️ 「처리기간 0건=죽은 코드」 판정은 무효 (3-2절 정정, 샘플 누락)
3. STEP 2 실행 — 최근 160문항 + 과거 반례 정밀도 조사               ✅ 완료
   → 처리기간 삭제 NO-GO, 토큰겹침은 기존 shadow,
     blocking guard 변경 0건 (3-2절)
3-1. ★ 선행 수정 — 거절 claim 원문 보존 (rejected_claims[].text)     ✅ 완료
     감사 로그 보존·사용자 비노출·168 회귀 통과 (4-1절)
4. BGE 질문 절 ↔ 근거 의미 일치 shadow 구현 (차단 없음)             ← 다음
   → 기존 가드는 전부 켜둔 채로 추가
5. **승인 claim 142건 전수** 점수 산출 → 분포 확인 → 그 뒤에 임계값
   ⚠️ 임계값을 측정 대상에서 고르지 말 것 (4-0절 ②③)
6. 양성 3·7·8·15·22 / 음성 4·12 + new_claim32 slot32 targeted A/B
7. 보지 않은 패러프레이즈 문항으로 일반화 확인
8. 전부 통과 시에만 기본 Product 경로 승격
   → cross-parent 66.7% 가드의 운명도 이때 재판단 (3-2절)
```

**STEP 1 최종 판정 (2026-08-04): GO.** 저장 claim 160개 paired replay에서
Qwen·검색 호출 0회, 판정이 바뀐 claim 5개가 전부 A5 3·7·8 정답 복구였고,
통과→차단으로 나빠진 claim은 0개였습니다. live `27/32 → 26/32` 비교는
baseline drift(입력 토큰 변화 6슬롯) 때문에 STEP 1 판정에서 제외합니다.

**남은 A5 실패 배분**:
```
15                            → STEP 2에서 정답 오탐 확인, 대체 검증 전 유지
22                            → factual value 안전장치 유지, 부정 동의어 별도 문제
4, 12, new_claim32 slot32     → STEP 3 (BGE 의미 검사)
16                            → 범위 밖 (프롬프트 트랙)
```

---

## 6. 판정 기준

```
정답 claim 과잉 차단 감소
A5 4·12 + new_claim32 slot32 false-full은 계속 차단
새 false-full 0   ← 단, 저장 출력 replay 기준으로 판정할 것 (live 비교 금지)
숫자·날짜 오답 차단 유지 (특히 A5 slot 32 계열)
인용 좌표 복원 100%
기존 단일 질문 회귀 0
shadow 휴리스틱별 "막은 오답 수 / 막은 정답 수" 집계 존재
```

**판정 시 주의**: `새 false-full 0`을 live 재실행 결과로 판정하면 baseline
drift(다른 코드 변경으로 프롬프트가 바뀜)를 verifier 회귀로 오인합니다.
verifier 변경의 판정은 반드시 **동일한 저장 출력**에 구/신 verifier를 각각
적용한 결과로 하세요.

---

## 7. 하지 말 것

- 숫자·날짜·명시 조건·인용 좌표 검사를 축소하지 않는다.
- slot 32 계열(모델이 표를 실제로 잘못 읽은 경우)의 차단을 풀지 않는다.
- STEP 1과 STEP 2~3을 동시에 켜서 측정하지 않는다.
- BGE 의미 검사를 4건 micro 결과만 보고 차단기로 승격하지 않는다 — 전수 측정
  필수(lexical 전례).
- BGE 의미 검사에 긴 주어가 포함된 전체 질문을 넣지 않는다.
- 새 형태소 분석기나 새 NLI 모델을 이번 라운드에 추가하지 않는다 — BGE 전수
  측정 결과가 부족할 때만 다음 라운드에서 검토한다.
- A5를 재실행하지 않는다.
- **verifier 전용 변경을 live 32문항 재실행으로 A/B하지 않는다** — 저장 출력
  replay를 쓴다. live 실행은 프롬프트·검색·evidence pack이 실제로 바뀌는
  변경(STEP 3의 BGE 투입 등)에만 쓴다.
- **new_claim32 slot32를 "Qwen 변동"으로 처리하고 넘어가지 않는다** — 어투만
  바꾸면 뚫리는 가드의 실증 사례이므로 STEP 3 검증 케이스로 보존한다.

---

## 8. 수정 후 내가(Claude) 재검증할 것

- [x] STEP 1 단독 측정 결과가 STEP 2~3과 분리되어 기록됐는지 — 완료
- [x] `_required_factual_value_present`가 절 단위로 동작하는지 — 완료(3·7·8 복구)
- [x] slot 15·22가 이 수정으로 안 풀린다는 것이 기록됐는지 — 완료(별개 버그 확인)
- [x] STEP 1을 **저장 출력 replay**로 재측정해 baseline drift 없는 순수 효과를
      확인했는지 — 완료(160 claim paired A/B, 완화 5·강화 0·새 false-full 0)
- [x] new_claim32 slot32가 STEP 3 검증 케이스로 등록됐는지 — 완료
      (`product_minimal_verifier_semantic_shadow_registered_cases_20260804.jsonl`)
- [x] 휴리스틱별 "막은 오답 / 막은 정답" 집계가 실제로 존재하는지 — 완료
      (단, 원시 claim이 유실된 cross-parent 모호성 4건은 정밀도 보류)
- [x] STEP 2에서 휴리스틱을 **하나씩** 검토했는지 — 처리기간부터 확인했고
      과거 true-positive 반례 때문에 삭제 전 중단, 여러 가드 동시 변경 0건
- [x] STEP 2 측정이 저장 질문 160개 replay인지 (live 재실행 아님) — 완료
- [x] A5 slot 15·22를 막은 휴리스틱이 각각 어느 것인지 특정됐는지 — 완료
- [x] "막은 오답 0 + 막은 정답 ≥1" 휴리스틱이 삭제 대상으로 분류됐는지 —
      해당 휴리스틱 없음. 처리기간은 과거 실제 오답 1건을 막아 삭제 조건 불충족
- [x] **거절 claim 원문 보존 수정이 STEP 3 구현 전에 반영됐는지** — 완료
      (원시 text·E refs 보존, 사용자 렌더링 비노출, 168 passed)
- [x] BGE 의미 검사가 **승인 claim 142건 전수**로 측정됐는지 (micro 7건 아님)
      — 완료(일반 RAG 139 + 메타데이터 3, 인용 224, 등록 대조 5)
- [x] **점수 분포를 먼저 보고** 임계값을 나중에 정했는지 — 임계값 0 상태로
      전수 분포를 먼저 산출했고, 분포 중첩으로 임계값 자체를 만들지 않음
- [x] 중간대(0.1~0.5)가 두꺼우면 lexical과 같은 결론으로 종료했는지 —
      일반 RAG 22/139(15.83%), 정상·오답 저점 중첩으로 blocking 승격 중단
- [x] BGE 입력이 관계 중심 절인지, 전체 질문이 아닌지 코드로 확인 —
      `relation_clauses_for_claims` + atomic `제목/문맥/근거` 입력, 전체 질문 미사용
- [x] STEP 3 통과 후 cross-parent 66.7% 가드 운명을 재판단했는지 —
      STEP 3 미통과로 대체 가드 없음. 라이브 개정판 혼합 오답 1/1 차단 확인,
      기존 blocking 유지
- [x] slot 32 계열 차단이 유지되는지 — shadow가 판정에 관여하지 않아 기존
      차단 경로 변경 0
- [x] existing32 / new_claim32 회귀 없음, 새 false-full 0 — STEP 1 저장 claim의
      숫자 게이트 결정 변화 0, paired replay 기준

---

## 9. STEP 3 실행 결과 (2026-08-04)

저장 출력 replay로 승인 claim 142건을 전수 측정했다. 일반 RAG 인용은
chunk 좌표를 192/192 재검증하고 atomic 문맥 162건을 복원했으며, 실제 atomic
reranker와 같은 `제목 + 문맥 + 근거` 형식으로 BGE-M3를 호출했다. 메타데이터
claim 3건은 RAG와 분리 집계했다.

```
일반 RAG claim 139
<0.01             19
0.01~0.1          11
0.1~0.5           22  (15.83%)
0.5~0.9           22
>=0.9             65
```

등록 오답은 0.00005059~0.00151845였지만, `meaning_complete=true` 정상 claim도
0.00002566부터 존재했다. 오답 전체를 차단하는 하한은 정상 답변을 차단하고,
최저 정상 답변을 살리는 하한은 오답을 통과시킨다.

**STEP 3 최종 판정: STOP.** BGE 관계 의미 점수는 shadow 진단으로만 보존하고
blocking verifier로 승격하지 않는다. threshold와 unseen paraphrase 단계도 진행하지
않는다. 기존 숫자·날짜·명시 조건·인용 좌표·cross-parent 가드는 모두 유지한다.

상세:

- `reports/v3/product_minimal_verifier_step3_bge_shadow_decision_20260804.md`
- `reports/v3/product_minimal_verifier_cross_parent_ambiguity_live_adjudication_20260804.md`
