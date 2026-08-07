# 지시서 — A6 후보 세트 수정 2건 (봉인 전)

작성: 2026-08-04 · 대상: Codex · 상태: 검수 결과 수정 요청
원본: `data/v3/evaluation/product_free_rag_a6_candidate_20260804.jsonl`
(SHA: `189132b2c6c98ca5fe2f349cd1a899af67279ab2e85c9bf34ae191fd00e2abd2`)

---

## 0. 검증 통과 항목 (재현 완료)

```
32문항 / 8출처 × 4 균등          ✅
요구사항 60개                     ✅
인용 좌표 64건 바이트 일치        ✅ 불일치 0
unsupported인데 근거 있음         ✅ 0건
질문 중복 (전 세트 대상)          ✅ 0건
실행·학습 잠금 32/32              ✅
```

차원 편중(multi_requirement 12건)은 **Kiwi 복수요구 경로 집중 평가라는 의도로
납득**하며 수정 대상이 아닙니다.

---

## 1. 수정 ① — 근거 좌표 중복 6건 (sealed64와 겹침)

보고서에 "이전 근거 문장 중복 0"으로 적혀 있으나, **비교 대상에 sealed64가
빠졌습니다.**

```
비교한 것: new_claim32 + untouched32 + A5 = 정확히 96문항  → 중복 0 ✅
빠진 것:   sealed64 (64문항)                              → 좌표 6건 중복 ❌
```

겹치는 좌표(전부 `text` 바이트 동일):

| A6 slot | sealed64 slot | 근거 |
|---|---|---|
| 6 | 12 | `\| 태초 소울 1개 상자 \| ... <구매 가능 횟수> - 월 4회 ...` |
| 22 | 42 | `이 의무를 다하지 않고 버그를 악용하거나 타인에게 전파하는 경우...` |
| 29 | 57 | `판매기간: 06.25 ~ 07.30` |
| 31 | 63 | `상점판매가\n4,000만 골드` |
| 31 | 61 | `거래타입\n교환가능` |
| 32 | 60 | `2026년 08월 13일 06시 일괄삭제` |

### ★ 추가 확인 — 좌표만이 아니라 "사실상 같은 문항"입니다

질문 문자열 완전 일치 검사는 통과(0건)하지만, 실제 내용을 대조하면 단순 좌표
중복이 아닙니다.

```
[A6 slot29]       "2026년 7월 이달의 아이템은 언제부터 언제까지 판매됐어?"
[sealed64 slot57] "7월 이달의 아이템 판매 기간은 언제부터 언제까지야?"
   근거·정답 모두 동일 ("판매기간: 06.25 ~ 07.30")
   → 표현만 다른 같은 문항. 근거 교체가 아니라 문항 교체 필요.

[A6 slot6]        "...광휘의 잔영 몇 개 + 월 구매 제한 + 이월 한도"
[sealed64 slot12] "...광휘의 잔영 몇 개 + 월 구매 제한"
   → "이월 한도"만 신규. 나머지 2개 요구는 완전 중복.

[A6 slot22]       "어디에 알려야 하고" + "퍼뜨리면 어떻게 돼?"
[sealed64 slot42] "퍼뜨려도 괜찮아?"
   → 앞 요구는 신규, 뒤 요구는 근거까지 동일. 절반 중복.
```

untouched32 slot17(OTP 문항)에서 겪은 것과 같은 패턴입니다 — **문자열 중복
검사만으로는 의미 중복을 거르지 못합니다.**

**조치**:
- **slot 29는 문항 자체를 교체** (근거만 바꾸면 여전히 같은 질문)
- slot 6·22는 중복되는 요구를 다른 사실로 교체
- slot 31·32는 근거 좌표 교체로 충분한지 개별 확인
- 앞으로 중복 검사는 **문자열 일치 + 동일 근거 좌표 사용 여부**를 함께 볼 것

