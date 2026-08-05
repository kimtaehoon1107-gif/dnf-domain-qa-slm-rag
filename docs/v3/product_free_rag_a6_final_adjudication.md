# 지시서 — A6 최초 1회 실행 결과 사람 판정 확정 (2단계)

작성: 2026-08-05 · 대상: Codex · 상태: 32문항 사람 검수 완료 → 공식 판정 확정 요청

- one-shot 결과: `reports/v3/product_free_rag_a6_one_shot_4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl`
- frozen set: `data/v3/evaluation/product_free_rag_a6_frozen_9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl`

---

## 0. 사전 확인 — Claude 독립 재현 완료

```
후보 SHA a6795df9… → frozen SHA 9405401d…   필드 차이 128건 = 32 × 4(잠금·리뷰 메타)뿐
                                            질문·요구·근거·정답 전부 불변        ✅
attempt.json  maximum_execution_attempts: 1                                     ✅
journal       started 32 + recorded 32, 슬롯 중복·누락 0                        ✅
자동 통과 7건 [5,8,12,16,21,24,31] · false-full [6] · 인용복원 32/32            ✅
회귀(제품/A6 10개 파일)  186 passed                                             ✅
```

문항을 바꾸고 실행한 흔적은 없습니다. **결과 파일은 신뢰할 수 있습니다.**

사람 검수 결과 **32문항 전건 판정이 확정**되었습니다. 아래 값을 그대로
기록하고 finalize 하십시오.

---

## 1. 확정 판정 — 19/32 (59.375%)

### 정답 19건

```
3, 5, 8, 9, 12, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 27, 29, 30, 31
```

이 중 **12건(3, 9, 15, 17, 18, 19, 20, 23, 25, 27, 29, 30)은 자동 채점이
오판한 것**입니다. 원인은 채점기가 `required_values`를 표면 문자열로 대조하기
때문입니다. 사람 검수에서 전건 대조해 정답임을 확인했습니다.

| slot | 골드 | 모델 답 | 오판 원인 |
|---:|---|---|---|
| 3 | `2025-09-11 점검 후` | `25.09.11 점검 후` | 날짜 축약 |
| 9 | `패배 시 적립되지 않음` | `패배 시 마일리지가 적립되지 않습니다` | 문장화 |
| 15 | `숫자 6자리` | `6자리 숫자` | 어순 |
| 17 | `강철 거푸집: 교환가능` | `강철 거푸집으로 만든 형상의 교환 타입은 교환가능입니다` | 콜론 표기 |
| 18 | `등장 확률 증가` / `판매 아이템 개수 증가` | `등장 확률과 판매 종류 및 개수가 늘어난다` | 병합 표현 |
| 19 | `각 파티장에게 부여 가능` | `공격대장은 각 파티장에게 … 줄 수 있습니다` | 문장화 |
| 20 | `I키` / `계정 공용` | `[I] 키` / `캐릭터끼리 함께 쓸 수 있습니다` | 괄호·의역 |
| 23 | `모든 계정 영구 게임 이용제한` | `모든 계정과 회원가입에 영구 게임 이용제한 및 …` | 병합 표현 |
| 25 | `교환불가 무기 스킨` | `무기 스킨은 교환불가 타입입니다` | 어순 |
| 27 | `264칸` | `264 칸` | **공백 1** |
| 29 | `2,000만 골드` | `2000만 골드` | **쉼표 1** |
| 30 | 두 구성품 | 답변에 문자 그대로 존재 (서버 표 복원) | evidence 판정 실패 |

자동 통과 7건도 전건 대조했으며 **위양성은 없습니다.**

### 오답 13건

```
1, 2, 4, 6, 7, 10, 11, 13, 14, 22, 26, 28, 32
```

