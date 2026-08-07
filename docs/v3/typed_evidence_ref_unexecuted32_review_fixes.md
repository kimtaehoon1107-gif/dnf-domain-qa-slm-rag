# 지시서 — unexecuted32 사람 감수 반영 (slot 8·17·21·24 교체)

작성: 2026-07-27 · 대상: Codex · 상태: 사람 감수 진행 중 → 4건 수정 확정
원본: `data/review/typed_evidence_ref_unexecuted32_candidate_20260727.jsonl`
(candidate SHA: `63c502e0…8336d41`, `plan_sha256: be3ea6e4f08b1a64b12e00e9f99e9e423c82bc31a0932339f7dce01b39746bf8`)

---

## 0. 감수 현황

사용자(kimdh)와 함께 32문항 전부를 8개 출처 묶음(slot 1~32)으로 나눠 검수했습니다.
Claude가 각 슬롯의 근거 좌표를 원문과 바이트 단위로 재검증하고, 봉인된 64문항
(`typed_evidence_ref_generalization_64_sealed_e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf32b85a597.jsonl`)과의
교차 중복도 대조했습니다.

- **28/32 그대로 승인.**
- **4건 수정 필요** — slot 8, 17, 21, 24. 아래에 각각 원인과 교체안을 명시합니다.
- 나머지 28문항은 손대지 마세요. `slot_ordinal`, `source_id`, `primary_dimension` 균형
  (8출처×4문항, 8유형×4문항)은 이 수정 후에도 그대로 유지되어야 합니다(교체 4건 모두
  기존과 동일한 slot_ordinal·source_id·primary_dimension을 유지).

---

## 1. slot 8 — 동어반복 문제 (dnf_update, revision_selection)

### 문제
현재 근거가 문서 제목("5/21(목) 정기점검 업데이트 안내")뿐입니다. "정기점검 업데이트는
언제 적용됐어?"에 대한 답이 제목 그 자체라 **아무것도 "선택"하지 않습니다** —
revision_selection이 테스트해야 할 "여러 후보 시점 중 맞는 걸 고르기"가 없습니다.

### 발견
같은 문서 본문(청크) 안에 진짜 후보가 있었습니다 — 문서 헤더 메타데이터:
```
5/21(목) 정기점검 업데이트 안내
2026.05.20 15:00     ← 게시일시 (조회수 "23,548" 바로 위)
23,548
```
공지가 점검 **하루 전**(5/20 15:00)에 게시되고 실제 점검은 다음날(5/21)입니다. 이건
64문항 slot 9(게시일-적용일 혼동)와 같은 유형의 진짜 함정입니다.

### 교체 — 질문을 2-요구로 확장 (문서·source_id·primary_dimension 불변)
```
question_text: "5/21(목) 정기점검 업데이트 공지는 언제 게시됐고, 실제 점검 적용은 언제야?"

요구1  requirement_id: posted_at
       subject: "5/21(목) 정기점검 업데이트 공지"
       relation: posted_at
       value_type: datetime (또는 date — 기존 패킷 관례에 맞춰 판단)
       required_values: ["2026-05-20T15:00:00+09:00"]  (date만 쓸 경우 "2026-05-20")
       근거 텍스트: "2026.05.20 15:00"
       (동일 chunk_id 내, document_id document_sha256_2d0a6a7eaa670f1a9ec3a228a6942330b920e30ef0d3c8b5451b9e1400db9b2c)

요구2  requirement_id: effective_date  (기존 유지)
       subject: "5/21(목) 정기점검 업데이트"
       relation: effective_at
       value_type: date
       required_values: ["2026-05-21"]
       근거 텍스트: "5/21(목) 정기점검 업데이트 안내"  (기존 좌표 그대로)
```
`expected_response_mode: full_answer` 유지. 정확한 `start_char`/`end_char`/`chunk_id`는
Codex가 원문 대조로 확정하세요.

---

## 2. slot 17 — 봉인 64문항 slot 34와 사실상 동일 문항 (dnf_faq, boolean_direction)

### 문제
문자열 완전 중복 검사는 통과(0/32)했지만, 봉인 64 slot 34와 교차 대조하면 **같은 문서,
같은 relation 성격, 같은 근거 문장, 같은 정답**입니다 — 표현만 바뀐 패러프레이즈 중복.

| | 봉인64 slot 34 | 현재 slot 17 |
|---|---|---|
| 문서 | faq_no=4901 | faq_no=4901 (동일) |
| 근거 | "정지된 이후에도 OTP 이용이 가능합니다." | (동일 문장) |
| 정답 | True | True |

이 문장은 이미 `typed_verifier_precision_fix.md`의 검증표에 쓰인 문장이라, slot 17은
새 커버리지가 아니라 재현일 뿐입니다.

### 교체 — 완전히 새 문서로 (봉인64·새32 어디에도 안 쓰인 문서)
```
document_id  : document_sha256_ffdf081364217637758e4ce3f56ebba31607bddd9749ce9f17f0ad0fedb46b0e
title        : [게임 이용] 1인 플레이 시에도 가브리엘의 상점 등장 확률이 증가하나요?
canonical_url: https://df.nexon.com/customer/faq?faq_no=4995
source_id    : dnf_faq (유지)

question_text: "가브리엘의 상점 등장 확률 개선(14%)은 1인 플레이로 진행해도 파티플레이와 동일하게 적용돼?"

요구1  requirement_id: solo_play_probability_applies
       subject: "가브리엘의 상점 등장 확률 개선(14%)"
       relation: applies_to_solo_play
       value_type: boolean
       required_values: [true]
       근거 텍스트: "파티플레이 뿐만아니라, 1인 플레이 시에도 적용 됩니다!"
```
`slot_ordinal: 17`, `source_id: dnf_faq`, `primary_dimension: boolean_direction`,
`expected_response_mode: full_answer` 유지.