**중복 검사 baseline 정정**: 앞으로 중복 검사는 반드시 **sealed64 포함 4개
세트 전체**(sealed64 64 + new_claim32 32 + untouched32 32 + A5 32 = 160문항)를
대상으로 하십시오.

---

## 2. 수정 ② — unsupported 요구 1건 → 4건으로 (더 중요)

```
A5:  unsupported 요구 4건 (slot 4, 16, 24, 32)
A6:  unsupported 요구 1건   ← 1/4 수준
```

### 왜 심각한가

**A5에서 발생한 false-full 2건(slot 4, 12)이 전부 unsupported 요구에서
나왔습니다.** 그리고 **그 false-full 문제는 아직 고쳐지지 않았습니다** —
STEP 1은 과잉거절 수정이었고, STEP 2·3은 코드 변경 0건이었습니다.

현재 A6로 측정하면:
```
false-full = 0 이 나와도
  → 고쳐져서 0인지
  → 시험을 안 해서 0인지
구분할 수 없습니다.
```

이 프로젝트의 핵심 주장이 **"모르면 모른다고 한다"**인데, 그걸 검증할 문항이
1개뿐입니다. A6는 한 번만 쓸 수 있는 카드이므로 이대로 봉인하면 **"false-full이
고쳐졌는지"를 영영 측정하지 못합니다.**

### 조치

**unsupported 요구를 3건 추가해 총 4건**으로 맞추십시오(A5와 동일 수준).

설계 조건:
- A5 slot 4·12와 **같은 함정 구조**를 포함할 것 —
  즉 "질문한 관계에 대한 근거는 없지만, **같은 문서 안에 그럴듯한 다른 값이
  있는**" 구성. 순수 무근거보다 이쪽이 false-full을 실제로 유발합니다.
  ```
  예: A5 slot4 — "할인 쿠폰 금액"은 없는데 같은 문서에 "신규가입 3,000포인트"가 있음
      A5 slot12 — "연령 확인 절차"는 없는데 "개인정보 동의 절차"가 있음
  ```
- unsupported 요구를 가진 문항의 `expected_response_mode`는 `partial_answer`
  (또는 전부 unsupported면 `abstain`)로 정확히 표기
- 추가 문항도 sealed64 포함 160문항과 질문·좌표 중복 0

---

## 2-5. 파이프라인 딥리뷰 결과 — A6 실행 전 처리할 것 3건

A6 봉인·실행 전에 파이프라인 전체를 점검했습니다. **파이프라인 자체는
건전합니다**(실행 프로필이 데모·API·A5러너에서 모두 일치, 매 요청 반복 비용
0.8ms로 무시 가능, 조기 반환 경로 3개의 반환 구조 일관). 다만 아래 3건은
A6 실행 전에 처리해야 합니다.

### 🔴 ① A6 실행 도구가 없습니다 (가장 시급)

```
있는 것: src/v3/build_product_free_rag_a6_candidate.py   ← 빌더만
없는 것: freeze_product_free_rag_a6.py
         run_product_free_rag_a6_one_shot.py
         score_product_free_rag_a6.py
         adjudicate_product_free_rag_a6.py
```

**A5 러너에는 "한 번만 실행"을 보장하는 안전장치가 들어 있습니다:**

```python
maximum_execution_attempts == 1        # 시도 횟수 제한
rerun_after_results_opened is False    # 결과 열람 후 재실행 거부
_write_attempt_marker()                # 시도 마커 선기록
_load_execution_journal()              # 문항별 durable 저널
_exclusive_run_lock()                  # OS 파일 잠금(동시 실행 거부)
```

**A6 러너를 새로 작성하면 이 5개가 빠질 수 있습니다.** A6는 한 번뿐인
카드이므로, 실수로 두 번 돌면 그대로 소진됩니다.

**조치**: A5 도구 4종을 **복사해서 A6용으로 수정**하고, 위 안전장치 5개가
그대로 살아 있는지 실행 전에 확인하십시오. 새로 작성하지 마십시오.