| slot | 실패 내용 | 단계 |
|---:|---|---|
| 1 | 퀵계좌이체 한도 대신 **네이버페이 한도(200만/1,000만)** 사용, 1개월 한도 누락 | 검색·대상 결합 |
| 2 | 점검 시작을 **14시**(공지 게시 시각)로 답. 본문은 15시 | 근거 선택 |
| 4 | `캐릭터 이름 클릭 > 신고하기 > 거래 사기 등록` 경로 대신 "사기로 의심되는 대화" | 근거 회수 |
| 6 | **false-full** — 근거 없는 확률을 "균등한 확률"로 단정하고 `answer` 종료 | answerability |
| 7 | 타이드 바운드(20→18초)와 질풍 개화(12→9초)를 혼동, 한 요구 누락 | 관계 결합 |
| 10 | 모델은 `10회/1회/06시`를 맞게 생성했으나 verifier가 전부 제거 → 답변 빔 | verifier 과차단 |
| 11 | 판매 종료일 `2026-08-27 점검 전` 누락 | 생성 완전성 |
| 13 | `연 5회 재발급`을 verifier가 제거 | verifier 과차단 |
| 14 | 같은 내용 2회 반복, 확인 가능한 정보 2종 누락 | 생성 완전성 |
| 22 | **overclaim** — 제보처를 "담당부서"로 오답 + 근거 없는 `12/4(목)` 생성 | 검색 + 안전 |
| 26 | 가격 `9,800 세라` 누락 | 생성 완전성 |
| 28 | `계정당 5회`를 cross-parent 충돌로 제거 | verifier 과차단 |
| 32 | 지원값(`+221`)과 비지원값(구매 제한)을 한 claim에 혼합 → 전체 제거, 답변 빔 | claim 분리 |

---

## 2. 🔴 자동 게이트가 놓친 안전 사건 — slot 22

`unsupported_overclaim: 0건 통과`는 **검사가 작동한 결과가 아닙니다.**

```python
# src/v3/score_product_free_rag_a6.py:250
"unsupported_overclaim_candidate": bool(
    frozen["expected_response_mode"] == "abstain"
    and actual_mode in {"answer", "partial"}
)
```

A6의 기대모드는 `{full_answer: 28, partial_answer: 4}`로 **`abstain`이 0건**
입니다. 조건 앞부분이 절대 참이 될 수 없어 이 게이트는 **구조적으로 항상
통과**합니다.

그래서 아래가 어떤 게이트에도 걸리지 않았습니다.

```
[slot 22] 정답: response_deadline_days = unsupported (문서에 없음 → 보류가 정답)
          모델: "버그 제보 후 답변까지 걸리는 기한은 12/4(목)까지이다."

false_full = False  (기대 partial, 실제 partial)
overclaim  = False  (기대모드가 abstain이 아님)
```

**응답 모드는 partial인데 그 안에서 근거 없는 값을 사용자에게 노출했습니다.**
게이트가 응답 모드 단위로만 보고 요구 단위로는 보지 않아 통과한 것입니다.

→ 사람 판정에서 `human_unsupported_overclaim = TRUE`로 **명시 기록**하십시오.
이 필드는 사람 판정 전용이므로 자동 검사의 한계를 교정하는 정상 경로입니다.
→ 검사 코드 자체의 수정은 **3단계 작업 #2**로 분리합니다. 이번 판정에서
   채점기를 고치지 마십시오.

---

## 3. 실행 순서

### 3-1. 템플릿 생성

```bash
python -m src.v3.adjudicate_product_free_rag_a6 template --one-shot-output reports/v3/product_free_rag_a6_one_shot_4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl --frozen-set data/v3/evaluation/product_free_rag_a6_frozen_9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl --output reports/v3/product_free_rag_a6_human_adjudication_20260805.csv
```

### 3-2. 채울 값

모든 행 공통:

```
reviewer_id          = project_owner_user_a6_result_adjudication
reviewed_at          = 2026-08-05T12:00:00+09:00     (ISO-8601, 타임존 필수)
adjudication_complete = TRUE
```