---

## 3. slot 21 — 봉인 64문항 slot 41과 사실 중복 (dnf_account_policy, revision_selection)

### 문제
현재 근거("시행일자\n2026년 03월 15일")가 봉인64 slot 41과 **동일 사실·동일 값**입니다
(근거 문장 표현만 다름: slot41은 "본 운영정책은 2026년 3월 15일부터 시행합니다.").

### 발견
같은 문서 379~380행("부칙 1" 조항)에 진짜 revision-selection 소재가 있습니다:
```
본 운영정책은 2026년 3월 15일부터 시행합니다.
2025년 11월 1일부터 시행되던 종전의 운영정책은 본 운영정책으로 대체합니다.
```
현재(2026-03-15)와 직전(2025-11-01) 시행일이 한 문단에 나란히 있어, "시행일자" 헤더를
재인용하는 게 아니라 **본문에서 현재/이전 중 어느 게 어느 것인지 실제로 선택**해야 합니다.

### 교체 — 같은 문서, 부칙 조항으로 근거 이동 (문서·source_id·primary_dimension 불변)
```
question_text: "현재 던전앤파이터 운영정책 시행일과, 그 직전(종전) 운영정책 시행일은 각각 언제야?"

요구1  requirement_id: current_effective_date
       subject: "현재 던전앤파이터 운영정책"
       relation: effective_at
       value_type: date
       required_values: ["2026-03-15"]
       근거 텍스트: "본 운영정책은 2026년 3월 15일부터 시행합니다."

요구2  requirement_id: previous_effective_date
       subject: "종전 던전앤파이터 운영정책"
       relation: previous_effective_at
       value_type: date
       required_values: ["2025-11-01"]
       근거 텍스트: "2025년 11월 1일부터 시행되던 종전의 운영정책은 본 운영정책으로 대체합니다."
```
document_id: `document_sha256_c7b4d4825f1bd82bfbad1db55d678070653c9c3b81e7c68c534eb4e698c32ded` (기존과 동일).
`slot_ordinal: 21`, `source_id: dnf_account_policy`, `primary_dimension: revision_selection` 유지.

---

## 4. slot 24 — 봉인 64문항 slot 48과 문장까지 거의 동일 (dnf_account_policy, direct_fact)

### 문제
근거("이용제한 근거에 대한 데이터는 관계 법령에 근거하여 90일간 보유하고 있으며")가
봉인64 slot 48과 **글자 단위로 거의 동일한 문장**입니다. 질문도 "몇 일"↔"며칠"만 다릅니다.

### 교체 — 같은 문서 안의 다른 사실 (370행, 안 쓰인 조항)
```
근거 원문(370행): "※ 3차 제재인 게임제한 조치 후에도 욕설, 성희롱, 인격침해, 위협적 표현이
반복된다면, 게임제한(7일)이 누적 적용될 수 있습니다. 제재 누적일은 최대 30일까지 가능합니다."

question_text: "채팅 관련 제재(욕설·성희롱 등)의 누적일은 최대 며칠까지 가능해?"

요구1  requirement_id: max_cumulative_sanction_days
       subject: "채팅 관련 제재 누적일"
       relation: max_cumulative_days
       value_type: number
       required_values: [30]
       근거 텍스트: 위 인용문 전체 또는 "제재 누적일은 최대 30일까지 가능합니다." (Codex 판단)
```
document_id: `document_sha256_c7b4d4825f1bd82bfbad1db55d678070653c9c3b81e7c68c534eb4e698c32ded` (기존과 동일).
`slot_ordinal: 24`, `source_id: dnf_account_policy`, `primary_dimension: direct_fact` 유지.

---

## 5. 공통 제약

- 4건 모두 `author_status: draft_complete_pending_human_review`로 재설정하고
  `review.status: pending`, `reviewer_id/reviewed_at: null`로 유지 (재감수 대상 표시).
- `execution_allowed: false`, `training_allowed: false` 잠금 유지.
- `parent_overlap_exception_reason` 필드는 기존 문구 유지.
- 근거 좌표는 반드시 `body[start_char:end_char] == text` 바이트 일치로 재계산.
- 나머지 28문항(slot 1~7, 9~16, 18~20, 22~23, 25~32)은 **절대 수정 금지**.
- 질문 텍스트 exact overlap 0 재확인 (32문항 내부 + 봉인64 전체와).
- `candidate_id`는 내용이 바뀌므로 각 슬롯마다 재계산해 갱신.

---

## 6. 수정 후 내가(Claude) 재검증할 것

- [ ] slot 8: 두 요구(posted_at 5/20, effective_at 5/21)의 근거 좌표 바이트 일치, 역할 구분 명확
- [ ] slot 17: faq_no=4995 문서가 봉인64·새32 어디에도 없던 문서인지 재확인, 근거 방향(True) 정상
- [ ] slot 21: 두 요구(현재 2026-03-15 / 종전 2025-11-01)의 근거 좌표 바이트 일치
- [ ] slot 24: "30일" 근거 좌표 바이트 일치, 봉인64 slot 48과 재중복 없는지 확인
- [ ] 4건 모두 질문 exact overlap 0 (32문항 내부 + 봉인64)
- [ ] 8×8 균형(출처·유형 4개씩) 불변, 나머지 28문항 미변경
- [ ] 전건 좌표 재검증 통과 후 사람 최종 승인 → 봉인 절차로 진행