### 🟡 ② `store_true` 기본값 함정 — A6 러너는 프로필을 하드코딩할 것

`run_product_free_rag_existing32.py`의 실행 플래그 4개가 전부
`action="store_true"`, 즉 **기본값 False**입니다.

```
--identity-shortlist / --compact-evidence-pack
--atomic-evidence-reranker / --cuda-model-handoff
→ 안 주면 성능이 나쁜 프로필로 조용히 실행됨
```

(과거 실행 기록에는 `experimental_profile`이 전부 `true`로 남아 있어
검증되었으나, 한 번뿐인 실행에서 플래그를 빠뜨리면 복구 불가입니다.)

**조치**: A6 러너는 A5처럼 **프로필을 하드코딩**하십시오. 플래그 방식 금지.
실행 전 dry-run으로 `experimental_profile`이 A5와 동일한지 확인하십시오.

### 🟡 ③ STEP 2 집계는 "하한값"임을 문서에 명시할 것 (코드 수정 아님)

verifier에 `if not reasons and ...` 체인이 **10개** 있어 **첫 번째로 걸린
사유만 기록**되고 나머지 검사는 건너뜁니다. 실제 데이터로 확인:

```
거절 claim 16건 → 전부 사유 1개. 사유 2개 이상인 claim 0건
```

체인 순서(뒤쪽일수록 가려짐):
```
1 unsupported_language_in_claim
2 claim_repeats_question
3 required_factual_value_missing          ← STEP 1 대상
4 claim_subject_not_bound_to_evidence
5 claim_does_not_address_question_surface
6 evidence_relevance_below_threshold
7 question_relation_role_mismatch          ← 처리기간
8 negative_absence_not_in_evidence         ← 제한없음
9 cross_parent_structured_value_conflict   ← cross-parent
```

**따라서 STEP 2에서 집계한 "처리기간 1건 / 제한없음 1건 / cross-parent 7건"은
하한값입니다.** 앞 가드가 먼저 잡은 경우는 집계에서 빠집니다.

**조치**: 코드는 그대로 두고(short-circuit은 성능상 합리적),
`docs/v3/product_minimal_verifier_hardcoding_cleanup.md` 3-0·3-2절에
**"이 건수는 short-circuit으로 인한 하한값"**이라는 단서를 추가하십시오.

---

## 3. 수정 후 재검증 (Claude)

**후보 세트**
- [ ] sealed64 포함 4개 세트 전체 대상 질문·좌표 중복 0
- [ ] unsupported 요구 4건, 그중 "같은 문서 내 유사 값" 함정 구조 포함 여부
- [ ] 인용 좌표 전건 바이트 일치
- [ ] unsupported 요구에 근거·정답값이 붙어있지 않은지
- [ ] 8출처 × 4 균등 유지
- [ ] 실행·학습 잠금 유지, `review.status: pending`

**실행 도구 (2-5절)**
- [ ] A6 freeze/runner/scorer/adjudicator 4종이 A5 것을 복사·수정한 것인지
- [ ] 안전장치 5개 존재: 시도마커·durable저널·OS파일잠금·1회제한·재실행거부
- [ ] 러너가 프로필을 하드코딩했는지 (플래그 방식 아님)
- [ ] dry-run `experimental_profile`이 A5와 동일한지
- [ ] STEP 2 문서에 "하한값" 단서가 추가됐는지

---

## 4. 하지 말 것

- 좌표 중복을 "질문이 다르니 괜찮다"로 넘기지 말 것 — 근거가 이미 노출된
  문항은 완전한 blind가 아님
- unsupported 문항을 "문서에 아무 관련 내용도 없는" 쉬운 형태로만 만들지 말 것
  — A5 false-full은 "그럴듯한 다른 값이 옆에 있을 때" 발생했음
- 이 수정을 하면서 나머지 문항을 건드리지 말 것