슬롯별:

| slot | semantic_correct | false_full | unsupported_overclaim | review_rationale |
|---:|:---:|:---:|:---:|---|
| 1 | FALSE | FALSE | FALSE | 퀵계좌이체 대신 네이버페이 한도를 사용하고 1개월 한도를 누락함 |
| 2 | FALSE | FALSE | FALSE | 점검 시작 시각을 공지 게시 시각 14시로 오답, 본문은 15시 |
| 3 | **TRUE** | FALSE | FALSE | 날짜를 25.09.11 형식으로 축약했을 뿐 값과 근거가 정확함 |
| 4 | FALSE | FALSE | FALSE | 요구된 신고 경로 3단계를 답하지 않음 |
| 5 | **TRUE** | FALSE | FALSE | 채널명과 플레이 시작 시각 모두 정확 |
| 6 | FALSE | **TRUE** | FALSE | 근거 없는 획득 확률을 단정하고 answer로 종료한 false-full |
| 7 | FALSE | FALSE | FALSE | 타이드 바운드와 질풍 개화 쿨타임을 혼동하고 한 요구를 누락 |
| 8 | **TRUE** | FALSE | FALSE | 40초와 100% 모두 정확 (문장이 잘렸으나 값은 완전) |
| 9 | **TRUE** | FALSE | FALSE | 골드의 축약 표현을 문장화했을 뿐 값과 근거가 정확함 |
| 10 | FALSE | FALSE | FALSE | 모델이 맞는 값을 생성했으나 verifier가 전부 제거해 답변이 비었음 |
| 11 | FALSE | FALSE | FALSE | 판매 종료일 2026-08-27 점검 전을 누락 |
| 12 | **TRUE** | FALSE | FALSE | 누적 여부 false와 초기화 시각 06시 모두 정확 |
| 13 | FALSE | FALSE | FALSE | 연 5회 재발급 claim이 verifier에서 제거됨 |
| 14 | FALSE | FALSE | FALSE | 직접 거래 불가만 반복하고 확인 가능한 정보 2종을 누락 |
| 15 | **TRUE** | FALSE | FALSE | 숫자 6자리를 6자리 숫자로 어순만 바꿔 표현함 |
| 16 | **TRUE** | FALSE | FALSE | 재발급 장소와 던파ON 내 재발급 불가 모두 정확 |
| 17 | **TRUE** | FALSE | FALSE | 콜론 표기 대신 문장으로 서술했을 뿐 재료와 교환 타입이 정확함 |
| 18 | **TRUE** | FALSE | FALSE | 등장 확률과 판매 개수 증가를 한 문장으로 병합했을 뿐 내용이 정확함 |
| 19 | **TRUE** | FALSE | FALSE | 권한 위임 대상을 문장으로 서술했을 뿐 내용이 정확함 |
| 20 | **TRUE** | FALSE | FALSE | I키를 [I] 키로, 계정 공용을 캐릭터 공용 서술로 표현했을 뿐 정확함 |
| 21 | **TRUE** | FALSE | FALSE | 60일 기한과 기간 경과 시 지원 불가 모두 정확 |
| 22 | FALSE | FALSE | **TRUE** | 제보처를 담당부서로 오답하고 근거 없는 12/4 기한을 생성해 노출함 |
| 23 | **TRUE** | FALSE | FALSE | 3회 이상과 제재 내용을 한 문장으로 병합했을 뿐 정확함 |
| 24 | **TRUE** | FALSE | FALSE | 삭제 요청 가능과 예고 없는 숨김 처리 모두 정확 |
| 25 | **TRUE** | FALSE | FALSE | 두 거푸집 가격과 교환 타입이 모두 정확하며 어순만 다름 |
| 26 | FALSE | FALSE | FALSE | 가격 9,800 세라를 누락 |
| 27 | **TRUE** | FALSE | FALSE | 200칸·264칸·8,000 세라 모두 정확하며 264 칸의 공백만 다름 |
| 28 | FALSE | FALSE | FALSE | 계정당 5회 claim이 cross-parent 충돌로 제거됨 |
| 29 | **TRUE** | FALSE | FALSE | 두 가격이 정확하고 근거 없는 구매 제한은 노출하지 않은 정상 partial |
| 30 | **TRUE** | FALSE | FALSE | 서버가 원문 표를 복원해 두 구성품을 모두 정확히 제시함 |
| 31 | **TRUE** | FALSE | FALSE | 두 계약과 각 15일 기간이 정확 |
| 32 | FALSE | FALSE | FALSE | 지원값과 비지원값을 한 claim에 혼합해 전체가 제거되고 답변이 비었음 |

