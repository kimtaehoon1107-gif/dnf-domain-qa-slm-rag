# 지시서 — untouched32 slot 11 교체 (레미디아 여프료시카 사실 중복)

작성: 2026-07-28 · 대상: Codex · 상태: 사람 감수 완료 → 교체 확정
원본: `data/review/typed_evidence_ref_untouched32_candidate_20260728.jsonl`
(candidate SHA: `ab8c4c537b8161c02c804358c6112db435ed298615b6bfc73a028f7526c389ca`)

---

## 1. 문제

slot 11(dnf_event, multi_requirement)의 근거가 "함께해요! 레미디아 여프료시카"
(`https://df.nexon.com/df/pg/priestdoll`)이고, weekly_reset_at="매주 목요일 06시",
deletion_at="2026-07-30T06:00:00+09:00"입니다.

이 문서·relation·정답값이 이미 봉인·실행된 `new_claim32`
(= `data/review/typed_evidence_ref_unexecuted32_candidate_20260727.jsonl`,
SHA `fe76f10a9610d6e2ba923f14e6c2df967e0097bffb0f44b773e0a97228ae6590`)의 slot 11과
**문서·relation·정답값까지 완전히 동일**합니다(질문 문장 표현만 다름). 문자열 완전 중복
검사로는 안 걸리지만 사실 단위로는 세 번째 반복(sealed64 관련은 아니고 new_claim32/
unexecuted32와의 중복)입니다. `new_claim32`가 왜 미수정 상태로 봉인·실행됐는지는 별도로
`docs/v3/new_claim32_process_integrity_inquiry.md`에서 확인 요청 중이지만, 이 중복 자체는
그 답변과 무관하게 확정된 사실이라 지금 바로 교체합니다.

---

## 2. 교체안 — dnf_event 소스 내 미사용 문서로

```
document_id  : document_sha256_d59f3c4278301e5fe7a5a25fa132c9295f4eb699be7a8ef6c0067f7b84b31a87
title        : 여름맞이 7일간의 여정
canonical_url: https://df.nexon.com/pg/summersevengift
source_id    : dnf_event (유지)
primary_dimension: multi_requirement (유지)

question_text: "여름맞이 7일간의 여정 이벤트의 하루 기준(초기화 시각)과 보상 우편 보관 기간은 각각 며칠/몇 시야?"

요구1  requirement_id: daily_boundary_at
       subject: "여름맞이 7일간의 여정"
       relation: daily_boundary_at
       value_type: text
       required_values: ["매일 오전 06시 - 다음날 오전 06시"]
       근거 텍스트: "본 이벤트의 하루 기준은 매일 오전 06시 - 다음날 오전 06시입니다."

요구2  requirement_id: mail_retention_days
       subject: "여름맞이 7일간의 여정 보상"
       relation: mail_retention_days
       value_type: number
       required_values: [15]
       근거 텍스트: "게임 접속 후 [보상받기]를 클릭하면 보상을 받을 수 있으며, 지급된 보상은 우편함에서 확인 가능합니다. (우편 보관 기간: 15일)"
       (정확한 인용 범위는 Codex가 원문 대조로 확정 — "(우편 보관 기간: 15일)" 문구가
       핵심이며, 앞 문장과 합쳐서 인용해도 무방)
```

이 문서는 `sealed64`, `new_claim32`, `untouched32`의 다른 어떤 슬롯에서도 쓰인 적이
없습니다(확인 완료).

---

## 3. 공통 제약

- `slot_ordinal: 11`, `source_id: dnf_event`, `primary_dimension: multi_requirement`,
  `expected_response_mode: full_answer` 유지.
- `author_status: draft_complete_pending_human_review`로 재설정, `review.status: pending`
  유지.
- `execution_allowed: false`, `training_allowed: false` 잠금 유지.
- `parent_overlap_exception_reason` 필드는 기존 문구 유지.
- 근거 좌표는 `body[start_char:end_char] == text` 바이트 일치로 재계산.
- 나머지 31문항은 절대 수정 금지.
- `candidate_id`는 내용이 바뀌므로 재계산해 갱신.
- 교체 후 질문 exact overlap 0 재확인 (32문항 내부 + sealed64 + new_claim32).

---

## 4. 교체 후 내가(Claude) 재검증할 것

- [ ] 두 요구(daily_boundary_at, mail_retention_days)의 근거 좌표 바이트 일치
- [ ] 이 문서가 sealed64·new_claim32·untouched32 어디에도 안 쓰였는지 재확인
- [ ] 질문 exact overlap 0
- [ ] 8×8 균형 불변, 나머지 31문항 미변경
- [ ] validator 재실행 PASS 확인