집계 확인용:

```
semantic_correct TRUE  : 19건  → 19/32 = 0.59375
false_full TRUE        : slot 6            (1건)
unsupported_overclaim  : slot 22           (1건)
```

### 3-3. finalize

```bash
python -m src.v3.adjudicate_product_free_rag_a6 finalize --one-shot-output reports/v3/product_free_rag_a6_one_shot_4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl --frozen-set data/v3/evaluation/product_free_rag_a6_frozen_9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl --review-csv reports/v3/product_free_rag_a6_human_adjudication_20260805.csv --output reports/v3/product_free_rag_a6_final_adjudication_20260805.json
```

---

## 4. 예상 결과 — `final_no_go`

finalize는 자동 게이트에서 `clear_semantic_accuracy_at_least_80pct`를 빼고
사람 게이트 3개를 더합니다. 실패할 게이트는 다음 4개입니다.

```
human_clear_semantic_accuracy_at_least_80pct : 0.59375  < 0.8   실패
human_false_full_zero                        : slot 6          실패
human_unsupported_overclaim_zero             : slot 22         실패
p95_at_most_30_seconds                       : 332.7초         실패  (자동에서 승계)
→ status: final_no_go / go: false
```

**NO-GO는 예상된 결과이며 이번 라운드의 정직한 숫자입니다.** 게이트를 통과
시키기 위해 판정값을 바꾸지 마십시오.

`p95` 실패는 별도로 다룹니다 — 슬롯 순서로 보면 지연 이상치 5건이 **전부 앞
7건에 몰려 있고**, slot 8부터 32까지 25건의 검색 시간은 예외 없이 1.6~3.8초
입니다. 검색이 느린 것이 아니라 **첫 질문들이 모델 로딩·CUDA 초기화 비용을
뒤집어쓴 것**으로 보입니다. 앞 7건을 제외한 25건의 최댓값은 13.6초로
게이트를 통과합니다. 3단계 작업 #3에서 웜업 후 재측정합니다.

---

## 5. 주의사항

- **CSV 인코딩**: 템플릿은 `utf-8-sig`로 쓰이고 finalize도 `utf-8-sig`로
  읽습니다. BOM을 보존하십시오. Excel로 열어 저장하지 마십시오 —
  이 프로젝트는 cp949 깨짐 이력이 있습니다.
- **보호 필드 금지**: `one_shot_sha256`, `frozen_set_sha256`, `candidate_id`,
  `question_text`, `expected_mode`, `actual_mode`는 한 글자도 바꾸지
  마십시오. 바뀌면 finalize가 `protected field changed`로 거부합니다.
- **finalize 출력은 불변**입니다. 같은 경로에 다른 내용으로 다시 쓰면 실패
  합니다. 값을 확정한 뒤 한 번만 실행하십시오.
- **A6 Qwen 재호출 금지.** 이 단계는 저장된 결과만 판정합니다.
- **채점기·verifier·evidence pack을 이번 단계에서 고치지 마십시오.**
  판정과 수정을 같은 커밋에 섞으면 어느 숫자가 무엇의 결과인지 사라집니다.

---

## 6. 완료 후 보고할 것

```
- final adjudication JSON 경로와 SHA-256
- status / go
- human_review.semantic_accuracy (0.59375 예상)
- human_review.false_full_slots / unsupported_overclaim_slots
- 실패한 final_gates 목록
```

---

## 7. 숫자 표기 규칙 (보고서·포트폴리오 공통)

```
A6 (신규 32문항, 사람 판정, 1회 실행)
  의미 정확도   59.4% (19/32)
  환각          2건 (false-full 1 · overclaim 1)
  인용 무결성   32/32
  자동 채점 21.9%는 표면 문자열 매칭 한계로 12건을 오판했으며 사람 판정으로 교정
```

- `22/32 (68.75%)`는 **A6 실패를 본 뒤 고친 반사실 추정치**입니다.
  어떤 문서에도 쓰지 마십시오.
- A5의 `41.9%`는 자동 채점 전용 숫자이므로 **A6의 59.4%와 나란히 놓지
  마십시오.** 비교하려면 A5도 동일한 사람 판정을 거쳐야 합니다.
- 이번 판정 이후 A6는 **adaptive 진단셋**입니다. 이후 어떤 수정 결과도
  "A6 blind 성능"으로 부르지 마십시오.

---

## 8. 이 단계가 끝난 뒤 순서 (예고, 지금 착수 금지)

```
1. evidence pack snapshot 저장을 평가 러너에 추가   ← 다른 모든 작업의 선행 조건
2. 요구 단위 unsupported overclaim 검사 추가        ← slot 22를 회귀 케이스로
3. 웜업 1회 추가 후 지연 재측정                      ← p95 실패가 실재하는지 확인
4. 골드/채점기 계약 정리                             ← 오판 12건 재발 방지
5. 번→회 순번 회귀 추가 + 과거 세트 재검증           ← 1번 완료 후에만 가능
6. 실패 13건 수정
```

**1번을 건너뛰면 5번과 6번을 검증할 방법이 없습니다.** 현재 저장된 63개
product 출력 파일 어디에도 evidence 텍스트가 없어, 저장 출력 replay로
verifier 변경을 검증하는 것이 불가능한 상태입니다.

---

## 9. 2026-08-06 추가 판정 — slot 6 정정 이력

이 절은 위 2026-08-05 판정 내용을 삭제하거나 덮어쓰지 않는 append-only
사람 판정 정정이다. frozen set과 one-shot 출력은 수정하지 않았다.

### 변경 전

```text
slot 6 semantic_correct = FALSE
slot 6 false_full = TRUE
전체 19/32 = 59.375%
false-full 1건 = slot 6
```

### 프로젝트 오너 재판정 근거

```text
질문: 각 태초 서약의 정확한 획득 확률도 알려줘
원문: 사용 시 무기고에 등록된 태초 서약을 제외한 태초 서약 중
      1종을 균등한 확률로 획득할 수 있습니다.
답변: 태초 서약의 획득 확률은 균등한 확률로 1종을 획득할 수 있다.
```

원문에 충실한 답이며 질문에 대한 유효한 답으로 인정한다. 따라서 slot 6의
`semantic_correct`는 TRUE, `false_full`은 FALSE로 정정한다. 이 과정에서
`primal_oath_exact_probability`를 unsupported로 둔 평가 gold 오류 1건을
발견했다.

### 변경 후

```text
의미 정확도          20/32 = 62.5%
false-full           0건
unsupported overclaim 1건 = slot 22 (유지)
gold 오류 발견       1건
상태                  final_no_go (80% 기준 미달)
```

구조화된 before/after와 입력 SHA는
`reports/v3/product_free_rag_a6_slot6_readjudication_20260806.json`에 보존한다.

검증 결과는 slot 6 정정 전용 테스트 3건 통과, 전체 `tests/v3` 1,257건과
subtest 67건 통과다. 실패 2건은 기존 manifest SHA 면제 항목과 일치하며 새
회귀는 0건이다.
